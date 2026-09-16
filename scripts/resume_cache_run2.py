# scripts/resume_cache_run_2.py
import asyncio
from langgraph_sdk import get_client
from langgraph_sdk.schema import Command

TUNNEL_URL = "https://butler-shepherd-barnes-andrews.trycloudflare.com"
THREAD_ID = "01a0a85f-8cd9-7110-aea0-9e881e6dc770"

async def main():
    client = get_client(url=TUNNEL_URL)
    async for chunk in client.runs.stream(
        THREAD_ID, "lodging",
        command=Command(resume="approve"),
        config={"configurable": {"test_mode": True}},
    ):
        print(chunk)

if __name__ == "__main__":
    asyncio.run(main())