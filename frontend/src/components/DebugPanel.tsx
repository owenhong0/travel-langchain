// src/components/DebugPanel.tsx

interface DebugPanelProps {
  isLoading: boolean;
  messagesLength: number;
  interruptType?: string;
  threadId?: string | null;
  error?: string | null;
}

export function DebugPanel({ isLoading, messagesLength, interruptType, threadId, error }: DebugPanelProps) {
  return (
    <div style={{
      position: "fixed",
      top: "10px",
      right: "10px",
      background: "#f0f0f0",
      border: "1px solid #ccc",
      padding: "10px",
      borderRadius: "5px",
      fontSize: "12px",
      fontFamily: "monospace",
      zIndex: 1000,
      minWidth: "200px"
    }}>
      <h4 style={{ margin: "0 0 8px 0", fontSize: "14px" }}>Debug Panel</h4>
      <div><strong>Thread ID:</strong> {threadId || "None"}</div>
      <div><strong>Is Loading:</strong> {isLoading ? "✅ Yes" : "❌ No"}</div>
      <div><strong>Messages:</strong> {messagesLength}</div>
      <div><strong>Interrupt:</strong> {interruptType || "None"}</div>
      {error && <div style={{ color: "red" }}><strong>Error:</strong> {error}</div>}
    </div>
  );
}