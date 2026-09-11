import {useReviewInterrupt} from "../../hooks/useReviewInterrupt.ts";

export function DestinationOrderReview() {
    const {interrupt, isLive, isStreaming, submit} = useReviewInterrupt("order_review");
    if (!interrupt) return null;

    return (
        <div>
            <h2>Review your destination order</h2>
            {!isLive && (
                <p className="history-banner">
                    Viewing a past step — submitting will branch the thread here.
                </p>
            )}
            <p>{interrupt.message}</p>
            <ol>
                {interrupt.ordered_destinations?.map((destination, index) => (
                    <li key={index}>
                        <strong>{destination.city}, {destination.country}</strong>
                        <br />
                        Duration: {destination.recommended_duration_days} days
                        <br />
                        Purpose: {destination.purpose}
                        {destination.is_international_gateway && (
                            <><br /><em>International gateway</em></>
                        )}
                        {destination.requires_flight_or_ferry && (
                            <><br /><em>Requires flight or ferry</em></>
                        )}
                    </li>
                ))}
            </ol>
            <button disabled={isStreaming} onClick={() => submit("approve")}>
                Approve
            </button>
            <button
                disabled={isStreaming}
                onClick={() => {
                    const city = prompt("Which city to drop?");
                    if (city) submit(`drop: ${city}`);
                }}
            >
                Drop a destination
            </button>
        </div>
    );
}
