// src/lib/fixtureClient.ts
import type {Client} from "@langchain/langgraph-sdk";
import type {TripClient} from "../types/orchestrator";
import {fixtureName, currentState, historyStates, advance, reset} from "./fixtureData";

interface StreamPayload {
    command?: { resume?: unknown };
    checkpoint?: { checkpoint_id?: string };
}

export function createFixtureClient(): TripClient {
    console.log("[fixtureClient] instance created, fixture:", fixtureName);
    return {
        runs: {
            stream: async function* (_threadId, _assistantId, payload) {
                const opts = payload as unknown as StreamPayload | undefined;
                // A resume moves one step on; a fork passes the checkpoint it branches from.
                if (opts?.command?.resume !== undefined) {
                    advance(opts.checkpoint?.checkpoint_id);
                } else if (!opts?.command) {
                    reset(); // a fresh start begins the sequence again
                }
                console.log("[fixtureClient] runs.stream ->", currentState().checkpoint.checkpoint_id);
                yield {event: "values", data: structuredClone(currentState().values)};
            },
        },
        threads: {
            getState: async () => structuredClone(currentState()),
            create: async () =>
                ({thread_id: currentState().checkpoint.thread_id}) as unknown as Awaited<ReturnType<Client["threads"]["create"]>>,
            getHistory: async () => structuredClone([...historyStates()].reverse()),
        },
    };
}