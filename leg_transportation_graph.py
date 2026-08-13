# leg_transportation_graph.py
import json
import math
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

from llm_config import get_llm
from trip_info_graph import invoke_structured_with_retry, APPROVE_SIGNALS
from main import fetch_flight_offers, duffel_places_lookup, duffel_city_coords, duffel_city_country

llm = get_llm("premium")          # recommend_leg_options stays on this
extraction_llm = get_llm("cheap")  # search_route_options / verify_route_options / search_car_rental use this

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
    leg_type: Literal["arrival", "internal", "departure"]  # NEW — for review clarity, not routing
    distance_miles: Optional[float]   # NEW — computed once, reused for ranking

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
    home_city: str
    home_country: str
    return_city: str
    return_country: str
    legs: list[Leg]
    finalized_legs: Annotated[list[dict], operator.add]


# ---------- Leg derivation & mode classification ----------

def derive_legs(state: TransportPlanningState):
    stops = state["dated_itinerary"]
    internal = [{
        "origin": stops[i]["city"],
        "destination": stops[i + 1]["city"],
        "origin_country": _country_code(stops[i]["city"], stops[i]["country"]),
        "destination_country": _country_code(stops[i + 1]["city"], stops[i + 1]["country"]),
        "depart_date": stops[i]["return_date"],
        "requires_flight_or_ferry": stops[i].get("requires_flight_or_ferry", False)
                                     or stops[i + 1].get("requires_flight_or_ferry", False),
        "leg_type": "internal",
    } for i in range(len(stops) - 1)]

    home_country = state["home_country"]    # already ISO, from request_home_context
    return_country = state["return_country"]
    stop0_country = _country_code(stops[0]["city"], stops[0]["country"])
    stopN_country = _country_code(stops[-1]["city"], stops[-1]["country"])

    arrival_leg = {
        "origin": state["home_city"],
        "destination": stops[0]["city"],
        "origin_country": home_country,
        "destination_country": stop0_country,
        "depart_date": stops[0]["depart_date"],
        "requires_flight_or_ferry": bool(home_country) and bool(stop0_country) and home_country != stop0_country,
        "leg_type": "arrival",
    }
    departure_leg = {
        "origin": stops[-1]["city"],
        "destination": state["return_city"],
        "origin_country": stopN_country,
        "destination_country": return_country,
        "depart_date": stops[-1]["return_date"],
        "requires_flight_or_ferry": bool(stopN_country) and bool(return_country) and stopN_country != return_country,
        "leg_type": "departure",
    }

    return {"legs": [arrival_leg, *internal, departure_leg]}

# Known island/archipelago destinations where ground transport (train/bus/car) to the
# mainland isn't possible — flight or ferry only, regardless of same-country status.
# Extend this list as new destinations come up; it's intentionally small and explicit
# rather than trying to infer "island-ness" from an LLM, which is error-prone for a
# binary feasibility gate like this.
ISLAND_DESTINATIONS = {
    "jeju", "okinawa", "bali", "phuket", "boracay", "santorini", "mykonos",
    "hawaii", "maui", "oahu", "sicily", "sardinia", "corsica",
    # Southeast Asia — added after "car" got selected as a finalized mode between
    # islands with no bridge/ground connections (Con Dao <-> Phu Quoc,
    # Khao Sok <-> Koh Samui, Koh Samui <-> Koh Phangan). Khao Sok and Krabi are
    # intentionally NOT in this set — they're mainland and correctly get ground modes.
    "con dao", "koh lanta", "koh phangan", "koh samui", "koh tao", "phu quoc",
}

def _is_island(place_name: str) -> bool:
    lowered = place_name.lower()
    return any(island in lowered for island in ISLAND_DESTINATIONS)

# Beyond this, ground transport stops being a realistic default in the US and
# most large countries — driving/rail becomes a full-day-plus commitment.
# Below the lower bound, ground modes alone are fine. Between the two, offer
# flight alongside ground options rather than picking one for the traveler.
GROUND_ONLY_MAX_MILES = 150
FLIGHT_ONLY_MIN_MILES = 500

def _haversine_miles(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    r = 3958.8  # earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def _leg_distance_miles(leg: dict) -> Optional[float]:
    origin_coords = duffel_city_coords(_clean_place_name(leg["origin"]))
    dest_coords = duffel_city_coords(_clean_place_name(leg["destination"]))
    if not origin_coords or not dest_coords:
        return None
    return _haversine_miles(origin_coords, dest_coords)

def _suggest_modes(leg: dict, distance: Optional[float]) -> list[str]:
    if _is_island(leg["origin"]) or _is_island(leg["destination"]):
        return ["flight", "ferry"]
    if leg["origin_country"] != leg["destination_country"]:
        return ["flight"]
    if distance is None:
        return ["flight", "train", "bus", "car"]
    if distance >= FLIGHT_ONLY_MIN_MILES:
        return ["flight"]
    if distance <= GROUND_ONLY_MAX_MILES:
        return ["train", "bus", "car"]
    return ["flight", "train", "bus"]

def classify_leg_modes(state: TransportPlanningState):
    annotated = []
    for leg in state["legs"]:
        distance = _leg_distance_miles(leg)
        annotated.append({**leg, "modes_requested": _suggest_modes(leg, distance), "distance_miles": distance})

    raw = interrupt({
        "type": "transport_mode_review",
        "message": "Confirm modes per leg (e.g. '0: flight,train | 1: car'), or 'approve' for defaults.",
        "legs": annotated,   # now includes distance_miles so you can see what drove the suggestion
    })
    legs = annotated if raw.strip().lower() in APPROVE_SIGNALS else _apply_mode_overrides(annotated, raw)
    return {"legs": legs}

def request_home_context(state: TransportPlanningState):
    raw = interrupt({
        "type": "home_context_request",
        "message": "Where are you traveling from? Add '-> city' if returning somewhere "
                   "different (open-jaw), otherwise it defaults to the same city.",
        "first_stop": state["dated_itinerary"][0]["city"],
        "last_stop": state["dated_itinerary"][-1]["city"],
    })
    home_raw, _, return_raw = raw.partition("->")
    home_city = home_raw.strip()
    return_city = return_raw.strip() or home_city

    return {
        "home_city": home_city,
        "home_country": duffel_city_country(home_city) or "",
        "return_city": return_city,
        "return_country": duffel_city_country(return_city) or "",
    }

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
    "KR": ["korail.com", "letskorail.com", "kr.trip.com"],
    "JP": ["jorudan.co.jp", "hyperdia.com", "japanrailpass.net"],
    "US": ["amtrak.com", "wanderu.com"],
}

BUS_DOMAINS_BY_COUNTRY = {
    "default": BUS_DOMAINS,
    "KR": ["kobus.co.kr", "bustago.or.kr", "kr.trip.com"],
    "US": ["greyhound.com", "peterpanbus.com", "megabus.com"],
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
    if cache_key in _domain_cache:
        return _domain_cache[cache_key]
    data = TavilySearch(max_results=5).invoke({"query": query_hint})
    print(f"[discover_relevant_domains] query={query_hint!r} raw_data_type={type(data)} raw_data={data!r}")  # DEBUG
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
    'neighborhood (city)' vs 'city (neighborhood)' convention in the data.
    Splits on whitespace as well as punctuation — multi-word city names
    ("New York City") were previously kept as one space-containing token,
    which almost never appears literally in a real URL and caused every
    result for such cities to get filtered out."""
    raw = re.split(r"[(),\s]+", name)
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
    """Strip parenthetical qualifiers like '(Busan)' AND common geographic
    suffixes like 'Island'/'-do' that don't appear in Duffel's canonical
    city_name field — e.g. 'Jeju Island' needs to become 'Jeju' before an
    airport lookup, or it silently fails to match and forces an extra
    no-options retry round on every trip that includes it."""
    cleaned = re.sub(r"\s*\(.*?\)", "", name).strip()
    cleaned = re.sub(r"\s+Island$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"-do$", "", cleaned, flags=re.IGNORECASE)  # Korean island/province suffix
    return cleaned.strip()

def _parse_duration_hours(duration: str | None) -> float:
    if not duration:
        return 0.0
    hours = re.search(r"(\d+)h", duration)
    mins = re.search(r"(\d+)min", duration)
    return (int(hours.group(1)) if hours else 0) + (int(mins.group(1)) if mins else 0) / 60

# ---------- Nearby-airport overrides ----------
#
# Some towns have no airport of their own but sit close enough to a real one that a
# flight + short ground transfer is a legitimate alternative to a long bus/train —
# e.g. Hoi An has no airport, but Da Nang (30km away) does. This is different from
# the _clean_place_name suffix-stripping fix: that fix handles a REAL airport whose
# NAME didn't match (Jeju Island -> Jeju); this handles a town with NO airport at all,
# where substituting a nearby city is the only way a flight option can exist.
#
# Scoped ONLY to search_flight_leg's internal Duffel lookup — leg["origin"]/
# leg["destination"] are never rewritten, so display, ground-transport search, and
# lodging all still see the real town name. Extend as new airport-less towns come up;
# these are the ones already hit plus a starter set for common backpacker/beach
# regions likely to come up next (not exhaustive).
NEARBY_AIRPORT_OVERRIDES = {
    # Vietnam
    "hoi an": ("Da Nang", 30),
    "sapa": ("Hanoi", 320),          # long transfer — flagged loudly via transfer_note
    # Thailand
    "khao sok national park": ("Surat Thani", 70),
    "pai": ("Chiang Mai", 135),
    "ao nang": ("Krabi", 20),
    # Spain / Basque coast
    "mundaka": ("Bilbao", 35),
    "zarautz": ("Bilbao", 65),
    "tarifa": ("Jerez de la Frontera", 100),
    # Italy
    "positano": ("Naples", 60),
    "amalfi": ("Naples", 65),
    "cinque terre": ("Pisa", 100),
}

def _flight_lookup_name(place_name: str) -> tuple[str, Optional[int]]:
    """Returns (name to actually look up in Duffel, transfer_km or None). For most
    places this is just the cleaned place name with no transfer. For known
    airport-less towns, substitutes the nearest real airport city and returns the
    approximate transfer distance so the flight option can be tagged with an honest
    caveat rather than looking like a door-to-door flight."""
    cleaned = _clean_place_name(place_name)
    override = NEARBY_AIRPORT_OVERRIDES.get(cleaned.lower())
    if override:
        return override[0], override[1]
    return cleaned, None

# ---------- Country name normalization ----------

COUNTRY_NAME_TO_ISO = {
    # --- Europe ---
    "spain": "ES", "españa": "ES",
    "portugal": "PT",
    "france": "FR",
    "italy": "IT", "italia": "IT",
    "germany": "DE", "deutschland": "DE",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "ireland": "IE",
    "netherlands": "NL", "holland": "NL",
    "belgium": "BE",
    "switzerland": "CH",
    "austria": "AT",
    "greece": "GR",
    "croatia": "HR",
    "iceland": "IS",
    "norway": "NO",
    "sweden": "SE",
    "denmark": "DK",
    "finland": "FI",
    "poland": "PL",
    "czech republic": "CZ", "czechia": "CZ",
    "hungary": "HU",
    "turkey": "TR", "türkiye": "TR",
    "malta": "MT",
    "cyprus": "CY",

    # --- Asia ---
    "south korea": "KR", "korea": "KR", "republic of korea": "KR",
    "japan": "JP",
    "china": "CN",
    "taiwan": "TW",
    "hong kong": "HK",
    "thailand": "TH",
    "vietnam": "VN",
    "indonesia": "ID",
    "philippines": "PH",
    "malaysia": "MY",
    "singapore": "SG",
    "india": "IN",
    "nepal": "NP",
    "sri lanka": "LK",
    "cambodia": "KH",
    "laos": "LA",
    "myanmar": "MM",
    "maldives": "MV",

    # --- Middle East ---
    "united arab emirates": "AE", "uae": "AE",
    "israel": "IL",
    "jordan": "JO",
    "qatar": "QA",
    "saudi arabia": "SA",
    "oman": "OM",
    "turkiye": "TR",

    # --- Americas ---
    "united states": "US", "usa": "US", "united states of america": "US",
    "canada": "CA",
    "mexico": "MX",
    "brazil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "peru": "PE",
    "colombia": "CO",
    "costa rica": "CR",
    "panama": "PA",
    "ecuador": "EC",
    "uruguay": "UY",
    "cuba": "CU",
    "dominican republic": "DO",
    "jamaica": "JM",
    "bahamas": "BS",

    # --- Oceania ---
    "australia": "AU",
    "new zealand": "NZ",
    "fiji": "FJ",

    # --- Africa ---
    "morocco": "MA",
    "egypt": "EG",
    "south africa": "ZA",
    "kenya": "KE",
    "tanzania": "TZ",
    "tunisia": "TN",
}

def normalize_country_fallback(fallback: str) -> str:
    """Normalize an LLM-generated country name/string to ISO if we have a mapping;
    otherwise return it unchanged. Used wherever duffel_city_country() fails to
    resolve and we fall back to the raw country string from itinerary data — without
    this, that raw string (e.g. 'South Korea') would mismatch against a resolved ISO
    code (e.g. 'KR') anywhere the two get compared, which is the root cause behind
    both the earlier flight cross-country false-mismatch bug and the lodging
    currency-plausibility gap."""
    return COUNTRY_NAME_TO_ISO.get(fallback.strip().lower(), fallback)

def _country_code(city_name: str, fallback: str) -> str:
    """Resolves a city to its ISO country code via the shared Duffel airport
    cache — the single source of truth for country identity in this file, so
    leg country fields, cross-country comparisons, and domain-map lookups all
    speak the same format instead of mixing ISO codes with LLM-generated
    country names. Falls back to a normalized version of the itinerary's
    original country string only if the city can't be resolved."""
    resolved = duffel_city_country(_clean_place_name(city_name))
    if resolved:
        return resolved
    return normalize_country_fallback(fallback)

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
    domains = list(dict.fromkeys(discovered + ROME2RIO_DOMAIN))
    if len(domains) < 3:
        domains += _flatten_by_country(
            leg["destination_country"], RAIL_DOMAINS_BY_COUNTRY, BUS_DOMAINS_BY_COUNTRY
        ) + FERRY_DOMAINS
    print(f"[search_route_options] {leg['origin']} -> {leg['destination']}: domains={domains}")  # DEBUG

    query = f"{leg['origin']} to {leg['destination']} {mode_label} schedule tickets"
    if state.get("review_feedback"):
        query += f" — traveler feedback: {state['review_feedback']}"

    data = TavilySearch(max_results=5, include_domains=domains, include_raw_content="text").invoke({"query": query})
    raw_results = _tavily_results(data)
    docs = [d for d in raw_results if _url_matches_route(d.get("url"), leg["origin"], leg["destination"])]
    print(f"[search_route_options] {leg['origin']} -> {leg['destination']}: "  # DEBUG
          f"{len(raw_results)} raw tavily results, {len(docs)} survived url filter")
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

    print(f"[search_route_options] {leg['origin']} -> {leg['destination']}: "  # DEBUG
          f"extracted {len(result.options)} options, {len(tagged)} tagged as relevant")
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

    structured_llm = extraction_llm.with_structured_output(RouteOptions)
    result = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=route_extraction_instructions),
        HumanMessage(content=json.dumps(docs)),
    ], RouteOptions)

    tagged = [{**opt.model_dump(), "source": "operator_site", "round": state.get("search_round", 0)}
              for opt in result.options if opt.mode in modes]
    return {"raw_options": tagged}

def search_flight_leg(state: LegTransportState):
    leg = state["leg"]
    origin_lookup_name, origin_transfer_km = _flight_lookup_name(leg["origin"])
    dest_lookup_name, dest_transfer_km = _flight_lookup_name(leg["destination"])

    origin_codes = duffel_places_lookup(origin_lookup_name)
    dest_codes = duffel_places_lookup(dest_lookup_name)

    # duffel_places_lookup's own last-resort passthrough returns the input string
    # unchanged when it finds nothing — that's not a real airport code, so treat
    # it as "no flight route found" rather than sending garbage to Duffel
    def _is_real_code(code: str) -> bool:
        return len(code) == 3 and code.isalpha() and code.isupper()

    if not origin_codes or not _is_real_code(origin_codes[0]) or not dest_codes or not _is_real_code(dest_codes[0]):
        return {"raw_options": [{
            "mode": "flight",
            "provider": f"No flight route found ({leg['origin']} → {leg['destination']})",
            "price_estimate": None,
            "duration": None,
            "booking_url": None,
            "segments": None,
            "round": state.get("search_round", 0),
            "unresolved": True,  # marks this as a non-real option — filtered out in
                                 # recommend_leg_options so it can never be silently finalized
        }]}

    offers = fetch_flight_offers(origin_codes[0], dest_codes[0], leg["depart_date"], passenger_count=1)

    # If either endpoint used a nearby-airport override, say so explicitly on the
    # option — a flight into Da Nang for a "Hoi An" leg isn't door-to-door, and
    # recommend_leg_options needs this to weigh the extra transfer fairly against
    # a direct ground option instead of comparing raw flight duration alone.
    transfer_parts = []
    if origin_transfer_km:
        transfer_parts.append(f"~{origin_transfer_km}km transfer from {origin_lookup_name} airport to {leg['origin']}")
    if dest_transfer_km:
        transfer_parts.append(f"~{dest_transfer_km}km transfer from {dest_lookup_name} airport to {leg['destination']}")
    transfer_note = "; ".join(transfer_parts) or None

    options = [{
        "mode": "flight",
        "provider": o["owner"]["name"] + (f" (lands at {dest_lookup_name}, not {leg['destination']} directly)" if dest_transfer_km else ""),
        "price_estimate": f"{o['price']['total_amount']} {o['price']['currency']}",
        "duration": o["slices"][0]["duration"],
        "booking_url": None,
        "segments": None,
        "round": state.get("search_round", 0),
        **({"transfer_note": transfer_note} if transfer_note else {}),
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
    structured_llm = extraction_llm.with_structured_output(TransportOption)
    opt = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=(
            "Extract a representative car rental option (mode='car') from this search data. "
            f"This is a PICKUP LOCATION search for the metro area of '{origin_display}'. "
            "Accept results for rentals anywhere in that city or its main airport, even if "
            "the exact neighborhood/district name isn't mentioned verbatim — a rental listed "
            "generally for the city is valid. Only treat it as not found if results are for a "
            "clearly different city entirely.\n\n"
            "IMPORTANT: duration must be a rental LENGTH (e.g. '3 days', 'per day') or omitted "
            "entirely — never a calendar availability window like 'Sep 7 - Sep 30', which is "
            "not a trip duration and must not be extracted into this field. If price_estimate "
            "and duration are both unavailable/unclear from the source, leave provider populated "
            "but set price_estimate and duration to null rather than guessing or copying an "
            "unrelated number from the page."
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
leg of a trip, given all the real options found. Weigh price and time together — don't let
speed silently win by default:
- Under ~250 miles, the time saved by flying is usually small once you account for security,
  boarding, and getting to/from the airport — a meaningfully cheaper train or bus should often
  outrank a marginally faster flight, not just a slower one.
- Beyond ~250 miles, time matters more, and price differences between similar-speed options
  (e.g. two flights) should decide the ranking rather than mode alone.
- Still don't recommend a wildly slower option to save a small amount of money — this is a
  balance, not a pure cost minimization.
- Whether the leg crosses water or a distance where ground transport is impractical (flight or
  ferry should rank first even if pricier).
- Whether an option is unconfirmed/placeholder ("No X service found") — these always rank last.
- An option with a missing price AND missing duration is nearly as unreliable as an
  explicit 'not found' placeholder — rank it low even if it's the only option in the round,
  rather than treating 'only option available' as a reason to rank it first.
- If an option has a 'transfer_note' (a flight landing at a nearby airport rather than the
  destination itself), factor the extra ground transfer time and cost into your comparison
  against direct ground options — don't just compare flight duration alone against a direct
  bus/train duration, since a "1 hour flight" with a 2-hour transfer on each end may lose to
  a single 5-hour direct bus.
Return every option's index in your ranked_option_indices, best to worst — don't drop any."""

def recommend_leg_options(state: LegTransportState):
    current = [o for o in state["reconciled_options"] if not o.get("unresolved")]
    if not current:
        return {"options": [], "recommendation_reasoning": None}

    leg = state["leg"]
    distance_note = f" (~{leg['distance_miles']:.0f} miles)" if leg.get("distance_miles") else ""

    structured_llm = llm.with_structured_output(LegRecommendation)
    rec = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=recommendation_instructions),
        HumanMessage(content=f"Leg: {leg['origin']} → {leg['destination']}{distance_note}\n"
                              f"Options: {json.dumps(current)}"),
    ], LegRecommendation)

    ranked = [current[i] for i in rec.ranked_option_indices if 0 <= i < len(current)]
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
            "raw_option_count": len(state.get("raw_options", [])),  # debug — remove once resolved
            "reconciled_count": len(state.get("reconciled_options", [])),  # debug — remove once resolved
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
# wiring — replace the existing START edge

builder.add_node("request_home_context", request_home_context)
builder.add_edge(START, "request_home_context")
builder.add_edge("request_home_context", "derive_legs")
builder.add_edge("derive_legs", "classify_leg_modes")
builder.add_conditional_edges("classify_leg_modes", fan_out_legs, ["plan_leg"])
builder.add_edge("plan_leg", "aggregate_legs")
builder.add_edge("aggregate_legs", END)

transport_graph = builder.compile()

if __name__ == "__main__":
    print("NYC:", duffel_places_lookup("New York City"))
    print("NY:", duffel_places_lookup("New York"))
    print("CHI:", duffel_places_lookup("Chicago"))
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