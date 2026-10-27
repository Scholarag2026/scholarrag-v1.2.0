"""Deduplicated corpus basis and the screener operating point (evaluation E1).

Interpreter: ``evaluation/.venv/Scripts/python`` or the system ``python`` (stdlib only).

Some SYNERGY exports list a row as a duplicate of another record through
``duplicate_record_id``. The primary basis drops such a row and keeps the record it names, so
a final inclusion is counted once. The committed manifests in ``dedup_basis/`` hold the dropped
ids for each deduplicated dataset and the unique-record counts.

CLI::

    python corpus_basis.py --dataset van_de_Schoot_2017 --csv path/to/van_de_Schoot_2017.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BASIS_DIR: Path = HERE / "dedup_basis"
DEDUP_DATASETS: tuple[str, ...] = ("Nagtegaal_2019", "van_de_Schoot_2017")

DUPLICATE_RULE = (
    "a row whose duplicate_record_id is non-empty is a duplicate of the record it names "
    "and is dropped; the named record is kept"
)
SUBMITTED_BASIS_REASON = (
    "the export lists 407 rows as duplicates of other records (duplicate_record_id); "
    "5 of them are final inclusions, so the submitted basis counted those inclusions twice"
)
SUBMITTED_BASIS_REASONS: dict[str, str] = {
    "van_de_Schoot_2017": SUBMITTED_BASIS_REASON,
    "Nagtegaal_2019": (
        "the export lists 11 rows as duplicates of other records (duplicate_record_id); "
        "none of them is a final inclusion, so only the title-and-abstract counts change"
    ),
}


@dataclass(frozen=True)
class DuplicateManifest:
    dataset: str
    n_rows: int
    duplicate_record_ids: tuple[int, ...]
    n_unique: int
    n_included_unique: int
    n_ta_positive_unique: int
    rule: str


def _flag(value: str | None) -> int:
    """Read a 0/1 label cell; blank is 0."""
    if value is None or not value.strip():
        return 0
    return int(float(value))


def build_manifest(csv_path: Path, dataset: str) -> DuplicateManifest:
    """Read the v1 CSV and list the rows that duplicate another record."""
    with Path(csv_path).open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    ids = {int(r["record_id"]) for r in rows}
    pointer: dict[int, int] = {}
    for r in rows:
        dup = (r.get("duplicate_record_id") or "").strip()
        if dup:
            pointer[int(r["record_id"])] = int(float(dup))
    for rid, target in pointer.items():
        if target not in ids:
            raise ValueError(
                f"{dataset}: record_id {rid} names duplicate_record_id {target}, "
                f"which is not in the file (record_id {target} is absent)"
            )
        if target in pointer:
            raise ValueError(
                f"{dataset}: record_id {rid} is a duplicate of a duplicate "
                f"(record_id {target} is itself a duplicate of {pointer[target]})"
            )
    unique = [r for r in rows if int(r["record_id"]) not in pointer]
    return DuplicateManifest(
        dataset=dataset,
        n_rows=len(rows),
        duplicate_record_ids=tuple(sorted(pointer)),
        n_unique=len(unique),
        n_included_unique=sum(_flag(r.get("label_included")) for r in unique),
        n_ta_positive_unique=sum(_flag(r.get("label_abstract_screening")) for r in unique),
        rule=DUPLICATE_RULE,
    )


def write_manifest(m: DuplicateManifest, path: Path) -> None:
    data = asdict(m)
    data["duplicate_record_ids"] = sorted(m.duplicate_record_ids)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> DuplicateManifest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["duplicate_record_ids"] = tuple(data["duplicate_record_ids"])
    return DuplicateManifest(**data)


def load_duplicate_ids(dataset: str, basis_dir: Path = BASIS_DIR) -> frozenset[int]:
    """Dropped ids for *dataset*; empty off the list, an error when a listed one has no file."""
    if dataset not in DEDUP_DATASETS:
        return frozenset()
    path = Path(basis_dir) / f"{dataset}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no duplicate manifest for {dataset}: {path}")
    return frozenset(load_manifest(path).duplicate_record_ids)


def apply_basis(
    rows: Sequence[Mapping[str, Any]], duplicate_ids: frozenset[int]
) -> list[dict[str, Any]]:
    """Drop the rows whose record_id is a duplicate; the kept original keeps its own row."""
    return [dict(r) for r in rows if r["record_id"] not in duplicate_ids]


def _is_screened_in(row: Mapping[str, Any]) -> bool:
    status = row.get("status")
    if status is not None:
        return status in ("INCLUDE", "NEEDS_REVIEW")
    return row.get("predicted") == 1


def _is_excluded(row: Mapping[str, Any]) -> bool:
    status = row.get("status")
    if status is not None:
        return status == "EXCLUDE"
    return row.get("predicted") == 0


def operating_point(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Screener counts on *rows*; rows with ``predicted is None`` are unscreened and skipped."""
    scored = [r for r in rows if r.get("predicted") is not None]
    final_pos = [r for r in scored if r.get("label_included") == 1]
    ta_pos = [r for r in scored if r.get("label_abstract_screening") == 1]
    return {
        "n": len(scored),
        "n_screened_in": sum(_is_screened_in(r) for r in scored),
        "n_excluded": sum(_is_excluded(r) for r in scored),
        "n_final_pos": len(final_pos),
        "n_final_kept": sum(_is_screened_in(r) for r in final_pos),
        "n_ta_pos": len(ta_pos),
        "n_ta_kept": sum(_is_screened_in(r) for r in ta_pos),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    m = build_manifest(args.csv, args.dataset)
    out = args.out or BASIS_DIR / f"{args.dataset}.json"
    write_manifest(m, out)
    print(
        f"{args.dataset}: n_rows={m.n_rows} duplicates={len(m.duplicate_record_ids)} "
        f"n_unique={m.n_unique} n_included_unique={m.n_included_unique}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
