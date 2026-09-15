// src/lib/interruptHistory.ts
export async function fetchInterruptHistory(threadId: string) {
  const res = await fetch(`${API_BASE_URL}/interrupt-history/${threadId}`);
  if (!res.ok) throw new Error(`Failed to fetch interrupt history: ${res.status}`);
  return res.json() as Promise<{
    thread_id: string;
    count: number;
    snapshots: Array<{
      interrupt_type: string;
      checkpoint_ns: string;
      checkpoint_id: string;
      next: string[];
      values: unknown;
      interrupt_value: Record<string, unknown>;
    }>;
  }>;
}