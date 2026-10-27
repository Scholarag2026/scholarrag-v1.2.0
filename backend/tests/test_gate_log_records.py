"""Pure tests for the gate-log record builders (no database)."""

import copy
import json
from types import SimpleNamespace

import pytest

from app.services.gate_log import (
    apply_length_trim,
    attempt_record,
    build_gate_log,
    claim_rows,
    revision_request_record,
)

SENT = "Tutoring boosts outcomes (Smith, 2020)."


def _attempt(name, sentences=("A.",)):
    return attempt_record(
        attempt=name,
        first_pass_sentences=list(sentences),
        first_pass_claims=[],
        link_map_failed=False,
        revision=None,
        finalize_fates=[{"fate": "kept", "rule": None, "delivered": "A."}],
    )


def test_claim_rows_follow_the_claim_tuple_order():
    claims = [("Tutoring boosts outcomes", "smith_2020", "ctx", SENT)]
    vs = [SimpleNamespace(status="verified")]
    expected = {
        "sentence": SENT,
        "proposition": "Tutoring boosts outcomes",
        "key": "smith_2020",
        "status": "verified",
    }
    assert claim_rows(claims, vs) == [expected]
    assert claim_rows(claims, vs, reused=[True]) == [{**expected, "reused": True}]
    with pytest.raises(ValueError):
        claim_rows(claims, [])
    with pytest.raises(ValueError):
        claim_rows(claims, vs, reused=[True, False])


def test_revision_triggers():
    kwargs = dict(
        keep_verbatim=[],
        failed=[{"sentence": "S.", "key": "k", "status": "unsupported", "extra": "x"}],
        coverage_issue={"b.", "a."},
        uncited_finding=["u"],
        unclassified=["c"],
    )
    rec = revision_request_record(
        statuses=["verified", "unsupported", "needs_nuance", "no_full_text", "unsupported"],
        coverage_flagged=True,
        **kwargs,
    )
    assert rec["triggers"] == ["coverage_flag", "needs_nuance", "unsupported"]
    assert rec["coverage_issue"] == ["a.", "b."]
    assert rec["failed"] == [{"sentence": "S.", "key": "k", "status": "unsupported"}]
    assert rec["uncited_finding"] == ["u"] and rec["unclassified"] == ["c"]
    rec2 = revision_request_record(statuses=["error"], coverage_flagged=False, **kwargs)
    assert rec2["triggers"] == ["error"]


def test_build_gate_log_marks_the_kept_attempt():
    attempts = [_attempt("first"), _attempt("second")]
    out = build_gate_log(attempts, "second")
    assert [a["kept"] for a in out["attempts"]] == [False, True]
    assert out["schema_version"] == 1 and out["kept_attempt"] == "second"
    with pytest.raises(ValueError):
        build_gate_log(attempts, "third")
    assert [a["kept"] for a in attempts] == [False, False]


def test_attempt_record_rejects_unknown_attempt():
    with pytest.raises(ValueError):
        _attempt("third")


def test_apply_length_trim():
    fates = [
        {"fate": "kept", "rule": None, "delivered": "A."},
        {"fate": "kept", "rule": None, "delivered": "B."},
        {"fate": "removed", "rule": "unverified", "delivered": None},
    ]
    before = copy.deepcopy(fates)
    out = apply_length_trim(fates, "A.")
    assert [f["fate"] for f in out] == ["kept", "removed", "removed"]
    assert [f["rule"] for f in out] == [None, "length_trimmed", "unverified"]
    assert out[1]["delivered"] is None
    assert fates == before


def test_duplicate_sentences_are_kept_as_separate_rows():
    rec = _attempt("first", ["A.", "A.", "B."])
    assert rec["first_pass"]["sentences"] == ["A.", "A.", "B."]


def test_records_are_json_serialisable():
    log = build_gate_log([_attempt("first")], "first")
    assert json.loads(json.dumps(log)) == log
