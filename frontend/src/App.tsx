// src/App.tsx
import { BrowserRouter, Routes, Route, Outlet } from "react-router-dom";
import { TripThreadProvider } from "./context/TripThreadProvider";
import { StartTrip } from "./components/StartTrip";
import { TripSummary } from "./components/TripSummary";
import { HumanFeedbackInterrupt } from "./components/interrupts/HumanFeedbackInterrupt";
import { OrderReviewInterrupt } from "./components/interrupts/OrderReviewInterrupt";
import { StartDateRequestInterrupt } from "./components/interrupts/StartDateRequestInterrupt";
import { DateReviewInterrupt } from "./components/interrupts/DateReviewInterrupt";
import { LoyaltyProgrammesRequestInterrupt } from "./components/interrupts/LoyaltyProgrammesRequestInterrupt";
import { HomeContextRequestInterrupt } from "./components/interrupts/HomeContextRequestInterrupt";
import { TransportModeReviewInterrupt } from "./components/interrupts/TransportModeReviewInterrupt";
import { StayReviewInterrupt } from "./components/interrupts/StayReviewInterrupt";
import { StayTypeReviewInterrupt } from "./components/interrupts/StayTypeReviewInterrupt";
import "./App.css";

export default function App() {
    return (
        <BrowserRouter>
            <Routes>
                {/* Home route - start a new trip */}
                <Route path="/" element={<StartTrip />} />
                
                {/* Trip routes with thread context */}
                <Route path="/trip/:threadId" element={<TripThreadProvider><Outlet /></TripThreadProvider>}>
                    <Route path="analysts" element={<HumanFeedbackInterrupt />} />
                    <Route path="destinations" element={<OrderReviewInterrupt />} />
                    <Route path="dates/range" element={<StartDateRequestInterrupt />} />
                    <Route path="dates/review" element={<DateReviewInterrupt />} />
                    <Route path="loyalty" element={<LoyaltyProgrammesRequestInterrupt />} />
                    <Route path="home-context" element={<HomeContextRequestInterrupt />} />
                    <Route path="transport" element={<TransportModeReviewInterrupt />} />
                    <Route path="stays/types" element={<StayTypeReviewInterrupt />} />
                    <Route path="stays" element={<StayReviewInterrupt />} />
                    <Route path="summary" element={<TripSummary />} />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}