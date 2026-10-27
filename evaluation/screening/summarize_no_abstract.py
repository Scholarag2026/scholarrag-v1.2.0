"""Summarise title-only screening of the no-abstract records into ``summary.json``.

Interpreter: any Python 3.12+ (stdlib + ``common``). Importer:
``tests/test_screening_no_abstract_results.py``.

Input: ``<dataset>_runA.jsonl`` for Fong_2021 and van_Dis_2020 in ``--results-dir`` (default
``screening/results/no_abstract``). These are the development records that carry no abstract,
screened with the shipped protocols and prompt. The rule under test is the title-only TOPIC
exclusion: a gold inclusion that the screener excludes outright on TOPIC is a lost inclusion.
Output: ``summary.json`` with one block per dataset and a ``combined`` block.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common import wilson_interval  # noqa: E402

DEFAULT_DIR = HERE / "results" / "no_abstract"
DATASETS = ("Fong_2021", "van_Dis_2020")


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def summarise(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    inc = [r for r in rows if int(r["label_included"]) == 1]
    excl = [r for r in rows if r["status"] == "EXCLUDE"]
    topic = [r for r in excl if r["criterion"] == "TOPIC"]
    lost = [r for r in inc if r["status"] == "EXCLUDE" and r["criterion"] == "TOPIC"]
    lo, hi = wilson_interval(len(lost), len(inc))
    return {
        "n_records": len(rows),
        "n_inclusions": len(inc),
        "inclusions_excluded_by_topic": len(lost),
        "inclusions_excluded_by_topic_wilson_95": None if lo is None else [lo, hi],
        "inclusions_needs_review": sum(1 for r in inc if r["status"] == "NEEDS_REVIEW"),
        "records_excluded": len(excl),
        "records_excluded_by_topic": len(topic),
        "records_excluded_by_topic_gold_inclusion": len(lost),
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_DIR)
    args = ap.parse_args(argv)
    per = {n: read_rows(args.results_dir / f"{n}_runA.jsonl") for n in DATASETS}
    summary = {
        "datasets": {n: summarise(r) for n, r in per.items()},
        "combined": summarise([r for rows in per.values() for r in rows]),
    }
    out = args.results_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
