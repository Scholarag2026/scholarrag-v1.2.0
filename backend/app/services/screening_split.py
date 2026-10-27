"""Retry a failed screening batch in smaller calls before any record is marked unscreened.

A screening call whose structured output fails marks every record of its batch unscreened.
The failure is usually tied to one awkward record or one unlucky sample rather than to the
whole batch, so ``screen_batch_with_split`` retries a failed batch in halves, and a failing
half one record at a time. A normal batch makes exactly one call and is returned unchanged.

The extra calls are bounded: a batch of ``n`` records costs at most ``2 + ceil(n / 2)`` calls
beyond the first (the two halves, then the records of one failing half). When both halves
fail, splitting stops: two failures in a row point to the call itself (for example a
provider outage), not to one record. The records of that batch are then not tried alone and
stay unscreened with the error of their half. A record that fails alone keeps the
unscreened outcome and its own error.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.agents.relevance_screener_agent import ScreeningBatchResult

logger = logging.getLogger(__name__)


@dataclass
class ScreenedPiece:
    """One slice of the original batch and what became of it: ``result`` for a slice
    that was screened, ``error`` (``"<ExceptionType>: <message>"``) for one that was not."""

    papers: list[dict[str, Any]]
    result: ScreeningBatchResult | None
    error: str | None


async def screen_batch_with_split(
    screen: Callable[[list[dict[str, Any]]], Awaitable[ScreeningBatchResult]],
    batch: list[dict[str, Any]],
) -> tuple[list[ScreenedPiece], int]:
    """Screen *batch* with *screen*, splitting on failure.

    Returns the pieces in input order (every record in exactly one piece) and the number
    of ``screen`` calls made."""
    calls = 0

    async def attempt(papers: list[dict[str, Any]]) -> ScreenedPiece:
        nonlocal calls
        calls += 1
        try:
            return ScreenedPiece(papers, await screen(papers), None)
        except Exception as exc:
            return ScreenedPiece(papers, None, f"{type(exc).__name__}: {exc}")

    whole = await attempt(batch)
    if whole.error is None or len(batch) == 1:
        return [whole], calls

    mid = (len(batch) + 1) // 2
    first = await attempt(batch[:mid])
    second = await attempt(batch[mid:])
    pieces: list[ScreenedPiece] = []
    if first.error is not None and second.error is not None:
        pieces = [first, second]
    else:
        for half in (first, second):
            if half.error is not None and len(half.papers) > 1:
                pieces.extend([await attempt([paper]) for paper in half.papers])
            else:
                pieces.append(half)

    recovered = sum(len(p.papers) for p in pieces if p.error is None)
    logger.info(
        "Screening batch of %d failed once; split retry recovered %d record(s), %d still failing",
        len(batch),
        recovered,
        len(batch) - recovered,
    )
    return pieces, calls
