## Table E2-k SciFact against published oracle-abstract verifiers

Strict: verified to SUPPORT; needs_nuance to NEI; unsupported with at least one assertion verdict "contradicted" to CONTRADICT; any other unsupported, no_full_text or error to NEI.

Lenient: verified to SUPPORT; needs_nuance to SUPPORT; unsupported with at least one assertion verdict "contradicted" to CONTRADICT; any other unsupported, no_full_text or error to NEI.

Abstract-level label-only, as in the published SciFact evaluation: a prediction is correct when the predicted label equals the gold label of the (claim, abstract) pair; NOT_ENOUGH_INFO predictions are ignored. Precision is correct predictions over non-NEI predictions. Recall is correct predictions over pairs whose gold label is not NEI. F1 is computed from the unrounded precision and recall.

| System | Split | Setting | P | R | F1 | Note |
|---|---|---|---|---|---|---|
| VeriSci trained on FEVER only (zero-shot) | SciFact dev, oracle abstract | Label-Only | 0.889 | 0.583 | 0.704 | Wadden et al., 2020, EMNLP, Table 7 (b), abstract-level results; tuned on dev |
| VeriSci (FEVER then SciFact) | SciFact dev, oracle abstract | Label-Only | 0.910 | 0.674 | 0.774 | Wadden et al., 2020, EMNLP, Table 7 (b), abstract-level results; tuned on dev |
| Paragraph-Joint | SciFact dev, oracle abstract | Label-Only | 0.833 | 0.766 | 0.798 | Li et al., 2021, SDU workshop at AAAI (arXiv 2012.14500), Table 3; tuned on dev |
| GPT-4o zero-shot, SUPPORT class | authors' own 80/10/10 re-split of SciFact train plus dev, test part (n = 122) | zero-shot prompt, title plus abstract | 0.910 | 0.800 | 0.850 | Kosprdic et al., 2024, IC3K (KMIS), Table 3; different split, not directly comparable |
| ScholarRAG run A, SUPPORT class, strict mapping | SciFact dev (340 rows) | SUPPORT-class metric | 0.983 | 0.413 | 0.582 | dev split, not the GPT-4o split; set beside the GPT-4o row only |
| ScholarRAG run B, SUPPORT class, strict mapping | SciFact dev (340 rows) | SUPPORT-class metric | 0.983 | 0.413 | 0.582 | dev split, not the GPT-4o split; set beside the GPT-4o row only |
| ScholarRAG run A, strict mapping | SciFact dev (209 evidence pairs) | Label-Only | 0.922 | 0.569 | 0.704 | oracle abstract |
| ScholarRAG run A, lenient mapping | SciFact dev (209 evidence pairs) | Label-Only | 0.939 | 0.813 | 0.872 | oracle abstract |
| ScholarRAG run B, strict mapping | SciFact dev (209 evidence pairs) | Label-Only | 0.937 | 0.569 | 0.708 | oracle abstract |
| ScholarRAG run B, lenient mapping | SciFact dev (209 evidence pairs) | Label-Only | 0.950 | 0.823 | 0.882 | oracle abstract |
| ScholarRAG run A, before the guards, strict mapping | SciFact dev (209 evidence pairs) | Label-Only | 0.924 | 0.579 | 0.712 | oracle abstract |
| ScholarRAG run B, before the guards, strict mapping | SciFact dev (209 evidence pairs) | Label-Only | 0.938 | 0.579 | 0.716 | oracle abstract |

### Published results on the same 340 SciFact dev pairs (NEI pairs included, 340 pairs)

The verifier has four labels and SciFact has three. Verified maps to SUPPORT, unsupported with a contradicted assertion to CONTRADICT, and the other unsupported rows and no_full_text to NEI. needs_nuance has no SciFact slot: it marks a claim whose assertions are all supported but which overstates the finding or drops a qualifier the paper attaches. Both readings are therefore reported. Lenient counts needs_nuance as SUPPORT, which is closer to SciFact's own meaning; strict counts it as no decision, the cautious reading. The source is the SciFact evidence-annotation instructions (Wadden et al., 2020, EMNLP, Appendix D; https://scifact.s3-us-west-2.amazonaws.com/doc/evidence-annotation-instructions.pdf). Section 3.3 says "If the evidence supports a special case of the claim (or the exact claim), support is full." Section 3.3.1 tells annotators to withhold scientific skepticism and to "Just take the author's words at face value". A claim stated more generally than its evidence was thus labelled SUPPORT in SciFact, while the verifier flags it as needs_nuance by design (51 of 138 gold SUPPORT pairs in run A and 53 in run B). The annotators were not asked about overstatement, so the lenient reading is closer to SciFact's meaning but not the same as it.

Med-V1 reports 3-way accuracy, so each ScholarRAG row below gives Label F1 and 3-way accuracy, scored on all 340 shipped rows.

| System | Metric | Value | Note |
|---|---|---|---|
| Med-V1-L3B (Llama-3.2-3B-Instruct base) | 3-way accuracy | 0.844 | Jin et al., 2026, arXiv 2603.05308v4, Figure 3, SciFact panel (bar labels) |
| Med-V1-Q3B (Qwen2.5-3B-Instruct base) | 3-way accuracy | 0.856 | Jin et al., 2026, arXiv 2603.05308v4, Figure 3, SciFact panel (bar labels) |
| ScholarRAG run A, strict mapping | Label F1 | 68.6 | 340 pairs, oracle abstract |
| ScholarRAG run A, strict mapping | 3-way accuracy | 0.709 | 340 pairs, oracle abstract; 95% CI 0.658 to 0.755 |
| ScholarRAG run A, lenient mapping | Label F1 | 84.8 | 340 pairs, oracle abstract |
| ScholarRAG run A, lenient mapping | 3-way accuracy | 0.853 | 340 pairs, oracle abstract; 95% CI 0.811 to 0.887 |
| ScholarRAG run B, strict mapping | Label F1 | 69.2 | 340 pairs, oracle abstract |
| ScholarRAG run B, strict mapping | 3-way accuracy | 0.712 | 340 pairs, oracle abstract; 95% CI 0.661 to 0.757 |
| ScholarRAG run B, lenient mapping | Label F1 | 86.0 | 340 pairs, oracle abstract |
| ScholarRAG run B, lenient mapping | 3-way accuracy | 0.862 | 340 pairs, oracle abstract; 95% CI 0.821 to 0.894 |

### SciRIFF-Eval rows (fold not stated in the paper)

The SciRIFF paper does not state which SciFact fold Table 2 scores, and the released harness scores a 184-pair fold drawn from SciFact train, so these rows are not set beside the 340 dev pairs.

| System | Metric | Value | Note |
|---|---|---|---|
| GPT-5 (oracle abstract) | Label F1 | 73.1 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |
| Gemini-2.5-Pro (oracle abstract) | Label F1 | 77.1 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |
| DeepSeek-V3.1 (oracle abstract) | Label F1 | 82.4 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |
| Kimi-K2 (oracle abstract) | Label F1 | 87.6 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |
| GPT-4o (oracle abstract) | Label F1 | 85.5 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |
| GPT-4o-mini (oracle abstract) | Label F1 | 82.7 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |
| Llama-3.1-8B-Instruct (oracle abstract) | Label F1 | 66.7 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |
| Llama-3.1-8B-Instruct fine-tuned on SciRIFF (oracle abstract) | Label F1 | 85.8 | Wadden et al., 2025, EMNLP, Table 2, SciFact column (Label F1 / Token F1); different fold, not directly comparable |

Verified-row precision, run A: 58 verified, 57 of them gold SUPPORT (precision 0.983, 95% CI 0.909 to 0.997). False verifications: 385:9767444. NEI verified 1 of 131 rows (130 distinct pairs), 95% CI 0.001 to 0.042. CONTRADICT verified 0 of 71.
Verified-row precision, run B: 58 verified, 57 of them gold SUPPORT (precision 0.983, 95% CI 0.909 to 0.997). False verifications: 385:9767444. NEI verified 1 of 131 rows (130 distinct pairs), 95% CI 0.001 to 0.042. CONTRADICT verified 0 of 71.
Verified-row precision, lexical baseline: 2 verified, of which 1 gold CONTRADICT and 0 gold NEI.

SUPPORT recall, run A: of 138 gold SUPPORT rows, 57 verified (recall 0.413, 95% CI 0.334 to 0.496), 51 needs_nuance, 30 unsupported (10 with a contradicted assertion). Verified before the guards: 59; moved by the guards: 275:4961038, 880:8426046.
SUPPORT recall, run B: of 138 gold SUPPORT rows, 57 verified (recall 0.413, 95% CI 0.334 to 0.496), 53 needs_nuance, 28 unsupported (8 with a contradicted assertion). Verified before the guards: 59; moved by the guards: 275:4961038, 880:8426046.

The guards changed 7 (run A) and 4 (run B) SciFact statuses, all towards stricter.

Provenance:

- The verifier prompt was developed on SciFact train pairs; dev was not used to write it.
- Guard 7 was designed with a probe over 852 stored rows that included SciFact dev rows (FREEZE_DIGESTS_v6.md), so dev is not fully held out for the guard chain.

Caveats:

- The comparison uses SciFact dev with oracle abstracts; no test-set or open-retrieval result is reported.
- The published VeriSci and Paragraph-Joint models were fine-tuned on SciFact train, and all three were tuned on dev (the zero-shot VeriSci row only for its rationale threshold).
- Our CONTRADICT label is inferred from assertion verdicts.
- The GPT-4o row uses its authors' own re-split of train and dev (n = 122) and a SUPPORT-class metric, so it is set beside our SUPPORT-class row only.
- The NEI total counts 131 rows over 130 distinct pairs; one pair appears twice in the shipped runs.
- Comparisons hold for the stated reading; the SciRIFF rows are not ranked.
- The Med-V1 rows are scored on 340 pairs and count NEI pairs, so they are set beside the all-cited figures of ScholarRAG, not beside the 209 evidence pairs. Med-V1 reports 3-way accuracy, a different metric.
- The SciRIFF paper does not state which SciFact fold its Table 2 scores, and the released harness scores a 184-pair fold drawn from SciFact train. The SciRIFF rows are therefore listed apart, with no ScholarRAG row beside them. SciRIFF reports Label F1 only, without precision or recall, and its prompt is its own expert-written template.
- No superiority over the general-purpose models is claimed: the verifier is itself a general-purpose model, and SciFact measures one step, labelling a claim against a given abstract.
