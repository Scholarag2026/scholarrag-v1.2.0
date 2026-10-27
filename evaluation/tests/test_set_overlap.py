from __future__ import annotations

import json
from pathlib import Path

import pytest
import set_overlap as so

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_norm_doi_folds_prefix_case_and_space():
    assert so.norm_doi(" https://doi.org/10.1000/ABC ") == "10.1000/abc"
    assert so.norm_doi("doi:10.1000/abc") == so.norm_doi("10.1000/ABC") == "10.1000/abc"
    assert so.norm_doi("") is None and so.norm_doi(None) is None


def test_norm_text_folds_punctuation_and_case():
    assert so.norm_text("  Hello,  World! ") == "hello world"
    assert so.norm_text("") is None and so.norm_text(None) is None


def test_pairwise_counts_shared_keys_and_returns_ids(tmp_path):
    sets = {
        "a": {"dois": {f"10.1/{i}": {f"a-{i:02d}"} for i in range(8)}},
        "b": {"dois": {f"10.1/{i}": {f"b-{i:02d}"} for i in range(6, 20)}},
    }
    (row,) = so.pairwise(sets, "dois")
    assert (row["a"], row["b"], row["n_shared"]) == ("a", "b", 2)
    assert row["examples"] == [["a-06", "b-06"], ["a-07", "b-07"]]


def test_examples_never_carry_key_text():
    sets = {
        "x": {"titles": {f"short title {i}": {str(i)} for i in range(9)}},
        "y": {"titles": {f"short title {i}": {str(100 + i)} for i in range(9)}},
    }
    (row,) = so.pairwise(sets, "titles")
    assert row["n_shared"] == 9 and len(row["examples"]) == 5
    assert "title" not in json.dumps(row["examples"])


def test_empty_set_is_reported_not_skipped(tmp_path):
    p = tmp_path / "real_claims_dev.jsonl"
    p.write_text("", encoding="utf-8")
    assert so.claim_set_keys(p)["n"] == 0


def test_claim_set_keys_collects_both_dois(tmp_path):
    p = tmp_path / "c.jsonl"
    row = {"item_id": "i1", "claim": "A claim.", "source_doi": "10.1/A", "chunk_doi": "doi:10.1/b"}
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    keys = so.claim_set_keys(p)
    assert keys["dois"] == {"10.1/a": {"i1"}, "10.1/b": {"i1"}}
    assert keys["claims"] == {"a claim": {"i1"}}


def test_screening_keys_counts_records_with_doi(tmp_path):
    p = tmp_path / "s.jsonl"
    rows = [
        {"record_id": 1, "title": "T One", "doi": "10.1/x"},
        {"record_id": 2, "title": "", "doi": None},
    ]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    keys = so.screening_keys(p)
    assert (keys["n"], keys["n_with_doi"]) == (2, 1)
    assert keys["titles"] == {"t one": {"1"}}


def test_scifact_keys_split_ids(tmp_path):
    sample = tmp_path / "s.json"
    sample.write_text(json.dumps(["5:10", "6:11"]), encoding="utf-8")
    dev = tmp_path / "d.jsonl"
    dev.write_text(
        json.dumps({"id": 7, "cited_doc_ids": [11], "evidence": {"12": []}}) + "\n",
        encoding="utf-8",
    )
    keys = so.scifact_keys(sample, dev)
    assert set(keys["train"]["claim_ids"]) == {"5", "6"}
    assert set(keys["dev"]["doc_ids"]) == {"11", "12"}
    (row,) = so.pairwise({"t": keys["train"], "d": keys["dev"]}, "doc_ids")
    assert row["n_shared"] == 1 and row["examples"] == [["11", "11"]]


def test_update_log_block_requires_markers(tmp_path):
    log = tmp_path / "L.md"
    log.write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        so.update_log_block(log, "body", "set-overlap")


def test_update_log_block_replaces_between_markers(tmp_path):
    log = tmp_path / "L.md"
    log.write_text("a\n<!-- n:start -->\nold\n<!-- n:end -->\nz\n", encoding="utf-8")
    so.update_log_block(log, "new body", "n")
    assert log.read_text(encoding="utf-8") == "a\n<!-- n:start -->\nnew body\n<!-- n:end -->\nz\n"
