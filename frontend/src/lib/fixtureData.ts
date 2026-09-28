// src/lib/fixtureData.ts
import type { TripThreadState } from "../types/orchestrator";
import type { InterruptHistorySnapshot } from "./interruptHistory";

const files = import.meta.glob<TripThreadState>("../fixtures/*.json", {
  eager: true,
  import: "default",
});

export const fixtureName = import.meta.env.VITE_FIXTURE ?? "completed_trip";
export const state = files[`../fixtures/${fixtureName}.json`];
if (!state) {
  throw new Error(`[fixtureData] No fixture "${fixtureName}". Found: ${Object.keys(files).join(", ")}`);
}

// Every fixture with a pending interrupt, oldest → newest.
const ordered = Object.values(files)
  .filter((f) => f.interrupts.length > 0)
  .sort((a, b) => a.checkpoint.checkpoint_id.localeCompare(b.checkpoint.checkpoint_id));

// Only what would already have happened by the time the active fixture fires.
const activeIdx = ordered.findIndex((f) => f.checkpoint.checkpoint_id === state.checkpoint.checkpoint_id);
export const historyStates: TripThreadState[] =
  activeIdx === -1 ? [state] : ordered.slice(0, activeIdx + 1);

export const historySnapshots: InterruptHistorySnapshot[] = historyStates.flatMap((s) => {
  const pending = s.interrupts[0];
  if (!pending) return [];
  return [{
    interrupt_type: pending.value.type,
    checkpoint_ns: s.checkpoint.checkpoint_ns,
    checkpoint_id: s.checkpoint.checkpoint_id,
    next: s.next,
    values: s.values,
    interrupt_value: pending.value,
  }];
});