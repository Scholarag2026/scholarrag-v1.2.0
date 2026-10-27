"""The README section on substituting another OpenAI-compatible model."""

import re
from pathlib import Path

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]

STEP_VARS = (
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_REASONER_MODEL",
    "SCREENER_SECOND_PASS_MODEL",
    "SCREENER_SECOND_PASS_OUTPUT_MODE",
    "WRITING_MODEL",
)
OTHER_PROVIDERS = re.compile(
    r"(?i)\b(gpt-?\d|chatgpt|anthropic|gemini|llama|mistral|ollama|vllm|"
    r"dashscope|alibaba|moonshot|kimi|glm|zhipu|grok)\b"
)
PROCESS_WORDS = re.compile(r"\bReviewer [1-4]\b|\bWP\d+\b|\brun\d+\b")


def _section() -> str:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("\n## Substituting another model\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_readme_substitution_section_names_every_variable():
    section = _section()
    for name in STEP_VARS:
        assert name in section, name
        assert name.lower() in Settings.model_fields, name
    assert "api.deepseek.com" in section and "--second-pass-model" in section
    assert "\u2014" not in section


def test_readme_substitution_section_names_no_other_provider():
    section = _section()
    assert OTHER_PROVIDERS.search(section) is None
    assert PROCESS_WORDS.search(section) is None


def test_env_example_points_to_substitution_section():
    env = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "Substituting another model" in env
    for name in STEP_VARS[:5]:
        assert f"\n{name}=" in env, name


def test_readme_step_seven_does_not_overclaim_the_configured_name():
    section = _section()
    assert "Every reported number was produced with deepseek-flash" not in section
    flat = " ".join(section.split())
    assert "DeepSeek flash model" in flat
    assert "`deepseek-chat`" in flat


def test_readme_substitution_section_names_the_timeouts():
    flat = " ".join(_section().split())
    for name in ("LLM_TIMEOUT_SECONDS", "LLM_LONG_TIMEOUT_SECONDS"):
        assert f"`{name}`" in flat, name
        assert name.lower() in Settings.model_fields, name
    assert Settings.model_fields["llm_timeout_seconds"].default == 60
    assert Settings.model_fields["llm_long_timeout_seconds"].default == 300
    assert "default 60" in flat and "default 300" in flat
