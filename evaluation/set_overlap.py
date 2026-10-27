"""Role sizes and pairwise overlap of every evaluation set.

Only counts and ids leave this module. A normalised value (a DOI, a claim, a title) is used
as a join key and is never returned by ``pairwise`` or written to the JSON output.

Run from ``evaluation/``::

    python set_overlap.py --screening-data <dir> --scifact-dir <dir>
    python set_overlap.py --check          # re-render the log block from the committed JSON
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Mapping
from itertools import combinations
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for _p in (HERE, HERE / "claims"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import read_jsonl, write_json  # noqa: E402

CLAIM_SETS = (
    "hss_dev_claims",
    "hss_dev_band2_claims",
    "hss_claims",
    "hss_test_v3_claims",
    "real_claims_dev",
    "real_claims_test",
)
SCREENING_SETS = ("Fong_2021", "van_Dis_2020", "Nagtegaal_2019", "Smid_2020", "van_de_Schoot_2017")
SCIFACT_TRAIN = "scifact_train_dev120"
SCIFACT_DEV = "scifact_dev"
BLOCK_NAME = "set-overlap"
DEFAULT_JSON = HERE / "set_overlap.json"
DEFAULT_LOG = None  # the development log is internal; pass --update-log to use one
MAX_EXAMPLES = 5
KEYS = ("dois", "claims", "titles", "claim_ids", "doc_ids")

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)


def norm_doi(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    for prefix in _DOI_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    return text or None


def norm_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[\W_]+", " ", text).strip()
    return text or None


def _add(index: dict[str, set[str]], key: str | None, ident: str) -> None:
    if key:
        index.setdefault(key, set()).add(ident)


def claim_set_keys(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    dois: dict[str, set[str]] = {}
    claims: dict[str, set[str]] = {}
    ids: list[str] = []
    for row in rows:
        item_id = str(row["item_id"])
        ids.append(item_id)
        _add(dois, norm_doi(row.get("source_doi")), item_id)
        _add(dois, norm_doi(row.get("chunk_doi")), item_id)
        _add(claims, norm_text(row.get("claim")), item_id)
    return {"n": len(rows), "item_ids": sorted(ids), "dois": dois, "claims": claims}


def screening_keys(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    dois: dict[str, set[str]] = {}
    titles: dict[str, set[str]] = {}
    with_doi = 0
    for row in rows:
        rid = str(row["record_id"])
        doi = norm_doi(row.get("doi"))
        if doi:
            with_doi += 1
        _add(dois, doi, rid)
        _add(titles, norm_text(row.get("title")), rid)
    return {"n": len(rows), "n_with_doi": with_doi, "dois": dois, "titles": titles}


def scifact_keys(train_sample: Path, dev_claims: Path) -> dict[str, Any]:
    sample = json.loads(Path(train_sample).read_text(encoding="utf-8"))
    train_claims: dict[str, set[str]] = {}
    train_docs: dict[str, set[str]] = {}
    for entry in sample:
        claim_id, _, doc_id = str(entry).partition(":")
        train_claims[claim_id] = {claim_id}
        if doc_id:
            train_docs[doc_id] = {doc_id}
    dev_rows = read_jsonl(dev_claims)
    dev_claim_ids: dict[str, set[str]] = {}
    dev_doc_ids: dict[str, set[str]] = {}
    for row in dev_rows:
        cid = str(row["id"])
        dev_claim_ids[cid] = {cid}
        docs = [str(d) for d in row.get("cited_doc_ids") or []]
        docs += [str(d) for d in (row.get("evidence") or {})]
        for d in docs:
            dev_doc_ids[d] = {d}
    return {
        "train": {"n": len(sample), "claim_ids": train_claims, "doc_ids": train_docs},
        "dev": {"n": len(dev_rows), "claim_ids": dev_claim_ids, "doc_ids": dev_doc_ids},
    }


def pairwise(sets: Mapping[str, Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    names = sorted(n for n, s in sets.items() if key in s)
    rows: list[dict[str, Any]] = []
    for a, b in combinations(names, 2):
        index_a, index_b = sets[a][key], sets[b][key]
        shared = sorted(set(index_a) & set(index_b))
        examples = sorted([min(index_a[v]), min(index_b[v])] for v in shared)[:MAX_EXAMPLES]
        rows.append({"a": a, "b": b, "key": key, "n_shared": len(shared), "examples": examples})
    return rows


def build(claims_dir: Path, screening_data: Path, scifact_dir: Path) -> dict[str, Any]:
    from run_scifact import resolve_data_dir

    sets: dict[str, dict[str, Any]] = {}
    sizes: dict[str, int] = {}
    for name in CLAIM_SETS:
        keys = claim_set_keys(Path(claims_dir) / f"{name}.jsonl")
        sizes[name] = keys["n"]
        sets[name] = {"dois": keys["dois"], "claims": keys["claims"]}
    for name in SCREENING_SETS:
        keys = screening_keys(Path(screening_data) / f"{name}.jsonl")
        sizes[name] = keys["n"]
        sizes[f"{name} (with DOI)"] = keys["n_with_doi"]
        sets[name] = {"dois": keys["dois"], "titles": keys["titles"]}
    folder = resolve_data_dir(Path(scifact_dir))
    sf = scifact_keys(Path(claims_dir) / "scifact_train_dev120.json", folder / "claims_dev.jsonl")
    for name, split in ((SCIFACT_TRAIN, "train"), (SCIFACT_DEV, "dev")):
        sizes[name] = sf[split]["n"]
        sets[name] = {"claim_ids": sf[split]["claim_ids"], "doc_ids": sf[split]["doc_ids"]}
    pairs: list[dict[str, Any]] = []
    for key in KEYS:
        pairs.extend(pairwise(sets, key))
    return {"sizes": sizes, "pairs": pairs}


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = ["### Set sizes", "", "| Set | n |", "| --- | ---: |"]
    for name, n in result["sizes"].items():
        lines.append(f"| {name} | {n} |")
    for key in KEYS:
        rows = [r for r in result["pairs"] if r["key"] == key]
        if not rows:
            continue
        lines += [
            "",
            f"### Shared `{key}` per pair",
            "",
            "| A | B | Shared | Example ids |",
            "| --- | --- | ---: | --- |",
        ]
        for r in rows:
            ex = "; ".join(f"{x} / {y}" for x, y in r["examples"])
            lines.append(f"| {r['a']} | {r['b']} | {r['n_shared']} | {ex} |")
    return "\n".join(lines) + "\n"


def _markers(name: str) -> tuple[str, str]:
    return f"<!-- {name}:start -->", f"<!-- {name}:end -->"


def _locate(text: str, name: str, log: Path) -> tuple[int, int, str]:
    start, end = _markers(name)
    i, j = text.find(start), text.find(end)
    if i < 0 or j < 0 or j < i:
        raise ValueError(f"log {log} is missing the {start} / {end} markers")
    return i + len(start), j, text


def update_log_block(log: Path, block: str, name: str) -> None:
    text = Path(log).read_text(encoding="utf-8")
    a, b, _ = _locate(text, name, log)
    new = text[:a] + "\n" + block.strip("\n") + "\n" + text[b:]
    Path(log).write_text(new, encoding="utf-8")


def _read_block(log: Path, name: str) -> str:
    text = Path(log).read_text(encoding="utf-8")
    a, b, _ = _locate(text, name, log)
    return text[a:b].strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Role sizes and pairwise overlap of evaluation sets.")
    ap.add_argument("--claims-dir", type=Path, default=HERE / "claims")
    ap.add_argument("--screening-data", type=Path)
    ap.add_argument("--scifact-dir", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--update-log", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        log = args.update_log or DEFAULT_LOG
        if log is None:
            print("check failed: --update-log is required to check a log block")
            return 1
        try:
            expected = render_markdown(json.loads(args.out.read_text(encoding="utf-8"))).strip()
            actual = _read_block(log, BLOCK_NAME)
        except (OSError, ValueError) as exc:
            print(f"check failed: {exc}")
            return 1
        if expected != actual:
            print("check failed: the log block differs from the committed JSON")
            return 1
        print("set overlap log block matches the committed JSON")
        return 0
    if args.screening_data is None or args.scifact_dir is None:
        ap.error("--screening-data and --scifact-dir are required")
    result = build(args.claims_dir, args.screening_data, args.scifact_dir)
    write_json(args.out, result)
    if args.update_log:
        update_log_block(args.update_log, render_markdown(result), BLOCK_NAME)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
