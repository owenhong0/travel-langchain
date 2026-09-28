// lib/langgraphClient.ts
import {Client} from "@langchain/langgraph-sdk";
import {createFixtureClient} from "./fixtureClient";
import type {TripClient, TripThreadState} from "../types/orchestrator";

function createRealClient(): TripClient {
    const raw = new Client({apiUrl: import.meta.env.VITE_LANGGRAPH_API_URL});
    return {
        runs: {stream: raw.runs.stream.bind(raw.runs)},
        // lib/langgraphClient.ts — inside createRealClient()
        threads: {
            getState: async (threadId) => (await raw.threads.getState(threadId)) as unknown as TripThreadState,
            create: raw.threads.create.bind(raw.threads),
            getHistory: raw.threads.getHistory.bind(raw.threads) as unknown as TripClient["threads"]["getHistory"],
        },
    };
}

export const client: TripClient =
    import.meta.env.VITE_STUB_MODE === "true" ? createFixtureClient() : createRealClient();

// useStream's client option wants the SDK's full Client type; verified via
// stream.lgp.cjs that it only ever calls threads.getState/create + runs.stream,
// all of which TripClient implements — this cast bridges the declared gap.
export const sdkClient = client as unknown as Client;

export const ASSISTANT_ID = "orchestrator"; // matches langgraph.json graph key