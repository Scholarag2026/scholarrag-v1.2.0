"""screening/summarize.py on synthetic run files (no LLM, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import corpus_basis as cb
import pytest
from conftest import load_script_module

from common import read_json, read_jsonl, write_json

sm = load_script_module("screening", "summarize")


def _row(i, label, pred, has_abstract=True, called_at="2026-09-02T12:00:00+00:00"):
    return {
        "record_id": i,
        "label": label,
        "label_included": label,
        "label_abstract_screening": None,
        "has_abstract": has_abstract,
        "title": f"Paper {i}",
        "predicted": pred,
        "reason": f"reason {i}",
        "batch_index": (i - 1) // 2,
        "called_at": called_at,
        "latency_s": 1.0,
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_tokens": None,
        "model_reported": "deepseek-v4-flash",
        "system_fingerprint": "fp",
        "provider_response_id": None,
        "attempts": 1,
    }


def _meta(run):
    return {
        "started": "2026-09-02T12:00:00+00:00",
        "finished": "2026-09-02T12:10:00+00:00",
        "model_configured": "deepseek-chat",
        "model_reported": ["deepseek-v4-flash"],
        "system_fingerprints": ["fp"],
        "temperature": 0.0,
        "prompt_version": ["v1"],
        "n_batches": 3,
        "failures": 0,
        "n_unscreened_records": 0 if run == "A" else 1,
        "price": {"price_model": "deepseek-v4-flash"},
        "total_input_tokens": 300,
        "total_output_tokens": 30,
        "total_cost": 0.001,
        "cost_basis": "list price, tier by call time, cache-miss assumed (upper bound)",
        "latency_s": {"median": 1.0, "p90": 1.0},
    }


_M = {
    "n": 6, "prevalence": 0.5, "recall": 1.0, "precision": 0.5, "f1": 2 / 3,
    "specificity": 0.0, "inclusion_rate": 1.0, "wss_at_achieved_recall": 0.0, "wss_at_95": None,
}


@pytest.fixture
def workspace(tmp_path: Path):
    results, data, protos = tmp_path / "results", tmp_path / "data", tmp_path / "protocols"
    for d in (results, data, protos):
        d.mkdir()
    proto = {
        "dataset_id": "D", "source_review_doi": "10.1/d", "research_question": "q",
        "inclusion_criteria": ["i"], "exclusion_criteria": ["e"],
        "label_field": "label_included", "notes": "n",
    }
    (protos / "D.json").write_text(json.dumps(proto), encoding="utf-8")
    labels = [1, 1, 1, 0, 0, 0]
    preds_a = [1, 1, 0, 1, 0, 0]  # TP=2 FN=1 FP=1 TN=2
    preds_b = [1, 0, 0, 1, 0, None]  # record 6 unscreened in B
    pairs_a = zip(labels, preds_a, strict=True)
    rows_a = [_row(i + 1, lab, p, has_abstract=(i != 2)) for i, (lab, p) in enumerate(pairs_a)]
    pairs_b = zip(labels, preds_b, strict=True)
    rows_b = [_row(i + 1, lab, p) for i, (lab, p) in enumerate(pairs_b)]
    for run, rows in (("A", rows_a), ("B", rows_b)):
        (results / f"D_run{run}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
        write_json(results / f"D_run{run}.meta.json", _meta(run))
    tfidf = dict(_M, recall=2 / 3, precision=2 / 3, specificity=2 / 3, inclusion_rate=0.5)
    write_json(
        results / "D_baselines.json",
        {"k": 3, "include_all": _M, "tfidf": {"metrics": tfidf, "wss_at_95_ranking": 0.2}},
    )
    write_json(
        results / "D_wos_gate.json",
        {
            "included_records": {
                "n": 3, "n_with_issn": 2, "n_in_wos_any": 1, "share_in_wos_any": 1 / 3,
                "share_in_wos_any_of_resolved": 0.5,
                "per_collection": {c: {"n": 0} for c in ("SCIE", "SSCI", "AHCI", "ESCI")},
            },
            "all_records": {"share_in_wos_any": 0.5},
        },
    )
    write_json(
        data / "D.fetch.json",
        {"dataset_id": "D", "n": 6, "n_missing_abstract": 2, "share_missing_abstract": 1 / 3},
    )
    return results, data, protos


def _args(results, protos, data):
    return ["--results-dir", str(results), "--protocols-dir", str(protos),
            "--data-dir", str(data)]


def test_summarise_metrics_agreement_and_false_negatives(workspace):
    results, data, protos = workspace
    summary = sm.summarise(results, protos, data)
    d = summary["datasets"]["D"]
    a = d["runs"]["A"]["metrics"]
    assert (a["tp"], a["fp"], a["tn"], a["fn"]) == (2, 1, 2, 1)
    assert a["recall"] == pytest.approx(2 / 3) and a["precision"] == pytest.approx(2 / 3)
    assert a["share_missing_abstract_screened"] == pytest.approx(1 / 6)
    assert d["runs"]["B"]["metrics"]["n_unscreened"] == 1
    agr = d["agreement_AB"]
    assert agr["n_compared"] == 5 and agr["n_disagreements"] == 1
    assert agr["kappa"] == pytest.approx(sm.cohens_kappa([1, 1, 0, 1, 0], [1, 0, 0, 1, 0]))
    assert d["missing_abstract"]["share_missing_abstract"] == pytest.approx(1 / 3)
    assert d["missing_abstract"]["source"] == "D.fetch.json"
    a_run = d["runs"]["A"]
    assert "false_negatives" not in a_run and "n_false_negatives" not in a_run
    ex = a_run["excluded_positives"]
    assert [f["record_id"] for f in ex["final"]] == [3] and ex["ta_non_final"] == []
    assert ex["final"][0]["has_abstract"] is False and ex["final"][0]["other_run"] == "B"
    assert ex["final"][0]["other_run_predicted"] == 0
    assert ex["final"][0]["other_run_status"] == "EXCLUDE"
    assert (a_run["n_excluded_final_inclusions"], a_run["n_excluded_ta_positives"]) == (1, 0)
    assert a_run["share_missing_abstract_excluded_positives"] == 1.0
    assert d["label_field_note"] and "label_included" in d["label_field_note"]


def test_figure4_rows_and_standalone_file(workspace):
    results, data, protos = workspace
    assert sm.main(_args(results, protos, data)) == 0
    fig = read_json(results / "figure4_screening.json")
    assert "generated" not in fig and "generated" not in read_json(results / "summary.json")
    assert "Generated" not in (results / "summary.md").read_text(encoding="utf-8")
    assert [r["series"] for r in fig["rows"]] == [
        "LLM run A", "LLM run B", "include-all", "TF-IDF (k matched)", "WoS gate"
    ]
    assert {"share_lower_bound", "share_upper_bound", "resolved"} <= set(fig["rows"][-1])
    row = fig["rows"][0]
    for key in ("dataset", "series", "n", "prevalence", "recall", "precision", "f1",
                "specificity", "inclusion_rate", "wss_at_achieved_recall", "kappa_AB"):
        assert key in row
    assert row["n"] == 6 and row["kappa_AB"] == fig["rows"][1]["kappa_AB"]
    assert fig["rows"][2]["kappa_AB"] is None
    assert read_json(results / "summary.json")["figure4"] == fig["rows"]


def test_markdown_headings_columns_and_no_categorisation_file(workspace):
    results, data, protos = workspace
    sm.main(_args(results, protos, data))
    md = (results / "summary.md").read_text(encoding="utf-8")
    for heading in ("Table E1-a", "Table E1-b", "Table E1-c", "Table E1-d", "Table E1-e"):
        assert heading in md
    assert "## Table E1-a. Screening performance on each protocol's gold label" in md
    assert "Missing abstract (share)" in md and "Cost basis" in md
    assert "upper bound" in md and "0.333" in md
    fn_md = (results / "D_false_negatives.md").read_text(encoding="utf-8")
    assert "Paper 3" in fn_md and "## Run A: excluded final inclusions (1)" in fn_md
    assert "## Run B: excluded final inclusions (2)" in fn_md and "run B: EXCLUDE" in fn_md
    assert "abstract: no" in fn_md
    # A run whose false negatives carry no coded category gets no categorisation file at
    # all, and summary.md then reports no category section.
    assert not (results / "D_fn_categories.csv").exists()
    assert "False-negative categories" not in md


def test_committed_fn_categories_are_read_and_never_rewritten(workspace):
    results, data, protos = workspace
    categories = results / "D_fn_categories.csv"
    body = (
        "dataset,run,record_id,title,reason,category,notes\n"
        "D,A,3,Paper 3,off topic,,\n"
    )
    categories.write_text(body, encoding="utf-8")
    sm.main(_args(results, protos, data))
    assert categories.read_text(encoding="utf-8") == body
    md = (results / "summary.md").read_text(encoding="utf-8")
    assert "False-negative categories - D" in md and "uncategorised" in md


def test_missing_abstract_falls_back_to_rows(workspace):
    results, data, protos = workspace
    (data / "D.fetch.json").unlink()
    d = sm.summarise(results, protos, data)["datasets"]["D"]
    assert d["missing_abstract"]["source"] == "rows"
    assert d["missing_abstract"]["share_missing_abstract"] == pytest.approx(1 / 6)


def test_no_runs_returns_1(tmp_path):
    assert sm.main(_args(tmp_path, tmp_path, tmp_path)) == 1


# ---------------------------------------------------------------- additional cases


def _padded_row(i, label, has_title=True):
    row = _row(i, label, 1)
    row["reason"] = "no decision returned"
    row["padded_include"] = True
    row["has_title"] = has_title
    return row


def test_padded_includes_are_counted_and_reported_both_ways(workspace):
    results, data, protos = workspace
    rows = [json.loads(x) for x in (results / "D_runA.jsonl").read_text("utf-8").splitlines()]
    rows[3] = _padded_row(4, 0)  # record 4: label 0, padded INCLUDE (was FP already)
    rows[0] = _padded_row(1, 1, has_title=False)  # record 1: label 1, padded INCLUDE (a TP)
    (results / "D_runA.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    summary = sm.summarise(results, protos, data)
    info = summary["datasets"]["D"]["runs"]["A"]
    m = info["metrics"]
    assert m["n_padded_include"] == 2 and m["n_missing_title"] == 1
    assert (m["tp"], m["fp"], m["tn"], m["fn"]) == (2, 1, 2, 1)  # as production returned them
    excl = info["metrics_padded_as_unscreened"]
    assert (excl["tp"], excl["fp"], excl["tn"], excl["fn"]) == (1, 0, 2, 1)
    assert excl["n_skipped"] == 2 and excl["recall"] == pytest.approx(0.5)
    series = [r["series"] for r in summary["figure4"]]
    assert "LLM run A (padded as unscreened)" in series
    assert "LLM run B (padded as unscreened)" not in series  # B has no padded rows
    md = sm.render_markdown(summary)
    assert "Padded INCLUDE" in md and "Missing title" in md
    assert "padded as unscreened" in md


def _padded_decision_row(i, label, predicted):
    """A row still flagged ``padded_decision`` (any status/predicted value): the broader
    flag, distinct from ``_padded_row``'s narrower ``padded_include``."""
    row = _row(i, label, predicted)
    row["reason"] = "no decision returned"
    row["padded_decision"] = True
    return row


def test_padded_decisions_are_counted_and_reported_strictly(workspace):
    """A row still flagged ``padded_decision`` (any status, not only the narrower
    ``padded_include``) is counted (``n_padded_decisions``) and has a strict-reading metrics
    variant (``metrics_padded_decision_as_unscreened``) that scores it as unscreened, with a
    matching figure4 row."""
    results, data, protos = workspace
    rows = [json.loads(x) for x in (results / "D_runA.jsonl").read_text("utf-8").splitlines()]
    # record 3: label 1, was a false negative (pred 0) -- also still padded_decision
    rows[2] = _padded_decision_row(3, 1, 0)
    # record 4: label 0, was a false positive (pred 1) -- also still padded_decision
    rows[3] = _padded_decision_row(4, 0, 1)
    (results / "D_runA.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    summary = sm.summarise(results, protos, data)
    info = summary["datasets"]["D"]["runs"]["A"]
    m = info["metrics"]
    assert m["n_padded_decisions"] == 2
    assert m["n_padded_include"] == 0  # neither padded row is a padded INCLUDE
    # unaffected: the padded_decision rows kept their own original confusion counts
    assert (m["tp"], m["fp"], m["tn"], m["fn"]) == (2, 1, 2, 1)
    strict = info["metrics_padded_decision_as_unscreened"]
    assert strict["n_skipped"] == 2
    assert (strict["tp"], strict["fp"], strict["tn"], strict["fn"]) == (2, 0, 2, 0)
    assert strict["recall"] == pytest.approx(1.0)
    series = [r["series"] for r in summary["figure4"]]
    assert "LLM run A (padded decisions as unscreened)" in series
    assert "LLM run B (padded decisions as unscreened)" not in series  # B has no such rows


def test_figure4_row_carries_n_padded_decisions_even_when_n_padded_include_is_zero(workspace):
    """``_figure4_row`` must not copy only ``n_padded_include`` (structurally 0 in
    production, since padding always lands on NEEDS_REVIEW, never on a predicted=1 row), or
    ``figure4_screening.json`` would have no field a consumer (Fig. 4) could read to see
    that a run had any padded (no-decision-returned) row at all. ``n_padded_decisions`` must
    be non-zero on both the ordinary ``LLM run A`` row and its strict ``(padded decisions as
    unscreened)`` row for a run that has padded rows but no padded includes."""
    results, data, protos = workspace
    rows = [json.loads(x) for x in (results / "D_runA.jsonl").read_text("utf-8").splitlines()]
    rows[2] = _padded_decision_row(3, 1, 0)
    rows[3] = _padded_decision_row(4, 0, 1)
    (results / "D_runA.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    summary = sm.summarise(results, protos, data)
    fig = summary["figure4"]
    ordinary = next(r for r in fig if r["series"] == "LLM run A")
    strict = next(r for r in fig if r["series"] == "LLM run A (padded decisions as unscreened)")
    assert ordinary["n_padded_include"] == 0
    assert ordinary["n_padded_decisions"] == 2
    assert strict["n_padded_decisions"] == 2


def test_kappa_undefined_rendered_as_dash_with_footnote(workspace):
    results, data, protos = workspace
    for run in ("A", "B"):
        rows = [_row(i, 1, 1) for i in range(1, 4)]
        (results / f"D_run{run}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), "utf-8"
        )
    summary = sm.summarise(results, protos, data)
    agr = summary["datasets"]["D"]["agreement_AB"]
    assert agr["kappa"] is None and agr["kappa_undefined"] is True
    assert agr["percent_agreement"] == 1.0
    md = sm.render_markdown(summary)
    assert "kappa undefined here: this column scores only the binary INCLUDE" in md
    assert "not the three-way INCLUDE/EXCLUDE/NEEDS_REVIEW status" in md
    row = (
        "| D | LLM run A | label_included | 3 | 1.000 | 1.000 | 1.000 | 1.000 | - | 1.000 "
        "| 0.000 | -0.050 | - |"
    )
    assert row in md


def test_kappa_undefined_note_does_not_claim_the_runs_are_identical(workspace):
    """B5 residual (second-pass review): the binary INCLUDE / not-INCLUDE decision can be
    constant in both runs (kappa undefined for Table E1-a's own column) while the runs still
    disagree on plenty of records' three-way status -- Table E1-e's own status kappa is
    defined and non-trivial in that case, exactly the shape production data takes whenever
    every protocol criterion defers to full text (no record is ever INCLUDE). The old
    "(constant runs)" wording claimed the two runs "gave the same decision for every record",
    which is false whenever this happens; the note must name the binary field as what is
    constant, not the runs."""
    results, data, protos = workspace
    statuses_a = ["EXCLUDE", "NEEDS_REVIEW", "EXCLUDE", "NEEDS_REVIEW", "EXCLUDE", "NEEDS_REVIEW"]
    statuses_b = ["NEEDS_REVIEW", "EXCLUDE", "EXCLUDE", "NEEDS_REVIEW", "NEEDS_REVIEW", "EXCLUDE"]
    labels = [1, 1, 1, 0, 0, 0]
    for run, statuses in (("A", statuses_a), ("B", statuses_b)):
        rows = [_status_row(i + 1, lab, st) for i, (lab, st) in enumerate(zip(labels, statuses))]
        (results / f"D_run{run}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
    summary = sm.summarise(results, protos, data)
    agr = summary["datasets"]["D"]["agreement_AB"]
    agr_status = summary["datasets"]["D"]["agreement_AB_status"]
    # No record is ever INCLUDE in either run, so the binary basis is constant -> undefined,
    # while the three-way status basis actually disagrees on several records -> defined.
    assert agr["kappa_undefined"] is True
    assert agr_status["kappa_undefined"] is False and agr_status["kappa"] is not None
    assert agr_status["n_disagreements"] > 0
    md = sm.render_markdown(summary)
    assert "kappa undefined here: this column scores only the binary INCLUDE" in md
    assert "does not mean the two runs are" in md
    assert "gave the same decision for every record" not in md
    # Table E1-b's own "% agreement A/B" column shares the same binary basis and reads
    # 1.000 here despite the runs disagreeing on half the records' three-way status.
    e1b_section = md.split("## Table E1-b")[1].split("## Table E1-e")[0]
    assert "1.000" in e1b_section
    assert "'% agreement A/B' is the same binary INCLUDE / not-INCLUDE basis" in e1b_section


def _gate(n, n_with_issn, n_in, all_share=0.5, all_n=100, all_with_issn=100):
    return {
        "included_records": {
            "n": n, "n_with_issn": n_with_issn, "n_unresolved": n - n_with_issn,
            "n_in_wos_any": n_in, "share_in_wos_any": n_in / n,
            "share_in_wos_any_of_resolved": (n_in / n_with_issn) if n_with_issn else None,
            "per_collection": {c: {"n": 0} for c in ("SCIE", "SSCI", "AHCI", "ESCI")},
        },
        "all_records": {
            "n": all_n, "n_with_issn": all_with_issn, "n_unresolved": all_n - all_with_issn,
            "share_in_wos_any": all_share,
        },
    }


def test_gate_table_partial_hydration_reports_both_bounds(workspace):
    results, data, protos = workspace
    # van_de_Schoot-like: 388 included, 336 resolved, 317 in WoS; 6189 records, 336 resolved
    write_json(results / "D_wos_gate.json", _gate(388, 336, 317, 317 / 6189, 6189, 336))
    fetch = read_json(data / "D.fetch.json")
    fetch["hydrate"] = "included"
    write_json(data / "D.fetch.json", fetch)
    summary = sm.summarise(results, protos, data)
    gate = summary["datasets"]["D"]["wos_gate_table"]
    assert gate["hydrate"] == "included" and gate["resolved"] == "336/388"
    assert gate["share_lower_bound"] == pytest.approx(317 / 388)  # unresolved = not in WoS
    # resolved-only is a point estimate (in WoS / resolved); the upper bound is the true
    # worst case, unresolved records assumed *inside* WoS: (in WoS + unresolved) / included
    assert gate["share_resolved_only"] == pytest.approx(317 / 336)
    assert gate["share_upper_bound"] == pytest.approx((317 + 52) / 388)
    assert gate["share_all_included"] is None  # 52 unresolved -> no single figure
    assert gate["all_records_share"] is None  # 336/6189 resolved < 0.9
    md = sm.render_markdown(summary)
    assert "| D | included | 388 | 336/388 | 317 | 0.817-0.951 (resolved-only 0.943) |" in md
    assert "lies between the lower bound" in md and "same-title" in md
    fig = [r for r in summary["figure4"] if r["series"] == "WoS gate"]
    assert fig and fig[0]["share_lower_bound"] == pytest.approx(317 / 388)
    assert fig[0]["share_resolved_only"] == pytest.approx(317 / 336)
    assert fig[0]["share_upper_bound"] == pytest.approx((317 + 52) / 388)
    # fully hydrated dataset (route v2): a single value, all three coincide
    write_json(results / "D_wos_gate.json", _gate(27, 27, 20, 0.8, 100, 95))
    fetch["hydrate"] = "openalex_id"
    write_json(data / "D.fetch.json", fetch)
    summary = sm.summarise(results, protos, data)
    gate = summary["datasets"]["D"]["wos_gate_table"]
    assert gate["share_all_included"] == pytest.approx(20 / 27)
    assert (gate["share_lower_bound"] == gate["share_upper_bound"]
            == gate["share_resolved_only"] == pytest.approx(20 / 27))
    assert gate["all_records_share"] == 0.8 and gate["hydrate"] == "openalex_id"
    assert "| D | openalex_id | 27 | 27/27 | 20 | 0.741 |" in sm.render_markdown(summary)


def test_gate_table_row_upper_bound_assumes_unresolved_records_are_in_wos():
    """share_upper_bound must be the true worst-case ceiling, not the resolved-only rate."""
    gate = sm.gate_table_row(_gate(10, 6, 4), None)
    assert gate["share_lower_bound"] == pytest.approx(0.4)
    assert gate["share_resolved_only"] == pytest.approx(4 / 6)
    assert gate["share_upper_bound"] == pytest.approx(0.8)


def test_prov_table_records_concurrency_and_latency_note(workspace):
    results, data, protos = workspace
    for run in ("A", "B"):
        m = read_json(results / f"D_run{run}.meta.json")
        m["concurrency"] = 8
        write_json(results / f"D_run{run}.meta.json", m)
    md = sm.render_markdown(sm.summarise(results, protos, data))
    assert "Concurrency" in md and "| 8 |" in md
    assert "wall-clock per batch" in md and "in flight" in md


def test_prov_table_counts_distinct_system_fingerprints(workspace):
    """Table E1-c must carry a 'Fingerprints' column so a served-model change
    mid-run is visible in the table a reviewer actually reads, matching Table E2-c."""
    results, data, protos = workspace
    meta = read_json(results / "D_runA.meta.json")
    meta["system_fingerprints"] = ["fp_a", "fp_b"]
    write_json(results / "D_runA.meta.json", meta)
    md = sm.render_markdown(sm.summarise(results, protos, data))
    assert "Fingerprints" in md
    header_idx = sm.PROV_HEADERS.index("Fingerprints")
    prov_section = md.split("## Table E1-c")[1]
    row = next(line for line in prov_section.splitlines() if line.startswith("| D | A |"))
    cell = [c.strip() for c in row.strip("|").split("|")][header_idx]
    assert cell == "2"


def test_prov_table_cost_is_not_double_rounded(workspace):
    """0.17351378 rounds correctly to 0.174 at the table's 3-decimal display precision in one
    step; rounding to 4 decimals first (0.1735) and formatting that at 3 decimals gives 0.173,
    because 0.1735 is not exactly representable in binary floating point. Table E1-c must show
    the correctly-rounded value, not the double-rounded one."""
    results, data, protos = workspace
    meta = read_json(results / "D_runA.meta.json")
    meta["total_cost"] = 0.17351378
    write_json(results / "D_runA.meta.json", meta)
    assert round(round(meta["total_cost"], 4), 3) == 0.173  # the bug this test guards against
    md = sm.render_markdown(sm.summarise(results, protos, data))
    header_idx = sm.PROV_HEADERS.index("Cost (USD)")
    prov_section = md.split("## Table E1-c")[1]
    row = next(line for line in prov_section.splitlines() if line.startswith("| D | A |"))
    cell = [c.strip() for c in row.strip("|").split("|")][header_idx]
    assert cell == "0.174"


def test_baseline_row_states_query_mode(workspace):
    results, data, protos = workspace
    base = read_json(results / "D_baselines.json")
    base["query_mode"] = "rq"
    write_json(results / "D_baselines.json", base)
    summary = sm.summarise(results, protos, data)
    md = sm.render_markdown(summary)
    assert "TF-IDF (k=3, query=rq)" in md
    assert any(r["series"] == "TF-IDF (k matched)" and r.get("query_mode") == "rq"
               for r in summary["figure4"])


# ---------------------------------------------------------------- additional cases


def test_label_field_note_discloses_human_label_noise_for_both_label_fields():
    """The gold labels are SYNERGY's own screening decisions, not a re-annotation for this
    evaluation, and SYNERGY publishes no inter-screener agreement; that limitation must be
    visible under Table E1-a regardless of which label field a dataset uses."""
    for label_field in ("label_abstract_screening", "label_included", None):
        note = sm.label_field_note(label_field)
        assert "not a re-annotation" in note or "human label noise" in note
        assert "van_de_Schoot_2017" in note and "over-inclusive" in note
        assert "within a dataset" in note, (
            "the over-inclusive criterion is also passed to the screener in the prompt, so it "
            "raises van_de_Schoot_2017's recall too; recall must be qualified as safe only "
            "within a dataset, not as a cross-dataset ranking"
        )


def test_committed_screening_summary_contains_label_noise_note_verbatim():
    """The committed evaluation/screening/results/v3/summary.md must carry LABEL_NOISE_NOTE
    verbatim (not just the module constant), so a reviewer reading the static file alone sees
    the label-provenance caveat next to every dataset's recall/precision numbers."""
    md = (sm.HERE / "results" / "v3" / "summary.md").read_text(encoding="utf-8")
    assert sm.LABEL_NOISE_NOTE in md


# ---------------------------------------------------------------- metrics_primary


def _status_row(
    i, label, status, has_abstract=True, called_at="2026-09-02T12:00:00+00:00",
    criterion=None, guard_reason="", to_confirm=None,
):
    # "predicted" mirrors the real row schema: 1 only for status == "INCLUDE" (run_screening.py
    # sets predicted = int(bool(include[i])), and include[i] is status == "INCLUDE").
    row = _row(i, label, 1 if status == "INCLUDE" else 0,
               has_abstract=has_abstract, called_at=called_at)
    row["status"] = status
    row["criterion"] = criterion if criterion is not None else ("E1" if status == "EXCLUDE" else "")
    row["quote"] = "a quote" if status == "EXCLUDE" else ""
    row["guard_applied"] = bool(guard_reason)
    row["guard_reason"] = guard_reason
    row["to_confirm"] = to_confirm if to_confirm is not None else []
    return row


def test_metrics_primary_and_sensitivity_blocks_and_wilson_intervals(workspace):
    results, data, protos = workspace
    proto = json.loads((protos / "D.json").read_text(encoding="utf-8"))
    proto["primary_label"] = "label_included"
    (protos / "D.json").write_text(json.dumps(proto), encoding="utf-8")
    # labels: [1,1,1,0,0,0]; statuses: INCLUDE, NEEDS_REVIEW, EXCLUDE, EXCLUDE, INCLUDE, EXCLUDE
    statuses = ["INCLUDE", "NEEDS_REVIEW", "EXCLUDE", "EXCLUDE", "INCLUDE", "EXCLUDE"]
    labels = [1, 1, 1, 0, 0, 0]
    rows = [_status_row(i + 1, lab, st) for i, (lab, st) in enumerate(zip(labels, statuses))]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["label_field"] == "label_included"
    assert mp["n_positive"] == 3
    # include-only: predicted 1 for records 1 and 5 -> tp=1 (record1), fn=2 -> recall 1/3
    assert mp["recall_include_only"] == pytest.approx(1 / 3)
    # screened-in: INCLUDE or NEEDS_REVIEW -> records 1,2,5 predicted positive -> tp=2 -> 2/3
    assert mp["recall_screened_in"] == pytest.approx(2 / 3)
    assert mp["recall_screened_in"] >= mp["recall_include_only"]
    lo, hi = mp["recall_include_only_wilson"]
    assert lo == pytest.approx(sm.wilson_interval(1, 3)[0])
    assert hi == pytest.approx(sm.wilson_interval(1, 3)[1])
    assert mp["needs_review_rate"] == pytest.approx(1 / 6)
    assert mp["screened_in_rate"] == pytest.approx(3 / 6)  # records 1,2,5 screened in

    ms = summary["datasets"]["D"]["runs"]["A"]["metrics_sensitivity"]
    assert ms is None  # no row carries label_abstract_screening in this fixture


# ---------------------------------------------------------------- five-column report


def test_metrics_primary_reports_the_five_column_final_inclusion_basis(workspace):
    """Retained recall's own work-saved figure, auto-inclusion precision (with its own n)
    and queue precision, all on the label_field basis metrics_primary was called with. The
    same fixture as the Wilson-interval test above."""
    results, data, protos = workspace
    statuses = ["INCLUDE", "NEEDS_REVIEW", "EXCLUDE", "EXCLUDE", "INCLUDE", "EXCLUDE"]
    labels = [1, 1, 1, 0, 0, 0]
    rows = [_status_row(i + 1, lab, st) for i, (lab, st) in enumerate(zip(labels, statuses))]
    mp = sm.metrics_primary(rows, "label_included")

    # counts_include: tp=1 (record 1), fp=1 (record 5), fn=2 (records 2, 3), tn=2 (4, 6)
    assert mp["auto_inclusion_precision"] == pytest.approx(0.5)
    assert mp["auto_inclusion_n"] == 2

    # counts_screened (INCLUDE or NEEDS_REVIEW): tp=2 (1, 2), fp=1 (5), fn=1 (3), tn=2 (4, 6)
    # retained recall = 2/3 (already asserted above); WSS = (tn+fn)/n - (1-recall)
    assert mp["wss_at_achieved_retained_recall"] == pytest.approx(3 / 6 - (1 - 2 / 3))

    # queue: one NEEDS_REVIEW row (record 2), label_included=1 -> precision 1/1
    assert mp["queue_precision"] == pytest.approx(1.0)
    assert mp["queue_precision_n"] == 1


def test_metrics_primary_auto_inclusion_precision_is_none_with_no_includes(workspace):
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW"),
        _status_row(2, 0, "EXCLUDE"),
    ]
    mp = sm.metrics_primary(rows, "label_included")
    assert mp["auto_inclusion_precision"] is None
    assert mp["auto_inclusion_n"] == 0


def test_metrics_primary_queue_precision_is_none_with_no_needs_review_rows(workspace):
    rows = [
        _status_row(1, 1, "INCLUDE"),
        _status_row(2, 0, "EXCLUDE"),
    ]
    mp = sm.metrics_primary(rows, "label_included")
    assert mp["queue_precision"] is None
    assert mp["queue_precision_n"] == 0


def test_final_inclusion_table_renders_with_the_five_columns(workspace):
    results, data, protos = workspace
    statuses = ["INCLUDE", "NEEDS_REVIEW", "EXCLUDE", "EXCLUDE", "INCLUDE", "EXCLUDE"]
    labels = [1, 1, 1, 0, 0, 0]
    rows = [_status_row(i + 1, lab, st) for i, (lab, st) in enumerate(zip(labels, statuses))]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (results / "D_runB.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    md = sm.render_markdown(summary)
    assert "Table E1-e" in md
    # retained recall 2/3, screened-in share 3/6=0.5, auto-inclusion precision 0.5 (n=2)
    assert "0.667" in md and "0.500" in md
    assert "(n = 2)" in md
    # A and B are byte-identical rows here, so status agreement is perfect: kappa 1.0
    assert "1.000" in md


def test_final_inclusion_table_prints_none_n_zero_with_no_auto_inclusions(workspace):
    """Every unconfirmed full-text inclusion criterion routes to NEEDS_REVIEW, never
    INCLUDE, so a run with zero INCLUDE decisions must print 'none, n = 0' for
    auto-inclusion precision, not a stray 0.000 that reads as "the auto-included set is 0%
    precise" rather than "there is no such set"."""
    results, data, protos = workspace
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW"),
        _status_row(2, 0, "EXCLUDE"),
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (results / "D_runB.jsonl").unlink()
    summary = sm.summarise(results, protos, data)
    md = sm.render_markdown(summary)
    assert "none, n = 0" in md


# ---------------------------------------------------------------- baseline rows in E1-e


def test_baseline_final_inclusion_row_reports_recall_share_wss_and_precision():
    """A non-LLM baseline (include-all or TF-IDF) has no NEEDS_REVIEW queue and no second
    run: its retained recall is simply its recall, its screened-in share its inclusion
    rate, and its Queue precision / A/B agreement cells are '-'. The trailing WSS@95
    (ranking) cell is populated only when a ranking value is passed in."""
    # n=6, prevalence=0.5 (3 positives): tp=3 fp=3 fn=0 tn=0 -> recall=1.0 precision=0.5
    include_all = {
        "n": 6, "tp": 3, "fp": 3, "tn": 0, "fn": 0, "recall": 1.0, "precision": 0.5,
        "inclusion_rate": 1.0, "wss_at_achieved_recall": 0.0,
    }
    row = sm._baseline_final_inclusion_row("D", "include-all", include_all)
    assert row == ["D", "include-all", 6, 1.0, "[0.439, 1.000]", 1.0, 0.0, 0.0,
                    "0.500 (n = 6)", "-", "-", None]

    # tp=2 fp=1 fn=1 tn=2 -> recall=2/3 precision=2/3 inclusion_rate=0.5
    tfidf = {
        "n": 6, "tp": 2, "fp": 1, "tn": 2, "fn": 1, "recall": 2 / 3, "precision": 2 / 3,
        "inclusion_rate": 0.5, "wss_at_achieved_recall": pytest.approx(3 / 6 - 1 / 3),
    }
    tfidf["wss_at_achieved_recall"] = 3 / 6 - 1 / 3
    row = sm._baseline_final_inclusion_row("D", "TF-IDF (k=3)", tfidf, 0.2)
    assert row[0:4] == ["D", "TF-IDF (k=3)", 6, pytest.approx(2 / 3)]
    assert row[5] == pytest.approx(0.5)
    assert row[6] == pytest.approx(0.5)  # excluded share, 1 - inclusion rate
    assert row[8] == "0.667 (n = 3)"
    assert row[9] == "-" and row[10] == "-"
    assert row[11] == 0.2  # the ranking's own WSS@95, independent of the matched threshold


def test_baseline_final_inclusion_row_prints_none_n_zero_when_nothing_included():
    m = {"n": 4, "tp": 0, "fp": 0, "tn": 4, "fn": 0, "recall": None, "precision": None,
         "inclusion_rate": 0.0, "wss_at_achieved_recall": 1.0}
    row = sm._baseline_final_inclusion_row("D", "include-none", m)
    assert row[8] == "none, n = 0"


def test_final_inclusion_table_carries_a_baseline_row_beside_the_model_rows(workspace):
    """Table E1-e must carry an include-all and a TF-IDF baseline row per dataset, beside
    (not instead of) the LLM run rows, with the trailing WSS@95 (ranking) column populated
    only for the TF-IDF row."""
    results, data, protos = workspace
    base = read_json(results / "D_baselines.json")
    base["include_all"].update({"tp": 3, "fp": 3, "tn": 0, "fn": 0})
    base["tfidf"]["metrics"].update({"tp": 2, "fp": 1, "tn": 2, "fn": 1})
    base["tfidf"]["wss_at_95_ranking"] = 0.2
    write_json(results / "D_baselines.json", base)
    summary = sm.summarise(results, protos, data)
    md = sm.render_markdown(summary)
    e1e_section = md.split("## Table E1-e")[1].split("## Table E1-c")[0]
    assert "| D | include-all | 6 |" in e1e_section
    assert "| D | TF-IDF (k=3, query=rq+criteria) | 6 |" in e1e_section
    tfidf_row = next(
        line for line in e1e_section.splitlines() if line.startswith("| D | TF-IDF")
    )
    assert tfidf_row.strip().endswith("| 0.200 |")
    include_all_row = next(
        line for line in e1e_section.splitlines() if line.startswith("| D | include-all")
    )
    assert include_all_row.strip().endswith("| - |")  # no ranking WSS@95 for include-all
    fig = summary["figure4"]
    baseline_series = [r["series"] for r in fig if r["dataset"] == "D"]
    assert "include-all" in baseline_series and "TF-IDF (k matched)" in baseline_series


def test_table_e1a_carries_retained_recall_and_flags_structural_zero(workspace):
    """B5: Table E1-a itself (not only Table E1-e) must carry the retained-recall basis, and
    must say plainly when its own INCLUDE-only Recall/Precision/WSS columns read 0.000 only
    because a full-text inclusion criterion cannot be confirmed from title and abstract, not
    because the screener found nothing -- a bare 0.000 with no such note reads as a failing
    screener."""
    results, data, protos = workspace
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW"),
        _status_row(2, 0, "EXCLUDE"),
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (results / "D_runB.jsonl").unlink()
    summary = sm.summarise(results, protos, data)
    mfi = summary["datasets"]["D"]["runs"]["A"]["metrics_final_inclusion"]
    assert mfi["auto_inclusion_n"] == 0 and mfi["recall_screened_in"] == pytest.approx(1.0)
    md = sm.render_markdown(summary)
    assert "Retained recall (final inclusions)" in md  # E1-a trailing columns
    assert "Structurally zero" in md
    e1a_section = md.split("## Table E1-a")[1].split("## Table E1-b")[0]
    assert sm.fmt(mfi["recall_screened_in"]) in e1a_section


def test_figure4_llm_run_rows_carry_retained_recall_and_a_non_null_status_kappa(workspace):
    """B5: figure4_screening.json (the manuscript figure input) must carry the
    retained-recall basis with its Wilson interval on every 'LLM run X' row, and its status
    kappa (kappa_AB_status) must not be null merely because the INCLUDE-only kappa_AB is
    undefined by construction on a protocol naming a full-text inclusion criterion."""
    results, data, protos = workspace
    statuses_a = ["INCLUDE", "NEEDS_REVIEW", "EXCLUDE", "EXCLUDE", "INCLUDE", "EXCLUDE"]
    statuses_b = ["INCLUDE", "EXCLUDE", "EXCLUDE", "EXCLUDE", "INCLUDE", "NEEDS_REVIEW"]
    labels = [1, 1, 1, 0, 0, 0]
    for run, statuses in (("A", statuses_a), ("B", statuses_b)):
        rows = [_status_row(i + 1, lab, st) for i, (lab, st) in enumerate(zip(labels, statuses))]
        (results / f"D_run{run}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
    summary = sm.summarise(results, protos, data)
    status_kappa = summary["datasets"]["D"]["agreement_AB_status"]["kappa"]
    assert status_kappa is not None
    fig = summary["figure4"]
    run_a = next(r for r in fig if r["series"] == "LLM run A")
    assert run_a["kappa_AB_status"] == status_kappa
    assert run_a["retained_recall"] is not None
    assert run_a["retained_recall_wilson_lo"] is not None
    assert run_a["retained_recall_wilson_hi"] is not None
    assert run_a["queue_precision"] is not None or run_a["auto_inclusion_n"] is not None


# ---------------------------------------------------------------- needs_review_by_*, D3


def test_metrics_primary_reports_needs_review_by_reason_and_criterion(workspace):
    results, data, protos = workspace
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW", guard_reason="full_text_criterion", criterion="E1"),
        _status_row(2, 1, "NEEDS_REVIEW", guard_reason="cut_abstract", criterion="E2"),
        _status_row(3, 1, "NEEDS_REVIEW", guard_reason=""),  # genuine model NEEDS_REVIEW
        _status_row(4, 0, "EXCLUDE"),
        _status_row(5, 0, "INCLUDE"),
        _status_row(6, 0, "INCLUDE"),
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["needs_review_by_reason"] == {
        "full_text_criterion": 1, "cut_abstract": 1, "undecidable": 1,
    }
    assert mp["needs_review_by_criterion"] == {"E1": 1, "E2": 1}
    assert mp["n_needs_review_full_text"] == 1


def test_metrics_primary_d3_counts_every_abstract_bearing_record_no_exemption(workspace):
    """D3 is the needs-review rate over ALL abstract-bearing records. A full-text exclusion
    criterion can ground a NEEDS_REVIEW today only behind explicit contrary evidence, the
    screener working as designed, so nothing is exempted from either the numerator or the
    denominator."""
    results, data, protos = workspace
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW", guard_reason="full_text_criterion"),  # counted
        _status_row(2, 1, "NEEDS_REVIEW", guard_reason="unquoted_criterion"),  # counted
        _status_row(3, 1, "NEEDS_REVIEW", guard_reason=""),  # counted: genuine, abstract
        _status_row(4, 1, "INCLUDE"),  # counted: not needs-review, abstract
        _status_row(5, 0, "EXCLUDE", has_abstract=False),  # excluded: no abstract
        _status_row(6, 0, "INCLUDE"),
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    # denominator: records 1,2,3,4,6 (abstract-bearing) = 5; numerator: records 1,2,3 = 3
    assert mp["needs_review_rate_abstract_bearing"] == pytest.approx(3 / 5)
    # the plain needs_review_rate is over all 6 rows regardless of abstract
    assert mp["needs_review_rate"] == pytest.approx(3 / 6)


def test_metrics_primary_needs_review_by_reason_trusts_only_the_rows_own_guard_reason(workspace):
    """``needs_review_by_reason``/``n_needs_review_full_text`` read only the row's own
    ``guard_reason`` column. The guard always attributes "full_text_criterion" or
    "unquoted_criterion" when a full-text criterion routes a record to NEEDS_REVIEW, so a
    criterion named with no ``guard_reason`` is not treated specially: it buckets as an
    ordinary undecided record, with no protocol lookup involved at all."""
    results, data, protos = workspace
    proto = json.loads((protos / "D.json").read_text(encoding="utf-8"))
    proto["exclusion_criteria"] = [
        {"text": "e1", "stage": "full_text", "stage_rationale": "cannot judge from abstract"},
        "e2",
    ]
    (protos / "D.json").write_text(json.dumps(proto), encoding="utf-8")
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW", guard_reason="", criterion="E1"),
        _status_row(2, 1, "NEEDS_REVIEW", guard_reason="full_text_criterion", criterion="E1"),
        _status_row(3, 1, "INCLUDE"),
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["needs_review_by_reason"] == {"undecidable": 1, "full_text_criterion": 1}
    assert mp["n_needs_review_full_text"] == 1


def test_metrics_primary_d3_reads_rows_with_no_guard_reason_column_at_all(workspace):
    """A row schema predating per-row ``guard_reason`` attribution entirely (the column is
    absent, not merely empty -- the shape every screener run had before that attribution
    existed) must still score correctly: ``r.get("guard_reason") or ""`` treats a missing
    column exactly like an empty one, so D3 still counts every abstract-bearing NEEDS_REVIEW
    row with no exemption and no protocol cross-reference."""
    results, data, protos = workspace
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW"),  # guard-silent, abstract-bearing: undecidable
        _status_row(2, 1, "NEEDS_REVIEW", has_abstract=False),  # no_abstract
        _status_row(3, 1, "INCLUDE"),  # abstract-bearing, not needs-review
        _status_row(4, 0, "EXCLUDE"),  # abstract-bearing, not needs-review
    ]
    for row in rows:
        del row["guard_reason"]  # the historical schema carries no such column at all
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    # denominator: records 1,3,4 (abstract-bearing) = 3; numerator: record 1 = 1
    assert mp["needs_review_rate_abstract_bearing"] == pytest.approx(1 / 3)
    assert mp["needs_review_by_reason"] == {"undecidable": 1, "no_abstract": 1}


def test_metrics_primary_buckets_a_needs_review_row_with_no_abstract_separately(workspace):
    """The harness must use "no_abstract", matching the product path
    (``run_smart_search``), instead of folding every guard-silent NEEDS_REVIEW into
    "undecidable" regardless of whether the record had an abstract at all."""
    results, data, protos = workspace
    rows = [
        _status_row(1, 1, "NEEDS_REVIEW", guard_reason="", has_abstract=False),
        _status_row(2, 1, "NEEDS_REVIEW", guard_reason=""),  # has an abstract: still undecidable
        _status_row(3, 0, "INCLUDE"),
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["needs_review_by_reason"] == {"no_abstract": 1, "undecidable": 1}


def test_metrics_primary_merges_the_guards_own_no_abstract_reason_with_the_fallback_bucket(
    workspace,
):
    """The screener's guard attributes ``"no_abstract"`` itself (an EXCLUDE on a no-abstract
    record, demoted unconditionally), the same slug this harness already uses as its
    guard-silent fallback for a no-abstract record. ``needs_review_by_reason`` reads only
    ``guard_reason`` (or the fallback when it is empty), so both kinds of row land in the
    same bucket without any code change here."""
    results, data, protos = workspace
    rows = [
        # the guard's own attribution: a demoted EXCLUDE, so guard_reason is non-empty
        _status_row(1, 1, "NEEDS_REVIEW", guard_reason="no_abstract", has_abstract=False),
        # the pre-existing guard-silent fallback: a genuine model NEEDS_REVIEW, no attribution
        _status_row(2, 1, "NEEDS_REVIEW", guard_reason="", has_abstract=False),
        _status_row(3, 0, "INCLUDE"),
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["needs_review_by_reason"] == {"no_abstract": 2}


def test_metrics_primary_reports_to_confirm_rate_and_breakdown(workspace):
    """The share of INCLUDE decisions carrying a non-empty ``to_confirm`` note, broken down
    by criterion id (one INCLUDE naming two ids contributes to both), no threshold."""
    results, data, protos = workspace
    rows = [
        _status_row(1, 1, "INCLUDE", to_confirm=["I1", "I3"]),
        _status_row(2, 1, "INCLUDE", to_confirm=["I1"]),
        _status_row(3, 1, "INCLUDE"),  # no to_confirm
        _status_row(4, 0, "EXCLUDE"),  # not an INCLUDE: never counted either way
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["to_confirm_by_criterion"] == {"I1": 2, "I3": 1}
    # 2 of 3 INCLUDE decisions carry a non-empty to_confirm note
    assert mp["to_confirm_rate"] == pytest.approx(2 / 3)


def test_metrics_primary_to_confirm_rate_is_none_with_no_include_rows(workspace):
    results, data, protos = workspace
    rows = [_status_row(1, 1, "EXCLUDE"), _status_row(2, 1, "NEEDS_REVIEW")]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["to_confirm_rate"] is None
    assert mp["to_confirm_by_criterion"] == {}


def test_metrics_primary_d3_is_none_when_no_row_has_an_abstract(workspace):
    results, data, protos = workspace
    rows = [
        _status_row(i, 1, "NEEDS_REVIEW", guard_reason="full_text_criterion", has_abstract=False)
        for i in (1, 2)
    ]
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["needs_review_rate_abstract_bearing"] is None


def test_metrics_primary_reports_n_padded_decisions(workspace):
    """A row the model never returned a decision for (``padded_decision``) must be visible
    in ``metrics_primary``, not silently scored as a genuine NEEDS_REVIEW with no trace of
    the padding anywhere in the summary."""
    results, data, protos = workspace
    statuses = ["INCLUDE", "NEEDS_REVIEW", "EXCLUDE", "EXCLUDE", "INCLUDE", "EXCLUDE"]
    labels = [1, 1, 1, 0, 0, 0]
    rows = [_status_row(i + 1, lab, st) for i, (lab, st) in enumerate(zip(labels, statuses))]
    rows[1]["padded_decision"] = True  # record 2's NEEDS_REVIEW is a padded non-decision
    (results / "D_runA.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    summary = sm.summarise(results, protos, data)
    mp = summary["datasets"]["D"]["runs"]["A"]["metrics_primary"]
    assert mp["n_padded_decisions"] == 1
    # the padded row is still counted as screened-in / needs-review above (documented, not a
    # bug): n_padded_decisions lets a caller subtract it, it does not change these two.
    assert mp["recall_screened_in"] == pytest.approx(2 / 3)
    assert mp["needs_review_rate"] == pytest.approx(1 / 6)


def test_metrics_primary_falls_back_to_predicted_when_rows_carry_no_status(workspace):
    """The six already-committed v1 runs have no ``status`` column at all; ``metrics_primary``
    must still compute (falling back to the binary ``predicted``), and its
    ``recall_include_only`` must equal the existing ``final_inclusion_recall`` on the same
    rows, since both are recall of ``predicted`` against ``label_included``."""
    results, data, protos = workspace
    summary = sm.summarise(results, protos, data)
    info = summary["datasets"]["D"]["runs"]["A"]
    assert info["metrics_primary"]["recall_include_only"] == pytest.approx(
        info["metrics"]["final_inclusion_recall"]
    )
    assert info["metrics_primary"]["recall_screened_in"] == info["metrics_primary"][
        "recall_include_only"
    ]


def test_metrics_primary_uses_the_documented_default_when_primary_label_is_absent(workspace):
    """``Smid_2020``/``van_de_Schoot_2017``-style protocols with no explicit ``primary_label``
    key must default to ``label_included`` (protocols/README.md's documented default)."""
    results, data, protos = workspace
    proto = json.loads((protos / "D.json").read_text(encoding="utf-8"))
    assert "primary_label" not in proto
    summary = sm.summarise(results, protos, data)
    assert summary["datasets"]["D"]["protocol"]["primary_label"] == "label_included"


def test_agreement_status_falls_back_to_predicted_and_differs_from_binary_when_it_can(workspace):
    results, data, protos = workspace
    statuses_a = ["INCLUDE", "NEEDS_REVIEW", "EXCLUDE", "EXCLUDE", "INCLUDE", "EXCLUDE"]
    statuses_b = ["INCLUDE", "EXCLUDE", "EXCLUDE", "EXCLUDE", "INCLUDE", "EXCLUDE"]
    labels = [1, 1, 1, 0, 0, 0]
    for run, statuses in (("A", statuses_a), ("B", statuses_b)):
        rows = [_status_row(i + 1, lab, st) for i, (lab, st) in enumerate(zip(labels, statuses))]
        (results / f"D_run{run}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
    summary = sm.summarise(results, protos, data)
    entry = summary["datasets"]["D"]
    # binary agreement_AB (predicted 0/1) never sees the INCLUDE/NEEDS_REVIEW distinction
    assert entry["agreement_AB"]["kappa"] == 1.0
    # three-way agreement_AB_status does, and differs
    assert entry["agreement_AB_status"]["kappa"] != entry["agreement_AB"]["kappa"]
    assert entry["agreement_AB_status"]["n_disagreements"] == 1


def test_agreement_ab_is_unchanged_by_key_default(workspace):
    """``agreement()`` called with no ``key`` argument must be byte-identical to the default
    behaviour (predicted-only), so the six committed runs' ``agreement_AB`` never moves."""
    results, data, protos = workspace
    rows_a = [json.loads(x) for x in (results / "D_runA.jsonl").read_text("utf-8").splitlines()]
    rows_b = [json.loads(x) for x in (results / "D_runB.jsonl").read_text("utf-8").splitlines()]
    assert sm.agreement(rows_a, rows_b) == sm.agreement(rows_a, rows_b, key="predicted")


def test_summarise_on_rows_with_no_status_column_still_computes_agreement_and_new_blocks(
    workspace,
):
    """Backward-compatibility regression: a run file with no ``status`` column (the schema
    every screener run had before the three-way INCLUDE/EXCLUDE/NEEDS_REVIEW status existed,
    matching the shipped screener's earliest committed runs) must still let ``summarise()``
    compute ``agreement_AB`` (predicted-only, since there is no status to compare) and gain
    the newer ``metrics_primary``/``metrics_sensitivity``/``agreement_AB_status`` siblings
    without raising."""
    results, data, protos = workspace
    fresh = sm.summarise(results, protos, data)
    info_a = fresh["datasets"]["D"]["runs"]["A"]
    assert set(
        ["file", "metrics", "metrics_padded_as_unscreened", "n_excluded_final_inclusions",
         "n_excluded_ta_positives", "excluded_positives",
         "share_missing_abstract_excluded_positives", "meta"]
    ) <= set(info_a.keys())
    assert {"metrics_primary", "metrics_sensitivity"} <= set(info_a.keys())
    assert fresh["datasets"]["D"]["agreement_AB"] is not None
    # agreement_AB_status falls back to "predicted" for a row with no status column, so it
    # is always computable and equals agreement_AB exactly wherever no row carries a status.
    assert fresh["datasets"]["D"]["agreement_AB_status"] == fresh["datasets"]["D"]["agreement_AB"]
    assert info_a["metrics_primary"]["recall_include_only"] == pytest.approx(
        info_a["metrics"]["final_inclusion_recall"]
    )


def test_label_field_note_appears_in_generated_summary_md(workspace):
    results, data, protos = workspace  # protocol label_field = "label_included"
    md = sm.render_markdown(sm.summarise(results, protos, data))
    assert "human label noise" in md and "van_de_Schoot_2017" in md
    proto = json.loads((protos / "D.json").read_text(encoding="utf-8"))
    proto["label_field"] = "label_abstract_screening"
    (protos / "D.json").write_text(json.dumps(proto), encoding="utf-8")
    md = sm.render_markdown(sm.summarise(results, protos, data))
    assert "human label noise" in md and "van_de_Schoot_2017" in md


# ---------------------------------------------------------------- additional cases


def test_missing_abstract_note_reads_the_cap_from_run_meta(workspace):
    """Table E1-b's truncation sentence must read the run's own abstract_cap rather than a
    hardcoded figure -- production's cap changed from 500 to 10,000 characters and the
    sentence must track whatever a future run's meta records, not a fixed number."""
    results, data, protos = workspace
    for run in ("A", "B"):
        meta_path = results / f"D_run{run}.meta.json"
        meta = read_json(meta_path)
        meta["abstract_cap"] = 10000
        write_json(meta_path, meta)
    md = sm.render_markdown(sm.summarise(results, protos, data))
    assert "truncates abstracts to 10,000 characters" in md
    assert "500 characters" not in md


def test_missing_abstract_note_falls_back_when_no_run_carries_abstract_cap(workspace):
    """A run whose meta carries no abstract_cap at all (e.g. an older run) must not print a
    stale hardcoded number; it falls back to naming the cap as configured, not a value."""
    results, data, protos = workspace  # the workspace fixture's _meta() carries no abstract_cap
    md = sm.render_markdown(sm.summarise(results, protos, data))
    assert "truncates abstracts to a configured character cap" in md
    assert "500 characters" not in md
    assert "characters." not in md.replace("a configured character cap.", "")


def test_committed_v3_summary_md_matches_render_markdown_on_the_abstract_cap_line():
    """The shipped evaluation/screening/results/v3/summary.md already reports the real
    10,000-character cap; render_markdown(summary.json) must reproduce that exact sentence,
    proving the fix (not just a synthetic fixture) matches the committed artifact."""
    results_dir = sm.HERE / "results" / "v3"
    summary = read_json(results_dir / "summary.json")
    md = sm.render_markdown(summary)
    shipped_md = (results_dir / "summary.md").read_text(encoding="utf-8")
    line = next(l for l in md.splitlines() if l.startswith("Missing abstract (share)"))
    shipped_line = next(
        l for l in shipped_md.splitlines() if l.startswith("Missing abstract (share)")
    )
    assert line == shipped_line
    assert "truncates abstracts to 10,000 characters" in line


def test_main_exits_non_zero_on_a_results_dir_with_no_run_files(tmp_path, capsys):
    """A results directory holding no run files at all (wrong or stale --results-dir)
    must fail loudly instead of writing a summary with no datasets."""
    results, data, protos = tmp_path / "results", tmp_path / "data", tmp_path / "protocols"
    for d in (results, data, protos):
        d.mkdir()
    rc = sm.main(_args(results, protos, data))
    assert rc == 1
    assert not (results / "summary.json").exists()
    assert "no run files found" in capsys.readouterr().out


def test_default_results_dir_is_the_result_of_record():
    """RESULTS_DIR must point at results/v3 (the directory of record,
    evaluation/README.md "Results directories"), not another results directory, so a bare
    invocation with no --results-dir reads the right data."""
    assert sm.RESULTS_DIR == sm.HERE / "results" / "v3"


# ---------------------------------------------------------------- deduplicated basis (Task 3)

VDS = "van_de_Schoot_2017"
N_FIXTURE = 6
RESULTS_V3 = sm.HERE / "results" / "v3"


def dedup(rows, dataset="van_de_Schoot_2017"):
    """The deduplicated basis for *dataset* from the committed manifests."""
    return cb.apply_basis(rows, cb.load_duplicate_ids(dataset))


@pytest.fixture
def vds_workspace(workspace, tmp_path):
    """The ``D`` fixture renamed to van_de_Schoot_2017, with a manifest dropping records 5, 6."""
    results, data, protos = workspace
    for d in (results, data, protos):
        for f in list(d.iterdir()):
            if f.name.startswith("D"):
                f.rename(d / (VDS + f.name[1:]))
    proto = json.loads((protos / f"{VDS}.json").read_text(encoding="utf-8"))
    proto["dataset_id"] = VDS
    (protos / f"{VDS}.json").write_text(json.dumps(proto), encoding="utf-8")
    basis = tmp_path / "basis"
    cb.write_manifest(
        cb.DuplicateManifest(
            dataset=VDS, n_rows=N_FIXTURE,
            duplicate_record_ids=(5, 6), n_unique=N_FIXTURE - 2, n_included_unique=3,
            n_ta_positive_unique=0, rule=cb.DUPLICATE_RULE,
        ),
        basis / f"{VDS}.json",
    )
    return results, data, protos, basis


def test_dedup_basis_is_primary_and_submitted_basis_kept_once(vds_workspace):
    results, data, protos, basis = vds_workspace
    summary = sm.summarise(results, protos, data, basis_dir=basis)
    e = summary["datasets"][VDS]
    assert e["basis"]["deduplicated"] and e["basis"]["n_rows_dropped"] == 2
    assert e["basis"]["manifest"] == f"dedup_basis/{VDS}.json"
    assert e["runs"]["A"]["metrics_final_inclusion"]["n"] == N_FIXTURE - 2
    ref = e["submitted_basis_reference"]
    assert ref["reason"] == cb.SUBMITTED_BASIS_REASON
    assert ref["runs"]["A"]["metrics_final_inclusion"]["n"] == N_FIXTURE
    md = sm.render_markdown(summary)
    assert md.count("as exported (") == 1


def test_basis_block_on_a_dataset_that_is_not_deduplicated(workspace, tmp_path):
    results, data, protos = workspace
    e = sm.summarise(results, protos, data, basis_dir=tmp_path)["datasets"]["D"]
    assert e["basis"] == {"deduplicated": False, "n_rows_dropped": 0, "manifest": None}
    assert "submitted_basis_reference" not in e


def test_ta_basis_split_counts_final_and_non_final():
    def r(i, final, ta, status):
        row = _status_row(i, final, status)
        row["label_abstract_screening"] = ta
        return row

    rows = [
        r(1, 1, 1, "NEEDS_REVIEW"),  # TA positive, final, kept
        r(2, 0, 1, "NEEDS_REVIEW"),  # TA positive, non-final, kept
        r(3, 0, 1, "EXCLUDE"),  # TA positive, non-final, excluded
        r(4, 0, 0, "NEEDS_REVIEW"),  # TA negative
    ]
    s = sm.ta_basis_split(rows)
    assert (s["n_ta_pos"], s["n_ta_kept"], s["final"], s["non_final"]) == (
        3, 2, {"n": 1, "kept": 1}, {"n": 2, "kept": 1},
    )
    assert s["recall"] == pytest.approx(2 / 3)
    lo, hi = s["wilson"]
    assert 0 < lo < 2 / 3 < hi < 1
    assert "wss_at_achieved_retained_recall" in s


def test_ta_basis_split_is_none_without_a_ta_label():
    assert sm.ta_basis_split([_status_row(1, 1, "EXCLUDE"), _status_row(2, 0, "EXCLUDE")]) is None


def test_ta_table_says_when_a_dataset_has_no_ta_label(workspace):
    results, data, protos = workspace
    sm.main(_args(results, protos, data))
    md = (results / "summary.md").read_text(encoding="utf-8")
    assert "no title-and-abstract label in this export" in md
    assert "## Table E1-f. Title-and-abstract basis" in md
    assert md.index("## Table E1-e") < md.index("## Table E1-f")


def test_ta_table_row_for_a_dataset_with_a_ta_label(workspace):
    results, data, protos = workspace
    for run in ("A", "B"):
        path = results / f"D_run{run}.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["label_abstract_screening"] = 1 if row["record_id"] <= 4 else 0
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    summary = sm.summarise(results, protos, data)
    ta = summary["datasets"]["D"]["runs"]["A"]["ta_basis"]
    assert ta["n_ta_pos"] == 4 and ta["n_ta_kept"] == 3
    md = sm.render_markdown(summary)
    assert "no title-and-abstract label in this export" not in md
    assert "TA positives (n)" in md and "Non-final TA positives kept" in md


def test_e1a_names_the_gold_label_per_row(workspace):
    results, data, protos = workspace
    sm.main(_args(results, protos, data))
    md = (results / "summary.md").read_text(encoding="utf-8")
    assert "| Gold label |" in md and "Retained recall (final inclusions)" in md
    assert "Retained recall 95% CI (final inclusions)" in md
    assert "Prevalence (gold label)" in md
    e1a = md.split("## Table E1-a")[1].split("## Table E1-b")[0]
    assert "label_included" in e1a


def test_figure4_rows_name_their_basis(workspace):
    results, data, protos = workspace
    sm.main(_args(results, protos, data))
    fig = read_json(results / "figure4_screening.json")["rows"]
    llm = [r for r in fig if r["series"].startswith("LLM run")]
    assert llm and all(
        r["label_basis"] and r["retained_recall_basis"] == "label_included"
        and "prevalence_final" in r and r["basis"] == "as exported"
        for r in llm
    )
    assert all(r["retained_recall_ta"] is None for r in llm)  # fixture has no TA label
    base = [r for r in fig if r["series"] in ("include-all", "TF-IDF (k matched)")]
    assert all(r["label_basis"] and r["basis"] == "as exported" for r in base)


def test_figure4_rows_say_deduplicated_on_a_deduplicated_dataset(vds_workspace):
    results, data, protos, basis = vds_workspace
    summary = sm.summarise(results, protos, data, basis_dir=basis)
    llm = [r for r in summary["figure4"] if r["series"] == "LLM run A"]
    assert llm[0]["basis"] == "deduplicated" and llm[0]["n"] == N_FIXTURE - 2


def test_committed_runs_give_the_audited_ta_numbers():
    """Real results/v3 run files. Nagtegaal as exported, then on the deduplicated basis."""
    a = sm.ta_basis_split(read_jsonl(RESULTS_V3 / "Nagtegaal_2019_runA.jsonl"))  # as exported
    assert (a["n_ta_kept"], a["n_ta_pos"], a["final"], a["non_final"]) == (
        289, 392, {"n": 101, "kept": 101}, {"n": 291, "kept": 188},
    )
    for run, kept in (("A", 287), ("B", 286)):
        rows = read_jsonl(RESULTS_V3 / f"Nagtegaal_2019_run{run}.jsonl")
        d = sm.ta_basis_split(dedup(rows, "Nagtegaal_2019"))
        assert (d["n_ta_kept"], d["n_ta_pos"]) == (kept, 389)
        if run == "A":
            assert (d["final"], d["non_final"]) == (
                {"n": 101, "kept": 101}, {"n": 288, "kept": 186},
            )
    v = sm.ta_basis_split(read_jsonl(RESULTS_V3 / f"{VDS}_runA.jsonl"))  # as exported
    assert (v["n_ta_kept"], v["n_ta_pos"]) == (156, 388)
    for run, kept in (("A", 142), ("B", 137)):  # primary basis
        d = sm.ta_basis_split(dedup(read_jsonl(RESULTS_V3 / f"{VDS}_run{run}.jsonl")))
        assert (d["n_ta_kept"], d["n_ta_pos"]) == (kept, 356)


def test_missing_abstract_share_uses_the_deduplicated_rows(vds_workspace):
    results, data, protos, basis = vds_workspace
    kept = cb.apply_basis(read_jsonl(results / f"{VDS}_runA.jsonl"), frozenset({5, 6}))
    info = sm.missing_abstract_info(VDS, data, kept, deduplicated=True)
    assert info["source"] == "rows (deduplicated)" and info["n"] == len(kept)
    assert info["n_missing_abstract"] == 1  # record 3 has no abstract; the fetch file is ignored
    assert sm.missing_abstract_info(VDS, data, kept)["source"] == f"{VDS}.fetch.json"


def test_baseline_rows_name_the_baselines_own_label_field(workspace):
    """Baselines are scored on the label_field in the baselines file, which can differ from
    the protocol's. Figure 4 label_basis and the E1-a Gold label column must name it."""
    results, data, protos = workspace
    proto = json.loads((protos / "D.json").read_text(encoding="utf-8"))
    proto["label_field"] = "label_abstract_screening"
    (protos / "D.json").write_text(json.dumps(proto), encoding="utf-8")
    base = read_json(results / "D_baselines.json")
    base["label_field"] = "label_included"
    write_json(results / "D_baselines.json", base)
    summary = sm.summarise(results, protos, data)
    rows = [r for r in summary["figure4"] if r["series"] in ("include-all", "TF-IDF (k matched)")]
    assert len(rows) == 2 and all(r["label_basis"] == "label_included" for r in rows)
    llm = [r for r in summary["figure4"] if r["series"].startswith("LLM run")]
    assert all(r["label_basis"] == "label_abstract_screening" for r in llm)
    e1a = sm.render_markdown(summary).split("## Table E1-a")[1].split("## Table E1-b")[0]
    for line in e1a.splitlines():
        if "| include-all |" in line or "| TF-IDF" in line:
            assert "label_included" in line and "label_abstract_screening" not in line


# ------------------------------------------------ false negatives on the exclusion basis (Task 4)

def _srow(i, status, final, ta):
    row = _row(i, final, {"EXCLUDE": 0}.get(status, 1))
    row.update(status=status, label_abstract_screening=ta)
    return row


def test_excluded_positives_ignores_queued_records():
    rows = [
        _srow(1, "EXCLUDE", 1, 1),       # final inclusion, excluded outright
        _srow(2, "NEEDS_REVIEW", 1, 1),  # final inclusion, queued: not listed
        _srow(3, "EXCLUDE", 0, 1),       # TA positive only, excluded outright
        _srow(4, "INCLUDE", 0, 1),       # TA positive only, kept
        _srow(5, "EXCLUDE", 0, 0),       # excluded, positive on neither basis
    ]
    out = sm.excluded_positives(rows)
    assert [r["record_id"] for r in out["final"]] == [1]
    assert [r["record_id"] for r in out["ta_non_final"]] == [3]


def test_excluded_positives_reports_the_other_runs_status():
    a = [_srow(1, "EXCLUDE", 1, 1)]
    b = [_srow(1, "NEEDS_REVIEW", 1, 1)]
    out = sm.excluded_positives(a, b, "B")
    assert out["final"][0]["other_run"] == "B"
    assert out["final"][0]["other_run_status"] == "NEEDS_REVIEW"


def test_fn_markdown_header_and_empty_sections():
    md = sm.fn_markdown("X", {"A": {"final": [], "ta_non_final": []}})
    assert md.splitlines()[2] == (
        "Records the source review included that the screener excluded outright (status "
        "EXCLUDE), with the screener's stated reason. Records routed to NEEDS_REVIEW stay in "
        "the reading queue and are not listed."
    )
    assert "excluded outright (status EXCLUDE)" in md and md.count("_none_") == 2
    assert "## Run A: excluded final inclusions (0)" in md
    assert (
        "## Run A: excluded title-and-abstract positives that were not final inclusions (0)"
        in md
    )


def test_secondary_headers_use_the_exclusion_basis_names():
    assert "Excluded final inclusions" in sm.SECONDARY_HEADERS
    assert "Excluded TA positives" in sm.SECONDARY_HEADERS
    assert "Excluded positives without abstract (share)" in sm.SECONDARY_HEADERS
    assert "False negatives" not in sm.SECONDARY_HEADERS
    assert "FN without abstract (share)" not in sm.SECONDARY_HEADERS


def test_committed_runs_give_the_audited_exclusions():
    a = sm.excluded_positives(
        dedup(read_jsonl(RESULTS_V3 / "Nagtegaal_2019_runA.jsonl"), "Nagtegaal_2019")
    )
    assert (len(a["final"]), len(a["ta_non_final"])) == (0, 102)
    s = sm.excluded_positives(read_jsonl(RESULTS_V3 / "Smid_2020_runA.jsonl"))
    assert s["final"] == []
    v = sm.excluded_positives(dedup(read_jsonl(RESULTS_V3 / f"{VDS}_runA.jsonl")))
    assert sorted(r["record_id"] for r in v["final"]) == [1569, 2473]


def test_v3_has_no_categorisation_folder():
    assert not (RESULTS_V3 / "fn_categorisation").exists()


def test_categorised_results_render_with_the_release_paragraph(tmp_path):
    """Categorised results render the release paragraph, which prints no agreement figure."""
    results_dir = tmp_path / "results" / "v3"
    results_dir.mkdir(parents=True)
    summary = json.loads((RESULTS_V3 / "summary.json").read_text(encoding="utf-8"))
    summary["results_dir"] = str(results_dir)
    first = next(iter(summary["datasets"].values()))
    first["fn_categories"] = {"FN-ABS": 3, "uncategorised": 1}
    md = sm.render_markdown(summary)
    assert "False-negative categories." in md
    assert "no method disclosure or agreement figure" in md
    assert "### False-negative categories" in md


def _queue_rows():
    """10 rows: 8 EXCLUDE, 2 NEEDS_REVIEW (both full_text_criterion); 2 final positives, of
    which one sits in the queue and one is excluded outright."""
    rows = []
    for i in range(1, 11):
        status = "NEEDS_REVIEW" if i in (1, 2) else "EXCLUDE"
        label = 1 if i in (1, 3) else 0
        row = _status_row(
            i, label, status,
            guard_reason="full_text_criterion" if status == "NEEDS_REVIEW" else "",
        )
        row["label_abstract_screening"] = 1 if i == 1 else 0
        rows.append(row)
    return rows


def test_excluded_share_differs_from_wss_when_recall_below_one():
    m = sm.metrics_primary(_queue_rows())
    assert m["excluded_share"] == 0.8
    assert m["wss_at_achieved_retained_recall"] == pytest.approx(0.3)  # 0.8 - (1 - 0.5)


def test_queue_by_reason_counts_positives_per_cause():
    q = sm.metrics_primary(_queue_rows())["queue_by_reason"]
    assert q == {
        "full_text_criterion": {"n": 2, "share_of_corpus": 0.2, "n_final_pos": 1, "n_ta_pos": 1}
    }


def test_queue_by_reason_ta_positives_are_none_without_a_ta_label():
    rows = _queue_rows()
    for r in rows:
        r["label_abstract_screening"] = None
    q = sm.metrics_primary(rows)["queue_by_reason"]
    assert q["full_text_criterion"]["n_ta_pos"] is None


def test_excluded_share_leaves_out_unscreened_rows():
    rows = _queue_rows()
    rows[9]["predicted"] = None
    rows[9]["status"] = None
    assert sm.metrics_primary(rows)["excluded_share"] == pytest.approx(7 / 9)


def test_committed_runs_give_the_audited_excluded_shares():
    def share(name):
        return round(sm.metrics_primary(read_jsonl(RESULTS_V3 / name))["excluded_share"], 3)

    assert share("Smid_2020_runA.jsonl") == 0.618
    assert share("Nagtegaal_2019_runA.jsonl") == 0.654  # as exported
    assert share(f"{VDS}_runA.jsonl") == 0.841  # as exported, reference only
    for run, n_exc in (("A", 4839), ("B", 4841)):  # primary basis
        m = sm.metrics_primary(dedup(read_jsonl(RESULTS_V3 / f"{VDS}_run{run}.jsonl")))
        assert m["n"] == 5782 and round(m["excluded_share"] * 5782) == n_exc
        assert round(m["excluded_share"], 3) == 0.837


def test_queue_and_tfidf_tables_render(workspace):
    results, data, protos = workspace
    for run in ("A", "B"):
        path = results / f"D_run{run}.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["status"] = "NEEDS_REVIEW" if row["predicted"] else "EXCLUDE"
            row["guard_reason"] = ""
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    base = read_json(results / "D_baselines.json")
    base["run_file"] = "D_runA.jsonl"
    base["n"] = 6
    base["tfidf"].update(
        {
            "target_at_95": 3, "records_read_at_95": 5, "screener_budget": 3,
            "screener_found": 2, "found_at_screener_budget": 1,
            "records_read_at_screener_found": 4,
        }
    )
    write_json(results / "D_baselines.json", base)
    md = sm.render_markdown(sm.summarise(results, protos, data))
    assert "## Table E1-g. Reading queue by cause" in md
    assert "| Dataset | Run | Cause | Records (n) | Share of corpus |" in md
    assert "undecidable" in md.split("## Table E1-g")[1].split("## Table E1-h")[0]
    assert "## Table E1-h. TF-IDF ranking against the screener, in records read" in md
    h = md.split("## Table E1-h")[1].split("## Table E1-c")[0]
    assert "TF-IDF at 95% recall: records read (found / target)" in h
    assert "| D | A | 6 | 3 (50.0%) | 2 | 1 | 4 (66.7%) | 5 (83.3%) (3 / 3) |" in h
    assert "fixed with the labels" in h and "has no 95% recall point" in h
    assert "Reading saved is the excluded share minus (1 - R)" in md
    assert "never has to open at all" not in md
    assert "Excluded share" in md


def _asr_agg(n_not_reached=0):
    def stat(mean, lo, hi, missed=0):
        return {"mean": mean, "min": lo, "max": hi, "n_not_reached": missed}

    agg = {"wss_at_95": stat(0.8, 0.7, 0.9), "wss_at_100": stat(0.7, 0.6, 0.8)}
    for run in ("A", "B"):
        agg[f"{run}.found_at_screener_budget"] = stat(2.0, 1, 3)
        agg[f"{run}.records_to_screener_found"] = stat(4.0, 3, 5, n_not_reached)
    agg["stop_rule_records"] = stat(100.0, 90, 110)
    agg["stop_rule_found"] = stat(2.0, 1, 3)
    return agg


def test_asreview_table_renders_with_not_reached_seeds(workspace):
    results, data, protos = workspace
    (results / "asreview").mkdir()
    write_json(
        results / "asreview" / "D_asreview.json",
        {
            "dataset": "D", "n_total": 6, "n_pos": 3,
            "screener": {"A": {"budget": 3, "found": 2}, "B": {"budget": 2, "found": 1}},
            "per_seed": [{"seed": i} for i in range(1, 16)],
            "aggregate": _asr_agg(n_not_reached=2),
            "stop_rule": {"rule": "consecutive_irrelevant", "k": 100},
        },
    )
    write_json(
        results / "asreview" / "asreview_meta.json",
        {"asreview_version": "asreview 3.0.8", "seeds": list(range(1, 16))},
    )
    summary = sm.summarise(results, protos, data)
    assert summary["datasets"]["D"]["asreview"]["n_pos"] == 3
    md = sm.render_markdown(summary)
    assert "## Table E1-i." in md and "not reached in 2 of 15 seeds" in md
    assert "ASReview LAB 3.0.8" in md and "seeds 1 to 15" in md
    assert "makes the exclusion decision itself" in md


def test_asreview_key_is_none_without_files(workspace):
    results, data, protos = workspace
    summary = sm.summarise(results, protos, data)
    assert summary["datasets"]["D"]["asreview"] is None
    assert "Table E1-i" not in sm.render_markdown(summary)


def test_summary_text_and_generator_carry_no_banned_phrase():
    """The summary text and its generator carry none of the banned phrases."""
    banned = ("earlier" + " run", "earlier" + "-run")
    committed = (RESULTS_V3 / "summary.md").read_text(encoding="utf-8")
    generator = (sm.HERE / "summarize.py").read_text(encoding="utf-8")
    for text in (committed, generator):
        for phrase in banned:
            assert phrase not in text, phrase
    assert "the protocol files record a spot-check" in committed
