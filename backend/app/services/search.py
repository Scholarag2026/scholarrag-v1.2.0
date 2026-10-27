# backend/app/services/search.py
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import date

from app.clients.openalex import OpenAlexClient, OpenAlexSearchPage
from app.config import settings
from app.schemas.paper import PaperData

logger = logging.getLogger(__name__)

#: Query parameters that identify the account behind a request (polite-pool address, API
#: key). They must not reach a stored job result or an exported screening record.
_URL_IDENTITY_RE = re.compile(r"(mailto|api_key)=[^&\s']+")


def describe_search_failure(exc: BaseException) -> str:
    """Compact, shareable one-liner for a failed search query.

    ``"<ExceptionClass>: <message>"``; for an HTTP status error the message is the status
    plus the provider's own explanation (OpenAlex's ``message``/``error`` JSON field, e.g.
    "Insufficient budget ... Resets at midnight UTC") instead of the request URL, and any
    ``mailto=``/``api_key=`` value is redacted.
    """
    text = f"{type(exc).__name__}: {exc}"
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) is not None:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("error") or "")[:200]
        except Exception:
            detail = (getattr(response, "text", "") or "")[:200]
        reason = getattr(response, "reason_phrase", "") or ""
        text = f"{type(exc).__name__}: HTTP {response.status_code}"
        if reason:
            text += f" {reason}"
        if detail:
            text += f" - {detail}"
    return _URL_IDENTITY_RE.sub(r"\1=***", text)


class SearchService:
    """Scholarly search fan-out. OpenAlex is the only scholarly data source."""

    def __init__(self) -> None:
        self._openalex = OpenAlexClient()

    async def search(
        self,
        query: str,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        min_citations: int | None = None,
        to_publication_date: date | None = None,
        raise_on_failure: bool = False,
        stats: dict | None = None,
    ) -> tuple[list[PaperData], dict[str, int]]:
        """Search OpenAlex, deduplicate, and return merged results.

        Returns (papers, sources) where sources is a count per API. The tuple shape is
        preserved for callers even though there is now exactly one source.

        A provider failure is logged and yields an empty result by default (the one-shot
        ``/search`` endpoint). Callers that must tell "no results" from "provider down"
        (the Smart Search fan-out) pass ``raise_on_failure=True`` and get the exception.

        ``to_publication_date`` is forwarded to the OpenAlex client
        unchanged; see ``OpenAlexClient.search``.

        Result order follows ``settings.search_sort``: ``cited_by_count`` re-sorts the merge
        by citation count (stable), ``relevance`` keeps the OpenAlex order. When *stats* is
        a dict it is filled with ``total_count`` (OpenAlex ``meta.count``, ``None`` when
        unknown or the query failed), ``sort`` and ``per_query_cap``.
        """
        try:
            page = await self._search_openalex(
                query,
                year_from=year_from,
                year_to=year_to,
                min_citations=min_citations,
                to_publication_date=to_publication_date,
            )
        except Exception as exc:
            logger.warning("OpenAlex search failed for %r: %s", query, exc)
            if stats is not None:
                stats.update(
                    {
                        "total_count": None,
                        "sort": settings.search_sort,
                        "per_query_cap": settings.search_per_query_cap,
                    }
                )
            if raise_on_failure:
                raise
            page = OpenAlexSearchPage([], None, settings.search_sort, settings.search_per_query_cap)

        oa_results = page.papers
        if stats is not None:
            stats.update(
                {
                    "total_count": page.total_count,
                    "sort": page.sort,
                    "per_query_cap": page.per_page,
                }
            )

        sources = {"openalex": len(oa_results)}

        # Deduplicate by DOI, keeping the version with higher citation count
        merged = self._deduplicate(list(oa_results))

        # Under the citation setting, order by citation count descending (stable); under
        # relevance, keep the order OpenAlex returned.
        if settings.search_sort == "cited_by_count":
            merged.sort(key=lambda p: p.citation_count or 0, reverse=True)

        return merged, sources

    async def _search_openalex(self, query: str, **kwargs) -> OpenAlexSearchPage:
        return await self._openalex.search_page(query, **kwargs)

    @staticmethod
    def _deduplicate(papers: list[PaperData]) -> list[PaperData]:
        """Deduplicate papers by DOI, keeping the higher-cited duplicate.

        Each survivor stays at the position of its first occurrence, and papers without a
        DOI stay where they were, so the input order is preserved.
        """
        kept: list[PaperData | None] = []
        first_index: dict[str, int] = {}

        for paper in papers:
            if not paper.doi:
                kept.append(paper)
                continue

            doi_lower = paper.doi.lower()
            index = first_index.get(doi_lower)
            if index is None:
                first_index[doi_lower] = len(kept)
                kept.append(paper)
            else:
                existing = kept[index]
                if existing is not None and (paper.citation_count or 0) > (
                    existing.citation_count or 0
                ):
                    kept[index] = paper

        return [paper for paper in kept if paper is not None]


async def gather_search_results(
    search_service: SearchService,
    queries: Sequence[str],
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    min_citations: int | None = None,
    to_publication_date: date | None = None,
    concurrency: int | None = None,
    stop_check: Callable[[], Awaitable[bool]] | None = None,
    stats_out: dict[str, dict] | None = None,
) -> tuple[list[tuple[str, list[PaperData]]], bool, list[tuple[str, str]]]:
    """Run *queries* against *search_service* with bounded concurrency.

    Returns ``(results, stopped, failures)``:

    * ``results`` holds one ``(query, papers)`` pair per query that actually executed and
      returned, in the input order of *queries*. Queries that raised are logged and omitted
      from ``results``.
    * ``stopped`` is True when *stop_check* returned True, meaning the remaining queries were
      deliberately skipped (time budget exhausted or job cancelled).
    * ``failures`` lists ``(query, "<ExceptionClass>: <message>")`` for every query that
      raised, in input order, so a caller can tell an empty round caused by a provider
      outage or quota block from one where the literature genuinely ran dry.

    When *stats_out* is given, ``stats_out[query]`` receives the ``stats`` dict of each query
    that ran (total hits, sort, per-query cap).

    *stop_check* is awaited immediately before each individual query is issued, which is what
    makes a wall-clock cap bind *inside* a round instead of only at round boundaries.
    """
    if not queries:
        return [], False, []

    limit = concurrency if concurrency is not None else settings.search_fanout_concurrency
    semaphore = asyncio.Semaphore(max(1, limit))
    stopped = False
    failures: dict[str, str] = {}

    async def _run_one(query: str) -> tuple[str, list[PaperData]] | None:
        nonlocal stopped
        async with semaphore:
            if stopped:
                return None
            if stop_check is not None and await stop_check():
                stopped = True
                return None
            query_stats: dict = {}
            try:
                papers, _sources = await search_service.search(
                    query,
                    year_from=year_from,
                    year_to=year_to,
                    min_citations=min_citations,
                    to_publication_date=to_publication_date,
                    raise_on_failure=True,
                    stats=query_stats,
                )
            except Exception as exc:
                logger.warning("Search failed for query %r", query, exc_info=True)
                failures[query] = describe_search_failure(exc)
                return None
            if stats_out is not None:
                stats_out[query] = query_stats
            return query, papers

    raw = await asyncio.gather(*(_run_one(q) for q in queries))
    ordered_failures = [(q, failures[q]) for q in queries if q in failures]
    return [item for item in raw if item is not None], stopped, ordered_failures
