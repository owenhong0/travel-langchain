# webapp.py
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres import PostgresSaver

from checkpoint_utils import discover_checkpoint_namespaces
from trip_orchestrator import builder

app = FastAPI()

# The frontend runs on a different port during dev (Vite), so this needs CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # adjust to your actual dev/prod origins
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/interrupt-history/{thread_id}")
def get_interrupt_history(thread_id: str):
    conn_string = os.environ["POSTGRES_URI"]  # confirm this matches your compose env

    hits = []
    with PostgresSaver.from_conn_string(conn_string) as saver:
        graph = builder.compile(checkpointer=saver)
        for checkpoint_ns in discover_checkpoint_namespaces(thread_id, conn_string):
            config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
            for snap in graph.get_state_history(config):
                if not snap.tasks or not snap.tasks[0].interrupts:
                    continue
                interrupt_value = snap.tasks[0].interrupts[0].value
                hits.append({
                    "interrupt_type": interrupt_value.get("type", "unknown"),
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": snap.config["configurable"]["checkpoint_id"],
                    "next": list(snap.next),
                    "values": snap.values,
                    "interrupt_value": interrupt_value,
                })

    hits.sort(key=lambda h: h["checkpoint_id"])
    return {"thread_id": thread_id, "count": len(hits), "snapshots": hits}