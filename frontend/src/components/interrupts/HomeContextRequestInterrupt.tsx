// src/components/interrupts/HomeContextRequestInterrupt.tsx  (route: home-context)
import { useState } from "react";
import { useTripThreadContext } from "../../hooks/useTripThreadContext";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";

export function HomeContextRequestInterrupt() {
    const [homeCity, setHomeCity] = useState("");
    const [homeCountry, setHomeCountry] = useState("");
    const [returnCity, setReturnCity] = useState("");
    const [returnCountry, setReturnCountry] = useState("");
    const { interrupt, resume, isStreaming } = useTripThreadContext();
    
    if (interrupt?.type !== "home_context_request") return <UnknownInterruptFallback />;

    const handleSubmit = () => {
        if (!homeCity || !homeCountry) return;
        // Backend expects a simple string format with the location info
        const returnLocation = returnCity && returnCountry ? `${returnCity}, ${returnCountry}` : `${homeCity}, ${homeCountry}`;
        resume(`${homeCity}, ${homeCountry} | return: ${returnLocation}`);
    };

    return (
        <section>
            <h1>Where are you traveling from?</h1>
            <label>Home city <input value={homeCity} onChange={(e) => setHomeCity(e.target.value)} disabled={isStreaming} /></label>
            <label>Home country <input value={homeCountry} onChange={(e) => setHomeCountry(e.target.value)} disabled={isStreaming} /></label>
            <label>Returning to a different city? <input value={returnCity} onChange={(e) => setReturnCity(e.target.value)} placeholder="Same as home city" disabled={isStreaming} /></label>
            <label>Return country <input value={returnCountry} onChange={(e) => setReturnCountry(e.target.value)} placeholder="Same as home country" disabled={isStreaming} /></label>
            <button onClick={handleSubmit} disabled={isStreaming || !homeCity || !homeCountry}>Continue</button>
        </section>
    );
}