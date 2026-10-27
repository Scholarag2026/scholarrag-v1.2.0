"""`claims/label_sets.py`: the verifier scored against every claim label set."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import label_sets as ls
import pytest

CLAIMS_DIR = Path(__file__).resolve().parents[1] / "claims"


def _row(result, set_name, population, run):
    [row] = [
        x for x in result["table"]
        if (x["set"], x["population"], x["run"]) == (set_name, population, run)
    ]
    return row


def _cell(result, set_name, population, run):
    row = _row(result, set_name, population, run)
    return row["n_correct"], row["n"]


def _pair(result, a, b, population):
    [row] = [
        x for x in result["agreement"]
        if (x["set_a"], x["set_b"], x["population"]) == (a, b, population)
    ]
    return row


def test_reproduces_shipped_label_set_numbers():
    r = ls.build(CLAIMS_DIR, CLAIMS_DIR / "results" / "v6")
    assert _cell(r, "construction_rule", "constructed", "A") == (55, 60)
    assert _cell(r, "construction_rule", "constructed", "B") == (54, 60)
    assert not any(
        x["set"] == "construction_rule" and x["population"] != "constructed" for x in r["table"]
    )
    assert {x["set"] for x in r["table"]} == {"human_blind", "construction_rule"}


def test_reproduces_shipped_blind_label_set_numbers():
    r = ls.build(CLAIMS_DIR, CLAIMS_DIR / "results" / "v6")
    assert _cell(r, "human_blind", "constructed", "A") == (53, 60)
    assert _cell(r, "human_blind", "constructed", "B") == (52, 60)
    assert _cell(r, "human_blind", "real", "A") == (15, 26)
    assert _cell(r, "human_blind", "real", "B") == (15, 26)
    assert _cell(r, "human_blind", "all", "A") == (68, 86)
    assert _cell(r, "human_blind", "all", "B") == (67, 86)
    row = _row(r, "human_blind", "real", "A")
    assert row["kappa"] == pytest.approx(0.3602, abs=1e-3)
    assert row["verified_recall"] == pytest.approx(6 / 13, abs=1e-3)
    assert row["falsely_verified"] == 0
    constructed = _row(r, "human_blind", "constructed", "A")
    assert constructed["n_no_majority"] == 0
    assert constructed["falsely_verified"] == 1
    assert constructed["verified_precision"] == pytest.approx(13 / 14, abs=1e-3)
    assert _pair(r, "human_blind", "construction_rule", "constructed")["n_agree"] == 58


def test_outputs_never_name_the_development_model_or_numbers():  # D2
    r = ls.build(CLAIMS_DIR, CLAIMS_DIR / "results" / "v6")
    text = ls.render_markdown(r) + json.dumps(r) + Path(ls.__file__).read_text(encoding="utf-8")
    token = bytes.fromhex("636c61756465").decode()
    assert token not in text.lower() and "11/26" not in text


def test_blind_set_is_included_when_file_present(tmp_path):
    assert set(ls.load_label_sets(CLAIMS_DIR, tmp_path)) == {"construction_rule"}
    (tmp_path / "human_labels_blind.json").write_text(
        json.dumps({"items": [{"item_id": "real-test-01", "majority_label": "verified"}]}),
        encoding="utf-8",
    )
    assert "human_blind" in ls.load_label_sets(CLAIMS_DIR, tmp_path)


def test_only_blind_and_rule_sets(tmp_path):
    ids = [
        json.loads(line)["item_id"]
        for name in ("hss_test_v3_claims.jsonl", "real_claims_test.jsonl")
        for line in (CLAIMS_DIR / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for f in (CLAIMS_DIR / "results" / "v6").glob("*_run?.jsonl"):
        shutil.copy(f, tmp_path)
    items = [{"item_id": i, "majority_label": "unsupported"} for i in ids]
    payload = json.dumps({"items": items})
    # a labels file under the removed name must not be read
    (tmp_path / ("human_labels" + ".json")).write_text(payload, encoding="utf-8")
    (tmp_path / "human_labels_blind.json").write_text(payload, encoding="utf-8")
    r = ls.build(CLAIMS_DIR, tmp_path)
    assert {x["set"] for x in r["table"]} == {"human_blind", "construction_rule"}
    assert set(r["exposure"]) == {"human_blind", "construction_rule"}
    assert "differ_counts" not in r and "differing_real" not in r


def test_no_majority_item_keeps_the_row_and_is_counted():  # Review Focus 5
    sets = {"human_blind": {"r1": "verified", "r2": None, "r3": "unsupported"}}
    preds = {"A": {"r1": "verified", "r2": "verified", "r3": "verified"}}
    [row] = ls.label_set_table(sets, preds, {"real": ["r1", "r2", "r3"]})
    assert (row["set"], row["population"], row["n"], row["n_no_majority"], row["n_correct"]) == (
        "human_blind", "real", 2, 1, 1)


def test_pairwise_agreement_leaves_none_out_of_n():
    sets = {
        "human_blind": {"r1": "verified", "r2": None, "r3": "unsupported"},
        "construction_rule": {"r1": "verified", "r2": "verified", "r3": "verified"},
    }
    [row] = ls.pairwise_agreement(sets, {"real": ["r1", "r2", "r3"]})
    assert (row["n"], row["n_no_majority"], row["n_agree"]) == (2, 1, 1)


def test_population_needs_full_coverage_by_the_set():
    sets = {"construction_rule": {"c1": "verified"}}
    preds = {"A": {"c1": "verified", "r1": "verified"}}
    rows = ls.label_set_table(sets, preds, {"constructed": ["c1"], "real": ["r1"]})
    assert [x["population"] for x in rows] == ["constructed"]


def test_verifier_status_mapping(tmp_path):
    rows = [
        {"item_id": "a", "predicted_status": "error"},
        {"item_id": "b", "predicted_status": "needs_nuance"},
        {"item_id": "c", "predicted_status": "no_full_text"},
    ]
    (tmp_path / "hss_runA.jsonl").write_text(
        "\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    assert ls.verifier_statuses(tmp_path, "hss_runA") == {
        "a": "unsupported", "b": "needs_nuance", "c": "no_full_text"}


def test_build_carries_no_timestamp():
    assert "generated" not in ls.build(CLAIMS_DIR, CLAIMS_DIR / "results" / "v6")
