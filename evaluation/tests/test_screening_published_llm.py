"""Published LLM screening results: every row quotes its value from a fetched snapshot."""

from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import DEV_MODEL_WORD

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "evaluation" / "screening" / "results" / "v3"
PATH = RESULTS / "published_llm_screening.json"
SOURCES = RESULTS / "published_llm_sources"
ALLOWED = {
    "Nagtegaal_2019",
    "Smid_2020",
    "van_de_Schoot_2017",
    "SYNERGY macro-average (includes Smid_2020)",
}
ROW_KEYS = {
    "citation", "doi_or_url", "peer_reviewed", "dataset", "dataset_version_note", "model",
    "setting", "metric", "value", "quote", "location", "caveat", "snapshot",
}


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def norm(s: str) -> str:
    return " ".join(s.split())


def test_every_row_quotes_its_value_and_names_an_allowed_dataset():
    d = read_json(PATH)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["accessed"]) and d["search_log"]
    assert all(s["query"] and s["where"] for s in d["search_log"])
    assert d["rows"]
    for r in d["rows"]:
        assert set(r) == ROW_KEYS
        assert isinstance(r["peer_reviewed"], bool)
        assert r["value"] in r["quote"] and r["dataset"] in ALLOWED
        assert r["caveat"] and r["location"] and r["dataset_version_note"]
        assert r["doi_or_url"].startswith(("10.", "https://"))
    for x in d["rejected"]:
        assert x["citation"] and x["reason"]


def test_every_quote_is_in_its_fetched_snapshot():
    for r in read_json(PATH)["rows"]:
        text = (REPO / r["snapshot"]).read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines[0] == f"url: {r['doi_or_url']}"
        assert re.fullmatch(r"accessed: \d{4}-\d{2}-\d{2}", lines[1])
        assert norm(r["quote"]) in norm(text)
        assert len(lines) <= 2 + 40 * 3


def test_no_row_is_unsourced_or_mentions_the_development_model():
    assert DEV_MODEL_WORD not in PATH.read_text(encoding="utf-8")
    snaps = list(SOURCES.glob("*.txt"))
    assert snaps
    assert all(DEV_MODEL_WORD not in p.read_text(encoding="utf-8") for p in snaps)
    used = {r["snapshot"] for r in read_json(PATH)["rows"]}
    assert used == {p.relative_to(REPO).as_posix() for p in snaps}


def test_caveat_matches_its_own_row():
    rows = read_json(PATH)["rows"]
    for r in rows:
        if "conservative" in r["setting"]:
            assert "sensitive threshold" not in r["caveat"]
            assert "conservative threshold" in r["caveat"]
        for name in ("Llama3.3-70B", "Qwen2.5-72B"):
            if name in r["caveat"]:
                assert name in r["model"]


def test_synergy_has_a_single_macro_average_row():
    rows = read_json(PATH)["rows"]
    assert sum("SYNERGY" in r["dataset"] for r in rows) == 1
