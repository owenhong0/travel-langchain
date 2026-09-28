import type { TripThreadState } from "../types/orchestrator";
import type { InterruptHistorySnapshot } from "./interruptHistory";

const files = import.meta.glob<TripThreadState>("../fixtures/*.json", { eager: true, import: "default" });
const COMPLETED = "completed_trip";

// Interrupt fixtures, oldest → newest (build-fixtures gives them ascending checkpoint ids).
const steps = Object.values(files)
  .filter((f) => f.interrupts.length > 0)
  .sort((a, b) => a.checkpoint.checkpoint_id.localeCompare(b.checkpoint.checkpoint_id));

// The finished trip is the last state. It gets a message so useTripThread's "run complete"
// check (messages.length > 0 and no interrupt) navigates to /summary, and it chains onto the
// last interrupt so the history stays one branch.
const base = files[`../fixtures/${COMPLETED}.json`];
const finished: TripThreadState = {
  ...base,
  values: { ...base.values, messages: [{ id: "fixture-final", type: "ai", content: "Trip finalized." }] },
  parent_checkpoint: steps[steps.length - 1]?.checkpoint ?? null,
};

const sequence: TripThreadState[] = [...steps, finished];

export const fixtureName: string = import.meta.env.VITE_FIXTURE ?? COMPLETED;
const start = files[`../fixtures/${fixtureName}.json`];
if (!start) throw new Error(`[fixtureData] No fixture "${fixtureName}". Found: ${Object.keys(files).join(", ")}`);
const startIdx = fixtureName === COMPLETED
  ? sequence.length - 1
  : sequence.findIndex((s) => s.checkpoint.checkpoint_id === start.checkpoint.checkpoint_id);
if (startIdx === -1) throw new Error(`[fixtureData] "${fixtureName}" has no pending interrupt`);

let cursor = startIdx;

export const reset = () => { cursor = startIdx; };

export const currentState = () => sequence[cursor];
export const historyStates = () => sequence.slice(0, cursor + 1); // oldest → newest

// A resume moves one step on. A fork from an earlier checkpoint rewinds to it, then moves on.
export function advance(fromCheckpointId?: string) {
  const from = fromCheckpointId
    ? sequence.findIndex((s) => s.checkpoint.checkpoint_id === fromCheckpointId)
    : cursor;
  cursor = Math.min((from === -1 ? cursor : from) + 1, sequence.length - 1);
}

export const historySnapshots = (): InterruptHistorySnapshot[] =>
  historyStates().flatMap((s) => {
    const pending = s.interrupts[0];
    return pending ? [{
      interrupt_type: pending.value.type,
      checkpoint_ns: s.checkpoint.checkpoint_ns,
      checkpoint_id: s.checkpoint.checkpoint_id,
      next: s.next,
      values: s.values,
      interrupt_value: pending.value,
    }] : [];
  });