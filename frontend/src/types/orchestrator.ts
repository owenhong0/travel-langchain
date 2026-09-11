// Mirrors OrchestratorState + every interrupt() payload across
// trip_info_graph.py, leg_transportation_graph.py, lodging_graph.py, trip_orchestrator.py

// ---------- trip_info_graph.py ----------

// DestinationCandidate (trip_info_graph.py) — used in review_destinations
export interface DestinationCandidate {
  city: string;
  country: string;
  rationale: string;
  recommended_season: string;
  recommended_duration_days_min: number;
  recommended_duration_days_max: number;
  date: string;
  requires_flight_or_ferry: boolean;
}

// OrderedStop (trip_info_graph.py) — used in both order_review and start_date_request
export interface OrderedDestination {
  city: string;
  country: string;
  recommended_duration_days: string; // e.g. "2-4" — a range string, not a number
  purpose: string;
  is_international_gateway: boolean;
  requires_flight_or_ferry: boolean;
}

// DatedStop (trip_info_graph.py) — used in date_review
export interface DatedLeg {
  city: string;
  country: string;
  depart_date: string;
  return_date: string;
  duration_days: number;
  requires_flight_or_ferry: boolean;
}

// ---------- leg_transportation_graph.py ----------

// Leg TypedDict + modes_requested/distance_miles annotations — used in transport_mode_review
export interface TransportLeg {
  origin: string;
  destination: string;
  origin_country: string;
  destination_country: string;
  depart_date: string;
  requires_flight_or_ferry: boolean;
  modes_requested: string[];
  leg_type: "arrival" | "internal" | "departure";
  distance_miles: number | null;
}

// TransportSegment (leg_transportation_graph.py) — populated when mode === "combined"
export interface TransportSegment {
  mode: "flight" | "train" | "bus" | "car" | "ferry";
  provider: string | null;
  duration: string | null;
}

// TransportOption.model_dump() + fields added during reconcile/search — used in leg_transport_review
export interface TransportOption {
  mode: "flight" | "train" | "bus" | "car" | "ferry" | "combined";
  provider: string | null;
  price_estimate: string | null;
  duration: string | null;
  booking_url: string | null;
  segments: TransportSegment[] | null;
  source?: string; // e.g. "rome2rio" | "operator_site"
  round?: number;
  confidence?: "corroborated" | "unverified";
  unresolved?: boolean; // true = placeholder "no route found" entry, never finalize this
  transfer_note?: string; // present when a flight uses a nearby-airport override
}

// ---------- lodging_graph.py ----------

// StayLeg TypedDict — used in stay_type_review
export interface StayLeg {
  city: string;
  country: string;
  check_in: string;
  check_out: string;
  duration_days: number;
  stay_types_requested: string[]; // NOTE: array, not singular "stay_type" — see bug note above
  loyalty_programmes: string[];
}

// StayOption.model_dump() + fields added during pricing/reconcile — used in stay_review
export interface StayOption {
  type: "hotel" | "hostel" | "homestay" | "apartment" | "resort";
  name: string;
  area: string | null;
  price_estimate: string | null;
  price_amount: number | null;
  price_currency: string | null;
  price_amount_min: number | null;
  price_amount_max: number | null;
  price_type: "per_night" | "total" | "per_person_per_night" | "unknown";
  rating: string | null;
  booking_url: string | null;
  brand_classification: "international_chain" | "local_chain" | "boutique" | "independent_local" | "vacation_rental";
  // added by _apply_pricing / reconcile_stay_options — not on the base Pydantic model
  confidence: "date_verified" | "corroborated" | "unverified";
  source?: string;
  round?: number;
  search_query?: string;
  matched_area?: string | null;
  price_usd?: number | null;
  price_per_night_usd?: number | null;
  total_cost_usd?: number | null;
  price_note?: string;
  price_by_source?: Record<string, { price_estimate: string; price_per_night_usd: number | null; total_cost_usd: number | null }>;
  points_value?: { percent_bookable_with_points?: string; point_value_cents?: string; note?: string };
  date_specific?: boolean;
}

// ---------- Interrupt union — every interrupt({...}) call across all four files ----------

export type Interrupt =
  | { type: "human_feedback"; message: string; analysts: string[] }
  | { type: "review_destinations"; message: string; destination_candidates: DestinationCandidate[] }
  | { type: "order_review"; message: string; ordered_destinations: OrderedDestination[] }
  | { type: "start_date_request"; message: string; ordered_destinations: OrderedDestination[] }
  | { type: "date_review"; message: string; dated_itinerary: DatedLeg[] }
  | { type: "loyalty_programmes_request"; message: string }
  | { type: "home_context_request"; message: string; first_stop: string; last_stop: string }
  | { type: "transport_mode_review"; message: string; legs: TransportLeg[] }
  | {
      type: "leg_transport_review";
      message: string;
      recommendation_reasoning: string | null;
      options: TransportOption[];
    }
  | { type: "stay_type_review"; message: string; stay_legs: StayLeg[] }
  | {
      type: "stay_review";
      message: string;
      recommendation_reasoning: string | null;
      options: StayOption[];
    };

// ---------- InitialTripState (trip_orchestrator.py INITIAL_STATE) ----------

export interface InitialTripState {
  [key: string]: unknown;
  trip_preferences: string;
  max_analysts: number;
  analysts: string[];
  sections: string[];
  human_analyst_feedback: string;
  destination_candidates: DestinationCandidate[];
  finalized_destinations: unknown[]; // subset of DestinationCandidate — backend doesn't fix a shape here
  review_decision: string | null;
  ordered_destinations: OrderedDestination[];
  order_decision: string | null;
  order_feedback: string | null;
  trip_start_date: string | null;
  trip_end_date: string | null;
  dated_itinerary: DatedLeg[];
  date_decision: string | null;
  date_feedback: string | null;

  loyalty_programmes: string[];

  home_city: string;
  home_country: string;
  return_city: string;
  return_country: string;
  legs: TransportLeg[];
  finalized_legs: unknown[]; // { ...TransportLeg, selected: TransportOption | null }

  stay_legs: StayLeg[];
  finalized_stays: unknown[]; // { ...StayLeg, selected: StayOption | null }
}