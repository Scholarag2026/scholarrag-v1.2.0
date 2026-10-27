"""A sentence with one citation whose propositions leave content only before that citation
uncovered is verified as a whole sentence.

No model call, no database: pure-function tests over ``validate_citation_links`` and the
finalize step."""

import os

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")

import pytest  # noqa: E402

from app.agents.citation_link_agent import (  # noqa: E402
    CitationLink,
    CitationLinkMap,
    validate_citation_links,
)
from app.services.fulltext import finalize_generated_section  # noqa: E402

MAO = (
    "A systematic search for the review identified 50 empirical studies meeting its "
    "inclusion criteria, revealing four major themes: teacher feedback practices in L2 "
    "writing classrooms, L2 learner responses to feedback, stakeholders' beliefs and "
    "perspectives about feedback, and feedback-related motivation and emotions "
    "(Mao et al., 2024)."
)
MAO_TAIL = MAO[MAO.index("revealing") : MAO.index(" (Mao")]
MAO_LEAD = MAO[: MAO.index(", revealing")]
MAO_50 = "50 empirical studies meeting its inclusion criteria"
UNS = (
    "Screening yielded the same 50 eligible studies for the review, sorted into two major "
    "themes: writing accuracy outcomes and learner motivation only (Mao et al., 2024)."
)


def _link(sentence, proposition, citation_text="(Mao et al., 2024)", key="mao_2024"):
    return CitationLink(
        paragraph_index=0,
        sentence=sentence,
        citation_text=citation_text,
        keys=[key],
        proposition=proposition,
    )


def _validate(*links, content=None):
    sentence = links[0].sentence
    return validate_citation_links(CitationLinkMap(links=list(links)), content or sentence)


@pytest.mark.parametrize(
    "proposition",
    [MAO_TAIL, MAO_LEAD, MAO_50],
    ids=["leading_residue", "leading_clause", "inner_phrase"],
)
def test_a_partial_proposition_widens_to_the_whole_sentence(proposition):
    validated = _validate(_link(MAO, proposition))
    assert validated[0]["proposition"] == MAO
    assert validated[0]["coverage_incomplete"] is False
    assert validated[0]["residue_spans"] == []


def test_the_unsupported_fixture_is_widened_and_checked_whole():
    validated = _validate(
        _link(UNS, "Screening yielded the same 50 eligible studies for the review")
    )
    assert validated[0]["proposition"] == UNS


def test_a_trailing_aside_keeps_the_model_proposition():
    sentence = (
        "Liu and Wu (2019) add that 60% of students preferred teacher feedback, "
        "underscoring the persistent value of human judgement."
    )
    proposition = "60% of students preferred teacher feedback"
    validated = _validate(_link(sentence, proposition, "(2019)", "liu_2019"))
    assert validated[0]["proposition"] == proposition
    assert validated[0]["coverage_incomplete"] is True


def test_a_trailing_aside_after_a_narrative_citation_keeps_the_model_proposition():
    sentence = "In a large trial, Smith (2020) found gains in accuracy, which settles the debate."
    proposition = "found gains in accuracy"
    validated = _validate(_link(sentence, proposition, "(2020)", "smith_2020"))
    assert validated[0]["proposition"] == proposition
    assert validated[0]["coverage_incomplete"] is True


def test_a_non_frame_residue_at_both_ends_keeps_the_model_proposition():
    sentence = (
        "The most convincing evidence comes from a classroom trial in which Yallop et al. "
        "(2021) found revision gains, which settles the debate."
    )
    proposition = "found revision gains"
    validated = _validate(_link(sentence, proposition, "(2021)", "yallop_2021"))
    assert validated[0]["proposition"] == proposition
    assert validated[0]["coverage_incomplete"] is True


def test_a_two_citation_sentence_is_not_widened():
    sentence = "Lee (2021) found no change, while Smith (2020) found gains in accuracy."
    proposition = "found gains in accuracy"
    validated = _validate(_link(sentence, proposition, "(2020)", "smith_2020"))
    assert validated[0]["proposition"] == proposition
    assert validated[0]["coverage_incomplete"] is True


def test_two_links_whose_union_covers_the_sentence_are_unchanged():
    sentence = (
        "Bonilla Lopez et al. (2018) reported that learners' cognitive-load estimates "
        "were significantly lower when processing direct corrections, while self-"
        "correcting with no feedback available imposed significantly lower load."
    )
    first = (
        "learners' cognitive-load estimates were significantly lower when processing "
        "direct corrections"
    )
    second = "self-correcting with no feedback available imposed significantly lower load"
    validated = _validate(
        _link(sentence, first, "(2018)", "lopez_2018"),
        _link(sentence, second, "(2018)", "lopez_2018"),
    )
    assert [v["proposition"] for v in validated] == [first, second]


def test_a_leading_meta_evaluation_still_flags_after_widening():
    sentence = (
        "The most convincing evidence comes from a classroom trial in which Yallop et al. "
        "(2021) found revision gains."
    )
    validated = _validate(_link(sentence, "found revision gains", "(2021)", "yallop_2021"))
    assert validated[0]["proposition"] == sentence
    assert validated[0]["meta_evaluation"] is True


@pytest.mark.parametrize("proposition", [MAO_TAIL, MAO_LEAD, MAO_50])
def test_widened_supported_sentence_survives_finalize(proposition):
    validated = _validate(_link(MAO, proposition))
    result = finalize_generated_section(MAO, validated, [], {(MAO, MAO, "mao_2024"): "verified"})
    assert "identified 50 empirical studies" in result.text
    assert result.stats["sentences_removed_coverage_incomplete"] == 0


def test_an_unwidened_partial_proposition_is_removed_by_finalize():
    raw = [
        {
            "paragraph_index": 0,
            "sentence": MAO,
            "citation_text": "(Mao et al., 2024)",
            "keys": ["mao_2024"],
            "proposition": MAO_TAIL,
        }
    ]
    result = finalize_generated_section(MAO, raw, [], {(MAO, MAO_TAIL, "mao_2024"): "verified"})
    assert result.stats["sentences_removed_coverage_incomplete"] == 1
