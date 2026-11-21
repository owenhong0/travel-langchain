// src/lib/analysts.ts
import type { Analyst } from "../types/orchestrator";

export type Note = { id: string; text: string; analyst?: string };

/** Accepts the new structured analyst OR the old "Name: …\nRole: …" persona string
 *  (old fixtures still use strings — remove the string branch after recapturing). */
export function normalizeAnalyst(a: Analyst | string): Analyst {
    if (typeof a !== "string") return a;
    const get = (key: string) => a.match(new RegExp(`^${key}:\\s*(.*)$`, "m"))?.[1]?.trim() ?? "";
    return { persona_name: get("Name"), focus_area: get("Focus"), description: get("Description") };
}

/** Turns the notes list into the single feedback string the backend expects. */
export function composeFeedback(notes: Note[]): string {
    return notes
        .map((n, i) => `${i + 1}. ${n.analyst ? `[${n.analyst}] ` : ""}${n.text}`)
        .join("\n");
}

/** Not crypto.randomUUID(): it's undefined over plain http on your phone (npm run dev -- --host). */
let counter = 0;
export const newNoteId = () => `note-${Date.now()}-${counter++}`;