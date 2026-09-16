import {useCallback, useEffect, useState, useRef} from "react";
import {useNavigate} from "react-router-dom";
import {ROUTE_FOR_INTERRUPT} from "../lib/interruptRoutes";
import type {InitialTripState, Interrupt} from "../types/orchestrator";
import {useStream} from "@langchain/langgraph-sdk/react";
import {fetchInterruptHistory, type InterruptHistorySnapshot} from "../lib/interruptHistory";

const TEST_MODE = import.meta.env.VITE_TEST_MODE === "true";

export function useTripThread(existingThreadId?: string) {
    const navigate = useNavigate();
    const [currentThreadId, setCurrentThreadId] = useState<string | null>(existingThreadId || null);
    const lastInterruptIdRef = useRef<string | undefined>(null);

    // New — holds the namespace-aware interrupt history from our custom endpoint.
    const [interruptHistory, setInterruptHistory] = useState<InterruptHistorySnapshot[]>([]);

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

    // New — fetches the full interrupt history from our custom backend endpoint,
    // which walks every checkpoint_ns (unlike thread.history, which only sees
    // the root namespace). Called on initial load and after resume/fork succeed.
    const refreshInterruptHistory = useCallback(async (threadId: string) => {
        try {
            const result = await fetchInterruptHistory(threadId);
            setInterruptHistory(result.snapshots);
        } catch (err) {
            console.error('[useTripThread] Failed to fetch interrupt history:', err);
        }
    }, []);

    const start = useCallback(
        async (initialState: InitialTripState) => {
            await thread.submit(initialState, {
                config: {configurable: {test_mode: TEST_MODE}},
            });
            const threadIdToUse = currentThreadId || existingThreadId;
            if (threadIdToUse) {
                await refreshInterruptHistory(threadIdToUse);
            }
        },
        [thread, currentThreadId, existingThreadId, refreshInterruptHistory]
    );

    const resume = useCallback(
        async (value: string | object) => {
            console.log('[useTripThread] Resuming with value:', value);
            await thread.submit(undefined, {
                command: {resume: value},
                config: {configurable: {test_mode: TEST_MODE}},
            });
            const threadIdToUse = currentThreadId || existingThreadId;
            if (threadIdToUse) {
                await refreshInterruptHistory(threadIdToUse);
            }
        },
        [thread, currentThreadId, existingThreadId, refreshInterruptHistory]
    );

    const forkFrom = useCallback(
        async (checkpointId: string, checkpointNs: string, value: string | object) => {
            console.log('[useTripThread] Forking from checkpoint:', checkpointId, 'ns:', checkpointNs, 'with value:', value);
            await thread.submit(undefined, {
                command: {resume: value},
                checkpoint: {checkpoint_id: checkpointId, checkpoint_ns: checkpointNs, checkpoint_map: undefined},
                config: {configurable: {test_mode: TEST_MODE}},
            });
            const threadIdToUse = currentThreadId || existingThreadId;
            if (threadIdToUse) {
                await refreshInterruptHistory(threadIdToUse);
            }
        },
        [thread, currentThreadId, existingThreadId, refreshInterruptHistory]
    );

    // Original — unchanged. Handles navigation based on interrupt state, only
    // navigating for NEW interrupts.
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

    // New — separate effect, separate concern: fetch interrupt history once
    // the thread ID is known (covers initial load, refresh, and deep links).
    useEffect(() => {
        const threadIdToUse = currentThreadId || existingThreadId;
        if (!threadIdToUse) return;

        let cancelled = false;

        fetchInterruptHistory(threadIdToUse)
            .then((result) => {
                if (!cancelled) {
                    setInterruptHistory(result.snapshots);
                }
            })
            .catch((err) => {
                console.error('[useTripThread] Failed to fetch interrupt history:', err);
            });

        return () => {
            cancelled = true;
        };
    }, [currentThreadId, existingThreadId]);

    const errorMessage = thread.error ?
        (typeof thread.error === 'string' ? thread.error :
            typeof thread.error === 'object' && thread.error && 'message' in thread.error ?
                String(thread.error.message) : 'An error occurred') : null;

    return {
        threadId: currentThreadId || existingThreadId || null,
        interrupt: thread.interrupt?.value as Interrupt | undefined,
        values: thread.values,
        interruptHistory, // new — the namespace-aware endpoint data
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