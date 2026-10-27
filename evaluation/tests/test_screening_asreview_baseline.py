"""screening/asreview_baseline.py: metrics, export, label-order reading and the input check."""

from __future__ import annotations

import csv
import json
import sqlite3
import zipfile
from pathlib import Path

import asreview_baseline as ab
import pytest

L = [1, 0, 0, 1, 0, 0, 0, 1, 0, 0]  # priors are positions 0 and 1


def test_found_within_and_records_to_find():
    assert ab.found_within(L, 4) == 2
    assert ab.records_to_find(L, 3) == 8
    assert ab.records_to_find(L, 4) is None


def test_wss_at_recall():
    assert ab.wss_at_recall(L, 20, 3, 1.0) == pytest.approx((20 - 8) / 20)
    assert ab.wss_at_recall(L, 20, 4, 1.0) is None


def test_stop_rule_constants():
    assert ab.STOP_RULE == {"rule": "consecutive_irrelevant", "k": 100}
    assert ab.SEEDS == tuple(range(1, 16))


def test_stop_rule_triggers_inside_and_after_the_order():
    assert ab.stop_after_consecutive_irrelevant([1, 0, 0, 0, 1], 3, 50, 3) == (4, 1)
    assert ab.stop_after_consecutive_irrelevant([1, 0, 1], 3, 50, 2) == (6, 2)
    with pytest.raises(ValueError, match="truncated"):
        ab.stop_after_consecutive_irrelevant([1, 0], 3, 50, 2)


def test_stop_rule_records_are_capped_at_n_total():
    assert ab.stop_after_consecutive_irrelevant([1, 1], 100, 10, 2) == (10, 2)


def test_seed_metrics_reports_not_reached_as_none():
    m = ab.seed_metrics([1, 0, 0], 10, 2, {"A": (2, 2)})
    assert m["A"]["records_to_screener_found"] is None
    assert m["A"]["share_to_screener_found"] is None
    assert m["A"]["found_at_screener_budget"] == 1
    assert m["stop_rule_records"] is None
    assert m["stop_rule_recall"] is None
    assert m["wss_at_100"] is None and m["wss_at_95"] is None


def test_seed_metrics_values_when_reached():
    m = ab.seed_metrics(L, 20, 3, {"A": (4, 2), "B": (8, 3)})
    assert m["A"]["found_at_screener_budget"] == 2
    assert m["A"]["recall_at_screener_budget"] == pytest.approx(2 / 3)
    assert m["A"]["records_to_screener_found"] == 4
    assert m["A"]["share_to_screener_found"] == pytest.approx(4 / 20)
    assert m["B"]["records_to_screener_found"] == 8
    assert m["wss_at_100"] == pytest.approx(12 / 20)
    assert m["stop_rule_found"] == 3 and m["stop_rule_recall"] == 1.0
    assert m["stop_rule_records"] == 20


def test_aggregate_counts_not_reached():
    a = ab.aggregate([{"x": 1.0}, {"x": None}, {"x": 3.0}])
    assert a["x"] == {"mean": 2.0, "min": 1.0, "max": 3.0, "n_not_reached": 1}


def test_aggregate_flattens_the_screener_blocks():
    a = ab.aggregate([{"A": {"y": 1}, "x": 2}, {"A": {"y": None}, "x": 4}])
    assert a["A.y"] == {"mean": 1.0, "min": 1, "max": 1, "n_not_reached": 1}
    assert a["x"]["mean"] == 3.0


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def corpus(tmp_path):
    data = tmp_path / "data"
    results = tmp_path / "results"
    basis = tmp_path / "basis"
    for d in (data, results, basis):
        d.mkdir()
    name = "van_de_Schoot_2017"
    recs = [
        {"record_id": 1, "title": "T1", "abstract": "A1", "label_included": 1},
        {"record_id": 2, "title": "", "abstract": "A2", "label_included": 0},
        {"record_id": 3, "title": "T3", "abstract": "A3", "label_included": 1},
        {"record_id": 4, "title": "T4", "abstract": None, "label_included": 0},
        {"record_id": 5, "title": "T5", "abstract": "A5", "label_included": 0},
    ]
    _write_jsonl(data / f"{name}.jsonl", recs)
    run = [
        {"record_id": 1, "predicted": 1, "status": "INCLUDE", "label_included": 1},
        {"record_id": 2, "predicted": 0, "status": "EXCLUDE", "label_included": 0},
        {"record_id": 3, "predicted": 1, "status": "INCLUDE", "label_included": 1},
        {"record_id": 4, "predicted": 0, "status": "EXCLUDE", "label_included": 0},
        {"record_id": 5, "predicted": None, "label_included": 0},
    ]
    _write_jsonl(results / f"{name}_runA.jsonl", run)
    _write_jsonl(results / f"{name}_runB.jsonl", run)
    (basis / f"{name}.json").write_text(
        json.dumps(
            {
                "dataset": name,
                "n_rows": 5,
                "duplicate_record_ids": [3],
                "n_unique": 4,
                "n_included_unique": 1,
                "n_ta_positive_unique": 0,
                "rule": "r",
            }
        ),
        encoding="utf-8",
    )
    return name, data, results, basis


def test_export_uses_the_screened_deduplicated_records(tmp_path, corpus):
    name, data, results, basis = corpus
    out = tmp_path / "c.csv"
    ids = ab.export_corpus(name, data, results, out, basis)
    assert ids == [1, 2, 4]
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["title"] for r in rows] == ["T1", "", "T4"]
    assert [r["abstract"] for r in rows] == ["A1", "A2", ""]
    assert [r["label_included"] for r in rows] == ["1", "0", "0"]


def _make_project(path: Path, rows: list[tuple[int, int]]) -> Path:
    db = path.parent / "results.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.execute("create table results(record_id INTEGER UNIQUE, label INTEGER, time REAL)")
    con.executemany("insert into results values (?,?,0)", rows)
    con.commit()
    con.close()
    with zipfile.ZipFile(path, "w") as z:
        z.write(db, "reviews/abc/results.db")
        z.writestr("project.json", "{}")
    return path


def test_read_label_order_follows_rowid_and_rejects_unknown_rows(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    proj = _make_project(tmp_path / "a" / "p.asreview", [(2, 1), (1, 0), (0, 0)])
    assert ab.read_label_order(proj, [10, 20, 30]) == [(30, 1), (20, 0), (10, 0)]
    bad = _make_project(tmp_path / "b" / "p.asreview", [(7, 1)])
    with pytest.raises(ValueError, match="outside"):
        ab.read_label_order(bad, [10, 20, 30])


def test_portable_argv_strips_local_paths(tmp_path):
    w, o = tmp_path / "w", tmp_path / "o"
    got = ab.portable_argv(
        ["C:/x/asreview.exe", "simulate", str(w / "Mixed_Case.csv"), "--out", str(o / "p")], w, o
    )
    assert got == ["asreview", "simulate", "<work-dir>/Mixed_Case.csv", "--out", "<out-dir>/p"]
    with pytest.raises(ValueError):
        ab.portable_argv(["asreview", str(tmp_path / "elsewhere" / "x")], w, o)


def test_input_check_flags_a_label_mismatch(tmp_path, corpus):
    name, data, results, basis = corpus
    d1 = tmp_path / "first"
    d1.mkdir()
    # label of record 2 is stored as 1 but label_included says 0
    (d1 / f"{name}_seed01.order.json").write_text(
        json.dumps({"record_ids": [1, 2, 4], "labels": [1, 1, 0]}), encoding="utf-8"
    )
    v = ab.input_check(d1, d1, name, data, results, basis)
    assert v["order"][0] is False
    assert v["repeat"][0] is True


def test_input_check_passes_a_consistent_order(tmp_path, corpus):
    name, data, results, basis = corpus
    d1, d2 = tmp_path / "p1", tmp_path / "p2"
    for d in (d1, d2):
        d.mkdir()
        (d / f"{name}_seed01.order.json").write_text(
            json.dumps({"record_ids": [1, 2, 4], "labels": [1, 0, 0]}), encoding="utf-8"
        )
    v = ab.input_check(d1, d2, name, data, results, basis)
    assert v["order"][0] is True and v["metrics"][0] is True and v["repeat"][0] is True
    (d2 / f"{name}_seed01.order.json").write_text(
        json.dumps({"record_ids": [1, 4, 2], "labels": [1, 0, 0]}), encoding="utf-8"
    )
    assert ab.input_check(d1, d2, name, data, results, basis)["repeat"][0] is False


def test_committed_asreview_outputs_are_complete():
    import json
    from pathlib import Path

    asr = Path(__file__).resolve().parents[1] / "screening" / "results" / "v3" / "asreview"
    totals = {"Nagtegaal_2019": None, "Smid_2020": None, "van_de_Schoot_2017": None}
    for ds in totals:
        s = json.loads((asr / f"{ds}_asreview.json").read_text(encoding="utf-8"))
        assert len(s["per_seed"]) == 15
        assert s["stop_rule"] == {"rule": "consecutive_irrelevant", "k": 100}
        expected = {
            "Nagtegaal_2019": (2008, 101),
            "Smid_2020": (2627, 27),
            "van_de_Schoot_2017": (5782, 38),
        }[ds]
        assert (s["n_total"], s["n_pos"]) == expected
        for seed in range(1, 16):
            o = json.loads((asr / f"{ds}_seed{seed:02d}.order.json").read_text(encoding="utf-8"))
            assert sum(o["labels"]) == s["n_pos"]
            assert len(set(o["record_ids"])) == len(o["record_ids"])
    meta = json.loads((asr / "asreview_meta.json").read_text(encoding="utf-8"))
    assert meta["asreview_version"].endswith("3.0.8")
