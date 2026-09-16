import hashlib
import json
import os

import psycopg
from psycopg.types.json import Jsonb

from langchain_core.runnables import RunnableConfig
from langchain_tavily import TavilySearch
from langchain_tavily import TavilyExtract

CACHE_SCHEMA_VERSION = os.environ.get("CACHE_SCHEMA_VERSION", "v1")

def cached_tavily_extract(config: RunnableConfig, conn_string: str, invoke_args: dict, **tool_kwargs):
    test_mode = (config or {}).get("configurable", {}).get("test_mode", False)
    cache_args = {"invoke_args": invoke_args, "tool_kwargs": tool_kwargs}

    if test_mode:
        cached = get_cached(conn_string, "tavily_extract", cache_args)
        if cached is not None:
            return cached

    result = TavilyExtract(**tool_kwargs).invoke(invoke_args)

    if test_mode:
        store_cache(conn_string, "tavily_extract", cache_args, result)
    return result

def cached_tavily_search(config: RunnableConfig | None, conn_string: str, invoke_args: dict, **tool_kwargs):
    """Wraps TavilySearch(**tool_kwargs).invoke(invoke_args) with test-mode caching.
    Cache key covers both construction args (domains, max_results, etc.) and the
    invoke-time query, since either can change the result."""
    test_mode = (config or {}).get("configurable", {}).get("test_mode", False)
    cache_args = {"invoke_args": invoke_args, "tool_kwargs": tool_kwargs}

    if test_mode:
        cached = get_cached(conn_string, "tavily_search", cache_args)
        if cached is not None:
            return cached

    result = TavilySearch(**tool_kwargs).invoke(invoke_args)

    if test_mode:
        store_cache(conn_string, "tavily_search", cache_args, result)
    return result


def _cache_key(call_type: str, args: dict) -> str:
    """Deterministic hash of a call's identity — same call_type + args +
    schema_version always produces the same key, regardless of dict ordering."""
    canonical = json.dumps(args, sort_keys=True, default=str)
    raw = f"{call_type}|{CACHE_SCHEMA_VERSION}|{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()

def get_cached(conn_string: str, call_type: str, args: dict) -> dict | None:
    if not conn_string:
        raise RuntimeError(
            "POSTGRES_URI is not set — required for test_mode caching. "
            "Check .env (native `langgraph dev`) or docker-compose.yml (container)."
        )
    key = _cache_key(call_type, args)
    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT output_snapshot FROM test_response_cache WHERE cache_key = %s",
                (key,),
            )
            row = cur.fetchone()
            print(f"[cache] {'HIT' if row else 'MISS'} call_type={call_type} key={key[:8]}")
            return row[0] if row else None


def store_cache(conn_string: str, call_type: str, args: dict, output: dict) -> None:
    """Store a response for this exact call. No-op if the key already exists —
    first write wins, since replaying should be deterministic once cached."""
    key = _cache_key(call_type, args)
    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO test_response_cache
                    (cache_key, call_type, schema_version, input_snapshot, output_snapshot)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (cache_key) DO NOTHING
                """,
                (key, call_type, CACHE_SCHEMA_VERSION, Jsonb(args), Jsonb(output)),
            )
        conn.commit()