import { useContext } from "react";
import { TripThreadContext } from "../context/TripThreadContext";

export function useTripThreadContext() {
  const context = useContext(TripThreadContext);
  if (!context) {
    throw new Error("useTripThreadContext must be used within a TripThreadProvider");
  }
  return context;
}