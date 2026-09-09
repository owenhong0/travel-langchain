// src/components/interrupts/StayTypeReviewInterrupt.tsx  (route: stays/types)
import { useTripThreadContext } from "../../hooks/useTripThreadContext";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import type {StayLeg} from "../../types/orchestrator.ts";


export function StayTypeReviewInterrupt() {
    const { interrupt, values, resume, isStreaming } = useTripThreadContext();
    if (interrupt?.type !== "stay_type_review") return <UnknownInterruptFallback />;
    const stayLegs = (values?.stay_legs ?? []) as StayLeg[];

    return (
        <ReviewShell title="Review stay types for each destination" isStreaming={isStreaming}
            onApprove={() => resume("approve")} onRequestChanges={(fb) => resume(fb)}>
            <p>{interrupt.message}</p>
            <ul>
                {stayLegs.map((leg: StayLeg, i: number) => (
                    <li key={i}>
                        <strong>{leg.city}</strong>: {leg.stay_type || 'Not specified'}
                    </li>
                ))}
            </ul>
        </ReviewShell>
    );
}
