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

export function useReviewInterrupt<T extends Interrupt["type"]>(
  type: T
): UseReviewInterruptReturn<T> {
  const { resume, forkFrom, isStreaming, history, values: liveValues, interrupt: currentInterrupt } = useTripThreadContext();
  const location = useLocation();
  const viewingCheckpointId = (location.state as LocationState | null)?.viewingCheckpointId;
  const viewingInterruptType = (location.state as LocationState | null)?.viewingInterruptType;
  const isLive = !viewingCheckpointId;

  // Get interrupt history for historical lookups
  const interruptHistory = useInterruptHistory(currentInterrupt, history);

  // Use existing type-narrowing hook for live interrupts
  const liveInterruptResult = useInterruptOfType(type);

  let interrupt: Extract<Interrupt, { type: T }> | null = null;
  let values: InitialTripState | undefined = liveValues as InitialTripState | undefined;
  let sourceCheckpointId: string | undefined;
  let isProcessing = false;
  let isUnexpected = false;

  if (isLive) {
    interrupt = liveInterruptResult.interrupt;
    isProcessing = liveInterruptResult.isProcessing;
    isUnexpected = liveInterruptResult.isUnexpected;
  } else {
    // For historical interrupts, we need to check if we're viewing a specific interrupt type
    // that matches the requested type, since all interior interrupts share the same checkpoint
    console.log('[useReviewInterrupt] Historical mode:', {
      viewingInterruptType,
      requestedType: type,
      viewingCheckpointId,
      interruptHistoryLength: interruptHistory.length,
      interruptHistoryTypes: interruptHistory.map(h => h.type),
      currentInterruptType: currentInterrupt?.type
    });
    
    if (viewingInterruptType === type) {
      // First try to find the historical interrupt entry from our local history
      let historicalEntry = interruptHistory.find(entry => entry.type === type);
      console.log('[useReviewInterrupt] Historical entry from session history:', !!historicalEntry, historicalEntry?.type);
      
      // If not found in session history, try to reconstruct from thread history
      if (!historicalEntry && viewingCheckpointId) {
        console.log('[useReviewInterrupt] Attempting to reconstruct historical interrupt from thread history');
        
        // Find the checkpoint we're viewing
        const targetSnapshot = (history ?? []).find(
          (s) => s.checkpoint?.checkpoint_id === viewingCheckpointId
        );
        
        if (targetSnapshot) {
          console.log('[useReviewInterrupt] Found target snapshot:', {
            checkpointId: targetSnapshot.checkpoint?.checkpoint_id,
            hasValues: !!targetSnapshot.values
          });
          
          // For historical viewing, we'll create a minimal interrupt structure
          // This is a fallback when session history doesn't have the interrupt
          const fallbackInterrupt = {
            type: type,
            message: `Historical ${type} interrupt - original data not available in session`,
            // Add type-specific fallback data based on the interrupt type and expected component structure
            ...(type === 'human_feedback' && { 
              analysts: ['Historical analyst data not available in current session'] 
            }),
            ...(type === 'review_destinations' && { 
              destination_candidates: [{
                city: 'Historical Data',
                country: 'Not Available',
                rationale: 'Original destination data is not available in the current session. This is a historical view.',
                recommended_season: 'N/A',
                recommended_duration_days_min: 0,
                recommended_duration_days_max: 0,
                requires_flight_or_ferry: false
              }]
            }),
            ...(type === 'order_review' && { 
              destinations: [{
                city: 'Historical Data',
                country: 'Not Available',
                rationale: 'Original destination data is not available in the current session.',
                recommended_season: 'N/A',
                recommended_duration_days_min: 0,
                recommended_duration_days_max: 0,
                requires_flight_or_ferry: false
              }]
            }),
            ...(type === 'start_date_request' && { 
              message: 'Historical start date request - original data not available' 
            }),
            ...(type === 'date_review' && { 
              dates: []
            }),
            ...(type === 'loyalty_programmes_request' && { 
              message: 'Historical loyalty programmes request - original data not available' 
            }),
            ...(type === 'home_context_request' && { 
              message: 'Historical home context request - original data not available' 
            }),
            ...(type === 'transport_mode_review' && { 
              transport_modes: []
            }),
            ...(type === 'stay_type_review' && { 
              stay_types: []
            }),
            ...(type === 'stay_review' && { 
              stays: []
            })
          } as Extract<Interrupt, { type: T }>;
          
          interrupt = fallbackInterrupt;
          sourceCheckpointId = viewingCheckpointId;
          values = targetSnapshot.values as InitialTripState | undefined;
          
          console.log('[useReviewInterrupt] Created fallback historical interrupt:', {
            interruptType: interrupt?.type,
            hasValues: !!values,
            sourceCheckpointId
          });
        } else {
          console.warn('[useReviewInterrupt] Could not find target snapshot for checkpoint:', viewingCheckpointId);
        }
      } else if (historicalEntry) {
        // Use the stored complete interrupt data
        interrupt = historicalEntry.interruptData as Extract<Interrupt, { type: T }>;
        
        // Use the viewing checkpoint ID or the stored root checkpoint ID for forking
        sourceCheckpointId = viewingCheckpointId || historicalEntry.rootCheckpointId;
        
        // Get values from the snapshot at that checkpoint
        const snapshot = (history ?? []).find(
          (s) => s.checkpoint?.checkpoint_id === sourceCheckpointId
        );
        if (snapshot) {
          values = snapshot.values as InitialTripState | undefined;
        }
        
        console.log('[useReviewInterrupt] Historical interrupt loaded from session history:', {
          interruptType: interrupt?.type,
          hasValues: !!values,
          sourceCheckpointId
        });
      }
    } else {
      console.log('[useReviewInterrupt] Viewing different interrupt type:', viewingInterruptType, 'vs requested:', type);
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
    isProcessing: isLive ? isProcessing : false,
    isUnexpected: isLive ? isUnexpected : false,
    submit 
  };
}
