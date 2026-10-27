# Changelog

All notable changes to ScholarRAG are documented in this file. The format follows
Keep a Changelog.

## [1.2.0] - 2026-10-27

### Added

- The section write job result carries `gate_log`: the first-pass claims and their
  statuses, the sentences sent to revision, and the fate of every sentence at finalize
  (`kept`, `changed`, `merged` or `removed`, with the removal rule).
  `demo/drafting_gate_counts.py` reads it.
- The Smart Search round log and the screening record give each query's OpenAlex total,
  sort and cap.
- Every agent model is built from `DEEPSEEK_BASE_URL` and `DEEPSEEK_API_KEY`, so another
  OpenAI-compatible endpoint can be configured; the `thinking` field is sent only to
  `api.deepseek.com`. README "Substituting another model" lists the steps.
- The verification toast shows the four record statuses and a failed-lookup count.
- The Smart Search panel labels every backend stop reason, the screening panel labels
  every needs-review reason, and the Smart Search panel and paper card strings come from
  the English and Chinese message catalogs.

### Changed

- OpenAlex search ranks by relevance by default. `SEARCH_SORT` (`relevance` or
  `cited_by_count`) and `SEARCH_PER_QUERY_CAP` (default 25) are settings. Citation lists
  keep citation order.
- The second-pass judge's stage budget grows with the number of candidates:
  `SCREENER_SECOND_PASS_WAVE_SECONDS` (90) for each wave of concurrent calls, from a floor
  of `SCREENER_SECOND_PASS_STAGE_BUDGET_SECONDS` (1800) up to
  `SCREENER_SECOND_PASS_STAGE_BUDGET_MAX_SECONDS` (10800).
- The first PDF download attempt sends the application's identity (`DeepResearch/2.0`),
  the User-Agent the OpenAlex and Unpaywall clients send; the two retries send a
  browser-like User-Agent.
- The backend image is built on `python:3.12-slim-bookworm`.
- `evaluation/README.md` states which sets each prompt was developed on and the role of
  every evaluation set.

### API

- `overall_status` takes the values `record_verified`, `metadata_mismatch`,
  `doi_not_found` and `no_doi`, in place of `pass`, `warning`, `fail` and `no_doi`. It is
  `null` when the Crossref lookup failed. `pass`, `warning` and `fail` are not accepted
  as aliases.
- The verification job result reports `record_verified`, `metadata_mismatch`,
  `doi_not_found` and `no_doi` in place of `passed`, `failed` and `warnings`, plus the
  count of failed lookups, `lookup_failed`.

### Fixed

- A Crossref error or timeout is reported as a failed lookup, not as "DOI not found".
- A screening batch that fails is retried in halves, and a failing half one record at a
  time, before any record is marked `unscreened`.
- A sentence with one citation whose proposition leaves unverified text before the
  citation is verified as a whole sentence.
- Under a staged protocol, a Smart Search round that finds a new full-text candidate is
  not counted as a dry round. A failed query generation is retried once.
- Token counts are kept for replies that carry reasoning details.
- A claim whose verification ended in an error is verified again after revision.
- Revision notes the writer appends after the section text are removed. A "Notes on"
  header is cut only when it names revisions or is followed by bullet lines only.
- The title-echo removal count counts one per removed sentence.

### Removed

- The unused `VerificationReport` schema.
