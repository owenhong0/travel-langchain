import { useEffect, useRef, useState } from "react";
import { ROUTE_FOR_INTERRUPT } from "../lib/interruptRoutes";
import type { Interrupt } from "../types/orchestrator";

export interface InterruptHistoryEntry {
  type: Interrupt["type"];
  timestamp: string;
  rootCheckpointId?: string;
  route: string;
  interruptData: Interrupt; // Store the complete interrupt object
}

/**
 * Hook to track interrupt history locally within a session.
 * 
 * Since LangGraph's subgraph interrupts (like those within trip_info_graph) 
 * all happen within a single root-level checkpoint, thread.history only shows
 * one entry for the entire trip_info phase. This hook watches thread.interrupt
 * for changes and accumulates a local list of all interrupts encountered.
 * 
 * LIMITATION: This is session-only - the list is rebuilt from scratch on each
 * page reload and doesn't persist historical data across browser sessions.
 */
export function useInterruptHistory(
  interrupt: Interrupt | undefined,
  history: any[] | undefined
) {
  const [interruptHistory, setInterruptHistory] = useState<InterruptHistoryEntry[]>([]);
  const lastInterruptTypeRef = useRef<string | null>(null);
  const seenInterruptTypesRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!interrupt?.type) {
      return;
    }

    // Only add if this is a new interrupt type that we haven't seen before in this session
    // This prevents duplicates when navigating back to previous steps
    if (interrupt.type !== lastInterruptTypeRef.current && !seenInterruptTypesRef.current.has(interrupt.type)) {
      const route = ROUTE_FOR_INTERRUPT[interrupt.type as keyof typeof ROUTE_FOR_INTERRUPT];
      
      if (route) {
        const newEntry: InterruptHistoryEntry = {
          type: interrupt.type,
          timestamp: new Date().toISOString(),
          rootCheckpointId: history?.[0]?.checkpoint?.checkpoint_id,
          route,
          interruptData: interrupt,
        };

        setInterruptHistory(prev => [...prev, newEntry]);
        lastInterruptTypeRef.current = interrupt.type;
        seenInterruptTypesRef.current.add(interrupt.type);
      }
    } else if (interrupt.type !== lastInterruptTypeRef.current) {
      // Update the last seen type even if we don't add a new entry
      lastInterruptTypeRef.current = interrupt.type;
    }
  }, [interrupt?.type, interrupt?.message, history]);

  // Reset history when thread changes (new trip started)
  const currentThreadCheckpoint = history?.[0]?.checkpoint?.checkpoint_id;
  const previousThreadCheckpointRef = useRef<string | null>(null);
  
  useEffect(() => {
    if (currentThreadCheckpoint && 
        currentThreadCheckpoint !== previousThreadCheckpointRef.current &&
        previousThreadCheckpointRef.current !== null) {
      // New thread detected, reset history and seen interrupts
      setInterruptHistory([]);
      lastInterruptTypeRef.current = null;
      seenInterruptTypesRef.current.clear();
    }
    previousThreadCheckpointRef.current = currentThreadCheckpoint;
  }, [currentThreadCheckpoint]);

  return interruptHistory;
}