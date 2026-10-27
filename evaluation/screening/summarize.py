"""Summarise the screening evaluation (E1) into manuscript-ready tables.

Interpreter: ``evaluation/.venv/Scripts/python`` or the system ``python`` (stdlib only).

Reads everything under ``--results-dir`` (default ``results/v3``, the results of record;
and ``<dataset>.fetch.json`` under ``--data-dir``)::

    <dataset>_run<A|B>.jsonl (+ .meta.json)   from run_screening.py
    <dataset>_baselines.json                  from baselines.py (optional)
    <dataset>_wos_gate.json                   from wos_gate_effect.py (optional)
    data/<dataset>.fetch.json                 from fetch_synergy.py (missing-abstract share;
                                              falls back to the rows' ``has_abstract``)

and writes, under that same ``--results-dir``::

    summary.json              all numbers (tables E1-a..i + ``figure4`` rows)
    summary.md                markdown tables E1-a performance on each protocol's gold label,
                              E1-b secondary, E1-c provenance/cost/latency, E1-d WoS gate,
                              E1-e final-inclusion basis, E1-f title-and-abstract basis, and
                              E1-g reading queue by cause, E1-h TF-IDF records read and E1-i
                              ASReview LAB simulation (the last three are added by later
                              steps of the round and are absent until their inputs exist)
    figure4_screening.json    one row per (dataset, series) for manuscript Fig. 4
    <dataset>_false_negatives.md   every record the source review included that the
                                   screener excluded outright (status EXCLUDE), with its
                                   reason, abstract availability and the other run's
                                   status on the same record; title-and-abstract positives
                                   that were not final inclusions are listed separately

No empty categorisation file is written. A ``<dataset>_fn_categories.csv`` (columns
dataset, run, record_id, title, reason, category, notes) is read from ``--results-dir``
when one is committed there, and its category counts are then reported in ``summary.md``;
a results directory whose false negatives carry no coded category simply has no such file
and no category section.

``results/v3/`` is the published results directory.

False-negative categories: when a results directory commits coded categories of its own, the
summary prints a short paragraph saying where the codes were read from and that the
categorisation package is not part of the release, so no agreement figure is printed.
``results/v3/`` commits no coded categories.

Basis rule: a dataset in ``corpus_basis.DEDUP_DATASETS`` (``van_de_Schoot_2017``,
``Nagtegaal_2019``) is summarised on its deduplicated records, so every metric, agreement
and figure row counts the rows that remain after the duplicate rows named by its manifest
(``dedup_basis/<dataset>.json``) are dropped; the kept original's row is used, never the
duplicate's. The entry's ``basis`` block names the basis and ``submitted_basis_reference``
holds the final-inclusion and title-and-abstract metrics on the undeduplicated rows, with
the reason the two differ; ``summary.md`` prints the van_de_Schoot_2017 as-exported figures
once, under Table E1-e. Table E1-f reports retention of the title-and-abstract positives
(``ta_basis``) split into final and non-final inclusions, and says so when an export has no
title-and-abstract label.

Metrics are computed on the protocol's ``label`` (see ``protocols/README.md``); recall against
the review's final inclusions (``label_included``) is reported as a secondary number when the
protocol label is the title/abstract decision. Records the screener could not process
(``predicted = null``) are excluded from the confusion counts and reported separately.
Rows production padded with INCLUDE because the model returned no decision
(``padded_include``) are counted (``n_padded_include``) and the metrics are given twice: as
returned, and with those rows treated as unscreened (``metrics_padded_as_unscreened``; the
figure rows carry the series ``"LLM run X (padded as unscreened)"`` whenever such rows exist).
The broader ``padded_decision`` column (true for a padded row regardless of the status it
landed on -- the shipped backend currently pads to NEEDS_REVIEW, not INCLUDE) is counted as
``n_padded_decisions`` inside ``metrics_primary``, so a
padded non-decision that inflates ``recall_screened_in``/``needs_review_rate`` is visible and
subtractable there even though those two figures are not themselves adjusted for it. The same
count and a strict-reading metrics variant are also available
alongside the headline ``metrics`` block: ``n_padded_decisions`` and
``metrics_padded_decision_as_unscreened`` (every ``padded_decision`` row scored as unscreened,
the ``padded_decision`` superset of ``metrics_padded_as_unscreened``'s narrower
``padded_include``-only rewrite), with a matching ``"LLM run X (padded decisions as
unscreened)"`` figure row whenever such rows exist.
Cohen's kappa is undefined when both runs are constant and identical; the tables print ``-``
and a footnote instead of a number (``agreement_AB.kappa_undefined``).
The WoS-gate table (E1-d) reports the gate's recall ceiling as an interval whenever the
hydration is incomplete, because a record with no ISSN has an unknown venue: the *lower
bound* counts every unresolved human-included record as outside WoS (``n_in_wos_any /
n_included``) and the *upper bound* counts every unresolved record as inside WoS
(``(n_in_wos_any + n_unresolved) / n_included``); a fully resolved set prints one value.
``n_in_wos_any / n_with_issn`` (the share of *resolved* records only) is reported alongside
as ``share_resolved_only``, a point estimate that assumes the unresolved records are in WoS
at the same rate as the resolved ones -- it is not a bound. All three are in ``summary.json``
(``wos_gate_table.share_lower_bound`` / ``share_resolved_only`` / ``share_upper_bound``) and
in ``figure4_screening.json`` (series ``"WoS gate"``). The gate files are written by
``wos_gate_effect.py`` on the same basis as every other metric, so a deduplicated dataset's gate
row counts its deduplicated records. The
all-records share is suppressed (``-``) when fewer than 90 % of all records carry an ISSN.
The hydration mode comes from ``<dataset>.fetch.json``.
Cost figures come from the run meta (``total_cost``: list price, peak/off-peak tier by call
time, cache-miss assumed = an upper bound, see ``cost_basis``).

Tests load this module through ``conftest.load_script_module("screening", "summarize")``
because ``claims/summarize.py`` shares the module name.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import corpus_basis  # noqa: E402

from common import (  # noqa: E402
    ProtocolError,
    binary_metrics,
    cohens_kappa,
    confusion_counts,
    fmt,
    inclusion_rate,
    kappa_undefined,
    load_protocol,
    markdown_table,
    percent_agreement,
    read_json,
    read_jsonl,
    recall,
    resolve_path_args,
    wilson_interval,
    write_json,
    wss_at_achieved_recall,
)

DATA_DIR = HERE / "data"
RESULTS_DIR = HERE / "results" / "v3"
PROTOCOLS_DIR = HERE / "protocols"

MIN_RESOLVED_SHARE = 0.9  # below this, a WoS-gate share over the whole set is not printed
RUN_FILE_RE = re.compile(r"^(?P<dataset>.+)_run(?P<run>[AB])\.jsonl$")
META_KEYS = (
    "started",
    "finished",
    "dry_run",
    "model_configured",
    "model_reported",
    "system_fingerprints",
    "temperature",
    "prompt_version",
    "prompt_version_flag",
    "abstract_cap",
    "batch_size",
    "concurrency",
    "limit",
    "n_records",
    "n_batches",
    "failures",
    "n_unscreened_records",
    "n_padded_include",
    "n_padded_decisions",
    "n_missing_title",
    "record_order_seed",
    "retried_failed",
    "price",
    "total_input_tokens",
    "total_output_tokens",
    "cost_basis",
    "total_cost",
    "total_cost_flat",
    "latency_s",
    "protocol_sha",
    "full_text_criteria",
)
FIGURE4_METRICS = (
    "n",
    "prevalence",
    "recall",
    "precision",
    "f1",
    "specificity",
    "inclusion_rate",
    "wss_at_achieved_recall",
    "wss_at_95",
)


# --------------------------------------------------------------------------------------
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------------------


def _portable_dir(path: Path) -> str:
    """The results directory as a POSIX path relative to this script, so the committed
    summary carries no local path. A directory outside the tree is kept as given."""
    try:
        return Path(path).resolve().relative_to(HERE).as_posix()
    except ValueError:
        return str(path)


def discover_runs(results_dir: Path) -> dict[str, dict[str, Path]]:
    """``{dataset: {"A": path, "B": path}}`` for every run file present."""
    found: dict[str, dict[str, Path]] = {}
    for path in sorted(results_dir.glob("*_run?.jsonl")):
        m = RUN_FILE_RE.match(path.name)
        if m:
            found.setdefault(m["dataset"], {})[m["run"]] = path
    return found


def _labelled(
    rows: Sequence[Mapping[str, Any]], label_key: str
) -> tuple[list[int], list[int | None]]:
    labels: list[int] = []
    preds: list[int | None] = []
    for r in rows:
        if r.get(label_key) is None:
            continue
        labels.append(int(r[label_key]))
        p = r.get("predicted")
        preds.append(None if p is None else int(p))
    return labels, preds


def _share_missing_abstract(rows: Sequence[Mapping[str, Any]]) -> float | None:
    known = [r for r in rows if r.get("has_abstract") is not None]
    if not known:
        return None
    return sum(1 for r in known if not r["has_abstract"]) / len(known)


def _without_padded(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copy of ``rows`` with production's padded INCLUDEs turned into unscreened rows."""
    return [dict(r, predicted=None) if r.get("padded_include") else dict(r) for r in rows]


def _without_padded_decision(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copy of ``rows`` with every row still flagged ``padded_decision`` turned into an
    unscreened row -- the strict reading of E1-a: a record the
    model never returned a decision for at all, whatever status the padding landed on, is not
    scored as a screener decision. A superset of :func:`_without_padded`, which only rewrites
    the narrower ``padded_include`` flag: ``rows_for_batch`` sets ``padded_include`` only when
    ``reason == NO_DECISION_REASON``, which also sets ``padded_decision``, so every
    ``padded_include`` row is a ``padded_decision`` row -- ``padded_include`` is a subset of
    ``padded_decision``, not a disjoint set. In production ``padded_include`` is empty
    (padding lands on NEEDS_REVIEW, never on a predicted=1 row), so this function's rewrite
    set is the only one of the two that ever removes any rows there."""
    return [dict(r, predicted=None) if r.get("padded_decision") else dict(r) for r in rows]


def run_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Headline metrics on ``label`` plus secondary recall against ``label_included``."""
    labels, preds = _labelled(rows, "label")
    metrics = binary_metrics(confusion_counts(labels, preds))
    metrics["n_rows"] = len(rows)
    metrics["n_unscreened"] = sum(1 for r in rows if r.get("predicted") is None)
    metrics["n_padded_include"] = sum(1 for r in rows if r.get("padded_include"))
    metrics["n_padded_decisions"] = sum(1 for r in rows if r.get("padded_decision"))
    metrics["n_missing_title"] = sum(1 for r in rows if r.get("has_title") is False)
    metrics["n_missing_label"] = len(rows) - len(labels)
    labels_final, preds_final = _labelled(rows, "label_included")
    metrics["final_inclusion_recall"] = (
        recall(confusion_counts(labels_final, preds_final)) if labels_final else None
    )
    metrics["n_final_inclusions"] = sum(labels_final)
    metrics["share_missing_abstract_screened"] = _share_missing_abstract(rows)
    return metrics


def _agreement_value(row: Mapping[str, Any], key: str) -> Any:
    """The column ``agreement()`` compares for one row and ``key``.

    ``key="predicted"`` (the default, and the *only* path the six committed v1 runs' already
    -published ``agreement_AB`` ever took) returns the binary ``predicted`` unchanged -- byte
    -identical to the original function. ``key="status"`` reads
    the new three-way ``status`` column and falls back to ``predicted`` for a row that carries
    none (the six committed v1 rows), so ``agreement_AB_status`` is always computable and
    equals ``agreement_AB`` exactly wherever no row carries a ``status``.
    """
    if key == "predicted":
        return row.get("predicted")
    value = row.get(key)
    return value if value is not None else row.get("predicted")


def agreement(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    *,
    key: str = "predicted",
) -> dict[str, Any]:
    """Percent agreement and Cohen's kappa between runs A and B on shared, screened records."""
    by_id_b = {r["record_id"]: _agreement_value(r, key) for r in rows_b}
    a_vals: list[Any] = []
    b_vals: list[Any] = []
    for r in rows_a:
        if r["record_id"] in by_id_b:
            a_vals.append(_agreement_value(r, key))
            b_vals.append(by_id_b[r["record_id"]])
    pairs = [(a, b) for a, b in zip(a_vals, b_vals, strict=True) if a is not None and b is not None]
    return {
        "n_shared": len(a_vals),
        "n_compared": len(pairs),
        "n_disagreements": sum(1 for a, b in pairs if a != b),
        "percent_agreement": percent_agreement(a_vals, b_vals),
        "kappa": cohens_kappa(a_vals, b_vals),
        "kappa_undefined": kappa_undefined(a_vals, b_vals),
    }


def _status_predictions(rows: Sequence[Mapping[str, Any]], positive: set[str]) -> list[int | None]:
    """1 when a row's ``status`` (falling back to the binary ``predicted`` when a row carries
    no ``status``, e.g. the six committed v1 runs) names one of ``positive``, else 0."""
    preds: list[int | None] = []
    for r in rows:
        status = r.get("status")
        if status is not None:
            preds.append(1 if status in positive else 0)
            continue
        p = r.get("predicted")
        preds.append(None if p is None else int(bool(p)))
    return preds


def _labelled_with(
    rows: Sequence[Mapping[str, Any]], label_key: str, preds: Sequence[int | None]
) -> tuple[list[int], list[int | None]]:
    """Zip ``rows``' ``label_key`` values with a caller-supplied parallel ``preds`` column,
    dropping rows with no label (mirrors :func:`_labelled` for a non-``predicted`` column)."""
    labels: list[int] = []
    out: list[int | None] = []
    for r, p in zip(rows, preds, strict=True):
        if r.get(label_key) is None:
            continue
        labels.append(int(r[label_key]))
        out.append(p)
    return labels, out


def metrics_primary(
    rows: Sequence[Mapping[str, Any]],
    label_field: str = "label_included",
) -> dict[str, Any] | None:
    """The gate/acceptance metrics block (D3 and D3b defined below),
    scored on ``label_field`` (``primary_label``, defaulting to
    ``"label_included"``, or ``label_abstract_screening`` for :func:`metrics_sensitivity`...
    callers name the field).

    ``recall_include_only`` treats only ``status == "INCLUDE"`` (or, for a row with no
    ``status`` column at all -- the six committed v1 runs -- the existing binary
    ``predicted``) as a positive screening decision; ``recall_screened_in`` additionally
    counts ``NEEDS_REVIEW``. For a run with no ``status`` column the two are identical (v1
    has no NEEDS_REVIEW route), which is the intended behaviour when this block is computed
    for the six committed v1 runs: ``recall_include_only`` there equals the existing
    ``final_inclusion_recall``. Wilson intervals (``common.wilson_interval``) are computed on
    each recall's own true positives over the shared positive count. Returns ``None`` when no
    row carries ``label_field`` (mirrors the empty-list handling of :func:`run_metrics`).

    ``n_padded_decisions`` counts rows the model
    never returned a decision for at all (``padded_decision``, regardless of the status the
    padding landed on). These rows are *not* excluded from ``recall_screened_in`` or
    ``needs_review_rate`` above -- they are real production output and a NEEDS_REVIEW padded
    row is, today, indistinguishable in kind from a genuine one once written -- but the count is
    surfaced here so a non-decision inflating either figure is visible and can be subtracted by
    a caller that wants the stricter, padding-excluded reading.

    ``needs_review_by_reason`` (NEEDS_REVIEW counts keyed by the row's own ``guard_reason``
    when non-empty, ``"no_abstract"`` for a guard-silent row with no abstract, or
    ``"undecidable"`` for any other guard-silent row -- a genuine model NEEDS_REVIEW the
    guard did not touch) and ``needs_review_by_criterion`` (NEEDS_REVIEW counts keyed by
    ``criterion`` for the rows that carry one) read only each row's own columns. The
    guard attributes ``"full_text_criterion"`` (a verbatim quote of contrary evidence) on a
    NEEDS_REVIEW naming a full-text exclusion criterion, and ``"unquoted_criterion"`` (no
    verbatim quote) on that same NEEDS_REVIEW or on any other criterion-naming NEEDS_REVIEW
    without one -- an ordinary abstract-stage id or a full-text inclusion id included (the
    quote test is not narrowed to full-text exclusion ids, so no criterion-naming
    NEEDS_REVIEW with no quote falls silently into "undecidable") -- whether or not it demoted
    anything; a compliant model routing leaves ``guard_reason`` empty, so this module needs neither the protocol's own
    stage marks
    nor a run meta's frozen copy of them to answer that question; ``guard_reason`` alone is
    authoritative. ``n_needs_review_full_text`` is
    ``needs_review_by_reason.get("full_text_criterion", 0)``. The guard can now
    also attribute ``guard_reason == "no_abstract"`` itself (an EXCLUDE on a record with no
    abstract, demoted unconditionally); this lands in exactly the same bucket as the
    guard-silent fallback above, since both describe the same thing -- a record with no
    abstract that cannot be decided -- and this function needs no change to merge them, since
    it already reads ``guard_reason`` first and falls back to the abstract check only when
    that column is empty.

    ``needs_review_rate_abstract_bearing``, the needs-review rate over *all* abstract-bearing
    records, no row exempted, so
    there is nothing to leave out of the denominator; a full-text exclusion criterion
    can ground a NEEDS_REVIEW today only behind explicit contrary evidence, the screener
    working as designed.

    D3b (superseding S8's ``full_text_routed_rate``/``full_text_routed_by_criterion``, which
    measured NEEDS_REVIEW routing, a population D3 no longer excludes): ``to_confirm_rate``,
    the share of INCLUDE decisions carrying a non-empty ``to_confirm`` note, and
    ``to_confirm_by_criterion``, the same population's ids counted individually (one INCLUDE
    naming two ids contributes to both). No threshold on either.
    """
    include_preds = _status_predictions(rows, {"INCLUDE"})
    screened_preds = _status_predictions(rows, {"INCLUDE", "NEEDS_REVIEW"})
    labels, inc_preds = _labelled_with(rows, label_field, include_preds)
    if not labels:
        return None
    _, scr_preds = _labelled_with(rows, label_field, screened_preds)
    counts_include = confusion_counts(labels, inc_preds)
    counts_screened = confusion_counts(labels, scr_preds)
    m = binary_metrics(counts_include)
    n_pos = counts_include.n_positive
    n_needs_review = sum(1 for r in rows if r.get("status") == "NEEDS_REVIEW")
    n_abstract_bearing = sum(1 for r in rows if r.get("has_abstract"))
    needs_review_by_reason: dict[str, int] = {}
    needs_review_by_criterion: dict[str, int] = {}
    n_needs_review_abstract_bearing = 0
    for r in rows:
        if r.get("status") != "NEEDS_REVIEW":
            continue
        criterion = r.get("criterion")
        if criterion:
            needs_review_by_criterion[criterion] = needs_review_by_criterion.get(criterion, 0) + 1
        guard_reason = r.get("guard_reason") or ""
        reason = guard_reason or ("no_abstract" if not r.get("has_abstract") else "undecidable")
        needs_review_by_reason[reason] = needs_review_by_reason.get(reason, 0) + 1
        if r.get("has_abstract"):
            n_needs_review_abstract_bearing += 1
    n_needs_review_full_text = needs_review_by_reason.get("full_text_criterion", 0)
    # Records the screener excluded outright, over the screened records (unscreened rows leave
    # both counts). Reading saved is this share minus (1 - R); it is printed in its own column.
    n_screened_rows = sum(1 for p in screened_preds if p is not None)
    n_excluded_rows = sum(1 for p in screened_preds if p == 0)
    excluded_share = (n_excluded_rows / n_screened_rows) if n_screened_rows else None
    # The reading queue by cause: per needs_review_by_reason key, the records, their share of
    # the screened corpus and how many are final inclusions / title-and-abstract positives
    # (None when no queued row of that cause carries a title-and-abstract label at all).
    queue_by_reason: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("status") != "NEEDS_REVIEW":
            continue
        reason = r.get("guard_reason") or (
            "no_abstract" if not r.get("has_abstract") else "undecidable"
        )
        q = queue_by_reason.setdefault(
            reason, {"n": 0, "share_of_corpus": None, "n_final_pos": 0, "n_ta_pos": None}
        )
        q["n"] += 1
        if r.get("label_included") is not None and int(r["label_included"]) == 1:
            q["n_final_pos"] += 1
        if r.get("label_abstract_screening") is not None:
            ta_pos = int(r["label_abstract_screening"]) == 1
            q["n_ta_pos"] = (q["n_ta_pos"] or 0) + (1 if ta_pos else 0)
    for q in queue_by_reason.values():
        q["share_of_corpus"] = (q["n"] / n_screened_rows) if n_screened_rows else None
    n_include = sum(1 for r in rows if r.get("status") == "INCLUDE")
    # The queue-precision half of the shipped five-column report -- the share of
    # NEEDS_REVIEW rows (carrying label_field) whose gold label is a positive, i.e. how
    # often a record queued for further reading is a genuine final inclusion.
    needs_review_labelled = [
        r for r in rows if r.get("status") == "NEEDS_REVIEW" and r.get(label_field) is not None
    ]
    queue_precision_n = len(needs_review_labelled)
    queue_precision = (
        sum(1 for r in needs_review_labelled if int(r[label_field]) == 1) / queue_precision_n
        if queue_precision_n else None
    )
    to_confirm_by_criterion: dict[str, int] = {}
    n_include_with_to_confirm = 0
    for r in rows:
        if r.get("status") != "INCLUDE":
            continue
        ids = r.get("to_confirm") or []
        if not ids:
            continue
        n_include_with_to_confirm += 1
        for cid in ids:
            to_confirm_by_criterion[cid] = to_confirm_by_criterion.get(cid, 0) + 1
    return {
        "label_field": label_field,
        "n": m["n"],
        "n_positive": n_pos,
        "recall_include_only": m["recall"],
        "recall_include_only_wilson": (
            wilson_interval(counts_include.tp, n_pos) if n_pos else (None, None)
        ),
        "recall_screened_in": recall(counts_screened),
        "recall_screened_in_wilson": (
            wilson_interval(counts_screened.tp, n_pos) if n_pos else (None, None)
        ),
        "precision": m["precision"],
        "specificity": m["specificity"],
        "inclusion_rate": m["inclusion_rate"],
        "screened_in_rate": inclusion_rate(counts_screened),
        "needs_review_rate": (n_needs_review / len(rows)) if rows else None,
        "needs_review_by_reason": needs_review_by_reason,
        "needs_review_by_criterion": needs_review_by_criterion,
        "excluded_share": excluded_share,
        "queue_by_reason": queue_by_reason,
        "n_needs_review_full_text": n_needs_review_full_text,
        "needs_review_rate_abstract_bearing": (
            (n_needs_review_abstract_bearing / n_abstract_bearing)
            if n_abstract_bearing else None
        ),
        "to_confirm_rate": (n_include_with_to_confirm / n_include) if n_include else None,
        "to_confirm_by_criterion": to_confirm_by_criterion,
        "n_padded_decisions": sum(1 for r in rows if r.get("padded_decision")),
        "wss_at_achieved_recall": m["wss_at_achieved_recall"],
        "wss_at_95": m["wss_at_95"],
        # The shipped five-column report (retained recall and its Wilson interval,
        # screened-in share and needs_review_rate above already covered three of the five;
        # these three close it). "auto_inclusion_precision" is m["precision"] under its
        # report name, printed by a caller as "none, n = 0" when auto_inclusion_n is 0 (no
        # INCLUDE decision at all, the structural consequence of routing every unconfirmed
        # full-text inclusion criterion to NEEDS_REVIEW).
        "auto_inclusion_precision": m["precision"],
        "auto_inclusion_n": counts_include.tp + counts_include.fp,
        # Work saved over sampling evaluated at the *retained* recall (INCLUDE or
        # NEEDS_REVIEW), not the INCLUDE-only recall wss_at_achieved_recall above already
        # reports -- the reading a screener recommending "auto-include or queue for a human"
        # actually saves, since NEEDS_REVIEW rows still get read.
        "wss_at_achieved_retained_recall": wss_at_achieved_recall(counts_screened),
        "queue_precision": queue_precision,
        "queue_precision_n": queue_precision_n,
    }


def metrics_sensitivity(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """:func:`metrics_primary` scored on ``label_abstract_screening`` where the export
    carries it; ``None`` when no row does."""
    return metrics_primary(rows, "label_abstract_screening")


def ta_basis_split(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The screener's retention of the title-and-abstract positives, split by whether the
    review also kept the record at full text.

    A title-and-abstract positive is a row with ``label_abstract_screening == 1`` that the
    screener scored (``predicted is not None``); it is *kept* when screened in (INCLUDE or
    NEEDS_REVIEW, or ``predicted == 1`` for a row with no ``status``). ``final`` is the part
    that is also a final inclusion (``label_included == 1``), ``non_final`` the rest.
    ``wss_at_achieved_retained_recall`` is :func:`metrics_sensitivity`'s own figure. Returns
    ``None`` when no row carries ``label_abstract_screening`` (Smid_2020's export has none).
    """
    if not any(r.get("label_abstract_screening") is not None for r in rows):
        return None
    kept_flags = _status_predictions(rows, {"INCLUDE", "NEEDS_REVIEW"})
    pos = [
        (r, kept)
        for r, kept in zip(rows, kept_flags, strict=True)
        if r.get("label_abstract_screening") == 1 and kept is not None
    ]
    n_pos = len(pos)
    n_kept = sum(1 for _, kept in pos if kept)
    final = [kept for r, kept in pos if r.get("label_included") == 1]
    non_final = [kept for r, kept in pos if r.get("label_included") != 1]
    sens = metrics_sensitivity(rows) or {}
    return {
        "n_ta_pos": n_pos,
        "n_ta_kept": n_kept,
        "recall": (n_kept / n_pos) if n_pos else None,
        "wilson": wilson_interval(n_kept, n_pos) if n_pos else (None, None),
        "final": {"n": len(final), "kept": sum(1 for k in final if k)},
        "non_final": {"n": len(non_final), "kept": sum(1 for k in non_final if k)},
        "wss_at_achieved_retained_recall": sens.get("wss_at_achieved_retained_recall"),
    }


def _outright_excluded(row: Mapping[str, Any]) -> bool:
    """True when the screener excluded the row outright: ``status == "EXCLUDE"`` (a row with
    no ``status``: ``predicted == 0``). A NEEDS_REVIEW row stays in the reading queue and an
    unscreened row (``predicted is None``) was never decided, so neither counts."""
    status = row.get("status")
    if status is not None:
        return status == "EXCLUDE"
    return row.get("predicted") == 0


def _other_run_status(row: Mapping[str, Any] | None) -> str | None:
    """The other run's status on the same record (a status-less row: INCLUDE or EXCLUDE
    from ``predicted``); ``None`` when the record is absent or unscreened there."""
    if row is None:
        return None
    if row.get("status") is not None:
        return str(row["status"])
    predicted = row.get("predicted")
    if predicted is None:
        return None
    return "INCLUDE" if predicted else "EXCLUDE"


def excluded_positives(
    rows: Sequence[Mapping[str, Any]],
    other_rows: Sequence[Mapping[str, Any]] | None = None,
    other_run: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Records the source review included that the screener excluded outright.

    ``"final"`` holds final inclusions (``label_included == 1``); ``"ta_non_final"`` holds
    title-and-abstract positives that were not final inclusions
    (``label_abstract_screening == 1`` and ``label_included == 0``). Only rows with status
    EXCLUDE are listed: records routed to NEEDS_REVIEW stay in the reading queue. Each item
    carries the abstract availability and the other run's decision on the same record."""
    other = {r["record_id"]: r for r in other_rows or []}
    out: dict[str, list[dict[str, Any]]] = {"final": [], "ta_non_final": []}
    for r in rows:
        if not _outright_excluded(r):
            continue
        if r.get("label_included") == 1:
            key = "final"
        elif r.get("label_abstract_screening") == 1 and r.get("label_included") == 0:
            key = "ta_non_final"
        else:
            continue
        counterpart = other.get(r["record_id"])
        out[key].append(
            {
                "record_id": r["record_id"],
                "title": r.get("title") or "",
                "reason": r.get("reason") or "",
                "label_included": r.get("label_included"),
                "label_abstract_screening": r.get("label_abstract_screening"),
                "has_abstract": r.get("has_abstract"),
                "other_run": other_run,
                "other_run_predicted": counterpart.get("predicted") if counterpart else None,
                "other_run_status": _other_run_status(counterpart),
            }
        )
    return out


def _fmt_decision(value: Any) -> str:
    if value is None:
        return "not screened"
    return str(int(value))


FN_INTRO = (
    "Records the source review included that the screener excluded outright (status "
    "EXCLUDE), with the screener's stated reason. Records routed to NEEDS_REVIEW stay in "
    "the reading queue and are not listed."
)


def fn_markdown(
    dataset: str,
    excluded_by_run: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
) -> str:
    parts = [f"# False negatives - {dataset}", "", FN_INTRO]
    sections = (
        ("final", "excluded final inclusions"),
        ("ta_non_final", "excluded title-and-abstract positives that were not final inclusions"),
    )
    for run, groups in sorted(excluded_by_run.items()):
        for key, title in sections:
            items = groups.get(key, [])
            parts += ["", f"## Run {run}: {title} ({len(items)})", ""]
            if not items:
                parts.append("_none_")
                continue
            for fn in items:
                parts.append(f"- **{fn['record_id']}** {fn['title']}")
                parts.append(f"  - reason: {fn['reason'] or '(no reason recorded)'}")
                has_abs = fn.get("has_abstract")
                abs_txt = "unknown" if has_abs is None else ("yes" if has_abs else "no")
                other = fn.get("other_run")
                other_status = fn.get("other_run_status")
                other_txt = (
                    f"; run {other}: {other_status or 'not screened'}" if other else ""
                )
                parts.append(f"  - abstract: {abs_txt}{other_txt}")
    return "\n".join(parts) + "\n"


def load_fn_categories(path: Path) -> dict[str, int]:
    """Counts of the committed categories (rule plus language-model overrides; empty categories are
    reported as 'uncategorised')."""
    counts: dict[str, int] = {}
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cat = (row.get("category") or "").strip() or "uncategorised"
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def missing_abstract_info(
    dataset: str,
    data_dir: Path | None,
    rows: Sequence[Mapping[str, Any]],
    deduplicated: bool = False,
) -> dict[str, Any]:
    """Missing-abstract share from ``<dataset>.fetch.json``; fallback: the run rows.

    On a deduplicated basis the fetch file is skipped: its ``n`` counts the exported rows,
    duplicates included, so the share is counted over the kept rows instead."""
    if data_dir is not None and not deduplicated:
        info = read_json(data_dir / f"{dataset}.fetch.json")
        if info and info.get("n"):
            return {
                "source": f"{dataset}.fetch.json",
                "n": info["n"],
                "n_missing_abstract": info.get("n_missing_abstract"),
                "share_missing_abstract": info.get("share_missing_abstract"),
            }
    known = [r for r in rows if r.get("has_abstract") is not None]
    n_missing = sum(1 for r in known if not r["has_abstract"])
    return {
        "source": "rows (deduplicated)" if deduplicated else "rows",
        "n": len(known),
        "n_missing_abstract": n_missing,
        "share_missing_abstract": (n_missing / len(known)) if known else None,
    }


LABEL_NOISE_NOTE = (
    "The gold labels are the source reviews' own screening decisions as distributed by "
    "SYNERGY, not a re-annotation for this evaluation; SYNERGY publishes no per-record "
    "inter-screener agreement, so records counted here as LLM false positives or false "
    "negatives include human label noise and review-specific screening thresholds. "
    "van_de_Schoot_2017's protocol records a deliberately over-inclusive title/abstract "
    "stage, so precision is not compared across datasets here; note that this criterion is "
    "also passed to the screener in the prompt (protocols/README.md: the criteria lists go "
    "unchanged to screen_papers), so it raises this dataset's recall as well, and recall is "
    "read as a capability number only within a dataset -- across runs A and B and against "
    "the baselines on the same records -- not as a ranking of the three datasets."
)


def label_field_note(label_field: str | None) -> str:
    if label_field == "label_included":
        return (
            "Gold label = label_included: the review's final inclusion set after full-text "
            "reading (this SYNERGY export carries no title/abstract decision). A title/abstract "
            "screener is expected to keep more than this set, so precision is a lower bound and "
            f"recall is measured against the final inclusions. {LABEL_NOISE_NOTE}"
        )
    return (
        "Gold label = label_abstract_screening: the human screeners' title/abstract decision "
        "(the evaluated task); recall against the final inclusions is reported separately. "
        f"{LABEL_NOISE_NOTE}"
    )


def _figure4_row(
    dataset: str, series: str, m: Mapping[str, Any], kappa: float | None,
    mfi: Mapping[str, Any] | None = None, status_kappa: float | None = None,
    ta: Mapping[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    """One row of ``figure4_screening.json``.

    ``n_padded_include`` and ``n_padded_decisions``
    are both carried onto every row, not only ``n_padded_include``: production pads
    to NEEDS_REVIEW, never to a predicted=1 row, so ``n_padded_include`` is structurally 0 on
    every production run and the broader ``n_padded_decisions`` (any status, from
    :func:`run_metrics`) is the only one of the two that can ever show a run had a padded
    (no-decision-returned) row at all, on either an ordinary or a strict (``padded decisions as
    unscreened``) row.

    ``mfi`` (``metrics_final_inclusion``, an "LLM run X" row only) adds the retained-recall
    basis -- ``retained_recall`` with its own Wilson interval, ``screened_in_rate``,
    ``wss_at_achieved_retained_recall``, ``auto_inclusion_precision``/``auto_inclusion_n`` and
    ``queue_precision`` -- and ``status_kappa`` adds ``kappa_AB_status``, the three-way
    INCLUDE/EXCLUDE/NEEDS_REVIEW run-to-run kappa: on a protocol that names a full-text
    inclusion criterion ``kappa_AB`` above is undefined by construction (every run gives the
    same, constant INCLUDE-only decision), so this is the only run-to-run agreement figure
    that is not null for such a dataset's model runs, and is the one the manuscript figure
    plots for them.

    ``ta`` (the run's :func:`ta_basis_split`, ``None`` for a dataset with no title-and-abstract
    label) adds ``retained_recall_ta`` with its Wilson interval beside the final-inclusion
    ``retained_recall``, whose basis is named by ``retained_recall_basis``. The caller names
    the other bases in ``extra``: ``label_basis`` (the field the ``FIGURE4_METRICS`` columns
    are scored on), ``basis`` ("deduplicated" or "as exported") and ``prevalence_final``.
    """
    row: dict[str, Any] = {"dataset": dataset, "series": series}
    row.update({k: m.get(k) for k in FIGURE4_METRICS})
    row["kappa_AB"] = kappa
    row["n_padded_include"] = m.get("n_padded_include")
    row["n_padded_decisions"] = m.get("n_padded_decisions")
    if mfi is not None:
        lo, hi = mfi.get("recall_screened_in_wilson") or (None, None)
        row["retained_recall_basis"] = "label_included"
        row["retained_recall"] = mfi.get("recall_screened_in")
        row["retained_recall_wilson_lo"] = lo
        row["retained_recall_wilson_hi"] = hi
        row["screened_in_rate"] = mfi.get("screened_in_rate")
        row["wss_at_achieved_retained_recall"] = mfi.get("wss_at_achieved_retained_recall")
        row["auto_inclusion_precision"] = mfi.get("auto_inclusion_precision")
        row["auto_inclusion_n"] = mfi.get("auto_inclusion_n")
        row["queue_precision"] = mfi.get("queue_precision")
        row["kappa_AB_status"] = status_kappa
        ta_lo, ta_hi = (ta or {}).get("wilson") or (None, None)
        row["retained_recall_ta"] = (ta or {}).get("recall")
        row["retained_recall_ta_wilson_lo"] = ta_lo
        row["retained_recall_ta_wilson_hi"] = ta_hi
    row.update(extra)
    return row


def gate_table_row(gate: Mapping[str, Any] | None, hydrate: str | None) -> dict[str, Any] | None:
    """Numbers for one Table E1-d row.

    Records with no ISSN have an unknown venue, so ``share_lower_bound`` (unresolved
    assumed *outside* WoS: in WoS / all human-included records) and ``share_upper_bound``
    (unresolved assumed *inside* WoS: (in WoS + unresolved) / all human-included records)
    are the true worst-case interval. ``share_resolved_only`` (in WoS / resolved records) is
    a separate point estimate that assumes the unresolved records are in WoS at the same
    rate as the resolved ones -- it is not a bound. ``share_all_included`` is the single
    value when every record is resolved (all three coincide) and ``None`` otherwise;
    ``all_records_share`` is ``None`` when < 90 % of all records are resolved.
    """
    if not gate:
        return None
    inc = gate["included_records"]
    allr = gate.get("all_records") or {}
    n, n_issn = int(inc["n"]), int(inc["n_with_issn"])
    n_unresolved = int(inc.get("n_unresolved", n - n_issn))
    n_in = int(inc["n_in_wos_any"])
    all_n, all_issn = allr.get("n"), allr.get("n_with_issn")
    all_ok = bool(all_n) and all_issn is not None and all_issn / all_n >= MIN_RESOLVED_SHARE
    per = inc.get("per_collection", {})
    return {
        "hydrate": hydrate,
        "n_included": n,
        "resolved": f"{n_issn}/{n}",
        "n_unresolved": n_unresolved,
        "n_in_wos_any": n_in,
        "share_all_included": inc["share_in_wos_any"] if n_unresolved == 0 else None,
        "share_lower_bound": (n_in / n) if n else None,
        "share_resolved_only": (n_in / n_issn) if n_issn else None,
        "share_upper_bound": ((n_in + n_unresolved) / n) if n else None,
        "per_collection": {c: per.get(c, {}).get("n") for c in ("SCIE", "SSCI", "AHCI", "ESCI")},
        "all_records_resolved": (f"{all_issn}/{all_n}" if all_n and all_issn is not None else None),
        "all_records_share": allr.get("share_in_wos_any") if all_ok else None,
    }


def summarise(
    results_dir: Path,
    protocols_dir: Path,
    data_dir: Path | None = None,
    basis_dir: Path = corpus_basis.BASIS_DIR,
) -> dict[str, Any]:
    """Every dataset's numbers. A dataset in ``corpus_basis.DEDUP_DATASETS`` is scored on
    its deduplicated rows (the duplicate rows named by its manifest in ``basis_dir`` are
    dropped right after the run files are read, before any metric or agreement); its
    ``submitted_basis_reference`` holds the final-inclusion and title-and-abstract metrics on
    the undeduplicated rows, with the reason the two bases differ."""
    datasets: dict[str, Any] = {}
    for dataset, run_paths in discover_runs(results_dir).items():
        primary_field = "label_included"
        try:
            protocol = load_protocol(protocols_dir / f"{dataset}.json")
            primary_field = protocol.extra.get("primary_label", "label_included")
            protocol_info: dict[str, Any] = {
                "label_field": protocol.label_field,
                "source_review_doi": protocol.source_review_doi,
                "research_question": protocol.research_question,
                "primary_label": primary_field,
            }
        except ProtocolError as exc:
            protocol_info = {"error": str(exc)}
        raw_rows_by_run = {run: read_jsonl(p) for run, p in run_paths.items()}
        deduplicated = dataset in corpus_basis.DEDUP_DATASETS
        duplicate_ids = corpus_basis.load_duplicate_ids(dataset, basis_dir)
        rows_by_run = {
            run: corpus_basis.apply_basis(rows, duplicate_ids)
            for run, rows in raw_rows_by_run.items()
        }
        first_run = min(raw_rows_by_run, default=None)
        basis: dict[str, Any] = {
            "deduplicated": deduplicated,
            "n_rows_dropped": (
                len(raw_rows_by_run[first_run]) - len(rows_by_run[first_run])
                if first_run is not None else 0
            ),
            "manifest": f"dedup_basis/{dataset}.json" if deduplicated else None,
        }
        runs: dict[str, Any] = {}
        excluded_by_run: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for run, rows in sorted(rows_by_run.items()):
            meta = read_json(run_paths[run].with_suffix(".meta.json"), default={}) or {}
            other = next((o for o in sorted(rows_by_run) if o != run), None)
            excluded = excluded_positives(rows, rows_by_run.get(other) if other else None, other)
            excluded_by_run[run] = excluded
            runs[run] = {
                "file": run_paths[run].name,
                "metrics": run_metrics(rows),
                "metrics_padded_as_unscreened": run_metrics(_without_padded(rows)),
                "metrics_padded_decision_as_unscreened": run_metrics(
                    _without_padded_decision(rows)
                ),
                "metrics_primary": metrics_primary(rows, primary_field),
                # The shipped five-column report's own basis, fixed to
                # label_included regardless of a protocol's own primary_label (every dataset
                # this task re-runs already sets/defaults primary_label to label_included, so
                # this is currently identical to metrics_primary for them; kept as its own
                # field so the report table is correct for any dataset, present or future,
                # whose primary_label differs).
                "metrics_final_inclusion": metrics_primary(rows, "label_included"),
                "metrics_sensitivity": metrics_sensitivity(rows),
                "ta_basis": ta_basis_split(rows),
                "n_excluded_final_inclusions": len(excluded["final"]),
                "n_excluded_ta_positives": len(excluded["ta_non_final"]),
                "excluded_positives": excluded,
                "share_missing_abstract_excluded_positives": _share_missing_abstract(
                    excluded["final"] + excluded["ta_non_final"]
                ),
                "meta": {k: meta.get(k) for k in META_KEYS},
            }
        entry: dict[str, Any] = {
            "protocol": protocol_info,
            "label_field_note": label_field_note(protocol_info.get("label_field")),
            "basis": basis,
            "missing_abstract": missing_abstract_info(
                dataset, data_dir, next(iter(rows_by_run.values()), []),
                deduplicated=deduplicated,
            ),
            "runs": runs,
        }
        if deduplicated:
            entry["submitted_basis_reference"] = {
                "reason": corpus_basis.SUBMITTED_BASIS_REASONS[dataset],
                "n_rows": len(raw_rows_by_run[first_run]) if first_run is not None else 0,
                "runs": {
                    run: {
                        "metrics_final_inclusion": metrics_primary(rows, "label_included"),
                        "metrics_sensitivity": metrics_sensitivity(rows),
                    }
                    for run, rows in sorted(raw_rows_by_run.items())
                },
            }
        if "A" in rows_by_run and "B" in rows_by_run:
            entry["agreement_AB"] = agreement(rows_by_run["A"], rows_by_run["B"])
            entry["agreement_AB_status"] = agreement(
                rows_by_run["A"], rows_by_run["B"], key="status"
            )
        entry["baselines"] = read_json(results_dir / f"{dataset}_baselines.json")
        entry["wos_gate"] = read_json(results_dir / f"{dataset}_wos_gate.json")
        entry["asreview"] = read_json(results_dir / "asreview" / f"{dataset}_asreview.json")
        fetch_info = read_json(data_dir / f"{dataset}.fetch.json") if data_dir else None
        entry["wos_gate_table"] = gate_table_row(
            entry["wos_gate"], (fetch_info or {}).get("hydrate")
        )

        (results_dir / f"{dataset}_false_negatives.md").write_text(
            fn_markdown(dataset, excluded_by_run), encoding="utf-8"
        )
        entry["fn_categories"] = load_fn_categories(
            results_dir / f"{dataset}_fn_categories.csv"
        )
        datasets[dataset] = entry

    figure4 = []
    for dataset, entry in datasets.items():
        kappa = (entry.get("agreement_AB") or {}).get("kappa")
        status_kappa = (entry.get("agreement_AB_status") or {}).get("kappa")
        label_basis = (entry.get("protocol") or {}).get("label_field") or "label"
        basis_name = "deduplicated" if entry["basis"]["deduplicated"] else "as exported"

        def basis_cols(
            mfi: Mapping[str, Any] | None, basis_label: str | None = None
        ) -> dict[str, Any]:
            n_pos = (mfi or {}).get("n_positive")
            n_lab = (mfi or {}).get("n")
            return {
                "label_basis": basis_label or label_basis,
                "basis": basis_name,
                "prevalence_final": (n_pos / n_lab) if n_lab else None,
            }

        first_mfi = next(
            (i.get("metrics_final_inclusion") for i in entry["runs"].values()), None
        )
        for run, info in entry["runs"].items():
            mfi = info.get("metrics_final_inclusion")
            ta = info.get("ta_basis")
            cols = basis_cols(mfi)
            figure4.append(
                _figure4_row(
                    dataset, f"LLM run {run}", info["metrics"], kappa,
                    mfi=mfi, status_kappa=status_kappa, ta=ta, **cols,
                )
            )
            if info["metrics"].get("n_padded_include"):
                figure4.append(
                    _figure4_row(
                        dataset,
                        f"LLM run {run} (padded as unscreened)",
                        info["metrics_padded_as_unscreened"],
                        kappa,
                        mfi=mfi, status_kappa=status_kappa, ta=ta, **cols,
                    )
                )
            if info["metrics"].get("n_padded_decisions"):
                # The strict reading -- every row still flagged
                # padded_decision (any status, not just the narrower padded_include) scored
                # as unscreened, not as a screener decision.
                figure4.append(
                    _figure4_row(
                        dataset,
                        f"LLM run {run} (padded decisions as unscreened)",
                        info["metrics_padded_decision_as_unscreened"],
                        kappa,
                        mfi=mfi, status_kappa=status_kappa, ta=ta, **cols,
                    )
                )
        base = entry.get("baselines") or {}
        base_label = base.get("label_field")  # baselines are scored on their own label field
        if base.get("include_all"):
            figure4.append(
                _figure4_row(
                    dataset, "include-all", base["include_all"], None,
                    **basis_cols(first_mfi, base_label),
                )
            )
        if base.get("tfidf"):
            m = dict(base["tfidf"]["metrics"])
            m["wss_at_95"] = base["tfidf"].get("wss_at_95_ranking")
            figure4.append(
                _figure4_row(
                    dataset, "TF-IDF (k matched)", m, None, query_mode=base.get("query_mode"),
                    **basis_cols(first_mfi, base_label),
                )
            )
        gate = entry.get("wos_gate_table")
        if gate:
            # wos_gate_effect.py counts a deduplicated dataset on its deduplicated records, the
            # basis of every other row of the series.
            figure4.append(
                {
                    "dataset": dataset,
                    "series": "WoS gate",
                    "hydrate": gate["hydrate"],
                    "n_included": gate["n_included"],
                    "resolved": gate["resolved"],
                    "n_in_wos_any": gate["n_in_wos_any"],
                    "share_lower_bound": gate["share_lower_bound"],
                    "share_resolved_only": gate["share_resolved_only"],
                    "share_upper_bound": gate["share_upper_bound"],
                }
            )
    asr_meta = read_json(results_dir / "asreview" / "asreview_meta.json")
    return {
        "results_dir": _portable_dir(results_dir),
        "asreview_meta": (
            {k: asr_meta.get(k) for k in ("asreview_version", "seeds")} if asr_meta else None
        ),
        "datasets": datasets,
        "figure4": figure4,
    }


def _cost_str(meta: Mapping[str, Any]) -> Any:
    """The raw cost, not pre-rounded: ``markdown_table`` formats every cell through
    ``common.fmt`` at its 3-decimal display precision, and rounding here first (to 4
    decimals) double-rounds -- e.g. 0.17351378 rounds correctly to 0.174 at 3 dp directly,
    but rounds to 0.1735 at 4 dp first and then prints as 0.173, because 0.1735 is not
    exactly representable in binary floating point."""
    cost = meta.get("total_cost")
    return None if cost is None else float(cost)


PERF_HEADERS = [
    "Dataset", "System", "Gold label", "n", "Prevalence (gold label)", "Recall", "Precision",
    "F1", "Specificity", "Inclusion rate", "WSS@R (achieved)", "WSS@95", "kappa A/B",
    "Retained recall (final inclusions)", "Retained recall 95% CI (final inclusions)",
]
# Table E1-f: the screener's retention of the title-and-abstract positives, split into the
# ones that are also final inclusions and the ones the review dropped at full text.
TA_HEADERS = [
    "Dataset", "Run", "TA positives (n)", "Retained (TA)", "Retained recall (TA)", "95% CI",
    "Final inclusions kept", "Non-final TA positives kept", "Reading saved (TA basis)",
]
NO_TA_LABEL_TEXT = "no title-and-abstract label in this export"
SUBMITTED_BASIS_DATASET = "van_de_Schoot_2017"
QUEUE_HEADERS = [
    "Dataset", "Run", "Cause", "Records (n)", "Share of corpus", "Final inclusions (n)",
    "TA positives (n)",
]
TFIDF_READ_HEADERS = [
    "Dataset", "Run", "N", "Screener: records read", "Screener: final inclusions kept",
    "TF-IDF at the screener's budget: found",
    "TF-IDF to reach the screener's count: records read",
    "TF-IDF at 95% recall: records read (found / target)",
]
TFIDF_READ_NOTE = (
    "The TF-IDF stopping points are fixed with the labels; the screener's point is its own "
    "label-free decision. The screener has no ranking, so it has no 95% recall point."
)
ASREVIEW_HEADERS = [
    "Dataset", "Screener run", "Screener: records read (final kept)",
    "ASReview found at that budget: mean (min to max)",
    "ASReview records to reach the screener's count: mean (min to max)",
    "WSS@95: mean (min to max)", "WSS@100: mean (min to max)",
    "Stop after 100 irrelevant: records read, found",
]
ASREVIEW_NOTE = (
    "ASReview uses the reviewer's labels as screening proceeds; the screener uses none and "
    "makes the exclusion decision itself. WSS@95 and WSS@100 stop at a point fixed with the "
    "labels; the last column applies a stopping rule that does not."
)


def _stat(agg: Mapping[str, Any] | None, digits: int = 0, n_seeds: int = 15) -> str:
    """``mean (min to max)`` for one aggregate; a seed that never got there is counted aloud."""
    if not agg or agg.get("mean") is None:
        if not agg:
            return "-"
        return f"not reached in {agg.get('n_not_reached', n_seeds)} of {n_seeds} seeds"
    text = f"{agg['mean']:.{digits}f} ({agg['min']:.{digits}f} to {agg['max']:.{digits}f})"
    missed = agg.get("n_not_reached") or 0
    return f"{text}; not reached in {missed} of {n_seeds} seeds" if missed else text


def _asreview_rows(dataset: str, asr: Mapping[str, Any] | None) -> list[list[Any]]:
    """Table E1-i rows for one dataset: ASReview LAB at each screener run's operating point."""
    if not asr:
        return []
    agg = asr.get("aggregate") or {}
    n_seeds = len(asr.get("per_seed") or []) or 15
    n = asr.get("n_total")
    stop = (
        f"{_stat(agg.get('stop_rule_records'), 0, n_seeds)}, "
        f"{_stat(agg.get('stop_rule_found'), 1, n_seeds)}"
    )
    rows = []
    for run, sc in sorted((asr.get("screener") or {}).items()):
        rows.append(
            [
                dataset, run, f"{_reads(sc.get('budget'), n)} ({sc.get('found')})",
                _stat(agg.get(f"{run}.found_at_screener_budget"), 1, n_seeds),
                _stat(agg.get(f"{run}.records_to_screener_found"), 0, n_seeds),
                _stat(agg.get("wss_at_95"), 3, n_seeds),
                _stat(agg.get("wss_at_100"), 3, n_seeds), stop,
            ]
        )
    return rows


def _asreview_line(meta: Mapping[str, Any] | None) -> str:
    """The one line naming the version, model, priors and seeds."""
    if not meta:
        return ""
    seeds = meta.get("seeds") or []
    span = f"{min(seeds)} to {max(seeds)}" if seeds else "-"
    version = str(meta.get("asreview_version") or "-").replace("asreview ", "")
    return (
        f"ASReview LAB {version}, default model (elas_u4), priors one relevant and one "
        f"irrelevant record, seeds {span}."
    )


SECONDARY_HEADERS = [
    "Dataset", "Run", "Gold label", "Final inclusions (n)", "Recall vs final inclusions",
    "Retained recall vs final inclusions",
    "Unscreened records", "Padded INCLUDE (n)", "Recall / precision (padded as unscreened)",
    "Excluded final inclusions", "Excluded TA positives",
    "Excluded positives without abstract (share)", "Missing abstract (share)",
    "Missing title (n)", "% agreement A/B",
]
PROV_HEADERS = [
    "Dataset", "Run", "Model configured", "Model reported", "Fingerprints", "Temp.",
    "Prompt version", "Batches", "Failed", "Retried", "Input tokens", "Output tokens",
    "Cost (USD)", "Cost basis", "Concurrency", "Latency median (s)", "Latency p90 (s)", "Date",
]
GATE_HEADERS = [
    "Dataset", "Hydration", "Included n", "Resolved (ISSN/n)", "in WoS (any)",
    "Ceiling lower-upper", "SCIE", "SSCI", "AHCI", "ESCI",
    "All records resolved", "All records share",
]
# The five-column final-inclusion report (retained recall, screened-in share,
# reading saved, auto-inclusion precision, queue precision), plus the run-to-run A/B
# agreement on the three-way status (kappa is a per-dataset, not a per-run, number, so it is
# printed once per dataset rather than duplicated on every run's own row).
# The same table also carries a non-LLM baseline row per dataset (include-all and, on
# the same final-inclusion basis, a TF-IDF ranker matched to the screener's own screened-in
# count); a baseline has no NEEDS_REVIEW queue and no second run, so its own Queue precision
# and A/B agreement cells read "-"; the trailing column is the TF-IDF ranking's work saved at
# a fixed 0.95 recall (independent of the matched threshold), "-" for every other row.
FINAL_INCLUSION_HEADERS = [
    "Dataset", "Run", "n", "Retained recall", "95% CI", "Screened-in share",
    "Excluded share", "Reading saved (WSS)", "Auto-inclusion precision (n)", "Queue precision",
    "A/B agreement, status (kappa)", "Reading saved @0.95 (TF-IDF ranking)",
]


def _auto_inclusion_precision_str(mfi: Mapping[str, Any]) -> str:
    """"none, n = 0" when no record was auto-included at all (the structural consequence of
    routing every unconfirmed full-text inclusion criterion to NEEDS_REVIEW, on any protocol
    naming one); "<precision> (n = <n>)" otherwise."""
    n = mfi.get("auto_inclusion_n") or 0
    if n == 0:
        return "none, n = 0"
    return f"{fmt(mfi.get('auto_inclusion_precision'))} (n = {n})"


def _retained_recall_ci_str(mfi: Mapping[str, Any]) -> str:
    lo, hi = mfi.get("recall_screened_in_wilson") or (None, None)
    if lo is None or hi is None:
        return "-"
    return f"[{fmt(lo)}, {fmt(hi)}]"


def _wilson_ci_str(lo: Any, hi: Any) -> str:
    if lo is None or hi is None:
        return "-"
    return f"[{fmt(lo)}, {fmt(hi)}]"


def _baseline_final_inclusion_row(
    dataset: str, name: str, m: Mapping[str, Any], wss95_ranking: Any = None
) -> list:
    """One Table E1-e row for a non-LLM baseline, scored on the same
    ``label_included`` basis as ``m`` already is (``baselines.py --label primary``, the
    default). A baseline makes one include/exclude decision per record and has no
    NEEDS_REVIEW queue and no second run to compare against, so its retained recall is
    simply ``m["recall"]``, its screened-in share is ``m["inclusion_rate"]``, its precision
    stands in for auto-inclusion precision with ``n`` the number of records it included, and
    its Queue precision and A/B agreement cells read "-". ``wss95_ranking`` (the TF-IDF
    ranking's work saved at a fixed 0.95 recall, independent of the threshold ``m`` itself
    was matched at) is given only for the TF-IDF row; every other row's trailing cell is "-".
    """
    tp, fn, fp = m.get("tp") or 0, m.get("fn") or 0, m.get("fp") or 0
    n_positive = tp + fn
    n_included = tp + fp
    ci = _wilson_ci_str(*wilson_interval(tp, n_positive)) if n_positive else "-"
    precision_str = (
        f"{fmt(m.get('precision'))} (n = {n_included})" if n_included else "none, n = 0"
    )
    return [
        dataset, name, m.get("n"), m.get("recall"), ci, m.get("inclusion_rate"),
        None if m.get("inclusion_rate") is None else 1 - m["inclusion_rate"],
        m.get("wss_at_achieved_recall"), precision_str, "-", "-", wss95_ranking,
    ]


def _ceiling_str(gate: Mapping[str, Any]) -> str:
    """``0.640-0.883 (resolved-only 0.845)`` while records are unresolved; a single value
    once all are resolved (the interval collapses and the point estimate is redundant)."""
    if gate.get("share_all_included") is not None:
        return fmt(gate["share_all_included"])
    lower, upper = gate.get("share_lower_bound"), gate.get("share_upper_bound")
    if lower is None or upper is None:
        return "-"
    resolved_only = gate.get("share_resolved_only")
    suffix = f" (resolved-only {fmt(resolved_only)})" if resolved_only is not None else ""
    return f"{fmt(lower)}-{fmt(upper)}{suffix}"


def _perf_row(
    dataset: str, system: str, m: Mapping[str, Any], wss95: Any, kappa: Any,
    mfi: Mapping[str, Any] | None = None, gold_label: Any = None,
) -> list:
    """One row of Table E1-a. ``mfi`` (``metrics_final_inclusion``, present for an "LLM run
    X" row, ``None`` for a baseline row that was never scored on the final-inclusion basis)
    supplies the trailing retained-recall pair: the primary read of this table once any
    dataset's protocol names a full-text inclusion criterion, since the preceding Recall /
    Precision / WSS columns then count INCLUDE decisions only and are 0 by construction (the
    full-text-to-confirm guard demotes every genuine INCLUDE to NEEDS_REVIEW first)."""
    return [
        dataset, system, gold_label, m["n"], m["prevalence"], m["recall"], m["precision"], m["f1"],
        m["specificity"], m["inclusion_rate"], m["wss_at_achieved_recall"], wss95, kappa,
        mfi.get("recall_screened_in") if mfi else None,
        _retained_recall_ci_str(mfi) if mfi else "-",
    ]


def _ta_rows(dataset: str, entry: Mapping[str, Any]) -> list[list[Any]]:
    """Table E1-f rows for one dataset: one per run, or a single row saying the export has no
    title-and-abstract label (never a zero, never silently omitted)."""
    rows: list[list[Any]] = []
    for run, info in entry["runs"].items():
        ta = info.get("ta_basis")
        if not ta:
            continue
        lo, hi = ta["wilson"]
        rows.append(
            [
                dataset, run, ta["n_ta_pos"], ta["n_ta_kept"], ta["recall"],
                _wilson_ci_str(lo, hi),
                f"{ta['final']['kept']}/{ta['final']['n']}",
                f"{ta['non_final']['kept']}/{ta['non_final']['n']}",
                ta["wss_at_achieved_retained_recall"],
            ]
        )
    if not rows:
        rows.append([dataset, "-", NO_TA_LABEL_TEXT, "-", "-", "-", "-", "-", "-"])
    return rows


def _reads(n: Any, total: Any) -> str:
    """``1,234 (61.5%)``: records read and their share of the corpus; ``-`` when unknown."""
    if n is None:
        return "-"
    if not total:
        return f"{n:,}"
    return f"{n:,} ({100 * n / total:.1f}%)"


def _tfidf_read_rows(dataset: str, base: Mapping[str, Any]) -> list[list[Any]]:
    """Table E1-h row for one dataset: the TF-IDF ranking against the screener, in records
    read. The baseline is scored against one screener run (``run_file``); the figures are fixed
    with the labels, and a baseline file written before they were recorded prints no row."""
    tf = base.get("tfidf") or {}
    if tf.get("screener_budget") is None and tf.get("records_read_at_95") is None:
        return []
    n = base.get("n")
    match = RUN_FILE_RE.match(str(base.get("run_file") or ""))
    run = match.group("run") if match else "-"
    target = tf.get("target_at_95")
    at95 = tf.get("records_read_at_95")
    at95_text = (
        "-" if at95 is None else f"{_reads(at95, n)} ({target} / {target})"
    )
    return [
        [
            dataset, run, n, _reads(tf.get("screener_budget"), n), tf.get("screener_found"),
            tf.get("found_at_screener_budget"),
            _reads(tf.get("records_read_at_screener_found"), n), at95_text,
        ]
    ]


def _submitted_basis_sentence(dataset: str, entry: Mapping[str, Any]) -> str | None:
    """The one sentence that names the as-exported figures, printed under Table E1-e."""
    ref = entry.get("submitted_basis_reference")
    if not ref or not ref.get("runs"):
        return None
    run = sorted(ref["runs"])[0]
    mfi = ref["runs"][run]["metrics_final_inclusion"] or {}
    n_pos = mfi.get("n_positive")
    recall_value = mfi.get("recall_screened_in")
    if not n_pos or recall_value is None:
        return None
    kept = round(recall_value * n_pos)
    return (
        f"{dataset} as exported ({ref['n_rows']:,} rows): retained recall "
        f"{kept}/{n_pos} = {fmt(recall_value)}; {ref['reason']}."
    )


def render_markdown(summary: Mapping[str, Any]) -> str:
    parts = ["# Screening evaluation summary (E1)", ""]
    perf_rows: list[list[Any]] = []
    prov_rows: list[list[Any]] = []
    gate_rows: list[list[Any]] = []
    secondary_rows: list[list[Any]] = []
    final_inclusion_rows: list[list[Any]] = []
    queue_rows: list[list[Any]] = []
    tfidf_read_rows: list[list[Any]] = []
    asreview_rows: list[list[Any]] = []
    ta_rows: list[list[Any]] = []
    submitted_sentences: list[str] = []
    notes: list[str] = []
    kappa_footnote = False
    status_kappa_footnote = False
    structural_zero_footnote = False
    abstract_cap: int | None = None
    for dataset, entry in summary["datasets"].items():
        agr = entry.get("agreement_AB") or {}
        kappa = agr.get("kappa")
        if agr.get("kappa_undefined"):
            kappa_footnote = True
        pct = agr.get("percent_agreement")
        agr_status = entry.get("agreement_AB_status") or {}
        status_kappa = agr_status.get("kappa")
        if agr_status.get("kappa_undefined"):
            status_kappa_footnote = True
        label_field = (entry.get("protocol") or {}).get("label_field")
        missing = (entry.get("missing_abstract") or {}).get("share_missing_abstract")
        notes.append(f"- **{dataset}**: {entry.get('label_field_note', '')}")
        ta_rows.extend(_ta_rows(dataset, entry))
        if dataset == SUBMITTED_BASIS_DATASET:
            sentence = _submitted_basis_sentence(dataset, entry)
            if sentence:
                submitted_sentences.append(sentence)
        for run, info in entry["runs"].items():
            m = info["metrics"]
            mfi = info.get("metrics_final_inclusion")
            if mfi and not mfi.get("auto_inclusion_n") and (mfi.get("recall_screened_in") or 0) > 0:
                # This table's own Recall/Precision/WSS columns count INCLUDE decisions only;
                # 0 auto-inclusions here while retained recall (INCLUDE or NEEDS_REVIEW) is
                # above 0 means those columns read exactly 0.000 by construction, not because
                # the screener missed anything -- see the trailing Retained recall columns.
                structural_zero_footnote = True
            perf_rows.append(
                _perf_row(
                    dataset, f"LLM run {run}", m, m["wss_at_95"], kappa, mfi=mfi,
                    gold_label=label_field,
                )
            )
            if mfi:
                final_inclusion_rows.append(
                    [
                        dataset, run, mfi["n"], mfi["recall_screened_in"],
                        _retained_recall_ci_str(mfi), mfi["screened_in_rate"],
                        mfi.get("excluded_share"), mfi["wss_at_achieved_retained_recall"],
                        _auto_inclusion_precision_str(mfi), mfi.get("queue_precision"),
                        status_kappa, None,
                    ]
                )
            for cause, q in sorted(
                ((mfi or {}).get("queue_by_reason") or {}).items(),
                key=lambda kv: (-kv[1]["n"], kv[0]),
            ):
                queue_rows.append(
                    [
                        dataset, run, cause, q["n"], q["share_of_corpus"], q["n_final_pos"],
                        q["n_ta_pos"],
                    ]
                )
            meta = info["meta"]
            if abstract_cap is None and meta.get("abstract_cap") is not None:
                abstract_cap = meta["abstract_cap"]
            lat = meta.get("latency_s") or {}
            prov_rows.append(
                [
                    dataset, run, meta.get("model_configured"),
                    ", ".join(meta.get("model_reported") or []) or None,
                    len(meta.get("system_fingerprints") or []),
                    meta.get("temperature"),
                    ", ".join(meta.get("prompt_version") or []) or None,
                    meta.get("n_batches"), meta.get("failures"), meta.get("retried_failed"),
                    meta.get("total_input_tokens"), meta.get("total_output_tokens"),
                    _cost_str(meta), meta.get("cost_basis"), meta.get("concurrency"),
                    lat.get("median"), lat.get("p90"),
                    (meta.get("started") or "")[:10] or None,
                ]
            )
            excl = info.get("metrics_padded_as_unscreened") or {}
            excl_txt = (
                f"{fmt(excl.get('recall'))} / {fmt(excl.get('precision'))}"
                if m.get("n_padded_include")
                else "as-is"
            )
            secondary_rows.append(
                [
                    dataset, run, label_field, m["n_final_inclusions"],
                    m["final_inclusion_recall"],
                    mfi.get("recall_screened_in") if mfi else None,
                    m["n_unscreened"], m.get("n_padded_include"),
                    excl_txt, info.get("n_excluded_final_inclusions"),
                    info.get("n_excluded_ta_positives"),
                    info.get("share_missing_abstract_excluded_positives"), missing,
                    m.get("n_missing_title"), pct,
                ]
            )
        base = entry.get("baselines") or {}
        if base.get("include_all"):
            m = base["include_all"]
            perf_rows.append(
                _perf_row(
                    dataset, "include-all", m, m["wss_at_95"], None,
                    gold_label=base.get("label_field") or label_field,
                )
            )
            final_inclusion_rows.append(_baseline_final_inclusion_row(dataset, "include-all", m))
        if base.get("tfidf"):
            m = base["tfidf"]["metrics"]
            wss95 = base["tfidf"].get("wss_at_95_ranking")
            label = f"TF-IDF (k={base.get('k')}, query={base.get('query_mode') or 'rq+criteria'})"
            perf_rows.append(
                _perf_row(
                    dataset, label, m, wss95, None,
                    gold_label=base.get("label_field") or label_field,
                )
            )
            final_inclusion_rows.append(
                _baseline_final_inclusion_row(dataset, label, m, wss95)
            )
        tfidf_read_rows.extend(_tfidf_read_rows(dataset, base))
        asreview_rows.extend(_asreview_rows(dataset, entry.get("asreview")))
        gate = entry.get("wos_gate_table") or gate_table_row(entry.get("wos_gate"), None)
        if gate:
            per = gate["per_collection"]
            gate_rows.append(
                [
                    dataset,
                    gate["hydrate"] or "unknown", gate["n_included"], gate["resolved"],
                    gate["n_in_wos_any"], _ceiling_str(gate),
                    *(per.get(c) for c in ("SCIE", "SSCI", "AHCI", "ESCI")),
                    gate["all_records_resolved"], gate["all_records_share"],
                ]
            )

    abstract_cap_note = (
        f"{abstract_cap:,} characters" if abstract_cap is not None
        else "a configured character cap"
    )
    parts += ["## Table E1-a. Screening performance on each protocol's gold label", ""]
    parts.append(markdown_table(PERF_HEADERS, perf_rows))
    parts += [
        "",
        "Metrics use the protocol label named in the Gold label column (see the gold-label "
        "notes below); a deduplicated dataset is scored on its deduplicated records. "
        "WSS@R = (TN+FN)/N - (1-R) (Cohen et al. 2006) at the achieved recall; WSS@95 is "
        "given for a fixed decision only when recall >= 0.95, and for TF-IDF from its ranking. "
        "kappa is Cohen's kappa between runs A and B on records screened in both. Metrics are "
        "computed on the decisions as production returned them; Table E1-b gives the count of "
        "INCLUDE decisions production padded in because the model returned no decision "
        "('no decision returned') and the recall / precision with those rows treated as "
        "unscreened (padded as unscreened). All figures are point estimates on the stated n "
        "with no confidence interval; a few-point difference between systems, datasets or "
        "runs A and B is not interpreted as a difference (see README.md, 'No confidence "
        "intervals'). The trailing 'Retained recall' pair (blank for a baseline row, which is "
        "never scored on this basis) counts INCLUDE or NEEDS_REVIEW as a positive decision "
        "instead of INCLUDE alone; it is the primary reading of this table once a protocol "
        "names a full-text inclusion criterion (Table E1-e reports it in full, alongside "
        "screened-in share, reading saved, auto-inclusion precision and queue precision).",
        *(["", "kappa undefined here: this column scores only the binary INCLUDE / "
           "not-INCLUDE decision, which is constant across every record in both runs (not "
           "the three-way INCLUDE/EXCLUDE/NEEDS_REVIEW status), so expected agreement is 1 "
           "and kappa has no value; '-' is printed. This does not mean the two runs are "
           "identical record by record -- Table E1-e's own three-way status kappa, computed "
           "on the same runs, is reported there."]
          if kappa_footnote else []),
        *(["", "Structurally zero: this table's own Recall, Precision and WSS columns count "
           "INCLUDE decisions only, and a dataset whose protocol names a full-text inclusion "
           "criterion cannot clear that criterion from title and abstract alone, so the "
           "full-text-to-confirm guard demotes every genuine INCLUDE to NEEDS_REVIEW before "
           "this table's own columns can count it; those columns then read exactly 0.000 (or "
           "blank) by construction, not as a measure of a failure to find anything -- the "
           "trailing Retained recall columns and Table E1-e report what the screener actually "
           "kept."]
          if structural_zero_footnote else []),
        "",
        *notes,
        "",
        "## Table E1-b. Secondary numbers",
        "",
        markdown_table(SECONDARY_HEADERS, secondary_rows),
        "",
        "Missing abstract (share) is the share of dataset records without an abstract "
        "(from the fetch counts, else from the run rows); the production prompt shows "
        f"'(no abstract)' for those records and truncates abstracts to {abstract_cap_note}. "
        "Missing title (n) counts screened records without title text (the prompt shows "
        "'(no title)'); with no abstract either, such records are blank to the screener. "
        "'Retained recall vs final inclusions' is the same INCLUDE-or-NEEDS_REVIEW basis as "
        "Table E1-a's trailing columns and Table E1-e's own retained recall, scored here "
        "against the review's final inclusions specifically rather than this table's own gold "
        "label. '% agreement A/B' is the same binary INCLUDE / not-INCLUDE basis as Table "
        "E1-a's own kappa column, not the three-way status agreement Table E1-e reports; it "
        "reads 1.000 whenever no record was INCLUDE in either run, which is not the same "
        "thing as the two runs matching on every record's status.",
        "",
        "## Table E1-e. Final-inclusion basis (primary basis: retained recall, "
        "screened-in share, reading saved, auto-inclusion precision, queue precision)",
        "",
        markdown_table(FINAL_INCLUSION_HEADERS, final_inclusion_rows),
        "",
        "All five figures are scored against label_included (the review's own final "
        "inclusions), regardless of which label a dataset's other tables use as primary. "
        "Retained recall counts INCLUDE or NEEDS_REVIEW as a positive screening decision "
        "(everything not yet excluded); its 95% CI is the Wilson interval on the "
        "true positives over the shared positive count. Screened-in share is the fraction of "
        "the corpus routed to INCLUDE or NEEDS_REVIEW. Reading saved is work saved over "
        "sampling (Cohen et al. 2006), (TN+FN)/N - (1-R), evaluated at the *retained* recall "
        "R above (not the INCLUDE-only recall Table E1-a's WSS columns use). Reading saved is "
        "the excluded share minus (1 - R); the excluded share itself is printed in its own "
        "column. Excluded share is the fraction of the corpus the screener excluded outright; "
        "it does not have to sum to one with the screened-in share, since one measures what "
        "was excluded and the other what was not excluded. "
        "Auto-inclusion precision is the share of INCLUDE decisions that are a genuine final "
        "inclusion, with n the count of INCLUDE decisions it is computed over; printed as "
        "'none, n = 0' when no record was auto-included at all, the structural consequence of "
        "routing an unconfirmed full-text inclusion criterion to NEEDS_REVIEW rather than "
        "INCLUDE on any protocol that names one. Queue precision "
        "is the share of NEEDS_REVIEW rows that are a genuine final inclusion, i.e. how often "
        "the queue a reviewer reads actually contains one. A/B agreement is Cohen's kappa "
        "between runs A and B on the three-way INCLUDE/EXCLUDE/NEEDS_REVIEW status "
        "(agreement_AB_status), a per-dataset number repeated on each run's own row. Each "
        "dataset also carries an include-all and a TF-IDF baseline row (baselines.py, matched "
        "to the screener's own screened-in count and scored on the same label_included basis); "
        "a baseline has no NEEDS_REVIEW queue and no second run, so its Queue precision and "
        "A/B agreement cells read '-', and its Auto-inclusion precision (n) column reports its "
        "overall precision with n the number of records it included. The trailing column is "
        "the TF-IDF ranking's work saved at a fixed 0.95 recall, independent of the matched "
        "threshold; '-' for every other row.",
        *(["", "kappa undefined (constant runs) for the status agreement column: '-' is "
           "printed where this applies."]
          if status_kappa_footnote else []),
        *(["", *submitted_sentences] if submitted_sentences else []),
        "",
        "## Table E1-f. Title-and-abstract basis",
        "",
        markdown_table(TA_HEADERS, ta_rows),
        "",
        "A title-and-abstract (TA) positive is a record the source review's human screeners "
        "kept at the title-and-abstract stage. 'Final inclusions kept' counts the TA positives "
        "that are also final inclusions (kept / n); 'Non-final TA positives kept' counts the "
        "ones the review dropped at full text. Retained means INCLUDE or NEEDS_REVIEW, and "
        "Reading saved is evaluated at the retained TA recall. A dataset whose export carries "
        "no TA decision prints one row saying so.",
        "",
        "## Table E1-g. Reading queue by cause",
        "",
        markdown_table(QUEUE_HEADERS, queue_rows),
        "",
        "Each NEEDS_REVIEW record is counted under the cause the screener attached to it "
        "(its guard reason; 'no_abstract' for a record with no abstract, 'undecidable' for a "
        "model routing the guard did not touch). Share of corpus is over the screened records. "
        "Final inclusions and TA positives count the queued records of that cause that the "
        "source review kept at full text and at title and abstract; a dash means the export "
        "carries no title-and-abstract label.",
        "",
        "## Table E1-h. TF-IDF ranking against the screener, in records read",
        "",
        markdown_table(TFIDF_READ_HEADERS, tfidf_read_rows),
        "",
        TFIDF_READ_NOTE,
        "",
        *(
            [
                "## Table E1-i. ASReview LAB simulation (15 seeds) at the screener's "
                "operating point",
                "",
                markdown_table(ASREVIEW_HEADERS, asreview_rows),
                "",
                ASREVIEW_NOTE,
                "",
                _asreview_line(summary.get("asreview_meta")),
                "",
            ]
            if asreview_rows
            else []
        ),
        "## Table E1-c. Provenance, cost and latency per run",
        "",
        markdown_table(PROV_HEADERS, prov_rows),
        "",
        "Cost (USD) sums the per-call list price of the reported model with the peak/off-peak "
        "tier taken from each call's timestamp; the screening interface exposes no cache-hit "
        "split, so every input token is billed at the cache-miss rate and the figure is an "
        "upper bound. Output tokens are recorded as reported by the API and may include "
        "reasoning tokens. 'Fingerprints' counts the distinct `system_fingerprint` values the "
        "API returned across the run's calls; more than one indicates the served model "
        "changed mid-run. Latency is wall-clock per batch call measured while up to "
        "'Concurrency' calls were in flight (the harness default is 8; production uses "
        "analysis_concurrency = 4), so medians and p90 include provider-side queueing.",
        "",
    ]
    if gate_rows:
        parts += [
            "## Table E1-d. WoS venue-gate effect (recall ceiling of the optional Stage-1 filter)",
            "",
            markdown_table(GATE_HEADERS, gate_rows),
            "",
            "A deduplicated dataset is counted on its deduplicated records, the basis of "
            "every other table of this section.",
            "",
            "'Ceiling lower-upper' is the recall ceiling of the gate over the human-included "
            "records: a record with no ISSN has an unknown venue, so the gate's recall "
            "ceiling lies between the lower bound (unresolved records assumed outside WoS: "
            "in WoS / Included n) and the upper bound (unresolved records assumed inside "
            "WoS: (in WoS + unresolved) / Included n), with 'Resolved (ISSN/n)' next to "
            "them; the parenthetical 'resolved-only' figure (in WoS / resolved) is a point "
            "estimate, not a bound, that assumes the unresolved records are in WoS at the "
            "same rate as the resolved ones. A fully resolved set prints a single value, "
            "all three coinciding. 'All records share' is printed only "
            "when at least 90 % of all records carry an ISSN ('-' otherwise). Route-v1 "
            "datasets are hydrated for the human-included records only ('Hydration' = "
            "included), so their all-records column is unresolved by design. Resolution is "
            "by DOI where the export has one and otherwise by exact normalised title in "
            "Crossref; title-only matches carry a same-title risk (a comment, reprint or "
            "conference abstract with the same title would attribute a wrong venue) and "
            "cannot be year-checked when the export carries no year (Nagtegaal_2019); the "
            "protocol files record a spot-check (judged by the harness fix agent, to be "
            "re-read by the authors) of such matches, 20/20 correct in each dataset, a "
            "sample rather than a census whose 95 % Wilson interval is "
            "[0.839, 1.000], so up to about one in six title-only matches could still be a "
            "same-title mismatch, an error these intervals do not carry.",
            "",
        ]
    any_categorised = any(
        any(cat != "uncategorised" for cat in (entry.get("fn_categories") or {}))
        for entry in summary["datasets"].values()
    )
    any_fn_categories = any(entry.get("fn_categories") for entry in summary["datasets"].values())
    if any_categorised:
        parts += [
            "False-negative categories. The categories below were read from the "
            "`<dataset>_fn_categories.csv` files in this results directory. The "
            "categorisation package that documents how such codes were "
            "assigned is not part of this release, so no method disclosure or "
            "agreement figure is printed here.",
            "",
        ]
    elif any_fn_categories:
        parts += [
            "False-negative categories. The `category` column in each dataset's own "
            "`<dataset>_fn_categories.csv` has not been filled in for this results "
            "directory, so every false-negative row below is reported as uncategorised.",
            "",
        ]
    for dataset, entry in summary["datasets"].items():
        cats = entry.get("fn_categories") or {}
        if cats:
            parts += [f"### False-negative categories - {dataset}", ""]
            parts.append(markdown_table(["Category", "n"], sorted(cats.items())))
            parts.append("")
    return "\n".join(parts)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    ap.add_argument("--protocols-dir", type=Path, default=PROTOCOLS_DIR)
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR, help="holds <dataset>.fetch.json")
    return resolve_path_args(ap.parse_args(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = summarise(args.results_dir, args.protocols_dir, args.data_dir)
    if not summary["datasets"]:
        print(f"no run files found in {args.results_dir}")
        return 1
    write_json(args.results_dir / "summary.json", summary)
    write_json(
        args.results_dir / "figure4_screening.json",
        {
            "rows": summary["figure4"],
        },
    )
    (args.results_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    for dataset, entry in summary["datasets"].items():
        runs = ", ".join(
            f"{run}: recall={info['metrics']['recall']} precision={info['metrics']['precision']}"
            for run, info in entry["runs"].items()
        )
        print(f"{dataset}: {runs}; kappa A/B={(entry.get('agreement_AB') or {}).get('kappa')}")
    print(f"wrote {args.results_dir / 'summary.json'}, summary.md and figure4_screening.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
