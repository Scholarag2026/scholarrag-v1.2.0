"""Pure helpers of search/search_sort_comparison.py (no network, no backend import)."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from conftest import EVAL_ROOT, load_script_module

sp = load_script_module("search", "search_sort_comparison")
REPO = EVAL_ROOT.parent
RECORD = REPO / "demo/expected/screening_record.json"


def test_load_round_queries_reads_round_one_of_the_demo_record():
    qs = sp.load_round_queries(RECORD, 1)
    assert len(qs) == 7 and qs[0].startswith('"written corrective feedback"')


def test_overlap_at_cap_matches_on_doi_then_title():
    a = [{"doi": "10.1/a", "title": "A"}, {"doi": None, "title": "B b"}]
    b = [{"doi": "10.1/A", "title": "x"}, {"doi": None, "title": "b  B"}]
    assert sp.overlap_at_cap(a, b) == 2


def test_publication_cutoff_reads_the_demo_freeze_date():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert sp.publication_cutoff(record) == date(2026, 9, 8)


def test_publication_cutoff_is_none_without_a_freeze():
    assert sp.publication_cutoff({"criteria": {"publication_date_max": None}}) is None
    assert sp.publication_cutoff({}) is None


def test_llm_modules_loaded_flags_only_the_agents_package():
    assert sp.llm_modules_loaded(["app.clients.openalex", "app.config"]) is False
    assert sp.llm_modules_loaded(["app.agents.screener"]) is True
    assert sp.llm_modules_loaded(["app.agents"]) is True
    assert sp.llm_modules_loaded(["app.agentsx"]) is False


def test_summarise_reports_ranks_and_median_year():
    papers = [
        SimpleNamespace(title="T1", year=2000, citation_count=5, doi="10.1/x"),
        SimpleNamespace(title="T2", year=2010, citation_count=None, doi=None),
        SimpleNamespace(title="T3", year=None, citation_count=1, doi=None),
    ]
    page = SimpleNamespace(papers=papers, total_count=99, sort="relevance", per_page=25)
    s = sp.summarise(page)
    assert s["total_count"] == 99 and s["returned"] == 3 and s["median_year"] == 2005
    assert s["top"][0] == {
        "rank": 1, "title": "T1", "year": 2000, "cited_by_count": 5, "doi": "10.1/x",
    }
