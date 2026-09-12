import { useNavigate, useParams, useLocation } from "react-router-dom";
import { useTripThreadContext } from "../hooks/useTripThreadContext.ts";
import { useInterruptHistory } from "../hooks/useInterruptHistory.ts";
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
  timestamp?: string;
  status: "completed" | "current" | "pending";
}

// Map interrupt types to human-readable labels
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
  const { history, isStreaming, interrupt } = useTripThreadContext();
  const { threadId } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const currentViewingId = (location.state as LocationState | null)?.viewingCheckpointId;

  // Use local interrupt history instead of thread.history
  const interruptHistory = useInterruptHistory(interrupt, history);
  
  const headCheckpointId = history?.[0]?.checkpoint?.checkpoint_id;
  const currentInterruptType = interrupt?.type;

  // Create timeline steps from local interrupt history
  const timelineSteps: TimelineStep[] = interruptHistory.map((entry, index) => {
    const isHead = entry.type === currentInterruptType;
    const isActive = isHead ? !currentViewingId : entry.rootCheckpointId === currentViewingId;
    
    // Determine status based on position and state
    let status: TimelineStep["status"];
    if (isHead && isStreaming) {
      status = "current";
    } else if (isHead) {
      status = "completed";
    } else {
      status = "completed";
    }

    return {
      checkpointId: entry.rootCheckpointId || headCheckpointId || "",
      type: entry.type,
      route: entry.route,
      isHead,
      isActive,
      timestamp: entry.timestamp,
      status,
    };
  });

  const handleStepClick = (step: TimelineStep) => {
    if (!threadId) return;
    
    // For historical steps (not the current head), we need to pass both checkpoint ID and interrupt type
    // since all interior interrupts share the same checkpoint ID
    navigate(`/trip/${threadId}/${step.route}`, {
      state: step.isHead ? undefined : { 
        viewingCheckpointId: step.checkpointId,
        viewingInterruptType: step.type 
      },
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
            key={`${step.checkpointId}-${step.type}-${index}`}
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
              {step.isHead && (
                <div className="step-badge">Current</div>
              )}
              {step.timestamp && (
                <div className="step-timestamp">
                  {new Date(step.timestamp).toLocaleTimeString([], { 
                    hour: '2-digit', 
                    minute: '2-digit' 
                  })}
                </div>
              )}
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
