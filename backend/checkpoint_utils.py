# checkpoint_utils.py
import psycopg

def discover_checkpoint_namespaces(thread_id: str, conn_string: str) -> list[str]:
    """All checkpoint_ns values for this thread — parent ("") plus every
    nested subgraph invocation and Send() fan-out branch."""
    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT checkpoint_ns FROM checkpoints WHERE thread_id = %s",
                (thread_id,),
            )
            return [row[0] for row in cur.fetchall()]