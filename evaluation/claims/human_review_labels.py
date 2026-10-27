"""Blind-labeller majority verdicts, inter-rater agreement and v6 scoring. Reads the three
completed blind claims workbooks and the workbook key, all read-only (`openpyxl`,
`read_only=True`); writes nothing back to any of them and never copies the key. No labeller
identity is read from or written to any output of this script: the three workbooks are
joined only by the order their `--workbook` flags are given (labeller 1, 2, 3).

Inputs, given on the command line (never hard-coded; both outside `evaluation/claims/` and
never committed):

* ``--workbook`` (repeat exactly three times, in labeller order) -- each labeller's own
  filled blind claims workbook. This script reads only the ``Claims`` sheet (86 items: 60
  constructed, 26 real, one row per claim item judged against the stored source text). The
  three workbooks are local files the author holds; this script never names them. It refuses
  a workbook whose workbook id (the Guide line, else the sent copy matched by row order or
  named with ``--copy``) differs from the key's, and joins on the opaque item id, never on
  row position.
* ``--key`` -- the workbook key CSV: the one-way join from a workbook's opaque ``item_id``
  (e.g. ``BC-001``) back to the evaluation's own ``item_id`` (e.g. ``hss-altered-06``) and
  its ``set``. Read-only; nothing from it beyond that join is ever written anywhere.

Majority rule: the majority label for an item is the status at least two of the three
labellers returned; a three-way split is `no_majority`, excluded from every label-based
metric and reported as a count. Inter-rater agreement is reported two ways: the mean of the
three pairwise percent-agreement rates, and Fleiss' kappa.

Outputs, under ``evaluation/claims/results/v6/``:

* ``human_labels_blind.json`` -- one entry per item: the evaluation's own item id, the
  majority label, each labeller's own verdict as ``reviewer_1``..``reviewer_3`` (no names),
  and whether the item is one of the eight protocol-fixed ``no_full_text`` rows. Nothing
  from the key beyond the ``item_id``/``set`` join.
* ``human_review_scores_blind.json`` -- the v6 (`results/v6/{hss,real}_run{A,B}.jsonl`)
  verifier statuses scored against the majority label: accuracy (with a 95% Wilson
  interval), Cohen's kappa, `verified` precision/recall, and the falsely-`verified` count,
  per set (constructed, real) and per run (A, B).

It also rewrites ``results/v6/summary.json``/``summary.md`` (already written by
``freeze_v6.py``) to add the labeller majority scores as Table E2-j, the label of record.

Usage (the evaluation venv's python, for ``openpyxl``; no backend import, no network, no
LLM), from ``evaluation/claims/``::

    python human_review_labels.py --tag blind --workbook C1.xlsx --workbook C2.xlsx \\
        --workbook C3.xlsx --key key.csv

A run with no ``--workbook``/``--key`` arguments refuses: this script has no default
workbook location.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import openpyxl

HERE = Path(__file__).resolve().parent  # evaluation/claims
EVAL_ROOT = HERE.parent
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))
sys.path.insert(0, str(HERE))

from blind_review import (  # noqa: E402
    integrity_counts,
    integrity_warning_lines,
    resolve_workbook_id,
)

from common import (  # noqa: E402
    cohens_kappa,
    now_iso,
    per_class_prf,
    percent_agreement,
    read_json,
    read_jsonl,
    wilson_interval,
    write_json,
)

V6_DIR = HERE / "results" / "v6"

CANONICAL_STATUSES: tuple[str, ...] = ("verified", "needs_nuance", "unsupported", "no_full_text")
SET_TO_V6_PREFIX: dict[str, str] = {"constructed": "hss", "real": "real"}
RUNS: tuple[str, ...] = ("A", "B")


def _read_sheet(path: Path, sheet_name: str) -> list[dict[str, Any]]:
    """Every non-blank row of *sheet_name*, read-only, as a header-keyed dict of stripped
    strings (blank cells become ``""``, never ``None``, so a missing field is unambiguous)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)
        header = [str(c) if c is not None else "" for c in next(rows_iter)]
        out = []
        for row in rows_iter:
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            values = ("" if c is None else str(c).strip() for c in row)
            out.append(dict(zip(header, values, strict=True)))
        return out
    finally:
        wb.close()


def load_key(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {row["opaque_id"]: row for row in csv.DictReader(fh)}


def majority_label(verdicts: list[str]) -> str | None:
    """The status at least two of three reviewers returned, or ``None`` for a three-way
    split (`no_majority`)."""
    top, count = Counter(verdicts).most_common(1)[0]
    return top if count >= 2 else None


def fleiss_kappa(table: list[list[int]]) -> float | None:
    """Fleiss' kappa for a fixed number of raters per item, ``table[i][c]`` the count of
    raters who assigned item ``i`` to category ``c``. ``None`` when undefined (fewer than 2
    items or 0 raters)."""
    n_items = len(table)
    if n_items == 0:
        return None
    n_raters = sum(table[0])
    if n_raters < 2:
        return None
    n_cats = len(table[0])
    p_i = [(sum(x * x for x in row) - n_raters) / (n_raters * (n_raters - 1)) for row in table]
    p_bar = sum(p_i) / n_items
    p_j = [sum(row[c] for row in table) / (n_items * n_raters) for c in range(n_cats)]
    p_e = sum(p * p for p in p_j)
    if p_e >= 1.0:
        return None
    return (p_bar - p_e) / (1.0 - p_e)


def pairwise_agreement(cols: dict[int, list[str]]) -> dict[str, Any]:
    """Mean pairwise percent agreement and mean pairwise Cohen's kappa over the three
    reviewer columns (keys ``1``, ``2``, ``3``), reported alongside Fleiss' kappa (the task's
    "pairwise percent agreement and Fleiss kappa") so both readings are on record."""
    pct, kap = [], []
    for a, b in itertools.combinations((1, 2, 3), 2):
        pct.append(percent_agreement(cols[a], cols[b]))
        kap.append(cohens_kappa(cols[a], cols[b]))
    return {
        "mean_pairwise_percent_agreement": sum(pct) / len(pct),
        "pairwise_percent_agreement": [round(p, 4) for p in pct],
        "mean_pairwise_cohens_kappa": (
            (sum(kap) / len(kap)) if all(k is not None for k in kap) else None
        ),
    }


# --------------------------------------------------------------------------------------
# Claims sheet: majority labels + inter-rater agreement
# --------------------------------------------------------------------------------------


def check_workbook_ids(
    workbook_paths: Sequence[Path], key_path: Path, *, copies: Sequence[str] | None = None,
    sent_dir: Path | None = None,
) -> list[str]:
    """Refuse a workbook whose workbook id differs from the key's ``workbook_id``. The id
    comes from the Guide line, else from the sent copy named in *copies* (one per workbook),
    else from the one sent copy whose Claims row order matches. Returns the method used for
    each workbook, never an id."""
    with key_path.open(encoding="utf-8-sig", newline="") as fh:
        key_ids = {row["workbook_id"] for row in csv.DictReader(fh)}
    methods: list[str] = []
    for n, path in enumerate(workbook_paths):
        found, method = resolve_workbook_id(
            path, kind="claims", copy=copies[n] if copies else None, sent_dir=sent_dir)
        if found not in key_ids:
            raise ValueError(f"{path.name}: the workbook id does not match the key")
        methods.append(method)
    return methods


def build_human_labels(
    workbook_paths: Sequence[Path], key_path: Path, *, sheet_name: str = "Claims",
) -> dict[str, Any]:
    key = load_key(key_path)
    review_by_reviewer = {
        i: _read_sheet(p, sheet_name) for i, p in enumerate(workbook_paths, start=1)
    }
    opaque_ids = [r["item_id"] for r in review_by_reviewer[1]]
    verdicts: dict[str, dict[int, str]] = {oid: {} for oid in opaque_ids}
    for reviewer, rows in review_by_reviewer.items():
        for row in rows:
            verdicts[row["item_id"]][reviewer] = row["human_verdict"].strip().lower()

    items: list[dict[str, Any]] = []
    no_majority_ids: list[str] = []
    for oid in opaque_ids:
        k = key[oid]
        v = verdicts[oid]
        m = majority_label([v[1], v[2], v[3]])
        if m is None:
            no_majority_ids.append(k["real_item_id"])
        items.append({
            "item_id": k["real_item_id"],
            "set": k["set"],
            "majority_label": m,
            "reviewer_1": v[1],
            "reviewer_2": v[2],
            "reviewer_3": v[3],
            "unanimous": len({v[1], v[2], v[3]}) == 1,
            "is_protocol_fixed_no_full_text": (
                k["expected_label"] == "no_full_text" and v[1] == v[2] == v[3] == "no_full_text"
            ),
        })

    def _agreement_over(id_subset: list[str]) -> dict[str, Any]:
        cols = {i: [verdicts[oid][i] for oid in id_subset] for i in (1, 2, 3)}
        table = [
            [sum(1 for i in (1, 2, 3) if verdicts[oid][i] == c) for c in CANONICAL_STATUSES]
            for oid in id_subset
        ]
        agr = pairwise_agreement(cols)
        agr["fleiss_kappa"] = fleiss_kappa(table)
        agr["n_items"] = len(id_subset)
        agr["n_unanimous"] = sum(
            1 for oid in id_subset if len({verdicts[oid][i] for i in (1, 2, 3)}) == 1
        )
        agr["n_no_majority"] = sum(
            1 for oid in id_subset
            if majority_label([verdicts[oid][1], verdicts[oid][2], verdicts[oid][3]]) is None
        )
        return agr

    fixed_opaque_ids = {
        oid for oid in opaque_ids
        if key[oid]["expected_label"] == "no_full_text"
        and verdicts[oid][1] == verdicts[oid][2] == verdicts[oid][3] == "no_full_text"
    }
    judged_ids = [oid for oid in opaque_ids if oid not in fixed_opaque_ids]

    # Report one number per sheet, computed on the 78 freely judged items (the 86 minus the
    # eight protocol-fixed no_full_text rows, on which every reviewer trivially agrees by
    # construction and which would otherwise inflate agreement without testing anything).
    # `with_withheld` (all 86) is kept alongside for the record.
    agreement = _agreement_over(judged_ids)
    agreement["population"] = "judged_only (86 minus the 8 protocol-fixed no_full_text rows)"
    agreement["n_no_majority"] = sum(1 for oid in judged_ids if majority_label(
        [verdicts[oid][1], verdicts[oid][2], verdicts[oid][3]]
    ) is None)
    agreement["with_withheld"] = _agreement_over(opaque_ids)
    agreement["with_withheld"]["population"] = (
        "all 86 Claims items, including the 8 protocol-fixed rows"
    )
    agreement["with_withheld"]["n_no_majority"] = len(no_majority_ids)
    agreement["n_protocol_fixed_excluded"] = len(fixed_opaque_ids)

    # Per population (constructed, real): the pooled figure can hide weak agreement on one
    # population, so the same measures are reported for each, judged-only and with_withheld.
    agreement["by_population"] = {}
    for population in ("constructed", "real"):
        pop_ids = [oid for oid in opaque_ids if key[oid]["set"] == population]
        if not pop_ids:
            continue
        block = _agreement_over([oid for oid in pop_ids if oid not in fixed_opaque_ids])
        block["with_withheld"] = _agreement_over(pop_ids)
        agreement["by_population"][population] = block

    return {
        "generated": now_iso(),
        "source": (
            "three blind claims workbooks (Claims sheet) joined through the workbook key; "
            "no labeller identity read or recorded"
        ),
        "n_items": len(items),
        "n_constructed": sum(1 for it in items if it["set"] == "constructed"),
        "n_real": sum(1 for it in items if it["set"] == "real"),
        "no_majority_item_ids": no_majority_ids,
        "inter_rater_agreement": agreement,
        "items": items,
    }


# --------------------------------------------------------------------------------------
# Score v6 against the human majority label
# --------------------------------------------------------------------------------------


def score_v6_against_labels(
    human_labels: dict[str, Any], *,
    label_of_record: str = "blind labeller majority (results/v6/human_labels_blind.json)",
) -> dict[str, Any]:
    by_set: dict[str, dict[str, str]] = {"constructed": {}, "real": {}}
    for item in human_labels["items"]:
        label = item["majority_label"]
        if label is not None:
            by_set[item["set"]][item["item_id"]] = label

    out: dict[str, Any] = {}
    for set_name, prefix in SET_TO_V6_PREFIX.items():
        gold_by_id = by_set[set_name]
        set_out: dict[str, Any] = {}
        for run in RUNS:
            rows = read_jsonl(V6_DIR / f"{prefix}_run{run}.jsonl")
            pairs = [(gold_by_id[r["item_id"]], str(r.get("predicted_status")))
                     for r in rows if r["item_id"] in gold_by_id]
            gold = [g for g, _ in pairs]
            pred = [p for _, p in pairs]
            n = len(pairs)
            n_correct = sum(1 for g, p in pairs if g == p)
            lo, hi = wilson_interval(n_correct, n) if n else (None, None)
            prf = per_class_prf(gold, pred, list(CANONICAL_STATUSES))
            verified = prf["verified"]
            falsely_verified = verified["predicted"] - verified["tp"]
            set_out[f"run_{run}"] = {
                "n": n,
                "n_matched_to_human_label": n,
                "n_missing_human_label": len(rows) - n,
                "accuracy": (n_correct / n) if n else None,
                "n_correct": n_correct,
                "accuracy_wilson_95": [lo, hi],
                "kappa": cohens_kappa(gold, pred),
                "verified_precision": verified["precision"],
                "verified_recall": verified["recall"],
                "falsely_verified": falsely_verified,
                "confusion": {
                    f"{g}->{p}": c
                    for (g, p), c in sorted(Counter(zip(gold, pred, strict=True)).items())
                },
            }
        out[set_name] = set_out
    return {
        "generated": now_iso(),
        "label_of_record": label_of_record,
        "note": (
            "Scored against results/v6/*.jsonl (the guard-7 replay of the cached model "
            "answers), not against the workbook's own stored verifier_status column."
        ),
        "by_set": out,
    }


# --------------------------------------------------------------------------------------
# Fold into results/v6/summary.json + summary.md
# --------------------------------------------------------------------------------------


def _fmt(value: float | None, spec: str = ".4f") -> str:
    return "n/a" if value is None else format(value, spec)


def _md_human_review_table(scores: dict[str, Any], *, title: str) -> list[str]:
    intro = (
        "The constructed and real claim sets are scored here against the labeller "
        f"majority verdict ({scores['label_of_record']})."
    )
    lines = [
        title,
        "",
        intro,
        "",
        "| set | run | n | accuracy | wilson 95% | kappa | verified precision | "
        "verified recall | falsely verified |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for set_name, runs in scores["by_set"].items():
        for run_key, block in runs.items():
            lo, hi = block["accuracy_wilson_95"]
            lines.append(
                f"| {set_name} | {run_key} | {block['n']} | {_fmt(block['accuracy'])} | "
                f"{_fmt(lo, '.3f')}-{_fmt(hi, '.3f')} | {_fmt(block['kappa'])} | "
                f"{_fmt(block['verified_precision'])} | {_fmt(block['verified_recall'])} | "
                f"{block['falsely_verified']} |"
            )
    lines.append("")
    return lines


def update_v6_summary_blind(blind_labels: dict[str, Any], blind_scores: dict[str, Any]) -> None:
    import summarize as sm  # noqa: PLC0415

    summary = read_json(V6_DIR / "summary.json")
    summary.pop("human_review", None)
    summary["human_review_blind"] = {
        "label_of_record": True,
        "exposure": "blind",
        "majority_rule": (
            "at least two of three labellers; a three-way split is no_majority and excluded"
        ),
        "inter_rater_agreement": blind_labels["inter_rater_agreement"],
        "scores": blind_scores,
    }
    write_json(V6_DIR / "summary.json", summary)

    note = "\n\nLabel of record: Table E2-j (the blind labellers' majority verdict).\n"
    header, _, rest = sm.render_markdown(summary).partition("\n\n")
    blind_lines = _md_human_review_table(
        blind_scores, title="## Table E2-j blind labeller majority, label of record"
    )
    markdown = header + note + "\n" + rest.rstrip() + "\n\n" + "\n".join(blind_lines)
    (V6_DIR / "summary.md").write_text(markdown, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--workbook", action="append", type=Path, dest="workbooks", default=None,
        help=(
            "one labeller's filled blind claims workbook, read-only. Repeat exactly three "
            "times, in labeller order (labeller 1, 2, 3). No default: the three workbooks "
            "are local files the author holds; this script never names them."
        ),
    )
    ap.add_argument(
        "--key", type=Path, default=None,
        help="the workbook key CSV (opaque_id -> real item_id/set join), read-only.",
    )
    ap.add_argument(
        "--tag", choices=("blind",), default="blind",
        help="blind (the only choice): the Claims sheet of the blind labeller workbooks and "
        "the *_blind outputs.",
    )
    ap.add_argument(
        "--copy", action="append", choices=("1", "2", "3"), default=None,
        help="the sent copy each workbook came from, repeated once per "
        "workbook in the same order. Used only when a workbook's Guide has no workbook id "
        "line; without it the copy is found by matching the Claims row order.",
    )
    ap.add_argument(
        "--sent-dir", type=Path, default=None,
        help="the folder of the sent copies (blind-claims-copy1.xlsx and so on); needed "
        "only when a Guide has no workbook id line.",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.workbooks or len(args.workbooks) != 3 or args.key is None:
        print(
            "ERROR: --workbook (repeated exactly three times, in reviewer order) and --key "
            "are both required; this script has no default workbook location."
        )
        return 2

    workbook_paths = (args.workbooks[0], args.workbooks[1], args.workbooks[2])
    if args.copy is not None and len(args.copy) != 3:
        print("ERROR: --copy must be given once per workbook (three times) or not at all.")
        return 2
    try:
        methods = check_workbook_ids(
            workbook_paths, args.key, copies=args.copy, sent_dir=args.sent_dir)
    except ValueError as err:
        print(f"ERROR: {err}")
        return 1
    blind_labels = build_human_labels(workbook_paths, args.key, sheet_name="Claims")
    blind_labels["copy_identification"] = methods
    blind_labels["integrity_flags"] = integrity_counts(workbook_paths)
    blind_labels.pop("generated", None)  # a blind output must not date the labelling
    write_json(V6_DIR / "human_labels_blind.json", blind_labels)
    blind_scores = score_v6_against_labels(blind_labels)
    blind_scores.pop("generated", None)
    write_json(V6_DIR / "human_review_scores_blind.json", blind_scores)
    update_v6_summary_blind(blind_labels, blind_scores)
    for line in integrity_warning_lines(blind_labels["integrity_flags"]):
        print(line)
    print("copy identification: " + ", ".join(methods))
    print(f"wrote {V6_DIR / 'human_labels_blind.json'}, human_review_scores_blind.json; "
          f"updated summary.json/summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
