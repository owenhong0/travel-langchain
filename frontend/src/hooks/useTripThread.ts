import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { client, ASSISTANT_ID } from "../lib/langgraphClient";
import { ROUTE_FOR_INTERRUPT } from "../lib/interruptRoutes";
import type { Interrupt, InitialTripState } from "../types/orchestrator";

export function useTripThread(existingThreadId?: string) {
  const [threadId, setThreadId] = useState<string | null>(existingThreadId ?? null);
  const [interrupt, setInterrupt] = useState<Interrupt | null>(null);
  const [runComplete, setRunComplete] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

const threadIdRef = useRef<string | null>(threadId);
useEffect(() => {
  threadIdRef.current = threadId;
}, [threadId]);

  const consumeStream = useCallback(
    async (tid: string, opts: { input?: InitialTripState; command?: { resume: string } }) => {
      setIsStreaming(true);
      setError(null);
      try {
        const stream = client.runs.stream(tid, ASSISTANT_ID, {
          input: opts.input,
          command: opts.command,
          streamMode: "values",
        });

        let sawInterrupt = false;
        for await (const chunk of stream) {
          if (chunk.event === "values") {
            const data = chunk.data as Record<string, unknown>;
            const pending = data.__interrupt__ as { value: Interrupt }[] | undefined;
            if (pending && pending.length > 0) {
              sawInterrupt = true;
              setInterrupt(pending[0].value);
            }
          }
        }
        if (!sawInterrupt) {
          setInterrupt(null);
          setRunComplete(true);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Stream failed");
      } finally {
        setIsStreaming(false);
      }
    },
    []
  );

  // Rehydrate on direct URL load / refresh — the backend's state is the source of truth
  useEffect(() => {
    if (existingThreadId && !interrupt && !runComplete) {
      client.threads.getState(existingThreadId).then((state) => {
        const pending = (state.values as Record<string, unknown>)?.__interrupt__ as
          | { value: Interrupt }[]
          | undefined;
        if (pending && pending.length > 0) {
          setInterrupt(pending[0].value);
        } else if (state.next.length === 0) {
          setRunComplete(true);
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingThreadId]);

  const start = useCallback(
    async (initialState: InitialTripState) => {
      const thread = await client.threads.create();
      setThreadId(thread.thread_id);
      await consumeStream(thread.thread_id, { input: initialState });
    },
    [consumeStream]
  );

  const resume = useCallback(
    async (value: string) => {
      const tid = threadIdRef.current;
      if (!tid) throw new Error("No active thread to resume");
      setInterrupt(null);
      await consumeStream(tid, { command: { resume: value } });
    },
    [consumeStream]
  );

  useEffect(() => {
    if (!threadId) return;
    if (interrupt) {
      navigate(`/trip/${threadId}/${ROUTE_FOR_INTERRUPT[interrupt.type]}`);
    } else if (runComplete) {
      navigate(`/trip/${threadId}/summary`);
    }
  }, [interrupt, runComplete, threadId, navigate]);

  return { threadId, interrupt, runComplete, isStreaming, error, start, resume };
}