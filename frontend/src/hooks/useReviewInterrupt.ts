import { useLocation } from "react-router-dom";
import { useTripThreadContext } from "./useTripThreadContext";
import { useInterruptOfType } from "./useInterruptOfType";
import type { Interrupt, InitialTripState } from "../types/orchestrator";

interface LocationState {
  viewingCheckpointId?: string;
}

// Type-safe return type for the hook
interface UseReviewInterruptReturn<T extends Interrupt["type"]> {
  interrupt: Extract<Interrupt, { type: T }> | null;
  values: InitialTripState | undefined;
  isLive: boolean;
  isStreaming: boolean;
  submit: (value: string | object) => Promise<void>;
}

export function useReviewInterrupt<T extends Interrupt["type"]>(
  type: T
): UseReviewInterruptReturn<T> {
  const { resume, forkFrom, isStreaming, history, values: liveValues } = useTripThreadContext();
  const location = useLocation();
  const viewingCheckpointId = (location.state as LocationState | null)?.viewingCheckpointId;
  const isLive = !viewingCheckpointId;

  // Use existing type-narrowing hook for live interrupts
  const liveInterrupt = useInterruptOfType(type);

  let interrupt: Extract<Interrupt, { type: T }> | null = null;
  let values: InitialTripState | undefined = liveValues as InitialTripState | undefined;
  let sourceCheckpointId: string | undefined;

  if (isLive) {
    interrupt = liveInterrupt;
  } else {
    const snapshot = (history ?? []).find(
      (s) => s.checkpoint?.checkpoint_id === viewingCheckpointId
    );
    if (snapshot) {
      const historicalInterrupt = snapshot.tasks[0]?.interrupts[0]?.value as Interrupt | undefined;
      if (historicalInterrupt?.type === type) {
        interrupt = historicalInterrupt as Extract<Interrupt, { type: T }>;
        values = snapshot.values as InitialTripState | undefined;
        sourceCheckpointId = snapshot.checkpoint?.checkpoint_id ?? undefined;
      }
    }
  }

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
    submit 
  };
}
