// src/components/interrupts/StartDateRequestInterrupt.tsx  (route: dates/range)
import { useState } from "react";
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { HistoricalBanner } from "../HistoricalBanner";

export function StartDateRequestInterrupt() {
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");
    const { interrupt, isLive, isStreaming, submit } = useReviewInterrupt("start_date_request");
    
    if (!interrupt) return <UnknownInterruptFallback />;

    const handleSubmit = () => {
        if (!startDate || !endDate) return;
        // Backend expects a simple string format: "YYYY-MM-DD, YYYY-MM-DD"
        submit(`${startDate}, ${endDate}`);
    };

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <section>
                <h1>When are you traveling?</h1>
                <label>Start date <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} disabled={isStreaming} /></label>
                <label>End date <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} disabled={isStreaming} /></label>
                <button onClick={handleSubmit} disabled={isStreaming || !startDate || !endDate}>Continue</button>
            </section>
        </>
    );
}
