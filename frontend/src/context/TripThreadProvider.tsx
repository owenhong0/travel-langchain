import { useParams } from "react-router-dom";
import { useTripThread } from "../hooks/useTripThread";
import { TripThreadContext } from "./TripThreadContext";

export function TripThreadProvider({ children }: { children: React.ReactNode }) {
  const { threadId } = useParams<{ threadId: string }>();
  const thread = useTripThread(threadId);

  return (
    <TripThreadContext.Provider value={thread}>
      {children}
    </TripThreadContext.Provider>
  );
}

