import { ReviewShell } from "./ReviewShell";
import {UnknownInterruptFallback} from "./UnknownInterruptFallback.tsx";
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { HistoricalBanner } from "../HistoricalBanner";
import { ProcessingState } from "../ProcessingState";

export function HumanFeedbackInterrupt() {
    const { interrupt, isLive, isStreaming, isProcessing, isUnexpected, submit } = useReviewInterrupt("human_feedback");
    
    if (isProcessing) return <ProcessingState />;
    if (isUnexpected || !interrupt) return <UnknownInterruptFallback />;

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell title="Review your research analysts" isStreaming={isStreaming}
                onApprove={() => submit("approve")} onRequestChanges={(fb) => submit(fb)}>
                <ul>{interrupt.analysts.map((persona, i) => <li key={i} style={{ whiteSpace: "pre-line" }}>{persona}</li>)}</ul>
            </ReviewShell>
        </>
    );
}
