# LangGraph Interrupt Snapshots — Mechanisms & Implementation Notes

Reference doc covering the core mechanisms behind snapshotting graph state at
interrupts in `travel-langchain`, the bugs they caused, and how each was
resolved. Written for future-you (or a teammate) debugging something adjacent.

---

## 1. The core mechanism: checkpoints are full snapshots, not diffs

Every LangGraph checkpoint stores the **entire graph state** as it stood at
that moment — not a delta from the previous checkpoint. This is what lets
`Command(resume=...)` reconstruct execution from any single checkpoint without
replaying prior steps. It also means state naturally "grows" across
checkpoints (analysts populate, then sections, then destinations, etc.) —
that's the mechanism working correctly, not redundant storage.

**Read APIs:**
- `graph.get_state(config)` → current/latest state at a checkpoint
- `graph.get_state_history(config)` → full checkpoint history for a `config`
- Both wrap the underlying `checkpointer.list(...)` call

---

## 2. Checkpoint namespacing — the root cause of "missing" interrupts

Checkpoints are scoped by `checkpoint_ns`, not just `thread_id`. A **plain
`get_state_history(config)` call with no `checkpoint_ns` only returns the
root namespace (`""`)** — it does not recurse into nested subgraphs.

In this project, `trip_orchestrator.py` nests three subgraphs
(`trip_info`, `transportation`, `lodging`) as single nodes. Interrupts firing
*inside* those subgraphs live under dynamic namespaces like:

```
trip_info:<task-uuid>
trip_info:<task-uuid>|conduct_interview:<branch-uuid>   # Send() fan-out branches
```

The UUID segments are generated fresh per run — there is no stable namespace
string to hardcode. **Namespaces must be discovered dynamically per thread**:

```sql
SELECT DISTINCT checkpoint_ns FROM checkpoints WHERE thread_id = %s;
```

Then query each namespace separately and merge results. This was true both
for the debugging CLI script and, later, for the frontend's own `history`
array from the SDK — same underlying gap, two different symptoms.

---

## 3. The "frozen parent checkpoint" mirror artifact

While a subgraph is still running, the **parent orchestrator's own
checkpoint does not advance** — it stays frozen at whatever state existed the
moment the subgraph was entered (`next: ["trip_info"]`, near-empty `values`).

However, that frozen checkpoint's *attached pending interrupt* is **not**
frozen — it always reflects whichever interior interrupt is currently active
inside the subgraph at query time. Symptoms:

- Querying the same `checkpoint_id` repeatedly over time returns a
  **different `interrupt_type` each time**, tracking whatever's live inside
  the subgraph right now.
- Once real interrupt payloads were surfaced, this showed up as an apparent
  **duplicate**: a root-namespace entry reporting the same interrupt type as
  a genuinely distinct nested entry.

**Fix:** filter out any root-namespace (`checkpoint_ns == ""`) entry whose
`next[0]` matches the parent segment of another entry's `checkpoint_ns`
(e.g. root `next: ["trip_info"]` + a real `checkpoint_ns` starting with
`"trip_info:"` → the root entry is a mirror, drop it). Fixed at the API layer
(`webapp.py`) so every consumer gets correct data automatically.

---

## 4. Which checkpointer is *actually* in use — three different answers

`trip_orchestrator.py` compiles the graph three different ways depending on
how it's invoked:

| Invocation | Checkpointer | Real data? |
|---|---|---|
| `orchestrator = builder.compile()` (module level) | none | no |
| `if __name__ == "__main__":` block | `InMemorySaver()` | no — fresh & empty every run |
| Plain import (`else` branch) | none | no — this caused the original `ValueError: No checkpointer set` |
| **LangGraph Platform** (`langgraph-api`, via `langgraph.json`) | **injected by the platform** | **yes — this is the real one** |

None of the checkpointers explicitly written in the source file are the one
actually holding production data. The platform overrides/ignores whatever
`.compile()` was given and injects its own Postgres-backed persistence,
configured via the deployment's own environment. **To read real data, you
must either go through the platform (SDK client) or recompile the graph
yourself with your own `PostgresSaver` pointed at the same database** — never
rely on the source file's own compiled `graph`/`orchestrator` objects.

---

## 5. Custom routes on LangGraph Platform (`webapp.py`)

LangGraph Platform supports mounting a custom FastAPI app alongside the
graph via `langgraph.json`:

```json
"http": { "app": "./webapp.py:app" }
```

This app runs **inside the same container/process** as the platform, so it
can share the same Postgres connection info via `os.environ`. This became the
correct home for namespace-aware interrupt history: the frontend cannot
reach Postgres directly (no credentials in the browser), and the SDK's own
`getHistory()` doesn't walk nested namespaces — a custom route closes that
gap without duplicating a data path the platform already half-serves.

**Important gotcha:** any middleware added here (e.g. `CORSMiddleware`) is
**global** — it applies to the platform's built-in routes too, not just your
custom ones. Scoping `allow_methods=["GET"]` to match only your own route's
needs will break the platform's own `POST /threads` etc. Use `allow_methods:
["*"]` unless you have a specific reason to restrict it, and know that the
restriction is felt project-wide.

---

## 6. Dependency management traps specific to this setup

- `langgraph.json`'s `"dependencies": ["."]` looks for `pyproject.toml`,
  `setup.py`, **or** `requirements.txt` in the project root — whichever
  exists. Anything importable in your local venv must *also* be declared
  there, or it silently works locally and breaks in the built image.
- `langgraph-checkpoint-postgres` (for `PostgresSaver`) uses **`psycopg`
  (v3)**, not `psycopg2`. Don't mix drivers across files unless you have a
  reason to — it doubles what needs installing for no benefit.
- `psycopg[binary]` needs quoting in zsh (`"psycopg[binary]"`) or the shell
  interprets the brackets as a glob and silently drops the argument.

---

## 7. Frontend: live state vs. historical state are two different data sources

**The rule:** one boolean (`isLive` / `!viewingCheckpointId`) decides which of
two completely separate sources a component reads from.

- **Live** (the one interrupt currently being worked through) — driven by
  the SDK's real-time streaming state (`useStream`'s `interrupt`,
  `isLoading`). Never touches the namespace-aware endpoint.
- **Historical** (everything else: a single resolved step, or the full
  progress sidebar) — always reads from the `/interrupt-history/{thread_id}`
  endpoint's response, fetched once per thread load and refreshed after
  `resume`/`forkFrom` succeed (not polled).

### The bug this replaced

The original historical branch tried to reconstruct interrupt data from a
**session-local tracker** (`useInterruptHistory`) that only knew about
interrupts *lived through in the current browser session* — empty on refresh
or deep link. When it missed, the code **fabricated placeholder content**
(`"Historical Data — Not Available"`) instead of falling back to the real,
already-fetched checkpoint snapshot that was sitting right there. Root fix:
stop reconstructing from an ephemeral cache; read the real payload from the
namespace-aware endpoint instead.

### `forkFrom` needs `checkpoint_ns`, not just `checkpoint_id`

Resuming/forking from a **nested** historical interrupt (e.g. one inside
`trip_info`) requires passing the correct `checkpoint_ns` along with the
`checkpoint_id` — a hardcoded `checkpoint_ns: ""` only worked before because
nothing nested was ever reachable to fork from in the first place.

---

## 8. Retired/superseded pieces

Once the namespace-aware endpoint + `interruptHistory` were wired through:

- `useInterruptHistory.ts` (session-only tracker) — superseded
- `ThreadHistoryProvider` / `useThreadHistoryContext` — was never wired in,
  and had the same namespace-blindness the tracker was working around
- `wizard_progress` (backend `OrchestratorState` field + `merge_step_data`
  reducer) — redundant once every real answer already lives in a checkpoint
  snapshot; don't need a second accumulator tracking the same information

---

## 9. Debugging habits that paid off repeatedly

- **Test one variable at a time.** Several rounds of "fix one error, hit the
  next" (fastapi → psycopg2 → CORS → stale container) were each solved
  faster by reading the *next* traceback carefully rather than guessing
  ahead at what else might be wrong.
- **Distrust container names that look auto-generated** (`unruffled_ellis`
  vs. `travel-langchain-langgraph-api-1`) — it's a strong signal that
  `docker compose up` was never actually run for that stack.
- **`docker ps` before `docker logs`** — confirms you're looking at the
  container you think you are.
- **`curl` the backend directly before touching the frontend** — isolates
  "is the data right" from "is the UI reading it right."