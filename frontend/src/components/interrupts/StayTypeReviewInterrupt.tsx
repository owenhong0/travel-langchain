// src/components/interrupts/StayTypeReviewInterrupt.tsx  (route: stays/types)
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { HistoricalBanner } from "../HistoricalBanner";
import type {StayLeg} from "../../types/orchestrator.ts";


export function StayTypeReviewInterrupt() {
    const { interrupt, values, isLive, isStreaming, submit } = useReviewInterrupt("stay_type_review");
    if (!interrupt) return <UnknownInterruptFallback />;
    const stayLegs = (values?.stay_legs ?? []) as StayLeg[];

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell title="Review stay types for each destination" isStreaming={isStreaming}
                onApprove={() => submit("approve")} onRequestChanges={(fb) => submit(fb)}>
                <p>{interrupt.message}</p>
                <ul>
                    {stayLegs.map((leg: StayLeg, i: number) => (
                        <li key={i}>
                            <strong>{leg.city}</strong>: {leg.stay_type || 'Not specified'}
                        </li>
                    ))}
                </ul>
            </ReviewShell>
        </>
    );
}
