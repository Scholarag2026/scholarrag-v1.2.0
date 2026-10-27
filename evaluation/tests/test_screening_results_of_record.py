"""Deterministic checker for the screening results of record (results/v3)."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import DEV_MODEL_WORD, load_script_module

from common import read_json

EVAL_ROOT = Path(__file__).resolve().parents[1]
SCREENING = EVAL_ROOT / "screening"
RESULTS = SCREENING / "results" / "v3"

sm = load_script_module("screening", "summarize")
S = read_json(RESULTS / "summary.json")["datasets"]


def test_vds_primary_basis_is_deduplicated():
    e = S["van_de_Schoot_2017"]
    m = e["runs"]["A"]["metrics_final_inclusion"]
    assert e["basis"]["deduplicated"] and (m["n"], m["n_positive"]) == (5782, 38)
    assert round(m["recall_screened_in"], 3) == 0.947
    ref = e["submitted_basis_reference"]["runs"]["A"]["metrics_final_inclusion"]
    assert ref["n"] == 6189


def test_ta_basis_present_and_split():
    # Nagtegaal_2019 is deduplicated like van_de_Schoot_2017 (orchestrator ruling); the
    # as-exported basis (2019 rows) stays in its submitted_basis_reference.
    for run, kept in (("A", 287), ("B", 286)):
        t = S["Nagtegaal_2019"]["runs"][run]["ta_basis"]
        assert (t["n_ta_kept"], t["n_ta_pos"]) == (kept, 389)
        assert (t["final"]["n"], t["final"]["kept"]) == (101, 101)
    ref = S["Nagtegaal_2019"]["submitted_basis_reference"]
    assert ref["n_rows"] == 2019
    assert S["Smid_2020"]["runs"]["A"]["ta_basis"] is None
    for run, kept in (("A", 142), ("B", 137)):
        v = S["van_de_Schoot_2017"]["runs"][run]["ta_basis"]
        assert (v["n_ta_kept"], v["n_ta_pos"]) == (kept, 356)


def test_excluded_share_and_queue_present():
    for ds in S:
        for run in "AB":
            m = S[ds]["runs"][run]["metrics_final_inclusion"]
            assert 0 < m["excluded_share"] < 1 and m["queue_by_reason"]
    shares = {
        ds: round(S[ds]["runs"]["A"]["metrics_final_inclusion"]["excluded_share"], 3) for ds in S
    }
    assert shares == {"Smid_2020": 0.618, "Nagtegaal_2019": 0.655, "van_de_Schoot_2017": 0.837}
    b = S["van_de_Schoot_2017"]["runs"]["B"]["metrics_final_inclusion"]
    assert round(b["excluded_share"], 3) == 0.837
    sub = S["van_de_Schoot_2017"]["submitted_basis_reference"]["runs"]["A"]
    assert round(sub["metrics_final_inclusion"]["excluded_share"], 3) == 0.841


def test_false_negative_files_use_the_exclusion_basis():
    for ds in S:
        text = (RESULTS / f"{ds}_false_negatives.md").read_text(encoding="utf-8")
        assert "excluded outright (status EXCLUDE)" in text


def test_no_development_label_in_regenerated_outputs():
    files = [
        *RESULTS.glob("*.md"),
        *RESULTS.glob("*.json"),
        *(RESULTS / "asreview").glob("*.json"),
        *(RESULTS / "published_llm_sources").glob("*.txt"),
        SCREENING / "corpus_basis.py",
        SCREENING / "asreview_baseline.py",
        SCREENING / "asreview" / "README.md",
    ]
    for p in files:
        text = p.read_text(encoding="utf-8")
        assert DEV_MODEL_WORD not in text and "11/26" not in text, p.name
    assert DEV_MODEL_WORD not in (sm.__doc__ or "")


def test_no_local_paths_in_shipped_results():
    for p in RESULTS.rglob("*"):
        if p.is_file() and p.suffix in {".json", ".md", ".txt"}:
            text = p.read_text(encoding="utf-8")
            assert not any(
                s in text
                for s in (
                    "C:/Users",
                    "C:" + chr(92) + "Users",
                    "C:" + chr(92) * 2 + "Users",
                    "wul" + "82",
                )
            ), p.name


def test_readme_reports_no_new_numbers():
    readme = (EVAL_ROOT / "README.md").read_text(encoding="utf-8")
    assert "0.618 to 0.795" not in readme and "0.95 to 1.00" not in readme
    section = readme.split("ASReview LAB baseline", 1)[1].split("\n## ", 1)[0]
    assert not re.search(r"\d\.\d", section.replace("3.0.8", ""))


def test_summary_tables_present():
    md = (RESULTS / "summary.md").read_text(encoding="utf-8")
    for h in ("Table E1-f.", "Table E1-g.", "Table E1-h.", "Table E1-i."):
        assert h in md
    assert md.count("as exported (") == 1


def test_wos_gate_rows_are_on_the_deduplicated_basis_in_the_primary_series():
    fig = read_json(RESULTS / "figure4_screening.json")
    gate = {r["dataset"]: r for r in fig["rows"] if r["series"] == "WoS gate"}
    assert set(gate) == {"Nagtegaal_2019", "Smid_2020", "van_de_Schoot_2017"}
    assert "as_exported_reference_rows" not in fig
    # 43 exported final inclusions, 5 of them duplicates of kept records: 38 once each.
    assert gate["van_de_Schoot_2017"]["n_included"] == 38
    for name in ("Nagtegaal_2019", "van_de_Schoot_2017"):
        meta = read_json(RESULTS / f"{name}_wos_gate.json")
        assert meta["basis"] == "deduplicated"
        assert meta["included_records"]["n"] == gate[name]["n_included"]
    md = (RESULTS / "summary.md").read_text(encoding="utf-8")
    assert "(as-exported basis)" not in md
