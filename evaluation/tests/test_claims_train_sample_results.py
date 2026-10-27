"""The shipped verifier on the 491 SciFact train pairs: summariser and results of record."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import load_script_module

EVAL_ROOT = Path(__file__).resolve().parents[1]
CLAIMS = EVAL_ROOT / "claims"
RESULTS = CLAIMS / "results" / "v6" / "scifact_train491"
SAMPLE = CLAIMS / "scifact_train_491.json"

mod = load_script_module("claims", "summarize_train_sample")


def _row(i, gold, status, error=None):
    return {"item_id": f"c{i}:d{i}", "gold": gold, "predicted_status": status, "error": error}


def test_summarise_counts_and_intervals_on_a_small_set():
    rows = [
        _row(1, "SUPPORT", "verified"),
        _row(2, "SUPPORT", "needs_nuance"),
        _row(3, "SUPPORT", "unsupported"),
        _row(4, "SUPPORT", "verified"),
        _row(5, "CONTRADICT", "unsupported"),
        _row(6, "NOT_ENOUGH_INFO", "needs_nuance"),
        _row(7, "NOT_ENOUGH_INFO", "unsupported"),
    ]
    s = mod.summarise(rows)
    assert (s["n_rows"], s["n_errors"]) == (7, 0)
    sup = s["support"]
    assert (sup["n"], sup["verified"], sup["needs_nuance"], sup["unsupported"]) == (4, 2, 1, 1)
    assert sup["strict_recall"] == 0.5
    assert sup["lenient_recall"] == 0.75 and sup["lenient_verified_or_nuance"] == 3
    lo, hi = sup["strict_recall_wilson_95"]
    assert 0.15 < lo < 0.2 and 0.8 < hi < 0.85
    ns = s["non_support"]
    assert (ns["n"], ns["verified"], ns["needs_nuance"], ns["unsupported"]) == (3, 0, 1, 2)
    assert ns["by_gold"] == {"CONTRADICT": 1, "NOT_ENOUGH_INFO": 2}


def test_summarise_counts_error_rows_apart_from_the_scored_rows():
    rows = [_row(1, "SUPPORT", "verified"), _row(2, "SUPPORT", "error", error="boom")]
    s = mod.summarise(rows)
    assert (s["n_rows"], s["n_errors"], s["support"]["n"]) == (2, 1, 1)


def test_sample_ids_are_the_run_items():
    ids = json.loads(SAMPLE.read_text(encoding="utf-8"))
    rows = mod.read_rows(RESULTS / "scifact-train_runA.jsonl")
    assert len(ids) == 491 == len(set(ids))
    assert sorted(ids) == sorted(r["item_id"] for r in rows)


def test_committed_summary_matches_the_rows():
    rows = mod.read_rows(RESULTS / "scifact-train_runA.jsonl")
    on_disk = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    assert on_disk == mod.summarise(rows)


def test_results_of_record_for_the_491_pairs():
    s = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    assert (s["n_rows"], s["n_errors"]) == (491, 0)
    sup = s["support"]
    assert sup["n"] == 206
    assert (sup["verified"], sup["needs_nuance"], sup["unsupported"]) == (87, 79, 40)
    assert round(sup["strict_recall"], 3) == 0.422
    assert [round(x, 3) for x in sup["strict_recall_wilson_95"]] == [0.357, 0.491]
    assert sup["lenient_verified_or_nuance"] == 166
    assert round(sup["lenient_recall"], 3) == 0.806
    assert [round(x, 3) for x in sup["lenient_recall_wilson_95"]] == [0.746, 0.854]
    ns = s["non_support"]
    assert ns["n"] == 285
    assert (ns["verified"], ns["needs_nuance"], ns["unsupported"]) == (0, 12, 273)
    assert ns["by_gold"] == {"CONTRADICT": 85, "NOT_ENOUGH_INFO": 200}
