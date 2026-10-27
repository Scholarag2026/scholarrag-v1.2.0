"""The drafting gate log written into the section job result.

The log is built after the calls it describes and sent to no model; these tests run the
same scenarios as the gated-loop tests and read ``job.result["gate_log"]``.
"""

import json
import os
import re
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402

from app.agents.citation_link_agent import CitationLinkResult  # noqa: E402
from app.services.fulltext import section_sentence_texts  # noqa: E402
from tests.test_writing_gated_loop import (  # noqa: E402
    FIRST_TEXT,
    LINKS_PASS_1,
    LINKS_PASS_2,
    REGEN_LINKS_2,
    REGEN_PROVENANCE_1,
    REGEN_PROVENANCE_2,
    REGEN_TEXT_1,
    REGEN_TEXT_2,
    REVISED_TEXT,
    _AlwaysVerifiedAgent,
    _completion,
    _RoutingVerifyAgent,
    _seed_world,
)
from tests.test_writing_request_identity import GOLDEN, capture_write_calls  # noqa: E402

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "demo"
    / "tests"
    / "fixtures"
    / "gate_log_writing_result.json"
)

THREE_PARAGRAPHS = (
    "Tutoring boosts outcomes (Smith, 2020).\n\n"
    "Tutoring raises attendance (Smith, 2020).\n\n"
    "Tutoring lifts engagement (Smith, 2020)."
)


def _three_links() -> list[dict]:
    return [
        {
            "paragraph_index": i,
            "sentence": s,
            "keys": ["smith_2020"],
            "citation_text": "(Smith, 2020)",
            "proposition": s.split(" (")[0],
        }
        for i, s in enumerate(THREE_PARAGRAPHS.split("\n\n"))
    ]


async def _run(db_session, *, texts, link_side_effect, verify_agent=None, **kwargs):
    from app.models.analysis_job import JobType
    from app.services.writing import generate_section
    from tests.claim_verification_fixtures import make_session_factory, seed_draft, seed_job

    user, project = await _seed_world(db_session)
    draft = await seed_draft(db_session, project, user, {"type": "doc", "content": []})
    job = await seed_job(db_session, project, JobType.writing)
    calls = {"n": 0}

    async def fake_call_deepseek(system_prompt, user_prompt):
        calls["n"] += 1
        return _completion(texts(calls["n"], user_prompt))

    patches = [
        patch(
            "app.agents.writing_rules_agent.merge_writing_rules",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ),
        patch("app.services.writing.call_deepseek", new=fake_call_deepseek),
        patch(
            "app.services.writing.build_citation_link_map",
            new_callable=AsyncMock,
            side_effect=link_side_effect,
        ),
    ]
    if verify_agent is not None:
        patches.append(
            patch(
                "app.agents.claim_verification_agent.get_claim_verification_agent",
                return_value=verify_agent,
            )
        )
    factory, engine = make_session_factory()
    for p in patches:
        p.start()
    try:
        await generate_section(
            draft=draft,
            section_type="methods",
            context=None,
            job_id=job.id,
            session_factory=factory,
            **kwargs,
        )
    finally:
        for p in patches:
            p.stop()
    await engine.dispose()
    await db_session.refresh(job)
    assert job.status.value == "completed", job.error
    return job.result


async def _revised_scenario(db_session):
    return await _run(
        db_session,
        texts=lambda n, up: FIRST_TEXT if "REVISION REQUIRED" not in up else REVISED_TEXT,
        link_side_effect=[
            CitationLinkResult(links=LINKS_PASS_1, provenance=None),
            CitationLinkResult(links=LINKS_PASS_2, provenance=None),
            CitationLinkResult(links=LINKS_PASS_1, provenance=None),
        ],
        verify_agent=_RoutingVerifyAgent(),
    )


@pytest.mark.asyncio
async def test_revised_section_logs_first_pass_revision_and_fates(db_session):
    result = await _revised_scenario(db_session)
    gl = result["gate_log"]
    assert gl["schema_version"] == 1
    assert gl["kept_attempt"] == "first"
    assert [a["attempt"] for a in gl["attempts"]] == ["first", "second"]
    assert [a["kept"] for a in gl["attempts"]] == [True, False]

    first, second = gl["attempts"]
    assert first["first_pass"]["sentences"] == [
        "Tutoring boosts outcomes (Smith, 2020).",
        "Tutoring reduces costs (Jones, 2019).",
    ]
    assert [(c["key"], c["status"]) for c in first["first_pass"]["claims"]] == [
        ("smith_2020", "verified"),
        ("jones_2019", "unsupported"),
    ]
    revision = first["revision"]
    assert revision["triggers"] == ["unsupported"]
    assert revision["keep_verbatim"] == ["Tutoring boosts outcomes (Smith, 2020)."]
    assert revision["failed"] == [
        {
            "sentence": "Tutoring reduces costs (Jones, 2019).",
            "key": "jones_2019",
            "status": "unsupported",
        }
    ]
    assert revision["sentences"] == [
        "Tutoring boosts outcomes (Smith, 2020).",
        "Tutoring improves retention (Jones, 2019).",
    ]
    assert [c["reused"] for c in revision["claims"]] == [True, False]
    assert [f["fate"] for f in first["finalize"]["sentences"]] == ["kept", "kept"]

    assert second["revision"] is None
    fates = second["finalize"]["sentences"]
    assert [f["fate"] for f in fates] == ["kept", "removed"]
    assert fates[1]["rule"] == "unverified"

    assert "gate_log" not in result["loop_stats"]
    assert not any(k.startswith(("gate", "sentence_fates")) for k in result["loop_stats"])


@pytest.mark.asyncio
async def test_section_without_revision_logs_revision_none(db_session):
    result = await _run(
        db_session,
        texts=lambda n, up: THREE_PARAGRAPHS,
        link_side_effect=[CitationLinkResult(links=_three_links(), provenance=None)],
        verify_agent=_AlwaysVerifiedAgent(),
    )
    gl = result["gate_log"]
    assert len(gl["attempts"]) == 1
    attempt = gl["attempts"][0]
    assert attempt["revision"] is None
    assert [f["fate"] for f in attempt["finalize"]["sentences"]] == ["kept"] * 3
    assert result["loop_stats"]["loop_revised"] is False


@pytest.mark.asyncio
async def test_failed_revision_link_call_is_logged(db_session):
    result = await _run(
        db_session,
        texts=lambda n, up: FIRST_TEXT if "REVISION REQUIRED" not in up else REVISED_TEXT,
        link_side_effect=[
            CitationLinkResult(links=LINKS_PASS_1, provenance=None),
            RuntimeError("linker down"),
        ],
        verify_agent=_RoutingVerifyAgent(),
    )
    first = result["gate_log"]["attempts"][0]
    assert first["revision"]["link_map_failed"] is True
    assert first["revision"]["claims"] == []
    assert first["link_map_failed"] is True
    assert result["claim_report"] is None


@pytest.mark.asyncio
async def test_first_pass_link_failure_still_writes_the_log(db_session):
    result = await _run(
        db_session,
        texts=lambda n, up: FIRST_TEXT,
        link_side_effect=RuntimeError("linker down"),
    )
    first = result["gate_log"]["attempts"][0]
    assert first["first_pass"]["claims"] == []
    assert first["revision"] is None
    assert first["link_map_failed"] is True


@pytest.mark.asyncio
async def test_second_attempt_kept_is_marked(db_session):
    result = await _run(
        db_session,
        texts=lambda n, up: REGEN_TEXT_1 if n == 1 else REGEN_TEXT_2,
        link_side_effect=[
            CitationLinkResult(
                links=[],
                provenance=REGEN_PROVENANCE_1,
                uncited_sentences=[
                    {
                        "paragraph_index": 0,
                        "sentence": REGEN_TEXT_1,
                        "tag": "finding",
                    }
                ],
            ),
            CitationLinkResult(links=REGEN_LINKS_2, provenance=REGEN_PROVENANCE_2),
        ],
        verify_agent=_RoutingVerifyAgent(),
    )
    gl = result["gate_log"]
    assert gl["kept_attempt"] == "second"
    assert [a["kept"] for a in gl["attempts"]] == [False, True]


@pytest.mark.asyncio
async def test_length_trim_marks_trimmed_sentences(db_session):
    def drop_last_block(body, _maximum, link_list, uncited):
        kept = body.split("\n\n")[:-1]
        return (
            "\n\n".join(kept),
            [lk for lk in link_list if lk["paragraph_index"] < len(kept)],
            [u for u in uncited if u["paragraph_index"] < len(kept)],
            True,
        )

    with patch("app.services.writing._trim_body_to_hard_maximum", new=drop_last_block):
        result = await _run(
            db_session,
            texts=lambda n, up: THREE_PARAGRAPHS,
            link_side_effect=[CitationLinkResult(links=_three_links(), provenance=None)],
            verify_agent=_AlwaysVerifiedAgent(),
            target_words=4,
        )
    gl = result["gate_log"]
    kept = next(a for a in gl["attempts"] if a["kept"])
    fates = kept["finalize"]["sentences"]
    assert any(f["fate"] == "removed" and f["rule"] == "length_trimmed" for f in fates)
    for f in fates:
        if f["fate"] in ("kept", "changed"):
            assert f["delivered"] in result["content"]


@pytest.mark.asyncio
async def test_kept_fates_match_the_delivered_text(db_session):
    result = await _revised_scenario(db_session)
    gl = result["gate_log"]
    kept = next(a for a in gl["attempts"] if a["kept"])
    delivered = {
        f["delivered"] for f in kept["finalize"]["sentences"] if f["fate"] in ("kept", "changed")
    }
    assert delivered == set(section_sentence_texts(result["content"]))


@pytest.mark.asyncio
async def test_write_requests_unchanged_with_gate_logging(db_session):
    assert await capture_write_calls(db_session) == json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_gate_log_contract_fixture_is_current(db_session):
    if not FIXTURE.parent.parent.parent.exists():
        pytest.skip("demo/ is absent")
    result = await _revised_scenario(db_session)
    view = {
        key: result[key]
        for key in ("content", "citation_links", "uncited_sentences", "loop_stats", "gate_log")
    }
    view["provenance"] = {"length": result["provenance"].get("length", {})}
    view["claim_report"] = {
        "verifications": [{"status": v["status"]} for v in result["claim_report"]["verifications"]]
    }
    text = _UUID.sub("<uuid>", json.dumps(view, indent=2, ensure_ascii=False))
    if os.environ.get("GATE_LOG_RECORD_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text + "\n", encoding="utf-8")
        pytest.skip("fixture recorded")
    assert json.loads(text) == json.loads(FIXTURE.read_text(encoding="utf-8"))
