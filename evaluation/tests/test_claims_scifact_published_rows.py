"""The published SciFact comparator rows are quoted from the cited papers.

Every value is stored with the verbatim extracted line that holds it, and each value must be a
whole token of that line, so a retyped or rounded number fails here.
"""

import json
import re

from conftest import DEV_MODEL_WORD

from common import EVAL_ROOT

ROWS = json.loads(
    (EVAL_ROOT / "claims" / "scifact_published_rows.json").read_text(encoding="utf-8")
)
BY = {r["key"]: r for r in ROWS}
EXPECTED = {  # (P, R, F1) on each row's own scale, copied from the extracted paper text
    "verisci_fever_zero_shot": (88.9, 58.3, 70.4),
    "verisci": (91.0, 67.4, 77.4),
    "paragraph_joint": (83.3, 76.6, 79.8),
    "gpt4o_zero_shot_support_class": (0.91, 0.80, 0.85),
}
SCIRIFF_F1 = {  # SciRIFF Table 2, SciFact column, Label F1 (percent), 340 dev pairs
    "sciriff_gpt5": 73.1,
    "sciriff_gemini25pro": 77.1,
    "sciriff_deepseek_v31": 82.4,
    "sciriff_kimi_k2": 87.6,
    "sciriff_gpt4o": 85.5,
    "sciriff_gpt4o_mini": 82.7,
    "sciriff_llama31_8b_instruct": 66.7,
    "sciriff_llama31_8b_instruct_sciriff": 85.8,
}
MEDV1_ACCURACY = {"medv1_l3b": 0.844, "medv1_q3b": 0.856}  # 3-way accuracy, 340 pairs
KEYS = [
    "key",
    "system",
    "citation",
    "source_url",
    "fetched_from",
    "table",
    "row_label",
    "split",
    "setting",
    "metric",
    "scale",
    "precision",
    "recall",
    "f1",
    "printed",
    "quote_lines",
    "locate",
    "tuned_on_dev",
    "different_split",
    "caveat",
    "basis",
    "accuracy",
]
OLD_FOUR = [
    "verisci_fever_zero_shot",
    "verisci",
    "paragraph_joint",
    "gpt4o_zero_shot_support_class",
]
NEW_METRICS = ("precision", "recall", "f1")


def test_rows_are_the_old_four_then_the_340_pair_rows():
    assert [r["key"] for r in ROWS] == OLD_FOUR + list(SCIRIFF_F1) + list(MEDV1_ACCURACY)
    for r in ROWS:
        assert sorted(r) == sorted(KEYS), r["key"]


def test_basis_flags():
    assert [BY[k]["basis"] for k in OLD_FOUR] == ["evidence_209"] * 3 + ["other_split"]
    for k in MEDV1_ACCURACY:
        assert BY[k]["basis"] == "all_340", k
        assert BY[k]["different_split"] is False


def test_sciriff_rows_are_not_claimed_as_the_340_dev_pairs():
    for k in SCIRIFF_F1:
        r = BY[k]
        assert r["basis"] == "sciriff_fold" and r["different_split"] is True, k
        assert "not stated in the paper" in r["split"] and "184" in r["split"], k
        assert "340" not in r["split"] and "340" not in r["caveat"], k


def test_sciriff_label_f1_values():
    for k, f1 in SCIRIFF_F1.items():
        r = BY[k]
        assert r["f1"] == f1 and r["precision"] is None and r["recall"] is None, k
        assert r["accuracy"] is None and r["scale"] == "percent" and r["setting"] == "Label-Only"
        assert r["table"].startswith("Table 2") and r["citation"].startswith("Wadden et al., 2025")
        assert r["source_url"] == BY["sciriff_gpt5"]["source_url"]


def test_medv1_three_way_accuracy_values():
    for k, acc in MEDV1_ACCURACY.items():
        r = BY[k]
        assert r["accuracy"] == acc and r["f1"] is None, k
        assert r["scale"] == "fraction" and r["metric"].startswith("3-way accuracy")
        assert r["citation"].startswith("Jin et al.")
        assert any("340 SciFact instances" in line for line in r["quote_lines"])


def test_sciriff_quotes_name_the_model_row():
    assert BY["sciriff_gpt5"]["quote_lines"][0].startswith("GPT-5 - 47.3")
    assert BY["sciriff_deepseek_v31"]["quote_lines"][0].startswith("DeepSeek-V3.1")
    pair = BY["sciriff_llama31_8b_instruct_sciriff"]["quote_lines"]
    assert pair[0].startswith("Llama 3.1 8B-Instruct -") and pair[1].startswith("SciRIFF ")
    assert BY["sciriff_llama31_8b_instruct_sciriff"]["tuned_on_dev"] is False


def test_exact_values():
    for k, (p, r, f) in EXPECTED.items():
        assert (BY[k]["precision"], BY[k]["recall"], BY[k]["f1"]) == (p, r, f), k


def test_every_value_is_a_whole_token_of_its_quote():
    for r in ROWS:
        metrics = [m for m in (*NEW_METRICS, "accuracy") if r[m] is not None]
        assert sorted(r["locate"]) == sorted(metrics) == sorted(r["printed"]), r["key"]
        for m in metrics:
            line, tok = r["locate"][m]
            token = r["quote_lines"][line].split()[tok]
            assert re.fullmatch(re.escape(r["printed"][m]) + r"(\d+\.\d)?", token), (r["key"], m)
            assert float(r["printed"][m]) == r[m]


def test_scale_flags_and_sources():
    three = ("verisci_fever_zero_shot", "verisci", "paragraph_joint")
    assert [BY[k]["scale"] for k in three] == ["percent"] * 3
    assert BY["gpt4o_zero_shot_support_class"]["scale"] == "fraction"
    assert BY["gpt4o_zero_shot_support_class"]["different_split"] is True
    assert all(not BY[k]["different_split"] for k in three)
    assert BY["verisci"]["tuned_on_dev"] and BY["paragraph_joint"]["tuned_on_dev"]
    assert BY["gpt4o_zero_shot_support_class"]["tuned_on_dev"] is False
    for r in ROWS:
        assert "source_sha256" not in r and r["source_url"].startswith("https://")
        assert ":\\" not in json.dumps(r) and "C:/" not in json.dumps(r)


def test_no_excluded_comparators_model_name_or_em_dash():
    text = json.dumps(ROWS, ensure_ascii=False)
    for banned in (DEV_MODEL_WORD, "Sylvestre", "MultiVerS", "VerT5erini", "\u2014"):
        assert banned not in text
