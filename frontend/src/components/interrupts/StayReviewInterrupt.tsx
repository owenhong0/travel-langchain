// src/components/interrupts/StayReviewInterrupt.tsx  (route: stays)
import { useTripThreadContext } from "../../hooks/useTripThreadContext";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";

export function StayReviewInterrupt() {
    const { interrupt, values, resume, isStreaming } = useTripThreadContext();
    if (interrupt?.type !== "stay_review") return <UnknownInterruptFallback />;
    const stays = values?.stay_legs ?? [];

    return (
        <ReviewShell title="Review your lodging" isStreaming={isStreaming}
            onApprove={() => resume("approve")} onRequestChanges={(fb) => resume(fb)}>
            <ul>{stays.map((s, i) => <li key={i}>{s.city}: <strong>{s.hotel_name}</strong></li>)}</ul>
        </ReviewShell>
    );
}