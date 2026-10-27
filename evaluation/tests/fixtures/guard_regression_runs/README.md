Redacted slice of a 30-item claim-verification run on the constructed claim set
(`hss_runA.jsonl`, `hss_runB.jsonl`). It is kept so that `test_claims_numeric_guard.py` and
`test_claims_quote_fidelity_guard.py` can regression-test the numeric and quote-fidelity
guards against real claim text and real guard-input fields. Each row keeps only `item_id`,
`rule`, `claim`, `chunk_doi`, `predicted_status`, `evidence_quote` and `quote_is_verbatim`;
every other field of the original run (token counts, timings, provenance, explanations, and
the like) is dropped. It is not an evaluation result: no accuracy, precision or recall figure
is computed from this directory.
