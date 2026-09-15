import { useLocation } from "react-router-dom";
import { useTripThreadContext } from "./useTripThreadContext";
import { useInterruptOfType } from "./useInterruptOfType";
import type { Interrupt, InitialTripState } from "../types/orchestrator";
import type { InterruptHistorySnapshot } from "../lib/interruptHistory";

interface LocationState {
  viewingCheckpointId?: string;
  viewingInterruptType?: string;
}

interface UseReviewInterruptReturn<T extends Interrupt["type"]> {
  interrupt: Extract<Interrupt, { type: T }> | null;
  values: InitialTripState | undefined;
  isLive: boolean;
  isStreaming: boolean;
  isProcessing: boolean;
  isUnexpected: boolean;
  submit: (value: string | object) => Promise<void>;
}

function resolveHistoricalInterrupt<T extends Interrupt["type"]>(
  type: T,
  viewingCheckpointId: string | undefined,
  interruptHistory: InterruptHistorySnapshot[]
): {
  interrupt: Extract<Interrupt, { type: T }> | null;
  values: InitialTripState | undefined;
  sourceCheckpointId: string | undefined;
  sourceCheckpointNs: string | undefined;
} {
  if (!viewingCheckpointId) {
    return { interrupt: null, values: undefined, sourceCheckpointId: undefined, sourceCheckpointNs: undefined };
  }

  const entry = interruptHistory.find((snap) => snap.checkpoint_id === viewingCheckpointId);

  if (!entry || entry.interrupt_type !== type) {
    return { interrupt: null, values: undefined, sourceCheckpointId: undefined, sourceCheckpointNs: undefined };
  }

  return {
    interrupt: entry.interrupt_value as Extract<Interrupt, { type: T }>,
    values: entry.values as InitialTripState | undefined,
    sourceCheckpointId: viewingCheckpointId,
    sourceCheckpointNs: entry.checkpoint_ns,
  };
}

export function useReviewInterrupt<T extends Interrupt["type"]>(
  type: T
): UseReviewInterruptReturn<T> {
  const { resume, forkFrom, isStreaming, interruptHistory, values: liveValues } = useTripThreadContext();
  const location = useLocation();
  const viewingCheckpointId = (location.state as LocationState | null)?.viewingCheckpointId;
  const isLive = !viewingCheckpointId;

  const liveInterruptResult = useInterruptOfType(type);

  const historical = isLive
    ? { interrupt: null, values: undefined, sourceCheckpointId: undefined, sourceCheckpointNs: undefined }
    : resolveHistoricalInterrupt(type, viewingCheckpointId, interruptHistory);

  const interrupt = isLive ? liveInterruptResult.interrupt : historical.interrupt;
  const values = isLive ? (liveValues as InitialTripState | undefined) : historical.values;
  const sourceCheckpointId = isLive ? undefined : historical.sourceCheckpointId;
  const sourceCheckpointNs = isLive ? undefined : historical.sourceCheckpointNs;
  const isProcessing = isLive ? liveInterruptResult.isProcessing : false;
  const isUnexpected = isLive ? liveInterruptResult.isUnexpected : false;

  const submit = async (value: string | object): Promise<void> => {
    try {
      if (isLive) {
        await resume(value);
      } else if (sourceCheckpointId) {
        await forkFrom(sourceCheckpointId, sourceCheckpointNs ?? "", value);
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