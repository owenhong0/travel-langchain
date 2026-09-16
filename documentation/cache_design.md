# Test-Mode Response Caching — Development & Design Process

## Motivation

Repeated test runs of the travel-langchain graphs (especially the `lodging` and
`transportation` subgraphs) re-hit real external APIs — Tavily search/extract, and
indirectly the LLM calls layered on top of that data — on every rerun, even when the
inputs (trip preferences, interrupt resume values) are identical between runs. This
was already flagged as deferred technical debt ("Idea 1: disk-cache Tavily
search/extract responses keyed on query params") before this feature existed. This
work generalizes that idea: instead of a disk cache scoped to Tavily alone, it's a
shared Postgres-backed cache scoped to any expensive external call, gated behind an
explicit `test_mode` flag so it never accidentally activates outside deliberate
testing.

## Key design decision: cache at the call site, not the node boundary

The original framing considered keying the cache per-node or per-interrupt (i.e.,
"if the interrupt resume payload is identical, skip the whole node"). This was
rejected: interrupts must still actually fire and pause so a test harness can
resume them — that's the entire point of testing the interrupt flow. What actually
needed to be skipped was the *expensive work downstream of a resume* — the LLM
calls, Tavily searches, and Duffel lookups a node performs after receiving its
resume value.

Caching at the call site (each individual `TavilySearch`/`TavilyExtract` invocation,
and eventually each LLM invocation) sidesteps this entirely: identical trip
preferences and identical resume payloads naturally produce identical arguments to
these calls, so the cache "just works" without the code needing to reason about
state or interrupt boundaries at all.

## Why `config.configurable`, not an environment variable

`test_mode` is threaded through LangGraph's `RunnableConfig.configurable`, not a
process-wide environment variable, for two reasons:

1. The `langgraph-api` server (and `langgraph dev`) serves multiple threads/runs
   concurrently. An env var would make test mode all-or-nothing across every
   concurrent user/thread; `configurable` scopes it per-run.
2. `configurable` values are automatically surfaced as run metadata in LangSmith
   traces, so cached vs. live runs can be visually distinguished in Studio without
   any extra instrumentation — a direct fit with this project's existing reliance
   on LangSmith for trace inspection.

## Cache key composition

Each cached call's key is a SHA-256 hash of:

```
call_type | CACHE_SCHEMA_VERSION | canonical_json(args)
```

- `call_type` — `"tavily_search"`, `"tavily_extract"`, etc. — namespaces the hash so
  identical argument dicts for different call types never collide.
- `CACHE_SCHEMA_VERSION` — an env var, bumped manually whenever a prompt or node's
  logic changes. Without this, a prompt edit could silently keep matching stale
  cached responses from before the edit, producing confusing "why didn't my change
  take effect" debugging sessions. This was identified as the single most important
  gotcha in the design — a correctness bug that would otherwise be invisible.
- `canonical_json(args)` — `json.dumps(args, sort_keys=True)` — a dict with the same
  keys/values in different insertion order still hashes identically.

For Tavily specifically, `args` includes both the tool's *construction* kwargs
(`max_results`, `include_domains`, etc.) and its *invoke-time* query — both affect
the result, so both must be part of the key or two calls with the same query but
different domain filters would incorrectly collide.

## Storage: Postgres, not Redis

Redis is already running in this project's stack, but purely as a pub-sub broker
for streaming real-time output from background runs (`langgraph-api`'s documented
role for `REDIS_URI`) — not configured or intended as a durable key-value store.
Repurposing it would mean adding a new usage pattern to infrastructure that already
has a job. Postgres, by contrast, is already the durable "look up by key, write if
missing" layer for the LangGraph checkpointer — a `test_response_cache` table is
simply more of the same pattern on the same connection style (plain `psycopg`,
matching the existing convention in `checkpoint_utils.py`).

## Implementation surface

- **`migrations/001_create_test_response_cache.sql`** — schema only.
- **`cache_utils.py`** — `_cache_key()`, `get_cached()`, `store_cache()`, plus the
  `cached_tavily_search()` / `cached_tavily_extract()` wrappers. Connection pattern
  mirrors `checkpoint_utils.py`: a fresh `psycopg.connect(conn_string)` per call, no
  pooling, `conn_string` passed explicitly rather than read from a global.
- **`leg_transportation_graph.py`** and **`lodging_graph.py`** — every node that
  calls Tavily now accepts `config: RunnableConfig` and routes its calls through the
  `cache_utils` wrappers instead of constructing `TavilySearch`/`TavilyExtract`
  directly.

## Bugs found and fixed during implementation

These were pre-existing issues surfaced by adding `config` threading and by testing
the graphs end-to-end for the first time in the course of this work — not caused by
the caching feature itself, but worth recording here since they were found in the
same pass:

1. **Argument-order bug in `lodging_graph.py`.** `search_agoda`,
   `search_hotel_chains`, `search_general_ota`, and `search_unique_stays` were
   calling the shared `_run_stay_search(leg, domains, ...)` helper, but that
   helper's signature is `_run_stay_search(config, leg, domains, ...)` — `config`
   is the first parameter. These four callers didn't have `config` in their own
   signatures at all, so `leg` (a dict) was landing in the slot typed
   `config: RunnableConfig | None`. This was a latent bug independent of caching,
   caught only because adding `config` threading forced a close read of every call
   site.

2. **Two functions missing `config` in `leg_transportation_graph.py`.**
   `verify_route_options` and `search_car_rental` referenced `config` inside their
   bodies (in calls to `cached_tavily_search`) without declaring it as a parameter
   — a `NameError` surfaced once the graph was actually exercised end-to-end in
   Studio, since these two functions were missed in an earlier snippet-by-snippet
   pass that covered `search_route_options` and `discover_relevant_domains`.

3. **`review_stay` infinite loop on destinations with zero lodging options
   (surfaced via Jeju-do).** The no-options branch of `review_stay` only treated
   the literal string `"skip"` as a terminal signal; any other reply — including
   `"approve"`, the standard resume signal used everywhere else in the codebase —
   fell through to `review_decision: "revise"`, re-triggering the same search that
   had already found nothing, forever. Fixed by accepting `APPROVE_SIGNALS` as an
   equivalent terminal signal on that branch, matching the convention used
   elsewhere.

4. **CORS blocking LangSmith Studio via tunnel.** `webapp.py`'s
   `CORSMiddleware` only allowed `http://localhost:5173` (the Vite dev server
   origin). When accessing the LangGraph server through `langgraph dev --tunnel`
   and LangSmith's hosted Studio UI (`smith.langchain.com`), every request from
   Studio's origin failed CORS preflight with a `400`, surfacing to the browser as
   "Failed to initialize Studio." This was initially misdiagnosed as a Brave
   Shields / DNS issue (both were separately, coincidentally real problems
   encountered in the same session — a stale local DNS cache from a prior dead
   tunnel, and Brave's ad-blocker correctly blocking unrelated Datadog telemetry
   calls) before the actual CORS `400`s were found in the Network tab. Fixed by
   adding `https://smith.langchain.com` to `allow_origins`.

## Verification methodology

Given this project's own note that LangSmith Studio's trace panel is unreliable for
tool inputs/outputs on this project, the cache was verified against Postgres
directly rather than relying on trace inspection alone:

1. Run a fresh thread with `test_mode: true` end-to-end through a real search fan-out
   → confirm `test_response_cache` goes from empty to populated (a genuine miss,
   writing on every call).
2. Run a **second**, separate thread with **identical** inputs and `test_mode: true`
   → confirm the row counts in `test_response_cache` do **not** increase, and that
   the run reproduces the exact same output (a genuine hit reproduces results
   deterministically; a fresh live call could plausibly return different data).

Both were confirmed against the `lodging` graph directly (bypassing `main` /
`trip_info` / `transportation` to keep the test cheap), using a minimal
single-stop Jeju-do itinerary.