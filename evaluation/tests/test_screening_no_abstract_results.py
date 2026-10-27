"""Title-only screening on the 915 no-abstract development records (Fong_2021, van_Dis_2020)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module

EVAL_ROOT = Path(__file__).resolve().parents[1]
RESULTS = EVAL_ROOT / "screening" / "results" / "no_abstract"

mod = load_script_module("screening", "summarize_no_abstract")


def _row(rid, included, status, criterion=""):
    return {
        "record_id": rid,
        "label_included": included,
        "status": status,
        "criterion": criterion,
        "has_abstract": False,
    }


def test_summarise_counts_excluded_inclusions_by_the_topic_rule():
    rows = [
        _row("1", 1, "NEEDS_REVIEW"),
        _row("2", 1, "EXCLUDE", "TOPIC"),
        _row("3", 0, "EXCLUDE", "TOPIC"),
        _row("4", 0, "NEEDS_REVIEW"),
        _row("5", 0, "EXCLUDE", "LANGUAGE"),
    ]
    s = mod.summarise(rows)
    assert (s["n_records"], s["n_inclusions"]) == (5, 2)
    assert s["inclusions_excluded_by_topic"] == 1
    assert s["inclusions_needs_review"] == 1
    assert s["records_excluded"] == 3 and s["records_excluded_by_topic"] == 2
    assert s["records_excluded_by_topic_gold_inclusion"] == 1


def test_committed_summary_matches_the_rows():
    rows = []
    for name in ("Fong_2021", "van_Dis_2020"):
        rows += mod.read_rows(RESULTS / f"{name}_runA.jsonl")
    on_disk = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    assert on_disk["combined"] == mod.summarise(rows)


def test_results_of_record_for_the_no_abstract_records():
    s = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    c = s["combined"]
    assert (c["n_records"], c["n_inclusions"]) == (915, 38)
    assert c["inclusions_excluded_by_topic"] == 1
    assert c["inclusions_needs_review"] == 37
    assert [round(x, 3) for x in c["inclusions_excluded_by_topic_wilson_95"]] == [0.005, 0.135]
    assert c["records_excluded_by_topic"] == 465
    assert c["records_excluded_by_topic_gold_inclusion"] == 1
    assert (
        s["datasets"]["Fong_2021"]["inclusions_excluded_by_topic"],
        s["datasets"]["van_Dis_2020"]["inclusions_excluded_by_topic"],
    ) == (0, 1)
    assert (
        s["datasets"]["Fong_2021"]["n_records"],
        s["datasets"]["van_Dis_2020"]["n_records"],
    ) == (477, 438)
