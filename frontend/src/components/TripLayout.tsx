// src/components/TripLayout.tsx
import { Outlet } from "react-router-dom";
import { ReviewTimeline } from "../context/ReviewTimeline";
import "./TripLayout.css";

export function TripLayout() {
    return (
        <div className="trip-layout">
            <aside className="trip-sidebar">
                <ReviewTimeline />
            </aside>
            <main className="trip-content">
                <Outlet />
            </main>
        </div>
    );
}