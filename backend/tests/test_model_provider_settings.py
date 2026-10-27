"""The model factory honours the base URL, key and model name from Settings.

DeepSeek stays the default: with the default base URL the agent request (URL,
authorization header, body) is the one the plain ``deepseek:<name>`` string produced.
The DeepSeek-only ``thinking`` field is sent only to ``api.deepseek.com``.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

import httpx  # noqa: E402
import pytest  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models import infer_model  # noqa: E402
from pydantic_ai.providers.deepseek import DeepSeekProvider  # noqa: E402
from pydantic_ai.settings import ModelSettings  # noqa: E402

from app.agents.model_config import (  # noqa: E402
    ANALYSIS_MODEL_SETTINGS,
    DETERMINISTIC_FAST_MODEL_SETTINGS,
    DETERMINISTIC_LONG_MODEL_SETTINGS,
    FAST_MODEL_SETTINGS,
    LONG_MODEL_SETTINGS,
    SECOND_PASS_V2_MODEL_SETTINGS,
    build_deepseek_model,
    thinking_disable_extra,
    uses_deepseek_endpoint,
)
from app.config import settings  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


class _Echo(BaseModel):
    text: str


def _completion(model: str) -> dict:
    return {
        "id": "cmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "system_fingerprint": "fp_test",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "final_result",
                                "arguments": '{"text": "ok"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _capture() -> tuple[list[httpx.Request], httpx.AsyncClient]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completion(json.loads(request.content)["model"]))

    return seen, httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.deepseek.com/v1", True),
        ("https://api.deepseek.com", True),
        ("https://API.DeepSeek.com/v1/", True),
        ("http://localhost:11434/v1", False),
        ("https://llm.example.org/compatible-mode/v1", False),
        ("https://api.deepseek.com.evil.example/v1", False),
        ("", False),
    ],
)
def test_uses_deepseek_endpoint_matches_host_only(url, expected):
    assert uses_deepseek_endpoint(url) is expected


def test_thinking_disable_extra_by_endpoint():
    assert thinking_disable_extra("https://api.deepseek.com/v1") == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    assert thinking_disable_extra("http://localhost:11434/v1") == {}


def test_default_tiers_send_thinking_disabled():
    for tier in (
        FAST_MODEL_SETTINGS,
        LONG_MODEL_SETTINGS,
        DETERMINISTIC_FAST_MODEL_SETTINGS,
        DETERMINISTIC_LONG_MODEL_SETTINGS,
        ANALYSIS_MODEL_SETTINGS,
    ):
        assert tier["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in SECOND_PASS_V2_MODEL_SETTINGS


def test_tiers_omit_thinking_for_other_endpoint():
    prog = (
        "from app.agents import model_config as m;"
        "print(repr([t.get('extra_body') for t in (m.FAST_MODEL_SETTINGS,"
        "m.LONG_MODEL_SETTINGS,m.DETERMINISTIC_FAST_MODEL_SETTINGS,"
        "m.DETERMINISTIC_LONG_MODEL_SETTINGS,m.ANALYSIS_MODEL_SETTINGS)]))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", prog],
        cwd=BACKEND_DIR,
        env={**os.environ, "DEEPSEEK_BASE_URL": "http://llm.local.test/v1"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "[None, None, None, None, None]"


async def test_default_request_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-settings-test")
    monkeypatch.setattr(settings, "deepseek_base_url", "https://api.deepseek.com/v1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    seen, client = _capture()
    model = build_deepseek_model("deepseek-flash", http_client=client)
    result = await Agent(model, output_type=_Echo, model_settings=FAST_MODEL_SETTINGS).run("ping")
    req, body = seen[0], json.loads(seen[0].content)
    assert str(req.url) == "https://api.deepseek.com/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-settings-test"
    assert body["model"] == "deepseek-flash" and body["thinking"] == {"type": "disabled"}
    assert body["tools"][0]["function"]["name"] == "final_result"
    assert result.output.text == "ok"


async def test_factory_request_matches_string_path(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-settings-test")
    monkeypatch.setattr(settings, "deepseek_base_url", "https://api.deepseek.com/v1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    seen_a, client_a = _capture()
    seen_b, client_b = _capture()
    model_a = infer_model(
        "deepseek:deepseek-flash",
        provider_factory=lambda _: DeepSeekProvider(
            api_key="sk-settings-test", http_client=client_a
        ),
    )
    model_b = build_deepseek_model("deepseek-flash", http_client=client_b)
    for model in (model_a, model_b):
        await Agent(model, output_type=_Echo, model_settings=FAST_MODEL_SETTINGS).run("ping")
    assert str(seen_a[0].url) == str(seen_b[0].url)
    assert seen_a[0].headers["authorization"] == seen_b[0].headers["authorization"]
    assert json.loads(seen_a[0].content) == json.loads(seen_b[0].content)


async def test_other_endpoint_request_uses_settings(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-other")
    monkeypatch.setattr(settings, "deepseek_base_url", "http://llm.local.test/v1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    seen, client = _capture()
    model = build_deepseek_model("other-model", http_client=client)
    ms = ModelSettings(timeout=60, **thinking_disable_extra("http://llm.local.test/v1"))
    result = await Agent(model, output_type=_Echo, model_settings=ms).run("ping")
    req, body = seen[0], json.loads(seen[0].content)
    assert str(req.url) == "http://llm.local.test/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-other"
    assert body["model"] == "other-model" and "thinking" not in body
    assert result.output.text == "ok"


def test_empty_settings_key_keeps_string_fallback(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_model("deepseek-flash") == "deepseek:deepseek-flash"


REASONER = {
    "analysis",
    "data_collection",
    "gap",
    "qualitative_coding",
    "quantitative_plan",
    "quantitative_interpretation",
    "research_design",
}


def _probe(extra_env: dict) -> list[dict]:
    env = {
        **os.environ,
        "DEEPSEEK_API_KEY": "sk-settings-probe",
        "DEEPSEEK_MODEL": "probe-main",
        "DEEPSEEK_REASONER_MODEL": "probe-reasoner",
        "SCREENER_SECOND_PASS_MODEL": "probe-judge",
        **extra_env,
    }
    done = subprocess.run(
        [sys.executable, "-m", "tests.provider_check"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(done.stdout)


def _expected_name(agent: str) -> str:
    if agent == "second_pass_v2":
        return "probe-judge"
    return "probe-reasoner" if agent in REASONER else "probe-main"


def test_all_agents_default_endpoint():
    rows = _probe({})
    assert len(rows) == 22
    for r in rows:
        assert r["error"] is None, r
        assert r["model_class"] == "DeepSeekChatModel", r
        assert r["base_url"] == "https://api.deepseek.com", r
        assert r["api_key"] == "sk-settings-probe", r
        assert r["model_name"] == _expected_name(r["agent"]), r


def test_all_agents_follow_settings_endpoint_and_key():
    rows = _probe({"DEEPSEEK_BASE_URL": "http://llm.local.test/v1"})
    assert len(rows) == 22
    for r in rows:
        assert r["error"] is None and r["model_class"] == "DeepSeekChatModel", r
        assert r["base_url"] == "http://llm.local.test/v1", r
        assert r["api_key"] == "sk-settings-probe", r
        assert r["model_name"] == _expected_name(r["agent"]), r
