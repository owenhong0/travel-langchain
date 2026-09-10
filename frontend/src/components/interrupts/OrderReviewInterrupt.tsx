// src/components/interrupts/OrderReviewInterrupt.tsx  (route: destinations)

import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import {useTripThreadContext } from "../../hooks/useTripThreadContext";

export function OrderReviewInterrupt() {
    const { interrupt, values, resume, isStreaming } = useTripThreadContext();
    if (interrupt?.type !== "order_review") return <UnknownInterruptFallback />;
    const destinations = values?.ordered_destinations ?? values?.finalized_destinations ?? [];

    return (
        <ReviewShell title="Review destination order" isStreaming={isStreaming}
            onApprove={() => resume("approve")} onRequestChanges={(fb) => resume(fb)}>
            <ol>{destinations.map((d, i) => <li key={i}>{typeof d === "string" ? d : d.name}</li>)}</ol>
        </ReviewShell>
    );
}