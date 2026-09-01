import { createContext, useContext, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useTripThread } from "../hooks/useTripThread";

type TripThreadContextValue = ReturnType<typeof useTripThread>;

const TripThreadContext = createContext<TripThreadContextValue | null>(null);

export function TripThreadProvider({ children }: { children: ReactNode }) {
  const { threadId: routeThreadId } = useParams<{ threadId: string }>();
  const tripThread = useTripThread(routeThreadId);

  return (
    <TripThreadContext.Provider value={tripThread}>
      {children}
    </TripThreadContext.Provider>
  );
}

export function useTripThreadContext(): TripThreadContextValue {
  const ctx = useContext(TripThreadContext);
  if (!ctx) throw new Error("useTripThreadContext must be used within a TripThreadProvider");
  return ctx;
}