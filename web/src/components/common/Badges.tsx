import type { AgentAction } from "../../types/api";

export function StatusBadge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "success" | "planned" | "warning" | "neutral" }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function ActionBadge({ action }: { action: AgentAction }) {
  return <span className="action-badge">{action}</span>;
}

export function ToolBadge({ children }: { children: React.ReactNode }) {
  return <code className="tool-badge">{children}</code>;
}
