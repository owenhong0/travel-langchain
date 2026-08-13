# lodging_graph.py
import json
import operator
import os
import re
from datetime import date
from typing import Annotated, TypedDict, Optional, Literal

import requests
from urllib.parse import urlparse
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch, TavilyExtract
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import Send, interrupt, Command
from pydantic import BaseModel, Field

from llm_config import get_llm
from main import duffel_city_country
from trip_info_graph import (
    invoke_structured_with_retry, APPROVE_SIGNALS,
    MAGAZINE_DOMAINS, UNIQUE_EXPERIENCE_DOMAINS,
)
from leg_transportation_graph import (
    discover_relevant_domains, _tavily_results, _place_tokens, _clean_place_name,
    normalize_country_fallback,
)

llm = get_llm("premium")  # recommend_stay_options stays premium
extraction_llm = get_llm("cheap")  # default tier for all search/extraction nodes

# ---------- Domain configuration ----------

AGODA_DOMAIN = ["agoda.com"]
HOTEL_CHAIN_DOMAINS = ["hyatt.com", "ihg.com", "marriott.com", "hilton.com", "accor.com"]
GENERAL_OTA_DOMAINS = ["booking.com", "hotels.com", "expedia.com"]
HOSTEL_DOMAINS = ["hostelworld.com", "hostelbookers.com"]
CHAIN_POINTS_DOMAIN = ["maxmypoint.com"]  # confirmed live via Tavily with include_domains restriction

GENERAL_OTA_DOMAINS_BY_COUNTRY = {
    "default": GENERAL_OTA_DOMAINS,
    "KR": ["yanolja.com", "yeogi.com", "booking.com"],
    "JP": ["travel.rakuten.co.jp", "jalan.net", "booking.com"],
    "CN": ["trip.com", "ctrip.com", "booking.com"],
    "IN": ["makemytrip.com", "goibibo.com", "booking.com"],
}


def _general_ota_domains(leg: "StayLeg") -> list[str]:
    """Live-discovers regionally relevant OTA domains for this leg's country, falling
    back to a small structured map (then the flat Western default) when discovery comes
    up thin — a Western-only OTA list misses local budget inventory the same way the old
    hardcoded rail/bus lists did before discover_relevant_domains was added there."""
    country = leg["country"]
    discovered = discover_relevant_domains(
        f"best hotel booking website OTA {country}",
        cache_key=(country, "lodging_ota"),
    )
    domains = list(dict.fromkeys(discovered + GENERAL_OTA_DOMAINS))
    if len(domains) < 3:
        domains += GENERAL_OTA_DOMAINS_BY_COUNTRY.get(country, GENERAL_OTA_DOMAINS_BY_COUNTRY["default"])
    return list(dict.fromkeys(domains))


# Deep-linked search-results URLs — dates are baked into the query string so the page
# itself (not a generic organic snippet) is forced to render date-specific rates.
# Verify these param names still work in the Tavily Extract playground before relying
# on them; OTA sites redesign their search URLs periodically and some pricing loads via
# client-side JS that a static extract won't see.

DIRECT_RATE_SOURCES = {
    "booking_direct": "https://www.booking.com/searchresults.html?ss={city}&checkin={check_in}&checkout={check_out}&group_adults=2&selected_currency=USD",
    "expedia_direct": "https://www.expedia.com/Hotel-Search?destination={city}&startDate={check_in}&endDate={check_out}",
}

STAY_TYPES = {"hotel", "hostel", "homestay", "apartment", "resort"}

# maps chain option names (as they'll appear from search_hotel_chains) to the program
# names a traveler might hold — keeps the points lookup from firing for a Hyatt property
# when the traveler only holds Marriott points, etc.
CHAIN_PROGRAM_ALIASES = {
    "hyatt": ["hyatt", "world of hyatt"],
    "hilton": ["hilton", "hilton honors"],
    "marriott": ["marriott", "marriott bonvoy", "bonvoy"],
    "ihg": ["ihg", "ihg one rewards"],
}

# ---------- Currency normalization ----------

_fx_cache: dict[str, Optional[float]] = {}


def _get_usd_rate(currency: str) -> Optional[float]:
    """Cached per currency for the process lifetime — re-search rounds and multiple
    legs in the same currency shouldn't re-pay the FX lookup."""
    currency = currency.upper()
    if currency == "USD":
        return 1.0
    if currency in _fx_cache:
        return _fx_cache[currency]
    try:
        resp = requests.get("https://api.frankfurter.app/latest",
                            params={"from": currency, "to": "USD"}, timeout=5)
        resp.raise_for_status()
        rate = resp.json()["rates"].get("USD")
    except Exception:
        rate = None  # unsupported currency or FX service unavailable — degrade gracefully
    _fx_cache[currency] = rate
    return rate


def _to_usd(amount: Optional[float], currency: Optional[str]) -> Optional[float]:
    if amount is None or not currency:
        return None
    rate = _get_usd_rate(currency)
    return round(amount * rate, 2) if rate is not None else None


def _nights(leg: "StayLeg") -> int:
    ci, co = date.fromisoformat(leg["check_in"]), date.fromisoformat(leg["check_out"])
    return max((co - ci).days, 1)


def _derive_night_total(price_usd, price_type, nights, party_size: int = 2):
    if price_usd is None or price_type == "unknown":
        return None, None
    if price_type == "per_night":
        return price_usd, round(price_usd * nights, 2)
    if price_type == "per_person_per_night":
        per_night = price_usd * party_size
        return per_night, round(per_night * nights, 2)
    return round(price_usd / nights, 2), price_usd  # "total"

def _pick_representative(options: list[dict]) -> dict:
    """Send() fan-out order isn't deterministic, so 'first seen' can pick an entry
    whose booking_url got filtered to None even when a sibling source has a real one.
    Prefer any entry with a populated booking_url, favoring booking_direct (date-specific
    deep link) among those, before falling back to plain first-seen."""
    with_url = [o for o in options if o.get("booking_url")]
    if with_url:
        with_url.sort(key=lambda o: o.get("source") != "booking_direct")
        return with_url[0]
    return options[0]


# Country -> plausible price currencies for THAT country's own listings. Keyed by ISO
# country code, so leg["country"] must be normalized to ISO before this is consulted —
# see derive_stay_legs, which now runs the raw dated_itinerary country string through
# normalize_country_fallback() rather than passing it through unchanged. Without that
# normalization, a leg whose country never resolved via duffel_city_country() would
# carry a raw string like "South Korea" instead of "KR", this dict would look it up and
# find nothing, and _is_plausible_currency would silently treat every currency as fine —
# the exact same fallback-format mismatch that caused the earlier flight-leg bug, just
# recurring in a different file.
PLAUSIBLE_CURRENCIES_BY_COUNTRY = {
    "KR": {"KRW", "USD"}, "ES": {"EUR", "USD"}, "PT": {"EUR", "USD"},
    "JP": {"JPY", "USD"}, "US": {"USD"}, "FR": {"EUR", "USD"},
    "TH": {"THB", "USD"}, "VN": {"VND", "USD"},
    # extend as new destinations come up — an unmapped country is never flagged, so
    # this only guards places you've actually added.
}


def _is_plausible_currency(currency: str, country: Optional[str]) -> bool:
    if not country or currency == "USD":
        return True  # USD is always a reasonable traveler-facing quoted price
    allowed = PLAUSIBLE_CURRENCIES_BY_COUNTRY.get(country)
    return currency in allowed if allowed else True  # unmapped country: don't false-flag


def _apply_pricing(d: dict, nights: int, country: Optional[str] = None) -> dict:
    """Shared by every search node so price_usd/price_per_night_usd/total_cost_usd/
    price_note are computed identically everywhere. When price_type is "unknown" but a
    real price_usd exists, don't just drop it — recommend_stay_options otherwise treats
    the option as priceless even though a real (if unlabeled) number was found.

    Also flags a currency that's implausible for the destination (e.g. a Seoul hotel
    priced in INR) — usually a session/geolocation quirk on the source page rather than
    a real local rate. The two notes are independent conditions (an option can be both
    unlabeled AND in a suspicious currency), so they're combined rather than using elif,
    which would let one note silently suppress the other."""
    d["price_usd"] = _to_usd(d.get("price_amount"), d.get("price_currency"))
    d["price_per_night_usd"], d["total_cost_usd"] = _derive_night_total(
        d["price_usd"], d.get("price_type", "unknown"), nights
    )

    notes = []
    if d["price_usd"] is not None and d.get("price_type") == "unknown":
        notes.append(
            f"${d['price_usd']:,.2f} found but not labeled as nightly or total — "
            "treat as approximate, don't assume it's the full stay cost"
        )
    if d.get("price_currency") and country and not _is_plausible_currency(d["price_currency"], country):
        notes.append(
            f"Price shown in {d['price_currency']}, unusual for {country} — may be a "
            "currency-detection error on the source page; verify before booking"
        )
    if notes:
        d["price_note"] = " | ".join(notes)

    return d

# ---------- Schemas ----------

class StayOption(BaseModel):
    type: Literal["hotel", "hostel", "homestay", "apartment", "resort"]
    name: str
    area: Optional[str] = Field(None, description="Neighborhood or district, if stated")
    price_estimate: Optional[str] = Field(None, description="Raw price text exactly as shown, e.g. '€142/night'")
    price_amount: Optional[float] = Field(
        None, description="Numeric price. If the source gives a RANGE (e.g. '$50-70', "
                          "'between $301 and $350'), set this to the midpoint — never "
                          "leave it null just because the source wasn't a single number."
    )
    price_currency: Optional[str] = Field(
        None, description="3-letter ISO 4217 code, e.g. USD, EUR, JPY — infer from symbol/context if not spelled out"
    )
    price_amount_min: Optional[float] = Field(None, description="Populate alongside price_amount when the source gave a range")
    price_amount_max: Optional[float] = Field(None, description="Populate alongside price_amount when the source gave a range")
    price_type: Literal["per_night", "total", "per_person_per_night", "unknown"] = Field(
        description="Whether price_amount is a nightly rate, a total-stay price, or a "
                    "per-person nightly rate (common on Korean/Japanese listings, e.g. "
                    "'72,600 per person, per night'). Use 'unknown' rather than guessing."
    )
    rating: Optional[str] = None
    booking_url: Optional[str] = None
    brand_classification: Literal[
        "international_chain", "local_chain", "boutique", "independent_local", "vacation_rental"
    ] = Field(description="international_chain: global brands like Hyatt/Marriott/Hilton/IHG/Accor. "
                          "local_chain: a multi-property brand operating mainly within one country/region "
                          "(e.g. Toyoko Inn, OYO, Jin Jiang). boutique: a distinctive, editorially-noted "
                          "independent property, usually design- or experience-led. independent_local: a "
                          "single-property hotel/hostel with no recognizable chain affiliation. "
                          "vacation_rental: apartments/homestays booked as a private residence.")


class StayOptions(BaseModel):
    options: list[StayOption] = Field(
        description="Every distinct viable stay found on this page for THIS city and "
                    "requested stay type(s). Do not invent options not shown."
    )


class PointsValue(BaseModel):
    percent_bookable_with_points: Optional[str] = None
    point_value_cents: Optional[str] = Field(None, description="Estimated cents-per-point value, if stated")
    note: Optional[str] = None


class StayRecommendation(BaseModel):
    ranked_option_indices: list[int] = Field(description="Indices into the options list, best first")
    reasoning: str = Field(description="1-2 sentences on why the top choice fits this stop")


class StayLeg(TypedDict):
    city: str
    country: str
    check_in: str
    check_out: str
    duration_days: int
    stay_types_requested: list[str]
    loyalty_programmes: list[str]  # e.g. ["Marriott Bonvoy", "Hyatt"] — empty list skips points lookup


class StayLegState(TypedDict):
    leg: StayLeg
    raw_options: Annotated[list[dict], operator.add]  # parallel search writes, never cleared
    reconciled_options: list[dict]  # this round's merged/confidence-tagged options, single-writer
    options: list[dict]  # recommended/ordered snapshot, single-writer
    recommendation_reasoning: Optional[str]
    search_round: int
    selected: Optional[dict]
    review_decision: Optional[str]
    review_feedback: Optional[str]
    finalized_stays: Annotated[list[dict], operator.add]


class LodgingPlanningState(TypedDict):
    dated_itinerary: list[dict]
    loyalty_programmes: list[str]
    stay_legs: list[StayLeg]
    finalized_stays: Annotated[list[dict], operator.add]


# ---------- Leg derivation ----------

def derive_stay_legs(state: LodgingPlanningState):
    stops = state["dated_itinerary"]
    legs = [{
        "city": s["city"],
        # duffel_city_country() returns real ISO when it resolves; when it doesn't,
        # normalize_country_fallback() converts the raw LLM-generated country string
        # (e.g. "South Korea") to ISO too, so leg["country"] is ALWAYS ISO by the time
        # it's used anywhere downstream — including PLAUSIBLE_CURRENCIES_BY_COUNTRY
        # lookups in _apply_pricing, which would otherwise silently no-op on a raw
        # country name it doesn't recognize.
        "country": duffel_city_country(_clean_place_name(s["city"])) or normalize_country_fallback(s["country"]),
        "check_in": s["depart_date"],
        "check_out": s["return_date"],
        "duration_days": s["duration_days"],
        "stay_types_requested": ["hotel"],  # default, overridable in classify_stay_types
        "loyalty_programmes": state.get("loyalty_programmes", []),
    } for s in stops if s["duration_days"] > 0]  # skip pure same-day transit stops
    return {"stay_legs": legs}


def _apply_type_overrides(legs: list[dict], raw: str) -> list[dict]:
    # raw format: "0: hostel,homestay | 2: hotel"
    overrides = {}
    for chunk in raw.split("|"):
        idx, _, types = chunk.partition(":")
        if idx.strip().isdigit():
            overrides[int(idx.strip())] = [t.strip() for t in types.split(",") if t.strip() in STAY_TYPES]
    return [
        {**leg, "stay_types_requested": overrides.get(i, leg["stay_types_requested"])}
        for i, leg in enumerate(legs)
    ]


def classify_stay_types(state: LodgingPlanningState):
    raw = interrupt({
        "type": "stay_type_review",
        "message": "Confirm stay type per stop (e.g. '0: hostel,homestay | 2: hotel'), "
                   "or 'approve' for hotels everywhere.",
        "stay_legs": state["stay_legs"],
    })
    legs = state["stay_legs"] if raw.strip().lower() in APPROVE_SIGNALS else _apply_type_overrides(state["stay_legs"],
                                                                                                   raw)
    return {"stay_legs": legs}


def fan_out_stays(state: LodgingPlanningState):
    return [Send("plan_stay", {"leg": leg, "options": [], "raw_options": []}) for leg in state["stay_legs"]]


def fan_out_stay_sources(state: StayLegState):
    sends = [
        Send("search_agoda", state),
        Send("search_general_ota", state),
        Send("search_unique_stays", state),
        Send("search_rates_direct", state),
    ]
    if "hotel" in state["leg"]["stay_types_requested"]:
        sends.append(Send("search_hotel_chains", state))
    return sends


# ---------- Helpers ----------

def _url_matches_city(url: str | None, city: str) -> bool:
    if not url:
        return True
    url_lower = url.lower()
    return any(tok in url_lower for tok in _place_tokens(city))


def _is_wrapped_redirect(url: str | None) -> bool:
    """Tavily's own click-tracking wrapper (e.g. '/goto?url=...') — not a real link
    to the property/booking page, so never store these as booking_url."""
    if not url:
        return False
    return url.startswith("/goto") or "goto?url=" in url


def _parse_city_areas(city: str) -> tuple[str, list[str]]:
    """Splits 'Seoul (Gangnam/Itaewon)' into ('Seoul', ['Gangnam', 'Itaewon']). A combined
    query like 'Seoul Gangnam/Itaewon hotel' searches poorly and lets off-area results
    (e.g. a Jongno-gu hotel) slip through on a bare city-name match — searching each area
    separately gets real results and lets the extraction prompt enforce area relevance.
    Returns (city, []) unchanged if there's no parenthetical breakdown."""
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", city.strip())
    if not m:
        return city.strip(), []
    base = m.group(1).strip()
    areas = [a.strip() for a in re.split(r"[/,]| and ", m.group(2)) if a.strip()]
    return base, areas


def _is_generic_listing_page(url: str) -> bool:
    """City/district hub pages (e.g. booking.com/city/kr/seoul.html or
    .../district/kr/seoul/gangnam-gu.html) are not a specific property's booking page —
    never store these as booking_url even if the domain and city both match."""
    url_lower = url.lower()
    return any(marker in url_lower for marker in ("/city/", "/district/", "/region/", "/country/"))


NON_BOOKING_SUFFIXES = ("/photos", "/photo", "/gallery", "/reviews", "/review", "/map")


def _strip_non_booking_subpath(url: str) -> str:
    """A property page found via extraction sometimes points at a photo gallery or
    reviews tab rather than the rooms/booking page. Trim the trailing subpath back to
    the property's base page, which on most hotel sites IS the booking entry point."""
    stripped = url.rstrip("/")
    for suffix in NON_BOOKING_SUFFIXES:
        if stripped.endswith(suffix):
            base = stripped[: -len(suffix)]
            return base or url
    return url


def _clean_url(url: str | None, city: str, allowed_domains: list[str]) -> Optional[str]:
    if not url or _is_wrapped_redirect(url) or _is_generic_listing_page(url):
        return None
    netloc = urlparse(url).netloc.replace("www.", "")
    if not any(netloc == d or netloc.endswith("." + d) for d in allowed_domains):
        return None  # not actually from a domain this node searched — likely a widget/off-site link
    if not _url_matches_city(url, city):
        return None
    return _strip_non_booking_subpath(url)


_NAME_STOPWORDS = {"the", "hotel", "hotels", "resort", "resorts", "spa"}


def _normalize_name(name: str) -> str:
    """Strips punctuation and common filler words (the/hotel/resort/spa) so 'The Aloft
    Seoul Gangnam Hotel' and 'Aloft Seoul Gangnam' key the same. Trade-off: two distinct
    but similarly-named budget properties could theoretically collide — acceptable, since
    a false "corroborated" tag is a much smaller error than failing to dedupe the same
    property across sources, which was silently under-counting corroboration before."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    tokens = [t for t in cleaned.split() if t not in _NAME_STOPWORDS]
    return " ".join(tokens)


def _key(o: dict) -> tuple:
    return (o["type"], _normalize_name(o.get("name") or ""))


def _matches_loyalty_programme(chain_name: str, loyalty_programmes: list[str]) -> bool:
    chain_lower = chain_name.lower()
    held = {p.lower() for p in loyalty_programmes}
    for aliases in CHAIN_PROGRAM_ALIASES.values():
        if any(a in chain_lower for a in aliases) and held & set(aliases):
            return True
    return False


def _format_date_query(check_in: str, check_out: str) -> str:
    ci, co = date.fromisoformat(check_in), date.fromisoformat(check_out)
    nights = (co - ci).days
    return f"{ci.strftime('%b %d')}\u2013{co.strftime('%b %d, %Y')} ({nights} nights) nightly rate"


# ---------- Search nodes ----------

stay_extraction_instructions = """You are extracting accommodation options from a hotel/
booking search results page for ONE specific city and specific stay type(s).

Extract every DISTINCT listing relevant to the requested type(s) (hotel, hostel, homestay,
apartment, resort) that genuinely appears on this page. If you cannot confirm a listing is
actually in the requested city, exclude it rather than guessing. If the page shows nothing
relevant to the requested type(s), return options=[] — do not fabricate anything, and never
substitute a listing from a different city.

For each listing, also classify brand_classification using the property name and any brand
cues on the page: recognizable global chains (Hyatt, Marriott, Hilton, IHG, Accor, etc.) are
international_chain; a multi-property brand operating mainly within one country or region is
local_chain; a distinctive independently-branded property is boutique if it reads as
design/experience-led, otherwise independent_local; apartments and homestays booked as a
private residence are vacation_rental. Use your best judgment from the name and content —
don't leave it blank.

Whenever a price appears, populate price_estimate (raw text exactly as shown, e.g.
'€142/night'), price_amount + price_currency (the numeric value and its ISO 4217 code, e.g.
142.0 and "EUR"), AND price_type — whether that figure is a per-night rate for the whole room,
a total price for the whole stay, or a PER-PERSON per-night rate. Watch for phrasing like
'per person, per night', 'per person/night', or 'pp/night' — these are common on Korean and
Japanese listings and mean the shown figure covers ONE guest for ONE night, not the whole room.
Use price_type='per_person_per_night' for these rather than defaulting to 'per_night', since
treating a per-person figure as a full-room rate understates the real cost. Use 'unknown' for
price_type rather than guessing if it isn't clear; never leave price_amount populated with
price_type left as a guess dressed up as certainty.

For booking_url, if the page offers multiple links for the same property, prefer one that
leads to rooms, rates, or booking/availability — not a photo gallery, review page, or map
view. Only fall back to a general property page if no more specific link is available.

When a price is given as a RANGE rather than a single number (e.g. 'USD 50-70 per
night', '$26 to $50', 'between $301 and $350'), you MUST still populate price_amount
— set it to the midpoint of the range, and additionally populate price_amount_min and
price_amount_max with the range bounds. Do not leave price_amount null just because
the source gave a range instead of one number; a null price_amount means 'no price
was found,' which is different from 'a price range was found.'
"""

rate_extraction_instructions = """You are extracting hotel listings AND their prices from a
live search-results page that was loaded with a specific check-in and check-out date already
applied as URL parameters. Extract price_estimate exactly as shown — do not average,
estimate, or carry over a price from a different date range. Populate price_amount,
price_currency, and price_type (per_night vs total — OTA search results pages often show a
per-night rate; read the actual label rather than assuming). Also classify
brand_classification per the rules above. If the page didn't actually render pricing (e.g. a
generic landing page instead of results), return options=[] rather than guessing.

For booking_url, prefer a link to the specific room/rate selection for that listing over a
generic property or photo link, if the page offers one."""

points_extraction_instructions = """You are extracting reward-points value data for ONE
specific hotel property from a rewards-tracking page. Only extract numbers that clearly
apply to this named property. If the page doesn't cover this specific hotel, return an
object with all fields null — do not estimate or infer numbers not shown.

Content here is often a short listing snippet (e.g. "Hyatt New York, NY, US 99%") rather
than a full table — that percentage is percent_bookable_with_points. A cents-per-point
value (e.g. "1.4 ~ 4.4 ¢") is only sometimes present; leave point_value_cents null when
it isn't shown rather than guessing from the percentage alone."""

editorial_price_caveat = """

This content is from travel editorial/magazine sites, which sometimes embed third-party
price-comparison widgets. Only populate price fields if a specific rate is stated in the
article's own prose about this specific property — never take a number or link from an
embedded booking widget, ad module, or unrelated "compare rates" element. When in doubt,
leave price_amount, price_currency, price_type, and booking_url null; this source is for
discovering distinctive properties, not for verified pricing."""


def _run_stay_search(leg: StayLeg, domains: list[str], type_label: str,
                      feedback: Optional[str], source: str, round_num: int,
                      extra_instructions: str = "", split_by_area: bool = True,
                      search_llm: Optional[ChatOpenAI] = None) -> list[dict]:
    base_city, areas = _parse_city_areas(leg["city"])
    # Chain-brand sources (Hyatt/Marriott/etc.) are a brand+city search, not neighborhood-scoped
    # the way Agoda/OTA listings are — splitting by area there just doubles calls for no new
    # results, so split_by_area=False keeps it to one search against the whole city.
    search_targets = areas if (areas and split_by_area) else [None]
    nights = _nights(leg)
    tagged: list[dict] = []

    # Default to the cheap tier — callers should pass search_llm explicitly, but this
    # fallback matters: previously it fell back to the module-level premium `llm`,
    # which silently routed search_agoda/search_hotel_chains/search_general_ota onto
    # Sonnet 5 on every call since none of them passed search_llm. Confirmed via
    # OpenRouter logs — Sonnet 5 calls were firing as often as DeepSeek ones, with
    # input token counts matching search-extraction payloads, not the once-per-leg
    # recommend_stay_options call.
    resolved_llm = search_llm or extraction_llm

    for area in search_targets:
        location_label = f"{base_city} {area}" if area else base_city
        query = f"{location_label} {type_label} {_format_date_query(leg['check_in'], leg['check_out'])}"
        if feedback:
            query += f" — traveler feedback: {feedback}"

        data = TavilySearch(max_results=3, include_domains=domains, include_raw_content="text").invoke({"query": query})
        docs = [d for d in _tavily_results(data) if _url_matches_city(d.get("url"), base_city)]
        for d in docs:
            if d.get("raw_content"):
                d["raw_content"] = d["raw_content"][:6000]
        if not docs:
            continue

        area_instructions = extra_instructions
        if area:
            area_instructions += (
                f"\n\nThe traveler specifically wants this stop to be in or very near the "
                f"{area} area of {base_city} — exclude listings that are clearly in a "
                f"different, unrelated district, even if they're still technically in {base_city}."
            )

        structured_llm = resolved_llm.with_structured_output(StayOptions)
        result = invoke_structured_with_retry(structured_llm, [
            SystemMessage(content=stay_extraction_instructions + area_instructions),
            HumanMessage(content=json.dumps(docs)),
        ], StayOptions)

        for opt in result.options:
            if opt.type not in leg["stay_types_requested"] and leg["stay_types_requested"] != ["hotel"]:
                # only filter strictly when the traveler asked for something specific;
                # default "hotel" leg still accepts anything Agoda/OTA surfaces as a fallback
                continue
            d = opt.model_dump()
            d["booking_url"] = _clean_url(d.get("booking_url"), base_city, domains)
            d = _apply_pricing(d, nights, country=leg["country"])
            tagged.append({**d, "source": source, "round": round_num, "search_query": query, "matched_area": area})

    return tagged


def search_agoda(state: StayLegState):
    leg = state["leg"]
    type_label = "/".join(leg["stay_types_requested"])
    domains = AGODA_DOMAIN + (HOSTEL_DOMAINS if "hostel" in leg["stay_types_requested"] else [])
    options = _run_stay_search(leg, domains, type_label, state.get("review_feedback"),
                               "agoda", state.get("search_round", 0),
                               search_llm=extraction_llm)
    return {"raw_options": options}


def search_hotel_chains(state: StayLegState):
    leg = state["leg"]
    options = _run_stay_search(leg, HOTEL_CHAIN_DOMAINS, "hotel loyalty programme",
                               state.get("review_feedback"), "chain", state.get("search_round", 0),
                               split_by_area=False, search_llm=extraction_llm)
    return {"raw_options": options}


def search_general_ota(state: StayLegState):
    """Independent corroboration source, separate from Agoda — same purpose as
    verify_route_options in the transport graph."""
    leg = state["leg"]
    type_label = "/".join(leg["stay_types_requested"])
    domains = _general_ota_domains(leg) + (HOSTEL_DOMAINS if "hostel" in leg["stay_types_requested"] else [])
    options = _run_stay_search(leg, domains, type_label, state.get("review_feedback"),
                               "general_ota", state.get("search_round", 0),
                               search_llm=extraction_llm)
    return {"raw_options": options}

_editorial_llm = get_llm("mid")  # module-level, avoid re-instantiating per call

def search_unique_stays(state: StayLegState):
    leg = state["leg"]
    domains = MAGAZINE_DOMAINS + UNIQUE_EXPERIENCE_DOMAINS
    options = _run_stay_search(leg, domains, "unique boutique stay", state.get("review_feedback"),
                               "editorial", state.get("search_round", 0),
                               extra_instructions=editorial_price_caveat,
                               search_llm=_editorial_llm)
    return {"raw_options": options}


def search_rates_direct(state: StayLegState):
    """Deep-links directly into Booking.com / Expedia search results with the traveler's
    exact dates baked into the URL, then Extracts (not searches) the rendered page — this
    is the source most likely to reflect real, date-specific pricing rather than a generic
    organic snippet. Silently returns nothing if a page fails to render statically-visible
    content (common on JS-heavy OTA pages), rather than breaking the graph."""
    leg = state["leg"]
    base_city, areas = _parse_city_areas(leg["city"])
    search_targets = areas if areas else [None]
    nights = _nights(leg)
    extractor = TavilyExtract(extract_depth="advanced")
    tagged = []

    for area in search_targets:
        location_label = f"{base_city} {area}" if area else base_city
        city_q = location_label.replace(" ", "+")
        urls = {src: tmpl.format(city=city_q, check_in=leg["check_in"], check_out=leg["check_out"])
                for src, tmpl in DIRECT_RATE_SOURCES.items()}

        area_instructions = ""
        if area:
            area_instructions = (
                f"\n\nThe traveler specifically wants this stop to be in or very near the "
                f"{area} area of {base_city} — exclude listings that are clearly in a "
                f"different, unrelated district, even if they're still technically in {base_city}."
            )

        for source, url in urls.items():
            try:
                result = extractor.invoke({"urls": [url]})
            except Exception:
                continue
            pages = result.get("results", []) if isinstance(result, dict) else []
            if not pages or not pages[0].get("raw_content"):
                continue

            structured_llm = extraction_llm.with_structured_output(StayOptions)
            parsed = invoke_structured_with_retry(structured_llm, [
                SystemMessage(content=rate_extraction_instructions + area_instructions),
                HumanMessage(content=pages[0]["raw_content"][:8000]),
            ], StayOptions)

            for opt in parsed.options:
                d = opt.model_dump()
                source_domain = urlparse(url).netloc.replace("www.", "")
                d["booking_url"] = _clean_url(d.get("booking_url"), base_city, [source_domain]) or url
                d = _apply_pricing(d, nights, country=leg["country"])
                # the URL itself IS the query here — pointing straight at the exact dated search
                tagged.append({**d, "source": source, "round": state.get("search_round", 0),
                               "date_specific": True, "search_query": url, "matched_area": area})
    return {"raw_options": tagged}


# ---------- Reconciliation ----------

def _best_available_total(opt: dict) -> Optional[float]:
    """Prefer the representative option's own total_cost_usd; if that's null
    but a corroborating source in price_by_source parsed a real number,
    fall back to that rather than showing 'n/a' when better data exists
    right next to it (e.g. Agoda's unparsed '$301-$350' range alongside
    Expedia's clean $392/night, $1,176 total for the same property)."""
    if opt.get("total_cost_usd") is not None:
        return opt["total_cost_usd"]
    for src_data in (opt.get("price_by_source") or {}).values():
        if src_data.get("total_cost_usd") is not None:
            return src_data["total_cost_usd"]
    return None

def reconcile_stay_options(state: StayLegState):
    """Merge this round's raw_options into a single confidence-tagged list.
    Writes to reconciled_options (single-writer) rather than back into raw_options
    (Annotated + operator.add), so the merge doesn't duplicate entries on top of
    themselves across supersteps."""
    latest = max((o.get("round", 0) for o in state["raw_options"]), default=0)
    current = [o for o in state["raw_options"] if o.get("round", 0) == latest]

    source_counts: dict[tuple, set] = {}
    price_by_key: dict[tuple, dict] = {}
    date_specific_keys: set = set()
    for o in current:
        k = _key(o)
        source_counts.setdefault(k, set()).add(o["source"])
        if o.get("price_estimate"):
            price_by_key.setdefault(k, {})[o["source"]] = {
                "price_estimate": o["price_estimate"],
                "price_per_night_usd": o.get("price_per_night_usd"),
                "total_cost_usd": o.get("total_cost_usd"),
            }
        if o.get("date_specific"):
            date_specific_keys.add(k)

    # Group all raw options per listing (across sources) instead of keeping only the
    # first one seen — fan-out order isn't deterministic, so first-seen can pick an
    # entry with a nulled-out booking_url even when a sibling source has a good one.
    grouped: dict[tuple, list[dict]] = {}
    for o in current:
        grouped.setdefault(_key(o), []).append(o)

    merged = []
    for k, group in grouped.items():
        o = _pick_representative(group)
        if k in date_specific_keys:
            confidence = "date_verified"
        elif len(source_counts[k]) >= 2:
            confidence = "corroborated"
        else:
            confidence = "unverified"
        entry = {**o, "confidence": confidence}
        if len(price_by_key.get(k, {})) > 1:
            entry["price_by_source"] = price_by_key[k]  # surfaces disagreement between sources, now in USD too
        merged.append(entry)
    return {"reconciled_options": merged}


# ---------- Points-value enrichment (MaxMyPoint) ----------

def enrich_points_value(state: StayLegState):
    """Enrich chain-hotel options with reward-night value/bookable-with-points info from
    MaxMyPoint. Only runs for options tagged source == "chain" whose brand matches a
    program the traveler actually holds — skipped entirely when loyalty_programmes is
    empty, to avoid paying for a lookup nobody can use."""
    leg = state["leg"]
    if not leg["loyalty_programmes"]:
        return {}

    reconciled = state["reconciled_options"]
    candidates = [o for o in reconciled
                  if o["source"] == "chain" and _matches_loyalty_programme(o["name"], leg["loyalty_programmes"])]
    if not candidates:
        return {}

    enriched_by_name = {}
    for opt in candidates:
        data = TavilySearch(
            max_results=3, include_domains=CHAIN_POINTS_DOMAIN,
            search_depth="advanced", include_raw_content="text",
        ).invoke({"query": f"{opt['name']} {leg['city']} points value bookable"})
        docs = [d for d in _tavily_results(data) if not _is_wrapped_redirect(d.get("url"))]
        if not docs:
            continue
        for d in docs:
            if d.get("raw_content"):
                d["raw_content"] = d["raw_content"][:3000]

        structured_llm = extraction_llm.with_structured_output(PointsValue)
        pv = invoke_structured_with_retry(structured_llm, [
            SystemMessage(content=points_extraction_instructions),
            HumanMessage(content=json.dumps(docs)),
        ], PointsValue)
        if pv.percent_bookable_with_points or pv.point_value_cents:
            enriched_by_name[opt["name"]] = pv.model_dump()

    if not enriched_by_name:
        return {}

    updated = [
        {**o, "points_value": enriched_by_name[o["name"]]} if o["name"] in enriched_by_name else o
        for o in reconciled
    ]
    return {"reconciled_options": updated}


# ---------- Recommendation, review, finalize ----------

recommendation_instructions = """You are recommending the best accommodation for one stop of
a trip, given all real options found. Consider genuine trade-offs a traveler would care about:
- Fit with the requested stay type(s) for this stop
- Compare using total_cost_usd (the real cost of this stop) as the primary price signal, not
  price_per_night_usd alone — a cheaper nightly rate at a longer stop can still lose to a
  pricier-per-night option at a shorter one. Mention price_per_night_usd only as supporting
  context (e.g. "great nightly rate, but the longer stay pushes the total up")
- If total_cost_usd/price_per_night_usd are null but a "price_note" field is present, a real
  price (price_usd) was found but couldn't be confidently labeled as nightly-vs-total — don't
  treat the option as priceless, factor the number in but flag the ambiguity in your reasoning
  rather than presenting it as precisely comparable to labeled options
- Confidence tier: "date_verified" (priced with the traveler's exact dates already applied)
  is most trustworthy on price, "corroborated" (2+ independent sources agree it exists) is
  next, "unverified" (single source) is weakest but still worth surfacing — smaller
  homestays/hostels often only appear on one source
- If "price_by_source" is present and sources disagree meaningfully on total_cost_usd,
  mention the spread rather than silently picking one number
- brand_classification as a fit signal: international_chain suits travelers who value
  loyalty points/consistency, boutique/independent_local suits travelers seeking local
  character — weigh this against what the traveler's preferences suggest they want
- If an option has a "points_value" entry, note it in your reasoning (e.g. a chain hotel
  that's a strong points redemption may be worth ranking above a slightly cheaper cash
  option) — but this is a bonus factor, not a reason to override a clearly better fit
- Only state a specific price or total cost in your reasoning if it is backed by a
  non-null price_amount, total_cost_usd, or price_per_night_usd field on that option.
  If price_estimate contains text (e.g. a range) but the structured price fields are
  null, describe it as 'pricing not confidently parsed — see price_estimate text'
  rather than doing your own arithmetic on the raw string and presenting it as a
  verified number.
Return every option's index in ranked_option_indices, best to worst — don't drop any."""


def recommend_stay_options(state: StayLegState):
    current = state["reconciled_options"]
    if not current:
        return {"options": [], "recommendation_reasoning": None}

    structured_llm = llm.with_structured_output(StayRecommendation)
    rec = invoke_structured_with_retry(structured_llm, [
        SystemMessage(content=recommendation_instructions),
        HumanMessage(content=f"Stop: {state['leg']['city']} ({state['leg']['check_in']} to "
                             f"{state['leg']['check_out']}, {_nights(state['leg'])} nights)\n"
                             f"Requested type(s): {state['leg']['stay_types_requested']}\n"
                             f"Options: {json.dumps(current)}"),
    ], StayRecommendation)

    ranked = [current[i] for i in rec.ranked_option_indices if 0 <= i < len(current)]
    # safety net: if the model dropped any options from its ranking, append them at the end
    # rather than silently losing them
    missing = [o for i, o in enumerate(current) if i not in rec.ranked_option_indices]
    ranked.extend(missing)

    return {"options": ranked, "recommendation_reasoning": rec.reasoning}


def review_stay(state: StayLegState):
    if not state["options"]:
        raw = interrupt({
            "type": "stay_review",
            "message": f"{state['leg']['city']}: no options found for the requested stay "
                       "type(s). Reply with feedback to re-search, or 'skip' to leave unresolved.",
            "recommendation_reasoning": None,
            "options": [],
        })
        if raw.strip().lower() == "skip":
            return {"selected": None, "review_decision": "finalize"}
        return {"review_feedback": raw, "review_decision": "revise"}

    raw = interrupt({
        "type": "stay_review",
        "message": f"{state['leg']['city']}: reply 'approve' to take the recommendation, "
                   "an index to pick another, or feedback to re-search.",
        "recommendation_reasoning": state.get("recommendation_reasoning"),
        "options": state["options"],
    })
    if raw.strip().lower() in APPROVE_SIGNALS:
        return {"selected": state["options"][0], "review_decision": "finalize"}
    if raw.strip().isdigit() and int(raw) < len(state["options"]):
        return {"selected": state["options"][int(raw)], "review_decision": "finalize"}
    return {"review_feedback": raw, "review_decision": "revise"}


def route_stay_review(state: StayLegState):
    return "finalize_stay" if state.get("review_decision") == "finalize" else "increment_round"


def increment_round(state: StayLegState):
    return {"search_round": state.get("search_round", 0) + 1}


def finalize_stay(state: StayLegState):
    return {"finalized_stays": [{**state["leg"], "selected": state["selected"]}]}


def aggregate_stays(state: LodgingPlanningState):
    # no-op passthrough — Send()'d branches already merged finalized_stays via operator.add
    return {}


# ---------- Graph wiring ----------

stay_builder = StateGraph(StayLegState)

stay_builder.add_node("search_agoda", search_agoda)
stay_builder.add_node("search_hotel_chains", search_hotel_chains)
stay_builder.add_node("search_general_ota", search_general_ota)
stay_builder.add_node("search_unique_stays", search_unique_stays)
stay_builder.add_node("search_rates_direct", search_rates_direct)
stay_builder.add_node("reconcile_stay_options", reconcile_stay_options)
stay_builder.add_node("enrich_points_value", enrich_points_value)
stay_builder.add_node("recommend_stay_options", recommend_stay_options)
stay_builder.add_node("review_stay", review_stay)
stay_builder.add_node("increment_round", increment_round)
stay_builder.add_node("finalize_stay", finalize_stay)

stay_builder.add_conditional_edges(
    START, fan_out_stay_sources,
    ["search_agoda", "search_hotel_chains", "search_general_ota", "search_unique_stays", "search_rates_direct"],
)

# Every search node feeds reconcile_stay_options — this is the ONLY path forward from search.
for node in ["search_agoda", "search_hotel_chains", "search_general_ota", "search_unique_stays", "search_rates_direct"]:
    stay_builder.add_edge(node, "reconcile_stay_options")

stay_builder.add_edge("reconcile_stay_options", "enrich_points_value")
stay_builder.add_edge("enrich_points_value", "recommend_stay_options")
stay_builder.add_edge("recommend_stay_options", "review_stay")

stay_builder.add_conditional_edges(
    "review_stay", route_stay_review,
    ["finalize_stay", "increment_round"],
)

stay_builder.add_conditional_edges(
    "increment_round", fan_out_stay_sources,
    ["search_agoda", "search_hotel_chains", "search_general_ota", "search_unique_stays", "search_rates_direct"],
)

stay_builder.add_edge("finalize_stay", END)

builder = StateGraph(LodgingPlanningState)
builder.add_node("derive_stay_legs", derive_stay_legs)
builder.add_node("classify_stay_types", classify_stay_types)
builder.add_node("plan_stay", stay_builder.compile(name="plan_stay"))
builder.add_node("aggregate_stays", aggregate_stays)

builder.add_edge(START, "derive_stay_legs")
builder.add_edge("derive_stay_legs", "classify_stay_types")
builder.add_conditional_edges("classify_stay_types", fan_out_stays, ["plan_stay"])
builder.add_edge("plan_stay", "aggregate_stays")
builder.add_edge("aggregate_stays", END)

lodging_graph = builder.compile()

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "1"}}
    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    dated_itinerary_raw = input("Paste the dated_itinerary JSON from trip_info_graph: ")
    loyalty_raw = input("Loyalty programmes held (JSON list, or blank for []): ").strip()
    result = graph.invoke(
        {
            "dated_itinerary": json.loads(dated_itinerary_raw),
            "loyalty_programmes": json.loads(loyalty_raw) if loyalty_raw else [],
            "stay_legs": [],
            "finalized_stays": [],
        },
        config=config,
    )

    while "__interrupt__" in result:
        data = result["__interrupt__"][0].value
        kind = data["type"]

        if kind == "stay_type_review":
            print("\nProposed stops:")
            for i, leg in enumerate(data["stay_legs"]):
                print(f"  [{i}] {leg['city']} ({leg['check_in']} → {leg['check_out']}) — "
                      f"types: {leg['stay_types_requested']}")
            raw = input("\nApprove all (blank/approve), or override e.g. '0: hostel,homestay | 2: hotel': ")
            result = graph.invoke(Command(resume=raw), config=config)

        elif kind == "stay_review":
            print(f"\n{data['message']}")
            if data.get("recommendation_reasoning"):
                print(f"  Recommendation: {data['recommendation_reasoning']}")
            for i, opt in enumerate(data["options"]):
                pn = f"${opt['price_per_night_usd']:,.2f}/night" if opt.get(
                    "price_per_night_usd") is not None else "night rate n/a"
                tot = f"${_best_available_total(opt):,.2f} total" if _best_available_total(opt) is not None else "total n/a"
                if opt.get("price_note"):
                    tot = opt["price_note"]  # unlabeled-but-real price and/or currency-mismatch caveat
                pv = opt.get("points_value")
                pv_str = f" — points: {pv}" if pv else ""
                price_spread = opt.get("price_by_source")
                spread_str = f" — by source: {price_spread}" if price_spread else ""
                area = opt.get("matched_area")
                area_str = f" [{area}]" if area else ""
                print(f"  [{i}] {opt['type']} ({opt['brand_classification']}) — {opt.get('name')}{area_str} — "
                      f"{pn} / {tot} — {opt['confidence']}{spread_str}{pv_str}")
                print(f"      query: {opt.get('search_query')}")
            raw = input("Your choice: ")
            result = graph.invoke(Command(resume=raw), config=config)

        else:
            raise ValueError(f"Unhandled interrupt type: {kind}")

    print("\nFinalized stays:")
    for leg in result["finalized_stays"]:
        sel = leg["selected"]
        if sel:
            pn = f"${sel['price_per_night_usd']:,.2f}/night" if sel.get(
                "price_per_night_usd") is not None else "night rate n/a"
            tot = f"${_best_available_total(sel):,.2f} total" if _best_available_total(sel) is not None else "total n/a"
            print(f"  {leg['city']}: {sel['type']} ({sel['brand_classification']}) — {sel.get('name')} "
                  f"({pn} / {tot}, {sel['confidence']})")
            print(f"    query: {sel.get('search_query')}")
        else:
            print(f"  {leg['city']}: unresolved (skipped)")
else:
    graph = builder.compile()