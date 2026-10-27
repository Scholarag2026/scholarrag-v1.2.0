"""The writer's raw request carries the DeepSeek-only ``thinking`` field only when the
configured base URL is the DeepSeek host."""

from unittest.mock import patch

import httpx
import pytest

PAYLOAD = {
    "id": "chatcmpl-1",
    "model": "m",
    "choices": [{"message": {"content": "text"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


async def _call(monkeypatch, base_url, writing_thinking):
    from app.config import settings
    from app.services.writing import call_deepseek

    monkeypatch.setattr(settings, "deepseek_api_key", "sk-w")
    monkeypatch.setattr(settings, "deepseek_base_url", base_url)
    monkeypatch.setattr(settings, "writing_thinking", writing_thinking)
    captured: dict = {}

    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return httpx.Response(200, json=PAYLOAD, request=httpx.Request("POST", url))

    with patch("httpx.AsyncClient.post", new=fake_post):
        completion = await call_deepseek("SYSTEM", "USER")
    return captured, completion.provenance


@pytest.mark.asyncio
async def test_call_deepseek_default_endpoint_sends_thinking_disabled(monkeypatch):
    captured, provenance = await _call(monkeypatch, "https://api.deepseek.com/v1", None)
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert provenance["thinking"] == "disabled"


@pytest.mark.asyncio
async def test_call_deepseek_other_endpoint_omits_thinking(monkeypatch):
    captured, provenance = await _call(monkeypatch, "http://llm.local.test/v1", "enabled")
    assert captured["url"] == "http://llm.local.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-w"
    assert "thinking" not in captured["json"]
    assert provenance["thinking"] is None
