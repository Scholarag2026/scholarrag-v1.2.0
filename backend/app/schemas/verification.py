# backend/app/schemas/verification.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


RecordStatus = Literal["record_verified", "metadata_mismatch", "doi_not_found", "no_doi"]


class VerifyReferencesRequest(BaseModel):
    paper_ids: list[UUID] = Field(
        default_factory=list,
        description="Specific paper IDs to verify. Empty = verify all.",
    )


class VerificationCheck(BaseModel):
    """One record check or one indicator for a paper.

    Record checks (``doi_exists``, ``metadata_match``) carry their own ``pass`` /
    ``fail`` / ``warning`` / ``skipped`` vocabulary, distinct from the record
    statuses. Indicators (``wos_indexed``, ``recency``,
    ``citation_count``) carry the neutral ``info`` / ``note`` / ``skipped`` and never
    influence a record's ``overall_status``.
    """

    check_type: str
    status: str
    message: str
    details: dict | None = None


class PaperVerificationResult(BaseModel):
    paper_id: UUID
    doi: str | None
    title: str
    # Derived from ``checks`` only. ``None`` means the Crossref lookup failed; that is
    # not a record status.
    overall_status: RecordStatus | None
    checks: list[VerificationCheck]  # doi_exists, metadata_match
    indicators: list[VerificationCheck] = Field(
        default_factory=list
    )  # wos_indexed, recency, citation_count
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
