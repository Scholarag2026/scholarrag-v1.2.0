"""Usage accounting survives a reply that carries completion_tokens_details (RB1).

genai-prices returns ``output_reasoning_tokens`` for such replies, pydantic-ai rejects
it, and the swallowed exception zeroes the usage. The model wrapper restores the counts.
"""

from __future__ import annotations

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.completion_usage import CompletionTokensDetails, CompletionUsage
from pydantic_ai.providers.deepseek import DeepSeekProvider

from app.agents.model_config import DeepSeekChatModel


def _completion(details: CompletionTokensDetails | None) -> ChatCompletion:
    return ChatCompletion(
        id="c1",
        created=0,
        model="deepseek-reasoner",
        object="chat.completion",
        choices=[
            Choice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content="ok"),
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            completion_tokens_details=details,
        ),
    )


def _model() -> DeepSeekChatModel:
    return DeepSeekChatModel("deepseek-reasoner", provider=DeepSeekProvider(api_key="k"))


class _Extracted:
    """What genai-prices 0.1.6/0.1.7 return for a reply with completion_tokens_details."""

    def __init__(self, with_reasoning: bool) -> None:
        self.input_tokens = 100
        self.output_tokens = 50
        if with_reasoning:
            self.output_reasoning_tokens = 30


@pytest.fixture
def genai_prices_0_1_6(monkeypatch):
    """Pin the library behaviour so the test does not depend on the installed version."""

    class _Provider:
        def extract_usage(self, data, api_flavor="default"):
            details = data["usage"].get("completion_tokens_details")
            return "m", _Extracted(details is not None)

    class _Snapshot:
        def find_provider(self, *args):
            return _Provider()

    monkeypatch.setattr("pydantic_ai.usage.get_snapshot", lambda: _Snapshot())


def test_usage_survives_reasoning_details(genai_prices_0_1_6):
    usage = (
        _model()._process_response(_completion(CompletionTokensDetails(reasoning_tokens=30))).usage
    )
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50


def test_usage_unchanged_without_details(genai_prices_0_1_6):
    usage = _model()._process_response(_completion(None)).usage
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
