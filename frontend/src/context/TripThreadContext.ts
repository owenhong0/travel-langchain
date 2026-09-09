import { createContext } from "react";
import { useTripThread } from "../hooks/useTripThread";

type TripThreadContextValue = ReturnType<typeof useTripThread>;

export const TripThreadContext = createContext<TripThreadContextValue | null>(null);