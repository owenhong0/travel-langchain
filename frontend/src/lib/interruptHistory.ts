// src/lib/interruptHistory.ts
import { historySnapshots } from "./fixtureData";

export interface InterruptHistorySnapshot {
  interrupt_type: string;
  checkpoint_ns: string;
  checkpoint_id: string;
  next: string[];
  values: unknown;
  interrupt_value: Record<string, unknown>;
}

export async function fetchInterruptHistory(threadId: string): Promise<{
  thread_id: string;
  count: number;
  snapshots: InterruptHistorySnapshot[];
}> {
  // Stub mode reads the same fixture sequence that getHistory uses, so the two can't disagree.
  if (import.meta.env.VITE_STUB_MODE === "true") {
    const snapshots = historySnapshots();
    return { thread_id: threadId, count: snapshots.length, snapshots };
  }

  const res = await fetch(`${import.meta.env.VITE_LANGGRAPH_API_URL}/interrupt-history/${threadId}`);
  if (!res.ok) throw new Error(`Failed to fetch interrupt history: ${res.status}`);
  return res.json();
}