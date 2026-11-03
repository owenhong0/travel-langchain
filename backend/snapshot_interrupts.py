"""
scripts/snapshot_interrupts.py

Read-only getter for LangGraph interrupt snapshots. Recompiles the graph
locally with a PostgresSaver pointed at the real database (rather than
importing trip_orchestrator.graph, which is baked with InMemorySaver and
has no real history). Walks every checkpoint_ns for a thread, since
interrupts inside subgraphs and Send() fan-out branches live under
dynamic nested namespaces.

Usage:
    python scripts/snapshot_interrupts.py --thread-id <id> --conn-string "postgresql://user:pass@localhost:5432/dbname"
    python scripts/snapshot_interrupts.py --thread-id <id> --conn-string "..." --interrupt-type date_review
    python scripts/snapshot_interrupts.py --thread-id <id> --conn-string "..." --latest-only
    python scripts/snapshot_interrupts.py --thread-id <id> --conn-string "..." --out snapshots.json

Or set POSTGRES_CONN_STRING in your shell so you don't have to pass --conn-string each time:
    export POSTGRES_CONN_STRING="postgresql://user:pass@localhost:5432/dbname"
"""

import argparse
import json
import os
from datetime import datetime, timezone

import psycopg2
from langgraph.checkpoint.postgres import PostgresSaver

from trip_orchestrator import builder  # the uncompiled StateGraph, before .compile() is called


def discover_checkpoint_namespaces(thread_id: str, conn_string: str) -> list[str]:
    """All checkpoint_ns values for this thread — parent ("") plus every
    nested subgraph invocation and Send() fan-out branch, each with its
    own dynamic task UUID."""
    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT checkpoint_ns FROM checkpoints WHERE thread_id = %s",
                (thread_id,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def snapshot_all_interrupts(graph, thread_id: str, conn_string: str) -> list[dict]:
    """Walk every checkpoint_ns for this thread and return every checkpoint
    where an interrupt was pending, tagged by interrupt type and namespace."""
    hits = []
    for checkpoint_ns in discover_checkpoint_namespaces(thread_id, conn_string):
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
        for snap in graph.get_state_history(config):
            if not snap.tasks or not snap.tasks[0].interrupts:
                continue
            interrupt_value = snap.tasks[0].interrupts[0].value
            hits.append({
                "interrupt_type": interrupt_value.get("type", "unknown"),
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": snap.config["configurable"]["checkpoint_id"],
                "next": list(snap.next),
                "values": snap.values,
            })
    return hits


def snapshot_latest_interrupt(graph, thread_id: str) -> dict | None:
    """Just the current pending interrupt, if the thread is paused right now.
    No namespace looping needed — the top-level task's interrupts always
    reflect whatever is currently pending, even inside a nested subgraph."""
    config = {"configurable": {"thread_id": thread_id}}
    state = graph.get_state(config)

    if not state.tasks or not state.tasks[0].interrupts:
        return None

    interrupt_value = state.tasks[0].interrupts[0].value
    return {
        "interrupt_type": interrupt_value.get("type", "unknown"),
        "thread_id": thread_id,
        "checkpoint_id": state.config["configurable"]["checkpoint_id"],
        "next": list(state.next),
        "values": state.values,
    }


def main():
    parser = argparse.ArgumentParser(description="Query LangGraph interrupt snapshots for a thread")
    parser.add_argument("--thread-id", required=True)
    parser.add_argument(
        "--conn-string",
        default=os.environ.get("POSTGRES_CONN_STRING"),
        help="Postgres connection string. Falls back to POSTGRES_CONN_STRING env var if not passed.",
    )
    parser.add_argument("--interrupt-type", help="Filter to one of the 8 interrupt types (e.g. date_review)")
    parser.add_argument("--latest-only", action="store_true", help="Only the current pending interrupt, not full history")
    parser.add_argument("--out", help="Write results to this JSON path instead of stdout")
    args = parser.parse_args()

    if not args.conn_string:
        parser.error("No connection string provided. Pass --conn-string or set POSTGRES_CONN_STRING.")

    with PostgresSaver.from_conn_string(args.conn_string) as saver:
        graph = builder.compile(checkpointer=saver)

        if args.latest_only:
            result = snapshot_latest_interrupt(graph, args.thread_id)
            results = [result] if result else []
        else:
            results = snapshot_all_interrupts(graph, args.thread_id, args.conn_string)

    if args.interrupt_type:
        results = [r for r in results if r["interrupt_type"] == args.interrupt_type]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thread_id": args.thread_id,
        "count": len(results),
        "snapshots": results,
    }

    if args.out:
        with open(args.out, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Wrote {len(results)} snapshot(s) to {args.out}")
    else:
        print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()