#!/usr/bin/env python
"""Open-access share of a demonstration run's included records.

The share is counted over the records a run screened in (outcome "included" in
``screening_record.json``) and is read from the OpenAlex ``open_access.is_oa`` field.
The raw OpenAlex answers are stored beside the result, so the number can be rechecked
offline with ``--offline --check`` and no network access.

Standard library plus httpx only. The contact address for the OpenAlex polite pool is
taken from the ``OPENALEX_EMAIL`` environment variable when it is set; this script
never reads a ``.env`` file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

import httpx

OPENALEX_WORKS = "https://api.openalex.org/works"
BATCH_SIZE = 50
SELECT = "id,doi,open_access"
DEFAULT_RETRY_WAIT = 2.0


def short_id(value: str) -> str:
    """Return the bare OpenAlex id (``W123``) for a URL or an id."""
    return (value or "").rstrip("/").rsplit("/", 1)[-1]


def included_records(record: Mapping) -> list[dict]:
    """Return the ``records`` entries with outcome "included", in file order."""
    return [r for r in record.get("records", []) if r.get("outcome") == "included"]


def _get(client: httpx.Client, params: dict) -> httpx.Response:
    response = client.get(OPENALEX_WORKS, params=params)
    if response.status_code == 429 or response.status_code >= 500:
        try:
            wait = float(response.headers.get("Retry-After", DEFAULT_RETRY_WAIT))
        except ValueError:
            wait = DEFAULT_RETRY_WAIT
        time.sleep(wait)
        response = client.get(OPENALEX_WORKS, params=params)
    response.raise_for_status()
    return response


def fetch_open_access(
    ids: Sequence[str], *, client: httpx.Client, mailto: str | None = None
) -> dict:
    """Ask OpenAlex for the open-access fields of *ids*, 50 per request."""
    results: dict[str, dict] = {}
    for start in range(0, len(ids), BATCH_SIZE):
        batch = list(ids[start : start + BATCH_SIZE])
        params = {
            "filter": "openalex:" + "|".join(batch),
            "per-page": str(BATCH_SIZE),
            "select": SELECT,
        }
        if mailto:
            params["mailto"] = mailto
        for work in _get(client, params).json().get("results", []):
            oa = work.get("open_access") or {}
            results[short_id(work.get("id", ""))] = {
                "doi": work.get("doi"),
                "is_oa": bool(oa.get("is_oa")),
                "oa_status": oa.get("oa_status"),
                "oa_url": oa.get("oa_url"),
            }
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": OPENALEX_WORKS,
        "results": results,
    }


def build_share(record: Mapping, cache: Mapping, *, run_id: str) -> dict:
    """Count the open-access share of the included records against *cache*."""
    ids = [short_id(r.get("openalex_id", "")) for r in included_records(record)]
    results = cache.get("results", {})
    found = [results[i] for i in ids if i in results]
    is_oa = sum(1 for f in found if f.get("is_oa"))
    status = Counter(f.get("oa_status") or "unknown" for f in found)
    return {
        "run_id": run_id,
        "fetched_at": cache.get("fetched_at"),
        "source": cache.get("source", OPENALEX_WORKS),
        "included": len(ids),
        "matched": len(found),
        "is_oa": is_oa,
        "share_is_oa": round(is_oa / len(ids), 3) if ids else None,
        "with_oa_url": sum(1 for f in found if f.get("oa_url")),
        "by_oa_status": dict(sorted(status.items())),
        "unmatched_ids": sorted(i for i in ids if i not in results),
    }


def _dump(doc: Mapping) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(
    argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None
) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--offline", action="store_true", help="read the cache, no network")
    ap.add_argument(
        "--check",
        action="store_true",
        help="compare with --out using the stored cache, no network, exit 1 on difference",
    )
    args = ap.parse_args(argv)

    run_dir: Path = args.run_dir
    out = args.out or run_dir / "oa_share.json"
    cache_path = args.cache or run_dir / "oa_share_openalex.json"
    record = json.loads((run_dir / "screening_record.json").read_text(encoding="utf-8"))

    # A check never fetches and never rewrites the stored answers: the fetch time is part
    # of the share, so a fresh fetch could not match and would destroy the offline recheck.
    if args.offline or args.check:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        ids = [short_id(r.get("openalex_id", "")) for r in included_records(record)]
        ids = [i for i in ids if i]
        try:
            with httpx.Client(transport=transport, timeout=30.0) as client:
                cache = fetch_open_access(
                    ids, client=client, mailto=os.environ.get("OPENALEX_EMAIL") or None
                )
        except httpx.HTTPError as exc:
            print(f"OpenAlex request failed: {exc}", file=sys.stderr)
            return 1
        cache_path.write_text(_dump(cache), encoding="utf-8")

    share = build_share(record, cache, run_id=run_dir.resolve().name)
    if args.check:
        current = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        if current != share:
            print(f"MISMATCH: {out} differs from the recomputed share", file=sys.stderr)
            return 1
        print(f"OK: {out} matches")
        return 0
    out.write_text(_dump(share), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
