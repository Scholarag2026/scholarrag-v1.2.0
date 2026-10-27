"""screening/corpus_basis.py: duplicate manifests and the screener operating point."""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

import corpus_basis as cb
import pytest

from common import read_jsonl

EVAL_ROOT = Path(__file__).resolve().parents[1]
RESULTS = EVAL_ROOT / "screening" / "results" / "v3"
FIELDS = [
    "record_id",
    "label_included",
    "label_abstract_screening",
    "duplicate_record_id",
]


def _write_csv(path: Path, rows: list[tuple]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        w.writerows(rows)
    return path


def test_manifest_drops_rows_that_name_an_original(tmp_path):
    csv5 = _write_csv(
        tmp_path / "x.csv",
        [(1, 1, 1, ""), (2, 0, 1, ""), (3, 1, 1, 1), (4, 0, 0, ""), (5, 0, 1, 2)],
    )
    m = cb.build_manifest(csv5, "X")
    assert m.n_rows == 5 and m.duplicate_record_ids == (3, 5) and m.n_unique == 3
    assert m.n_included_unique == 1
    assert m.n_ta_positive_unique == 2
    assert "source_csv_sha256" not in asdict(m)


def test_manifest_rejects_dangling_and_chained_duplicates(tmp_path):
    dangling = _write_csv(tmp_path / "d.csv", [(1, 0, 0, ""), (2, 0, 0, 7)])
    chained = _write_csv(tmp_path / "c.csv", [(1, 0, 0, ""), (2, 0, 0, 1), (3, 0, 0, 2)])
    with pytest.raises(ValueError, match="record_id 7"):
        cb.build_manifest(dangling, "X")
    with pytest.raises(ValueError, match="duplicate of a duplicate"):
        cb.build_manifest(chained, "X")


def test_manifest_round_trips_through_json(tmp_path):
    csv5 = _write_csv(tmp_path / "x.csv", [(1, 1, 1, ""), (2, 0, 1, 1)])
    m = cb.build_manifest(csv5, "X")
    out = tmp_path / "m.json"
    cb.write_manifest(m, out)
    assert cb.load_manifest(out) == m


def test_apply_basis_keeps_the_original_row_and_its_status():
    rows = [
        {"record_id": 1, "status": "EXCLUDE"},
        {"record_id": 2, "status": "INCLUDE"},
        {"record_id": 3, "status": "NEEDS_REVIEW"},
    ]
    kept = cb.apply_basis(rows, frozenset({3}))
    assert [r["record_id"] for r in kept] == [1, 2] and kept[0]["status"] == "EXCLUDE"


def test_load_duplicate_ids_is_empty_off_list_and_strict_on_list(tmp_path):
    assert cb.load_duplicate_ids("Smid_2020", tmp_path) == frozenset()
    with pytest.raises(FileNotFoundError):
        cb.load_duplicate_ids("van_de_Schoot_2017", tmp_path)


def test_operating_point_counts_and_skips_unscreened():
    def row(i, status, pred, final, ta):
        return {
            "record_id": i,
            "status": status,
            "predicted": pred,
            "label_included": final,
            "label_abstract_screening": ta,
        }

    rows = [
        row(1, "INCLUDE", 1, 1, 1),
        row(2, "NEEDS_REVIEW", 1, 0, 1),
        row(3, "EXCLUDE", 0, 1, 1),
        row(4, "EXCLUDE", 0, 0, 0),
        row(5, None, None, 1, 1),
    ]
    assert cb.operating_point(rows) == {
        "n": 4,
        "n_screened_in": 2,
        "n_excluded": 2,
        "n_final_pos": 2,
        "n_final_kept": 1,
        "n_ta_pos": 3,
        "n_ta_kept": 2,
    }


def test_operating_point_uses_predicted_for_status_less_rows_and_zero_ta_when_absent():
    rows = [
        {"record_id": 1, "predicted": 1, "label_included": 1, "label_abstract_screening": None},
        {"record_id": 2, "predicted": 0, "label_included": 1, "label_abstract_screening": None},
        {"record_id": 3, "predicted": 0, "label_included": 0},
    ]
    op = cb.operating_point(rows)
    assert (op["n"], op["n_screened_in"], op["n_excluded"]) == (3, 1, 2)
    assert (op["n_final_pos"], op["n_final_kept"]) == (2, 1)
    assert (op["n_ta_pos"], op["n_ta_kept"]) == (0, 0)


def test_cli_writes_manifest_and_prints_counts(tmp_path, capsys):
    src = _write_csv(tmp_path / "x.csv", [(1, 1, 1, ""), (2, 0, 1, 1)])
    out = tmp_path / "out.json"
    assert cb.main(["--dataset", "X", "--csv", str(src), "--out", str(out)]) == 0
    assert cb.load_manifest(out).duplicate_record_ids == (2,)
    printed = capsys.readouterr().out
    assert "n_rows" in printed and "n_unique" in printed


def test_submitted_basis_reasons_cover_every_deduplicated_dataset():
    assert set(cb.SUBMITTED_BASIS_REASONS) == set(cb.DEDUP_DATASETS)
    assert cb.SUBMITTED_BASIS_REASONS["van_de_Schoot_2017"] == cb.SUBMITTED_BASIS_REASON
    assert cb.SUBMITTED_BASIS_REASON == (
        "the export lists 407 rows as duplicates of other records (duplicate_record_id); "
        "5 of them are final inclusions, so the submitted basis counted those inclusions twice"
    )


def test_committed_manifests_and_dedup_operating_point():
    m = cb.load_manifest(cb.BASIS_DIR / "van_de_Schoot_2017.json")
    assert (m.n_rows, len(m.duplicate_record_ids), m.n_unique, m.n_included_unique) == (
        6189,
        407,
        5782,
        38,
    )
    for run in "AB":
        rows = read_jsonl(RESULTS / f"van_de_Schoot_2017_run{run}.jsonl")
        op = cb.operating_point(cb.apply_basis(rows, frozenset(m.duplicate_record_ids)))
        assert (op["n"], op["n_final_pos"], op["n_final_kept"]) == (5782, 38, 36)
    n = cb.load_manifest(cb.BASIS_DIR / "Nagtegaal_2019.json")
    assert (n.n_rows, len(n.duplicate_record_ids), n.n_unique, n.n_included_unique) == (
        2019,
        11,
        2008,
        101,
    )


def test_consumer_contract_for_later_tasks():
    """Pin the names, parameters and keys that the TF-IDF, summary and ASReview tasks consume."""
    import inspect

    params = {
        "load_duplicate_ids": ["dataset", "basis_dir"],
        "apply_basis": ["rows", "duplicate_ids"],
        "operating_point": ["rows"],
    }
    for name, expected in params.items():
        assert list(inspect.signature(getattr(cb, name)).parameters) == expected, name
    assert inspect.signature(cb.load_duplicate_ids).parameters["basis_dir"].default == (
        cb.BASIS_DIR
    )
    assert isinstance(cb.SUBMITTED_BASIS_REASON, str) and cb.SUBMITTED_BASIS_REASON
    op = cb.operating_point([{"record_id": 1, "predicted": 1, "status": "INCLUDE"}])
    assert set(op) == {
        "n",
        "n_screened_in",
        "n_excluded",
        "n_final_pos",
        "n_final_kept",
        "n_ta_pos",
        "n_ta_kept",
    }
    assert all(type(v) is int for v in op.values())
