# backend/tests/test_search_service.py
import inspect
from unittest.mock import patch

import pytest

from app.clients.openalex import OpenAlexSearchPage
from app.config import settings
from app.schemas.paper import PaperData
from app.services.search import SearchService


def _page(papers, total=None, sort="relevance", cap=25):
    return OpenAlexSearchPage(papers, total, sort, cap)


def _make_paper(doi: str | None, title: str, source: str = "openalex", citations: int = 10):
    return PaperData(
        doi=doi,
        title=title,
        authors=[{"name": "Test Author"}],
        year=2023,
        citation_count=citations,
        source_api=source,
    )


@pytest.mark.asyncio
async def test_search_returns_openalex_results():
    oa_results = [
        _make_paper("10.1/a", "Paper A"),
        _make_paper("10.1/b", "Paper B"),
        _make_paper("10.1/c", "Paper C"),
    ]

    with patch.object(SearchService, "_search_openalex", return_value=_page(oa_results)):
        svc = SearchService()
        papers, sources = await svc.search("test query")

    assert len(papers) == 3
    assert sources == {"openalex": 3}


@pytest.mark.asyncio
async def test_search_deduplicates_by_doi():
    oa_results = [
        _make_paper("10.1/same", "Paper Same", citations=50),
        _make_paper("10.1/SAME", "Paper Same Other Casing", citations=45),
        _make_paper("10.1/unique", "Paper Unique", citations=20),
    ]

    with patch.object(SearchService, "_search_openalex", return_value=_page(oa_results)):
        svc = SearchService()
        papers, _ = await svc.search("test query")

    assert len(papers) == 2
    dois = {p.doi.lower() for p in papers}
    assert dois == {"10.1/same", "10.1/unique"}


@pytest.mark.asyncio
async def test_search_keeps_higher_citation_on_dedup():
    oa_results = [
        _make_paper("10.1/dup", "Low version", citations=50),
        _make_paper("10.1/dup", "High version", citations=100),
    ]

    with patch.object(SearchService, "_search_openalex", return_value=_page(oa_results)):
        svc = SearchService()
        papers, _ = await svc.search("test")

    assert len(papers) == 1
    assert papers[0].citation_count == 100


@pytest.mark.asyncio
async def test_search_sorts_by_citations_under_the_citation_setting(monkeypatch):
    monkeypatch.setattr(settings, "search_sort", "cited_by_count")
    oa_results = [
        _make_paper("10.1/low", "Low", citations=5),
        _make_paper("10.1/high", "High", citations=500),
        _make_paper("10.1/mid", "Mid", citations=50),
    ]

    with patch.object(SearchService, "_search_openalex", return_value=_page(oa_results)):
        svc = SearchService()
        papers, _ = await svc.search("test")

    assert papers[0].citation_count == 500
    assert papers[1].citation_count == 50
    assert papers[2].citation_count == 5


@pytest.mark.asyncio
async def test_search_relevance_keeps_the_openalex_order(monkeypatch):
    monkeypatch.setattr(settings, "search_sort", "relevance")
    page = _page(
        [
            _make_paper("10.1/a", "A", citations=1),
            _make_paper(None, "B", citations=2),
            _make_paper("10.1/c", "C", citations=900),
        ]
    )
    with patch.object(SearchService, "_search_openalex", return_value=page):
        papers, _ = await SearchService().search("q")
    assert [p.title for p in papers] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_search_relevance_dedup_keeps_first_position_and_higher_cited():
    page = _page(
        [
            _make_paper("10.1/x", "X low", citations=1),
            _make_paper("10.1/y", "Y", citations=5),
            _make_paper("10.1/X", "X high", citations=9),
        ]
    )
    with patch.object(SearchService, "_search_openalex", return_value=page):
        papers, _ = await SearchService().search("q")
    assert [p.title for p in papers] == ["X high", "Y"]


@pytest.mark.asyncio
async def test_search_cited_by_count_resorts_the_merge(monkeypatch):
    monkeypatch.setattr(settings, "search_sort", "cited_by_count")
    page = _page(
        [
            _make_paper("10.1/a", "A", citations=1),
            _make_paper(None, "B", citations=50),
            _make_paper("10.1/c", "C", citations=900),
        ]
    )
    with patch.object(SearchService, "_search_openalex", return_value=page):
        papers, _ = await SearchService().search("q")
    counts = [p.citation_count for p in papers]
    assert counts == sorted(counts, reverse=True)
    assert [p.title for p in papers] == ["C", "B", "A"]


@pytest.mark.asyncio
async def test_search_fills_stats_with_total_sort_and_cap():
    page = _page([_make_paper("10.1/a", "A")], total=4321, sort="relevance", cap=25)
    stats: dict = {}
    with patch.object(SearchService, "_search_openalex", return_value=page):
        await SearchService().search("q", stats=stats)
    assert stats == {"total_count": 4321, "sort": "relevance", "per_query_cap": 25}


@pytest.mark.asyncio
async def test_search_stats_on_swallowed_failure_has_no_total():
    stats: dict = {}
    with patch.object(SearchService, "_search_openalex", side_effect=RuntimeError("down")):
        await SearchService().search("q", stats=stats)
    assert stats["total_count"] is None


@pytest.mark.asyncio
async def test_search_handles_api_failure_gracefully():
    with patch.object(
        SearchService, "_search_openalex", side_effect=Exception("OpenAlex down")
    ):
        svc = SearchService()
        papers, sources = await svc.search("test")

    assert papers == []
    assert sources == {"openalex": 0}


@pytest.mark.asyncio
async def test_search_raise_on_failure_propagates_the_provider_error():
    """Callers that must distinguish 'no results' from 'provider down' can opt out."""
    with patch.object(
        SearchService, "_search_openalex", side_effect=RuntimeError("OpenAlex down")
    ):
        svc = SearchService()
        with pytest.raises(RuntimeError, match="OpenAlex down"):
            await svc.search("test", raise_on_failure=True)


@pytest.mark.asyncio
async def test_search_passes_filters_through():
    with patch.object(SearchService, "_search_openalex", return_value=_page([])) as mock_oa:
        svc = SearchService()
        await svc.search("test", year_from=2020, year_to=2024, min_citations=10)

    assert mock_oa.await_args.kwargs == {
        "year_from": 2020,
        "year_to": 2024,
        "min_citations": 10,
        "to_publication_date": None,
    }


@pytest.mark.asyncio
async def test_search_passes_to_publication_date_through():
    """Forwarded to the OpenAlex client exactly like the other filters."""
    from datetime import date

    with patch.object(SearchService, "_search_openalex", return_value=_page([])) as mock_oa:
        svc = SearchService()
        await svc.search("test", to_publication_date=date(2026, 9, 8))

    assert mock_oa.await_args.kwargs["to_publication_date"] == date(2026, 9, 8)


def test_search_service_is_openalex_only():
    """S2 and CORE legs are gone from the search fan-out."""
    from app.services import search as search_module

    source = inspect.getsource(search_module)
    assert "semantic_scholar" not in source
    assert "SemanticScholar" not in source
    assert "core_api" not in source
    assert "CoreClient" not in source
    assert not hasattr(SearchService, "_search_semantic_scholar")
    assert not hasattr(SearchService, "_search_core")
