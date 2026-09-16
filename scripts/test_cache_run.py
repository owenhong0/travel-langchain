# scripts/test_cache_run.py
import asyncio
from langgraph_sdk import get_client

TUNNEL_URL = "https://butler-shepherd-barnes-andrews.trycloudflare.com"

async def main():
    client = get_client(url=TUNNEL_URL)
    thread = await client.threads.create()
    print(f"thread_id: {thread['thread_id']}")

    async for chunk in client.runs.stream(
        thread["thread_id"], "lodging",   # graph_id, not orchestrator
        input={
            "dated_itinerary": [
                {"city": "Jeju-do", "country": "South Korea",
                 "depart_date": "2026-11-05", "return_date": "2026-11-08",
                 "duration_days": 3},
            ],
            "loyalty_programmes": [],
            "stay_legs": [],
            "finalized_stays": [],
        },
        config={"configurable": {"test_mode": True}},
    ):
        print(chunk)

if __name__ == "__main__":
    asyncio.run(main())