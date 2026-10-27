"""Score the verifier against every claim label set, side by side.

Label sets (the label of record is the blind set):

* ``human_blind``: three labellers, tool output hidden. Read from
  ``results/v6/human_labels_blind.json`` when that file exists; otherwise the set is left out.
* ``construction_rule``: the label the construction rule fixed for each constructed claim
  (``expected[0]`` in ``hss_test_v3_claims.jsonl``); it covers the constructed set only.

A majority label of ``None`` is a three-way split among the labellers (``no_majority``). Such
an item stays in its set, is counted in ``n_no_majority`` and is left out of every rate.

A population (``constructed``, ``real``, ``all``) is reported for a set only when every item
of that population is in the set, so a set never silently covers part of a population.

Usage::

    python claims/label_sets.py [--results-dir claims/results/v6] [--out-json P] [--out-md P]

No network, no model call. Reads committed files only.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent  # evaluation/claims
EVAL_ROOT = HERE.parent
sys.path.insert(0, str(EVAL_ROOT))

from common import (  # noqa: E402
    cohens_kappa,
    per_class_prf,
    read_json,
    read_jsonl,
    wilson_interval,
    write_json,
)

LABEL_SETS: tuple[str, ...] = ("human_blind", "construction_rule")
EXPOSURE: dict[str, str] = {
    "human_blind": "three labellers, blind, label of record",
    "construction_rule": "construction rule, constructed set only",
}
RUNS: tuple[str, ...] = ("A", "B")
POPULATIONS: tuple[str, ...] = ("constructed", "real", "all")
STATUSES: tuple[str, ...] = ("verified", "needs_nuance", "unsupported", "no_full_text")
_STATUS_MAP = {"error": "unsupported"}

CONSTRUCTED_FILE = "hss_test_v3_claims.jsonl"
REAL_FILE = "real_claims_test.jsonl"
RUN_PREFIXES = ("hss", "real")


def _labels_from_file(path: Path) -> dict[str, str | None]:
    data = read_json(path)
    return {it["item_id"]: it["majority_label"] for it in data["items"]}


def load_label_sets(claims_dir: Path, results_dir: Path) -> dict[str, dict[str, str | None]]:
    """The label sets that exist, keyed by set name. A missing blind file drops that set."""
    out: dict[str, dict[str, str | None]] = {}
    blind = Path(results_dir) / "human_labels_blind.json"
    if blind.is_file():
        out["human_blind"] = _labels_from_file(blind)
    constructed = Path(claims_dir) / CONSTRUCTED_FILE
    if constructed.is_file():
        out["construction_rule"] = {
            row["item_id"]: row["expected"][0] for row in read_jsonl(constructed)
        }
    return out


def verifier_statuses(results_dir: Path, run: str) -> dict[str, str]:
    """``predicted_status`` per item for one run file stem (for example ``hss_runA``)."""
    out: dict[str, str] = {}
    for row in read_jsonl(Path(results_dir) / f"{run}.jsonl"):
        status = str(row.get("predicted_status"))
        out[row["item_id"]] = _STATUS_MAP.get(status, status)
    return out


def score_against(
    labels: Mapping[str, str | None],
    preds: Mapping[str, str],
    item_ids: Sequence[str],
) -> dict[str, Any]:
    in_set = [i for i in item_ids if i in labels and i in preds]
    labelled = [i for i in in_set if labels[i] is not None]
    gold = [str(labels[i]) for i in labelled]
    pred = [preds[i] for i in labelled]
    n = len(labelled)
    n_correct = sum(1 for g, p in zip(gold, pred, strict=True) if g == p)
    lo, hi = wilson_interval(n_correct, n) if n else (None, None)
    prf = per_class_prf(gold, pred, list(STATUSES))
    verified = prf["verified"]
    return {
        "n": n,
        "n_no_majority": len(in_set) - n,
        "n_correct": n_correct,
        "accuracy": (n_correct / n) if n else None,
        "wilson_95": [lo, hi],
        "kappa": cohens_kappa(gold, pred) if n else None,
        "verified_precision": verified["precision"],
        "verified_recall": verified["recall"],
        "falsely_verified": verified["predicted"] - verified["tp"],
    }


def _covers(labels: Mapping[str, Any], ids: Sequence[str]) -> bool:
    return bool(ids) and all(i in labels for i in ids)


def label_set_table(
    label_sets: Mapping[str, Mapping[str, str | None]],
    preds_by_run: Mapping[str, Mapping[str, str]],
    populations: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for set_name in LABEL_SETS:
        labels = label_sets.get(set_name)
        if labels is None:
            continue
        for population in POPULATIONS:
            ids = populations.get(population)
            if ids is None or not _covers(labels, ids):
                continue
            for run, preds in preds_by_run.items():
                rows.append({
                    "set": set_name,
                    "population": population,
                    "run": run,
                    **score_against(labels, preds, ids),
                })
    return rows


def pairwise_agreement(
    label_sets: Mapping[str, Mapping[str, str | None]],
    populations: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    present = [s for s in LABEL_SETS if s in label_sets]
    for i, a in enumerate(present):
        for b in present[i + 1:]:
            for population in POPULATIONS:
                ids = populations.get(population)
                if ids is None or not (
                    _covers(label_sets[a], ids) and _covers(label_sets[b], ids)
                ):
                    continue
                both = [
                    x for x in ids
                    if label_sets[a][x] is not None and label_sets[b][x] is not None
                ]
                la = [str(label_sets[a][x]) for x in both]
                lb = [str(label_sets[b][x]) for x in both]
                rows.append({
                    "set_a": a,
                    "set_b": b,
                    "population": population,
                    "n": len(both),
                    "n_no_majority": len(ids) - len(both),
                    "n_agree": sum(1 for x, y in zip(la, lb, strict=True) if x == y),
                    "kappa": cohens_kappa(la, lb) if both else None,
                })
    return rows


def _item_ids(path: Path) -> list[str]:
    return [row["item_id"] for row in read_jsonl(path)]


def build(claims_dir: Path, results_dir: Path) -> dict[str, Any]:
    claims_dir, results_dir = Path(claims_dir), Path(results_dir)
    constructed = _item_ids(claims_dir / CONSTRUCTED_FILE)
    real = _item_ids(claims_dir / REAL_FILE)
    populations = {"constructed": constructed, "real": real, "all": constructed + real}
    label_sets = load_label_sets(claims_dir, results_dir)
    preds_by_run: dict[str, dict[str, str]] = {}
    for run in RUNS:
        merged: dict[str, str] = {}
        for prefix in RUN_PREFIXES:
            merged.update(verifier_statuses(results_dir, f"{prefix}_run{run}"))
        preds_by_run[run] = merged
    result: dict[str, Any] = {
        "exposure": {s: EXPOSURE[s] for s in LABEL_SETS if s in label_sets},
        "table": label_set_table(label_sets, preds_by_run, populations),
        "agreement": pairwise_agreement(label_sets, populations),
    }
    return result


def _fmt(value: Any, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = ["## Table E2-i Verifier against every label set", ""]
    for name, text in result["exposure"].items():
        lines.append(f"- `{name}`: {text}")
    lines += [
        "",
        "| Label set | Population | Run | n | no majority | Correct | Accuracy | Wilson 95% "
        "| Kappa | Verified precision | Verified recall | Falsely verified |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in result["table"]:
        lo, hi = r["wilson_95"]
        lines.append(
            f"| {r['set']} | {r['population']} | {r['run']} | {r['n']} | {r['n_no_majority']} "
            f"| {r['n_correct']} | {_fmt(r['accuracy'])} | [{_fmt(lo)}, {_fmt(hi)}] "
            f"| {_fmt(r['kappa'])} | {_fmt(r['verified_precision'])} "
            f"| {_fmt(r['verified_recall'])} | {r['falsely_verified']} |"
        )
    lines += [
        "",
        "## Agreement between label sets",
        "",
        "| Set A | Set B | Population | n | no majority | Agree | Kappa |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result["agreement"]:
        lines.append(
            f"| {r['set_a']} | {r['set_b']} | {r['population']} | {r['n']} "
            f"| {r['n_no_majority']} | {r['n_agree']} | {_fmt(r['kappa'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--results-dir", type=Path, default=HERE / "results" / "v6")
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args(argv)
    out_json = args.out_json or args.results_dir / "label_sets.json"
    out_md = args.out_md or args.results_dir / "label_sets.md"
    result = build(HERE, args.results_dir)
    write_json(out_json, result)
    out_md.write_text(render_markdown(result), encoding="utf-8")
    print(f"wrote {out_json} and {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
