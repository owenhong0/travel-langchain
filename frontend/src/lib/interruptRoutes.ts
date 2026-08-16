import type { Interrupt } from "../types/orchestrator";

export const ROUTE_FOR_INTERRUPT: Record<Interrupt["type"], string> = {
  human_feedback: "analysts",
  order_review: "destinations",
  start_date_request: "dates/range",
  date_review: "dates/review",
  loyalty_programmes_request: "loyalty",
  home_context_request: "home-context",
  transport_mode_review: "transport",
  stay_review: "stays",
};