"""Every search entry point reaches the OpenAlex client with the sort and cap settings.

``OpenAlexClient._get_json`` is the only thing patched, so the real client and the real
``SearchService`` run for the one-shot job, Smart Search and Deep Search.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

from app.clients.openalex import OpenAlexClient  # noqa: E402
from app.config import settings  # noqa: E402
from tests.conftest import TEST_DATABASE_URL  # noqa: E402
from tests.test_deep_search_loop import (  # noqa: E402
    _fake_session_factory,
    _FakeExpansionAgent,
)
from tests.test_smart_search_service import (
    _fake_session_factory as _smart_session_factory,  # noqa: E402
)
from tests.test_smart_search_service import _query_result  # noqa: E402

SORT_CASES = [("relevance", None), ("cited_by_count", "cited_by_count:desc")]


def _get_json_mock() -> AsyncMock:
    return AsyncMock(return_value={"meta": {"count": 7}, "results": []})


def _assert_works_calls(get_json: AsyncMock, expected_sort: str | None) -> None:
    works_calls = [c for c in get_json.await_args_list if c.args[0] == "/works"]
    assert works_calls
    assert all(c.args[1].get("sort") == expected_sort for c in works_calls)
    assert all(c.args[1]["per_page"] == settings.search_per_query_cap for c in works_calls)


@pytest.mark.parametrize("sort, expected", SORT_CASES)
async def test_one_shot_search_uses_the_sort_setting(monkeypatch, sort, expected):
    import app.api.search as search_module

    monkeypatch.setattr(settings, "search_sort", sort)
    get_json = _get_json_mock()
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(search_module, "_session_factory", factory)
    try:
        with (
            patch.object(OpenAlexClient, "_get_json", new=get_json),
            patch.object(search_module.task_service, "update_job_status", new=AsyncMock()),
            patch.object(search_module, "batch_enrich_wos", new=AsyncMock()),
        ):
            await search_module._run_search_background(uuid4(), "teacher burnout", None, None, None)
    finally:
        await engine.dispose()

    _assert_works_calls(get_json, expected)


@pytest.mark.parametrize("sort, expected", SORT_CASES)
async def test_smart_search_uses_the_sort_setting(monkeypatch, sort, expected):
    from app.services import smart_search as smart_search_module

    monkeypatch.setattr(settings, "search_sort", sort)
    get_json = _get_json_mock()
    with (
        patch.object(OpenAlexClient, "_get_json", new=get_json),
        patch.object(
            smart_search_module,
            "generate_search_queries_with_provenance",
            new=AsyncMock(return_value=_query_result(["q1", "q2"])),
        ),
        patch.object(smart_search_module, "get_wos_journal_count", new=AsyncMock(return_value=1)),
        patch.object(smart_search_module, "is_wos_indexed_bulk", new=AsyncMock(return_value={})),
        patch.object(smart_search_module, "should_abort", new=AsyncMock(return_value=False)),
        patch.object(smart_search_module, "update_job_status", new=AsyncMock()),
    ):
        await smart_search_module.run_smart_search(
            project_id=uuid4(),
            job_id=uuid4(),
            query="teacher burnout",
            session_factory=_smart_session_factory,
        )

    _assert_works_calls(get_json, expected)


@pytest.mark.parametrize("sort, expected", SORT_CASES)
async def test_deep_search_uses_the_sort_setting(monkeypatch, sort, expected):
    from app.services import deep_search as deep_search_module

    monkeypatch.setattr(settings, "search_sort", sort)
    get_json = _get_json_mock()
    with (
        patch.object(OpenAlexClient, "_get_json", new=get_json),
        patch.object(
            deep_search_module,
            "get_query_expansion_agent",
            return_value=_FakeExpansionAgent(["e1", "e2"]),
        ),
        patch.object(deep_search_module, "batch_enrich_wos", new=AsyncMock()),
        patch.object(
            deep_search_module.task_service, "should_abort", new=AsyncMock(return_value=False)
        ),
        patch.object(deep_search_module.task_service, "update_job_status", new=AsyncMock()),
    ):
        await deep_search_module.run_deep_search(
            project_id=uuid4(),
            job_id=uuid4(),
            query="teacher burnout",
            filters={"max_rounds": 2},
            session_factory=_fake_session_factory,
        )

    _assert_works_calls(get_json, expected)
