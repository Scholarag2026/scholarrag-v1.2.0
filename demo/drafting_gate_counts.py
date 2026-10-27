"""Drafting-gate counts from a stored demo run.

Reads the seven ``writing_result*.json`` files of one ``demo/output/<run>`` directory and
writes ``drafting_gate_counts.json`` beside them: removals by reason, delivered and cited
sentences, and the text of the removed sentences the run itself stores. Standard library
only. A run that did not log per-sentence gate outcomes gets the status ``aggregate_only``;
a run that did gets ``per_sentence_log`` (below).

    python demo/drafting_gate_counts.py [--run-dir DIR] [--out FILE] [--check]

``--check`` exits 1 when the file at ``--out`` differs from a fresh computation. When every
section result carries a ``gate_log``, the counts come from the logged per-sentence outcomes
and the status is ``per_sentence_log``; ``--require-gate-log`` then exits 2 unless that
holds, no section file is missing and every logged fate count agrees with its counter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

DEFAULT_RUN_DIR = Path(__file__).resolve().parent / "output" / "20261026-115827"
OUTPUT_NAME = "drafting_gate_counts.json"

SECTION_FILES: tuple[str, ...] = ("writing_result.json",) + tuple(
    f"writing_result_{i}.json" for i in range(2, 8)
)
TEXT_SOURCED_REASONS: tuple[str, ...] = (
    "uncited_finding",
    "coverage_incomplete",
    "meta_evaluation_uncited",
)
SUMMED_FIELDS: tuple[str, ...] = (
    "removed_total",
    "residue_excised",
    "needs_citation_markers_removed",
    "headings_removed",
    "words_first_generation",
    "words_final",
    "delivered_sentences",
    "delivered_cited_sentences",
    "claim_rows",
)
STATUS_NOTE = "this run did not log per-sentence gate outcomes; aggregate counters only"
AGGREGATE_STATUS = "aggregate_only"
REMOVED_PREFIX = "sentences_removed_"
GATE_LOG_SCHEMA_VERSION = 1
PER_SENTENCE_STATUS = "per_sentence_log"
PER_SENTENCE_NOTE = "per-sentence gate outcomes logged by the run"
PARITY_COUNTERS: dict[str, str] = {
    rule: f"{REMOVED_PREFIX}{rule}"
    for rule in (
        "unverified",
        "no_full_text",
        "uncited_finding",
        "dangling",
        "coverage_incomplete",
        "meta_evaluation_uncited",
        "verb_initial",
        "heading_shaped",
        "title_echo",
    )
}
PARITY_COUNTERS["heading"] = "headings_removed"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def count_delivered_sentences(content: str) -> int:
    lines = [ln.strip() for ln in (content or "").splitlines()]
    kept = [ln for ln in lines if ln and not ln.startswith("#")]
    parts = _SENTENCE_SPLIT.split(" ".join(kept))
    return sum(1 for p in parts if p.strip())


def _entries(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _sentence_of(entry) -> str:
    """Stored sentence text, with the em dash written as a spaced hyphen and whitespace collapsed.

    The generated file carries no em dash and its checks reject a colon followed by a
    line break (plan constraint); the run's own text has both in some entries, so they
    are normalised here and nowhere else.
    """
    raw = entry.get("sentence") if isinstance(entry, Mapping) else entry
    return " ".join(str(raw or "").replace("\u2014", " - ").split())


def stored_removed_texts(loop_stats: Mapping, uncited_sentences: list[Mapping]) -> dict:
    texts: list[dict] = []
    findings = [
        u
        for u in _entries(uncited_sentences)
        if isinstance(u, Mapping) and u.get("tag") == "finding"
    ]
    for u in findings:
        texts.append({"reason": "uncited_finding", "text": _sentence_of(u)})
    coverage = _entries(loop_stats.get("coverage_incomplete_reasons"))
    for entry in coverage:
        texts.append({"reason": "coverage_incomplete", "text": _sentence_of(entry)})
    meta = _entries(loop_stats.get("meta_evaluation_reasons"))
    for entry in meta:
        texts.append({"reason": "meta_evaluation_uncited", "text": _sentence_of(entry)})
    counter = int(loop_stats.get("sentences_removed_uncited_finding") or 0)
    return {
        "texts": texts,
        "stored_count": min(len(findings), counter) + len(coverage) + len(meta),
        "ambiguous": len(findings) > counter,
    }


def carried_verbatim(before: Sequence[str], after: Sequence[str]) -> tuple[int, int, int]:
    """Return ``(carried, not_carried, new)`` by multiset intersection of two sentence lists."""
    shared = sum((Counter(before) & Counter(after)).values())
    return shared, len(before) - shared, len(after) - shared


def _status_counts(claims: list) -> dict:
    counts = Counter(c.get("status") for c in claims if isinstance(c, Mapping) and c.get("status"))
    return dict(counts)


def _revision_counts(revision: Mapping, first_sentences: list) -> dict:
    sentences = [str(x) for x in _entries(revision.get("sentences"))]
    carried, not_carried, new = carried_verbatim([str(x) for x in first_sentences], sentences)
    claims = [c for c in _entries(revision.get("claims")) if isinstance(c, Mapping)]
    failed = {_sentence_of(f) for f in _entries(revision.get("failed")) if isinstance(f, Mapping)}
    reused = sum(1 for c in claims if c.get("reused"))
    return {
        "triggers": len(_entries(revision.get("triggers"))),
        "keep_verbatim": len(_entries(revision.get("keep_verbatim"))),
        "failed": len(failed),
        "coverage_issue": len(_entries(revision.get("coverage_issue"))),
        "uncited_finding": len(_entries(revision.get("uncited_finding"))),
        "unclassified": len(_entries(revision.get("unclassified"))),
        "first_pass_sentences_carried_verbatim": carried,
        "first_pass_sentences_not_carried": not_carried,
        "new_sentences": new,
        "claims": len(claims),
        "claims_reused": reused,
        "claims_reverified": len(claims) - reused,
        "claims_by_status": _status_counts(claims),
        "link_map_failed": bool(revision.get("link_map_failed")),
    }


def _fates(attempt: Mapping) -> list[Mapping]:
    fin = attempt.get("finalize") if isinstance(attempt, Mapping) else None
    entries = _entries((fin or {}).get("sentences"))
    return [e for e in entries if isinstance(e, Mapping)]


def gate_counts(result: Mapping) -> dict | None:
    """Per-sentence counts from the result's ``gate_log``, or None when it has none."""
    log = result.get("gate_log")
    if not isinstance(log, Mapping) or log.get("schema_version") != GATE_LOG_SCHEMA_VERSION:
        return None
    attempts = [a for a in _entries(log.get("attempts")) if isinstance(a, Mapping)]
    kept = next((a for a in attempts if a.get("kept")), None)
    if kept is None:
        return None
    stats = result.get("loop_stats") or {}
    first = kept.get("first_pass") or {}
    first_claims = [c for c in _entries(first.get("claims")) if isinstance(c, Mapping)]
    first_sentences = _entries(first.get("sentences"))
    revision = kept.get("revision")
    fates = _fates(kept)
    body = [e for e in fates if e.get("rule") != "heading"]
    removed = [e for e in fates if e.get("fate") == "removed"]
    removed_body = [e for e in removed if e.get("rule") != "heading"]
    by_rule = Counter(e.get("rule") for e in removed)
    mismatch = sorted(
        rule
        for rule, counter in PARITY_COUNTERS.items()
        if by_rule.get(rule, 0) != int(stats.get(counter) or 0)
    )
    fate_count = Counter(e.get("fate") for e in body)
    discarded = sum(
        sum(1 for e in _fates(a) if e.get("rule") != "heading")
        for a in attempts
        if not a.get("kept")
    )
    return {
        "attempts": len(attempts),
        "kept_attempt": log.get("kept_attempt"),
        "first_pass": {
            "sentences": len(first_sentences),
            "claims": len(first_claims),
            "claims_by_status": _status_counts(first_claims),
        },
        "revision": (
            _revision_counts(revision, first_sentences) if isinstance(revision, Mapping) else None
        ),
        "finalize": {
            "input_sentences": len(body),
            "kept": fate_count.get("kept", 0),
            "changed": fate_count.get("changed", 0),
            "merged": fate_count.get("merged", 0),
            "removed_by_rule": dict(sorted(by_rule.items())),
            "removed_total": len(removed_body),
            "headings_removed": by_rule.get("heading", 0),
            "identity_ok": len(body)
            == sum(fate_count.get(f, 0) for f in ("kept", "changed", "merged")) + len(removed_body),
        },
        "discarded_attempt_sentences": discarded,
        "fate_counter_mismatch": mismatch,
        "removed_texts": [{"rule": e.get("rule"), "text": _sentence_of(e)} for e in removed],
    }


def section_counts(result: Mapping) -> dict:
    stats = result.get("loop_stats") or {}
    length = (result.get("provenance") or {}).get("length") or {}
    by_reason = {
        key[len(REMOVED_PREFIX) :]: value
        for key, value in stats.items()
        if key.startswith(REMOVED_PREFIX)
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value
    }
    cited = {
        link.get("sentence")
        for link in _entries(result.get("citation_links"))
        if isinstance(link, Mapping)
    }
    content = result.get("content") or ""
    section = {
        "removed_by_reason": by_reason,
        "removed_total": sum(by_reason.values()),
        "residue_excised": stats.get("sentences_residue_excised") or 0,
        "needs_citation_markers_removed": stats.get("needs_citation_markers_removed") or 0,
        "headings_removed": stats.get("headings_removed") or 0,
        "loop_revised": bool(stats.get("loop_revised")),
        "first_pass_verified_rate": stats.get("first_pass_verified_rate"),
        "words_first_generation": length.get("words") or 0,
        "words_final": length.get("final_words") or 0,
        "delivered_sentences": count_delivered_sentences(content),
        "delivered_cited_sentences": len(cited),
        "claim_rows": len((result.get("claim_report") or {}).get("verifications") or []),
        "stored_removed": stored_removed_texts(stats, result.get("uncited_sentences") or []),
    }
    gate = gate_counts(result)
    if gate is not None:
        section["gate"] = gate
    return section


_REVISION_SUM_KEYS = (
    "keep_verbatim",
    "failed",
    "coverage_issue",
    "uncited_finding",
    "unclassified",
    "first_pass_sentences_carried_verbatim",
    "first_pass_sentences_not_carried",
    "new_sentences",
    "claims",
    "claims_reused",
    "claims_reverified",
)


def _add_dicts(target: dict, source: Mapping) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def gate_totals(gates: list[Mapping]) -> dict:
    first: dict = {"sentences": 0, "claims": 0, "claims_by_status": {}}
    revision: dict = {k: 0 for k in _REVISION_SUM_KEYS}
    revision["claims_by_status"] = {}
    fin: dict = {
        "input_sentences": 0,
        "kept": 0,
        "changed": 0,
        "merged": 0,
        "removed_by_rule": {},
        "removed_total": 0,
        "headings_removed": 0,
        "identity_ok": True,
    }
    discarded = 0
    mismatch: set[str] = set()
    for g in gates:
        for key in ("sentences", "claims"):
            first[key] += g["first_pass"][key]
        _add_dicts(first["claims_by_status"], g["first_pass"]["claims_by_status"])
        rev = g["revision"]
        if rev is not None:
            for key in _REVISION_SUM_KEYS:
                revision[key] += rev[key]
            _add_dicts(revision["claims_by_status"], rev["claims_by_status"])
        for key in (
            "input_sentences",
            "kept",
            "changed",
            "merged",
            "removed_total",
            "headings_removed",
        ):
            fin[key] += g["finalize"][key]
        fin["identity_ok"] = fin["identity_ok"] and g["finalize"]["identity_ok"]
        _add_dicts(fin["removed_by_rule"], g["finalize"]["removed_by_rule"])
        discarded += g["discarded_attempt_sentences"]
        mismatch.update(g["fate_counter_mismatch"])
    return {
        "first_pass": first,
        "revision": revision,
        "finalize": fin,
        "discarded_attempt_sentences": discarded,
        "fate_counter_mismatch": sorted(mismatch),
        "sections_revised_at_gate": sum(1 for g in gates if g["revision"] is not None),
    }


def build_counts(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    present = [name for name in SECTION_FILES if (run_dir / name).is_file()]
    missing = [name for name in SECTION_FILES if name not in present]
    sections = [
        section_counts(json.loads((run_dir / name).read_text(encoding="utf-8"))) for name in present
    ]
    totals: dict = {f: sum(s[f] for s in sections) for f in SUMMED_FIELDS}
    by_reason: dict[str, int] = {}
    for s in sections:
        for reason, n in s["removed_by_reason"].items():
            by_reason[reason] = by_reason.get(reason, 0) + n
    totals["removed_by_reason"] = by_reason
    totals["stored_removed_count"] = sum(s["stored_removed"]["stored_count"] for s in sections)
    totals["sections_revised"] = sum(1 for s in sections if s["loop_revised"])
    not_recorded = [
        "the first-generation text",
        "the revised draft before finalize",
        "per-sentence kept, rewritten or removed outcome",
    ]
    not_recorded += [
        f"text of the {n} {reason} removals"
        for reason, n in by_reason.items()
        if reason not in TEXT_SOURCED_REASONS
    ]
    counts: dict = {
        "status": AGGREGATE_STATUS,
        "status_note": STATUS_NOTE,
        "basis": f"demo run {run_dir.name}",
        "not_recorded": not_recorded,
        "sections": sections,
        "totals": totals,
    }
    if missing:
        counts["sections_missing"] = missing
    elif sections and all("gate" in s for s in sections):
        counts["status"] = PER_SENTENCE_STATUS
        counts["status_note"] = PER_SENTENCE_NOTE
        counts["not_recorded"] = [
            "which first-pass sentences the revision rewrote rather than dropped"
        ]
        totals["gate"] = gate_totals([s["gate"] for s in sections])
    return counts


def gate_log_problem(counts: Mapping) -> str | None:
    """Why the counts do not meet ``--require-gate-log``, or None when they do."""
    if counts.get("sections_missing"):
        return "section files missing: " + ", ".join(counts["sections_missing"])
    if counts.get("status") != PER_SENTENCE_STATUS:
        return "not every section result carries a gate_log"
    bad = [
        str(i + 1) for i, s in enumerate(counts["sections"]) if s["gate"]["fate_counter_mismatch"]
    ]
    if bad:
        return "fate counts disagree with loop_stats counters in sections " + ", ".join(bad)
    broken = [
        str(i + 1)
        for i, s in enumerate(counts["sections"])
        if not s["gate"]["finalize"]["identity_ok"]
    ]
    if broken:
        return (
            "sentence identity input != kept + changed + merged + removed fails in sections "
            + ", ".join(broken)
        )
    return None


def render(counts: Mapping) -> str:
    return json.dumps(counts, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-gate-log", action="store_true")
    args = parser.parse_args(argv)
    out = args.out or (args.run_dir / OUTPUT_NAME)
    counts = build_counts(args.run_dir)
    text = render(counts)
    if args.check:
        current = None
        if out.is_file():
            current = out.read_bytes().decode("utf-8").replace("\r\n", "\n")
        if current != text:
            print(f"{out.name} is out of date; rerun without --check", file=sys.stderr)
            return 1
        print(f"{out.name} is current")
    else:
        out.write_bytes(text.encode("utf-8"))
        print(f"wrote {out.name}")
    if args.require_gate_log:
        problem = gate_log_problem(counts)
        if problem:
            print(f"gate log required: {problem}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
