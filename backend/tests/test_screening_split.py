"""Splitting a failed screening batch into smaller calls (no model call, no database)."""

import math
import os

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

import pytest  # noqa: E402

from app.agents.relevance_screener_agent import ScreeningError  # noqa: E402
from app.services.screening_split import screen_batch_with_split  # noqa: E402

ERROR_TEXT = "UnexpectedModelBehavior: Exceeded maximum output retries (2)"
EXPECTED_ERROR = f"ScreeningError: {ERROR_TEXT}"


def _batch(n=10):
    return [{"id": i} for i in range(n)]


def _ids(papers):
    return [p["id"] for p in papers]


def _fake(fails):
    calls = []

    async def screen(papers):
        calls.append(_ids(papers))
        if fails(_ids(papers)):
            raise ScreeningError(ERROR_TEXT)
        return {"ok": _ids(papers)}

    return screen, calls


async def test_a_batch_that_succeeds_is_called_once():
    screen, calls = _fake(lambda ids: False)
    pieces, made = await screen_batch_with_split(screen, _batch())
    assert calls == [list(range(10))]
    assert made == 1
    assert len(pieces) == 1
    assert pieces[0].error is None
    assert _ids(pieces[0].papers) == list(range(10))


async def test_a_failed_batch_is_retried_in_halves():
    screen, calls = _fake(lambda ids: len(ids) == 10)
    pieces, made = await screen_batch_with_split(screen, _batch())
    assert calls == [list(range(10)), [0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
    assert made == 3
    assert [_ids(p.papers) for p in pieces] == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
    assert all(p.error is None and p.result is not None for p in pieces)


async def test_a_failing_half_is_retried_one_record_at_a_time():
    screen, calls = _fake(lambda ids: 3 in ids)
    pieces, made = await screen_batch_with_split(screen, _batch())
    assert calls == [
        list(range(10)),
        [0, 1, 2, 3, 4],
        [5, 6, 7, 8, 9],
        [0],
        [1],
        [2],
        [3],
        [4],
    ]
    assert made == 8
    assert [_ids(p.papers) for p in pieces] == [[0], [1], [2], [3], [4], [5, 6, 7, 8, 9]]
    assert [p.error for p in pieces] == [None, None, None, EXPECTED_ERROR, None, None]
    assert pieces[3].result is None


async def test_both_halves_failing_stops_splitting():
    screen, _calls = _fake(lambda ids: True)
    pieces, made = await screen_batch_with_split(screen, _batch())
    assert made == 3
    assert [_ids(p.papers) for p in pieces] == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
    assert [p.error for p in pieces] == [EXPECTED_ERROR, EXPECTED_ERROR]


async def test_a_single_record_batch_is_not_split():
    screen, calls = _fake(lambda ids: True)
    pieces, made = await screen_batch_with_split(screen, _batch(1))
    assert made == 1
    assert calls == [[0]]
    assert len(pieces) == 1
    assert pieces[0].error == EXPECTED_ERROR


@pytest.mark.parametrize(
    "fails",
    [
        lambda ids: True,
        lambda ids: len(ids) > 1,
        lambda ids: 3 in ids,
        lambda ids: 3 in ids or 7 in ids,
    ],
    ids=["always", "more_than_one", "contains_3", "contains_3_or_7"],
)
async def test_extra_calls_are_bounded(fails):
    screen, _calls = _fake(fails)
    batch = _batch(10)
    pieces, made = await screen_batch_with_split(screen, batch)
    assert made - 1 <= 2 + math.ceil(10 / 2)
    flat = [i for p in pieces for i in _ids(p.papers)]
    assert flat == list(range(10))
