"""Two defects found in the demo run: the writer's trailing revision notes reached the
section (DG4), and an 'error' verdict was reused after revision instead of re-checked
(DG8)."""

import copy
import os
import uuid

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402

from app.agents.citation_link_agent import CitationLinkResult  # noqa: E402
from app.schemas.fulltext import ClaimVerification  # noqa: E402
from app.services.writing import _strip_trailing_revision_notes  # noqa: E402
from tests.test_writing_gated_loop import (  # noqa: E402
    JONES_CHUNK_TEXT,
    LINKS_PASS_1,
    SMITH_CHUNK_TEXT,
    _completion,
    _seed_world,
)

BODY = "Tutoring boosts outcomes (Smith, 2020). Tutoring reduces costs (Jones, 2019)."


def test_trailing_revision_notes_are_stripped():
    text = (
        BODY + "\n\n---\n\nNotes on revisions:\n"
        "- The Mao sentence was trimmed\n- The Smith sentence is unchanged"
    )
    assert _strip_trailing_revision_notes(text) == BODY


def test_notes_header_without_rule_is_stripped():
    text = BODY + "\n\nNotes on the revision:\n- One sentence was shortened"
    assert _strip_trailing_revision_notes(text) == BODY


def test_rule_followed_by_bullets_only_is_stripped():
    assert _strip_trailing_revision_notes(BODY + "\n---\n- kept Smith\n- trimmed Jones") == BODY


def test_notes_on_inside_a_sentence_is_kept():
    text = BODY + "\n\nNotes on the trial design vary across studies (Smith, 2020)."
    assert _strip_trailing_revision_notes(text) == text


def test_mid_text_rule_without_notes_is_kept():
    text = "First paragraph (Smith, 2020).\n\n---\n\nSecond paragraph (Jones, 2019)."
    assert _strip_trailing_revision_notes(text) == text


def test_real_cited_last_paragraph_under_notes_on_is_kept():
    text = BODY + "\n\nNotes on measurement: studies used tests (Jones, 2019). More text."
    assert _strip_trailing_revision_notes(text) == text


def test_leading_note_on_paragraph_is_kept():
    text = "Note on terminology: we use tutoring broadly (Smith, 2020).\n\n" + BODY
    assert _strip_trailing_revision_notes(text) == text


def test_text_without_notes_is_unchanged():
    assert _strip_trailing_revision_notes(BODY) == BODY


FIRST = "Tutoring boosts outcomes (Smith, 2020). Tutoring reduces costs (Jones, 2019)."
REVISED = FIRST


class _ErrorThenAgent:
    """Smith is always verified; Jones returns the given statuses in order."""

    def __init__(self, jones_statuses):
        self.jones_statuses = list(jones_statuses)
        self.jones_calls = 0
        self.calls: list[str] = []

    async def run(self, prompt, deps=None):
        self.calls.append(prompt)
        if "Claim to verify: Tutoring boosts outcomes" in prompt:
            status, quote = "verified", SMITH_CHUNK_TEXT
        else:
            status = self.jones_statuses[min(self.jones_calls, len(self.jones_statuses) - 1)]
            self.jones_calls += 1
            quote = JONES_CHUNK_TEXT if status == "verified" else None
        return type(
            "R",
            (),
            {
                "output": ClaimVerification(
                    claim_text="placeholder",
                    paper_id=uuid.uuid4(),
                    status=status,
                    evidence_quote=quote,
                    explanation="Checked.",
                )
            },
        )()


async def _run(db_session, agent):
    from app.models.analysis_job import JobType
    from app.services.writing import generate_section
    from tests.claim_verification_fixtures import make_session_factory, seed_draft, seed_job

    user, project = await _seed_world(db_session)
    draft = await seed_draft(db_session, project, user, {"type": "doc", "content": []})
    job = await seed_job(db_session, project, JobType.writing)

    async def fake_call(system_prompt, user_prompt):
        return _completion(REVISED if "REVISION REQUIRED" in user_prompt else FIRST)

    factory, engine = make_session_factory()
    with (
        patch(
            "app.agents.writing_rules_agent.merge_writing_rules",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ),
        patch("app.services.writing.call_deepseek", new=fake_call),
        patch(
            "app.services.writing.build_citation_link_map",
            new_callable=AsyncMock,
            side_effect=lambda *a, **k: CitationLinkResult(
                links=copy.deepcopy(LINKS_PASS_1), provenance=None
            ),
        ),
        patch(
            "app.agents.claim_verification_agent.get_claim_verification_agent",
            return_value=agent,
        ),
        patch("app.services.writing.THIN_SECTION_CITED_SENTENCE_MINIMUM", 1),
    ):
        await generate_section(
            draft=draft,
            section_type="methods",
            context=None,
            job_id=job.id,
            session_factory=factory,
        )
    await engine.dispose()
    await db_session.refresh(job)
    return job


def _jones_calls(agent):
    return sum("Claim to verify: Tutoring reduces costs" in p for p in agent.calls)


@pytest.mark.asyncio
async def test_error_verdict_is_reverified_after_revision(db_session):
    agent = _ErrorThenAgent(["error", "verified"])
    job = await _run(db_session, agent)
    assert job.status.value == "completed", job.error
    assert _jones_calls(agent) == 2
    assert "Tutoring reduces costs" in job.result["content"]


@pytest.mark.asyncio
async def test_repeated_error_is_removed_once(db_session):
    agent = _ErrorThenAgent(["error"])
    job = await _run(db_session, agent)
    assert job.status.value == "completed", job.error
    assert _jones_calls(agent) == 2
    assert "Tutoring reduces costs" not in job.result["content"]
    assert "Tutoring boosts outcomes" in job.result["content"]
    rows = job.result["gate_log"]["attempts"][0]["finalize"]["sentences"]
    assert sum(r["fate"] == "removed" for r in rows) == 1
