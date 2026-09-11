// src/components/interrupts/TransportModeReviewInterrupt.tsx  (route: transport)
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { HistoricalBanner } from "../HistoricalBanner";
import type { TransportLeg, InitialTripState } from "../../types/orchestrator";

interface TransportLegCardProps {
  leg: TransportLeg;
  index: number;
}

function TransportLegCard({ leg, index }: TransportLegCardProps) {
  const getLegTypeIcon = (legType: TransportLeg["leg_type"]): string => {
    switch (legType) {
      case "arrival": return "🛬";
      case "departure": return "🛫";
      case "internal": return "🚗";
      default: return "🚌";
    }
  };

  const getLegTypeLabel = (legType: TransportLeg["leg_type"]): string => {
    switch (legType) {
      case "arrival": return "Arrival";
      case "departure": return "Departure";
      case "internal": return "Internal";
      default: return "Transport";
    }
  };

  const formatDistance = (distance: number | null): string => {
    if (!distance) return "Distance unknown";
    return `${distance.toLocaleString()} miles`;
  };

  return (
    <li className="transport-leg-card">
      <div className="leg-header">
        <div className="leg-route">
          <span className="leg-type-icon" title={getLegTypeLabel(leg.leg_type)}>
            {getLegTypeIcon(leg.leg_type)}
          </span>
          <div className="route-info">
            <div className="route-cities">
              <span className="origin-city">{leg.origin}</span>
              <span className="route-arrow">→</span>
              <span className="destination-city">{leg.destination}</span>
            </div>
            <div className="route-countries">
              {leg.origin_country !== leg.destination_country && (
                <span className="country-info">
                  {leg.origin_country} → {leg.destination_country}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="leg-badges">
          <span className={`leg-type-badge leg-type-${leg.leg_type}`}>
            {getLegTypeLabel(leg.leg_type)}
          </span>
          {leg.requires_flight_or_ferry && (
            <span className="flight-ferry-badge" title="Requires flight or ferry">
              ✈️/⛴️
            </span>
          )}
        </div>
      </div>

      <div className="leg-details">
        <div className="leg-info-row">
          <span className="depart-date">
            📅 {new Date(leg.depart_date).toLocaleDateString()}
          </span>
          <span className="distance">
            📏 {formatDistance(leg.distance_miles)}
          </span>
        </div>

        {leg.modes_requested.length > 0 && (
          <div className="requested-modes">
            <strong>Requested modes:</strong> {leg.modes_requested.join(", ")}
          </div>
        )}
      </div>
    </li>
  );
}

export function TransportModeReviewInterrupt() {
    const { interrupt, values, isLive, isStreaming, submit } = useReviewInterrupt("transport_mode_review");
    
    if (!interrupt) {
        return <UnknownInterruptFallback />;
    }

    // Type the values properly and use the legs from the interrupt
    const typedValues = values as InitialTripState | undefined;
    const legs = interrupt.legs; // Use legs from interrupt, not values

    const handleApprove = () => submit("approve");
    const handleRequestChanges = (feedback: string) => submit(feedback);

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell 
                title="Review transportation for each leg" 
                isStreaming={isStreaming}
                onApprove={handleApprove} 
                onRequestChanges={handleRequestChanges}
            >
                <div className="transport-review">
                    <p className="review-message">{interrupt.message}</p>
                    
                    <div className="transport-legs">
                        <ol className="legs-list">
                            {legs.map((leg, index) => (
                                <TransportLegCard 
                                    key={`${leg.origin}-${leg.destination}-${index}`}
                                    leg={leg}
                                    index={index}
                                />
                            ))}
                        </ol>
                    </div>

                    {legs.length === 0 && (
                        <div className="no-legs-message">
                            <p>No transportation legs to review.</p>
                        </div>
                    )}
                </div>
            </ReviewShell>
        </>
    );
}
