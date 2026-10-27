"""Settings that bound the search pipelines (T3)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_deep_search_has_a_wall_clock_cap():
    defaults = Settings()
    assert defaults.deep_search_max_time_minutes == 30.0


def test_search_fanout_concurrency_default():
    defaults = Settings()
    assert defaults.search_fanout_concurrency == 4
    assert 1 <= defaults.search_fanout_concurrency <= 8


def test_time_caps_accept_fractional_minutes():
    """Sub-minute budgets must be representable so the caps are testable."""
    tuned = Settings(
        smart_search_max_time_minutes=0.25,
        deep_search_max_time_minutes=0.5,
    )
    assert tuned.smart_search_max_time_minutes == 0.25
    assert tuned.deep_search_max_time_minutes == 0.5


def test_search_sort_defaults_to_relevance():
    assert Settings().search_sort == "relevance"


def test_search_per_query_cap_defaults_to_25_and_is_bounded():
    assert Settings().search_per_query_cap == 25
    with pytest.raises(ValidationError):
        Settings(search_per_query_cap=0)
    with pytest.raises(ValidationError):
        Settings(search_per_query_cap=201)


def test_search_sort_rejects_unknown_values():
    with pytest.raises(ValidationError):
        Settings(search_sort="newest")
