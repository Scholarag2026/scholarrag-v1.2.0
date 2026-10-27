"""Finalize records what became of each sentence: kept, changed, merged or removed,
and the rule that removed it. The per-rule counts agree with finalize's own counters."""

import json
from pathlib import Path

import pytest

from app.services.fulltext import (
    FATE_RULES,
    finalize_draft_document,
    finalize_generated_section,
    section_sentence_texts,
)
from tests.conftest import skip_unless_run_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "demo" / "output" / "20261026-115827"


def _link(sentence, keys, citation_text="(X, 2020)", paragraph_index=0, **extra):
    return {
        "paragraph_index": paragraph_index,
        "sentence": sentence,
        "keys": keys,
        "citation_text": citation_text,
        **extra,
    }


PARITY = {
    r: f"sentences_removed_{r}"
    for r in (
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
} | {"heading": "headings_removed"}


def _assert_parity(result):
    removed = [f for f in result.sentence_fates if f["fate"] == "removed"]
    assert all(f["rule"] in FATE_RULES for f in removed)
    for rule, key in PARITY.items():
        assert sum(f["rule"] == rule for f in removed) == result.stats.get(key, 0), rule
    truncated = sum(
        f["fate"] == "merged" or f["rule"] == "truncated_fragment" for f in result.sentence_fates
    )
    assert truncated == result.stats.get("sentences_truncated_fragment_repaired", 0)
    assert "sentence_fates" not in result.stats
    assert all(isinstance(v, int) for v in result.stats.values())


def test_verified_sentence_is_kept():
    text = "Tutoring works well (Smith, 2020)."
    links = [_link(text, ["smith_2020"], "(Smith, 2020)")]
    status = {(text, text, "smith_2020"): "verified"}

    result = finalize_generated_section(text, links, [], status)

    assert result.sentence_fates == [
        {"sentence": text, "fate": "kept", "rule": None, "delivered": text, "paragraph": 0}
    ]
    _assert_parity(result)


def test_unsupported_sentence_is_removed_as_unverified():
    text = "Tutoring works well (Smith, 2020)."
    links = [_link(text, ["smith_2020"], "(Smith, 2020)")]
    status = {(text, text, "smith_2020"): "unsupported"}

    result = finalize_generated_section(text, links, [], status)

    assert len(result.sentence_fates) == 1
    fate = result.sentence_fates[0]
    assert fate["fate"] == "removed"
    assert fate["rule"] == "unverified"
    assert fate["delivered"] is None
    _assert_parity(result)


def test_uncited_finding_is_removed_and_framing_kept():
    text = (
        "Tutoring works well (Smith, 2020). Most studies agree tutoring helps. "
        "Tutoring is studied widely."
    )
    first = "Tutoring works well (Smith, 2020)."
    links = [_link(first, ["smith_2020"], "(Smith, 2020)")]
    status = {(first, first, "smith_2020"): "verified"}
    uncited = [
        {"paragraph_index": 0, "sentence": "Most studies agree tutoring helps.", "tag": "finding"},
        {"paragraph_index": 0, "sentence": "Tutoring is studied widely.", "tag": "framing"},
    ]

    result = finalize_generated_section(text, links, uncited, status)

    assert [f["fate"] for f in result.sentence_fates] == ["kept", "removed", "kept"]
    assert result.sentence_fates[1]["rule"] == "uncited_finding"
    _assert_parity(result)


def test_only_no_full_text_citation_removes_the_sentence():
    text = "This method was shown to work (Smith, 2020)."
    links = [_link(text, ["smith_2020"])]
    status = {(text, text, "smith_2020"): "no_full_text"}

    result = finalize_generated_section(text, links, [], status)

    assert [(f["fate"], f["rule"]) for f in result.sentence_fates] == [("removed", "no_full_text")]
    _assert_parity(result)


def test_dropped_no_full_text_citation_marks_the_sentence_changed():
    sentence = "Tutoring works (Smith, 2020) and (Jones, 2019)."
    links = [
        _link(sentence, ["smith_2020"], citation_text="(Smith, 2020)"),
        _link(sentence, ["jones_2019"], citation_text="(Jones, 2019)"),
    ]
    status = {
        (sentence, sentence, "smith_2020"): "verified",
        (sentence, sentence, "jones_2019"): "no_full_text",
    }

    result = finalize_generated_section(sentence, links, [], status)

    assert len(result.sentence_fates) == 1
    fate = result.sentence_fates[0]
    assert fate["fate"] == "changed"
    assert fate["delivered"] == result.text
    _assert_parity(result)


def test_heading_block_is_recorded():
    sentence = "Tutoring works well (Smith, 2020)."
    text = f"## Background\n\n{sentence}"
    links = [_link(sentence, ["smith_2020"], "(Smith, 2020)", paragraph_index=1)]
    status = {(sentence, sentence, "smith_2020"): "verified"}

    result = finalize_generated_section(text, links, [], status)

    assert result.sentence_fates[0] == {
        "sentence": "## Background",
        "fate": "removed",
        "rule": "heading",
        "delivered": None,
        "paragraph": 0,
    }
    assert result.sentence_fates[1]["fate"] == "kept"
    assert result.sentence_fates[1]["paragraph"] == 1
    _assert_parity(result)


def test_dangling_paragraph_is_recorded():
    first = "Tutoring works well (Smith, 2020)."
    second = "Tutoring is studied widely."
    text = f"{first}\n\n{second}"
    links = [_link(first, ["smith_2020"], "(Smith, 2020)")]
    status = {(first, first, "smith_2020"): "verified"}
    uncited = [{"paragraph_index": 1, "sentence": second, "tag": "framing"}]

    result = finalize_generated_section(text, links, uncited, status)

    assert result.sentence_fates[1]["fate"] == "removed"
    assert result.sentence_fates[1]["rule"] == "dangling"
    assert result.sentence_fates[1]["paragraph"] == 1
    assert result.stats["sentences_removed_dangling"] == 1
    _assert_parity(result)


def test_title_echo_block_is_recorded():
    heading_line = "## Learner engagement with written corrective feedback"
    echo = "Engagement with written corrective feedback shapes second-language writing."
    cited = "Zhang and Hyland (2018) found substantial variation in revision behaviour."
    text = f"{heading_line}\n\n{echo}\n\n{cited}"
    links = [_link(cited, ["zhang_2018"], citation_text="(2018)", paragraph_index=2)]
    status = {(cited, cited, "zhang_2018"): "verified"}

    result = finalize_generated_section(
        text,
        links,
        [],
        status,
        section_title="Learner engagement with written corrective feedback",
    )

    echoed = [f for f in result.sentence_fates if f["paragraph"] == 1]
    assert echoed
    assert all(f["fate"] == "removed" and f["rule"] == "title_echo" for f in echoed)
    assert result.stats["sentences_removed_title_echo"] == 1
    _assert_parity(result)


def test_truncated_fragment_dropped_and_merged():
    fragment = (
        "[NEEDS CITATION] for how learners actually revise in response to ME codes, "
        "and for whether ME promotes deeper cognitive engagement despite higher "
        "perceived load."
    )
    uncited = [{"paragraph_index": 0, "tag": "finding", "sentence": fragment, "unclassified": True}]
    dropped = finalize_generated_section(fragment, [], uncited, {})
    assert [(f["fate"], f["rule"]) for f in dropped.sentence_fates] == [
        ("removed", "truncated_fragment")
    ]
    _assert_parity(dropped)

    cited = "Tutoring works well (Smith, 2020)."
    tail = "Whether these gains last remains [NEEDS CITATION]."
    links = [_link(cited, ["smith_2020"], "(Smith, 2020)")]
    uncited = [{"paragraph_index": 0, "sentence": tail, "tag": "finding", "unclassified": True}]
    status = {(cited, cited, "smith_2020"): "verified"}

    merged = finalize_generated_section(cited + " " + tail, links, uncited, status)

    assert merged.text == "Tutoring works well (Smith, 2020), Whether these gains last remains."
    assert merged.stats["sentences_truncated_fragment_repaired"] == 1
    assert merged.sentence_fates == [
        {
            "sentence": cited,
            "fate": "changed",
            "rule": None,
            "delivered": merged.text,
            "paragraph": 0,
        },
        {
            "sentence": "Whether these gains last remains.",
            "fate": "merged",
            "rule": None,
            "delivered": None,
            "paragraph": 0,
        },
    ]
    _assert_parity(merged)


def _verifying_every_link(citation_links):
    return {
        (link["sentence"], link.get("proposition") or link["sentence"], key): "verified"
        for link in citation_links
        for key in link.get("keys") or []
    }


_RUN_FILES = ["writing_result.json"] + [f"writing_result_{i}.json" for i in range(2, 8)]


@pytest.mark.parametrize("name", _RUN_FILES)
def test_real_run_inputs_keep_counter_parity(name):
    run_dir = skip_unless_run_dir(RUN_DIR)
    r = json.loads((run_dir / name).read_text(encoding="utf-8"))
    status = _verifying_every_link(r["citation_links"])

    result = finalize_generated_section(
        r["content"], r["citation_links"], r["uncited_sentences"], status
    )

    _assert_parity(result)
    assert [
        f["sentence"] for f in result.sentence_fates if f["rule"] != "heading"
    ] == section_sentence_texts(r["content"])
    assert result.text == r["content"]
    assert all(f["fate"] == "kept" for f in result.sentence_fates)


def test_real_run_inputs_keep_counter_parity_leadin_case():
    sentence = (
        "Showed that one student resubmitted her essay 13 times while another "
        "made one resubmission (Zhang & Hyland, 2018)."
    )
    proposition = "one student resubmitted her essay 13 times while another made one resubmission"
    links = [
        {
            "paragraph_index": 0,
            "sentence": sentence,
            "proposition": proposition,
            "keys": ["zhang_2018"],
            "citation_text": "(Zhang & Hyland, 2018)",
        }
    ]
    status = {(sentence, proposition, "zhang_2018"): "verified"}

    result = finalize_generated_section(sentence, links, [], status)

    _assert_parity(result)
    assert [(f["fate"], f["rule"]) for f in result.sentence_fates] == [("removed", "verb_initial")]
    assert [f["sentence"] for f in result.sentence_fates] == section_sentence_texts(sentence)


def test_section_sentence_texts_drops_headings_and_markers():
    text = "## Aims\n\nOne claim [NEEDS CITATION]. Two claim (Smith, 2020).\n\nThree."

    assert section_sentence_texts(text) == [
        "One claim.",
        "Two claim (Smith, 2020).",
        "Three.",
    ]


def test_heal_path_stats_stay_integer_only():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {
                    "citationLinks": [
                        {
                            "sentence": "Bad claim (Smith, 2020).",
                            "keys": ["smith_2020"],
                            "citation_text": "(Smith, 2020)",
                        }
                    ]
                },
                "content": [{"type": "text", "text": "Bad claim (Smith, 2020)."}],
            }
        ],
    }
    status = {("Bad claim (Smith, 2020).", "Bad claim (Smith, 2020).", "smith_2020"): "unsupported"}
    claims = [
        ("Bad claim (Smith, 2020).", "smith_2020", "(Smith, 2020)", "Bad claim (Smith, 2020)."),
    ]

    _content, _links, stats, _healed = finalize_draft_document(doc, claims, status)

    assert "sentence_fates" not in stats
    assert all(isinstance(v, int) for v in stats.values())
