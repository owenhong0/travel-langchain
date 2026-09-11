import { createContext, useContext, useState, type ReactNode } from "react";
import type { ThreadState } from "@langchain/langgraph-sdk";
import type { Interrupt } from "../types/orchestrator";

const REVIEW_INTERRUPT_TYPES = new Set([
  "human_feedback",
  "order_review",
  "start_date_request",
  "date_review",
  "loyalty_programmes_request",
  "home_context_request",
  "transport_mode_review",
  "stay_review",
]);

interface ThreadHistoryContextValue {
  reviewStages: ThreadState[];
  headCheckpointId: string | undefined;
  viewingCheckpointId: string | undefined;
  viewingStage: ThreadState | undefined;
  isLive: boolean;
  setViewingCheckpointId: (id: string | undefined) => void;
}

const ThreadHistoryContext = createContext<ThreadHistoryContextValue | null>(null);

interface Props {
  history: ThreadState[]; // pass thread.history straight in from useTripThread
  children: ReactNode;
}

export function ThreadHistoryProvider({ history, children }: Props) {
  const [viewingCheckpointId, setViewingCheckpointId] = useState<string | undefined>(undefined);

  const reviewStages = history.filter((snap) =>
    snap.tasks.some((task) =>
      task.interrupts.some((interrupt) => {
        const value = interrupt.value as Interrupt | undefined;
        return value?.type !== undefined && REVIEW_INTERRUPT_TYPES.has(value.type);
      })
    )
  );

  const headCheckpointId = history[0]?.checkpoint?.checkpoint_id ?? undefined;
  const effectiveViewingId = viewingCheckpointId ?? headCheckpointId;
  const viewingStage = history.find((s) => s.checkpoint?.checkpoint_id === effectiveViewingId);
  const isLive = effectiveViewingId === headCheckpointId;

  return (
    <ThreadHistoryContext.Provider
      value={{
        reviewStages,
        headCheckpointId,
        viewingCheckpointId: effectiveViewingId,
        viewingStage,
        isLive,
        setViewingCheckpointId,
      }}
    >
      {children}
    </ThreadHistoryContext.Provider>
  );
}

export function useThreadHistoryContext(): ThreadHistoryContextValue {
  const ctx = useContext(ThreadHistoryContext);
  if (!ctx) throw new Error("useThreadHistoryContext must be used within ThreadHistoryProvider");
  return ctx;
}