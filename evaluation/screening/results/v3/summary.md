# Screening evaluation summary (E1)

## Table E1-a. Screening performance on each protocol's gold label

| Dataset | System | Gold label | n | Prevalence (gold label) | Recall | Precision | F1 | Specificity | Inclusion rate | WSS@R (achieved) | WSS@95 | kappa A/B | Retained recall (final inclusions) | Retained recall 95% CI (final inclusions) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | LLM run A | label_abstract_screening | 2008 | 0.194 | 0.000 | - | - | 1.000 | 0.000 | 0.000 | - | - | 1.000 | [0.963, 1.000] |
| Nagtegaal_2019 | LLM run B | label_abstract_screening | 2008 | 0.194 | 0.000 | - | - | 1.000 | 0.000 | 0.000 | - | - | 1.000 | [0.963, 1.000] |
| Nagtegaal_2019 | include-all | label_included | 2008 | 0.050 | 1.000 | 0.050 | 0.096 | 0.000 | 1.000 | 0.000 | -0.050 | - | - | - |
| Nagtegaal_2019 | TF-IDF (k=693, query=rq+criteria) | label_included | 2008 | 0.050 | 0.564 | 0.082 | 0.144 | 0.666 | 0.345 | 0.219 | 0.155 | - | - | - |
| Smid_2020 | LLM run A | label_included | 2627 | 0.010 | 0.000 | - | - | 1.000 | 0.000 | 0.000 | - | - | 1.000 | [0.875, 1.000] |
| Smid_2020 | LLM run B | label_included | 2627 | 0.010 | 0.000 | - | - | 1.000 | 0.000 | 0.000 | - | - | 1.000 | [0.875, 1.000] |
| Smid_2020 | include-all | label_included | 2627 | 0.010 | 1.000 | 0.010 | 0.020 | 0.000 | 1.000 | 0.000 | -0.050 | - | - | - |
| Smid_2020 | TF-IDF (k=1003, query=rq+criteria) | label_included | 2627 | 0.010 | 0.963 | 0.026 | 0.050 | 0.624 | 0.382 | 0.581 | 0.696 | - | - | - |
| van_de_Schoot_2017 | LLM run A | label_abstract_screening | 5782 | 0.062 | 0.000 | - | - | 1.000 | 0.000 | 0.000 | - | - | 0.947 | [0.827, 0.985] |
| van_de_Schoot_2017 | LLM run B | label_abstract_screening | 5782 | 0.062 | 0.000 | - | - | 1.000 | 0.000 | 0.000 | - | - | 0.947 | [0.827, 0.985] |
| van_de_Schoot_2017 | include-all | label_included | 5782 | 0.007 | 1.000 | 0.007 | 0.013 | 0.000 | 1.000 | 0.000 | -0.050 | - | - | - |
| van_de_Schoot_2017 | TF-IDF (k=943, query=rq+criteria) | label_included | 5782 | 0.007 | 0.947 | 0.038 | 0.073 | 0.842 | 0.163 | 0.784 | 0.773 | - | - | - |

Metrics use the protocol label named in the Gold label column (see the gold-label notes below); a deduplicated dataset is scored on its deduplicated records. WSS@R = (TN+FN)/N - (1-R) (Cohen et al. 2006) at the achieved recall; WSS@95 is given for a fixed decision only when recall >= 0.95, and for TF-IDF from its ranking. kappa is Cohen's kappa between runs A and B on records screened in both. Metrics are computed on the decisions as production returned them; Table E1-b gives the count of INCLUDE decisions production padded in because the model returned no decision ('no decision returned') and the recall / precision with those rows treated as unscreened (padded as unscreened). All figures are point estimates on the stated n with no confidence interval; a few-point difference between systems, datasets or runs A and B is not interpreted as a difference (see README.md, 'No confidence intervals'). The trailing 'Retained recall' pair (blank for a baseline row, which is never scored on this basis) counts INCLUDE or NEEDS_REVIEW as a positive decision instead of INCLUDE alone; it is the primary reading of this table once a protocol names a full-text inclusion criterion (Table E1-e reports it in full, alongside screened-in share, reading saved, auto-inclusion precision and queue precision).

kappa undefined here: this column scores only the binary INCLUDE / not-INCLUDE decision, which is constant across every record in both runs (not the three-way INCLUDE/EXCLUDE/NEEDS_REVIEW status), so expected agreement is 1 and kappa has no value; '-' is printed. This does not mean the two runs are identical record by record -- Table E1-e's own three-way status kappa, computed on the same runs, is reported there.

Structurally zero: this table's own Recall, Precision and WSS columns count INCLUDE decisions only, and a dataset whose protocol names a full-text inclusion criterion cannot clear that criterion from title and abstract alone, so the full-text-to-confirm guard demotes every genuine INCLUDE to NEEDS_REVIEW before this table's own columns can count it; those columns then read exactly 0.000 (or blank) by construction, not as a measure of a failure to find anything -- the trailing Retained recall columns and Table E1-e report what the screener actually kept.

- **Nagtegaal_2019**: Gold label = label_abstract_screening: the human screeners' title/abstract decision (the evaluated task); recall against the final inclusions is reported separately. The gold labels are the source reviews' own screening decisions as distributed by SYNERGY, not a re-annotation for this evaluation; SYNERGY publishes no per-record inter-screener agreement, so records counted here as LLM false positives or false negatives include human label noise and review-specific screening thresholds. van_de_Schoot_2017's protocol records a deliberately over-inclusive title/abstract stage, so precision is not compared across datasets here; note that this criterion is also passed to the screener in the prompt (protocols/README.md: the criteria lists go unchanged to screen_papers), so it raises this dataset's recall as well, and recall is read as a capability number only within a dataset -- across runs A and B and against the baselines on the same records -- not as a ranking of the three datasets.
- **Smid_2020**: Gold label = label_included: the review's final inclusion set after full-text reading (this SYNERGY export carries no title/abstract decision). A title/abstract screener is expected to keep more than this set, so precision is a lower bound and recall is measured against the final inclusions. The gold labels are the source reviews' own screening decisions as distributed by SYNERGY, not a re-annotation for this evaluation; SYNERGY publishes no per-record inter-screener agreement, so records counted here as LLM false positives or false negatives include human label noise and review-specific screening thresholds. van_de_Schoot_2017's protocol records a deliberately over-inclusive title/abstract stage, so precision is not compared across datasets here; note that this criterion is also passed to the screener in the prompt (protocols/README.md: the criteria lists go unchanged to screen_papers), so it raises this dataset's recall as well, and recall is read as a capability number only within a dataset -- across runs A and B and against the baselines on the same records -- not as a ranking of the three datasets.
- **van_de_Schoot_2017**: Gold label = label_abstract_screening: the human screeners' title/abstract decision (the evaluated task); recall against the final inclusions is reported separately. The gold labels are the source reviews' own screening decisions as distributed by SYNERGY, not a re-annotation for this evaluation; SYNERGY publishes no per-record inter-screener agreement, so records counted here as LLM false positives or false negatives include human label noise and review-specific screening thresholds. van_de_Schoot_2017's protocol records a deliberately over-inclusive title/abstract stage, so precision is not compared across datasets here; note that this criterion is also passed to the screener in the prompt (protocols/README.md: the criteria lists go unchanged to screen_papers), so it raises this dataset's recall as well, and recall is read as a capability number only within a dataset -- across runs A and B and against the baselines on the same records -- not as a ranking of the three datasets.

## Table E1-b. Secondary numbers

| Dataset | Run | Gold label | Final inclusions (n) | Recall vs final inclusions | Retained recall vs final inclusions | Unscreened records | Padded INCLUDE (n) | Recall / precision (padded as unscreened) | Excluded final inclusions | Excluded TA positives | Excluded positives without abstract (share) | Missing abstract (share) | Missing title (n) | % agreement A/B |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | A | label_abstract_screening | 101 | 0.000 | 1.000 | 0 | 0 | as-is | 0 | 102 | 0.000 | 0.084 | 0 | 1.000 |
| Nagtegaal_2019 | B | label_abstract_screening | 101 | 0.000 | 1.000 | 0 | 0 | as-is | 0 | 103 | 0.000 | 0.084 | 0 | 1.000 |
| Smid_2020 | A | label_included | 27 | 0.000 | 1.000 | 0 | 0 | as-is | 0 | 0 | - | 0.244 | 33 | 1.000 |
| Smid_2020 | B | label_included | 27 | 0.000 | 1.000 | 0 | 0 | as-is | 0 | 0 | - | 0.244 | 33 | 1.000 |
| van_de_Schoot_2017 | A | label_abstract_screening | 38 | 0.000 | 0.947 | 0 | 0 | as-is | 2 | 212 | 0.009 | 0.129 | 5 | 1.000 |
| van_de_Schoot_2017 | B | label_abstract_screening | 38 | 0.000 | 0.947 | 0 | 0 | as-is | 2 | 217 | 0.009 | 0.129 | 5 | 1.000 |

Missing abstract (share) is the share of dataset records without an abstract (from the fetch counts, else from the run rows); the production prompt shows '(no abstract)' for those records and truncates abstracts to 10,000 characters. Missing title (n) counts screened records without title text (the prompt shows '(no title)'); with no abstract either, such records are blank to the screener. 'Retained recall vs final inclusions' is the same INCLUDE-or-NEEDS_REVIEW basis as Table E1-a's trailing columns and Table E1-e's own retained recall, scored here against the review's final inclusions specifically rather than this table's own gold label. '% agreement A/B' is the same binary INCLUDE / not-INCLUDE basis as Table E1-a's own kappa column, not the three-way status agreement Table E1-e reports; it reads 1.000 whenever no record was INCLUDE in either run, which is not the same thing as the two runs matching on every record's status.

## Table E1-e. Final-inclusion basis (primary basis: retained recall, screened-in share, reading saved, auto-inclusion precision, queue precision)

| Dataset | Run | n | Retained recall | 95% CI | Screened-in share | Excluded share | Reading saved (WSS) | Auto-inclusion precision (n) | Queue precision | A/B agreement, status (kappa) | Reading saved @0.95 (TF-IDF ranking) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | A | 2008 | 1.000 | [0.963, 1.000] | 0.345 | 0.655 | 0.655 | none, n = 0 | 0.146 | 0.953 | - |
| Nagtegaal_2019 | B | 2008 | 1.000 | [0.963, 1.000] | 0.347 | 0.653 | 0.653 | none, n = 0 | 0.145 | 0.953 | - |
| Nagtegaal_2019 | include-all | 2008 | 1.000 | [0.963, 1.000] | 1.000 | 0.000 | 0.000 | 0.050 (n = 2008) | - | - | - |
| Nagtegaal_2019 | TF-IDF (k=693, query=rq+criteria) | 2008 | 0.564 | [0.467, 0.657] | 0.345 | 0.655 | 0.219 | 0.082 (n = 693) | - | - | 0.155 |
| Smid_2020 | A | 2627 | 1.000 | [0.875, 1.000] | 0.382 | 0.618 | 0.618 | none, n = 0 | 0.027 | 0.863 | - |
| Smid_2020 | B | 2627 | 1.000 | [0.875, 1.000] | 0.368 | 0.632 | 0.632 | none, n = 0 | 0.028 | 0.863 | - |
| Smid_2020 | include-all | 2627 | 1.000 | [0.875, 1.000] | 1.000 | 0.000 | 0.000 | 0.010 (n = 2627) | - | - | - |
| Smid_2020 | TF-IDF (k=1003, query=rq+criteria) | 2627 | 0.963 | [0.817, 0.993] | 0.382 | 0.618 | 0.581 | 0.026 (n = 1003) | - | - | 0.696 |
| van_de_Schoot_2017 | A | 5782 | 0.947 | [0.827, 0.985] | 0.163 | 0.837 | 0.784 | none, n = 0 | 0.038 | 0.948 | - |
| van_de_Schoot_2017 | B | 5782 | 0.947 | [0.827, 0.985] | 0.163 | 0.837 | 0.785 | none, n = 0 | 0.038 | 0.948 | - |
| van_de_Schoot_2017 | include-all | 5782 | 1.000 | [0.908, 1.000] | 1.000 | 0.000 | 0.000 | 0.007 (n = 5782) | - | - | - |
| van_de_Schoot_2017 | TF-IDF (k=943, query=rq+criteria) | 5782 | 0.947 | [0.827, 0.985] | 0.163 | 0.837 | 0.784 | 0.038 (n = 943) | - | - | 0.773 |

All five figures are scored against label_included (the review's own final inclusions), regardless of which label a dataset's other tables use as primary. Retained recall counts INCLUDE or NEEDS_REVIEW as a positive screening decision (everything not yet excluded); its 95% CI is the Wilson interval on the true positives over the shared positive count. Screened-in share is the fraction of the corpus routed to INCLUDE or NEEDS_REVIEW. Reading saved is work saved over sampling (Cohen et al. 2006), (TN+FN)/N - (1-R), evaluated at the *retained* recall R above (not the INCLUDE-only recall Table E1-a's WSS columns use). Reading saved is the excluded share minus (1 - R); the excluded share itself is printed in its own column. Excluded share is the fraction of the corpus the screener excluded outright; it does not have to sum to one with the screened-in share, since one measures what was excluded and the other what was not excluded. Auto-inclusion precision is the share of INCLUDE decisions that are a genuine final inclusion, with n the count of INCLUDE decisions it is computed over; printed as 'none, n = 0' when no record was auto-included at all, the structural consequence of routing an unconfirmed full-text inclusion criterion to NEEDS_REVIEW rather than INCLUDE on any protocol that names one. Queue precision is the share of NEEDS_REVIEW rows that are a genuine final inclusion, i.e. how often the queue a reviewer reads actually contains one. A/B agreement is Cohen's kappa between runs A and B on the three-way INCLUDE/EXCLUDE/NEEDS_REVIEW status (agreement_AB_status), a per-dataset number repeated on each run's own row. Each dataset also carries an include-all and a TF-IDF baseline row (baselines.py, matched to the screener's own screened-in count and scored on the same label_included basis); a baseline has no NEEDS_REVIEW queue and no second run, so its Queue precision and A/B agreement cells read '-', and its Auto-inclusion precision (n) column reports its overall precision with n the number of records it included. The trailing column is the TF-IDF ranking's work saved at a fixed 0.95 recall, independent of the matched threshold; '-' for every other row.

van_de_Schoot_2017 as exported (6,189 rows): retained recall 41/43 = 0.953; the export lists 407 rows as duplicates of other records (duplicate_record_id); 5 of them are final inclusions, so the submitted basis counted those inclusions twice.

## Table E1-f. Title-and-abstract basis

| Dataset | Run | TA positives (n) | Retained (TA) | Retained recall (TA) | 95% CI | Final inclusions kept | Non-final TA positives kept | Reading saved (TA basis) |
|---|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | A | 389 | 287 | 0.738 | [0.692, 0.779] | 101/101 | 186/288 | 0.393 |
| Nagtegaal_2019 | B | 389 | 286 | 0.735 | [0.689, 0.777] | 101/101 | 185/288 | 0.389 |
| Smid_2020 | - | no title-and-abstract label in this export | - | - | - | - | - | - |
| van_de_Schoot_2017 | A | 356 | 142 | 0.399 | [0.349, 0.451] | 36/38 | 106/318 | 0.236 |
| van_de_Schoot_2017 | B | 356 | 137 | 0.385 | [0.336, 0.436] | 36/38 | 101/318 | 0.222 |

A title-and-abstract (TA) positive is a record the source review's human screeners kept at the title-and-abstract stage. 'Final inclusions kept' counts the TA positives that are also final inclusions (kept / n); 'Non-final TA positives kept' counts the ones the review dropped at full text. Retained means INCLUDE or NEEDS_REVIEW, and Reading saved is evaluated at the retained TA recall. A dataset whose export carries no TA decision prints one row saying so.

## Table E1-g. Reading queue by cause

| Dataset | Run | Cause | Records (n) | Share of corpus | Final inclusions (n) | TA positives (n) |
|---|---|---|---|---|---|---|
| Nagtegaal_2019 | A | full_text_to_confirm | 392 | 0.195 | 98 | 253 |
| Nagtegaal_2019 | A | no_abstract | 168 | 0.084 | 1 | 9 |
| Nagtegaal_2019 | A | full_text_criterion | 96 | 0.048 | 1 | 14 |
| Nagtegaal_2019 | A | undecidable | 28 | 0.014 | 1 | 11 |
| Nagtegaal_2019 | A | unanchored_exclude | 9 | 0.004 | 0 | 0 |
| Nagtegaal_2019 | B | full_text_to_confirm | 389 | 0.194 | 98 | 255 |
| Nagtegaal_2019 | B | no_abstract | 166 | 0.083 | 1 | 9 |
| Nagtegaal_2019 | B | full_text_criterion | 94 | 0.047 | 0 | 12 |
| Nagtegaal_2019 | B | undecidable | 38 | 0.019 | 2 | 10 |
| Nagtegaal_2019 | B | unanchored_exclude | 9 | 0.004 | 0 | 0 |
| Smid_2020 | A | no_abstract | 494 | 0.188 | 4 | - |
| Smid_2020 | A | full_text_criterion | 409 | 0.156 | 0 | - |
| Smid_2020 | A | full_text_to_confirm | 69 | 0.026 | 23 | - |
| Smid_2020 | A | undecidable | 26 | 0.010 | 0 | - |
| Smid_2020 | A | unanchored_exclude | 5 | 0.002 | 0 | - |
| Smid_2020 | B | no_abstract | 495 | 0.188 | 4 | - |
| Smid_2020 | B | full_text_criterion | 374 | 0.142 | 0 | - |
| Smid_2020 | B | full_text_to_confirm | 71 | 0.027 | 23 | - |
| Smid_2020 | B | undecidable | 22 | 0.008 | 0 | - |
| Smid_2020 | B | unanchored_exclude | 4 | 0.002 | 0 | - |
| van_de_Schoot_2017 | A | no_abstract | 716 | 0.124 | 0 | 26 |
| van_de_Schoot_2017 | A | full_text_to_confirm | 147 | 0.025 | 36 | 101 |
| van_de_Schoot_2017 | A | undecidable | 65 | 0.011 | 0 | 14 |
| van_de_Schoot_2017 | A | unanchored_exclude | 15 | 0.003 | 0 | 1 |
| van_de_Schoot_2017 | B | no_abstract | 716 | 0.124 | 0 | 26 |
| van_de_Schoot_2017 | B | full_text_to_confirm | 141 | 0.024 | 36 | 99 |
| van_de_Schoot_2017 | B | undecidable | 61 | 0.011 | 0 | 12 |
| van_de_Schoot_2017 | B | unanchored_exclude | 21 | 0.004 | 0 | 0 |
| van_de_Schoot_2017 | B | cut_abstract | 1 | 0.000 | 0 | 0 |
| van_de_Schoot_2017 | B | unquoted_criterion | 1 | 0.000 | 0 | 0 |

Each NEEDS_REVIEW record is counted under the cause the screener attached to it (its guard reason; 'no_abstract' for a record with no abstract, 'undecidable' for a model routing the guard did not touch). Share of corpus is over the screened records. Final inclusions and TA positives count the queued records of that cause that the source review kept at full text and at title and abstract; a dash means the export carries no title-and-abstract label.

## Table E1-h. TF-IDF ranking against the screener, in records read

| Dataset | Run | N | Screener: records read | Screener: final inclusions kept | TF-IDF at the screener's budget: found | TF-IDF to reach the screener's count: records read | TF-IDF at 95% recall: records read (found / target) |
|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | A | 2008 | 693 (34.5%) | 101 | 57 | 1,837 (91.5%) | 1,597 (79.5%) (96 / 96) |
| Smid_2020 | A | 2627 | 1,003 (38.2%) | 27 | 26 | 1,507 (57.4%) | 667 (25.4%) (26 / 26) |
| van_de_Schoot_2017 | A | 5782 | 943 (16.3%) | 36 | 36 | 569 (9.8%) | 1,025 (17.7%) (37 / 37) |

The TF-IDF stopping points are fixed with the labels; the screener's point is its own label-free decision. The screener has no ranking, so it has no 95% recall point.

## Table E1-i. ASReview LAB simulation (15 seeds) at the screener's operating point

| Dataset | Screener run | Screener: records read (final kept) | ASReview found at that budget: mean (min to max) | ASReview records to reach the screener's count: mean (min to max) | WSS@95: mean (min to max) | WSS@100: mean (min to max) | Stop after 100 irrelevant: records read, found |
|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | A | 693 (34.5%) (101) | 98.1 (98.0 to 99.0) | 1119 (1114 to 1129) | 0.726 (0.719 to 0.736) | 0.443 (0.438 to 0.445) | 554 (535 to 565), 97.1 (97.0 to 98.0) |
| Nagtegaal_2019 | B | 696 (34.7%) (101) | 98.1 (98.0 to 99.0) | 1119 (1114 to 1129) | 0.726 (0.719 to 0.736) | 0.443 (0.438 to 0.445) | 554 (535 to 565), 97.1 (97.0 to 98.0) |
| Smid_2020 | A | 1,003 (38.2%) (27) | 27.0 (27.0 to 27.0) | 769 (707 to 800) | 0.794 (0.772 to 0.800) | 0.707 (0.695 to 0.731) | 235 (218 to 303), 22.3 (22.0 to 24.0) |
| Smid_2020 | B | 966 (36.8%) (27) | 27.0 (27.0 to 27.0) | 769 (707 to 800) | 0.794 (0.772 to 0.800) | 0.707 (0.695 to 0.731) | 235 (218 to 303), 22.3 (22.0 to 24.0) |
| van_de_Schoot_2017 | A | 943 (16.3%) (36) | 38.0 (38.0 to 38.0) | 200 (175 to 236) | 0.911 (0.908 to 0.914) | 0.939 (0.934 to 0.957) | 328 (311 to 349), 37.1 (37.0 to 38.0) |
| van_de_Schoot_2017 | B | 941 (16.3%) (36) | 38.0 (38.0 to 38.0) | 200 (175 to 236) | 0.911 (0.908 to 0.914) | 0.939 (0.934 to 0.957) | 328 (311 to 349), 37.1 (37.0 to 38.0) |

ASReview uses the reviewer's labels as screening proceeds; the screener uses none and makes the exclusion decision itself. WSS@95 and WSS@100 stop at a point fixed with the labels; the last column applies a stopping rule that does not.

ASReview LAB 3.0.8, default model (elas_u4), priors one relevant and one irrelevant record, seeds 1 to 15.

## Table E1-c. Provenance, cost and latency per run

| Dataset | Run | Model configured | Model reported | Fingerprints | Temp. | Prompt version | Batches | Failed | Retried | Input tokens | Output tokens | Cost (USD) | Cost basis | Concurrency | Latency median (s) | Latency p90 (s) | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | A | deepseek-flash | deepseek-flash | 1 | 0.000 | sha256:9bc741046cd6 | 202 | 0 | 0 | 1343874 | 142684 | 0.390 | list price, tier by call time, cache-miss assumed (upper bound) | 8 | 2.841 | 3.510 | 2026-09-15 |
| Nagtegaal_2019 | B | deepseek-flash | deepseek-flash | 1 | 0.000 | sha256:9bc741046cd6 | 202 | 0 | 0 | 1312401 | 139461 | 0.381 | list price, tier by call time, cache-miss assumed (upper bound) | 8 | 2.807 | 3.470 | 2026-09-15 |
| Smid_2020 | A | deepseek-flash | deepseek-flash | 1 | 0.000 | sha256:9bc741046cd6 | 263 | 0 | 0 | 1258386 | 146441 | 0.373 | list price, tier by call time, cache-miss assumed (upper bound) | 8 | 2.477 | 2.933 | 2026-09-15 |
| Smid_2020 | B | deepseek-flash | deepseek-flash | 1 | 0.000 | sha256:9bc741046cd6 | 263 | 0 | 0 | 1281668 | 149807 | 0.381 | list price, tier by call time, cache-miss assumed (upper bound) | 8 | 2.507 | 2.938 | 2026-09-15 |
| van_de_Schoot_2017 | A | deepseek-flash | deepseek-flash | 1 | 0.000 | sha256:9bc741046cd6 | 619 | 0 | 0 | 3604488 | 369045 | 1.037 | list price, tier by call time, cache-miss assumed (upper bound) | 8 | 2.572 | 3.159 | 2026-09-15 |
| van_de_Schoot_2017 | B | deepseek-flash | deepseek-flash | 1 | 0.000 | sha256:9bc741046cd6 | 619 | 0 | 0 | 3516589 | 360243 | 1.011 | list price, tier by call time, cache-miss assumed (upper bound) | 8 | 2.625 | 3.059 | 2026-09-15 |

Cost (USD) sums the per-call list price of the reported model with the peak/off-peak tier taken from each call's timestamp; the screening interface exposes no cache-hit split, so every input token is billed at the cache-miss rate and the figure is an upper bound. Output tokens are recorded as reported by the API and may include reasoning tokens. 'Fingerprints' counts the distinct `system_fingerprint` values the API returned across the run's calls; more than one indicates the served model changed mid-run. Latency is wall-clock per batch call measured while up to 'Concurrency' calls were in flight (the harness default is 8; production uses analysis_concurrency = 4), so medians and p90 include provider-side queueing.

## Table E1-d. WoS venue-gate effect (recall ceiling of the optional Stage-1 filter)

| Dataset | Hydration | Included n | Resolved (ISSN/n) | in WoS (any) | Ceiling lower-upper | SCIE | SSCI | AHCI | ESCI | All records resolved | All records share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Nagtegaal_2019 | included | 101 | 77/101 | 69 | 0.683-0.921 (resolved-only 0.896) | 68 | 21 | 0 | 1 | 295/2008 | - |
| Smid_2020 | openalex_id | 27 | 26/27 | 26 | 0.963-1.000 (resolved-only 1.000) | 12 | 23 | 0 | 0 | 2403/2627 | 0.865 |
| van_de_Schoot_2017 | included | 38 | 37/38 | 36 | 0.947-0.974 (resolved-only 0.973) | 20 | 30 | 0 | 1 | 305/5782 | - |

A deduplicated dataset is counted on its deduplicated records, the basis of every other table of this section.

'Ceiling lower-upper' is the recall ceiling of the gate over the human-included records: a record with no ISSN has an unknown venue, so the gate's recall ceiling lies between the lower bound (unresolved records assumed outside WoS: in WoS / Included n) and the upper bound (unresolved records assumed inside WoS: (in WoS + unresolved) / Included n), with 'Resolved (ISSN/n)' next to them; the parenthetical 'resolved-only' figure (in WoS / resolved) is a point estimate, not a bound, that assumes the unresolved records are in WoS at the same rate as the resolved ones. A fully resolved set prints a single value, all three coinciding. 'All records share' is printed only when at least 90 % of all records carry an ISSN ('-' otherwise). Route-v1 datasets are hydrated for the human-included records only ('Hydration' = included), so their all-records column is unresolved by design. Resolution is by DOI where the export has one and otherwise by exact normalised title in Crossref; title-only matches carry a same-title risk (a comment, reprint or conference abstract with the same title would attribute a wrong venue) and cannot be year-checked when the export carries no year (Nagtegaal_2019); the protocol files record a spot-check (judged by the harness fix agent, to be re-read by the authors) of such matches, 20/20 correct in each dataset, a sample rather than a census whose 95 % Wilson interval is [0.839, 1.000], so up to about one in six title-only matches could still be a same-title mismatch, an error these intervals do not carry.
