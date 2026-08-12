import operator
import os
import re
import threading
import time
from datetime import date
from enum import Enum
from multiprocessing import context
from typing import Annotated, TypedDict, Literal, Optional

import requests
from anthropic.resources.beta.messages import messages
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.types import Send, interrupt, Command
from pydantic import Field, BaseModel, ValidationError
from langchain_tavily import TavilySearch
from duffel_api import Duffel
from dotenv import load_dotenv

from models import extract_offer

load_dotenv()

duffel_api_key = os.getenv("DUFFEL_API_KEY")
DUFFEL_BASE_URL = "https://api.duffel.com"

client = Duffel(access_token=duffel_api_key)

router_llm = ChatOpenAI(
    model="anthropic/claude-sonnet-5",
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

DUFFEL_VERSION = "v2"  # check Duffel's docs/changelog for the current value
BASE_URL = "https://api.duffel.com"

class loyalty_programs(Enum):
    "BA"

class GraphState(TypedDict):
    user_message: str
    flight_query: dict
    resolved_origins: list[str]
    resolved_destinations: list[str]
    origin: Optional[str]  # NEW — per-branch value set only via Send payload
    destination: Optional[str]  # NEW — per-branch value set only via Send payload
    context: Annotated[list, operator.add]
    ranked_results: list

class SearchQuery(BaseModel):
    search_query: str = Field(None, description="Search query for retrieval.")

class Passenger(BaseModel):
    loyalty_programme_accounts: list[str] = Field(description="List of Airline Abbreviation loyalty programs enrolled.")
    fare_type: Literal["economy", "premium_economy", "business", "first"]
    family_name: str
    given_name: str
    age: int
    type: str
    id: str

class FlightQuery(BaseModel):
    origin: str = Field(description="The departure city or airport as stated by the user, unmodified.")
    destination: str = Field(description="The destination city or airport as stated by the user, unmodified.")
    round_trip: bool
    stops_allowed: bool
    departure_date: str = Field(description="ISO 8601 date format: YYYY-MM-DD")
    returning_date: str = Field(description="ISO 8601 date format: YYYY-MM-DD")
    fare_type: Literal["economy", "premium_economy", "business", "first"]
    passengers: list[Passenger]

# --- module-level cache state (place near the top, after duffel_api_key/client setup) ---
_airport_cache: list[dict] = []
_cache_refreshed_at: float = 0
_cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 24 * 60 * 60  # airports/cities rarely change; daily refresh is plenty

def _refresh_airport_cache():
    """Paginated crawl of Duffel's full airport catalog. Only reassigns _airport_cache
    once the whole crawl succeeds — a mid-crawl failure leaves the old (stale but valid)
    cache in place rather than replacing it with a partial one."""
    global _airport_cache, _cache_refreshed_at
    headers = {
        "Authorization": f"Bearer {duffel_api_key}",
        "Duffel-Version": DUFFEL_VERSION,
        "Accept": "application/json",
    }
    airports, cursor = [], None
    while True:
        params = {"limit": 200, **({"after": cursor} if cursor else {})}
        resp = requests.get(f"{DUFFEL_BASE_URL}/air/airports", params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        airports.extend(payload["data"])
        cursor = payload.get("meta", {}).get("after")
        if not cursor:
            break
    _airport_cache = airports
    _cache_refreshed_at = time.time()

def _prewarm_airport_cache():
    """Kicks off the crawl in a background thread at import time so the first real
    lookup during a request doesn't pay the full cold-start cost. Racing with the
    lock in duffel_places_lookup is fine — the lock's re-check handles it."""
    threading.Thread(target=_refresh_airport_cache, daemon=True).start()

_prewarm_airport_cache()


search_instructions = SystemMessage(content="""You will be given a conversation.
Convert the user's request into a well-structured web search query for flight prices.""")

def ensure_future_date(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    while d <= date.today():
        d = d.replace(year=d.year + 1)
    return d.isoformat()

def user_input(state: GraphState):
    today = date.today().isoformat()
    formatting_guidelines = SystemMessage(content=f"""
    Today's date is {today}. Convert the user's stated trip details into the FlightQuery fields.
    Do not resolve city names to airport codes — capture them exactly as stated.
    All dates must be in the future relative to today. If the user gives a date without
    a year, infer the year that makes it a future date.
    """)
    trip_info = HumanMessage(content=state["user_message"])

    agent = create_agent(model=router_llm, response_format=FlightQuery)
    response = agent.invoke({"messages": [formatting_guidelines,trip_info]})
    flight_query = response["structured_response"]
    flight_query.departure_date = ensure_future_date(flight_query.departure_date)
    if flight_query.round_trip:
        flight_query.returning_date = ensure_future_date(flight_query.returning_date)
    return {"flight_query": flight_query.model_dump(), "context": []}

def _match_airports(city_name: str) -> list[dict]:
    """Shared matching logic for duffel_places_lookup and duffel_city_coords.
    Tiered from strictest to loosest. The final tier checks BOTH directions —
    query-in-field and field-in-query — because traveler-facing city names
    ("New York City") don't always match Duffel's canonical city_name
    ("New York"); a one-directional check misses the shorter-field case."""
    q = city_name.strip().lower()
    if not q:
        return []

    def exact_code(a):
        return q == (a.get("iata_code") or "").lower() or q == (a.get("iata_city_code") or "").lower()

    def exact_name(a):
        return q == (a.get("city_name") or "").lower()

    word_re = re.compile(rf"\b{re.escape(q)}\b")
    def word_match(a):
        return bool(word_re.search((a.get("name") or "").lower())) or \
               bool(word_re.search((a.get("city_name") or "").lower()))

    def loose_match(a):
        name, city = (a.get("name") or "").lower(), (a.get("city_name") or "").lower()
        return (name and (q in name or name in q)) or (city and (q in city or city in q))

    for tier in (exact_code, exact_name, word_match):
        matches = [a for a in _airport_cache if tier(a)]
        if matches:
            return matches

    return [a for a in _airport_cache if loose_match(a)] if len(q) >= 3 else []

# main.py
def duffel_places_lookup(city_name: str) -> list[str]:
    if not _airport_cache or (time.time() - _cache_refreshed_at) > CACHE_TTL_SECONDS:
        with _cache_lock:
            if not _airport_cache or (time.time() - _cache_refreshed_at) > CACHE_TTL_SECONDS:
                _refresh_airport_cache()

    matches = _match_airports(city_name)
    city_codes = {a["iata_city_code"] for a in matches if a.get("iata_city_code")}
    if city_codes:
        return list(city_codes)
    return [a["iata_code"] for a in matches if a.get("iata_code")]

def duffel_city_coords(city_name: str) -> Optional[tuple[float, float]]:
    if not _airport_cache or (time.time() - _cache_refreshed_at) > CACHE_TTL_SECONDS:
        with _cache_lock:
            if not _airport_cache or (time.time() - _cache_refreshed_at) > CACHE_TTL_SECONDS:
                _refresh_airport_cache()

    for a in _match_airports(city_name):
        lat, lon = a.get("latitude"), a.get("longitude")
        if lat is not None and lon is not None:
            return (float(lat), float(lon))
    return None

def duffel_city_country(city_name: str) -> Optional[str]:
    """Best-effort ISO country code for a city, via the shared airport cache —
    used to populate origin_country/destination_country on the new home/return
    bookend legs so they work with the existing cross-country mode check."""
    if not _airport_cache or (time.time() - _cache_refreshed_at) > CACHE_TTL_SECONDS:
        with _cache_lock:
            if not _airport_cache or (time.time() - _cache_refreshed_at) > CACHE_TTL_SECONDS:
                _refresh_airport_cache()
    for a in _match_airports(city_name):
        code = a.get("iata_country_code")
        if code:
            return code
    return None

def resolve_iata_codes(state: GraphState):
    fq = FlightQuery.model_validate(state["flight_query"])
    return {
        "resolved_origins": duffel_places_lookup(fq.origin),
        "resolved_destinations": duffel_places_lookup(fq.destination),
    }

def validate_input(state: GraphState):
    fq = FlightQuery.model_validate(state["flight_query"])

    while True:
        errors = []
        if date.fromisoformat(fq.departure_date) <= date.today():
            errors.append(f"departure_date '{fq.departure_date}' is not in the future")
        if fq.round_trip and date.fromisoformat(fq.returning_date) <= date.fromisoformat(fq.departure_date):
            errors.append("returning_date must be after departure_date")

        if not errors:
            break  # validation passed — exit the loop and move on to review

        response = interrupt({
            "type": "schema_error",
            "errors": errors,
            "flight_query": fq.model_dump(),
        })
        fq = FlightQuery.model_validate(response["flight_query"])
        # loop repeats — re-checks the corrected query, interrupts again if still bad

    # Only reached once the query is genuinely valid
    response = interrupt({
        "type": "trip_review",
        "message": "Please review before we search for flights.",
        "flight_query": fq.model_dump(),
    })

    if response["type"] == "accept":
        return {"flight_query": fq.model_dump()}
    elif response["type"] == "edit":
        updated = {**fq.model_dump(), **response["edits"]}
        return {"flight_query": FlightQuery.model_validate(updated).model_dump()}
    else:
        raise ValueError(f"Unknown response type: {response['type']}")

def fan_out_airports(state: GraphState):
    """Conditional edge — Send() one branch per origin/destination pair."""
    branches = []
    for origin in state["resolved_origins"]:
        for destination in state["resolved_destinations"]:
            branches.append(Send("search_cash_fare", {
                "flight_query": state["flight_query"],
                "origin": origin,
                "destination": destination,
            }))
    return branches


# main.py
def fetch_flight_offers(origin: str, destination: str, departure_date: str, passenger_count: int) -> list[dict]:
    headers = {"Authorization": f"Bearer {duffel_api_key}", "Duffel-Version": DUFFEL_VERSION,
               "Content-Type": "application/json", "Accept": "application/json"}
    payload = {"data": {"slices": [{"origin": origin, "destination": destination,
                                     "departure_date": departure_date}],
                         "passengers": [{"type": "adult"}] * max(passenger_count, 1)}}
    resp = requests.post(f"{DUFFEL_BASE_URL}/air/offer_requests?return_offers=true",
                          json=payload, headers=headers)
    resp.raise_for_status()
    return [extract_offer(o).model_dump() for o in resp.json()["data"]["offers"]]

def search_cash_fare(state: GraphState):  # existing node now just calls the helper
    fq = FlightQuery.model_validate(state["flight_query"])
    parsed = fetch_flight_offers(state["origin"], state["destination"], fq.departure_date, len(fq.passengers))
    return {"context": parsed}

def rank_options(state: GraphState):
    ranked = sorted(state["context"], key=lambda o: o["price"]["total_amount"])
    return {"ranked_results": ranked}
### Graph

builder = StateGraph(GraphState)
builder.add_node("user_input", user_input)
builder.add_node("validate_input", validate_input)
builder.add_node("resolve_iata_codes", resolve_iata_codes)
builder.add_node("search_cash_fare", search_cash_fare)
builder.add_node("rank_options", rank_options)

builder.add_edge(START, "user_input")
builder.add_edge("user_input", "validate_input")
builder.add_edge("validate_input", "resolve_iata_codes")
builder.add_conditional_edges("resolve_iata_codes", fan_out_airports, ["search_cash_fare"])
builder.add_edge("search_cash_fare", "rank_options")
builder.add_edge("rank_options", END)



if __name__ == "__main__":
    config = {"configurable": {"thread_id": "1"}}
    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    result = graph.invoke({
        "user_message": input("""Where would you like to fly to? Please make sure to specify:
        1. Departing Location
        2. Destination City
        3. Departing Date
        4. Returning Date
        5. Number of Passengers
        6. Fare Type(s)
        7. Layovers? (Will be shown by default)
        8. Loyalty Programs (If Applicable)
    """),
            "flight_query": None,
            "resolved_origins": [],
            "resolved_destinations": [],
            "context": [],
        }, config=config)

    while "__interrupt__" in result:
        interrupt_data = result["__interrupt__"][0].value
        print(interrupt_data)

        if interrupt_data["type"] == "schema_error":
            corrected = interrupt_data["flight_query"].copy()
            print("Issues found:", *interrupt_data["errors"], sep="\n  - ")
            while True:
                field = input("Field to fix (blank to submit): ").strip()
                if not field:
                    break
                corrected[field] = input(f"New value for {field}: ")
            result = graph.invoke(Command(resume={"flight_query": corrected}), config=config)

        elif interrupt_data["type"] == "trip_review":
            approve = input("Approve trip? (y/n): ")
            if approve.lower() == "y":
                result = graph.invoke(Command(resume={"type": "accept"}), config=config)
            else:
                edits = {}
                while True:
                    field = input("Field to edit (blank to finish): ").strip()
                    if not field:
                        break
                    edits[field] = input(f"New value for {field}: ")
                result = graph.invoke(Command(resume={"type": "edit", "edits": edits}), config=config)

    print(result["ranked_results"])
else:
    graph = builder.compile()

'''
{
  "user_message": "I want to fly from Boston to Tokyo leaving August 22nd and returning September 10th for myself in economy class with no layovers",
  "context": [],
  "resolved_origins": [],
  "resolved_destinations": []
}
'''