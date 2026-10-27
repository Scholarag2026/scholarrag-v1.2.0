"""Score the three blind screening workbooks against the screening key.

The blind screening sample (target 80 EXCLUDE, 30 INCLUDE, 20 judge-demoted, 10 other
NEEDS_REVIEW records of one delivered run, named with ``--run-id``) is labelled by three
people who see no tool output. This script joins their decisions on the opaque record id
(never on row position), takes the 2-of-3 majority decision per record and reports:

* how many of the tool's EXCLUDE records a majority would include (miss rate, Wilson 95 %);
* how many of its INCLUDE records a majority also includes;
* how many judge-demoted records a majority upholds (exclude or unsure);
* inter-rater agreement (Fleiss' kappa, mean pairwise percent agreement).

A three-way split has no majority: it is counted in ``no_majority`` and left out of every
rate denominator. Decisions are compared after ``strip().lower()``.

Usage:
    python screening/blind_screening_scores.py --workbook A.xlsx --workbook B.xlsx
        --workbook C.xlsx --key key.csv --run-id RUN [--out-dir screening/results/blind_round]

Besides the scores the run writes ``blind_screening_records.csv``: one anonymised row per
record (record id, the record's OpenAlex id, stratum, system status, the three decisions; no
names, titles or attestation text). The OpenAlex id lets anyone find the record in the
delivered run's screening record. Anyone can recompute the scores from that file without
the workbooks (the scores do not read the OpenAlex id):

    python screening/blind_screening_scores.py --check blind_screening_records.csv
        [--out-dir screening/results/blind_round]

``--check`` rescores from the file and compares the result with the
``blind_screening_scores.json`` in ``--out-dir`` (the workbook-only ``integrity_flags`` are
not compared); it exits 0 when they match and 1 when they differ.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
sys.path.insert(0, str(EVAL_ROOT))
sys.path.insert(0, str(EVAL_ROOT / "claims"))

from blind_review import (  # noqa: E402
    BLIND_SCREENING_STRATA,
    SCREENING_DECISIONS,
    integrity_counts,
    integrity_warning_lines,
    resolve_workbook_id,
)
from human_review_labels import _read_sheet, fleiss_kappa, pairwise_agreement  # noqa: E402

from common import wilson_interval  # noqa: E402

DEFAULT_OUT_DIR = HERE / "results" / "blind_round"
RECORDS_FILE = "blind_screening_records.csv"
RECORDS_HEADER = ["record_id", "openalex_id", "stratum", "system_status",
                  "decision_1", "decision_2", "decision_3"]


def read_screening_decisions(path: Path) -> dict[str, str]:
    """Opaque record id to decision (``strip().lower()``) from the Screening sheet."""
    out: dict[str, str] = {}
    for row in _read_sheet(Path(path), "Screening"):
        out[row["record_id"]] = row["human_decision"].strip().lower()
    return out


def majority_decision(decisions: Sequence[str]) -> str | None:
    """The decision at least two of three labellers gave, else ``None``."""
    top, count = Counter(decisions).most_common(1)[0]
    return top if count >= 2 else None


def _load_key(key_path: Path) -> tuple[dict[str, str], set[str], dict[str, str]]:
    with Path(key_path).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return (
        {r["opaque_id"]: r["stratum"] for r in rows},
        {r["workbook_id"] for r in rows},
        {r["opaque_id"]: r.get("status", "") for r in rows},
    )


def _load_openalex_ids(key_path: Path) -> dict[str, str]:
    with Path(key_path).open(encoding="utf-8-sig", newline="") as fh:
        return {r["opaque_id"]: r.get("openalex_id", "") for r in csv.DictReader(fh)}


def _rate(count: int, n: int) -> dict[str, Any]:
    lo, hi = wilson_interval(count, n)
    return {"rate": (count / n) if n else None, "wilson_95": [lo, hi]}


def score_blind_screening(
    workbook_paths: Sequence[Path], key_path: Path, *, copies: Sequence[str] | None = None,
    sent_dir: Path | None = None,
) -> dict[str, Any]:
    """Score three returned workbooks. A workbook whose Guide lacks the id line is identified
    by *copies* (one sent copy name per workbook) or by its Screening row order; the method
    used for each is recorded under ``copy_identification``, never an id."""
    if len(workbook_paths) != 3:
        raise ValueError(f"expected 3 workbooks, got {len(workbook_paths)}")
    strata, key_wb_ids, _ = _load_key(key_path)
    methods: list[str] = []
    for n, path in enumerate(workbook_paths):
        found, method = resolve_workbook_id(
            Path(path), kind="screening", copy=copies[n] if copies else None,
            sent_dir=sent_dir)
        if found not in key_wb_ids:
            raise ValueError(f"{Path(path).name}: the workbook id does not match the key")
        methods.append(method)
    decisions = [read_screening_decisions(Path(p)) for p in workbook_paths]
    for i, c in enumerate(decisions, start=1):
        if set(c) != set(strata):
            missing = sorted(set(strata) - set(c))[:5]
            extra = sorted(set(c) - set(strata))[:5]
            raise ValueError(
                f"workbook {i} ids differ from the key (missing {missing}, extra {extra})")
    scores = _score_decisions(strata, decisions)
    scores["integrity_flags"] = integrity_counts(workbook_paths)
    scores["copy_identification"] = methods
    return scores


def _score_decisions(
    strata: dict[str, str], copies: Sequence[dict[str, str]],
) -> dict[str, Any]:
    """Every rate and agreement figure, from the stratum of each record and the three
    decision columns. Shared by the workbook path and the anonymised-file path."""
    ids = sorted(strata)
    for i, c in enumerate(copies, start=1):
        for rid in ids:
            if c[rid] not in SCREENING_DECISIONS:
                raise ValueError(
                    f"workbook {i}, {rid}: decision {c[rid]!r} is not one of "
                    f"{list(SCREENING_DECISIONS)}")

    by_stratum: dict[str, dict[str, int]] = {
        s: {"n_records": 0, "include": 0, "exclude": 0, "unsure": 0, "no_majority": 0,
            "n_any_include": 0}
        for s in BLIND_SCREENING_STRATA}
    majority: dict[str, str | None] = {}
    for rid in ids:
        triple = [c[rid] for c in copies]
        maj = majority_decision(triple)
        majority[rid] = maj
        b = by_stratum[strata[rid]]
        b["n_records"] += 1
        b[maj if maj is not None else "no_majority"] += 1
        if "include" in triple:
            b["n_any_include"] += 1
    for b in by_stratum.values():
        b["n"] = b["include"] + b["exclude"] + b["unsure"]

    def with_majority(stratum: str) -> list[str]:
        return [r for r in ids if strata[r] == stratum and majority[r] is not None]

    ex_ids = with_majority("exclude")
    n_ex_inc = sum(majority[r] == "include" for r in ex_ids)
    n_ex_any = sum("include" in [c[r] for c in copies] for r in ex_ids)
    inc_ids = with_majority("include")
    n_inc = sum(majority[r] == "include" for r in inc_ids)
    jd_ids = with_majority("judge_demoted")
    n_up = sum(majority[r] in ("exclude", "unsure") for r in jd_ids)
    n_jd_inc = sum(majority[r] == "include" for r in jd_ids)

    table = [[sum(c[r] == d for c in copies) for d in SCREENING_DECISIONS] for r in ids]
    cols = {i: [c[r] for r in ids] for i, c in enumerate(copies, start=1)}
    inter = pairwise_agreement(cols)
    return {
        "n_records": len(ids),
        "n_no_majority": sum(m is None for m in majority.values()),
        "by_stratum": by_stratum,
        "exclusions": {
            "n": len(ex_ids), "n_majority_include": n_ex_inc,
            "miss_rate_wilson_95": list(wilson_interval(n_ex_inc, len(ex_ids))),
            "n_any_include": n_ex_any,
            "any_include_wilson_95": list(wilson_interval(n_ex_any, len(ex_ids))),
        },
        "include_agreement": {
            "n": len(inc_ids), "n_majority_include": n_inc, **_rate(n_inc, len(inc_ids))},
        "judge_demoted": {
            "n": len(jd_ids), "n_upheld": n_up, **_rate(n_up, len(jd_ids)),
            "n_majority_include": n_jd_inc},
        "inter_rater": {
            "fleiss_kappa": fleiss_kappa(table),
            "mean_pairwise_percent_agreement": inter["mean_pairwise_percent_agreement"],
        },
        "per_labeller": {
            str(i): {d: sum(c[r] == d for r in ids) for d in SCREENING_DECISIONS}
            for i, c in enumerate(copies, start=1)},
    }


def write_records_file(
    path: Path, strata: dict[str, str], statuses: dict[str, str],
    copies: Sequence[dict[str, str]], openalex_ids: dict[str, str] | None = None,
) -> None:
    """The anonymised per-record file: opaque id, the record's OpenAlex id, stratum, the
    system's status and the three decisions. No title, name, venue or attestation text."""
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(RECORDS_HEADER)
        for rid in sorted(strata):
            w.writerow([rid, (openalex_ids or {}).get(rid, ""), strata[rid],
                        statuses.get(rid, ""), *(c[rid] for c in copies)])


def score_from_records(records_path: Path) -> dict[str, Any]:
    """Recompute the scores from the anonymised per-record file, without the workbooks.
    ``integrity_flags`` and ``copy_identification`` need the workbooks and are not part of
    the result."""
    with Path(records_path).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or list(rows[0]) != RECORDS_HEADER:
        raise ValueError(f"{Path(records_path).name}: header is not {RECORDS_HEADER}")
    strata = {r["record_id"]: r["stratum"] for r in rows}
    copies = [{r["record_id"]: r[f"decision_{n}"].strip().lower() for r in rows}
              for n in (1, 2, 3)]
    return _score_decisions(strata, copies)


def _f(value: float | None, spec: str = ".3f") -> str:
    return "n/a" if value is None else format(value, spec)


def _ci(pair: Sequence[float | None]) -> str:
    return f"[{_f(pair[0], '.4f')}, {_f(pair[1], '.4f')}]"


def render_markdown(scores: dict[str, Any], run_id: str) -> str:
    ex_, inc, jd, ir = (scores["exclusions"], scores["include_agreement"],
                        scores["judge_demoted"], scores["inter_rater"])
    lines = [
        f"## Blind screening sample, {scores['n_records']} records of the delivered run "
        f"{run_id}", "",
        f"Records labelled: {scores['n_records']}. Three-way splits (no majority, left out of "
        f"every rate): {scores['n_no_majority']}.", "",
        "| Stratum | Records | Include | Exclude | Unsure | No majority | Any labeller include |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, b in scores["by_stratum"].items():
        lines.append(f"| {name} | {b['n_records']} | {b['include']} | {b['exclude']} | "
                     f"{b['unsure']} | {b['no_majority']} | {b['n_any_include']} |")
    lines += [
        "",
        f"- Tool EXCLUDE records a majority includes: {ex_['n_majority_include']} of "
        f"{ex_['n']} (miss rate Wilson 95% {_ci(ex_['miss_rate_wilson_95'])}); any labeller "
        f"includes: {ex_['n_any_include']} of {ex_['n']} "
        f"(Wilson 95% {_ci(ex_['any_include_wilson_95'])}).",
        f"- Tool INCLUDE records a majority includes: {inc['n_majority_include']} of "
        f"{inc['n']} (rate {_f(inc['rate'])}, Wilson 95% {_ci(inc['wilson_95'])}).",
        f"- Judge-demoted records a majority upholds (exclude or unsure): {jd['n_upheld']} of "
        f"{jd['n']} (rate {_f(jd['rate'])}, Wilson 95% {_ci(jd['wilson_95'])}); "
        f"{jd['n_majority_include']} included.",
        f"- Agreement: Fleiss kappa {_f(ir['fleiss_kappa'])}, mean pairwise percent "
        f"agreement {_f(ir['mean_pairwise_percent_agreement'])}.",
        "", "| Labeller | Include | Exclude | Unsure |", "|---|---|---|---|",
    ]
    for who, c in scores["per_labeller"].items():
        lines.append(f"| {who} | {c['include']} | {c['exclude']} | {c['unsure']} |")
    return "\n".join(lines) + "\n"


def _check(records_path: Path, out_dir: Path) -> int:
    try:
        again = score_from_records(records_path)
    except (ValueError, KeyError) as err:
        print(f"ERROR: {err}")
        return 1
    stored_path = out_dir / "blind_screening_scores.json"
    if not stored_path.is_file():
        print(f"ERROR: {stored_path} not found; nothing to compare with")
        return 1
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    stored.pop("integrity_flags", None)
    stored.pop("copy_identification", None)
    if stored != again:
        print("MISMATCH: the scores recomputed from the records file differ from "
              f"{stored_path.name}")
        return 1
    print(f"OK: the scores recomputed from {Path(records_path).name} match {stored_path.name}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workbook", type=Path, action="append")
    ap.add_argument("--key", type=Path)
    ap.add_argument("--run-id", help="the delivered run the sample was drawn from; "
                    "it names the run in the scores heading (required with --workbook)")
    ap.add_argument("--check", type=Path, metavar="RECORDS_CSV",
                    help="recompute the scores from the anonymised records file and compare")
    ap.add_argument("--copy", action="append", choices=("1", "2", "3"),
                    help="the sent copy of each workbook, once per workbook in order; used "
                    "only when a Guide has no workbook id line (else the Screening row "
                    "order is matched against the sent copies)")
    ap.add_argument("--sent-dir", type=Path, default=None,
                    help="folder of the sent copies (blind-screening-copy1.xlsx and so on); "
                    "needed only when a Guide has no workbook id line")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args(argv)
    if args.check is not None:
        return _check(args.check, args.out_dir)
    if not args.workbook or args.key is None or not args.run_id:
        ap.error("--workbook, --key and --run-id are required unless --check is given")
    try:
        if args.copy is not None and len(args.copy) != len(args.workbook):
            ap.error("--copy must be given once per --workbook, or not at all")
        scores = score_blind_screening(
            args.workbook, args.key, copies=args.copy, sent_dir=args.sent_dir)
    except ValueError as err:
        print(f"ERROR: {err}")
        return 1
    print("copy identification: " + ", ".join(scores["copy_identification"]))
    for line in integrity_warning_lines(scores["integrity_flags"]):
        print(line)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "blind_screening_scores.json").write_text(
        json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "blind_screening_scores.md").write_text(
        render_markdown(scores, args.run_id), encoding="utf-8")
    strata, _, statuses = _load_key(args.key)
    copies = [read_screening_decisions(Path(p)) for p in args.workbook]
    write_records_file(args.out_dir / RECORDS_FILE, strata, statuses, copies,
                       _load_openalex_ids(args.key))
    print(f"wrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
