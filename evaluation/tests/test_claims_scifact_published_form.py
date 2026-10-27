from __future__ import annotations

import json
import shutil

import pytest
from conftest import DEV_MODEL_WORD
from scifact_published_form import (
    MAPPINGS,
    abstract_label_only,
    build_report,
    confusion,
    false_verifications,
    guard_changes,
    main,
    map_prediction,
    per_class,
    r1_9_counts,
    r2_1_counts,
    render_markdown,
    three_way_accuracy,
)

from common import EVAL_ROOT, read_json, read_jsonl

V6 = EVAL_ROOT / "claims" / "results" / "v6"
ROWS_A = read_jsonl(V6 / "scifact_runA.jsonl")
ROWS_B = read_jsonl(V6 / "scifact_runB.jsonl")


def test_mapping_strict_and_lenient():
    nn = {"predicted_status": "needs_nuance", "assertions": []}
    contra = {"predicted_status": "unsupported", "assertions": [{"verdict": "contradicted"}]}
    assert map_prediction(nn) == "NOT_ENOUGH_INFO"
    assert map_prediction(nn, mapping="lenient") == "SUPPORT"
    assert map_prediction(contra) == "CONTRADICT"
    assert map_prediction({"predicted_status": "verified"}) == "SUPPORT"


def test_missing_assertions_and_other_statuses_map_to_nei():
    for row in (
        {"predicted_status": "unsupported"},
        {"predicted_status": "unsupported", "assertions": None},
        {"predicted_status": "no_full_text"},
        {"predicted_status": "error"},
    ):
        for m in MAPPINGS:
            assert map_prediction(row, mapping=m) == "NOT_ENOUGH_INFO"


def test_no_full_text_and_error_rows_are_counted():
    rows = [
        {"gold": "SUPPORT", "predicted_status": "verified"},
        {"gold": "SUPPORT", "predicted_status": "no_full_text"},
        {"gold": "CONTRADICT", "predicted_status": "error"},
    ]
    out = abstract_label_only(rows)
    assert (out["n_rows"], out["gold_evidence_pairs"], out["correct"]) == (3, 3, 1)
    assert (out["precision"], out["recall"]) == (1.0, 0.333)


def test_unknown_mapping_and_key_raise():
    with pytest.raises(ValueError):
        map_prediction({"predicted_status": "verified"}, mapping="loose")
    with pytest.raises(ValueError):
        map_prediction({"predicted_status": "verified"}, status_key="other")


def test_confusion_matches_shipped_runs():
    a, b = confusion(ROWS_A), confusion(ROWS_B)
    assert [a["SUPPORT"][s] for s in ("verified", "needs_nuance", "unsupported")] == [57, 51, 30]
    assert [b["SUPPORT"][s] for s in ("verified", "needs_nuance", "unsupported")] == [57, 53, 28]
    for c in (a, b):
        assert [c["CONTRADICT"][s] for s in ("verified", "needs_nuance", "unsupported")] == [
            0,
            1,
            70,
        ]
        assert [c["NOT_ENOUGH_INFO"][s] for s in ("verified", "needs_nuance", "unsupported")] == [
            1,
            2,
            128,
        ]


def test_published_form_209_pairs():
    sa = abstract_label_only(ROWS_A)
    sb = abstract_label_only(ROWS_B)
    assert sa["n_rows"] == 209 and sa["gold_evidence_pairs"] == 209 and sa["correct"] == 119
    assert (sa["precision"], sa["recall"], sa["f1"]) == (0.922, 0.569, 0.704)
    assert (sb["precision"], sb["recall"], sb["f1"]) == (0.937, 0.569, 0.708)
    assert sa["precision_ci"] == [0.863, 0.957] and sa["recall_ci"] == [0.502, 0.635]
    la = abstract_label_only(ROWS_A, mapping="lenient")
    lb = abstract_label_only(ROWS_B, mapping="lenient")
    assert (la["precision"], la["recall"], la["f1"]) == (0.939, 0.813, 0.872)
    assert (lb["precision"], lb["recall"], lb["f1"]) == (0.95, 0.823, 0.882)


def test_published_form_all_cited_documents():
    assert abstract_label_only(ROWS_A, evidence_pairs_only=False)["n_rows"] == 340
    assert abstract_label_only(ROWS_A, evidence_pairs_only=False)["precision"] == 0.862
    assert abstract_label_only(ROWS_B, evidence_pairs_only=False)["precision"] == 0.881
    lenient = abstract_label_only(ROWS_A, mapping="lenient", evidence_pairs_only=False)
    assert lenient["precision"] == 0.885


def test_pre_guard_from_model_status():
    pa = abstract_label_only(ROWS_A, status_key="model_status")
    pb = abstract_label_only(ROWS_B, status_key="model_status")
    assert (pa["precision"], pa["recall"], pa["f1"]) == (0.924, 0.579, 0.712)
    assert (pb["precision"], pb["recall"], pb["f1"]) == (0.938, 0.579, 0.716)


def test_guard_changes_all_towards_stricter():
    assert guard_changes(ROWS_A) == {"changed": 7, "towards_stricter": 7}
    assert guard_changes(ROWS_B) == {"changed": 4, "towards_stricter": 4}


def test_per_class_support_strict_and_lenient():
    s = per_class(ROWS_A)["SUPPORT"]
    assert (round(s["precision"], 3), round(s["recall"], 3)) == (0.983, 0.413)
    assert round(per_class(ROWS_A, mapping="lenient")["SUPPORT"]["recall"], 3) == 0.783
    assert per_class(ROWS_A)["CONTRADICT"]["support"] == 71


def test_duplicate_row_kept_and_evidence_pairs_distinct():
    assert len(ROWS_A) == 340 and len({r["item_id"] for r in ROWS_A}) == 339
    ev = [r["item_id"] for r in ROWS_A if r["gold"] != "NOT_ENOUGH_INFO"]
    assert len(ev) == len(set(ev)) == 209


def test_zero_denominators_return_none():
    rows = [{"gold": "NOT_ENOUGH_INFO", "predicted_status": "unsupported"}]
    out = abstract_label_only(rows, evidence_pairs_only=False)
    assert out["precision"] is None and out["recall"] is None and out["f1"] is None


PUBLISHED = EVAL_ROOT / "claims" / "scifact_published_rows.json"


def test_r1_9_counts():
    out = r1_9_counts(ROWS_A, ROWS_B, read_json(V6 / "scifact_baseline.json"))
    for run in ("A", "B"):
        p = out["per_run"][run]
        assert p["false_verified_ids"] == ["385:9767444"]
        assert (p["verified_total"], p["verified_support"]) == (58, 57)
        assert (p["nei_verified"], p["nei_total"], p["nei_distinct_pairs"]) == (1, 131, 130)
        assert (p["contradict_verified"], p["contradict_total"]) == (0, 71)
        assert p["verified_precision_ci"] == [0.909, 0.997] and p["nei_verified_ci"][1] == 0.042
    assert out["baseline"] == {"verified_total": 2, "contradict_verified": 1, "nei_verified": 0}


def test_false_verifications_lists_non_support_verified_rows():
    rows = [
        {"item_id": "a", "gold": "NOT_ENOUGH_INFO", "predicted_status": "verified"},
        {"item_id": "b", "gold": "SUPPORT", "predicted_status": "verified"},
        {"item_id": "c", "gold": "CONTRADICT", "predicted_status": "unsupported"},
    ]
    assert false_verifications(rows) == [{"item_id": "a", "gold": "NOT_ENOUGH_INFO"}]


def test_r2_1_counts():
    a, b = r2_1_counts(ROWS_A), r2_1_counts(ROWS_B)
    assert (a["verified"], a["support_total"], a["verified_recall"]) == (57, 138, 0.413)
    assert a["verified_recall_ci"] == [0.334, 0.496]
    assert (a["needs_nuance"], a["unsupported"], b["needs_nuance"], b["unsupported"]) == (
        51,
        30,
        53,
        28,
    )
    assert (
        a["unsupported_with_contradicted_assertion"],
        b["unsupported_with_contradicted_assertion"],
    ) == (10, 8)
    assert a["pre_guard_verified"] == b["pre_guard_verified"] == 59
    assert sorted(a["guard_moved_ids"]) == ["275:4961038", "880:8426046"]


def test_report_states_mappings_guard7_and_caveats():
    rep = build_report(V6, PUBLISHED)
    assert "needs_nuance to NEI" in rep["mappings"]["strict"]
    assert "needs_nuance to SUPPORT" in rep["mappings"]["lenient"]
    notes = [n.lower() for n in rep["provenance_notes"]]
    assert any("guard 7" in n and "852" in n and "dev" in n for n in notes)
    assert any("7 (run a)" in n and "4 (run b)" in n and "stricter" in n for n in notes)
    assert any("tuned on dev" in c for c in rep["caveats"])


def test_training_caveat_does_not_overstate_the_zero_shot_row():
    rep = build_report(V6, PUBLISHED)
    text = " ".join(rep["caveats"])
    assert "all three were tuned on dev" in text
    assert "zero-shot VeriSci row only for its rationale threshold" in text


def test_markdown_table_values_and_scale():
    rep = build_report(V6, PUBLISHED)
    md = render_markdown(rep)
    assert md.startswith("## Table E2-k")
    assert "| 0.922 | 0.569 | 0.704 |" in md and "| 0.937 | 0.569 | 0.708 |" in md
    for r in rep["published"]:
        if r["basis"] in ("all_340", "sciriff_fold"):
            continue
        div = 100 if r["scale"] == "percent" else 1
        want = f"| {r['precision'] / div:.3f} | {r['recall'] / div:.3f} | {r['f1'] / div:.3f} |"
        assert want in md, r["key"]
    assert "385:9767444" in md and "0.413" in md and "130 distinct pairs" in md


def test_rows_carry_descriptive_labels_not_review_ids():
    md = render_markdown(build_report(V6, PUBLISHED))
    assert "R" + "1.9" not in md and "R" + "2.1" not in md
    assert "Verified-row precision, run A: 58 verified" in md
    assert "Verified-row precision, lexical baseline:" in md
    assert "SUPPORT recall, run B: of 138 gold SUPPORT rows" in md


def test_outputs_carry_no_banned_text():
    rep = build_report(V6, PUBLISHED)
    for text in (render_markdown(rep), json.dumps(rep, ensure_ascii=False)):
        assert DEV_MODEL_WORD not in text and "\u2014" not in text
        assert "C:/" not in text and ":\\" not in text and "E2-g" not in text


def test_tracked_outputs_are_current():
    assert main(["--check"]) == 0


def test_check_mode_detects_drift(tmp_path):
    for name in ("scifact_runA.jsonl", "scifact_runB.jsonl", "scifact_baseline.json"):
        shutil.copy(V6 / name, tmp_path / name)
    assert main(["--results-dir", str(tmp_path)]) == 0
    assert main(["--results-dir", str(tmp_path), "--check"]) == 0
    (tmp_path / "scifact_published_form.md").write_text("stale", encoding="utf-8")
    assert main(["--results-dir", str(tmp_path), "--check"]) == 1


def test_readme_names_the_new_results_files():
    text = (EVAL_ROOT / "README.md").read_text(encoding="utf-8")
    assert "results/v6/scifact_published_form.md" in text
    assert "demo/output/20261026-115827/drafting_gate_counts.json" in text
    assert "every reported\nfigure is in one of those two files." not in text


# ---------------------------------------------------------------------------
# The 340-pair basis: SciRIFF Label F1 and Med-V1 3-way accuracy (gap-scan Item 6)
# ---------------------------------------------------------------------------


def _hand_accuracy(rows, mapping):
    hits = sum(1 for r in rows if map_prediction(r, mapping=mapping) == r["gold"])
    return hits / len(rows)


def test_all_cited_label_f1_is_the_sciriff_metric_on_340_pairs():
    for rows, strict, lenient in ((ROWS_A, 0.686, 0.848), (ROWS_B, 0.692, 0.860)):
        s = abstract_label_only(rows, evidence_pairs_only=False)
        le = abstract_label_only(rows, mapping="lenient", evidence_pairs_only=False)
        assert s["n_rows"] == le["n_rows"] == 340 and s["gold_evidence_pairs"] == 209
        assert (s["f1"], le["f1"]) == (strict, lenient)


def test_three_way_accuracy_counts_nei_pairs():
    for rows in (ROWS_A, ROWS_B):
        for m in MAPPINGS:
            acc = three_way_accuracy(rows, mapping=m)
            assert acc["n_rows"] == 340
            assert acc["correct"] == round(_hand_accuracy(rows, m) * 340)
            assert acc["accuracy"] == round(_hand_accuracy(rows, m), 3)
            assert len(acc["accuracy_ci"]) == 2
    toy = [
        {"gold": "NOT_ENOUGH_INFO", "predicted_status": "unsupported"},
        {"gold": "SUPPORT", "predicted_status": "needs_nuance"},
    ]
    assert three_way_accuracy(toy)["correct"] == 1
    assert three_way_accuracy(toy, mapping="lenient")["correct"] == 2
    assert three_way_accuracy([])["accuracy"] is None


def test_report_340_block_and_basis_text():
    rep = build_report(V6, PUBLISHED)
    b = rep["same_340"]
    assert b["ours"]["A"]["strict"]["f1"] == 0.686 and b["ours"]["B"]["lenient"]["f1"] == 0.860
    assert (
        b["ours"]["A"]["lenient"]["accuracy"]
        == three_way_accuracy(ROWS_A, mapping="lenient")["accuracy"]
    )
    keys = [r["key"] for r in b["published"]]
    assert keys == ["medv1_l3b", "medv1_q3b"]
    sk = [r["key"] for r in rep["sciriff_fold"]]
    assert sk[:2] == ["sciriff_gpt5", "sciriff_gemini25pro"] and len(sk) == 8
    basis = rep["mapping_basis"]
    assert "SUPPORT" in basis and "closer to" in basis and "not the same as" in basis
    assert "If the evidence supports a special case of the claim" in basis
    assert "evidence-annotation-instructions.pdf" in basis
    assert "51 of 138" in basis and "53" in basis


def test_markdown_340_section():
    md = render_markdown(build_report(V6, PUBLISHED))
    assert "340 pairs" in md
    for want in (
        "| 73.1 |",  # SciRIFF GPT-5 Label F1, percent
        "| 87.6 |",
        "| 0.844 |",
        "| 0.856 |",
        "| 68.6 |",  # ScholarRAG all-cited Label F1 in percent, run A strict
        "| 69.2 |",
        "| 84.8 |",
        "| 86.0 |",
    ):
        assert want in md, want
    sec = md[md.index("340 pairs") :]
    assert sec.count("Jin et al.") == 2
    head, tail = sec.split("### SciRIFF-Eval rows", 1)
    assert "Wadden et al., 2025" not in head and tail.count("Wadden et al., 2025") == 8
    assert "| 73.1 |" in tail and "| 87.6 |" in tail
    assert "not stated in the paper" in tail and "184" in tail
    assert not [ln for ln in tail.splitlines() if ln.startswith("| ") and "ScholarRAG" in ln]
    assert "Wadden et al., 2025" in md and "Jin et al." in md
    assert "closer to SciFact's own meaning" in md
    assert "2 hours" not in md


def test_caveat_states_the_comparison_reading_not_a_no_ranking_claim():
    from claims.scifact_published_form import CAVEATS

    assert "Comparisons hold for the stated reading; the SciRIFF rows are not ranked." in CAVEATS
    assert "No ranking claim is made." not in CAVEATS
