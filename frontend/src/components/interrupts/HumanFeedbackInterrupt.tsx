import { ReviewShell } from "./ReviewShell";
import {UnknownInterruptFallback} from "./UnknownInterruptFallback.tsx";
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { HistoricalBanner } from "../HistoricalBanner";

export function HumanFeedbackInterrupt() {
    const { interrupt, isLive, isStreaming, submit } = useReviewInterrupt("human_feedback");
    if (!interrupt) return <UnknownInterruptFallback />;

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
