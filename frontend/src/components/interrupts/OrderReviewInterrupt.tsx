// src/components/interrupts/OrderReviewInterrupt.tsx  (route: destinations)

import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { HistoricalBanner } from "../HistoricalBanner";

export function OrderReviewInterrupt() {
    const { interrupt, values, isLive, isStreaming, submit } = useReviewInterrupt("order_review");
    if (!interrupt) return <UnknownInterruptFallback />;
    const destinations = values?.ordered_destinations ?? values?.finalized_destinations ?? [];

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell title="Review destination order" isStreaming={isStreaming}
                onApprove={() => submit("approve")} onRequestChanges={(fb) => submit(fb)}>
                <ol>{destinations.map((d, i) => <li key={i}>{typeof d === "string" ? d : d.name}</li>)}</ol>
            </ReviewShell>
        </>
    );
}
