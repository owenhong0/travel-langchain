// src/components/interrupts/HumanFeedbackInterrupt.tsx
import meadow from "../../assets/journeyman/vol1/Meadow.jpeg?w=1280;1920&format=avif;webp;jpg&quality=80&as=picture";
import { useReviewInterrupt } from "../../hooks/useReviewInterrupt";
import { normalizeAnalyst } from "../../lib/analysts";
import { FullBleedHero } from "../landing/FullBleedHero";
import { AnalystsPage } from "../analysts/AnalystsPage.tsx";
import { HistoricalBanner } from "../HistoricalBanner";
import { ProcessingState } from "../ProcessingState";
import { UnknownInterruptFallback } from "./UnknownInterruptFallback";

export function HumanFeedbackInterrupt() {
    const { interrupt, isLive, isStreaming, isProcessing, isUnexpected, submit } =
        useReviewInterrupt("human_feedback");

    if (isProcessing) return <ProcessingState />;
    if (isUnexpected || !interrupt) return <UnknownInterruptFallback />;

    const analysts = interrupt.analysts.map(normalizeAnalyst);

    return (
        <div className="analysts-screen">
            {!isLive && <HistoricalBanner />}
            <FullBleedHero image={meadow} alt="Dandelions and grass in a meadow">
                {/* key = analyst names → a regenerated panel remounts with an empty notes list */}
                <AnalystsPage
                    key={analysts.map(a => a.persona_name).join("|")}
                    analysts={analysts}
                    isStreaming={isStreaming}
                    onSubmit={(value) => void submit(value)}
                />
            </FullBleedHero>
        </div>
    );
}