"""TF-IDF comparison in records read: common helpers and baselines.py on both bases."""

from __future__ import annotations

import json
import math
import os
import random
import shutil
from pathlib import Path

import pytest

import baselines
import common

EVAL_ROOT = Path(__file__).resolve().parents[1]
RESULTS = EVAL_ROOT / "screening" / "results" / "v3"
DATA = Path(os.environ.get("SCREENING_DATA_DIR", EVAL_ROOT / "screening" / "data"))


def test_records_read_to_find_follows_the_wss_tie_break():
    scores, labels = [0.9, 0.5, 0.5, 0.1], [0, 1, 1, 0]
    assert common.records_read_to_find(scores, labels, 2) == 3
    assert common.records_read_to_find(scores, labels, 3) is None
    assert common.records_read_to_find(scores, labels, 0) is None
    assert common.found_in_top(scores, labels, 2) == 1
    assert common.found_in_top(scores, labels, 0) == 0
    assert common.found_in_top(scores, labels, 99) == 2


def test_records_read_matches_wss_from_ranking_on_random_ties():
    rng = random.Random(20261023)
    for _ in range(200):
        n = rng.randint(5, 60)
        scores = [round(rng.random(), 1) for _ in range(n)]
        labels = [1 if rng.random() < 0.3 else 0 for _ in range(n)]
        if sum(labels) == 0:
            labels[rng.randrange(n)] = 1
        t = math.ceil(0.95 * sum(labels) - 1e-9)
        wss = common.wss_from_ranking(scores, labels, 0.95)
        assert common.records_read_to_find(scores, labels, t) == round((1 - wss - 0.05) * n)


def _copy_runs(tmp_path: Path, dataset: str) -> Path:
    res = tmp_path / "v3"
    res.mkdir(parents=True, exist_ok=True)
    for name in (f"{dataset}_runA.jsonl", f"{dataset}_runA.meta.json"):
        shutil.copy(RESULTS / name, res / name)
    return res


def _run(tmp_path: Path, dataset: str, basis: str) -> dict:
    res = _copy_runs(tmp_path, dataset)
    code = baselines.main(
        [
            "--dataset",
            dataset,
            "--k-basis",
            "screened_in",
            "--basis",
            basis,
            "--data-dir",
            str(DATA),
            "--results-dir",
            str(res),
        ]
    )
    assert code == 0
    return json.loads((res / f"{dataset}_baselines.json").read_text(encoding="utf-8"))


@pytest.mark.skipif(not (DATA / "Smid_2020.jsonl").exists(), reason="local data absent")
@pytest.mark.skipif(
    not (DATA / "van_de_Schoot_2017.jsonl").exists()
    or not (DATA / "Nagtegaal_2019.jsonl").exists(),
    reason="local data absent",
)
def test_submitted_basis_reproduces_the_shipped_tfidf_numbers(tmp_path):
    r = {
        ds: _run(tmp_path / ds, ds, "submitted")["tfidf"]
        for ds in ("Smid_2020", "van_de_Schoot_2017", "Nagtegaal_2019")
    }
    assert (r["Smid_2020"]["records_read_at_95"], r["Smid_2020"]["target_at_95"]) == (667, 26)
    vds = r["van_de_Schoot_2017"]
    assert (vds["records_read_at_95"], vds["target_at_95"]) == (1138, 41)
    nag = r["Nagtegaal_2019"]
    assert (nag["records_read_at_95"], nag["target_at_95"]) == (1608, 96)
    assert vds["records_read_at_screener_found"] == 1138  # screener 41/43 at 981
    assert (vds["screener_budget"], vds["screener_found"]) == (981, 41)


@pytest.mark.skipif(not (DATA / "van_de_Schoot_2017.jsonl").exists(), reason="local data absent")
def test_dedup_basis_drops_duplicates_from_tfidf_records(tmp_path):
    out = _run(tmp_path / "v", "van_de_Schoot_2017", "dedup")
    assert out["basis"] == "dedup" and out["n"] == 5782 and out["n_duplicates_dropped"] == 407
    tf = out["tfidf"]
    assert tf["screener_budget"] == out["k"]
    assert tf["screener_found"] == 36
    assert tf["found_at_screener_budget"] <= tf["screener_found"] + 2
    if out["n_unscreened_excluded"] == 0:
        assert tf["records_read_at_95"] <= out["n"]


@pytest.mark.skipif(not (DATA / "Nagtegaal_2019.jsonl").exists(), reason="local data absent")
def test_dedup_basis_for_nagtegaal(tmp_path):
    out = _run(tmp_path / "n", "Nagtegaal_2019", "dedup")
    assert out["basis"] == "dedup" and out["n"] == 2008 and out["n_duplicates_dropped"] == 11


@pytest.mark.skipif(not (DATA / "Smid_2020.jsonl").exists(), reason="local data absent")
def test_smid_has_no_duplicates_and_keeps_its_ranking(tmp_path):
    out = _run(tmp_path / "s", "Smid_2020", "dedup")
    assert out["n_duplicates_dropped"] == 0
    assert round(out["tfidf"]["wss_at_95_ranking"], 4) == 0.6961
