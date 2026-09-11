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

    // Handle navigation based on interrupt state
    useEffect(() => {
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
            if (threadIdToUse) {
                const targetPath = `/trip/${threadIdToUse}/summary`;
                console.log('[useTripThread] Run complete, navigating to:', targetPath);
                navigate(targetPath);
            }
        }
    }, [thread.interrupt?.id, thread.interrupt?.value?.type, thread.isLoading, thread.messages.length, navigate, currentThreadId, existingThreadId]);

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