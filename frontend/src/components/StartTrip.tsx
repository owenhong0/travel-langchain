import {useState, type FormEvent, type KeyboardEvent} from "react";
import {Link} from "react-router-dom";
import {useTripThread} from "../hooks/useTripThread";
import type {InitialTripState} from "../types/orchestrator";
// import {DebugPanel} from "./DebugPanel";
import {FullBleedHero} from "./landing/FullBleedHero";
import backdrop from "../assets/journeyman/vol1/Vol1Page1.jpeg?w=640;1182&format=avif;webp;jpg&quality=70&as=picture";
import backdropPortrait
    from "../assets/journeyman/vol1/Vol1Page1Phone.jpeg?w=750&format=avif;webp;jpg&quality=70&as=picture";
import "./StartTrip.css";

const EMPTY_STATE: InitialTripState = {
    // trip_info_graph fields
    trip_preferences: "",
    max_analysts: 5, // Match backend default
    analysts: [],
    sections: [],
    human_analyst_feedback: "",
    destination_candidates: [],
    finalized_destinations: [],
    review_decision: null,
    ordered_destinations: [],
    order_decision: null,
    order_feedback: null,
    trip_start_date: null,
    trip_end_date: null,
    dated_itinerary: [],
    date_decision: null,
    date_feedback: null,

    // bridge node
    loyalty_programmes: [],

    // leg_transportation_graph fields
    home_city: "",
    home_country: "",
    return_city: "",
    return_country: "",
    legs: [],
    finalized_legs: [],

    // lodging_graph fields
    stay_legs: [],
    finalized_stays: [],
};

export function StartTrip() {
    // const {start, isStreaming, error, threadId, messages, interrupt} = useTripThread();
    const {start, isStreaming, error} = useTripThread();
    const [preferences, setPreferences] = useState("");

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        if (!preferences.trim() || isStreaming) return;
        start({...EMPTY_STATE, trip_preferences: preferences});
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        const isTouch = window.matchMedia("(pointer: coarse)").matches;
        if (e.key === "Enter" && !e.shiftKey && !isTouch && !e.nativeEvent.isComposing) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
        }
    };

    return (
        <FullBleedHero image={backdrop} portrait={backdropPortrait} alt="" blur>
            <div className="prompt">
                <h1 className="prompt__headline">What does the world look like to you?</h1>

                <div className="prompt__body">
                    <form className="prompt__panel" onSubmit={handleSubmit}>
                        <label htmlFor="trip-preferences" className="prompt__label">
                            Describe what you're looking for, e.g.
                        </label>
                        <textarea
                            id="trip-preferences"
                            className="prompt__input"
                            value={preferences}
                            onChange={(e) => setPreferences(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="I want to explore the grasslands of Xinjiang, alpine meadows and remnants of the Silk Road over a few weeks while indulging in local foods and customs. I'd like to keep a strict budget while staying comfortable in hotels and guided tours."
                            rows={4}
                            disabled={isStreaming}
                        />
                        <button type="submit" className="prompt__submit"
                                disabled={isStreaming || !preferences.trim()}>
                            {isStreaming ? "Planning…" : "Go"}
                        </button>
                    </form>

                    {error && <p role="alert" className="prompt__error">{error}</p>}

                    <nav className="prompt__links">
                        {/* "Already have a plan? Log in" — add once accounts exist */}
                        <Link to="/">Not sure yet? Read the issue</Link>
                    </nav>
                </div>
            </div>

            <p className="masthead--small">Journeyman</p>
        </FullBleedHero>
    );
}
