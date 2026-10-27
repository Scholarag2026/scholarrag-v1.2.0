"""Tests for demo/drafting_gate_counts.py (drafting-gate counts)."""

import json
import shutil
from pathlib import Path

import pytest
from conftest import DEMO_DIR, skip_unless_run_dir
from drafting_gate_counts import SECTION_FILES, _sentence_of, build_counts, main, section_counts


@pytest.fixture
def run():
    return skip_unless_run_dir(DEMO_DIR / "output" / "20261026-115827")


def test_totals_match_the_shipped_counters(run):
    # Every expected value below was read from the promoted run's own files, not from
    # drafting_gate_counts.py output: removal counters and rates from loop_stats in
    # writing_result*.json (7 files, summed); words from provenance.length; claim rows from
    # claim_report.verifications; cited sentences from distinct citation_links sentences;
    # delivered sentences from the gate log's kept, changed and merged finalize entries
    # (headings excluded) of the kept attempt.
    t = build_counts(run)["totals"]
    assert t["removed_total"] == 37
    assert t["removed_by_reason"] == {
        "uncited_finding": 21,
        "unverified": 10,
        "dangling": 5,
        "meta_evaluation_uncited": 1,
    }
    assert (t["delivered_sentences"], t["delivered_cited_sentences"], t["claim_rows"]) == (
        79,
        60,
        63,
    )
    assert (t["residue_excised"], t["needs_citation_markers_removed"], t["headings_removed"]) == (
        0,
        3,
        4,
    )
    assert (t["words_first_generation"], t["words_final"]) == (2987, 1863)
    assert t["stored_removed_count"] == 22 and t["sections_revised"] == 7
    assert "first_pass_verified_rate" not in t and "loop_revised" not in t


def test_protocol_section_and_ambiguous_section_5(run):
    # Section 1 words and removals: writing_result.json provenance.length (427 to 249) and the
    # sum of its sentences_removed_* counters (1 uncited_finding, 2 unverified, 1 dangling).
    # Section 5 (writing_result_5.json): 2 uncited_finding counter against 2 uncited sentences
    # tagged finding, so the stored texts are not ambiguous; one meta_evaluation_reasons
    # entry. No section carries coverage_incomplete reasons in this run.
    s = build_counts(run)["sections"]
    assert (s[0]["words_first_generation"], s[0]["words_final"], s[0]["removed_total"]) == (
        427,
        249,
        4,
    )
    assert s[4]["stored_removed"]["ambiguous"] is False
    assert sum(1 for x in s[4]["stored_removed"]["texts"] if x["reason"] == "uncited_finding") == 2
    assert (
        sum(1 for x in s[4]["stored_removed"]["texts"] if x["reason"] == "meta_evaluation_uncited")
        == 1
    )
    assert (
        sum(
            1
            for x in s[6]["stored_removed"]["texts"]
            if x["reason"] == "coverage_incomplete" and x["text"]
        )
        == 0
    )
    # first_pass_verified_rate in loop_stats of each writing_result*.json
    assert [round(x["first_pass_verified_rate"], 3) for x in s] == [
        0.923,
        0.375,
        0.75,
        0.529,
        0.667,
        0.714,
        0.765,
    ]


def test_status_basis_and_not_recorded(run):
    # The promoted run logs per-sentence gate outcomes (gate_log in every writing_result*.json,
    # schema_version present), so the removal texts are all recorded and the one remaining
    # unrecorded item is the rewrite-versus-drop split of first-pass sentences.
    out = build_counts(run)
    assert out["status"] == "per_sentence_log" and out["basis"] == "demo run 20261026-115827"
    assert out["not_recorded"] == [
        "which first-pass sentences the revision rewrote rather than dropped"
    ]
    text = json.dumps(out, ensure_ascii=False)
    for banned in ("citation rule, not the verifier", bytes.fromhex("436c61756465").decode(), "\u2014", "C:/", ":\\"):
        assert banned not in text


def test_missing_and_unknown_keys_are_tolerated():
    res = {
        "content": "One. Two.",
        "loop_stats": {"sentences_removed_new_rule": 2},
        "provenance": {"length": {}},
        "citation_links": [],
        "uncited_sentences": [],
        "claim_report": {"verifications": []},
    }
    c = section_counts(res)
    assert c["removed_by_reason"] == {"new_rule": 2} and c["removed_total"] == 2
    assert c["stored_removed"]["stored_count"] == 0 and c["delivered_sentences"] == 2


def test_tracked_output_is_current(run):
    assert main(["--run-dir", str(run), "--check"]) == 0


def test_check_mode(run, tmp_path):
    for f in SECTION_FILES:
        shutil.copy(run / f, tmp_path / f)
    assert main(["--run-dir", str(tmp_path)]) == 0
    written = json.loads((tmp_path / "drafting_gate_counts.json").read_text(encoding="utf-8"))
    assert written["basis"] == f"demo run {tmp_path.name}"
    assert main(["--run-dir", str(tmp_path), "--check"]) == 0
    (tmp_path / "drafting_gate_counts.json").write_text("{}", encoding="utf-8")
    assert main(["--run-dir", str(tmp_path), "--check"]) == 1


def test_source_files_hold_no_literal_em_dash():
    here = Path(__file__).resolve()
    for path in (here, here.parent.parent / "drafting_gate_counts.py"):
        assert "\u2014" not in path.read_text(encoding="utf-8"), path.name


def test_sentence_of_spaces_the_replacement_for_an_em_dash():
    out = _sentence_of({"sentence": "coded feedback\u2014error codes"})
    assert out == "coded feedback - error codes"
