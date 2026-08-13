from typing import Optional

from pydantic import BaseModel

class Money(BaseModel):
    base_amount: float
    tax_amount: float
    total_amount: float
    currency: str

class Carrier(BaseModel):
    iata_code: str
    name: str

class Place(BaseModel):
    iata_code: str
    name: str
    type: str
    city_name: Optional[str] = None
    country_code: Optional[str] = None
    time_zone: Optional[str] = None

class Wifi(BaseModel):
    available: Optional[bool] = None
    cost: Optional[str] = None

class Amenities(BaseModel):
    wifi: Wifi
    seat_pitch: Optional[str] = None
    power_available: Optional[bool] = None

class Cabin(BaseModel):
    class_name: str
    marketing_name: Optional[str] = None
    amenities: Amenities

class Baggage(BaseModel):
    type: str
    quantity: int

class Segment(BaseModel):
    operating_carrier: Carrier
    marketing_carrier: Carrier
    operating_flight_number: Optional[str] = None
    marketing_flight_number: Optional[str] = None
    aircraft: Optional[str] = None
    origin: Place
    destination: Place
    departing_at: Optional[str] = None
    arriving_at: Optional[str] = None
    duration: Optional[str] = None
    cabin: Cabin
    fare_basis_code: Optional[str] = None
    baggages: list[Baggage] = []

class SliceConditions(BaseModel):
    change_before_departure_allowed: Optional[bool] = None
    change_before_departure_penalty: Optional[str] = None
    advance_seat_selection_included: Optional[bool] = None

class Slice(BaseModel):
    origin: Place
    destination: Place
    duration: str
    stops: int
    fare_brand_name: Optional[str] = None
    conditions: SliceConditions
    segments: list[Segment]

class OfferConditions(BaseModel):
    refund_before_departure_allowed: Optional[bool] = None
    refund_before_departure_penalty: Optional[str] = None
    change_before_departure_allowed: Optional[bool] = None
    change_before_departure_penalty: Optional[str] = None

class FlightOffer(BaseModel):
    id: str
    owner: Carrier
    price: Money
    supported_loyalty_programmes: list[str]
    conditions: OfferConditions
    expires_at: str
    slices: list[Slice]

def _safe(d: Optional[dict], key: str, default=None):
    """dict.get(key, default) only falls back to `default` when the key is
    MISSING. Duffel frequently sends an explicit null for amenities/cabin/
    conditions fields that aren't populated for a given fare, which returns
    None (not default) and breaks any chained .get() on the result. This
    treats an explicit null the same as a missing key."""
    if d is None:
        return default
    value = d.get(key, default)
    return default if value is None else value

def extract_place(p: dict) -> Place:
    return Place(
        iata_code=p["iata_code"],
        name=p["name"],
        type=p["type"],
        city_name=p.get("city_name"),          # direct field, not nested
        country_code=p.get("iata_country_code"),
        time_zone=p.get("time_zone"),
    )

def extract_carrier(c: dict) -> Carrier:
    return Carrier(iata_code=c["iata_code"], name=c["name"])

def extract_segment(seg: dict) -> Segment:
    passenger_info = seg["passengers"][0]
    cabin_data = _safe(passenger_info, "cabin", {})
    amenities_data = _safe(cabin_data, "amenities", {})
    wifi_data = _safe(amenities_data, "wifi", {})
    seat_data = _safe(amenities_data, "seat", {})
    power_data = _safe(amenities_data, "power", {})

    return Segment(
        operating_carrier=extract_carrier(seg["operating_carrier"]),
        marketing_carrier=extract_carrier(seg["marketing_carrier"]),
        operating_flight_number=seg["operating_carrier_flight_number"],
        marketing_flight_number=seg["marketing_carrier_flight_number"],
        aircraft=seg.get("aircraft", {}).get("name") if seg.get("aircraft") else None,
        origin=extract_place(seg["origin"]),
        destination=extract_place(seg["destination"]),
        departing_at=seg["departing_at"],
        arriving_at=seg["arriving_at"],
        duration=seg["duration"],
        fare_basis_code=passenger_info.get("fare_basis_code"),
        cabin=Cabin(
            class_name=passenger_info.get("cabin_class", ""),
            marketing_name=cabin_data.get("marketing_name"),
            amenities=Amenities(
                wifi=Wifi(available=wifi_data.get("available"), cost=wifi_data.get("cost")),
                seat_pitch=seat_data.get("pitch"),
                power_available=power_data.get("available"),
            ),
        ),
        baggages=[Baggage(type=b["type"], quantity=b["quantity"]) for b in seg.get("baggages", [])],
    )

def extract_condition_flag(value) -> Optional[bool]:
    """Some Duffel condition fields come back as a plain bool,
    others as an object like {"allowed": bool, "penalty_amount": ...}."""
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return value.get("allowed")
    return None

def extract_condition_penalty(value) -> Optional[str]:
    if isinstance(value, dict):
        return value.get("penalty_amount")
    return None  # plain bool has no penalty info

def extract_slice(s: dict) -> Slice:
    segments = [extract_segment(seg) for seg in s["segments"]]
    conditions = _safe(s, "conditions", {})
    change = _safe(conditions, "change_before_departure")
    seat = _safe(conditions, "advance_seat_selection")

    return Slice(
        origin=extract_place(s["origin"]),
        destination=extract_place(s["destination"]),
        duration=s["duration"],
        stops=len(segments) - 1,
        fare_brand_name=s.get("fare_brand_name"),
        conditions=SliceConditions(
            change_before_departure_allowed=extract_condition_flag(change),
            change_before_departure_penalty=extract_condition_penalty(change),
            advance_seat_selection_included=extract_condition_flag(seat),
        ),
        segments=segments,
    )

def extract_offer(o: dict) -> FlightOffer:
    conditions = _safe(o, "conditions", {})
    refund = _safe(conditions, "refund_before_departure")
    change = _safe(conditions, "change_before_departure")

    return FlightOffer(
        id=o["id"],
        owner=extract_carrier(o["owner"]),
        price=Money(
            base_amount=float(o["base_amount"]),
            tax_amount=float(o["tax_amount"]),
            total_amount=float(o["total_amount"]),
            currency=o["total_currency"],
        ),
        supported_loyalty_programmes=o.get("supported_loyalty_programmes", []),
        conditions=OfferConditions(
            refund_before_departure_allowed=extract_condition_flag(refund),
            refund_before_departure_penalty=extract_condition_penalty(refund),
            change_before_departure_allowed=extract_condition_flag(change),
            change_before_departure_penalty=extract_condition_penalty(change),
        ),
        expires_at=o["expires_at"],
        slices=[extract_slice(s) for s in o["slices"]],
    )