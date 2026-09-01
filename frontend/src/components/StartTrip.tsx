// src/components/StartTrip.tsx
import { useState, type FormEvent } from "react";
import { useTripThread } from "../hooks/useTripThread";
import type { InitialTripState } from "../types/orchestrator";

const EMPTY_STATE: InitialTripState = {
  trip_preferences: "",
  max_analysts: 3,
  analysts: [],
  sections: [],
  human_analyst_feedback: "",
  destination_candidates: [],
  finalized_destinations: [],
  ordered_destinations: [],
  dated_itinerary: [],
  loyalty_programmes: [],
  legs: [],
  finalized_legs: [],
  stay_legs: [],
  finalized_stays: [],
};

export function StartTrip() {
  const { start, isStreaming, error } = useTripThread();
  const [preferences, setPreferences] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!preferences.trim() || isStreaming) return;
    start({ ...EMPTY_STATE, trip_preferences: preferences });
  };

  return (
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
  );
}