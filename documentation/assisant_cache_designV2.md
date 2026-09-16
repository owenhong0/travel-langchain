# Test-Mode Response Caching — Design & Implementation Notes

## Goal

Enable a `test_mode` flag that, when set on a LangGraph run's `config.configurable`,
transparently caches Tavily search/extract calls and LLM invocations against a Postgres
table — so repeated development/testing runs against the same inputs skip real API calls
entirely, cutting both cost and latency to near-zero on a cache hit.

Scope grew over the course of the night from "cache Tavily calls" to "cache literally
every external call" (Tavily search, Tavily extract, structured LLM output, and plain
LLM invokes) across all three planning subgraphs (`trip_info_graph.py`,
`leg_transportation_graph.py`, `lodging_graph.py`) plus the frontend.

## Architecture

### The cache table

```sql
CREATE TABLE test_response_cache (
    id               SERIAL PRIMARY KEY,
    cache_key        CHAR(64) NOT NULL UNIQUE,
    call_type        TEXT NOT NULL,
    schema_version   TEXT NOT NULL,
    input_snapshot   JSONB NOT NULL,
    output_snapshot  JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_test_cache_call_type ON test_response_cache (call_type);
CREATE INDEX idx_test_cache_lookup ON test_response_cache (cache_key);
```

`call_type` values in use: `tavily_search`, `tavily_extract`, `llm_structured`, `llm_plain`.

### Cache key derivation

```python
def _cache_key(call_type: str, args: dict) -> str:
    canonical = json.dumps(args, sort_keys=True, default=str)
    raw = f"{call_type}|{CACHE_SCHEMA_VERSION}|{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

Deterministic exact-match hashing — same `call_type` + `CACHE_SCHEMA_VERSION` + args
always produces the same key, regardless of dict key ordering. **Note:** this is
exact-match only, not semantic/similarity-based. Two prompts that are conceptually
equivalent but differ even slightly in wording, ordering, or upstream content will
produce different hashes and miss independently. See "Known limitation" below.

`graph_id` and `assistant_id` are intentionally excluded from the hash — a call with
identical arguments hits the same cache row regardless of which graph or assistant
triggered it (confirmed: Studio's `lodging` graph and the frontend's `orchestrator`
graph, which wires `lodging_graph` as a subgraph, share cache rows for identical calls).

### Four wrapper functions (`cache_utils.py`)

| Function | Wraps | Cache-miss behavior |
|---|---|---|
| `cached_tavily_search` | `TavilySearch(**kwargs).invoke(args)` | Live search, then store |
| `cached_tavily_extract` | `TavilyExtract(**kwargs).invoke(args)` | Live extract, then store |
| `cached_invoke_structured_with_retry` | the existing custom `invoke_structured_with_retry` (retry/validation loop) | Live structured call (with existing retry logic), store `result.model_dump()` |
| `cached_invoke` | a plain `.invoke()` call (no schema) | Live call, store `{content, name}`, reconstructed as `AIMessage` on hit |

All four follow the same shape: check `config.configurable.test_mode`; if true, look up
by `_cache_key`; on miss, run live and store; on hit, return the stored value
(deserializing back into a Pydantic model or `AIMessage` as appropriate) without
touching the network.

`cached_invoke_structured_with_retry` deliberately does **not** add its own
`.with_retry()` layer — it wraps the existing custom retry loop
(`invoke_structured_with_retry`), which already handles `ValidationError`,
`APIStatusError`, `ValueError`, and a `bad_field` structured-output recovery path.
Stacking `.with_retry()` on top would risk double-retrying and could interfere with
that recovery logic.

`cached_invoke` (for plain, non-structured LLM calls) is paired with a dedicated
`retryable_llm = interview_llm.with_retry(...)` instance, since a bare `.invoke()` has
no retry logic of its own.

## Implementation across the codebase

### Assistant setup in LangGraph Studio

1. Created a `lodging-test-mode` assistant via SDK (`assistants.create(graph_id="lodging",
   config={"configurable": {"test_mode": True}})`).
2. Confirmed it appears in Studio's ASSISTANTS panel once the graph dropdown is switched
   to match `graph_id`.
3. **Critical step easy to miss:** creating/selecting the assistant in the list is not
   enough — its "Active" toggle must be switched on and saved, or new threads still
   default to "Default Configuration" (no `test_mode`).

### Call sites converted (all three subgraphs)

- **`trip_info_graph.py`**: `create_analysts`, `search_gov_travel`,
  `search_travel_magazines`, `search_unique_experiences`, `extract_candidates`,
  `order_destinations`, `compute_dates` → `cached_invoke_structured_with_retry`.
  `generate_question`, `generate_answer`, `write_section` → `cached_invoke`. Also fixed
  a latent bug: `retryable_llm` was built from the premium tier (`llm`) instead of the
  intended mid tier (`interview_llm`), silently running these three functions on
  Claude Sonnet 5 instead of Haiku 4.5.
- **`leg_transportation_graph.py`**: `search_route_options`, `verify_route_options`,
  `search_car_rental`, `recommend_leg_options` → `cached_invoke_structured_with_retry`,
  matching each function's existing model tier (`llm`/`premium` or
  `extraction_llm`/`cheap`).
- **`lodging_graph.py`**: `_run_stay_search` (shared by `search_agoda`,
  `search_hotel_chains`, `search_general_ota`, `search_unique_stays`) gained a
  `model_tag` parameter threaded from each caller; `search_rates_direct`,
  `enrich_points_value`, `recommend_stay_options` also converted.
  `recommend_stay_options` was missing `config: RunnableConfig` entirely and needed it
  added before it could be wired in.

### Frontend (`useTripThread.ts`)

Added a permanent, env-driven toggle rather than a second `orchestrator-test-mode`
assistant, to match the existing `VITE_LANGGRAPH_API_URL` convention:

```typescript
const TEST_MODE = import.meta.env.VITE_TEST_MODE === "true";
```

Passed as `config: {configurable: {test_mode: TEST_MODE}}` on all three `thread.submit`
call sites (`start`, `resume`, `forkFrom`) in `useTripThread.ts`. Confirmed via browser
DevTools Network tab that the flag reaches the backend correctly in the request payload.

## Verification results

| Subgraph | Call types confirmed caching | Verification method |
|---|---|---|
| `lodging` | `tavily_search`, `tavily_extract`, `llm_structured` | Studio: miss run (545s/$0.38) → hit run (target nodes collapsed to near-zero) |
| `trip_info` | `tavily_search`, `llm_structured`, `llm_plain` | Studio: `create_analysts` hit at 0.05s from earlier SDK testing; `generate_question`/`generate_answer` populated on first run |
| `leg_transportation` | not independently re-verified tonight | code converted, same pattern as the other two |
| Frontend (`orchestrator`) | confirmed `test_mode: true` reaches backend | DevTools payload inspection |

Final cache table state at end of session:

```
   call_type    | count
----------------+-------
 tavily_search  |    75
 tavily_extract |    12
 llm_plain      |    45
 llm_structured |    61
```

## Debugging notes / gotchas hit along the way

- **Docker vs. `langgraph dev`**: code edits on the host don't reach a running
  `langgraph-api` container unless the volume is bind-mounted (it was, in this repo) —
  a plain `docker compose restart langgraph-api` was sufficient; no rebuild needed. When
  in doubt: `docker exec -it <container> grep -n <symbol> <file>` confirms what code the
  container is actually running.
- **Container naming**: Compose containers are named `<project>-<service>-<n>`, not the
  Compose project name itself (`travel-langchain` ≠ a container).
- **Studio's Input box "As Node" dropdown**: leaving this set to a non-default node
  fast-forwards past earlier nodes and injects your submitted JSON as if it were *their
  output* — not as the initial graph state. Clear it back to default before submitting a
  normal `__start__` input.
- **`dated_itinerary` shape**: must be a list of leg dicts, not a single dict — an early
  malformed test input caused a `KeyError('dated_itinerary')` in `derive_stay_legs` that
  looked like a code bug but was an input-shape mistake.
- **A cache miss can look identical to caching being broken**: any run against content
  that's never been cached before (even if you've "run this exact graph before") is a
  true first-time miss if the caching code didn't exist yet at the time of that earlier
  run, or if any upstream node's output diverged even slightly.

## Known limitation: exact-match only, not semantic

The cache only hits on byte-identical `(call_type, schema_version, args)` triples. In a
multi-step pipeline with a `Send()` fan-out over parallel analyst interviews
(`trip_info_graph.py`'s `conduct_interview`), a single upstream divergence — e.g. one
analyst's question/answer exchange taking a slightly different path due to an uncached
Tavily result — changes that analyst's `write_section` output, which changes
`extract_candidates`' input, which changes `order_destinations`' input, and so on:
every downstream node from that point misses, even though the original
`trip_preferences` text was identical between runs. Confirmed by comparing
`input_snapshot` rows directly: one run's `extract_candidates` output had 6
destinations, another had 7 (including `38th Parallel Beach` only in one), despite
identical starting text.

This is inherent to hash-based exact-match caching and not a bug in this
implementation. Genuine near-match/semantic caching (e.g. embedding-based similarity
lookup with a threshold) would be a separate, larger design effort — noted as a
possible future direction, not undertaken tonight.

## Open follow-ups (not completed tonight)

- `leg_transportation_graph.py`'s caching wasn't independently re-verified through
  Studio the way `lodging` and `trip_info` were (miss run → hit run comparison).
- Whether `cached_invoke`'s two-field `AIMessage` reconstruction (`content` + `name`
  only) is sufficient for everything `route_messages` and the rest of `InterviewState`
  read off cached messages — flagged as worth checking but not yet tested.
- `search_gov_travel`, `search_travel_magazines`, `search_unique_experiences` still use
  the premium tier (`llm`) for a single-string `SearchQuery` generation — a possible
  candidate for the mid/cheap tier, independent of caching, not addressed tonight.