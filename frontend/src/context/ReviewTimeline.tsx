import { useNavigate, useParams, useLocation } from "react-router-dom";
import { useTripThreadContext } from "../hooks/useTripThreadContext.ts";
import type { Interrupt } from "../types/orchestrator.ts";
import { ROUTE_FOR_INTERRUPT } from "../lib/interruptRoutes.ts";

interface LocationState {
  viewingCheckpointId?: string;
}

interface TimelineStep {
  checkpointId: string;
  type: Interrupt["type"];
  route: string;
  isHead: boolean;
  isActive: boolean;
  status: "completed" | "current" | "pending";
}

const INTERRUPT_LABELS: Record<Interrupt["type"], string> = {
  human_feedback: "Human Feedback",
  review_destinations: "Review Destinations",
  order_review: "Order Review",
  start_date_request: "Start Date",
  date_review: "Date Review",
  loyalty_programmes_request: "Loyalty Programs",
  home_context_request: "Home Context",
  transport_mode_review: "Transport Mode",
  leg_transport_review: "Transport Options",
  stay_type_review: "Stay Type",
  stay_review: "Accommodation",
};

export function ReviewTimeline() {
  const { interruptHistory, isStreaming, interrupt } = useTripThreadContext();
  const { threadId } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const currentViewingId = (location.state as LocationState | null)?.viewingCheckpointId;

  // checkpoint_id is ULID-based, so a lexical sort is also a chronological sort.
  const sortedHistory = [...interruptHistory].sort((a, b) =>
    a.checkpoint_id.localeCompare(b.checkpoint_id)
  );

  const timelineSteps: TimelineStep[] = sortedHistory.map((entry, index) => {
    const isLastEntry = index === sortedHistory.length - 1;
    // The most recent checkpoint is "current" only if its type still matches
    // the live interrupt — guards against a stale last-entry right after a
    // resume, before the next fetch has caught up.
    const isHead = isLastEntry && entry.interrupt_type === interrupt?.type;
    const isActive = isHead ? !currentViewingId : entry.checkpoint_id === currentViewingId;
    const status: TimelineStep["status"] = isHead && isStreaming ? "current" : "completed";

    return {
      checkpointId: entry.checkpoint_id,
      type: entry.interrupt_type as Interrupt["type"],
      route: ROUTE_FOR_INTERRUPT[entry.interrupt_type as keyof typeof ROUTE_FOR_INTERRUPT],
      isHead,
      isActive,
      status,
    };
  });

  const handleStepClick = (step: TimelineStep) => {
    if (!threadId) return;
    navigate(`/trip/${threadId}/${step.route}`, {
      state: step.isHead
        ? undefined
        : { viewingCheckpointId: step.checkpointId, viewingInterruptType: step.type },
    });
  };

  return (
    <nav className="review-timeline" role="navigation" aria-label="Trip progress timeline">
      <div className="timeline-header">
        <h3>Trip Progress</h3>
        {isStreaming && (
          <div className="timeline-status">
            <div className="streaming-indicator" />
            <span className="status-text">Processing...</span>
          </div>
        )}
      </div>

      <div className="timeline-steps">
        {timelineSteps.map((step, index) => (
          <button
            key={`${step.checkpointId}-${step.type}`}
            type="button"
            className={[
              "timeline-step",
              `timeline-step--${step.status}`,
              step.isActive && "timeline-step--active",
              step.isHead && "timeline-step--head",
            ].filter(Boolean).join(" ")}
            onClick={() => handleStepClick(step)}
            aria-current={step.isActive ? "step" : undefined}
            title={`${INTERRUPT_LABELS[step.type]}${step.isHead ? " (current)" : ""}`}
          >
            <div className="step-indicator">
              <div className="step-dot" />
              {index < timelineSteps.length - 1 && <div className="step-connector" />}
            </div>
            <div className="step-content">
              <div className="step-label">
                {INTERRUPT_LABELS[step.type] || step.type}
              </div>
              {step.isHead && <div className="step-badge">Current</div>}
            </div>
          </button>
        ))}
      </div>

      {timelineSteps.length === 0 && (
        <div className="timeline-empty">
          <p>No review steps yet</p>
        </div>
      )}
    </nav>
  );
}