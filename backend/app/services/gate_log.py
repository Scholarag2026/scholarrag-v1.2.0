"""Record builders for the drafting gate log.

The log records what the drafting gate saw and did, built after the calls it describes
from values that already exist, and sent to no model. The builders are pure: they return
JSON-serialisable dicts and lists and never mutate their inputs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

GATE_LOG_SCHEMA_VERSION: int = 1
LENGTH_TRIMMED_RULE: str = "length_trimmed"

_TRIGGER_STATUSES = {"unsupported", "needs_nuance", "error"}


def claim_rows(
    claims: Sequence[tuple[str, str, str, str]],
    verifications: Sequence[Any],
    *,
    reused: Sequence[bool] | None = None,
) -> list[dict]:
    """One row per claim; claims are (proposition, key, context, sentence)."""
    if len(claims) != len(verifications):
        raise ValueError("claims and verifications differ in length")
    if reused is not None and len(reused) != len(claims):
        raise ValueError("reused and claims differ in length")
    rows: list[dict] = []
    for i, ((proposition, key, _context, sentence), v) in enumerate(
        zip(claims, verifications, strict=True)
    ):
        row = {
            "sentence": sentence,
            "proposition": proposition,
            "key": key,
            "status": v.status,
        }
        if reused is not None:
            row["reused"] = bool(reused[i])
        rows.append(row)
    return rows


def revision_request_record(
    *,
    statuses: Iterable[str],
    coverage_flagged: bool,
    keep_verbatim: Sequence[str],
    failed: Sequence[Mapping[str, str]],
    coverage_issue: Iterable[str],
    uncited_finding: Sequence[str],
    unclassified: Sequence[str],
) -> dict:
    triggers = {s for s in statuses if s in _TRIGGER_STATUSES}
    if coverage_flagged:
        triggers.add("coverage_flag")
    return {
        "triggers": sorted(triggers),
        "keep_verbatim": list(keep_verbatim),
        "failed": [
            {"sentence": f["sentence"], "key": f["key"], "status": f["status"]} for f in failed
        ],
        "coverage_issue": sorted(coverage_issue),
        "uncited_finding": list(uncited_finding),
        "unclassified": list(unclassified),
    }


def revision_outcome_record(
    *, sentences: Sequence[str], claims: list[dict], link_map_failed: bool
) -> dict:
    return {
        "sentences": list(sentences),
        "claims": [dict(c) for c in claims],
        "link_map_failed": link_map_failed,
    }


def attempt_record(
    *,
    attempt: str,
    first_pass_sentences: Sequence[str],
    first_pass_claims: list[dict],
    link_map_failed: bool,
    revision: Mapping | None,
    finalize_fates: Sequence[Mapping],
) -> dict:
    if attempt not in ("first", "second"):
        raise ValueError(f"attempt must be first or second, got {attempt!r}")
    return {
        "attempt": attempt,
        "kept": False,
        "link_map_failed": link_map_failed,
        "first_pass": {
            "sentences": list(first_pass_sentences),
            "claims": [dict(c) for c in first_pass_claims],
        },
        "revision": dict(revision) if revision is not None else None,
        "finalize": {"sentences": [dict(f) for f in finalize_fates]},
    }


def apply_length_trim(fates: Sequence[Mapping], final_text: str) -> list[dict]:
    """Mark kept or changed sentences that no longer appear in the final text."""
    out: list[dict] = []
    for f in fates:
        entry = dict(f)
        if entry.get("fate") in ("kept", "changed") and entry.get("delivered") not in final_text:
            entry["fate"] = "removed"
            entry["rule"] = LENGTH_TRIMMED_RULE
            entry["delivered"] = None
        out.append(entry)
    return out


def build_gate_log(attempts: Sequence[Mapping], kept_attempt: str) -> dict:
    if not any(a.get("attempt") == kept_attempt for a in attempts):
        raise ValueError(f"no attempt named {kept_attempt!r}")
    built = []
    for a in attempts:
        entry = dict(a)
        entry["kept"] = a.get("attempt") == kept_attempt
        built.append(entry)
    return {
        "schema_version": GATE_LOG_SCHEMA_VERSION,
        "kept_attempt": kept_attempt,
        "attempts": built,
    }
