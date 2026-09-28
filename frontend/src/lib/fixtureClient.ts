// lib/fixtureClient.ts
import type {TripClient, TripThreadState} from "../types/orchestrator";
import type {Client} from "@langchain/langgraph-sdk";


const fixtures = import.meta.glob<TripThreadState>("../fixtures/*.json", {
  eager: true,
  import: "default",
});
const fixtureName = import.meta.env.VITE_FIXTURE ?? "completed_trip";
const state = fixtures[`../fixtures/${fixtureName}.json`];
if (!state) {
  throw new Error(
    `[fixtureClient] No fixture "${fixtureName}". Found: ${Object.keys(fixtures).join(", ")}`,
  );
}

export function createFixtureClient(): TripClient {
    console.log("[fixtureClient] instance created, fixture:", fixtureName);
    return {
        runs: {
            stream: async function* (_threadId, _assistantId, _opts) {
                console.log("[fixtureClient] runs.stream called");
                yield {event: "values", data: state.values};
            },
        },
        threads: {
            getState: async () => {
                console.log("[fixtureClient] threads.getState called");
                return state;
            },
            create: async () => {
                console.log("[fixtureClient] threads.create called, returning", state.checkpoint.thread_id);
                return {thread_id: state.checkpoint.thread_id} as unknown as Awaited<ReturnType<Client["threads"]["create"]>>;
            },
            getHistory: async () => {
                console.log("[fixtureClient] threads.getHistory called");
                return [state];
            },
        },
    };
}