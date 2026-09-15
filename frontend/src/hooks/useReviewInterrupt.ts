import { useLocation } from "react-router-dom";
import { useTripThreadContext } from "./useTripThreadContext";
import { useInterruptOfType } from "./useInterruptOfType";
import { useInterruptHistory } from "./useInterruptHistory";
import type { Interrupt, InitialTripState } from "../types/orchestrator";

interface LocationState {
  viewingCheckpointId?: string;
  viewingInterruptType?: string;
}

// Type-safe return type for the hook
interface UseReviewInterruptReturn<T extends Interrupt["type"]> {
  interrupt: Extract<Interrupt, { type: T }> | null;
  values: InitialTripState | undefined;
  isLive: boolean;
  isStreaming: boolean;
  isProcessing: boolean;
  isUnexpected: boolean;
  submit: (value: string | object) => Promise<void>;
}

// New helper — module scope, all const
function resolveHistoricalInterrupt<T extends Interrupt["type"]>(
  type: T,
  viewingInterruptType: string | undefined,
  viewingCheckpointId: string | undefined,
  interruptHistory: ReturnType<typeof useInterruptHistory>,
  history: ReturnType<typeof useTripThreadContext>["history"]
): {
  interrupt: Extract<Interrupt, { type: T }> | null;
  values: InitialTripState | undefined;
  sourceCheckpointId: string | undefined;
} {
  if (viewingInterruptType !== type) {
    return { interrupt: null, values: undefined, sourceCheckpointId: undefined };
  }

  const historicalEntry = interruptHistory.find((entry) => entry.type === type);

  if (historicalEntry) {
    const sourceCheckpointId = viewingCheckpointId || historicalEntry.rootCheckpointId;
    const snapshot = (history ?? []).find(
      (s) => s.checkpoint?.checkpoint_id === sourceCheckpointId
    );
    return {
      interrupt: historicalEntry.interruptData as Extract<Interrupt, { type: T }>,
      values: snapshot?.values as InitialTripState | undefined,
      sourceCheckpointId,
    };
  }

  const targetSnapshot = (history ?? []).find(
    (s) => s.checkpoint?.checkpoint_id === viewingCheckpointId
  );

  if (!targetSnapshot) {
    return { interrupt: null, values: undefined, sourceCheckpointId: undefined };
  }

  // The real interrupt payload from that checkpoint — the same object the user
  // actually saw at the time — instead of a fabricated placeholder.
  const rawInterrupt = targetSnapshot.tasks?.[0]?.interrupts?.[0]?.value;

  return {
    interrupt: (rawInterrupt ?? null) as Extract<Interrupt, { type: T }> | null,
    values: targetSnapshot.values as InitialTripState | undefined,
    sourceCheckpointId: viewingCheckpointId,
  };
}

// Rewritten hook body — no `let` anywhere
export function useReviewInterrupt<T extends Interrupt["type"]>(
  type: T
): UseReviewInterruptReturn<T> {
  const { resume, forkFrom, isStreaming, history, values: liveValues, interrupt: currentInterrupt } = useTripThreadContext();
  const location = useLocation();
  const viewingCheckpointId = (location.state as LocationState | null)?.viewingCheckpointId;
  const viewingInterruptType = (location.state as LocationState | null)?.viewingInterruptType;
  const isLive = !viewingCheckpointId;

  const interruptHistory = useInterruptHistory(currentInterrupt, history);
  const liveInterruptResult = useInterruptOfType(type);

  const historical = isLive
    ? { interrupt: null, values: undefined, sourceCheckpointId: undefined }
    : resolveHistoricalInterrupt(type, viewingInterruptType, viewingCheckpointId, interruptHistory, history);

  const interrupt = isLive ? liveInterruptResult.interrupt : historical.interrupt;
  const values = isLive ? (liveValues as InitialTripState | undefined) : historical.values;
  const sourceCheckpointId = isLive ? undefined : historical.sourceCheckpointId;
  const isProcessing = isLive ? liveInterruptResult.isProcessing : false;
  const isUnexpected = isLive ? liveInterruptResult.isUnexpected : false;

  const submit = async (value: string | object): Promise<void> => {
    try {
      if (isLive) {
        await resume(value);
      } else if (sourceCheckpointId) {
        await forkFrom(sourceCheckpointId, value);
      } else {
        console.warn('Cannot submit: no live interrupt or source checkpoint ID');
      }
    } catch (error) {
      console.error('Error submitting interrupt response:', error);
      throw error;
    }
  };

  return {
    interrupt,
    values,
    isLive,
    isStreaming: isLive ? isStreaming : false,
    isProcessing,
    isUnexpected,
    submit,
  };
}