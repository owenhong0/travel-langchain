import type { Interrupt } from "../types/orchestrator";

export const ROUTE_FOR_INTERRUPT: Record<Interrupt["type"], string> = {
  human_feedback: "analysts",
  review_destinations: "destinations/review",
  order_review: "destinations/order",
  start_date_request: "dates/range",
  date_review: "dates/review",
  loyalty_programmes_request: "loyalty",
  home_context_request: "home-context",
  transport_mode_review: "transport",
  stay_type_review: "stays/types",
  stay_review: "stays",
};
