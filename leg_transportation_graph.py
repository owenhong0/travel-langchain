# leg_transportation_graph.py
import json
import operator
import os
import re
from typing import Annotated, TypedDict, Optional, Literal
from urllib.parse import urlparse

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import Send, interrupt, Command
from pydantic import BaseModel, Field

from trip_info_graph import invoke_structured_with_retry, APPROVE_SIGNALS
from main import fetch_flight_offers, duffel_places_lookup

llm = ChatOpenAI(
    model="anthropic/claude-sonnet-5",
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# ---------- Schemas ----------

class TransportSegment(BaseModel):
    mode: Literal["flight", "train", "bus", "car", "ferry"]
    provider: Optional[str] = None
    duration: Optional[str] = None

class TransportOption(BaseModel):
    mode: Literal["flight", "train", "bus", "car", "ferry", "combined"]
    provider: Optional[str] = None
    price_estimate: Optional[str] = None
    duration: Optional[str] = None
    booking_url: Optional[str] = None
    segments: Optional[list[TransportSegment]] = None  # populated when mode == "combined"

class RouteOptions(BaseModel):
    options: list[TransportOption] = Field(
        description="Every distinct viable non-flight option found on this ONE route "
                    "comparison page — train, bus, ferry, and/or combined routes, if the "
                    "page shows them. Do not invent options not shown."
    )

class LegRecommendation(BaseModel):
    ranked_option_indices: list[int] = Field(description="Indices into the options list, best first")
    reasoning: str = Field(description="1-2 sentences on why the top choice makes sense for this leg")

class Leg(TypedDict):
    origin: str
    destination: str
    origin_country: str
    destination_country: str
    depart_date: str
    requires_flight_or_ferry: bool
    modes_requested: list[str]

class LegTransportState(TypedDict):
    leg: Leg
    raw_options: Annotated[list[dict], operator.add]  # parallel search writes, never cleared
    reconciled_options: list[dict]                     # this round's merged/confidence-tagged options, single-writer
    options: list[dict]                                # recommended/ordered snapshot, single-writer
    recommendation_reasoning: Optional[str]
    search_round: int
    selected: Optional[dict]
    review_decision: Optional[str]
    review_feedback: Optional[str]
    finalized_legs: Annotated[list[dict], operator.add]

class TransportPlanningState(TypedDict):
    dated_itinerary: list[dict]
    legs: list[Leg]
    finalized_legs: Annotated[list[dict], operator.add]

# ---------- Leg derivation & mode classification ----------

def derive_legs(state: TransportPlanningState):
    stops = state["dated_itinerary"]
    legs = [{
        "origin": stops[i]["city"],
        "destination": stops[i + 1]["city"],
        "origin_country": stops[i]["country"],
        "destination_country": stops[i + 1]["country"],
        "depart_date": stops[i]["return_date"],
        # a leg needs flight/ferry if EITHER end of it is flagged — reaching an island
        # matters regardless of which direction you're traveling
        "requires_flight_or_ferry": stops[i].get("requires_flight_or_ferry", False)
                                     or stops[i + 1].get("requires_flight_or_ferry", False),
    } for i in range(len(stops) - 1)]
    return {"legs": legs}

# Known island/archipelago destinations where ground transport (train/bus/car) to the
# mainland isn't possible — flight or ferry only, regardless of same-country status.
# Extend this list as new destinations come up; it's intentionally small and explicit
# rather than trying to infer "island-ness" from an LLM, which is error-prone for a
# binary feasibility gate like this.
ISLAND_DESTINATIONS = {
    "jeju", "okinawa", "bali", "phuket", "boracay", "santorini", "mykonos",
    "hawaii", "maui", "oahu", "sicily", "sardinia", "corsica",
}

def _is_island(place_name: str) -> bool:
    lowered = place_name.lower()
    return any(island in lowered for island in ISLAND_DESTINATIONS)

def _suggest_modes(leg: dict) -> list[str]:
    if _is_island(leg["origin"]) or _is_island(leg["destination"]):
        return ["flight", "ferry"]
    if leg["origin_country"] != leg["destination_country"]:
        return ["flight"]
    return ["train", "bus", "car"]

def _apply_mode_overrides(suggestions: list[dict], raw: str) -> list[dict]:
    # raw format: "0: flight,train | 1: car"
    overrides = {}
    for chunk in raw.split("|"):
        idx, _, modes = chunk.partition(":")
        if idx.strip().isdigit():
            overrides[int(idx.strip())] = [m.strip() for m in modes.split(",") if m.strip()]
    return [
        {**leg, "modes_requested": overrides.get(i, leg["modes_requested"])}
        for i, leg in enumerate(suggestions)
    ]

def classify_leg_modes(state: TransportPlanningState):
    suggestions = [{**leg, "modes_requested": _suggest_modes(leg)} for leg in state["legs"]]
    raw = interrupt({
        "type": "transport_mode_review",
        "message": "Confirm modes per leg (e.g. '0: flight,train | 1: car'), or 'approve' for defaults.",
        "legs": suggestions,
    })
    legs = suggestions if raw.strip().lower() in APPROVE_SIGNALS else _apply_mode_overrides(suggestions, raw)
    return {"legs": legs}

def fan_out_legs(state: TransportPlanningState):
    return [Send("plan_leg", {"leg": leg, "options": [], "raw_options": []}) for leg in state["legs"]]

def fan_out_modes(state: LegTransportState):
    """One Send per DISTINCT search node needed. Train/bus/ferry/combined all come from
    the same Rome2Rio route page, so they share one search node rather than three+
    uncoordinated calls that can disagree with each other. verify_route_options runs in
    parallel as an independent corroboration source (operator sites, not Rome2Rio)."""
    modes = set(state["leg"]["modes_requested"])
    sends = []
    if "flight" in modes:
        sends.append(Send("search_flight", state))
    if modes & {"train", "bus", "ferry"}:
        sends.append(Send("search_route_options", state))
        sends.append(Send("verify_route_options", state))
    if "car" in modes:
        sends.append(Send("search_car_rental", state))
    return sends

# ---------- Domain configuration ----------

# Flat lists — used as a last-resort backfill only when live discovery + the
# country-specific map both come up thin. Not the primary mechanism for any region.
RAIL_DOMAINS = ["raileurope.com", "trainline.com", "omio.com"]
BUS_DOMAINS = ["flixbus.com", "busbud.com"]

RAIL_DOMAINS_BY_COUNTRY = {
    "default": RAIL_DOMAINS,
    "South Korea": ["korail.com", "letskorail.com", "kr.trip.com"],
    "Japan": ["jorudan.co.jp", "hyperdia.com", "japanrailpass.net"],
}
BUS_DOMAINS_BY_COUNTRY = {
    "default": BUS_DOMAINS,
    "South Korea": ["kobus.co.kr", "bustago.or.kr", "kr.trip.com"],
}
FERRY_DOMAINS = ["directferries.com", "ferryhopper.com"]
CAR_RENTAL_DOMAINS = ["kayak.com", "rentalcars.com", "expedia.com"]
ROME2RIO_DOMAIN = ["rome2rio.com"]

def _flatten_by_country(country: str, *domain_maps: dict) -> list[str]:
    """Look up each domain map for this country (falling back to its 'default' entry)
    and flatten into one deduped list."""
    out: list[str] = []
    for dm in domain_maps:
        for d in dm.get(country, dm["default"]):
            if d not in out:
                out.append(d)
    return out

_domain_cache: dict[tuple[str, str], list[str]] = {}

# ---------- Shared helpers ----------

def _tavily_results(data) -> list[dict]:
    """TavilySearch.invoke() can return a plain string (error/status message)
    instead of the expected {"results": [...]} dict — normalize defensively."""
    if isinstance(data, dict):
        return data.get("results", [])
    return []

def discover_relevant_domains(
    query_hint: str, cache_key: tuple[str, str], max_domains: int = 4
) -> list[str]:
    """Unrestricted search to find likely authoritative domains for this leg's
    destination/mode. Cached per (country, mode) so re-search rounds and other
    legs in the same country don't re-pay the discovery call. This is the PRIMARY
    domain-selection path — static lists are only a backfill when this is thin."""
    if cache_key in _domain_cache:
        return _domain_cache[cache_key]
    data = TavilySearch(max_results=5).invoke({"query": query_hint})
    domains = []
    for r in _tavily_results(data):
        domain = urlparse(r["url"]).netloc.replace("www.", "")
        if domain and domain not in domains:
            domains.append(domain)
    domains = domains[:max_domains]
    _domain_cache[cache_key] = domains
    return domains

def _place_tokens(name: str) -> list[str]:
    """All significant name parts, since we can't rely on a consistent
    'neighborhood (city)' vs 'city (neighborhood)' convention in the data."""
    raw = re.split(r"[(),]", name)
    return [t.strip().lower() for t in raw if len(t.strip()) > 2]

def _url_matches_route(url: str | None, origin: str, destination: str) -> bool:
    """Loose check: URL must contain AT LEAST ONE token from each side. Catches
    genuinely wrong routes without rejecting correct results over a naming mismatch."""
    if not url:
        return True
    url_lower = url.lower()
    origin_hit = any(tok in url_lower for tok in _place_tokens(origin))
    dest_hit = any(tok in url_lower for tok in _place_tokens(destination))
    return origin_hit and dest_hit

def _is_plausible_url(url: str | None) -> bool:
    """Cheap guard against the LLM smuggling in an off-topic link despite the prompt."""
    if not url:
        return True
    bad_signals = ["hotel", "rental", "facebook.com", "booking.com/hotel"]
    return not any(sig in url.lower() for sig in bad_signals)

def _clean_url(url: str | None, origin: str, destination: str) -> Optional[str]:
    if not _is_plausible_url(url) or not _url_matches_route(url, origin, destination):
        return None
    return url

def _clean_place_name(name: str) -> str:
    """Strip parenthetical qualifiers like '(Busan)' before using a name in an
    external lookup (Duffel places, rental search) that expects a plain city name."""
    return re.sub(r"\s*\(.*?\)", "", name).strip()

def _parse_duration_hours(duration: str | None) -> float:
    if not duration:
        return 0.0
    hours = re.search(r"(\d+)h", duration)
    mins = re.search(r"(\d+)min", duration)
    return (int(hours.group(1)) if hours else 0) + (int(mins.group(1)) if mins else 0) / 60

# ---------- Search nodes ----------

route_extraction_instructions = """You are extracting travel options from a route
comparison or operator page for ONE specific origin-destination pair. The page typically
lists several ways to travel (e.g. "Bus, train via X", "Ferry", "Drive", "Bus, ferry").

Extract every DISTINCT option relevant to train, bus, and/or ferry travel that appears on
this page:
- A pure train-only option, if one exists → mode="train", segments=null
- A pure bus-only option, if one exists → mode="bus", segments=null
- A pure ferry-only option, if one exists → mode="ferry", segments=null
- Any multi-modal option combining these (e.g. "Bus, ferry", "Bus, train via X") →
  mode="combined", with segments listing each leg in order (mode, provider if named,
  duration if given per-leg)

Because all of these come from the SAME page for the SAME route, their durations and prices
should be internally consistent with each other — don't extract conflicting numbers for what
should be the same route.

If you cannot confirm the page is actually for THIS origin→destination pair (not a similarly
named place), return options=[] rather than guessing.

If the page shows no train/bus/ferry service at all (e.g. only flight), return options=[]
and do not fabricate anything. Never substitute a link from an unrelated route or place."""

def search_route_options(state: LegTransportState):
    leg = state["leg"]
    modes_requested = set(leg["modes_requested"]) & {"train", "bus", "ferry", "combined"}
    mode_label = "/".join(sorted(modes_requested)) or "train/bus/ferry"

    discovered = discover_relevant_domains(
        f"official {mode_label} operator booking site {leg['origin']} {leg['destination']}",
        cache_key=(leg["destination_country"], mode_label),
    )
    # discovery is primary; static list only backfills if discovery is thin
    domains = list(dict.fromkeys(discovered + ROME2RIO_DOMAIN))
    if len(domains) < 3:
        domains += _flatten_by_country(
            leg["destination_country"], RAIL_DOMAINS_BY_COUNTRY, BUS_DOMAINS_BY_COUNTRY
        ) + FERRY_DOMAINS

    query = f"{leg['origin']} to {leg['destination']} {mode_label} schedule tickets"
    if state.get("review_feedback"):
        query += f" — traveler feedback: {state['review_feedback']}"

    data = TavilySearch(max_results=5, include_domains=domains, include_raw_content="text").invoke({"query": query})
    docs = [d for d in _tavily_results(data) if _url_matches_route(d.get("url"), leg["origin"], leg["destination"])]
    for d in docs:
        if d.get("raw_content"):
            d["raw_content"] = d["raw_content"][:6000]

    if not docs:
        fallback_domains = discovered or _flatten_by_country(
            leg["destination_country"], RAIL_DOMAINS_BY_COUNTRY, BUS_DOMAINS_BY_COUNTRY
        ) + FERRY_DOMAINS
        data = TavilySearch(
            max_results=5,
            include_domains=fallback_domains,
            include_raw_content="text",
        ).invoke({"query": query})
        docs = [
            d for d in _tavily_results(data)
            if _url_matches_route(d.get("url"), leg["origin"], leg["destination"])
        ]
        for d in docs:
            if d.get("raw_content"):
                d["raw_content"] = d["raw_content"][:6000]

    structured_llm = llm.with_structured_output(RouteOptions)
    result = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=route_extraction_instructions),
        HumanMessage(content=json.dumps(docs)),
    ], RouteOptions)

    tagged = []
    for opt in result.options:
        d = opt.model_dump()
        d["booking_url"] = _clean_url(d.get("booking_url"), leg["origin"], leg["destination"])
        is_relevant = d["mode"] in modes_requested or (
            d["mode"] == "combined" and modes_requested & {"train", "bus", "ferry"}
        )
        if is_relevant:
            tagged.append({**d, "source": "rome2rio", "round": state.get("search_round", 0)})
    return {"raw_options": tagged}

def verify_route_options(state: LegTransportState):
    """Independent corroboration source — searches operator-specific domains (rail/bus/
    ferry company sites) discovered live for this leg's country, separate from
    search_route_options' Rome2Rio-first approach. Feeds reconcile_options, which flags
    whether each option was seen from one source or both."""
    leg = state["leg"]
    modes = set(leg["modes_requested"]) & {"train", "bus", "ferry"}
    mode_label = "/".join(sorted(modes))

    discovered = discover_relevant_domains(
        f"official {mode_label} operator booking site {leg['origin']} {leg['destination']}",
        cache_key=(leg["destination_country"], mode_label),  # shares cache with search_route_options
    )
    domains = discovered or _flatten_by_country(
        leg["destination_country"], RAIL_DOMAINS_BY_COUNTRY, BUS_DOMAINS_BY_COUNTRY
    ) + FERRY_DOMAINS

    query = f"{leg['origin']} to {leg['destination']} " + " ".join(modes)
    if state.get("review_feedback"):
        query += f" — traveler feedback: {state['review_feedback']}"

    data = TavilySearch(max_results=3, include_domains=domains, include_raw_content="text").invoke({"query": query})
    docs = [d for d in _tavily_results(data)
            if _url_matches_route(d.get("url"), leg["origin"], leg["destination"])]

    if not docs:
        return {"raw_options": []}

    structured_llm = llm.with_structured_output(RouteOptions)
    result = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=route_extraction_instructions),
        HumanMessage(content=json.dumps(docs)),
    ], RouteOptions)

    tagged = [{**opt.model_dump(), "source": "operator_site", "round": state.get("search_round", 0)}
              for opt in result.options if opt.mode in modes]
    return {"raw_options": tagged}

def search_flight_leg(state: LegTransportState):
    leg = state["leg"]
    origin_clean = _clean_place_name(leg["origin"])
    dest_clean = _clean_place_name(leg["destination"])

    origin_codes = duffel_places_lookup(origin_clean)
    dest_codes = duffel_places_lookup(dest_clean)

    # duffel_places_lookup's own last-resort passthrough returns the input string
    # unchanged when it finds nothing — that's not a real airport code, so treat
    # it as "no flight route found" rather than sending garbage to Duffel
    def _is_real_code(code: str) -> bool:
        return len(code) == 3 and code.isalpha() and code.isupper()

    if not origin_codes or not _is_real_code(origin_codes[0]) or not dest_codes or not _is_real_code(dest_codes[0]):
        return {"raw_options": [{
            "mode": "flight",
            "provider": f"No flight route found ({origin_clean} → {dest_clean})",
            "price_estimate": None,
            "duration": None,
            "booking_url": None,
            "segments": None,
            "round": state.get("search_round", 0),
        }]}

    offers = fetch_flight_offers(origin_codes[0], dest_codes[0], leg["depart_date"], passenger_count=1)
    options = [{
        "mode": "flight",
        "provider": o["owner"]["name"],
        "price_estimate": f"{o['price']['total_amount']} {o['price']['currency']}",
        "duration": o["slices"][0]["duration"],
        "booking_url": None,
        "segments": None,
        "round": state.get("search_round", 0),
    } for o in offers[:5]]
    return {"raw_options": options}

def search_car_rental(state: LegTransportState):
    leg = state["leg"]
    origin_display = leg["origin"]
    discovered = discover_relevant_domains(
        f"car rental company {origin_display}",
        cache_key=(origin_display, "car"),
    )
    domains = list(dict.fromkeys(discovered + CAR_RENTAL_DOMAINS))

    query = f"car rental pickup {origin_display}"
    if state.get("review_feedback"):
        query += f" — traveler feedback: {state['review_feedback']}"

    data = TavilySearch(max_results=3, include_domains=domains).invoke({"query": query})
    structured_llm = llm.with_structured_output(TransportOption)
    opt = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=(
            "Extract a representative car rental option (mode='car') from this search data. "
            f"This is a PICKUP LOCATION search for the metro area of '{origin_display}'. "
            "Accept results for rentals anywhere in that city or its main airport, even if "
            "the exact neighborhood/district name isn't mentioned verbatim — a rental listed "
            "generally for the city is valid. Only treat it as not found if results are for a "
            "clearly different city entirely."
        )),
        HumanMessage(content=json.dumps(_tavily_results(data))),
    ], TransportOption)

    result = opt.model_dump()
    result["booking_url"] = None if not _is_plausible_url(result.get("booking_url")) else result.get("booking_url")
    return {"raw_options": [{**result, "round": state.get("search_round", 0)}]}

# ---------- Reconciliation, recommendation, review, finalize ----------

def reconcile_options(state: LegTransportState):
    """Merge this round's raw_options into a single confidence-tagged list.
    Writes to reconciled_options (single-writer) rather than back into raw_options
    (Annotated + operator.add), so the merge doesn't duplicate entries on top of
    themselves across supersteps."""
    latest = max((o.get("round", 0) for o in state["raw_options"]), default=0)
    current = [o for o in state["raw_options"] if o.get("round", 0) == latest]

    rome2rio = [o for o in current if o.get("source") != "operator_site"]
    operator_internal = [o for o in current if o.get("source") == "operator_site"]

    def _key(o):
        return (o["mode"], (o.get("provider") or "").lower()[:15])

    operator_keys = {_key(o) for o in operator_internal}
    rome2rio_keys = {_key(o) for o in rome2rio}

    merged = []
    for o in rome2rio:
        merged.append({**o, "confidence": "corroborated" if _key(o) in operator_keys else "unverified"})
    for o in operator_internal:
        if _key(o) not in rome2rio_keys:
            merged.append({**o, "confidence": "unverified"})

    return {"reconciled_options": merged}

recommendation_instructions = """You are recommending the best transportation option for one
leg of a trip, given all the real options found. Consider genuine trade-offs a traveler would
care about — not just lowest price:
- Total travel time and number of connections/segments
- Whether the leg crosses water or a distance where ground transport is impractical (in which
  case flight or ferry should rank first even if pricier)
- Whether an option is unconfirmed/placeholder ("No X service found") — these should always
  rank last, never recommended
Return every option's index in your ranked_option_indices, best to worst — don't drop any."""

def recommend_leg_options(state: LegTransportState):
    current = state["reconciled_options"]

    if not current:
        return {"options": [], "recommendation_reasoning": None}

    structured_llm = llm.with_structured_output(LegRecommendation)
    rec = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=recommendation_instructions),
        HumanMessage(content=f"Leg: {state['leg']['origin']} → {state['leg']['destination']}\n"
                              f"Options: {json.dumps(current)}"),
    ], LegRecommendation)

    ranked = [current[i] for i in rec.ranked_option_indices if 0 <= i < len(current)]
    # safety net: if the model dropped any options from its ranking, append them at the end
    # rather than silently losing them
    missing = [o for i, o in enumerate(current) if i not in rec.ranked_option_indices]
    ranked.extend(missing)

    return {"options": ranked, "recommendation_reasoning": rec.reasoning}

def review_leg_transport(state: LegTransportState):
    if not state["options"]:
        raw = interrupt({
            "type": "leg_transport_review",
            "message": f"{state['leg']['origin']} → {state['leg']['destination']}: no options "
                       "found for the requested modes. Reply with feedback to re-search "
                       "(e.g. different modes), or 'skip' to leave this leg unresolved.",
            "recommendation_reasoning": None,
            "options": [],
        })
        if raw.strip().lower() == "skip":
            return {"selected": None, "review_decision": "finalize"}
        return {"review_feedback": raw, "review_decision": "revise"}

    raw = interrupt({
        "type": "leg_transport_review",
        "message": f"{state['leg']['origin']} → {state['leg']['destination']}: reply 'approve' to "
                   "take the recommended option, an index to pick another, or feedback to re-search.",
        "recommendation_reasoning": state.get("recommendation_reasoning"),
        "options": state["options"],
    })
    if raw.strip().lower() in APPROVE_SIGNALS:
        return {"selected": state["options"][0], "review_decision": "finalize"}
    if raw.strip().isdigit() and int(raw) < len(state["options"]):
        return {"selected": state["options"][int(raw)], "review_decision": "finalize"}
    return {"review_feedback": raw, "review_decision": "revise"}

def route_leg_review(state: LegTransportState):
    return "finalize_leg" if state.get("review_decision") == "finalize" else "increment_round"

def increment_round(state: LegTransportState):
    return {"search_round": state.get("search_round", 0) + 1}

def finalize_leg(state: LegTransportState):
    return {"finalized_legs": [{**state["leg"], "selected": state["selected"]}]}

def aggregate_legs(state: TransportPlanningState):
    # no-op passthrough — Send()'d branches already merged finalized_legs via operator.add
    return {}

# ---------- Graph wiring ----------

leg_builder = StateGraph(LegTransportState)

leg_builder.add_node("search_flight", search_flight_leg)
leg_builder.add_node("search_route_options", search_route_options)
leg_builder.add_node("verify_route_options", verify_route_options)
leg_builder.add_node("search_car_rental", search_car_rental)
leg_builder.add_node("reconcile_options", reconcile_options)
leg_builder.add_node("recommend_leg_options", recommend_leg_options)
leg_builder.add_node("review_leg_transport", review_leg_transport)
leg_builder.add_node("increment_round", increment_round)
leg_builder.add_node("finalize_leg", finalize_leg)

leg_builder.add_conditional_edges(
    START, fan_out_modes,
    ["search_flight", "search_route_options", "verify_route_options", "search_car_rental"],
)

# Every search node feeds reconcile_options — this is the ONLY path forward from search.
for node in ["search_flight", "search_route_options", "verify_route_options", "search_car_rental"]:
    leg_builder.add_edge(node, "reconcile_options")

leg_builder.add_edge("reconcile_options", "recommend_leg_options")
leg_builder.add_edge("recommend_leg_options", "review_leg_transport")

leg_builder.add_conditional_edges(
    "review_leg_transport", route_leg_review,
    ["finalize_leg", "increment_round"],
)

leg_builder.add_conditional_edges(
    "increment_round", fan_out_modes,
    ["search_flight", "search_route_options", "verify_route_options", "search_car_rental"],
)

leg_builder.add_edge("finalize_leg", END)

builder = StateGraph(TransportPlanningState)
builder.add_node("derive_legs", derive_legs)
builder.add_node("classify_leg_modes", classify_leg_modes)
builder.add_node("plan_leg", leg_builder.compile(name="plan_leg"))
builder.add_node("aggregate_legs", aggregate_legs)

builder.add_edge(START, "derive_legs")
builder.add_edge("derive_legs", "classify_leg_modes")
builder.add_conditional_edges("classify_leg_modes", fan_out_legs, ["plan_leg"])
builder.add_edge("plan_leg", "aggregate_legs")
builder.add_edge("aggregate_legs", END)

transport_graph = builder.compile()

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "1"}}
    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    dated_itinerary_raw = input(
        "Paste the dated_itinerary JSON from trip_info_graph (list of stops): "
    )
    result_internal = graph.invoke(
        {"dated_itinerary": json.loads(dated_itinerary_raw), "legs": [], "finalized_legs": []},
        config=config,
    )

    while "__interrupt__" in result_internal:
        interrupt_data = result_internal["__interrupt__"][0].value
        interrupt_type = interrupt_data["type"]

        if interrupt_type == "transport_mode_review":
            print("\nProposed legs:")
            for i_internal, leg_internal in enumerate(interrupt_data["legs"]):
                print(f"  [{i_internal}] {leg_internal['origin']} → {leg_internal['destination']} "
                      f"({leg_internal['depart_date']}) — modes: {leg_internal['modes_requested']}")
            raw_internal = input(
                "\nApprove all (blank/approve), or override e.g. '0: flight,train | 1: car': "
            )
            result_internal = graph.invoke(Command(resume=raw_internal), config=config)

        elif interrupt_type == "leg_transport_review":
            print(f"\n{interrupt_data['message']}")
            if interrupt_data.get("recommendation_reasoning"):
                print(f"  Recommendation: {interrupt_data['recommendation_reasoning']}")
            for i_internal, opt_internal in enumerate(interrupt_data["options"]):
                print(f"  [{i_internal}] {opt_internal['mode']} — {opt_internal.get('provider')} — "
                      f"{opt_internal.get('price_estimate')} — {opt_internal.get('duration')}")
            raw_internal = input("Your choice: ")
            result_internal = graph.invoke(Command(resume=raw_internal), config=config)

        else:
            raise ValueError(f"Unhandled interrupt type: {interrupt_type}")

    print("\nFinalized legs:")
    for leg_internal in result_internal["finalized_legs"]:
        sel = leg_internal["selected"]
        if sel:
            print(f"  {leg_internal['origin']} → {leg_internal['destination']}: {sel['mode']} via {sel.get('provider')} "
                  f"({sel.get('price_estimate')})")
        else:
            print(f"  {leg_internal['origin']} → {leg_internal['destination']}: unresolved (skipped)")
else:
    graph = builder.compile()