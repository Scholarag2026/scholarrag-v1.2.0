"""Tests for demo/oa_share.py, using an httpx MockTransport and no network."""

import json
from pathlib import Path

import httpx
import oa_share

OA = {
    "gold": {"is_oa": True, "oa_status": "gold", "oa_url": "https://x.org/a.pdf"},
    "green": {"is_oa": True, "oa_status": "green", "oa_url": "https://x.org/b.pdf"},
    "closed": {"is_oa": False, "oa_status": "closed", "oa_url": None},
}


def work(short: str, kind: str) -> dict:
    return {
        "id": f"https://openalex.org/{short}",
        "doi": f"https://doi.org/10.1/{short}",
        "open_access": OA[kind],
    }


def make_run(tmp_path: Path, ids: list[str], outcomes: list[str] | None = None) -> Path:
    outcomes = outcomes or ["included"] * len(ids)
    records = [
        {"outcome": o, "openalex_id": f"https://openalex.org/{i}"}
        for i, o in zip(ids, outcomes)
    ]
    (tmp_path / "screening_record.json").write_text(
        json.dumps({"records": records}), encoding="utf-8"
    )
    return tmp_path


def transport(kinds: dict[str, str], calls: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        wanted = request.url.params["filter"].removeprefix("openalex:").split("|")
        return httpx.Response(
            200, json={"results": [work(w, kinds[w]) for w in wanted if w in kinds]}
        )

    return httpx.MockTransport(handler)


def test_short_id_normalises():
    assert oa_share.short_id("https://openalex.org/W123") == "W123"
    assert oa_share.short_id("W123") == "W123"
    assert oa_share.short_id("") == ""


def test_included_records_selects_only_included():
    rec = {
        "records": [
            {"outcome": "included", "n": 1},
            {"outcome": "excluded", "n": 2},
            {"outcome": "needs_review", "n": 3},
            {"outcome": "included", "n": 4},
        ]
    }
    assert [r["n"] for r in oa_share.included_records(rec)] == [1, 4]


def test_batches_of_fifty():
    ids = [f"W{i}" for i in range(108)]
    calls: list[httpx.Request] = []
    with httpx.Client(transport=transport({i: "gold" for i in ids}, calls)) as c:
        cache = oa_share.fetch_open_access(ids, client=c)
    sizes = [
        len(r.url.params["filter"].removeprefix("openalex:").split("|")) for r in calls
    ]
    assert sizes == [50, 50, 8]
    for r in calls:
        assert r.url.params["filter"].startswith("openalex:")
        assert r.url.params["per-page"] == "50"
        assert r.url.params["select"] == "id,doi,open_access"
    assert len(cache["results"]) == 108
    assert cache["source"] == oa_share.OPENALEX_WORKS


def fetch(ids, kinds):
    with httpx.Client(transport=transport(kinds)) as c:
        return oa_share.fetch_open_access(ids, client=c)


def test_build_share_counts(tmp_path):
    ids = ["W1", "W2", "W3"]
    kinds = {"W1": "gold", "W2": "green", "W3": "closed"}
    rec = json.loads(
        make_run(tmp_path, ids).joinpath("screening_record.json").read_text()
    )
    share = oa_share.build_share(rec, fetch(ids, kinds), run_id="r")
    assert share["included"] == 3
    assert share["matched"] == 3
    assert share["is_oa"] == 2
    assert share["share_is_oa"] == 0.667
    assert share["with_oa_url"] == 2
    assert share["by_oa_status"] == {"closed": 1, "gold": 1, "green": 1}
    assert share["unmatched_ids"] == []
    assert share["run_id"] == "r"


def test_unmatched_ids_listed(tmp_path):
    ids = ["W1", "W2", "W3"]
    rec = json.loads(
        make_run(tmp_path, ids).joinpath("screening_record.json").read_text()
    )
    share = oa_share.build_share(
        rec, fetch(ids, {"W1": "gold", "W2": "closed"}), run_id="r"
    )
    assert share["matched"] == 2
    assert share["unmatched_ids"] == ["W3"]
    assert share["included"] == 3
    assert share["share_is_oa"] == 0.333


def test_offline_check_round_trip(tmp_path):
    ids = ["W1", "W2", "W3"]
    d = str(make_run(tmp_path, ids))
    t = transport({"W1": "gold", "W2": "green", "W3": "closed"})
    assert oa_share.main(["--run-dir", d], transport=t) == 0
    assert (tmp_path / "oa_share.json").exists()
    assert (tmp_path / "oa_share_openalex.json").exists()
    assert oa_share.main(["--run-dir", d, "--offline", "--check"]) == 0
    out = tmp_path / "oa_share.json"
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc["is_oa"] += 1
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    assert oa_share.main(["--run-dir", d, "--offline", "--check"]) == 1


def test_check_never_fetches_or_rewrites_cache(tmp_path):
    d = str(make_run(tmp_path, ["W1", "W2"]))
    assert oa_share.main(["--run-dir", d], transport=transport({"W1": "gold", "W2": "green"})) == 0
    cache = tmp_path / "oa_share_openalex.json"
    out = tmp_path / "oa_share.json"
    before = (cache.read_bytes(), out.read_bytes())
    calls: list = []
    t = transport({"W1": "closed", "W2": "closed"}, calls)
    assert oa_share.main(["--run-dir", d, "--check"], transport=t) == 0
    assert calls == []
    assert (cache.read_bytes(), out.read_bytes()) == before
    assert oa_share.main(["--run-dir", d, "--offline", "--check"]) == 0


def test_http_error_exits_1_without_output(tmp_path, monkeypatch):
    monkeypatch.setattr(oa_share.time, "sleep", lambda s: None)
    d = str(make_run(tmp_path, ["W1"]))
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    assert oa_share.main(["--run-dir", d], transport=httpx.MockTransport(handler)) == 1
    assert not (tmp_path / "oa_share.json").exists()
    assert len(calls) == 2


def test_mailto_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENALEX_EMAIL", "a@b.org")
    calls: list[httpx.Request] = []
    d = str(make_run(tmp_path, ["W1"]))
    assert (
        oa_share.main(["--run-dir", d], transport=transport({"W1": "gold"}, calls)) == 0
    )
    assert calls[0].url.params["mailto"] == "a@b.org"
