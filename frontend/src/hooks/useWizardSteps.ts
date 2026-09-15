// src/hooks/useWizardSteps.ts
import { useMemo } from "react";
import { useTripThreadContext } from "./useTripThreadContext";
import type { Interrupt } from "../types/orchestrator";

export interface WizardStep {
  type: Interrupt["type"];
  checkpointId: string;
  isCurrent: boolean;
}

export function useWizardSteps(): WizardStep[] {
  const { history, interrupt: currentInterrupt } = useTripThreadContext();

  return useMemo(() => {
    const steps = (history ?? [])
      .filter((snapshot) => snapshot.tasks?.[0]?.interrupts?.length)
      .map((snapshot) => ({
        type: snapshot.tasks[0].interrupts[0].value?.type as Interrupt["type"],
        checkpointId: snapshot.checkpoint?.checkpoint_id as string,
        isCurrent: false,
      }))
      .sort((a, b) => a.checkpointId.localeCompare(b.checkpointId));

    // checkpoint_id is ULID-based, so the last entry after a chronological
    // sort is the current pending interrupt, if the thread is still paused.
    if (steps.length > 0 && currentInterrupt) {
      steps[steps.length - 1] = { ...steps[steps.length - 1], isCurrent: true };
    }

    return steps;
  }, [history, currentInterrupt]);
}