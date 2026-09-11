// src/components/interrupts/ReviewDestinationsInterrupt.tsx
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { HistoricalBanner } from "../HistoricalBanner";
import type { DestinationCandidate } from "../../types/orchestrator";

interface DestinationCardProps {
  candidate: DestinationCandidate;
  index: number;
}

function DestinationCard({ candidate, index }: DestinationCardProps) {
  const durationText = candidate.recommended_duration_days_min === candidate.recommended_duration_days_max
    ? `${candidate.recommended_duration_days_min} days`
    : `${candidate.recommended_duration_days_min}-${candidate.recommended_duration_days_max} days`;

  return (
    <li className="destination-card">
      <div className="destination-header">
        <strong className="destination-title">
          [{index}] {candidate.city}, {candidate.country}
        </strong>
        {candidate.requires_flight_or_ferry && (
          <span className="flight-indicator" title="Requires flight or ferry">✈️</span>
        )}
      </div>
      <div className="destination-details">
        <span className="destination-season">{candidate.recommended_season}</span>
        <span className="destination-duration">{durationText}</span>
        {candidate.date && (
          <span className="destination-date">{new Date(candidate.date).toLocaleDateString()}</span>
        )}
      </div>
      <p className="destination-rationale">{candidate.rationale}</p>
    </li>
  );
}

export function ReviewDestinationsInterrupt() {
    const { interrupt, isLive, isStreaming, submit } = useReviewInterrupt("review_destinations");
    
    if (!interrupt) {
        return <UnknownInterruptFallback />;
    }

    const handleApprove = () => submit("approve");
    const handleRequestChanges = (feedback: string) => submit(feedback);

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell 
                title="Review destination candidates" 
                isStreaming={isStreaming}
                onApprove={handleApprove} 
                onRequestChanges={handleRequestChanges}
            >
                <div className="destinations-review">
                    <p className="review-message">{interrupt.message}</p>
                    <ul className="destinations-list">
                        {interrupt.destination_candidates.map((candidate, index) => (
                            <DestinationCard 
                                key={`${candidate.city}-${candidate.country}-${index}`}
                                candidate={candidate}
                                index={index}
                            />
                        ))}
                    </ul>
                </div>
            </ReviewShell>
        </>
    );
}
