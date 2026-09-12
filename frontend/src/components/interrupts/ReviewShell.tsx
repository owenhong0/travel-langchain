// src/components/interrupts/ReviewShell.tsx
import { type ReactNode, useState } from "react";
import { ProcessingState } from "../ProcessingState";

type ReviewShellProps = {
    title: string;
    children: ReactNode;
    onApprove: () => void;
    onRequestChanges: (feedback: string) => void;
    isStreaming: boolean;
    isProcessing?: boolean;
};

export function ReviewShell({ title, children, onApprove, onRequestChanges, isStreaming, isProcessing }: ReviewShellProps) {
    const [feedback, setFeedback] = useState("");
    
    // Show processing state when streaming or processing
    if (isStreaming || isProcessing) {
        return (
            <section>
                <h1>{title}</h1>
                <ProcessingState />
            </section>
        );
    }
    
    return (
        <section>
            <h1>{title}</h1>
            {children}
            <button onClick={onApprove} disabled={isStreaming}>Looks good, continue</button>
            <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Or describe what you'd like changed..."
                rows={3}
                disabled={isStreaming}
            />
            <button onClick={() => feedback.trim() && onRequestChanges(feedback)} disabled={isStreaming || !feedback.trim()}>
                Request changes
            </button>
        </section>
    );
}
