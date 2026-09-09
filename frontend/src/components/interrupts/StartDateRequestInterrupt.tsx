// src/components/interrupts/StartDateRequestInterrupt.tsx  (route: dates/range)
import { useState } from "react";
import { useTripThreadContext } from "../../hooks/useTripThreadContext";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";

export function StartDateRequestInterrupt() {
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");
    const { interrupt, resume, isStreaming } = useTripThreadContext();
    
    if (interrupt?.type !== "start_date_request") return <UnknownInterruptFallback />;

    const handleSubmit = () => {
        if (!startDate || !endDate) return;
        // Backend expects a simple string format: "YYYY-MM-DD, YYYY-MM-DD"
        resume(`${startDate}, ${endDate}`);
    };

    return (
        <section>
            <h1>When are you traveling?</h1>
            <label>Start date <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} disabled={isStreaming} /></label>
            <label>End date <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} disabled={isStreaming} /></label>
            <button onClick={handleSubmit} disabled={isStreaming || !startDate || !endDate}>Continue</button>
        </section>
    );
}