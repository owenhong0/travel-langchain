// src/fixtures/build-fixtures.ts
import fs from "fs";
import type {
    InitialTripState,
    Interrupt,
    StayOption,
    TransportOption,
    TripThreadState
} from "../src/types/orchestrator";


const completed = JSON.parse(
    fs.readFileSync("src/fixtures/completed_trip.json", "utf8"),
) as TripThreadState & { metadata?: Record<string, unknown> };

// Mirrors EMPTY_STATE in StartTrip.tsx: the frontend always sends every key.
const BASELINE: InitialTripState = {
    trip_preferences: "",
    max_analysts: 5,
    analysts: [],
    sections: [],
    human_analyst_feedback: "",
    destination_candidates: [],
    finalized_destinations: [],
    review_decision: null,
    ordered_destinations: [],
    order_decision: null,
    order_feedback: null,
    trip_start_date: null,
    trip_end_date: null,
    dated_itinerary: [],
    date_decision: null,
    date_feedback: null,
    loyalty_programmes: [],
    home_city: "",
    home_country: "",
    return_city: "",
    return_country: "",
    legs: [],
    finalized_legs: [],
    stay_legs: [],
    finalized_stays: [],
};

interface FixtureSpec {
    name: string;
    node: string; // orchestrator-level node the interrupt bubbles up through
    resolved: string[]; // was: (keyof InitialTripState)[]
    overrides?: Record<string, unknown>;
    interrupt: Interrupt;
}

const specs: FixtureSpec[] = [
    {
        name: "human_feedback",
        node: "trip_info",
        resolved: ["trip_preferences", "analysts"],
        interrupt: {
            type: "human_feedback",
            message: "Review the proposed analyst panel. Reply 'approve' to proceed, or give feedback to revise the panel.",
            analysts: completed.values.analysts.map(
                (a) => `Focus: ${a.focus_area}\nName: ${a.persona_name}\nDescription: ${a.description}\n`,
            ),
        },
    },
    {
        name: "review_destinations",
        node: "trip_info",
        resolved: ["trip_preferences", "analysts", "sections", "human_analyst_feedback", "destination_candidates"],
        interrupt: {
            type: "review_destinations",
            message: "Reply 'approve' (or leave blank) to take all of them, list indices or city/country names (comma-separated) to pick specific ones, or type anything else to revise your preferences.",
            destination_candidates: completed.values.destination_candidates,
        },
    },
    {
        name: "order_review",
        node: "trip_info",
        resolved: [
            "trip_preferences", "analysts", "sections", "human_analyst_feedback",
            "destination_candidates", "finalized_destinations", "review_decision",
            "ordered_destinations",
        ],
        interrupt: {
            type: "order_review",
            message:
                "Reply 'approve' to finalize, 'drop: <city, city>' to remove optional legs " +
                "(e.g. 'drop: Busan, Jeju'), or describe other changes.",
            ordered_destinations: completed.values.ordered_destinations,
        },
    },
];

const tripInfoThroughOrder = ["trip_preferences", "analysts", "sections", "human_analyst_feedback",
  "destination_candidates", "finalized_destinations", "review_decision", "ordered_destinations"];
const atStartDate = [...tripInfoThroughOrder, "order_decision"];
const atDateReview = [...atStartDate, "trip_start_date", "trip_end_date", "dated_itinerary"];
const tripInfoDone = [...atDateReview, "date_decision"];
const atTransport = [...tripInfoDone, "home_city", "home_country", "return_city", "return_country", "legs"];
const atLodging = [...atTransport, "finalized_legs", "stay_legs"];

const stops = completed.values.dated_itinerary;
const PLACEHOLDER_REASONING =
  "Placeholder: the captured run only kept the selected option, so there is no real recommendation text.";

specs.push(
  { name: "start_date_request", node: "trip_info", resolved: atStartDate,
    interrupt: { type: "start_date_request",
      message: "Earliest departure date and latest return/must-leave date, both required (YYYY-MM-DD, YYYY-MM-DD):",
      ordered_destinations: completed.values.ordered_destinations } },
  { name: "date_review", node: "trip_info", resolved: atDateReview,
    interrupt: { type: "date_review", message: "Reply 'approve' or describe date changes.",
      dated_itinerary: completed.values.dated_itinerary } },
  { name: "loyalty_programmes_request", node: "collect_loyalty_programmes", resolved: tripInfoDone,
    interrupt: { type: "loyalty_programmes_request",
      message: "Any hotel loyalty programmes you hold? Comma-separated (e.g. 'Marriott Bonvoy, Hyatt'), or 'skip' for none." } },
  { name: "home_context_request", node: "transportation", resolved: tripInfoDone,
    interrupt: { type: "home_context_request",
      message: "Where are you traveling from? Add '-> city' if returning somewhere different (open-jaw), otherwise it defaults to the same city.",
      first_stop: stops[0].city, last_stop: stops[stops.length - 1].city } },
  { name: "transport_mode_review", node: "transportation", resolved: atTransport,
    interrupt: { type: "transport_mode_review",
      message: "Confirm modes per leg (e.g. '0: flight,train | 1: car'), or 'approve' for defaults.",
      legs: completed.values.legs } },
);

const legs = completed.values.finalized_legs as { origin: string; destination: string; selected: TransportOption | null }[];
legs.forEach((leg, i) => specs.push({
  name: `leg_transport_review_${i}`, node: "transportation", resolved: atTransport,
  overrides: { finalized_legs: legs.slice(0, i) },
  interrupt: { type: "leg_transport_review",
    message: `${leg.origin} → ${leg.destination}: reply 'approve' to take the recommended option, an index to pick another, or feedback to re-search.`,
    recommendation_reasoning: PLACEHOLDER_REASONING,
    options: leg.selected ? [leg.selected] : [] },
}));

specs.push({ name: "stay_type_review", node: "lodging", resolved: atLodging,
  interrupt: { type: "stay_type_review",
    message: "Confirm stay type per stop (e.g. '0: hostel,homestay | 2: hotel'), or 'approve' for hotels everywhere.",
    stay_legs: completed.values.stay_legs } });

const stays = completed.values.finalized_stays as { city: string; selected: StayOption | null }[];
stays.forEach((stay, i) => specs.push({
  name: `stay_review_${i}`, node: "lodging", resolved: atLodging,
  overrides: { finalized_stays: stays.slice(0, i) },
  interrupt: { type: "stay_review",
    message: `${stay.city}: reply 'approve' to take the recommendation, an index to pick another, or feedback to re-search.`,
    recommendation_reasoning: PLACEHOLDER_REASONING,
    options: stay.selected ? [stay.selected] : [] },
}));

const checkpoint = (n: number) => ({
    checkpoint_id: `1f1b2c00-0000-6000-8000-${String(n).padStart(12, "0")}`,
    thread_id: completed.checkpoint.thread_id,
    checkpoint_ns: "",
});

function build(spec: FixtureSpec,  index: number): TripThreadState {
    const values: Record<string, unknown> = {...BASELINE};
    for (const field of spec.resolved) {
        if (!(field in completed.values)) {
            throw new Error(`[build-fixtures] "${field}" not found in completed_trip.json`);
        }
        values[field] = completed.values[field];
    }

    Object.assign(values, spec.overrides);

    const metadata = {...completed.metadata};
    delete metadata.LANGGRAPH_API_URL; // stale dev-tunnel URLs
    delete metadata.langgraph_api_url;

    const pending = {id: `${spec.name}-interrupt`, value: spec.interrupt};
    return {
        ...completed,
        checkpoint: checkpoint(index + 1),
        parent_checkpoint: index === 0 ? null : checkpoint(index),
        metadata,
        values: values as InitialTripState,
        next: [spec.node],
        tasks: [{id: `${spec.name}-task`, name: spec.node, interrupts: [pending]}],
        interrupts: [pending],
    } as TripThreadState;
}

specs.forEach((spec, index) => {
  fs.writeFileSync(`src/fixtures/${spec.name}.json`, JSON.stringify(build(spec, index), null, 2));
  console.log(`wrote src/fixtures/${spec.name}.json`);
});