# ScholarRAG evaluation harness

This folder holds the reproducible evaluation of ScholarRAG's LLM components. It measures
them with numbers derived from public datasets and committed result files:

* **E1 - screening performance vs human labels**: the unchanged production title/abstract
  screener (`app.agents.relevance_screener_agent.screen_papers`) is run over three SYNERGY
  systematic-review datasets and scored against the human screening decisions (recall,
  precision, F1, specificity, inclusion rate, WSS@R), next to include-all and TF-IDF baselines.
* **E1 - reproducibility**: every dataset is screened twice (runs A and B, temperature 0);
  percent agreement and Cohen's kappa between the two runs are reported, and every call's
  model, system fingerprint, response id, prompt version and token counts are recorded.
* **E1 - cost and latency**: per-run token totals, list-price cost (tiered by call time) and
  batch latency statistics.
* **E2 - claim verification**: the unchanged production claim-verification agent on the
  SciFact dev set and on a 60-item humanities/social-science full-text set, next to a lexical
  baseline (section "Claim verification (E2)" below).
* **E2 - claim-verification labels**: on the constructed and real-claims sets, the reference
  labels are the blind human labels (Table E2-j), the majority verdict of three labellers who
  saw only the claim and the source text (section "Claim-verification labels (v6)" below);
  SciFact's own published labels are unaffected.

Nothing in `evaluation/` is imported by the product. The scripts import production code by
adding `backend/` to `sys.path` and calling the public functions unchanged.

## Layout

```
evaluation/
  README.md                this file
  common.py                pure helpers: metrics, kappa, WSS, JSONL resume, price table, protocols
  ruff.toml                lint config for the whole tree
  .venv/                   evaluation-only interpreter (gitignored)
  screening/
    fetch_synergy.py       SYNERGY dataset -> data/<id>.jsonl + data/<id>.fetch.json (network, no LLM)
    run_screening.py       runs A/B of the production screener (LLM; system python)
    baselines.py           include-all and TF-IDF (k matched to the LLM inclusion count)
    wos_gate_effect.py     recall ceiling of the optional WoS venue gate (licensed CSVs, not shipped)
    spot_check_hydration.py  seeded sample of title-only hydration matches + Crossref record (spot-check judged by an automated pass, not the authors)
    summarize.py           tables E1-a..d, false-negative lists, figure4_screening.json
    blind_screening_scores.py  scores the three blind screening workbooks against the key;
                           writes results/blind_round/ (scores, report, per-record file)
    protocols/<id>.json    research question + criteria transcribed from each source review
    protocols/README.md    protocol schema, provenance rules, label_field policy, record order
    data/                  fetched datasets and dry-run output (gitignored)
    results/               committed run files, meta, baselines, gate effect, summaries;
                           see "Results directories" below
  claims/
    fetch_scifact.py       SciFact release tarball -> data/ (network, no LLM)
    run_scifact.py         runs A/B of the production verifier on the 340 SciFact dev pairs
    build_hss_set.py       acquires 21 OA applied-linguistics papers, builds the 60-claim HSS set
    run_hss.py             runs A/B of the production verifier on the HSS set
    baseline_lexical.py    lexical-overlap baseline (--set scifact | hss)
    verify_common.py       shared runner: production/dry-run verifier, resume, retry, meta
    summarize.py           tables E2-a..c, figure4_claims.json
    freeze_v6.py            replays every cached model answer under results/v6/inputs/
                           through the guard set at HEAD (no model call); writes results/v6/
                           and FREEZE_DIGESTS_v6.md
    human_review_labels.py  the three blind labellers' majority label per claim item,
                           inter-rater agreement, and v6 scored against that label; writes
                           results/v6/human_labels_blind.json, human_review_scores_blind.json
    label_sets.py          the verifier scored against the blind label set and the construction
                           rule; writes results/v6/label_sets.json, label_sets.md
    FREEZE_DIGESTS_v6.md    digests for the guard-7 replay; see "Claim-verification
                           labels (v6)" below
    hss_sources.json       a smaller, 10-paper source list, not the set results/v6/ scores
    hss_claims.jsonl       a smaller, 30-item claim set, not the set results/v6/ scores
    hss_test_v3_sources.json   the 21 papers results/v6/ scores against (DOI, journal, ISSN,
                           OpenAlex id, licence where recorded, access date)
    hss_test_v3_claims.jsonl   the 60 committed items results/v6/ scores; hss_test_v3_claims.build.json = build provenance
    hss_veto.json          vetoed-sentence list assembled by an automated review pass, not the authors; honoured by build_hss_set.py
    annotation/            earlier development labels (a development aid, not a reference); kept in the development repository, left out of the release archive
    data/                  SciFact files, full-text cache, dry-run output (gitignored)
    results/               committed run files, meta, baselines, summaries;
                           the result of record is v6/, see "Results directories" below
  tests/                   pytest suite; no network, no LLM
```

## Results directories

`screening/results/v3/` and `claims/results/v6/` are each the one result of record for their
evaluation, and every script's own `RESULTS_DIR` default already points at it, so the
commands below need no explicit `--results-dir` unless a different directory is wanted.

`screening/results/v3/` (screener prompt `SCREENER_PROMPT_VERSION`; the anchor ledger, the
title-only TOPIC exclude, the full-text-to-confirm queue routing, the type/table-of-contents
demotions and the inclusion-only second pass; the prompt value and the freeze record are in
`evaluation/screening/FREEZE_v3.md`) is the
screening result of record, over the three datasets in "Datasets and licences" above.
`run_screening.py`, `baselines.py`, `wos_gate_effect.py` and `summarize.py` all default
`--results-dir` to it.

`claims/results/v6/` (verifier prompt `CLAIM_VERIFICATION_PROMPT_VERSION`, `GUARD_DIGEST`,
`QUOTE_RELOCATION_VERSION`, `VERIFICATION_POLICY_VERSION`; their values are in
`evaluation/claims/FREEZE_DIGESTS_v6.md`) is the claim-verification result of record.
`results/v6/` is a deterministic replay of the stored model answers through the guard
set shipped at HEAD; no new model call was made to produce it. `verify_common.py`,
`baseline_lexical.py` and `summarize.py` all default `--results-dir` to it.

## Setup

Two interpreters are used (see "Interpreters and working directory" below); both are
Python 3.13 in this repository, though any recent Python 3 should work.

1. Evaluation-only interpreter (`evaluation/.venv`, gitignored, stdlib + `httpx` +
   `scikit-learn` + `pytest` + `ruff`):

   ```
   python -m venv evaluation/.venv
   evaluation/.venv/Scripts/python -m pip install -r evaluation/requirements.txt
   ```

   (POSIX: `evaluation/.venv/bin/python`.) `evaluation/requirements.txt` pins the versions
   this harness was built and tested against, including `pytest` and `ruff` so the test suite
   runs from this interpreter without touching the system one;
   `pip install httpx scikit-learn pytest ruff` also works if pinning is not needed.
2. System interpreter, for the scripts that call the production backend
   (`run_screening.py`, `claims/run_scifact.py`, `claims/run_hss.py`,
   `claims/build_hss_set.py`): install the backend's own dependencies with
   `pip install -r backend/requirements.txt` (repository root). These scripts `chdir` into
   `backend/` at import time (see "Working-directory rule" below) and need
   `DEEPSEEK_API_KEY` in the repository-root `.env` for anything beyond `--dry-run`.

Every command below is written for Windows (`evaluation/.venv/Scripts/python`); on
POSIX (Linux/macOS) replace every `\.venv/Scripts/python` with `.venv/bin/python` and every
other path separator is already POSIX-compatible.

## Interpreters and working directory

| Script | Interpreter | Why |
|---|---|---|
| `screening/fetch_synergy.py`, `baselines.py`, `wos_gate_effect.py`, `spot_check_hydration.py`, `summarize.py`, `claims/fetch_scifact.py`, `baseline_lexical.py`, `claims/summarize.py`, `claims/scifact_published_form.py` | `evaluation/.venv/Scripts/python` (or system `python`) | httpx / scikit-learn / stdlib only |
| `screening/run_screening.py`, `claims/run_scifact.py`, `claims/run_hss.py`, `claims/build_hss_set.py` | system `python` (3.13) | need the backend's pydantic-ai / pydantic-settings |
| `tests/` | either; the three backend parity tests run only under system `python` (3.13) with `backend/requirements.txt` installed, and are skipped in `evaluation/.venv` | `cd evaluation && python -m pytest tests -q -p no:cacheprovider` |

Run `claims/human_review_labels.py --tag blind` after `claims/summarize.py`, then `claims/label_sets.py`: `summarize.py` rewrites `summary.json` and `summary.md` without the Table E2-j block that `human_review_labels.py` folds in.

`python claims/scifact_published_form.py` writes Table E2-k (`results/v6/scifact_published_form.md` and `.json`); `--check` exits 1 when they are out of date.

**Working-directory rule.** `backend/app/config.py` builds its `Settings` with
`SettingsConfigDict(env_file=".env")`, i.e. relative to the *current* directory, and rejects
unknown keys; the repository-root `.env` carries deployment-only keys, so `import app.config`
from the repository root fails with a pydantic `ValidationError`. Every production-backed
script therefore (1) resolves all path arguments to absolute paths at parse time
(`common.resolve_path_args`), (2) calls `common.add_backend_to_path`, which puts `backend/` on
`sys.path` **and `os.chdir`s into it**, and (3) imports the settings through
`common.import_backend_settings`, which turns any failure into
`SystemExit("backend settings failed to load from <cwd>: ...")`. The commands below can be
launched from the repository root as written; relative `--results-dir` etc. are interpreted
relative to the directory you launch from.

**Real, paid runs are committed.** `screening/results/v3/` and `claims/results/v6/` hold the
real, paid runs of the production screener and verifier; every performance figure in
`results/v3/summary.md` and `results/v6/summary.md` comes from those runs, not from the
`--dry-run` stand-in (Tables E1-c and E2-c give their cost and latency).

## Paid runs: the cost gate

**Every command that is not `--dry-run` spends money the moment it starts.** The merged
production interface is on this branch and `DEEPSEEK_API_KEY` is read from the repo-root
`.env`, so `run_screening.py`, `run_scifact.py` and `run_hss.py` are live. They therefore
refuse to start (exit status 3) unless `--confirm-cost` is given; before exiting they print
the number of batches / model calls they would make and the list-price upper bound
(`run_screening.cost_upper_bound`: 2,000 input + 1,000 output tokens per batch;
`verify_common.cost_upper_bound`: 2,600 / 27,000 input + 1,000 output tokens per SciFact /
HSS call, all at the peak cache-miss tariff). `--limit` does **not** lift the gate: a
`--limit 30` smoke run is a paid run and needs the flag too. Recommended order for every
runner: (1) `--dry-run` (no LLM, writes under `data/_dryrun/`), (2) `--limit 30
--confirm-cost` and check `model_reported`, `temperature` and `latency_s` in the meta file,
(3) the full run with `--confirm-cost`.

## Testing without an LLM

No test and no `--dry-run` invocation contacts an LLM or the network. `run_screening.py
--dry-run` swaps the production screener for a deterministic keyword stand-in and writes to
`screening/data/_dryrun/results/` so the committed `results/` folder is never touched; the
unit tests patch the screener boundary (`main_async(args, screener=...)`) and the HTTP
boundary (`fetch_with_retries`). `run_screening.py` refuses to start against a backend whose
`screen_papers` does not return `ScreeningBatchResult`, and exits
with status 2 if the provenance reports a temperature other than 0.0 (override with
`--allow-nonzero-temperature`). `DEEPSEEK_API_KEY` is exported from the repo-root `.env` at
run time and never printed or written. The claims runners have the same `--dry-run`
(lexical stand-in) and the same guards. Latency is measured by `common.Stopwatch`, whose
`seconds` is a live property (it reports the elapsed time both inside and after the
`with` block); the tests drive both runners with a screener/verifier that sleeps and assert
the recorded `latency_s`.

## Datasets and licences

| Dataset | Domain | Records / included | Protocol gold label (Table E1-a) | Licence |
|---|---|---|---|---|
| `Nagtegaal_2019` (asreview systematic-review-datasets v1 index, the predecessor of SYNERGY) | public administration / behavioural science | 2,008 unique / 101 final, 389 title-abstract (2,019 rows as exported, 11 listed duplicates) | `label_abstract_screening` | CC0 |
| `van_de_Schoot_2017` (asreview systematic-review-datasets v1 index, the predecessor of SYNERGY) | psychology (PTSD trajectories) | 5,782 unique / 38 final, 356 title-abstract (6,189 rows as exported, 407 listed duplicates) | `label_abstract_screening` | CC-BY 4.0 |
| `Smid_2020` (SYNERGY v2) | social-science methodology (SEM simulation) | 2,627 / 27 final | `label_included` | CC0 (SYNERGY collection) |

Final inclusions (`label_included`) are the primary recall basis for all three datasets.
A row whose `duplicate_record_id` is set is dropped in favour of the record it names.

SYNERGY: De Bruin et al. 2023, DOI 10.34894/HE6NAQ (collection licence CC0; per-dataset
licences from the v1 index). Files are downloaded from the asreview GitHub raw endpoints;
nothing is redistributed here. Route v2 datasets are de-duplicated by OpenAlex id and rows
without any identifier are dropped (`<id>.fetch.json` records the counts). Route v1 datasets
are *hydrated* for the WoS gate analysis: every record with any positive label
(`--hydrate included`) is looked up by DOI, then by exact normalised title, in OpenAlex or -
when the shared-IP OpenAlex daily budget is spent - in Crossref (`--lookup crossref`); the
service, date and resolution counts are recorded in `<id>.fetch.json` and in the protocol's
`dataset_source.hydration`. Hydration never changes title or abstract text. **Title-only
matches carry a same-title risk** (a comment, reprint, erratum or conference abstract that
repeats the title would attribute a wrong ISSN): a title match must therefore be within
+-1 year of the export's year when the export has one (`match_method = title_exact_year`;
van_de_Schoot_2017 has a year for 6,173 records, Nagtegaal_2019 has none), and hits in
re-publishing series (`fetch_synergy.is_reprint_venue`: "Yearbook of ..." container titles)
are skipped. A malformed export DOI (`fetch_synergy.is_valid_doi` false, e.g.
`10.1037.a0037593`) is replaced by the Crossref DOI of the title-matched work and kept as
`doi_export`. The committed counts come from one hydration run per dataset under exactly
these rules (van_de_Schoot_2017: 112 by DOI + 219 by title and
year = 331/388 included records resolved, 42/43 final inclusions; Nagtegaal_2019 297/392,
title only; these are hydration counts on the rows as exported. `wos_gate_effect.py` counts a
deduplicated dataset on its deduplicated records, the basis of every other table, so
van_de_Schoot_2017's gate row covers 38 final inclusions of which 37 carry an ISSN). Two
van_de_Schoot_2017 records (349, 899) have a title-matched Crossref work whose year lies 2
and 5 years from the export year; the year rule leaves them unresolved. A
seeded random sample of 20 title matches per dataset was read record by record against the
matched Crossref record (`spot_check_hydration.py --judgements ...`; per-record
`judgement` / `judged_by` / `judged_on` in the committed
`screening/protocols/spot_checks/<id>.spot_check.json`, summary in each protocol's
`dataset_source.hydration.spot_check`): 20/20 and 20/20 correct under the reprint-venue
rule (it skips series such as *Yearbook of Psychiatry and Applied Mental Health*, which
reprint papers under their original titles). 20/20 is a sample, not a census: its
95 % Wilson interval is [0.839, 1.000], so up to about one in six of the 297
Nagtegaal_2019 title-only matches (and of the 219 van_de_Schoot_2017 title-and-year
matches) could still be a same-title mismatch, an error the E1-d intervals do not carry.
The spot-check judgements were produced by an automated pass and have not been verified by
the authors of this software.

**Label policy.** The evaluated task is title-and-abstract screening, and final inclusions
(`label_included`) are the primary basis for recall in all three datasets. The
title-and-abstract decision (`label_abstract_screening`, the human screeners' decision) is
reported beside them in Table E1-f, split into final and non-final inclusions. `Smid_2020`
has no title-and-abstract label, so Table E1-f says so and its precision is a lower bound
that `summarize.py` states. Records without an abstract are screened on the title alone (the
product shows "(no abstract)"); their share is reported per dataset and among the false
negatives, and records with neither title nor abstract are counted separately (`has_title`,
"Missing title (n)" in Table E1-b; `Smid_2020` has 33 such works, none of them included). The
production prompt builder truncates every abstract to 10,000 characters -- this is the
product's behaviour and is evaluated as is.

The gold labels are the source reviews' own screening decisions as distributed by
SYNERGY, not a re-annotation for this evaluation; SYNERGY publishes no per-record
inter-screener agreement, so records counted here as LLM false positives or false
negatives include human label noise and review-specific screening thresholds, and this
note is printed under Table E1-a (`summarize.label_field_note`). `van_de_Schoot_2017`'s
protocol (`inclusion_criteria[4]`) records a deliberately over-inclusive title/abstract
stage ("if there is any doubt the study is included"), so precision is not compared
across datasets here; note that this criterion is also passed to the screener in the
prompt (`protocols/README.md`: the criteria lists go unchanged to `screen_papers`), so
it raises this dataset's recall as well, and recall is read as a capability number only
within a dataset -- across runs A and B and against the baselines on the same records --
not as a ranking of the three datasets.

**Record order and resume.** `run_screening.py` shuffles every dataset deterministically
before batching (`random.Random(f"{dataset}:{seed}")`, `--record-order-seed` default
20260902, stored as `record_order_seed` in the meta file). SYNERGY exports list the
inclusions first, so file-order batches of 10 would be label-sorted, which production never
sees. The order is identical for runs A and B and across resumes; `--limit` applies after the
shuffle. Resume is at **record** level: batches are rebuilt from the same order and only the
records of a batch that are not yet in the results file are sent, so a batch left half-done
by a `--limit` smoke run is completed with a smaller call and no record is ever re-sent or
re-billed. Rows carry a `call_id` shared by the rows of one API call; the meta file counts
`n_calls` next to `n_batches`, and tokens, cost and latency are aggregated per call.

## Metrics

With TP/FP/TN/FN counted on the screened records (records the screener could not process are
excluded and reported as "unscreened"), N = TP+FP+TN+FN:

* recall = TP / (TP+FN); precision = TP / (TP+FP); F1 = 2PR / (P+R); specificity = TN / (TN+FP);
  inclusion rate = (TP+FP) / N; prevalence = (TP+FN) / N.
* WSS@R = (TN+FN)/N - (1-R), work saved over sampling at recall R (Cohen AM et al. 2006,
  J Am Med Inform Assoc 13:206-219, DOI 10.1197/jamia.M1929). For a fixed binary decision it
  is reported at the achieved recall and, when recall >= 0.95, at R = 0.95; for the TF-IDF
  ranking WSS@95 is computed by screening in descending similarity order.
* Cohen's kappa = (po - pe) / (1 - pe) between runs A and B on records screened in both
  (Cohen J 1960, Educ Psychol Meas 20:37-46, DOI 10.1177/001316446002000104). When pe = 1
  (both runs constant and identical) kappa is undefined: the harness stores `null`, sets
  `agreement_AB.kappa_undefined`, and the tables print `-` with a footnote.
* **Padded decisions.** Production pads any decision the model failed to return with
  INCLUDE and the visible reason `"no decision returned"`. The harness stores those rows as
  production returned them, flags them (`padded_include`), counts them (`n_padded_include`)
  and reports the metrics twice: as returned (Table E1-a) and with padded rows treated as
  unscreened (Table E1-b, `metrics_padded_as_unscreened`). `figure4_screening.json` carries
  the padded-as-unscreened variant as a "LLM run X (padded as unscreened)" row whenever such
  rows exist, for programmatic use; Fig. 4 itself does not plot a fifth bar series for it and
  instead states the padded-as-unscreened recall/precision in its footnote, sourced from that
  same row.
* The TF-IDF baseline uses cosine similarity between each record (title + abstract) and the
  **research question** (`--query rq`, the default); the
  variant with the inclusion criteria appended (`--query rq+criteria`) is available and the
  choice is recorded as `query_mode` in `<id>_baselines.json` and in the summary label. It
  includes exactly as many records as the LLM run (k matched) and is evaluated on the records
  the LLM actually screened (`predicted` not null), so precision/recall are directly
  comparable; include-all has recall 1 by construction. `--k-basis screened_in` matches k to
  the run's retained (INCLUDE or NEEDS_REVIEW) count instead of its INCLUDE count, the basis
  `results/v3/<id>_baselines.json` uses because all three of its protocols name a full-text
  inclusion criterion, which leaves the INCLUDE count at zero.
* **No confidence intervals.** All figures in Tables E1-a/b/d, and every column of Table
  E1-e except retained recall's own 95 % Wilson interval, are point estimates on the stated
  n with no confidence interval reported; on the 60-item HSS set (E2-b) the 95 % Wilson
  interval of an accuracy of 0.917 is about +-0.07, and Smid_2020 (27 included records) is
  also a small dataset, so a difference of a few points between systems, datasets or runs A
  and B is not interpreted as a difference.

### The shipped screening rule

The screener defaults to INCLUDE: a record is excluded only when the shown title and
abstract themselves fail a numbered criterion, and an EXCLUDE must name that criterion and
quote a phrase copied character for character from the shown text; a record the shown text
cannot decide, and a criterion that can only be judged from the full text, is NEEDS_REVIEW
rather than a soft EXCLUDE. Two further checks run before a record is treated as a genuine
INCLUDE. First, a deterministic check: a record whose source marks it a non-article type
(a book, a reference entry, a table of contents, and similar) is routed to NEEDS_REVIEW
without another model call. Second, only the records that survive the first check -- never
the whole batch -- reach the same model the batch pass uses, but with reasoning left on (at
effort high, the provider's own documented default since the request leaves the effort
unset) instead of disabled, and asked directly whether the shown text establishes
the population, the outcome and the study type
the review's own criteria name; any answer of "not established" also routes the record to
NEEDS_REVIEW. A record standing as INCLUDE during the search is provisional until this
check runs: the second pass itself runs only once, for the whole job, after every search
round has finished (not once per round, and not once per original batch of ten), over every
provisional INCLUDE the whole job produced, so a live search's own many rounds are never
slowed by the judge and a round's own stopping decision sees a provisional INCLUDE exactly
as it always did. Judged together as one concurrent stage, five records per call, up to
`screener_second_pass_concurrency` (default 8) calls in flight at once; a call that fails or
times out routes only its own small chunk to NEEDS_REVIEW with `second_pass_unavailable`.
The stage has its own wall-clock budget, separate from the search's own time budget, and the
budget grows with the number of candidates (`second_pass_stage_budget_seconds` in
`app.agents.relevance_screener_agent`): the stage needs `ceil(chunks / concurrency)` waves,
and each wave is given `screener_second_pass_wave_seconds` (default 90s). The budget is never
below `screener_second_pass_stage_budget_seconds` (default 1800s, which covers about 800
candidates) and never above `screener_second_pass_stage_budget_max_seconds` (default
10800s). Once the budget has elapsed the stage launches no new call; a call already in
flight is still awaited (at most 420s per call), and a chunk not yet started is routed to
NEEDS_REVIEW with `second_pass_unavailable` for a human to read. A normal run therefore
judges every candidate, and a stuck stage still ends. The evaluation harness
(`run_screening.py`) passes the 1800s floor unscaled; no benchmark run of record reaches the
second pass, so the floor decides none of them. Every call's own
provenance record carries the model DeepSeek actually served and its system fingerprint,
whichever model was configured. Every one of these checks
can only move a record from INCLUDE to NEEDS_REVIEW -- none of them can produce an EXCLUDE,
and none of them can promote a record into INCLUDE. One structural consequence follows from
this rule on its own: when a review's own protocol defers even one inclusion criterion to
full-text reading, the criterion cannot be confirmed from a title and abstract, so no record
can ever clear it at this stage -- the screener queues such a record for a human to read
rather than guessing. This is by design: the screener prioritises routing a genuinely
undecidable record to a reviewer over shipping a confident-looking guess. As encoded in
`screening/protocols/`, each of the three reported datasets places at least one inclusion
criterion at the full-text stage, so in both of their runs no record reaches the second
pass, and the reading saved comes only from outright exclusions.

The model also returns a population/subject/outcome anchor ledger (a verbatim quote or an
explicit absence for each slot) on every INCLUDE, but the guard's own check against that
ledger ships off: no production or harness caller passes `anchored_slots` to
`apply_decision_guard`, so it defaults to empty and never demotes an INCLUDE on that basis.
The inclusion-only second pass above is the check the software applies to an INCLUDE's grounding today; the
ledger is still recorded on every decision so a future run can turn the check on without a
further model call.

### Final-inclusion report (Table E1-e)

Table E1-a is scored on each dataset's own primary label. Table E1-e reports five figures
against the review's final inclusions specifically, on every dataset, regardless of which
label a dataset's other tables use as primary, because a screening pipeline's practical value
is what it does to the review's own inclusion set: **retained recall**, the share of final
inclusions the screener kept as INCLUDE or NEEDS_REVIEW (i.e. did not exclude outright), with
a 95 % Wilson interval; **screened-in share**, the fraction of the corpus routed to INCLUDE or
NEEDS_REVIEW; **reading saved**, work saved over sampling (Cohen et al. 2006) evaluated at
that retained recall rather than at the INCLUDE-only recall Table E1-a's own WSS columns use,
i.e. the share of the corpus the screener excluded outright less the share of final
inclusions it lost (1 minus retained recall), so it equals the excluded share only where
retained recall is 1; **auto-inclusion precision**, the share of INCLUDE decisions that are a genuine
final inclusion, with its own n, printed as "none, n = 0" when no record was auto-included at
all (the direct consequence of the routing rule above, on any protocol naming a full-text
inclusion criterion); and **queue precision**, the share of NEEDS_REVIEW rows that are a
genuine final inclusion, i.e. how often the records a reviewer actually reads contain one.
The table also reports the run-to-run agreement between A and B on the three-way INCLUDE/
EXCLUDE/NEEDS_REVIEW status (Cohen's kappa), once per dataset.

## ASReview LAB baseline

`screening/asreview_baseline.py` replays ASReview LAB (version 3.0.8, default model, one
relevant and one irrelevant prior record, seeds 1 to 15, stop after 100 consecutive
irrelevant records) on the same deduplicated records the screener scored, and counts the
records read to reach the screener's recall. ASReview lives in its own virtual environment
and is never installed into the evaluation interpreter.

```bash
python -m venv evaluation/screening/asreview/.venv
evaluation/screening/asreview/.venv/Scripts/python.exe -m pip install -r evaluation/screening/asreview/requirements.txt
cd evaluation/screening
python asreview_baseline.py --dataset all --seeds 1-15 --asreview-exe asreview/.venv/Scripts/asreview.exe --data-dir path/to/data
```

The aggregated numbers are in Table E1-i of `results/v3/summary.md`; this README states
none of them. Details: `screening/asreview/README.md`.

## Prices, cost and tokens

DeepSeek list prices (USD per 1M tokens) fetched on 2026-09-02 from
<https://api-docs.deepseek.com/quick_start/pricing> and stored in `common.DEEPSEEK_PRICES`:

| model | input, cache hit (off-peak / peak) | input, cache miss (off-peak / peak) | output (off-peak / peak) |
|---|---|---|---|
| deepseek-v4-flash | 0.007 / 0.014 | 0.22 / 0.44 | 0.66 / 1.32 |
| deepseek-v4-pro | 0.022 / 0.044 | 0.66 / 1.32 | 1.98 / 3.96 |

These are the prices used to compute every cost figure in this document; the provider's list
price read on 2026-10-26 is lower (see `README.md`'s requirements table), but the runs
recorded here were made and priced against the 2026-09-02 figures above.

Peak hours are 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday; all other hours are off-peak
(half price). The name `deepseek-flash` configured in the product (the provider's
name for the deployment behind the `deepseek-chat` alias) is priced as `deepseek-v4-flash`;
runs must confirm the served model from the `model_reported` column. Every call is
timestamped (`called_at`, ISO-8601 UTC) right before the request and priced with
`common.call_cost` in its own tier. The screening interface exposes only input/output token
totals (no cache-hit split), so all input tokens are billed at the cache-miss rate and the
screening cost is an **upper bound at list price** (`cost_basis` in the meta file); the claims
interface exposes `cache_read_tokens`, which are billed at the cache-hit rate. The served
model runs in thinking mode by default, so output tokens as reported by the API may include
reasoning tokens; they are recorded exactly as reported. `--price-input/--price-output` add a
flat estimate in `total_cost_flat` without replacing the tiered figure.

**Latency.** Latency medians and p90 are wall-clock per call (per batch for E1, per item for
E2) measured while up to `--concurrency` calls (default 8; production uses
`analysis_concurrency = 4`) were in flight, so they include provider-side queueing. The
concurrency is stored in every meta file and printed in Tables E1-c / E2-c.

**Cost and time.** The committed runs' actual cost and latency are the figures reported in
Table E1-c (`screening/results/v3/summary.md`) and Table E2-c (`claims/results/v6/summary.md`):
US$3.57 total for the six screening pass-1 runs (`evaluation/screening/FREEZE_v3.md` section
3) and US$0.58 total for the four SciFact/HSS runs (`evaluation/claims/FREEZE_DIGESTS_v6.md`).

## Command sequence (E1)

```
# data (network, no LLM). --lookup crossref when OpenAlex answers 429 (daily budget)
evaluation/.venv/Scripts/python evaluation/screening/fetch_synergy.py --dataset Nagtegaal_2019 --route v1 --hydrate included --lookup crossref
evaluation/.venv/Scripts/python evaluation/screening/fetch_synergy.py --dataset van_de_Schoot_2017 --route v1 --hydrate included --lookup crossref
evaluation/.venv/Scripts/python evaluation/screening/fetch_synergy.py --dataset Smid_2020 --route v2
# LLM runs: PAID (system python; DEEPSEEK_API_KEY from .env, never printed). Without
# --confirm-cost the runner prints the batch count and cost bound and exits 3.
# --prompt-version defaults to v3, the shipped prompt; --results-dir defaults to
# evaluation/screening/results/v3 (the directory of record), matching baselines.py/summarize.py/
# wos_gate_effect.py's own default, named explicitly below for clarity.
python evaluation/screening/run_screening.py --dataset <id> --run A --dry-run --results-dir evaluation/screening/data/_dryrun/results           # no LLM
python evaluation/screening/run_screening.py --dataset <id> --run A --limit 30 --confirm-cost --results-dir evaluation/screening/results/v3  # paid smoke
python evaluation/screening/run_screening.py --dataset <id> --run A --confirm-cost --results-dir evaluation/screening/results/v3
python evaluation/screening/run_screening.py --dataset <id> --run B --confirm-cost --results-dir evaluation/screening/results/v3
# --second-pass-model overrides the backend's own screener_second_pass_model default
# (deepseek-flash) for this run only; every run's own meta file records the model
# actually configured next to the model_reported/system_fingerprint DeepSeek served.
# repair batches that failed after --max-attempts (rows with predicted = null are re-screened)
python evaluation/screening/run_screening.py --dataset <id> --run A --retry-failed --confirm-cost --results-dir evaluation/screening/results/v3
# baselines, gate, summary
evaluation/.venv/Scripts/python evaluation/screening/baselines.py --dataset <id> --run A --results-dir evaluation/screening/results/v3
# --label-field label_included scores the gate on final inclusions, the basis of Table E1-d;
# without it the script takes each protocol's own label_field (the title-and-abstract label
# for Nagtegaal_2019 and van_de_Schoot_2017)
evaluation/.venv/Scripts/python evaluation/screening/wos_gate_effect.py --dataset <id> --label-field label_included --results-dir evaluation/screening/results/v3
evaluation/.venv/Scripts/python evaluation/screening/summarize.py --results-dir evaluation/screening/results/v3
```

Expected sizes per run (batches of 10): Nagtegaal_2019 202, van_de_Schoot_2017 619,
Smid_2020 263; two runs each. Runs are resumable at record level (re-run the same command:
only records missing from the results file are sent, a half-done batch is completed with a
smaller call, and the meta file counts `n_calls` next to `n_batches`); a batch that still fails after `--max-attempts` (default 3) is written with `predicted = null`
and counted as unscreened. Such rows are kept by a plain re-run; `--retry-failed` removes
them from the results file (atomic rewrite) and screens them again, and the meta file records
`retried_failed` (also per session). Smoke test without an LLM:
`python evaluation/screening/run_screening.py --dataset Nagtegaal_2019 --run A --dry-run --limit 30 --results-dir evaluation/screening/data/_dryrun/results`.

Outputs in `screening/results/v3/` (each script's own `--results-dir` already defaults there): `<id>_run<A|B>.jsonl` + `.meta.json`, `<id>_baselines.json`,
`<id>_wos_gate.json`, `<id>_false_negatives.md`, `summary.json`, `summary.md` (tables E1-a
performance, E1-b secondary, E1-c provenance/cost/latency, E1-d WoS gate),
`figure4_screening.json`. No categorisation file is written for a fresh run. `summarize.py`
reads a `<id>_fn_categories.csv` from the results directory when one is committed there and
then reports its category counts in `summary.md`; `results/v3/` ships none, so its false
negatives are published with the screener's own stated reason and no coded category.

The WoS gate analysis reads the four licensed Web of Science collection CSVs from the
repository root when present and writes aggregate counts only; it exits 0 when they are absent.
Table E1-d reports the gate's recall ceiling over the human-included records as an interval
`lower-upper` next to the resolution fraction (`ISSN/n`): a record with no ISSN has an
unknown venue, so the lower bound counts every unresolved record as outside WoS (in WoS /
all included) and the upper bound counts every unresolved record as inside WoS
((in WoS + unresolved) / all included); a fully resolved set prints a single value. The
share of *resolved* records only (in WoS / resolved) is reported alongside in parentheses as
a point estimate, not a bound, since it assumes the unresolved records are in WoS at the
same rate as the resolved ones. All three are stored in `summary.json`
(`wos_gate_table.share_lower_bound` / `share_resolved_only` / `share_upper_bound`) and as a
`"WoS gate"` row in `figure4_screening.json` (a deduplicated dataset's row counts its
deduplicated records). With the committed hydration the intervals over the final inclusions
are Nagtegaal_2019 0.683-0.921 (resolved-only 0.896; 69 of 101 in WoS, 77 resolved),
van_de_Schoot_2017 0.947-0.974 (resolved-only 0.973; 36/38, 37 resolved) and Smid_2020
0.963-1.000 (resolved-only 1.000; 26/27, 26 resolved). The table note states the same-title
risk of title-only matches.

## Claim verification (E2)

**Purpose.** Measure the production claim-verification agent
(`app/agents/claim_verification_agent.py`, prompt `CLAIM_VERIFICATION_PROMPT_VERSION`,
temperature 0.0) on (a) a public scientific benchmark and (b) a small humanities/social-science
full-text set built for this evaluation, and compare it with a lexical baseline. The harness
calls the unchanged production code path (`format_verification_prompt` ->
`agent.run(prompt, deps=AnalysisDependencies(...))` -> `provenance_from_run`) and records per
call the model the provider reported, its system fingerprint, response id, token counts
(input, output, cache-hit) and call time.

**SciFact (E2-a).** Wadden et al. (2020), *Fact or Fiction: Verifying Scientific Claims*,
EMNLP, DOI [10.18653/v1/2020.emnlp-main.609](https://doi.org/10.18653/v1/2020.emnlp-main.609).
Licence: claims CC BY 4.0; abstracts (S2ORC) ODC-By 1.0
(`https://github.com/allenai/scifact/blob/master/LICENSE.md`). `fetch_scifact.py` downloads
the release tarball (3,115,079 bytes), extracts it with a path-safe filter, verifies the line
counts (dev 300 / train 809 / test 300 / corpus 5,183) and writes `data/scifact.fetch.json`.
The dev set's 300 claims cite 340 claim-document rows (138 SUPPORT, 71 CONTRADICT,
131 NOT_ENOUGH_INFO); each row is one item whose single "full-text chunk" is the abstract's
sentences joined by one space. The 340 rows cover 339 distinct claim-document pairs: dev claim
1245 lists document 7662395 twice in its own `cited_doc_ids`, so `build_items` emits the item
twice (`item_id` "1245:7662395" appears twice in `scifact_run<A|B>.jsonl`) and both copies are
sent to the model, billed and counted in every metric above (both copies score `unsupported`
in both runs, so the numeric effect is a rounding-level shift in run-to-run agreement).

*Scoring map.* SUPPORT -> `verified`; CONTRADICT and NOT_ENOUGH_INFO -> `unsupported`. The
agent may also answer `needs_nuance`, `no_full_text` or fail (`error`); these are never a gold
class. In the *strict* table they count as a miss for the gold class and never as a hit
(`common.per_class_prf`); `needs_nuance` answers are additionally reported by gold class. The
*lenient* view is binary: `verified` vs everything else, computed over model-answered rows
only (error rows are excluded from the confusion counts and reported as `n_errors`, so a
failed call is never a "correct rejection"; the HSS `verified_binary` view does the same).
Both runs (A, B) use identical inputs; A/B agreement pairs only items that carry a model
decision in both runs (deterministic `no_full_text` items and error rows are excluded and
counted as `n_excluded_deterministic` / `n_excluded_error`) and is reported as percent
agreement and Cohen's kappa (status level and binary); when both runs are constant and
identical kappa is undefined and printed as `-` with the same footnote as in E1.

*Label-mapping sensitivity (Table E2-f).* The scoring map above is a choice: collapsing
CONTRADICT and NOT_ENOUGH_INFO onto one `unsupported` class discards the distinction between
a refuted claim and an unevidenced one, so `claims/summarize.py` rescores every SciFact run
under three mappings and reports per-class P/R/F1, macro-F1, CONTRADICT recall and the count
of gold-CONTRADICT rows predicted `verified` for each: *strict* (the mapping above),
*lenient* (a predicted `needs_nuance` counts as `verified`, everything else unchanged), and
*three-way* (available only when a row carries the per-assertion `verdict` field), which splits a predicted `unsupported` row by whether any
assertion was itself verdict `contradicted` and scores CONTRADICT against that split bucket
instead of the class it otherwise shares with NOT_ENOUGH_INFO. The sentence the manuscript
may state: "Mapping choice moves the headline numbers only at the margin the model's own
needs-nuance and per-assertion signals create; CONTRADICT recall and the count of
gold-CONTRADICT rows predicted verified are the figures a reviewer should read as the safety
check, not macro-F1 alone, and both are reported for every mapping in Table E2-f."

*Quote fidelity.* Share of `verified` answers whose `evidence_quote` is a verbatim substring
of the chunk text after whitespace normalisation (case-sensitive); a case-insensitive share
and the share of null quotes are reported alongside.

**HSS set (E2-b).** 60 claims over 21 open-access applied-linguistics articles
(`hss_test_v3_sources.json`: DOI, journal, ISSN, OpenAlex id, licence where recorded, access
date) drawn from Eurasian Journal of Applied Linguistics (4), Colombian Applied Linguistics
Journal (4), Studies in Second Language Learning and Teaching (3), Journal of Language and
Education (3), Technology in Language Teaching and Learning (2), TESL-EJ (2), TESL Canada
Journal (1), JALT CALL Journal (1) and Apples: Journal of Applied Language Studies (1). Papers
were acquired with the production pipeline (`UnpaywallClient.lookup` -> `fetch_pdf_from_url`
-> `extract_text_from_pdf` -> `chunk_text`; kept only with >= 15,000 characters and >= 3
chunks). Candidate sentences are ranked deterministically
(`common.select_candidate_sentences`, results/discussion/conclusion chunks first) and assigned
round-robin over papers to six construction rules, one claim per sentence, no sentence reused
(`build_hss_set.py`):

| rule | n | construction | expected status |
|---|---|---|---|
| verbatim | 8 | claim = sentence | verified |
| paraphrase | 8 | fixed ordered substitution table (>= 1 substitution; reporting verbs, connectives and generic nouns only; technical terms are never substituted) | verified |
| altered | 18 | direction flip, first number x2 (percentages capped at 99), or quantifier flip | unsupported |
| over_specified | 10 | an additional, unsupported modifier appended to a sentence that already reports an empirical finding | needs_nuance |
| wrong_paper | 8 | sentence from paper X, chunks of paper Y | unsupported |
| no_full_text | 8 | sentence with no chunks | no_full_text (deterministic; no model call) |

`needs_nuance` answers on paraphrase items are reported in their own column of Table E2-b and
are not scored as correct. Sentences that are not claims (PDF artefacts, reference-list
entries, section headings, questions, attributed findings from another study, and quoted
passages) are rejected by rule before assignment; the committed set (`hss_test_v3_claims.jsonl`,
`hss_test_v3_claims.build.json`) is the output of these rules. Labels are by construction, not
by expert annotation.

An earlier set of model labels for these 60 items (`claims/annotation/`) was used during development. It is a development aid, not a reference: these are not expert human annotations, no reported figure is scored against them, and the folder is kept in the development repository and left out of the release archive. The reference labels are the blind human labels (Table E2-j, `results/v6/human_labels_blind.json`; see "Claim-verification labels (v6)" below).

*Curation.* The 60 items were read by an automated review pass, not by the authors of this
software, and the authors have not verified this set. `hss_veto.json` is a safety net assembled by that same automated review, honoured by
the builder and recorded (with reasons) in `hss_test_v3_claims.build.json`. Every item except the
eight `no_full_text` ones is verified with *all* chunks of its paper, in production order.
`hss_test_v3_claims.jsonl`, `hss_test_v3_claims.build.json`, `hss_test_v3_sources.json` and
`hss_veto.json` are committed; the full-text cache (`data/hss_test_v3_fulltext/`) is not.

**Lexical baseline.** `baseline_lexical.py`: maximum token-Jaccard between the claim and any
chunk sentence, `>= 0.5` -> `verified`, otherwise `unsupported`; items without chunks ->
`no_full_text`. `--set scifact` (default; `--match-run` restricts it to the items of an LLM
run file) writes `results/v3/scifact_baseline.json` (the default `--results-dir`); `--set hss`
scores the HSS items exactly as `run_hss.py` loads them and writes
`results/v3/hss_baseline.json` with per-rule accuracy and the
binary verified metrics (Table E2-b, `figure4_claims.json`); the binary view is computed over
the items with chunks only, the no-chunk items being counted as `n_excluded_deterministic`,
so that it shares the denominator of the LLM rows (n = 25). On the HSS set the baseline marks
single-word alterations `verified` (Jaccard close to 1), which is the point of including it.

**No confidence intervals.** All figures in Tables E2-a/b/c/d are point estimates on the stated
n with no confidence intervals; E2-b's accuracy is on n = 60 (binary view n = 52, 16
positives) and the 95 % Wilson interval of an accuracy of 0.917 on n = 60 is about +-0.07
(Table E2-i), so a difference of a few points between the LLM run and a lexical baseline, or
between runs A and B, is not interpreted as a difference.

**Cost and provenance.** Meta files record `model_configured` (`deepseek-flash`), the distinct
`model_reported` values the API returned (expected `deepseek-flash`, priced as
`deepseek-v4-flash`), system fingerprints,
`temperature`, `prompt_version`, `concurrency`, token totals including cache-hit tokens,
`retried_failed`, and `total_cost` = sum over model-answered rows of
`common.call_cost(model_reported, called_at, input, output, cache_read)`. Deterministic
(`no_full_text`) and error rows carry no tokens and no cost. Error rows
(`predicted_status = "error"` after `--max-attempts`) are kept by a plain re-run and
re-attempted with `--retry-failed`.

**Commands**

```
evaluation/.venv/Scripts/python evaluation/claims/fetch_scifact.py
python evaluation/claims/build_hss_set.py --skip-fetch          # rebuild from the cache (no network)
python evaluation/claims/build_hss_set.py                       # full acquisition: Unpaywall/Crossref/PDF, no LLM
python evaluation/claims/run_scifact.py --run A --dry-run                    # no LLM
python evaluation/claims/run_scifact.py --run A --limit 30 --confirm-cost    # PAID smoke
python evaluation/claims/run_scifact.py --run A --confirm-cost ; ... --run B --confirm-cost   # PAID
python evaluation/claims/run_hss.py --run A --confirm-cost ; ... --run B --confirm-cost       # PAID
python evaluation/claims/run_scifact.py --run A --retry-failed --confirm-cost  # repair error rows
evaluation/.venv/Scripts/python evaluation/claims/baseline_lexical.py --match-run evaluation/claims/results/v6/scifact_runA.jsonl
evaluation/.venv/Scripts/python evaluation/claims/baseline_lexical.py --set hss
evaluation/.venv/Scripts/python evaluation/claims/summarize.py
```

Every runner accepts `--dry-run` (lexical stand-in, results under `claims/data/_dryrun/results/`,
no LLM) and is resumable; without `--dry-run` a runner refuses to start unless `--confirm-cost`
is given (see "Paid runs: the cost gate"); `summarize.py --results-dir <dir>` writes `summary.json`,
`summary.md` (Tables E2-a/b/c) and `figure4_claims.json`.

### Additional SciFact train evaluation set (491 pairs) and title-only screening check

`claims/scifact_train_491.json` lists 491 SciFact train claim-document pairs outside the
development sample, sharing no claim or document with it and no document cited in SciFact dev.
The shipped verifier's run on them is in `claims/results/v6/scifact_train491/`
(`scifact-train_runA.jsonl`, `.meta.json`, `PROMPT.txt` and `summary.json`). Of the 206 SUPPORT
pairs, 87 are `verified` (strict recall 0.422, Wilson 95 % 0.357 to 0.491) and 166 are
`verified` or `needs_nuance` (lenient recall 0.806, 0.746 to 0.854). Of the 285 non-support
pairs (85 CONTRADICT, 200 NOT_ENOUGH_INFO), none is `verified` and 12 are `needs_nuance`.
There are no error rows.

```
python evaluation/claims/fetch_scifact.py
python evaluation/claims/run_scifact.py --split train --sample-file evaluation/claims/scifact_train_491.json --run A --dry-run                  # no LLM
python evaluation/claims/run_scifact.py --split train --sample-file evaluation/claims/scifact_train_491.json --run A --confirm-cost --results-dir <new dir>   # PAID
python evaluation/claims/summarize_train_sample.py --results-dir <new dir>     # rewrites summary.json
```

`screening/results/no_abstract/` holds the screening run (shipped protocols and prompt, run A)
on the 915 development records of `Fong_2021` (477) and `van_Dis_2020` (438) that carry no
abstract. One of the 38 inclusions among them is excluded by the title-only TOPIC rule (1 of
38, Wilson 95 % 0.005 to 0.135; `van_Dis_2020` 1 of 7, `Fong_2021` 0 of 31); the other 37 are
queued as NEEDS_REVIEW. 465 of the 915 records are excluded outright on TOPIC, 1 of them a
gold inclusion. `python evaluation/screening/summarize_no_abstract.py` rewrites `summary.json`.

### Prompts and the dev / test split

The claim-verification prompt used for every reported result is the one labelled
`CLAIM_VERIFICATION_PROMPT_VERSION`, run with the guard set, the quote relocation and the
verification policy labelled `GUARD_DIGEST`, `QUOTE_RELOCATION_VERSION` and
`VERIFICATION_POLICY_VERSION`; their values are in `evaluation/claims/FREEZE_DIGESTS_v6.md`.
The screening prompt used for every reported result is the one labelled
`SCREENER_PROMPT_VERSION`; its value is in `evaluation/screening/FREEZE_v3.md`.

Neither prompt was fixed on held-out data. The screening prompt was developed on two other
published reviews, `Fong_2021` and `van_Dis_2020`. The claim-verification prompt was
developed on the SciFact **train** split (120 claim-document pairs, stratified 40 SUPPORT /
40 CONTRADICT / 40 NOT_ENOUGH_INFO, `claims/scifact_train_dev120.json`) and on constructed
applied-linguistics claims outside the reported sets (`claims/hss_dev_claims.jsonl`,
`claims/hss_dev_band2_claims.jsonl`), and SciFact dev rows were seen during development.
The screener's design and the verifier's guards, quote relocation and quote-repair turn
were settled after the committed run rows of all three reported reviews, `Nagtegaal_2019`,
`Smid_2020` and `van_de_Schoot_2017`, and the verifier's misses on the 86 in-house test
items had been read. That design assigns `Nagtegaal_2019` criteria I1 and E1 and `Smid_2020`
criteria I4, E9 and E11 to the full-text stage. The inclusion judge's settings were chosen
on records of the demonstration topic. No reported screening or claim figure is a held-out
result. The verifier was frozen before any blind label was scored and was not changed after
the blind labels came back.

`results/v6/summary.md` and `results/v3/summary.md` are the results of record. Five further files hold reported figures: Table E2-k in `results/v6/scifact_published_form.md`, the per-sentence drafting-gate counts of the demonstration run in `demo/output/20261026-115827/drafting_gate_counts.json`, the blind screening check in `screening/results/blind_round/blind_screening_scores.md`, `claims/results/v6/scifact_train491/summary.json` and `screening/results/no_abstract/summary.json`.

## Human-review workbook

`evaluation/claims/export_review_sheet.py` builds an Excel workbook (`Guide`, `Review`,
`Model_labels`, `Sources`, `Provenance`, plus `Screening` when a screening record is
given and `Delivered` when a `delivered_evidence.json` is given) so a person can
countersign or override the frozen claim-verification and screening runs and judge the
final, delivered text a user actually receives. Interpreter: either the evaluation venv or
plain system python (`openpyxl`; system python is needed for a lone-carriage-return cell to
round-trip correctly, since the evaluation venv has no `lxml`); no backend import, no
network, no LLM call. See "Layout" and
"Results directories" above for the results directories a workbook is exported from.

**Frozen versions a workbook reports against.** The verifier prompt
`CLAIM_VERIFICATION_PROMPT_VERSION` (the cached model answers `results/v6/` replays, stored
under `results/v6/inputs/`; see "Results directories" above); the screener prompt
`SCREENER_PROMPT_VERSION`, the prompt `demo/expected/screening_record.json` was generated
against, the current production screening prompt, and the value this export checks with
`--screening-prompt-version-expect` (its value is in `evaluation/screening/FREEZE_v3.md`);
the code-level guards (`GUARD_DIGEST`), the quote-relocation step
(`QUOTE_RELOCATION_VERSION`) and the quote-repair turn (`QUOTE_REPAIR_PROMPT_VERSION`), run
under `VERIFICATION_POLICY_VERSION`, at the commit recorded on the workbook's own Provenance
sheet (`guard_commit`). The values of the claims constants are in
`evaluation/claims/FREEZE_DIGESTS_v6.md`. The exporter reads the verifier prompt version from
the results directory's own meta files rather than taking the caller's word for it, and
refuses (`--screening-prompt-version-expect`) a screening record whose own provenance carries
a different screener prompt.

**Export command**, a runnable template that builds a reviewer workbook for the claim
sets above and, when `--delivered-evidence` is given, adds a Delivered sheet for the
promoted run's own delivered text (the key csv is never sent to the reviewer):

```
cd evaluation
python claims/export_review_sheet.py \
  --items claims/hss_test_v3_claims.jsonl claims/real_claims_test.jsonl \
  --cache-dir claims/data/hss_test_v3_fulltext claims/data/real_claims_fulltext \
  --results-dir claims/results/v6 --runs A,B \
  --out claims/results/v6/review-workbook.xlsx \
  --key-out claims/results/v6/review-workbook-key.csv \
  --screening-record ../demo/expected/screening_record.json \
  --screening-prompt-version-expect <SCREENER_PROMPT_VERSION> \
  --demo-run-id 20261026-115827 \
  --delivered-evidence ../demo/expected/delivered_evidence.json \
  --paper-authors ../demo/tools/selected.json
```

`--results-dir claims/results/v6` is every script's own default results directory (see
"Results directories" above). `--cache-dir` reads the gitignored full-text fetch caches
(`claims/data/hss_test_v3_fulltext/`, `claims/data/real_claims_fulltext/`); a fresh clone
does not carry them and must build them first with `claims/build_hss_set.py` and
`claims/harvest_real_claims.py` (both shipped, no LLM call), or pass
`--allow-missing-chunks` to export the workbook without the cached source text. `--out`
and `--key-out` above write inside the clone; the
key csv is a reviewer answer key and must never be sent to the reviewer along with the
workbook. `--guard-commit` is left unset above so it auto-detects the last commit that
touched `backend/app/services/fulltext.py` (see `resolve_guard_commit`); pass it
explicitly only to pin a specific commit. `<SCREENER_PROMPT_VERSION>` stands for the
`SCREENER_PROMPT_VERSION` value recorded in `evaluation/screening/FREEZE_v3.md`.
`--demo-run-id 20261026-115827` and
`--delivered-evidence ../demo/expected/delivered_evidence.json` name the demonstration run
this repository ships; substitute a different run id and its own
`delivered_evidence.json` (for example under `../demo/output/<run id>/`) to review a
different run instead.

`--paper-authors` is required whenever `--delivered-evidence` is given, on this full-export
path and on the `--delivered-only` path described below: it feeds the Delivered sheet's
`paper_authors` column, which the Guide text and the misattribution rule both depend on.

A separate `--delivered-only` mode writes just three sheets, `Guide`, `Provenance` and
`Delivered`, with no item list at all, for a workbook whose only purpose is the delivered
product's own fidelity review:

```
cd evaluation
python claims/export_review_sheet.py --delivered-only \
  --demo-run-id 20261026-115827 \
  --delivered-evidence ../demo/expected/delivered_evidence.json \
  --paper-authors ../demo/tools/selected.json \
  --out claims/results/v6/delivered-workbook.xlsx \
  --key-out claims/results/v6/delivered-workbook-key.csv
```

In this mode `--items`, `--cache-dir`, `--results-dir` and `--key-out` are optional, and
`--annotation`/`--screening-record`/`--screening-record-b` are refused. The workbook id is
computed from the run id and the built rows themselves (`compute_delivered_workbook_id`),
not from an item list and shuffle seed, so re-exporting the same run gives the same id.

`claims/results/v6/inputs/` carries a byte-for-byte copy of the same run/meta files, kept
as the frozen input set the cached verifier replay reads from; either directory produces
the same export.

`--demo-run-id` (else the screening record's own filename, else `"n/a"`) and `export_time`
(computed once per run, from `common.now_iso()`, and never overridable from the command
line) are stamped together on the workbook's own Provenance and Guide sheets, so the two
sheets can never disagree about which run or which export they describe; a re-export
against the same `--out` path overwrites the file and gets a new `export_time` but the
same `demo_run_id` and the same opaque item order (and therefore the same workbook id
and the same key csv), since neither the item order nor the export seed changes between
re-exports of the same inputs.

## Claim-verification labels (v6)

The reference labels for the constructed (HSS) and real claim sets are the majority verdict of
three blind labellers: each received a copy of the claims workbook that holds the claim and
the stored source text and none of the tool's output, and returned it filled. SciFact keeps
its own published gold label throughout; only the constructed and real sets carry a
project-authored label to replace.

`evaluation/claims/human_review_labels.py` (system or evaluation-venv python; `openpyxl`; no
backend import, no network, no LLM call) takes the three labellers' filled workbooks and the
workbook key as command-line arguments (`--tag blind`, `--workbook` repeated exactly three
times in labeller order, and `--key`; no default location, and a run with neither refuses
with a plain message), and does this in one pass:

1. Reads the three workbooks and the key (both outside this repository and never committed),
   checks each workbook's id against the key's (the Guide line, else the sent copy matched by
   its row order; `--sent-dir` names the folder of sent copies, `--copy` names a sent copy
   explicitly), and builds one majority label per `Claims`-sheet item, joined on the opaque
   item id: the status at least two of the three labellers returned, or `no_majority` on a
   three-way split. Inter-rater agreement is reported two ways, the mean of the three
   pairwise percent-agreement rates and Fleiss' kappa, over the items the labellers actually
   judged freely (excluding the eight constructed items whose evidence is withheld by
   construction and whose verdict the protocol fixes rather than leaving to judgement).
2. Scores `results/v6/{hss,real}_run{A,B}.jsonl` against that majority label: accuracy with a
   95% Wilson interval, Cohen's kappa, `verified` precision/recall and the falsely-`verified`
   count, per set and per run. Writes `results/v6/human_labels_blind.json` (the majority
   label and each labeller's own verdict, keyed by the evaluation's own item id; no labeller
   identity) and `results/v6/human_review_scores_blind.json` (the scoring above).
3. Folds the result into `results/v6/summary.json` (a `human_review_blind` block) and
   `results/v6/summary.md` (Table E2-j, the label of record).

From `evaluation/`, `python claims/label_sets.py` then scores the verifier against the blind
label set and the construction rule side by side (Table E2-i) and writes
`results/v6/label_sets.json` and `label_sets.md`.

## Blind screening check

`evaluation/screening/blind_screening_scores.py` scores the three blind screening workbooks:
each labeller saw 140 records sampled from the screening decisions of the demonstration run
(80 excluded, 30 included, 20 returned to review by the inclusion judge, 10 queued for other
reasons) and none of the tool's output. From `evaluation/`:

```
python screening/blind_screening_scores.py --workbook A.xlsx --workbook B.xlsx --workbook C.xlsx --key KEY.csv --run-id RUN
python screening/blind_screening_scores.py --check screening/results/blind_round/blind_screening_records.csv
```

The first command joins the decisions on the opaque record id, takes the two-of-three
majority per record and writes `screening/results/blind_round/blind_screening_scores.json`,
`blind_screening_scores.md` and `blind_screening_records.csv` (one anonymised row per record:
record id, OpenAlex id, stratum, the system's status and the three decisions). The second
recomputes every score from the records file alone and exits 0 when it matches the scores
file. No labeller identity, workbook or title is written to any of the three files.
