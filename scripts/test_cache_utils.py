import os

import pytest

from cache_utils import _cache_key, get_cached, store_cache

CONN_STRING = os.environ["POSTGRES_URI"] # adjust if your .env uses a different var name


def test_cache_key_is_deterministic():
    args = {"query": "flights SFO to JFK", "date": "2026-10-01"}
    assert _cache_key("tavily_search", args) == _cache_key("tavily_search", args)


def test_cache_key_ignores_dict_order():
    a = {"query": "x", "date": "y"}
    b = {"date": "y", "query": "x"}
    assert _cache_key("tavily_search", a) == _cache_key("tavily_search", b)


def test_cache_key_differs_by_call_type():
    args = {"query": "x"}
    assert _cache_key("tavily_search", args) != _cache_key("duffel", args)


def test_store_and_get_round_trip():
    args = {"query": "unique-test-query-12345"}
    output = {"result": "cached test value"}

    assert get_cached(CONN_STRING, "tavily_search", args) is None  # sanity: not cached yet

    store_cache(CONN_STRING, "tavily_search", args, output)
    cached = get_cached(CONN_STRING, "tavily_search", args)

    assert cached == output