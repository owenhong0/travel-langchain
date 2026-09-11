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
  const { history, isStreaming } = useTripThreadContext();
  const { threadId } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const currentViewingId = (location.state as LocationState | null)?.viewingCheckpointId;

  // Filter and process timeline steps with better typing
  const reviewStages = (history ?? []).filter((snap) =>
    snap.tasks.some((task) =>
      task.interrupts.some((interrupt) => {
        const interruptValue = interrupt.value as Interrupt | undefined;
        return interruptValue?.type !== undefined && interruptValue.type in ROUTE_FOR_INTERRUPT;
      })
    )
  );

  const headCheckpointId = history?.[0]?.checkpoint?.checkpoint_id;

  // Create timeline steps with proper typing
  const timelineSteps: TimelineStep[] = [...reviewStages]
    .reverse()
    .map((snap) => {
      const checkpointId = snap.checkpoint?.checkpoint_id;
      const interruptValue = snap.tasks[0]?.interrupts[0]?.value as Interrupt | undefined;
      const type = interruptValue?.type;
      
      if (!type || !checkpointId || !(type in ROUTE_FOR_INTERRUPT)) {
        return null;
      }

      const route = ROUTE_FOR_INTERRUPT[type];
      const isHead = checkpointId === headCheckpointId;
      const isActive = isHead ? !currentViewingId : checkpointId === currentViewingId;
      
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
        checkpointId,
        type,
        route,
        isHead,
        isActive,
        timestamp: snap.created_at,
        status,
      };
    })
    .filter((step): step is TimelineStep => step !== null);

  const handleStepClick = (step: TimelineStep) => {
    if (!threadId) return;
    
    navigate(`/trip/${threadId}/${step.route}`, {
      state: step.isHead ? undefined : { viewingCheckpointId: step.checkpointId },
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
            key={step.checkpointId}
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
