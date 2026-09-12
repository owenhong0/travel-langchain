// src/components/interrupts/OrderReviewInterrupt.tsx  (route: destinations)

import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { HistoricalBanner } from "../HistoricalBanner";
import { ProcessingState } from "../ProcessingState";
import type {OrderedDestination} from "../../types/orchestrator.ts";
import {DestinationCard} from "./ReviewDestinationsInterrupt.tsx";

export function OrderReviewInterrupt() {
    const { interrupt, values, isLive, isStreaming, isProcessing, isUnexpected, submit } = useReviewInterrupt("order_review");
    
    if (isProcessing) return <ProcessingState />;
    if (isUnexpected || !interrupt) return <UnknownInterruptFallback />;
    
    const destinations = (values?.ordered_destinations ?? values?.finalized_destinations ?? []) as OrderedDestination[];

    const handleApprove = () => submit("approve");
    const handleRequestChanges = (feedback: string) => submit(feedback);

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell
                title="Review destination candidates"
                isStreaming={isStreaming}
                isProcessing={isProcessing}
                onApprove={handleApprove}
                onRequestChanges={handleRequestChanges}
            >
                <div className="destinations-review">
                    <p className="review-message">{interrupt.message}</p>
                    <ul className="destinations-list">
                        {interrupt.ordered_destinations.map((destination, index) => (
                            <DestinationCard
                                key={`${destination.city}-${destination.country}-${index}`}
                                candidate={destination}
                                index={index}
                            />
                        ))}
                    </ul>
                </div>
            </ReviewShell>
        </>
    );
}
