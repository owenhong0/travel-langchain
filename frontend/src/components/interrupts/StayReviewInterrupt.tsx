// src/components/interrupts/StayReviewInterrupt.tsx  (route: stays)
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { ReviewShell } from "./ReviewShell";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";
import { HistoricalBanner } from "../HistoricalBanner";
import type { StayOption, StayLeg, InitialTripState } from "../../types/orchestrator";

interface StayOptionCardProps {
  option: StayOption;
  index: number;
}

function StayOptionCard({ option, index }: StayOptionCardProps) {
  const formatPrice = (option: StayOption): string => {
    if (option.price_estimate) {
      return option.price_estimate;
    }
    if (option.price_amount && option.price_currency) {
      return `${option.price_currency} ${option.price_amount}`;
    }
    return "Price not available";
  };

  const getBrandBadgeColor = (classification: StayOption["brand_classification"]): string => {
    switch (classification) {
      case "international_chain": return "#3b82f6";
      case "local_chain": return "#10b981";
      case "boutique": return "#8b5cf6";
      case "independent_local": return "#f59e0b";
      case "vacation_rental": return "#ef4444";
      default: return "#6b7280";
    }
  };

  return (
    <li className="stay-option-card">
      <div className="stay-header">
        <div className="stay-title-section">
          <strong className="stay-name">{option.name}</strong>
          <div className="stay-badges">
            <span 
              className="brand-badge" 
              style={{ backgroundColor: getBrandBadgeColor(option.brand_classification) }}
            >
              {option.brand_classification.replace(/_/g, ' ')}
            </span>
            {option.confidence && (
              <span className={`confidence-badge confidence-${option.confidence}`}>
                {option.confidence}
              </span>
            )}
          </div>
        </div>
        <div className="stay-price">
          {formatPrice(option)}
          {option.price_type && option.price_type !== "unknown" && (
            <span className="price-type"> ({option.price_type.replace(/_/g, ' ')})</span>
          )}
        </div>
      </div>
      
      <div className="stay-details">
        <div className="stay-info-row">
          <span className="stay-type">{option.type}</span>
          {option.area && <span className="stay-area">{option.area}</span>}
          {option.rating && <span className="stay-rating">⭐ {option.rating}</span>}
        </div>
        
        {option.price_note && (
          <p className="price-note">{option.price_note}</p>
        )}
        
        {option.booking_url && (
          <a 
            href={option.booking_url} 
            target="_blank" 
            rel="noopener noreferrer"
            className="booking-link"
          >
            View Details
          </a>
        )}
      </div>
    </li>
  );
}

interface StayLegSectionProps {
  leg: StayLeg;
  index: number;
}

function StayLegSection({ leg, index }: StayLegSectionProps) {
  const checkInDate = new Date(leg.check_in).toLocaleDateString();
  const checkOutDate = new Date(leg.check_out).toLocaleDateString();

  return (
    <div className="stay-leg-section">
      <h4 className="leg-title">
        {leg.city}, {leg.country}
      </h4>
      <div className="leg-dates">
        {checkInDate} - {checkOutDate} ({leg.duration_days} nights)
      </div>
      {leg.stay_types_requested.length > 0 && (
        <div className="requested-types">
          Requested: {leg.stay_types_requested.join(", ")}
        </div>
      )}
      {leg.loyalty_programmes.length > 0 && (
        <div className="loyalty-programs">
          Loyalty: {leg.loyalty_programmes.join(", ")}
        </div>
      )}
    </div>
  );
}

export function StayReviewInterrupt() {
    const { interrupt, values, isLive, isStreaming, submit } = useReviewInterrupt("stay_review");
    
    if (!interrupt) {
        return <UnknownInterruptFallback />;
    }

    // Type the values properly
    const typedValues = values as InitialTripState | undefined;
    const stayLegs = typedValues?.stay_legs ?? [];

    const handleApprove = () => submit("approve");
    const handleRequestChanges = (feedback: string) => submit(feedback);

    return (
        <>
            {!isLive && <HistoricalBanner />}
            <ReviewShell 
                title="Review your lodging options" 
                isStreaming={isStreaming}
                onApprove={handleApprove} 
                onRequestChanges={handleRequestChanges}
            >
                <div className="stays-review">
                    <p className="review-message">{interrupt.message}</p>
                    
                    {interrupt.recommendation_reasoning && (
                        <div className="recommendation-reasoning">
                            <h4>Our Recommendation</h4>
                            <p>{interrupt.recommendation_reasoning}</p>
                        </div>
                    )}

                    {stayLegs.map((leg, legIndex) => (
                        <div key={`${leg.city}-${leg.country}-${legIndex}`} className="stay-leg">
                            <StayLegSection leg={leg} index={legIndex} />
                        </div>
                    ))}

                    <div className="stay-options">
                        <h4>Available Options</h4>
                        <ul className="options-list">
                            {interrupt.options.map((option, index) => (
                                <StayOptionCard 
                                    key={`${option.name}-${index}`}
                                    option={option}
                                    index={index}
                                />
                            ))}
                        </ul>
                    </div>
                </div>
            </ReviewShell>
        </>
    );
}
