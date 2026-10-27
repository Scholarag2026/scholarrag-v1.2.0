Redacted slice of a claim-verification run that contains four line-break-hyphenation
quote-fidelity cases (`hss-verbatim-01`, `hss-paraphrase-04`, `real-test-12`, `real-test-20`).
`test_claims_quote_fidelity_guard.py::test_quote_fidelity_guard_does_not_fire_on_the_line_break_hyphenation_cases`
uses it to check that the guard does not fire on them. Each file keeps only the rows for those
four item ids, and each row keeps only `item_id`, `model_status`, `machine_reasons`,
`evidence_quote` and `evidence_quotes`; every other field (token counts, timings, provenance,
and the like) is dropped. It is not an evaluation result.
