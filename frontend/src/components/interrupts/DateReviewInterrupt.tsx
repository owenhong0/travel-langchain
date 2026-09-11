// src/components/interrupts/DateReviewInterrupt.tsx  (route: dates/review)
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { HistoricalBanner } from "../HistoricalBanner";
import type {DatedLeg} from "../../types/orchestrator.ts";

export function DateReviewInterrupt() {
    const { interrupt, values, isLive, isStreaming, submit } = useReviewInterrupt("date_review");
    if (!interrupt) return <UnknownInterruptFallback />;
    const itinerary: DatedLeg[] = values?.dated_itinerary ?? [];

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell title="Review your dated itinerary" isStreaming={isStreaming}
                onApprove={() => submit("approve")} onRequestChanges={(fb) => submit(fb)}>
                <ol>{itinerary.map((stop, i) => <li key={i}><strong>{stop.date}</strong> — {stop.city}</li>)}</ol>
            </ReviewShell>
        </>
    );
}
