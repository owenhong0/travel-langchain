// src/App.tsx
import {BrowserRouter, Routes, Route} from "react-router-dom";
import {TripThreadProvider} from "./context/TripThreadProvider";
import {DestinationOrderReview} from "./components/interrupts/DestinationOrderReview";
import "./App.css";
import {StartTrip} from "./components/StartTrip.tsx";

export default function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<StartTrip/>}/>
                <Route
                    path="/trip/:threadId/*"
                    element={
                        <TripThreadProvider>
                            <Routes>
                                <Route path="destinations" element={<DestinationOrderReview/>}/>
                                {/* remaining 7 interrupt routes go here as you build them:
                    analysts, dates/range, dates/review, loyalty,
                    home-context, transport, stays, summary */}
                            </Routes>
                        </TripThreadProvider>
                    }
                />
            </Routes>
        </BrowserRouter>
    );
}