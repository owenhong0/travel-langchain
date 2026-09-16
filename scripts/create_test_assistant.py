import asyncio
from langgraph_sdk import get_client

TUNNEL_URL = "http://localhost:2024"
ASSISTANT_NAME = "lodging-test-mode"

async def main():
    client = get_client(url=TUNNEL_URL)

    # Idempotency: avoid creating duplicate assistants on reruns
    existing = await client.assistants.search(graph_id="lodging", limit=50)
    match = next((a for a in existing if a.get("name") == ASSISTANT_NAME), None)
    if match:
        print("Already exists:", match["assistant_id"])
        return

    try:
        assistant = await client.assistants.create(
            graph_id="lodging",
            config={"configurable": {"test_mode": True}},
            name=ASSISTANT_NAME,
        )
    except Exception as e:
        # Surface this clearly — answers your open question about whether
        # graph_id must be one of the five registered top-level graphs
        print("assistants.create() failed — graph_id may not accept a subgraph directly:", e)
        raise

    print("Created:", assistant["assistant_id"])

if __name__ == "__main__":
    asyncio.run(main())