# Test-Mode Response Caching — Usage Guide

## What this does

When `test_mode` is enabled for a run, every Tavily search/extract call (and any
future call routed through `cache_utils.py`) checks Postgres for a previously
stored response before hitting the real API. If found, the stored response is
returned instantly with no external call. If not found, the real API is called
once and the result is stored for next time.

**This only ever activates when explicitly enabled per-run.** A normal run, with no
`test_mode` flag set, behaves exactly as before — every call goes live, nothing is
read from or written to the cache table.

## Enabling it on a run

`test_mode` lives in `config.configurable`, not an environment variable, so it must
be passed explicitly on **every** call that advances a thread — the initial run
*and* every subsequent resume through an interrupt. It does not persist
automatically between calls on the same thread.

**Via the LangGraph SDK (Python):**

```python
from langgraph_sdk import get_client

client = get_client(url=TUNNEL_URL)  # or your deployed server URL
thread = await client.threads.create()

# Initial run
async for chunk in client.runs.stream(
    thread["thread_id"], "lodging",  # or "transportation", "orchestrator", etc.
    input={...},
    config={"configurable": {"test_mode": True}},
):
    ...

# Every resume through an interrupt needs it again:
from langgraph_sdk.schema import Command

async for chunk in client.runs.stream(
    thread["thread_id"], "lodging",
    command=Command(resume="approve"),
    config={"configurable": {"test_mode": True}},   # repeat here too
):
    ...
```

**Via LangSmith Studio:** Studio's standard "Interact" flow for starting a thread
does not currently expose a way to set arbitrary `configurable` values before
kicking off a run. Threads started this way will **not** have `test_mode` set,
and will behave as normal live runs — see the note at the end of this guide for
how to change that.

## Running the graph directly vs. through the orchestrator

`lodging` and `transportation` are each independently registered graphs (per
`langgraph.json`), not only reachable as subgraphs inside `orchestrator`. For
testing the cache in isolation, target the specific graph you're testing directly
rather than running the full `main → trip_info → transportation → lodging`
sequence through `orchestrator` — this avoids re-paying for the upstream LLM calls
(destination brainstorming, itinerary dating) on every test iteration.

```python
# Cheap: talks to the lodging graph directly
client.runs.stream(thread_id, "lodging", input={...}, config={...})

# Expensive: re-runs everything upstream too, just to reach the same lodging state
client.runs.stream(thread_id, "orchestrator", input={...}, config={...})
```

Minimal input shape for testing `lodging` directly:

```python
{
    "dated_itinerary": [
        {
            "city": "Jeju-do",
            "country": "South Korea",
            "depart_date": "2026-11-05",
            "return_date": "2026-11-08",
            "duration_days": 3,
        },
    ],
    "loyalty_programmes": [],
    "stay_legs": [],
    "finalized_stays": [],
}
```

## Inspecting the cache directly

```bash
psql -d postgres
```

```sql
-- See what's cached, by type
SELECT call_type, count(*) FROM test_response_cache GROUP BY call_type;

-- Inspect a specific entry's inputs/outputs
SELECT call_type, input_snapshot, output_snapshot
FROM test_response_cache
WHERE call_type = 'tavily_search'
ORDER BY created_at DESC
LIMIT 5;

-- Clear everything (e.g. before a clean before/after comparison)
TRUNCATE test_response_cache;
```

Note which Postgres instance you're actually connected to. Native `langgraph dev`
reads `POSTGRES_URI` from `.env`, which points at the local Postgres.app instance
(`psql -d postgres` with no host/port flags hits this one directly). The
Dockerized `langgraph-api` container reads `POSTGRES_URI` from
`docker-compose.yml`'s `environment:` block, pointing at the separate
`langgraph-postgres` container instead — reachable via
`docker exec -it <container> psql -U postgres -d postgres`, not plain `psql`. These
are two different databases; don't cross-check counts between them.

## When to bump `CACHE_SCHEMA_VERSION`

Set as an environment variable, defaulting to `"v1"` if unset. **Bump this any time
you change a prompt, extraction schema, or the logic inside a node that calls a
cached function.** The cache key includes this version string specifically so that
old cached responses stop matching once the underlying behavior has changed —
without it, a code change could silently keep serving pre-change cached data,
which is a much harder bug to notice than a cache that's simply cold.

## Safety notes

- **Test mode is not currently gated behind an environment check.** Before relying
  on this in any shared or production-adjacent environment, add a guard (e.g.
  `if os.environ.get("ENVIRONMENT") == "production": test_mode = False`) so a
  stray `test_mode: true` from a client can never serve cached data outside local
  development.
- Cached responses are stored verbatim, including anything sensitive that happened
  to be in a Tavily result at cache-write time. Treat `test_response_cache` with
  the same care as any other data containing search results.

## Making Studio itself use the cache (optional follow-up)

Since Studio's basic thread-creation flow doesn't expose a `configurable` editor,
the most direct way to test caching *through Studio's UI* rather than the SDK is to
create a LangGraph **assistant** with a default config that sets
`configurable.test_mode: true`, then start threads against that assistant instead
of the graph's default one:

```python
assistant = await client.assistants.create(
    graph_id="lodging",
    config={"configurable": {"test_mode": True}},
    name="lodging-test-mode",
)
```

Any thread started in Studio against `lodging-test-mode` should then inherit
`test_mode: true` automatically, without needing the SDK for every run. This
hasn't been verified against your current Studio version — treat it as the next
thing to try if you want cache testing available directly through the UI.