// src/components/interrupts/UnknownInterruptFallback.tsx


import {useTripThreadContext } from "../../hooks/useTripThreadContext";

export function UnknownInterruptFallback() {
    const { interrupt, threadId } = useTripThreadContext();
    return (
        <div role="alert">
            <h1>Unexpected interrupt</h1>
            <p>Frontend doesn't have a component for: <code>{interrupt?.type ?? "unknown"}</code></p>
            <p>Thread: {threadId}</p>
        </div>
    );
}