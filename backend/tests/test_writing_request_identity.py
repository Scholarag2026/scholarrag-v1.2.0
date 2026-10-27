"""Pins what the write job sends to the model, the citation linker and the verifier.

The scenario is the one in `test_gate_triggers_one_revision_and_reuses_unchanged_verdicts`
(generation, one revision, the regeneration backstop). Every request is captured in call
order and compared with a golden file recorded on the code before gate logging was added,
so later logging changes cannot alter a single request.
"""

import json
import os
import re
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402

from app.agents.citation_link_agent import CitationLinkResult  # noqa: E402
from tests.test_writing_gated_loop import (  # noqa: E402
    FIRST_TEXT,
    LINKS_PASS_1,
    LINKS_PASS_2,
    REVISED_TEXT,
    _completion,
    _RoutingVerifyAgent,
    _seed_world,
)

GOLDEN = Path(__file__).parent / "fixtures" / "writing_request_identity.json"
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _norm(text: str) -> str:
    return _UUID.sub("<uuid>", text)


async def capture_write_calls(db_session) -> dict:
    """Run the gated-loop scenario and return every request it made, in call order."""
    from app.models.analysis_job import JobType
    from app.services.writing import generate_section
    from tests.claim_verification_fixtures import make_session_factory, seed_draft, seed_job

    user, project = await _seed_world(db_session)
    draft = await seed_draft(db_session, project, user, {"type": "doc", "content": []})
    job = await seed_job(db_session, project, JobType.writing)

    verify_agent = _RoutingVerifyAgent()
    model_calls: list[dict] = []

    async def fake_call_deepseek(system_prompt, user_prompt):
        model_calls.append({"system": system_prompt, "user": user_prompt})
        return _completion(FIRST_TEXT if "REVISION REQUIRED" not in user_prompt else REVISED_TEXT)

    link_mock = AsyncMock(
        side_effect=[
            CitationLinkResult(links=LINKS_PASS_1, provenance=None),
            CitationLinkResult(links=LINKS_PASS_2, provenance=None),
            CitationLinkResult(links=LINKS_PASS_1, provenance=None),
        ]
    )
    factory, engine = make_session_factory()
    with (
        patch(
            "app.agents.writing_rules_agent.merge_writing_rules",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ),
        patch(
            "app.services.writing.call_deepseek",
            new=fake_call_deepseek,
        ),
        patch(
            "app.services.writing.build_citation_link_map",
            new=link_mock,
        ),
        patch(
            "app.agents.claim_verification_agent.get_claim_verification_agent",
            return_value=verify_agent,
        ),
    ):
        await generate_section(
            draft=draft,
            section_type="methods",
            context=None,
            job_id=job.id,
            session_factory=factory,
        )
    await engine.dispose()

    return {
        "model_calls": [
            {"system": _norm(c["system"]), "user": _norm(c["user"])} for c in model_calls
        ],
        "link_inputs": [_norm(c.args[0]) for c in link_mock.call_args_list],
        "verify_prompts": [_norm(p) for p in verify_agent.calls],
    }


async def test_write_requests_match_the_recorded_golden(db_session):
    captured = await capture_write_calls(db_session)
    assert len(captured["model_calls"]) == 3

    if os.environ.get("GATE_LOG_RECORD_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(captured, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        pytest.skip("golden recorded")

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for key in ("model_calls", "link_inputs", "verify_prompts"):
        got, want = captured[key], golden[key]
        assert len(got) == len(want), f"{key}: {len(got)} calls, golden has {len(want)}"
        for i, (g, w) in enumerate(zip(got, want)):
            assert g == w, f"{key}: first differing call is index {i}"
