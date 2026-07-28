import operator
import os
from enum import Enum
from typing import Annotated, TypedDict

import requests
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from pydantic import Field, BaseModel
from langchain_tavily import TavilySearch
from duffel_api import Duffel
from dotenv import load_dotenv

load_dotenv()

agent = ChatAnthropic(model="claude-sonnet-5")

duffel_api_key = os.getenv("DUFFEL_API_KEY")

client = Duffel(access_token=duffel_api_key)

class loyalty_programs(Enum):
    "BA"

class GraphState(TypedDict):
    flight_query: FlightQuery
    context: list

class SearchQuery(BaseModel):
    search_query: str = Field(None, description="Search query for retrieval.")

class Passenger(BaseModel):
    loyalty_programme_accounts: list[str]
    fare_type: str
    family_name: str
    given_name: str
    age: int
    type: str
    id: str

class FlightQuery(BaseModel):
    origin: str
    destination: str
    round_trip: bool
    stops_allowed: bool
    departure_date: str
    returning_date: str
    passengers: list[Passenger]

    context: list



search_instructions = SystemMessage(content="""You will be given a conversation.
Convert the user's request into a well-structured web search query for flight prices.""")

DUFFEL_VERSION = "v2"  # check Duffel's docs/changelog for the current value
BASE_URL = "https://api.duffel.com"

def user_input(state: GraphState):
    input("Where would you like to fly to? Please make sure to input")
def search_cash_fare(state: GraphState):
    headers = {
        "Authorization": f"Bearer {duffel_api_key}",
        "Duffel-Version": DUFFEL_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "data": {
            "slices": [{
                "origin": state["flight_query"].origin,
                "destination": state["flight_query"].destination,
                "departure_date": state["flight_query"].departure_date,
            }],
            "passengers": [{"type": "adult"}],
        }
    }
    resp = requests.post(f"{BASE_URL}/air/offer_requests?return_offers=true",
                          json=payload, headers=headers)
    resp.raise_for_status()
    offers = resp.json()["data"]["offers"]

    parsed = [
        {"airline": o["owner"]["name"], "cash_price": float(o["total_amount"]), "currency": o["total_currency"]}
        for o in offers
    ]
    return {"context": parsed}

graph = StateGraph(GraphState)
graph.add_node("init_user_input", user_input)
graph.add_node("search_web", search_cash_fare)
graph.add_edge(START, "search_web")
graph.add_edge("search_web", END)
compiled = graph.compile()

result = compiled.invoke({
    "origin": "BOS",
    "destination": "NRT",
    "date": "2026-09-22",
    "context": [],
})
print(result)