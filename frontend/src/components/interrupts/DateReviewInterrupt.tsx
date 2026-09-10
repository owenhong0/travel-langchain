// src/components/interrupts/DateReviewInterrupt.tsx  (route: dates/review)
import { useTripThreadContext } from "../../hooks/useTripThreadContext";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";

export function DateReviewInterrupt() {
    const { interrupt, values, resume, isStreaming } = useTripThreadContext();
    if (interrupt?.type !== "date_review") return <UnknownInterruptFallback />;
    const itinerary = values?.dated_itinerary ?? [];

    return (
        <ReviewShell title="Review your dated itinerary" isStreaming={isStreaming}
            onApprove={() => resume("approve")} onRequestChanges={(fb) => resume(fb)}>
            <ol>{itinerary.map((stop, i) => <li key={i}><strong>{stop.date}</strong> — {stop.city}</li>)}</ol>
        </ReviewShell>
    );
}