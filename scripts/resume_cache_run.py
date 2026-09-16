import asyncio
from langgraph_sdk import get_client
from langgraph_sdk.schema import Command

TUNNEL_URL = "https://butler-shepherd-barnes-andrews.trycloudflare.com"
THREAD_ID = "01a0a85a-6c19-73e3-a3f0-fdd4671971a9"

async def main():
    client = get_client(url=TUNNEL_URL)
    async for chunk in client.runs.stream(
        THREAD_ID, "lodging",
        command=Command(resume="approve"),
        config={"configurable": {"test_mode": True}},   # must repeat this here
    ):
        print(chunk)

if __name__ == "__main__":
    asyncio.run(main())