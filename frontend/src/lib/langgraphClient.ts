// lib/langgraphClient.ts
import { Client } from "@langchain/langgraph-sdk";

export const client = new Client({
  apiUrl: import.meta.env.VITE_LANGGRAPH_API_URL, // http://localhost:2024 for `langgraph dev`
});

export const ASSISTANT_ID = "trip_orchestrator"; // matches langgraph.json graph key