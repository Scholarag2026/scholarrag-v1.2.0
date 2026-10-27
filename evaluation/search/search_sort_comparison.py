"""OpenAlex relevance order against citation order, side by side.

Runs one plain phrase and the first-round queries of the demo record under both search
sorts at the per-query cap of 25, with the record's freeze date as the publication cutoff.
OpenAlex only; no model call. Run it with the backend interpreter (it imports
``app.clients.openalex``)::

    python evaluation/search/search_sort_comparison.py \
        --record demo/expected/screening_record.json \
        --out evaluation/search/results/search_sort_comparison.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
from collections.abc import Iterable
from datetime import date
from pathlib import Path

PER_PAGE = 25
SORTS = ("relevance", "cited_by_count")
PHRASE_LABEL = "written corrective feedback"
DEMO_LABEL = "demo round 1 frozen queries"


def load_round_queries(record_path: Path, round_number: int) -> list[str]:
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    for rnd in record["provenance"]["rounds"]:
        if rnd.get("round") == round_number:
            return [q["query"] for q in rnd["queries"]]
    raise KeyError(f"round {round_number} not in {record_path}")


def publication_cutoff(record: dict) -> date | None:
    value = (record.get("criteria") or {}).get("publication_date_max")
    return date.fromisoformat(value) if value else None


def summarise(page) -> dict:
    years = [p.year for p in page.papers if p.year is not None]
    median = statistics.median(years) if years else None
    if isinstance(median, float) and median.is_integer():
        median = int(median)
    return {
        "total_count": page.total_count,
        "sort": page.sort,
        "per_page": page.per_page,
        "returned": len(page.papers),
        "median_year": median,
        "top": [
            {
                "rank": i,
                "title": p.title,
                "year": p.year,
                "cited_by_count": p.citation_count,
                "doi": p.doi,
            }
            for i, p in enumerate(page.papers, start=1)
        ],
    }


def _norm_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (title or "").lower())).strip()


def _keys(item: dict) -> tuple[str | None, str]:
    doi = (item.get("doi") or "").strip().lower() or None
    return doi, _norm_title(item.get("title"))


def overlap_at_cap(a: list[dict], b: list[dict]) -> int:
    """Papers present in both lists: shared DOI, else shared normalised title."""
    b_dois = {d for d, _ in map(_keys, b) if d}
    b_titles = {t for _, t in map(_keys, b) if t}
    count = 0
    for item in a:
        doi, title = _keys(item)
        if (doi and doi in b_dois) or (not doi and title and title in b_titles):
            count += 1
    return count


def llm_modules_loaded(modules: Iterable[str]) -> bool:
    return any(m == "app.agents" or m.startswith("app.agents.") for m in modules)


async def run_comparison(record_path: Path, out_path: Path) -> dict:
    from app.clients.openalex import OpenAlexClient  # backend/ is on sys.path by now

    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    cutoff = publication_cutoff(record)
    inputs = [
        {"label": PHRASE_LABEL, "queries": [PHRASE_LABEL]},
        {"label": DEMO_LABEL, "queries": load_round_queries(record_path, 1)},
    ]
    client = OpenAlexClient()
    runs: dict = {}
    for item in inputs:
        runs[item["label"]] = {}
        for query in item["queries"]:
            pages = {}
            for sort in SORTS:
                page = await client.search_page(
                    query, sort=sort, per_page=PER_PAGE, to_publication_date=cutoff
                )
                pages[sort] = summarise(page)
            overlap = overlap_at_cap(pages["relevance"]["top"], pages["cited_by_count"]["top"])
            runs[item["label"]][query] = {
                "relevance": pages["relevance"],
                "cited_by_count": pages["cited_by_count"],
                "overlap": overlap,
            }
    result = {
        "inputs": inputs,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "llm_modules_loaded": llm_modules_loaded(sys.modules),
        "runs": runs,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    backend = Path(__file__).resolve().parents[2] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    result = asyncio.run(run_comparison(args.record, args.out))
    return 1 if result["llm_modules_loaded"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
