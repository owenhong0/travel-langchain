// src/components/interrupts/TransportModeReviewInterrupt.tsx  (route: transport)
import { useTripThreadContext } from "../../hooks/useTripThreadContext";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";

export function TransportModeReviewInterrupt() {
    const { interrupt, values, resume, isStreaming } = useTripThreadContext();
    if (interrupt?.type !== "transport_mode_review") return <UnknownInterruptFallback />;
    const legs = values?.legs ?? [];

    return (
        <ReviewShell title="Review transportation for each leg" isStreaming={isStreaming}
            onApprove={() => resume("approve")} onRequestChanges={(fb) => resume(fb)}>
            <ol>{legs.map((leg, i) => <li key={i}>{leg.origin} → {leg.destination}: <strong>{leg.mode}</strong></li>)}</ol>
        </ReviewShell>
    );
}