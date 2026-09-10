// src/components/StartTrip.tsx
import {useState, type FormEvent} from "react";
import {useTripThread} from "../hooks/useTripThread";
import type {InitialTripState} from "../types/orchestrator";
import {DebugPanel} from "./DebugPanel";

const EMPTY_STATE: InitialTripState = {
  // trip_info_graph fields
  trip_preferences: "",
  max_analysts: 5, // Match backend default
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
  
  // bridge node
  loyalty_programmes: [],
  
  // leg_transportation_graph fields
  home_city: "",
  home_country: "",
  return_city: "",
  return_country: "",
  legs: [],
  finalized_legs: [],
  
  // lodging_graph fields
  stay_legs: [],
  finalized_stays: [],
};

export function StartTrip() {
    const {start, isStreaming, error, threadId, messages, interrupt} = useTripThread();
    const [preferences, setPreferences] = useState("");

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        if (!preferences.trim() || isStreaming) return;
        start({...EMPTY_STATE, trip_preferences: preferences});
    };

    return (
        <>
            <DebugPanel 
                isLoading={isStreaming}
                messagesLength={messages?.length || 0}
                interruptType={interrupt?.type}
                threadId={threadId}
                error={error}
            />
            <form onSubmit={handleSubmit}>
                <h1>Plan a trip</h1>
                <textarea
                    value={preferences}
                    onChange={(e) => setPreferences(e.target.value)}
                    placeholder="Describe what you're looking for — interests, rough dates, constraints..."
                    rows={5}
                    disabled={isStreaming}
                />
                <button type="submit" disabled={isStreaming || !preferences.trim()}>
                    {isStreaming ? "Starting..." : "Start planning"}
                </button>
                {error && <p role="alert">{error}</p>}
            </form>
        </>
    );
}
