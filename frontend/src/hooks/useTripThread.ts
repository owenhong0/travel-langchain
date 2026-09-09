import {useCallback, useEffect, useState} from "react";
import {useNavigate} from "react-router-dom";
import {ROUTE_FOR_INTERRUPT} from "../lib/interruptRoutes";
import type {InitialTripState, Interrupt} from "../types/orchestrator";
import {useStream} from "@langchain/langgraph-sdk/react";

export function useTripThread(existingThreadId?: string) {
    const navigate = useNavigate();
    const [currentThreadId, setCurrentThreadId] = useState<string | null>(existingThreadId || null);

    const thread = useStream({
        apiUrl: import.meta.env.VITE_LANGGRAPH_API_URL,
        assistantId: "orchestrator",
        threadId: existingThreadId,
        onThreadId: (id) => setCurrentThreadId(id),
    });

    // Use SDK's built-in state management:
    // thread.messages       -> array, updates live as tokens stream in
    // thread.isLoading      -> true while a run is active
    // thread.interrupt      -> the current interrupt payload, if any
    // thread.submit(input)  -> kicks off a new run
    // thread.error          -> any streaming errors

    const start = useCallback(
        async (initialState: InitialTripState) => {
            await thread.submit(initialState);
            // After submission, we need to track the thread ID for navigation
            // The SDK will create a thread internally if none exists
        },
        [thread]
    );

    const resume = useCallback(
        async (value: string | object) => {
            console.log('[useTripThread] Resuming with value:', value);
            await thread.submit(undefined, {command: {resume: value}});
        },
        [thread]
    );

    // Handle navigation based on interrupt state
    useEffect(() => {
        // Only navigate if we have a thread ID to work with
        if (!currentThreadId && !existingThreadId) {
            console.log('[useTripThread] No thread ID available, skipping navigation');
            return;
        }

        const threadIdToUse = currentThreadId || existingThreadId;
        console.log('[useTripThread] Navigation check:', {
            threadId: threadIdToUse,
            hasInterrupt: !!thread.interrupt,
            interruptType: thread.interrupt?.value?.type,
            isLoading: thread.isLoading,
            messageCount: thread.messages.length
        });

        if (thread.interrupt && thread.interrupt.value) {
            const interruptValue = thread.interrupt.value as Interrupt;
            const interruptType = interruptValue.type;
            const route = ROUTE_FOR_INTERRUPT[interruptType as keyof typeof ROUTE_FOR_INTERRUPT];
            console.log('[useTripThread] Interrupt detected:', { interruptType, route });
            if (route && threadIdToUse) {
                const targetPath = `/trip/${threadIdToUse}/${route}`;
                console.log('[useTripThread] Navigating to:', targetPath);
                navigate(targetPath);
            }
        } else if (!thread.isLoading && thread.messages.length > 0) {
            // Run is complete (not loading and has messages but no interrupt)
            if (threadIdToUse) {
                const targetPath = `/trip/${threadIdToUse}/summary`;
                console.log('[useTripThread] Run complete, navigating to:', targetPath);
                navigate(targetPath);
            }
        }
    }, [thread.interrupt, thread.isLoading, thread.messages.length, navigate, currentThreadId, existingThreadId]);

    // Extract error message safely
    const errorMessage = thread.error ?
        (typeof thread.error === 'string' ? thread.error :
            typeof thread.error === 'object' && thread.error && 'message' in thread.error ?
                String(thread.error.message) : 'An error occurred') : null;

    return {
    threadId: currentThreadId || existingThreadId || null,
    interrupt: thread.interrupt?.value as Interrupt | undefined,
    values: thread.values,   // <-- add this: gives interrupt components read access to graph state
    runComplete: !thread.isLoading && thread.messages.length > 0 && !thread.interrupt,
    isStreaming: thread.isLoading,
    error: errorMessage,
    messages: thread.messages,
    start,
    resume,
    setThreadId: setCurrentThreadId
};
}