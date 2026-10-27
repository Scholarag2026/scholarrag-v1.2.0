"""Summarise one SciFact train-split run (the 491-pair evaluation set) into ``summary.json``.

Interpreter: any Python 3.12+ (stdlib + ``common``).
Importer: ``tests/test_claims_train_sample_results.py``.

Input: ``scifact-train_runA.jsonl`` in ``--results-dir`` (default
``claims/results/v6/scifact_train491``). Output: ``summary.json`` in the same directory.

Gold SUPPORT rows are scored for recall of the ``verified`` status (strict) and of
``verified`` or ``needs_nuance`` together (lenient), each with a Wilson 95 % interval. Gold
CONTRADICT and NOT_ENOUGH_INFO rows are the non-support rows; the summary counts how many of
them the verifier called ``verified`` (a false verification) or ``needs_nuance``. Error rows
are counted in ``n_errors`` and left out of the per-class counts.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common import wilson_interval  # noqa: E402

DEFAULT_DIR = HERE / "results" / "v6" / "scifact_train491"
RUN_FILE = "scifact-train_runA.jsonl"


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _interval(count: int, n: int) -> list[float] | None:
    lo, hi = wilson_interval(count, n)
    return None if lo is None else [lo, hi]


def summarise(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    errors = [r for r in rows if r.get("error")]
    scored = [r for r in rows if not r.get("error")]
    sup = [r for r in scored if r["gold"] == "SUPPORT"]
    non = [r for r in scored if r["gold"] != "SUPPORT"]
    sc = Counter(r["predicted_status"] for r in sup)
    nc = Counter(r["predicted_status"] for r in non)
    n_sup = len(sup)
    lenient = sc["verified"] + sc["needs_nuance"]
    return {
        "n_rows": len(rows),
        "n_errors": len(errors),
        "support": {
            "n": n_sup,
            "verified": sc["verified"],
            "needs_nuance": sc["needs_nuance"],
            "unsupported": sc["unsupported"],
            "strict_recall": sc["verified"] / n_sup if n_sup else None,
            "strict_recall_wilson_95": _interval(sc["verified"], n_sup),
            "lenient_verified_or_nuance": lenient,
            "lenient_recall": lenient / n_sup if n_sup else None,
            "lenient_recall_wilson_95": _interval(lenient, n_sup),
        },
        "non_support": {
            "n": len(non),
            "by_gold": dict(sorted(Counter(r["gold"] for r in non).items())),
            "verified": nc["verified"],
            "needs_nuance": nc["needs_nuance"],
            "unsupported": nc["unsupported"],
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_DIR)
    args = ap.parse_args(argv)
    summary = summarise(read_rows(args.results_dir / RUN_FILE))
    out = args.results_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
