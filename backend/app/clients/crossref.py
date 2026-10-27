# backend/app/clients/crossref.py
"""CrossRef client — DOI verification.

Uses one process-wide pooled httpx client (a fresh ``AsyncClient`` per DOI meant a
fresh TLS handshake for every paper in a verification run) and the shared
transient-only retry policy.
"""

from __future__ import annotations

import logging

import httpx

from app.clients.http_retry import request_with_retry
from app.config import settings

logger = logging.getLogger(__name__)

CROSSREF_BASE_URL = "https://api.crossref.org"

_shared_http_client: httpx.AsyncClient | None = None


def _user_agent() -> str:
    if settings.openalex_email:
        return f"DeepResearch/2.0 (mailto:{settings.openalex_email})"
    return "DeepResearch/2.0"


def get_shared_http_client() -> httpx.AsyncClient:
    """Return the process-wide pooled CrossRef client."""
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        _shared_http_client = httpx.AsyncClient(
            timeout=settings.crossref_timeout,
            headers={"User-Agent": _user_agent()},
        )
    return _shared_http_client


async def close_shared_http_client() -> None:
    """Close the shared client. Tests and graceful shutdown only."""
    global _shared_http_client
    if _shared_http_client is not None and not _shared_http_client.is_closed:
        await _shared_http_client.aclose()
    _shared_http_client = None


class CrossrefLookupError(Exception):
    """A Crossref lookup could not be completed (not a 404).

    The message reads ``"<ExceptionClass or HTTP status>: <detail>"``.
    """


class CrossRefClient:
    """Client for the CrossRef API — used for DOI verification."""

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._client = http_client
        self.headers = {"User-Agent": _user_agent()}

    def _get_client(self) -> httpx.AsyncClient:
        return self._client if self._client is not None else get_shared_http_client()

    async def verify_doi(self, doi: str) -> dict | None:
        """Look a DOI up in CrossRef.

        Returns the metadata dict when the DOI resolves, ``None`` only when
        CrossRef answers 404 (the DOI does not exist), and raises
        ``CrossrefLookupError`` for any other HTTP status (after retries) and for
        any transport error, so a failed lookup is never read as a missing DOI.
        """
        client = self._get_client()

        async def _call() -> httpx.Response:
            resp = await client.get(
                f"{CROSSREF_BASE_URL}/works/{doi}", headers=self.headers
            )
            resp.raise_for_status()
            return resp

        try:
            response = await request_with_retry(_call)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                logger.info("DOI not found in CrossRef: %s", doi)
                return None
            logger.warning("CrossRef API error for %s: %s", doi, status)
            raise CrossrefLookupError(f"HTTP {status}: {exc}") from exc
        except Exception as exc:
            logger.warning("CrossRef verification failed for %s: %s", doi, exc)
            raise CrossrefLookupError(f"{type(exc).__name__}: {exc}") from exc

        message = response.json().get("message", {})

        title_list = message.get("title", [])
        title = title_list[0] if title_list else None

        authors = []
        for author in message.get("author", []):
            name_parts = []
            if author.get("given"):
                name_parts.append(author["given"])
            if author.get("family"):
                name_parts.append(author["family"])
            if name_parts:
                authors.append({"name": " ".join(name_parts)})

        date_parts = message.get("published-print", {}).get("date-parts", [[]])
        if not date_parts or not date_parts[0]:
            date_parts = message.get("published-online", {}).get("date-parts", [[]])
        year = date_parts[0][0] if date_parts and date_parts[0] else None

        container = message.get("container-title", [])
        journal_name = container[0] if container else None

        issn_list = message.get("ISSN", [])
        issn = issn_list[0] if issn_list else None

        return {
            "doi": message.get("DOI", doi),
            "title": title,
            "authors": authors,
            "year": year,
            "journal_name": journal_name,
            "issn": issn,
            "citation_count": message.get("is-referenced-by-count"),
        }
