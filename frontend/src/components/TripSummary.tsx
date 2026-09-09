// src/components/TripSummary.tsx  (route: summary)

import {useTripThreadContext} from "../hooks/useTripThreadContext";

export function TripSummary() {
    const { values } = useTripThreadContext();
    return (
        <section>
            <h1>Your trip plan</h1>
            <h2>Itinerary</h2>
            <ol>{(values?.dated_itinerary ?? []).map((s, i) => <li key={i}>{s.date} — {s.city}</li>)}</ol>
            <h2>Stays</h2>
            <ul>{(values?.finalized_stays ?? []).map((s, i) => <li key={i}>{s.city}: {s.hotel_name}</li>)}</ul>
            <h2>Transportation</h2>
            <ul>{(values?.finalized_legs ?? []).map((l, i) => <li key={i}>{l.origin} → {l.destination}: {l.mode}</li>)}</ul>
        </section>
    );
}