// src/fixtures/build-fixtures.ts
import fs from "fs";
import type {InitialTripState, Interrupt, TripThreadState} from "../src/types/orchestrator";


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
    interrupt: Interrupt;
}

const specs: FixtureSpec[] = [
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

function build(spec: FixtureSpec): TripThreadState {
    const values: Record<string, unknown> = {...BASELINE};
    for (const field of spec.resolved) {
        if (!(field in completed.values)) {
            throw new Error(`[build-fixtures] "${field}" not found in completed_trip.json`);
        }
        values[field] = completed.values[field];
    }

    const metadata = {...completed.metadata};
    delete metadata.LANGGRAPH_API_URL; // stale dev-tunnel URLs
    delete metadata.langgraph_api_url;

    const pending = {id: `${spec.name}-interrupt`, value: spec.interrupt};
    return {
        ...completed,
        metadata,
        values: values as InitialTripState,
        next: [spec.node],
        tasks: [{id: `${spec.name}-task`, name: spec.node, interrupts: [pending]}],
        interrupts: [pending],
    } as TripThreadState;
}

for (const spec of specs) {
    fs.writeFileSync(`src/fixtures/${spec.name}.json`, JSON.stringify(build(spec), null, 2));
    console.log(`wrote src/fixtures/${spec.name}.json`);
}