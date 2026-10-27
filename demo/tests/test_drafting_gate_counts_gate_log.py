"""Gate-log mode of drafting_gate_counts: per-sentence counts and the require flag."""

import copy
import json
import shutil

import drafting_gate_counts as dgc
from conftest import DEMO_DIR, skip_unless_run_dir

FIXTURE = DEMO_DIR / "tests" / "fixtures" / "gate_log_writing_result.json"
SHIPPED = DEMO_DIR / "output" / "20261026-115827"


def _write_all(tmp_path, result=None):
    text = json.dumps(result) if result is not None else FIXTURE.read_text(encoding="utf-8")
    for name in dgc.SECTION_FILES:
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_shipped_run_output_is_unchanged_and_meets_the_requirement():
    skip_unless_run_dir(SHIPPED)
    assert dgc.main(["--run-dir", str(SHIPPED), "--check"]) == 0
    # the promoted run logs gates in all seven section files
    assert dgc.main(["--run-dir", str(SHIPPED), "--check", "--require-gate-log"]) == 0


def test_run_without_a_gate_log_fails_the_requirement(tmp_path):
    plain = copy.deepcopy(_fixture())
    del plain["gate_log"]
    _write_all(tmp_path, plain)
    assert dgc.build_counts(tmp_path)["status"] == "aggregate_only"
    assert dgc.main(["--run-dir", str(tmp_path), "--require-gate-log"]) == 2


def test_contract_fixture_counts(tmp_path):
    _write_all(tmp_path)
    counts = dgc.build_counts(tmp_path)
    assert counts["status"] == "per_sentence_log"
    assert counts["status_note"] == dgc.PER_SENTENCE_NOTE
    gate = counts["sections"][0]["gate"]
    assert gate["attempts"] == 2
    assert gate["kept_attempt"] == "first"
    assert gate["first_pass"] == {
        "sentences": 2,
        "claims": 2,
        "claims_by_status": {"verified": 1, "unsupported": 1},
    }
    rev = gate["revision"]
    assert rev["keep_verbatim"] == 1
    assert rev["failed"] == 1
    assert rev["first_pass_sentences_carried_verbatim"] == 1
    assert rev["first_pass_sentences_not_carried"] == 1
    assert rev["new_sentences"] == 1
    assert rev["claims_reused"] == 1
    assert rev["claims_reverified"] == 1
    assert gate["finalize"] == {
        "input_sentences": 2,
        "kept": 2,
        "changed": 0,
        "merged": 0,
        "removed_by_rule": {},
        "removed_total": 0,
        "headings_removed": 0,
        "identity_ok": True,
    }
    assert gate["discarded_attempt_sentences"] == 2
    assert gate["fate_counter_mismatch"] == []
    assert counts["totals"]["gate"]["first_pass"]["claims"] == 14
    assert dgc.main(["--run-dir", str(tmp_path), "--require-gate-log"]) == 0


def test_counter_mismatch_fails_the_requirement(tmp_path):
    result = _fixture()
    kept = result["gate_log"]["attempts"][0]
    kept["finalize"]["sentences"] = [
        {
            "fate": "removed",
            "rule": "unverified",
            "sentence": f"Tutoring reduces costs {i}.",
            "delivered": None,
            "paragraph": 0,
        }
        for i in range(2)
    ]
    result["loop_stats"]["sentences_removed_unverified"] = 1
    gate = dgc.gate_counts(result)
    assert gate["fate_counter_mismatch"] == ["unverified"]
    _write_all(tmp_path, result)
    assert dgc.main(["--run-dir", str(tmp_path), "--require-gate-log"]) == 2


def test_carried_verbatim_is_a_multiset_count():
    assert dgc.carried_verbatim(["A.", "A.", "B."], ["A.", "C."]) == (1, 2, 1)


def test_removed_text_is_normalised():
    result = _fixture()
    result["gate_log"]["attempts"][0]["finalize"]["sentences"] = [
        {
            "fate": "removed",
            "rule": "unverified",
            "sentence": "Gains rose \u2014 sharply:\nnext.",
            "delivered": None,
            "paragraph": 0,
        }
    ]
    gate = dgc.gate_counts(result)
    (entry,) = gate["removed_texts"]
    assert entry["rule"] == "unverified"
    assert "\u2014" not in entry["text"]
    assert "\n" not in entry["text"]
    assert "\u2014" not in json.dumps(gate, ensure_ascii=False)


def test_first_pass_link_failure_is_counted():
    result = _fixture()
    attempt = result["gate_log"]["attempts"][0]
    attempt["first_pass"]["claims"] = []
    attempt["revision"] = None
    attempt["link_map_failed"] = True
    result["gate_log"]["attempts"] = [attempt]
    gate = dgc.gate_counts(result)
    assert gate["first_pass"]["claims"] == 0
    assert gate["revision"] is None


def test_unknown_or_absent_log_gives_none():
    result = _fixture()
    assert dgc.gate_counts({}) is None
    result["gate_log"]["schema_version"] = 2
    assert dgc.gate_counts(result) is None
    assert "gate" not in dgc.section_counts(result)


def test_mixed_run_is_aggregate_only(tmp_path):
    plain = copy.deepcopy(_fixture())
    del plain["gate_log"]
    _write_all(tmp_path, plain)
    shutil.copy(FIXTURE, tmp_path / "writing_result.json")
    counts = dgc.build_counts(tmp_path)
    assert counts["status"] == "aggregate_only"
    assert "per-sentence kept, rewritten or removed outcome" in counts["not_recorded"]


def test_missing_section_file_is_named(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "writing_result.json")
    counts = dgc.build_counts(tmp_path)
    assert counts["sections_missing"] == list(dgc.SECTION_FILES[1:])
    assert counts["status"] == "aggregate_only"
    assert dgc.main(["--run-dir", str(tmp_path), "--require-gate-log"]) == 2


def _entry(fate, rule, text, paragraph=0):
    delivered = text if fate in ("kept", "changed", "merged") else None
    return {
        "fate": fate,
        "rule": rule,
        "sentence": text,
        "delivered": delivered,
        "paragraph": paragraph,
    }


def _heading_result():
    result = _fixture()
    result["gate_log"]["attempts"][0]["finalize"]["sentences"] = [
        _entry("removed", "heading", "# Introduction"),
        _entry("kept", None, "Tutoring boosts outcomes (Smith, 2020)."),
        _entry("changed", None, "Tutoring helps pupils (Lee, 2018)."),
        _entry("removed", "unverified", "Tutoring reduces costs (Jones, 2019)."),
    ]
    result["loop_stats"]["headings_removed"] = 1
    result["loop_stats"]["sentences_removed_unverified"] = 1
    return result


def test_identity_holds_with_a_removed_heading():
    result = _heading_result()
    fin = dgc.gate_counts(result)["finalize"]
    assert fin["input_sentences"] == 3
    assert fin["removed_total"] == 1
    assert fin["headings_removed"] == 1
    assert fin["input_sentences"] == (
        fin["kept"] + fin["changed"] + fin["merged"] + fin["removed_total"]
    )
    assert fin["identity_ok"] is True
    assert dgc.gate_counts(result)["fate_counter_mismatch"] == []


def test_broken_identity_fails_the_requirement(tmp_path):
    result = _heading_result()
    _write_all(tmp_path, result)
    counts = dgc.build_counts(tmp_path)
    assert counts["totals"]["gate"]["finalize"]["identity_ok"] is True
    assert dgc.gate_log_problem(counts) is None
    counts["sections"][2]["gate"]["finalize"]["identity_ok"] = False
    assert "identity" in dgc.gate_log_problem(counts)
    assert "3" in dgc.gate_log_problem(counts)


def test_title_echo_is_a_parity_counter(tmp_path):
    result = _fixture()
    result["gate_log"]["attempts"][0]["finalize"]["sentences"] = [
        _entry("removed", "title_echo", "Tutoring in schools."),
        _entry("removed", "title_echo", "Tutoring is in schools."),
    ]
    result["loop_stats"]["sentences_removed_title_echo"] = 1
    assert dgc.gate_counts(result)["fate_counter_mismatch"] == ["title_echo"]
    result["loop_stats"]["sentences_removed_title_echo"] = 2
    assert dgc.gate_counts(result)["fate_counter_mismatch"] == []

