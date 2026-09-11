// src/components/interrupts/LoyaltyProgrammesRequestInterrupt.tsx  (route: loyalty)
import { useState } from "react";
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { HistoricalBanner } from "../HistoricalBanner";

export function LoyaltyProgrammesRequestInterrupt() {
    const [programme, setProgramme] = useState("");
    const [entries, setEntries] = useState<string[]>([]);
    const { interrupt, isLive, isStreaming, submit } = useReviewInterrupt("loyalty_programmes_request");
    
    if (!interrupt) return <UnknownInterruptFallback />;

    const addEntry = () => {
        if (!programme.trim()) return;
        setEntries((prev) => [...prev, programme.trim()]);
        setProgramme("");
    };
    // TODO: confirm loyalty_programmes expects a plain string[] vs richer objects
    const handleSubmit = () => submit(entries);

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <section>
                <h1>Any loyalty programmes to use?</h1>
                <p>E.g. hotel points, airline miles, credit card travel points.</p>
                <input value={programme} onChange={(e) => setProgramme(e.target.value)} placeholder="Chase Sapphire Reserve" disabled={isStreaming} />
                <button onClick={addEntry} disabled={isStreaming || !programme.trim()}>Add</button>
                <ul>{entries.map((e, i) => <li key={i}>{e}</li>)}</ul>
                <button onClick={handleSubmit} disabled={isStreaming}>{entries.length ? "Continue" : "Skip"}</button>
            </section>
        </>
    );
}
