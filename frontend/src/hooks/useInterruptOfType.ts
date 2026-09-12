// src/hooks/useInterruptOfType.ts

import type { Interrupt } from "../types/orchestrator";
import {useTripThreadContext} from "./useTripThreadContext.ts";

export function useInterruptOfType<T extends Interrupt["type"]>(
    type: T
): { 
    interrupt: Extract<Interrupt, { type: T }> | null;
    isProcessing: boolean;
    isUnexpected: boolean;
} {
    const { interrupt, isStreaming } = useTripThreadContext();
    
    // Case 1: The interrupt matches this component's type
    if (interrupt && interrupt.type === type) {
        return {
            interrupt: interrupt as Extract<Interrupt, { type: T }>,
            isProcessing: false,
            isUnexpected: false
        };
    }
    
    // Case 2: No interrupt exists yet AND a run is actively streaming (normal, transient)
    if (!interrupt && isStreaming) {
        return {
            interrupt: null,
            isProcessing: true,
            isUnexpected: false
        };
    }
    
    // Case 3: An interrupt exists but is a genuinely different type (unexpected)
    return {
        interrupt: null,
        isProcessing: false,
        isUnexpected: true
    };
}
