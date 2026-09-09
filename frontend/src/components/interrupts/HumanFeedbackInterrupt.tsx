import { ReviewShell } from "./ReviewShell";
import {UnknownInterruptFallback} from "./UnknownInterruptFallback.tsx";
import {useTripThreadContext} from "../../hooks/useTripThreadContext.ts";
import {useInterruptOfType} from "../../hooks/useInterruptOfType.ts";

export function HumanFeedbackInterrupt() {
    const data = useInterruptOfType("human_feedback");
    const { resume, isStreaming } = useTripThreadContext();
    if (!data) return <UnknownInterruptFallback />;

    return (
        <ReviewShell title="Review your research analysts" isStreaming={isStreaming}
            onApprove={() => resume("approve")} onRequestChanges={(fb) => resume(fb)}>
            <ul>{data.analysts.map((persona, i) => <li key={i} style={{ whiteSpace: "pre-line" }}>{persona}</li>)}</ul>
        </ReviewShell>
    );
}