import { useTripThreadContext } from './useTripThreadContext';

/**
 * Hook to access wizard progress data - accumulated user responses from all interrupt nodes.
 * This enables backward navigation by providing access to previously completed steps.
 */
export function useWizardProgress() {
  const { state } = useTripThreadContext();
  
  const wizardProgress = state?.wizard_progress || {};
  
  // Helper to get a specific interrupt's response
  const getInterruptResponse = (interruptType: string): unknown => {
    return wizardProgress[interruptType];
  };
  
  // Helper to check if an interrupt has been completed
  const isInterruptCompleted = (interruptType: string): boolean => {
    return interruptType in wizardProgress;
  };
  
  // Get all completed interrupt types
  const getCompletedInterrupts = (): string[] => {
    return Object.keys(wizardProgress);
  };
  
  // Get the full wizard progress object
  const getAllProgress = (): Record<string, unknown> => {
    return wizardProgress;
  };
  
  return {
    wizardProgress,
    getInterruptResponse,
    isInterruptCompleted,
    getCompletedInterrupts,
    getAllProgress,
  };
}