import {useCallback, useEffect, useState, useRef} from "react";
import {useNavigate} from "react-router-dom";
import {ROUTE_FOR_INTERRUPT} from "../lib/interruptRoutes";
import type {InitialTripState, Interrupt} from "../types/orchestrator";
import {useStream} from "@langchain/langgraph-sdk/react";

export function useTripThread(existingThreadId?: string) {
    const navigate = useNavigate();
    const [currentThreadId, setCurrentThreadId] = useState<string | null>(existingThreadId || null);
    const lastInterruptIdRef = useRef<string | undefined>(null);

    const thread = useStream({
        apiUrl: import.meta.env.VITE_LANGGRAPH_API_URL,
        assistantId: "orchestrator",
        threadId: existingThreadId,
        onThreadId: (id) => setCurrentThreadId(id),
        fetchStateHistory: true,
    });

    // Use SDK's built-in state management:
    // thread.messages       -> array, updates live as tokens stream in
    // thread.isLoading      -> true while a run is active
    // thread.interrupt      -> the current interrupt payload, if any
    // thread.submit(input)  -> kicks off a new run
    // thread.history        -> ThreadState[], full checkpoint list for this thread
    // thread.error          -> any streaming errors

    const start = useCallback(
        async (initialState: InitialTripState) => {
            await thread.submit(initialState);
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

    const forkFrom = useCallback(
        async (checkpointId: string, value: string | object) => {
            console.log('[useTripThread] Forking from checkpoint:', checkpointId, 'with value:', value);
            await thread.submit(undefined, {
                command: {resume: value},
                checkpoint: {checkpoint_id: checkpointId, checkpoint_ns: "", checkpoint_map: undefined},
            });
        },
        [thread]
    );

    // Handle navigation based on interrupt state - only navigate for NEW interrupts
    useEffect(() => {
        if (!currentThreadId && !existingThreadId) {
            console.log('[useTripThread] No thread ID available, skipping navigation');
            return;
        }

        const threadIdToUse = currentThreadId || existingThreadId;
        const currentInterruptId = thread.interrupt?.id;

        console.log('[useTripThread] Navigation check:', {
            threadId: threadIdToUse,
            hasInterrupt: !!thread.interrupt,
            interruptId: currentInterruptId,
            lastInterruptId: lastInterruptIdRef.current,
            interruptType: thread.interrupt?.value ? (thread.interrupt.value as Interrupt).type : undefined,
            isLoading: thread.isLoading,
            messageCount: thread.messages.length
        });

        // Only navigate if this is a NEW interrupt (different ID from last seen)
        if (thread.interrupt && thread.interrupt.value && currentInterruptId !== lastInterruptIdRef.current) {
            const interruptValue = thread.interrupt.value as Interrupt;
            const interruptType = interruptValue.type;
            const route = ROUTE_FOR_INTERRUPT[interruptType as keyof typeof ROUTE_FOR_INTERRUPT];

            console.log('[useTripThread] NEW interrupt detected:', {
                interruptId: currentInterruptId,
                interruptType,
                route,
                previousId: lastInterruptIdRef.current
            });

            if (route && threadIdToUse) {
                const targetPath = `/trip/${threadIdToUse}/${route}`;
                console.log('[useTripThread] Navigating to NEW interrupt:', targetPath);
                navigate(targetPath);
                lastInterruptIdRef.current = currentInterruptId;
            }
        } else if (!thread.isLoading && thread.messages.length > 0 && !thread.interrupt) {
            // Only navigate to summary if we're not viewing a historical interrupt
            if (threadIdToUse) {
                const targetPath = `/trip/${threadIdToUse}/summary`;
                console.log('[useTripThread] Run complete, navigating to:', targetPath);
                navigate(targetPath);
                lastInterruptIdRef.current = null; // Reset for next run
            }
        }
    }, [thread.interrupt?.id, thread.interrupt?.value, thread.isLoading, thread.messages.length, navigate, currentThreadId, existingThreadId]);

    const errorMessage = thread.error ?
        (typeof thread.error === 'string' ? thread.error :
            typeof thread.error === 'object' && thread.error && 'message' in thread.error ?
                String(thread.error.message) : 'An error occurred') : null;

    return {
        threadId: currentThreadId || existingThreadId || null,
        interrupt: thread.interrupt?.value as Interrupt | undefined,
        values: thread.values,
        history: thread.history,
        runComplete: !thread.isLoading && thread.messages.length > 0 && !thread.interrupt,
        isStreaming: thread.isLoading,
        error: errorMessage,
        messages: thread.messages,
        start,
        resume,
        forkFrom,
        setThreadId: setCurrentThreadId
    };
}