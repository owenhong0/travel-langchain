export interface OrderedDestination {
  city: string;
  country: string;
}

export interface DatedLeg {
  city: string;
  depart_date: string;
  return_date: string;
  duration_days: number;
}

export interface TransportLeg {
  origin: string;
  destination: string;
  depart_date: string;
  modes_requested: string[];
}

export interface StayLeg {
  city: string;
  stay_type?: string;
}

export interface StayOption {
  type: string;
  brand_classification: string;
  name?: string;
  price_per_night_usd?: number;
  total_cost_usd?: number;
  price_note?: string;
  confidence: string;
}

// Mirrors each interrupt({...}) payload shape in trip_orchestrator.py
export type Interrupt =
  | { type: "human_feedback"; analysts: string[] }
  | { type: "order_review"; ordered_destinations: OrderedDestination[] }
  | { type: "start_date_request"; ordered_destinations: OrderedDestination[] }
  | { type: "date_review"; dated_itinerary: DatedLeg[] }
  | { type: "loyalty_programmes_request"; message: string }
  | { type: "home_context_request"; message: string; first_stop: string; last_stop: string }
  | { type: "transport_mode_review"; legs: TransportLeg[] }
  | { type: "stay_type_review"; message: string; stay_legs: unknown[] }
  | { type: "stay_review"; message: string; recommendation_reasoning?: string; options: StayOption[] };

// Subset of OrchestratorState needed to kick off a run (mirrors INITIAL_STATE)
// src/types/orchestrator.ts
export interface InitialTripState {
  [key: string]: unknown; // lets this satisfy the SDK's Record<string, unknown> input type
  
  // trip_info_graph fields
  trip_preferences: string;
  max_analysts: number;
  analysts: string[];
  sections: string[];
  human_analyst_feedback: string;
  destination_candidates: unknown[];
  finalized_destinations: unknown[];
  review_decision: string | null;
  ordered_destinations: OrderedDestination[];
  order_decision: string | null;
  order_feedback: string | null;
  trip_start_date: string | null;
  trip_end_date: string | null;
  dated_itinerary: DatedLeg[];
  date_decision: string | null;
  date_feedback: string | null;
  
  // bridge node
  loyalty_programmes: string[];
  
  // leg_transportation_graph fields
  home_city: string;
  home_country: string;
  return_city: string;
  return_country: string;
  legs: TransportLeg[];
  finalized_legs: unknown[];
  
  // lodging_graph fields
  stay_legs: unknown[];
  finalized_stays: unknown[];
}
