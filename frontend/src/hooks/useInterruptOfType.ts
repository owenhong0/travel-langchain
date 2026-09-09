// src/hooks/useInterruptOfType.ts

import type { Interrupt } from "../types/orchestrator";
import {useTripThreadContext} from "./useTripThreadContext.ts";

export function useInterruptOfType<T extends Interrupt["type"]>(
    type: T
): Extract<Interrupt, { type: T }> | null {
    const { interrupt } = useTripThreadContext();
    if (!interrupt || interrupt.type !== type) return null;
    return interrupt as Extract<Interrupt, { type: T }>;
}