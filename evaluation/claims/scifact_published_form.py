"""Score the stored SciFact runs in the form the published SciFact systems report.

Interpreter: any Python 3.12+ (stdlib + ``common``). Importers:
``tests/test_claims_scifact_published_form.py``.

Published SciFact abstract-level label-only scoring counts a prediction as correct when the
predicted label equals the gold label of the (claim, abstract) pair; predictions of
NOT_ENOUGH_INFO are ignored. Precision is correct predictions over non-NEI predictions.
Recall is correct predictions over the pairs whose gold label is not NEI. F1 is computed from
the unrounded precision and recall; reported values are rounded to 3 places. A metric whose
denominator is zero is ``None``.

The verifier's four statuses are mapped to the three SciFact labels in two ways.

Strict: verified to SUPPORT; needs_nuance to NEI; unsupported with at least one assertion
verdict "contradicted" to CONTRADICT; any other unsupported, no_full_text or error to NEI.

Lenient: identical except needs_nuance to SUPPORT.

The gold label of each pair is the row's ``gold`` field (``common.scifact_gold_for_doc``).
Rows are scored as shipped: a duplicate row stays in the count, and a no_full_text or error
row maps to NEI and still counts in ``n_rows`` and in the recall denominator.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import EVAL_ROOT, read_json, read_jsonl, wilson_interval  # noqa: E402

MAPPINGS: tuple[str, str] = ("strict", "lenient")
STATUS_KEYS: tuple[str, str] = ("predicted_status", "model_status")
STATUS_RANK: dict[str, int] = {"verified": 2, "needs_nuance": 1, "unsupported": 0}

_NEI = "NOT_ENOUGH_INFO"
_GOLD_CLASSES = ("SUPPORT", "CONTRADICT", _NEI)
_STATUSES = ("verified", "needs_nuance", "unsupported", "no_full_text")


def has_contradiction_signal(row: Mapping[str, Any]) -> bool:
    """True when a per-assertion verdict is ``contradicted`` (same rule as
    ``claims/summarize.py``); a missing, null or empty ``assertions`` gives False."""
    return any(a.get("verdict") == "contradicted" for a in (row.get("assertions") or []))


def _check(status_key: str, mapping: str | None = None) -> None:
    if status_key not in STATUS_KEYS:
        raise ValueError(f"unknown status key: {status_key!r}")
    if mapping is not None and mapping not in MAPPINGS:
        raise ValueError(f"unknown mapping: {mapping!r}")


def map_prediction(
    row: Mapping[str, Any], *, status_key: str = "predicted_status", mapping: str = "strict"
) -> str:
    """Map one row's status to ``SUPPORT``, ``CONTRADICT`` or ``NOT_ENOUGH_INFO``."""
    _check(status_key, mapping)
    status = row.get(status_key)
    if status == "verified":
        return "SUPPORT"
    if status == "needs_nuance":
        return "SUPPORT" if mapping == "lenient" else _NEI
    if status == "unsupported" and has_contradiction_signal(row):
        return "CONTRADICT"
    return _NEI


def confusion(
    rows: Iterable[Mapping[str, Any]], *, status_key: str = "predicted_status"
) -> dict[str, dict[str, int]]:
    """Gold label to status to count; every gold class and status is present."""
    _check(status_key)
    table = {g: {s: 0 for s in _STATUSES} for g in _GOLD_CLASSES}
    for r in rows:
        g, s = r.get("gold"), r.get(status_key)
        if g in table:
            table[g][s] = table[g].get(s, 0) + 1
    return table


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or p + r == 0:
        return None
    return 2 * p * r / (p + r)


def _ci(count: int, n: int) -> list[float | None]:
    lo, hi = wilson_interval(count, n)
    return [_r(lo), _r(hi)]


def abstract_label_only(
    rows: Sequence[Mapping[str, Any]],
    *,
    status_key: str = "predicted_status",
    mapping: str = "strict",
    evidence_pairs_only: bool = True,
) -> dict[str, Any]:
    """Published-form abstract-level label-only precision, recall and F1.

    With ``evidence_pairs_only`` the rows are the pairs whose gold label is not NEI;
    otherwise every row is scored."""
    _check(status_key, mapping)
    used = [r for r in rows if not evidence_pairs_only or r.get("gold") != _NEI]
    predictions = [map_prediction(r, status_key=status_key, mapping=mapping) for r in used]
    predicted_non_nei = sum(1 for p in predictions if p != _NEI)
    correct = sum(1 for r, p in zip(used, predictions) if p != _NEI and p == r.get("gold"))
    gold_pairs = sum(1 for r in used if r.get("gold") != _NEI)
    precision = _ratio(correct, predicted_non_nei)
    recall = _ratio(correct, gold_pairs)
    return {
        "n_rows": len(used),
        "predicted_non_nei": predicted_non_nei,
        "correct": correct,
        "gold_evidence_pairs": gold_pairs,
        "precision": _r(precision),
        "recall": _r(recall),
        "f1": _r(_f1(precision, recall)),
        "precision_ci": _ci(correct, predicted_non_nei),
        "recall_ci": _ci(correct, gold_pairs),
    }


def per_class(
    rows: Sequence[Mapping[str, Any]],
    *,
    status_key: str = "predicted_status",
    mapping: str = "strict",
) -> dict[str, dict[str, Any]]:
    """Three-class precision, recall, support and predicted count over all rows."""
    _check(status_key, mapping)
    pairs = [
        (r.get("gold"), map_prediction(r, status_key=status_key, mapping=mapping)) for r in rows
    ]
    out: dict[str, dict[str, Any]] = {}
    for cls in _GOLD_CLASSES:
        support = sum(1 for g, _ in pairs if g == cls)
        predicted = sum(1 for _, p in pairs if p == cls)
        tp = sum(1 for g, p in pairs if g == cls and p == cls)
        out[cls] = {
            "precision": _ratio(tp, predicted),
            "recall": _ratio(tp, support),
            "support": support,
            "predicted": predicted,
        }
    return out


def three_way_accuracy(
    rows: Sequence[Mapping[str, Any]],
    *,
    status_key: str = "predicted_status",
    mapping: str = "strict",
) -> dict[str, Any]:
    """Three-class accuracy over every row, NEI pairs included (the Med-V1 metric)."""
    _check(status_key, mapping)
    correct = sum(
        1
        for r in rows
        if map_prediction(r, status_key=status_key, mapping=mapping) == r.get("gold")
    )
    return {
        "n_rows": len(rows),
        "correct": correct,
        "accuracy": _r(_ratio(correct, len(rows))),
        "accuracy_ci": _ci(correct, len(rows)),
    }


def guard_changes(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Rows the post-model guard changed, and how many of those became stricter."""
    changed = stricter = 0
    for r in rows:
        before, after = r.get("model_status"), r.get("predicted_status")
        if before == after:
            continue
        changed += 1
        if (
            before in STATUS_RANK
            and after in STATUS_RANK
            and STATUS_RANK[after] < STATUS_RANK[before]
        ):
            stricter += 1
    return {"changed": changed, "towards_stricter": stricter}


# ---------------------------------------------------------------------------
# Report (Table E2-k)
# ---------------------------------------------------------------------------

TABLE_TITLE = "## Table E2-k SciFact against published oracle-abstract verifiers"
OUTPUT_STEM = "scifact_published_form"

MAPPING_TEXT: dict[str, str] = {
    "strict": (
        "Strict: verified to SUPPORT; needs_nuance to NEI; unsupported with at least one "
        'assertion verdict "contradicted" to CONTRADICT; any other unsupported, no_full_text '
        "or error to NEI."
    ),
    "lenient": (
        "Lenient: verified to SUPPORT; needs_nuance to SUPPORT; unsupported with at least one "
        'assertion verdict "contradicted" to CONTRADICT; any other unsupported, no_full_text '
        "or error to NEI."
    ),
}

ANNOTATION_SOURCE_URL = (
    "https://scifact.s3-us-west-2.amazonaws.com/doc/evidence-annotation-instructions.pdf"
)


def mapping_basis(needs_nuance_a: int, needs_nuance_b: int, support_total: int) -> str:
    """Why two readings of needs_nuance are reported, with the SciFact annotation source."""
    return (
        "The verifier has four labels and SciFact has three. Verified maps to SUPPORT, "
        "unsupported with a contradicted assertion to CONTRADICT, and the other unsupported "
        "rows and no_full_text to NEI. needs_nuance has no SciFact slot: it marks a claim "
        "whose assertions are all supported but which overstates the finding or drops a "
        "qualifier the paper attaches. Both readings are therefore reported. Lenient counts "
        "needs_nuance as SUPPORT, which is closer to SciFact's own meaning; strict counts it "
        "as no decision, the cautious reading. The source is the SciFact evidence-annotation "
        "instructions (Wadden et al., 2020, EMNLP, Appendix D; "
        f"{ANNOTATION_SOURCE_URL}). Section 3.3 says "
        '"If the evidence supports a special case of the claim (or the exact claim), support '
        'is full." Section 3.3.1 tells annotators to withhold scientific skepticism and to '
        '"Just take the author\'s words at face value". A claim stated more generally than '
        "its evidence was thus labelled SUPPORT in SciFact, while the verifier flags it as "
        f"needs_nuance by design ({needs_nuance_a} of {support_total} gold SUPPORT pairs in "
        f"run A and {needs_nuance_b} in run B). The annotators were not asked about "
        "overstatement, so the lenient reading is closer to SciFact's meaning but not the "
        "same as it."
    )


METRIC_DEFINITION = (
    "Abstract-level label-only, as in the published SciFact evaluation: a prediction is "
    "correct when the predicted label equals the gold label of the (claim, abstract) pair; "
    "NOT_ENOUGH_INFO predictions are ignored. Precision is correct predictions over non-NEI "
    "predictions. Recall is correct predictions over pairs whose gold label is not NEI. F1 is "
    "computed from the unrounded precision and recall."
)

CAVEATS: list[str] = [
    "The comparison uses SciFact dev with oracle abstracts; no test-set or open-retrieval "
    "result is reported.",
    "The published VeriSci and Paragraph-Joint models were fine-tuned on SciFact train, and "
    "all three were tuned on dev (the zero-shot VeriSci row only for its rationale "
    "threshold).",
    "Our CONTRADICT label is inferred from assertion verdicts.",
    "The GPT-4o row uses its authors' own re-split of train and dev (n = 122) and a "
    "SUPPORT-class metric, so it is set beside our SUPPORT-class row only.",
    "The NEI total counts 131 rows over 130 distinct pairs; one pair appears twice in the "
    "shipped runs.",
    "Comparisons hold for the stated reading; the SciRIFF rows are not ranked.",
    "The Med-V1 rows are scored on 340 pairs and count NEI pairs, so they are set beside the "
    "all-cited figures of ScholarRAG, not beside the 209 evidence pairs. Med-V1 reports 3-way "
    "accuracy, a different metric.",
    "The SciRIFF paper does not state which SciFact fold its Table 2 scores, and the released "
    "harness scores a 184-pair fold drawn from SciFact train. The SciRIFF rows are therefore "
    "listed apart, with no ScholarRAG row beside them. SciRIFF reports Label F1 only, without "
    "precision or recall, and its prompt is its own expert-written template.",
    "No superiority over the general-purpose models is claimed: the verifier is itself a "
    "general-purpose model, and SciFact measures one step, labelling a claim against a given "
    "abstract.",
]


def false_verifications(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows verified although the gold label is not SUPPORT."""
    return [
        {"item_id": r.get("item_id"), "gold": r.get("gold")}
        for r in rows
        if r.get("gold") != "SUPPORT" and r.get("predicted_status") == "verified"
    ]


def _count(rows: Iterable[Mapping[str, Any]], gold: str, status: str) -> int:
    return sum(1 for r in rows if r.get("gold") == gold and r.get("predicted_status") == status)


def _r1_9_run(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    verified_total = sum(1 for r in rows if r.get("predicted_status") == "verified")
    verified_support = _count(rows, "SUPPORT", "verified")
    nei = [r for r in rows if r.get("gold") == _NEI]
    nei_verified = _count(rows, _NEI, "verified")
    return {
        "verified_total": verified_total,
        "verified_support": verified_support,
        "false_verified_ids": [f["item_id"] for f in false_verifications(rows)],
        "nei_verified": nei_verified,
        "nei_total": len(nei),
        "nei_distinct_pairs": len({r.get("item_id") for r in nei}),
        "contradict_verified": _count(rows, "CONTRADICT", "verified"),
        "contradict_total": sum(1 for r in rows if r.get("gold") == "CONTRADICT"),
        "verified_precision": _r(_ratio(verified_support, verified_total)),
        "verified_precision_ci": _ci(verified_support, verified_total),
        "nei_verified_ci": _ci(nei_verified, len(nei)),
    }


def r1_9_counts(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """Verified-status precision and false verifications per run, and the lexical baseline."""
    conf = baseline.get("confusion_gold_raw_x_predicted") or {}

    def base(gold: str) -> int:
        return int((conf.get(gold) or {}).get("verified", 0))

    return {
        "per_run": {"A": _r1_9_run(rows_a), "B": _r1_9_run(rows_b)},
        "baseline": {
            "verified_total": sum(base(g) for g in conf),
            "contradict_verified": base("CONTRADICT"),
            "nei_verified": base(_NEI),
        },
    }


def r2_1_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Where the SUPPORT rows went: verified recall, the other statuses and the guard."""
    support = [r for r in rows if r.get("gold") == "SUPPORT"]
    verified = sum(1 for r in support if r.get("predicted_status") == "verified")
    return {
        "support_total": len(support),
        "verified": verified,
        "verified_recall": _r(_ratio(verified, len(support))),
        "verified_recall_ci": _ci(verified, len(support)),
        "needs_nuance": sum(1 for r in support if r.get("predicted_status") == "needs_nuance"),
        "unsupported": sum(1 for r in support if r.get("predicted_status") == "unsupported"),
        "unsupported_with_contradicted_assertion": sum(
            1
            for r in support
            if r.get("predicted_status") == "unsupported" and has_contradiction_signal(r)
        ),
        "pre_guard_verified": sum(1 for r in support if r.get("model_status") == "verified"),
        "guard_moved_ids": [
            r.get("item_id")
            for r in support
            if r.get("model_status") == "verified" and r.get("predicted_status") != "verified"
        ],
    }


def _support_class(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cls = per_class(rows)["SUPPORT"]
    p, rec = cls["precision"], cls["recall"]
    return {
        "n_rows": len(rows),
        "precision": _r(p),
        "recall": _r(rec),
        "f1": _r(_f1(p, rec)),
    }


def _run_block(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    block: dict[str, Any] = {}
    for mapping in MAPPINGS:
        block[mapping] = {
            "evidence_pairs": abstract_label_only(rows, mapping=mapping),
            "all_cited": abstract_label_only(rows, mapping=mapping, evidence_pairs_only=False),
        }
    block["pre_guard"] = abstract_label_only(rows, status_key="model_status")
    block["per_class"] = per_class(rows)
    block["support_class"] = _support_class(rows)
    block["guard_changes"] = guard_changes(rows)
    return block


def _stricter_text(changes: Mapping[str, int]) -> str:
    if changes["towards_stricter"] == changes["changed"]:
        return "all towards stricter"
    return f"{changes['towards_stricter']} of them towards stricter"


def _provenance_notes(changes_a: Mapping[str, int], changes_b: Mapping[str, int]) -> list[str]:
    if _stricter_text(changes_a) == _stricter_text(changes_b) == "all towards stricter":
        tail = "all towards stricter"
    else:
        tail = f"{_stricter_text(changes_a)} in run A and {_stricter_text(changes_b)} in run B"
    return [
        "The verifier prompt was developed on SciFact train pairs; dev was not used to write it.",
        "Guard 7 was designed with a probe over 852 stored rows that included SciFact dev rows "
        "(FREEZE_DIGESTS_v6.md), so dev is not fully held out for the guard chain.",
        f"The guards changed {changes_a['changed']} (run A) and {changes_b['changed']} (run B) "
        f"SciFact statuses, {tail}.",
    ]


def _same_340(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    published: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """ScholarRAG on all 340 dev pairs (NEI included) and the published rows scored the same."""
    ours: dict[str, Any] = {}
    for run, rows in (("A", rows_a), ("B", rows_b)):
        ours[run] = {}
        for mapping in MAPPINGS:
            f1 = abstract_label_only(rows, mapping=mapping, evidence_pairs_only=False)
            acc = three_way_accuracy(rows, mapping=mapping)
            ours[run][mapping] = {
                "n_rows": len(rows),
                "f1": f1["f1"],
                "accuracy": acc["accuracy"],
                "accuracy_ci": acc["accuracy_ci"],
            }
    return {"ours": ours, "published": [r for r in published if r.get("basis") == "all_340"]}


def _sciriff_fold(published: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """SciRIFF Table 2 rows, whose SciFact fold the paper does not state."""
    return [r for r in published if r.get("basis") == "sciriff_fold"]


def build_report(results_dir: Path, published_rows_path: Path) -> dict[str, Any]:
    """Assemble Table E2-k from the stored runs and the curated published rows."""
    results_dir = Path(results_dir)
    rows_a = read_jsonl(results_dir / "scifact_runA.jsonl")
    rows_b = read_jsonl(results_dir / "scifact_runB.jsonl")
    baseline = read_json(results_dir / "scifact_baseline.json")
    runs = {"A": _run_block(rows_a), "B": _run_block(rows_b)}
    published = read_json(published_rows_path)
    r2_1 = {"A": r2_1_counts(rows_a), "B": r2_1_counts(rows_b)}
    return {
        "mappings": dict(MAPPING_TEXT),
        "mapping_basis": mapping_basis(
            r2_1["A"]["needs_nuance"], r2_1["B"]["needs_nuance"], r2_1["A"]["support_total"]
        ),
        "metric_definition": METRIC_DEFINITION,
        "runs": runs,
        "published": published,
        "same_340": _same_340(rows_a, rows_b, published),
        "sciriff_fold": _sciriff_fold(published),
        "r1_9": r1_9_counts(rows_a, rows_b, baseline),
        "r2_1": r2_1,
        "provenance_notes": _provenance_notes(
            runs["A"]["guard_changes"], runs["B"]["guard_changes"]
        ),
        "caveats": list(CAVEATS),
    }


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def _row(system: str, split: str, setting: str, prf: Sequence[float | None], note: str) -> str:
    p, r, f = (_fmt(v) for v in prf)
    return f"| {system} | {split} | {setting} | {p} | {r} | {f} | {note} |"


def _published_row(r: Mapping[str, Any]) -> str:
    div = 100 if r["scale"] == "percent" else 1
    prf = [r[k] / div for k in ("precision", "recall", "f1")]
    note = f"{r['citation']}, {r['table']}"
    if r.get("different_split"):
        note += "; different split, not directly comparable"
    elif r.get("tuned_on_dev"):
        note += "; tuned on dev"
    return _row(r["system"], r["split"], r["setting"], prf, note)


def _ours(run: str, block: Mapping[str, Any], mapping: str, key: str, label: str) -> str:
    m = block[mapping]["evidence_pairs"] if key == "mapping" else block[key]
    return _row(
        f"ScholarRAG run {run}, {label}",
        "SciFact dev (209 evidence pairs)",
        "Label-Only",
        [m["precision"], m["recall"], m["f1"]],
        "oracle abstract",
    )


def _ci_text(ci: Sequence[float | None]) -> str:
    return f"{_fmt(ci[0])} to {_fmt(ci[1])}"


def _render_340(report: Mapping[str, Any]) -> list[str]:
    block = report["same_340"]
    out = [
        "### Published results on the same 340 SciFact dev pairs (NEI pairs included, 340 pairs)",
        "",
        report["mapping_basis"],
        "",
        "Med-V1 reports 3-way accuracy, so each ScholarRAG row below gives Label F1 and "
        "3-way accuracy, scored on all 340 shipped rows.",
        "",
        "| System | Metric | Value | Note |",
        "|---|---|---|---|",
    ]
    for r in block["published"]:
        if r["f1"] is not None:
            metric, value = "Label F1", f"{r['f1']:.1f}"
        else:
            metric, value = "3-way accuracy", f"{r['accuracy']:.3f}"
        out.append(f"| {r['system']} | {metric} | {value} | {r['citation']}, {r['table']} |")
    for run in ("A", "B"):
        for mapping in MAPPINGS:
            o = block["ours"][run][mapping]
            note = f"{o['n_rows']} pairs, oracle abstract"
            out.append(
                f"| ScholarRAG run {run}, {mapping} mapping | Label F1 | {100 * o['f1']:.1f} "
                f"| {note} |"
            )
            out.append(
                f"| ScholarRAG run {run}, {mapping} mapping | 3-way accuracy | "
                f"{o['accuracy']:.3f} | {note}; 95% CI {_ci_text(o['accuracy_ci'])} |"
            )
    out += [
        "",
        "### SciRIFF-Eval rows (fold not stated in the paper)",
        "",
        "The SciRIFF paper does not state which SciFact fold Table 2 scores, and the released "
        "harness scores a 184-pair fold drawn from SciFact train, so these rows are not set "
        "beside the 340 dev pairs.",
        "",
        "| System | Metric | Value | Note |",
        "|---|---|---|---|",
    ]
    for r in report["sciriff_fold"]:
        out.append(
            f"| {r['system']} | Label F1 | {r['f1']:.1f} | {r['citation']}, {r['table']}; "
            "different fold, not directly comparable |"
        )
    return out + [""]


def render_markdown(report: Mapping[str, Any]) -> str:
    """Table E2-k as markdown: mappings, comparison table, verified-row precision and
    SUPPORT recall lines, caveats."""
    out = [TABLE_TITLE, ""]
    out += [report["mappings"]["strict"], "", report["mappings"]["lenient"], ""]
    out += [report["metric_definition"], ""]
    out += [
        "| System | Split | Setting | P | R | F1 | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    runs = report["runs"]
    for r in report["published"]:
        if r.get("basis") in ("all_340", "sciriff_fold"):
            continue
        out.append(_published_row(r))
        if r.get("different_split"):
            for run in ("A", "B"):
                sc = runs[run]["support_class"]
                out.append(
                    _row(
                        f"ScholarRAG run {run}, SUPPORT class, strict mapping",
                        f"SciFact dev ({sc['n_rows']} rows)",
                        "SUPPORT-class metric",
                        [sc["precision"], sc["recall"], sc["f1"]],
                        "dev split, not the GPT-4o split; set beside the GPT-4o row only",
                    )
                )
    for run in ("A", "B"):
        for mapping in MAPPINGS:
            out.append(_ours(run, runs[run], mapping, "mapping", f"{mapping} mapping"))
    for run in ("A", "B"):
        out.append(
            _ours(run, runs[run], "strict", "pre_guard", "before the guards, strict mapping")
        )
    out.append("")
    out += _render_340(report)
    for run in ("A", "B"):
        p = report["r1_9"]["per_run"][run]
        false_ids = ", ".join(p["false_verified_ids"]) or "none"
        out.append(
            f"Verified-row precision, run {run}: {p['verified_total']} verified, "
            f"{p['verified_support']} of them "
            f"gold SUPPORT (precision {_fmt(p['verified_precision'])}, 95% CI "
            f"{_ci_text(p['verified_precision_ci'])}). False verifications: {false_ids}. "
            f"NEI verified {p['nei_verified']} of {p['nei_total']} rows "
            f"({p['nei_distinct_pairs']} distinct pairs), 95% CI "
            f"{_ci_text(p['nei_verified_ci'])}. CONTRADICT verified "
            f"{p['contradict_verified']} of {p['contradict_total']}."
        )
    b = report["r1_9"]["baseline"]
    out.append(
        f"Verified-row precision, lexical baseline: {b['verified_total']} verified, of which "
        f"{b['contradict_verified']} gold CONTRADICT and {b['nei_verified']} gold NEI."
    )
    out.append("")
    for run in ("A", "B"):
        q = report["r2_1"][run]
        moved = ", ".join(q["guard_moved_ids"]) or "none"
        out.append(
            f"SUPPORT recall, run {run}: of {q['support_total']} gold SUPPORT rows, "
            f"{q['verified']} "
            f"verified (recall {_fmt(q['verified_recall'])}, 95% CI "
            f"{_ci_text(q['verified_recall_ci'])}), {q['needs_nuance']} needs_nuance, "
            f"{q['unsupported']} unsupported ({q['unsupported_with_contradicted_assertion']} "
            f"with a contradicted assertion). Verified before the guards: "
            f"{q['pre_guard_verified']}; moved by the guards: {moved}."
        )
    out += ["", report["provenance_notes"][2], ""]
    out += ["Provenance:", ""] + [f"- {n}" for n in report["provenance_notes"][:2]]
    out += ["", "Caveats:", ""] + [f"- {c}" for c in report["caveats"]]
    return "\n".join(out) + "\n"


def _dump(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _lf(data: bytes) -> bytes:
    """Line endings as written; a checkout with autocrlf may have turned them into CRLF."""
    return data.replace(b"\r\n", b"\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--results-dir", type=Path, default=EVAL_ROOT / "claims" / "results" / "v6")
    ap.add_argument(
        "--published", type=Path, default=EVAL_ROOT / "claims" / "scifact_published_rows.json"
    )
    ap.add_argument("--check", action="store_true", help="exit 1 when the outputs are stale")
    args = ap.parse_args(argv)
    report = build_report(args.results_dir, args.published)
    wanted = {
        args.results_dir / f"{OUTPUT_STEM}.json": _dump(report),
        args.results_dir / f"{OUTPUT_STEM}.md": render_markdown(report),
    }
    if args.check:
        stale = [
            path.name
            for path, text in wanted.items()
            if not path.exists() or _lf(path.read_bytes()) != text.encode("utf-8")
        ]
        for name in stale:
            print(f"out of date: {name}", file=sys.stderr)
        return 1 if stale else 0
    for path, text in wanted.items():
        path.write_bytes(text.encode("utf-8"))
        print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
