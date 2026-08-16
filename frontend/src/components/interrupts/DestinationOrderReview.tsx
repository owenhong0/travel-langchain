import { useTripThreadContext } from "../../context/TripThreadProvider";

export function DestinationOrderReview() {
  const { interrupt, resume, isStreaming } = useTripThreadContext();
  if (!interrupt || interrupt.type !== "order_review") return null;

  return (
    <div>
      <h2>Review your destination order</h2>
      <ol>
        {interrupt.ordered_destinations.map((s, i) => (
          <li key={`${s.city}-${i}`}>{s.city}, {s.country}</li>
        ))}
      </ol>
      <button disabled={isStreaming} onClick={() => resume("approve")}>
        Approve
      </button>
      <button
        disabled={isStreaming}
        onClick={() => {
          const city = prompt("Which city to drop?");
          if (city) resume(`drop: ${city}`);
        }}
      >
        Drop a destination
      </button>
    </div>
  );
}