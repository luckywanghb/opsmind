import type { TraceEntry } from "../../types/api";
import { StatusBadge } from "../common/Badges";
import { Icon } from "../common/Icon";

const taskLabels: Record<string, string> = {
  REQUEST_UNDERSTANDING: "请求理解",
  ACTION_DECISION: "动作决策",
  TOOL_SELECTION: "工具选择",
  TOOL_RESULT_REVIEW: "工具结果复核",
  CLARIFICATION: "澄清问题",
  RESPONSE_GENERATION: "结果与回复",
  HANDOFF_GENERATION: "转人工说明",
};

const nodeLabels: Record<string, string> = {
  select_tool: "工具选择",
  execute_tool: "工具选择与执行",
};

const statusLabels: Record<string, string> = {
  completed: "已完成",
  failed: "失败",
  blocked: "已拦截",
};

export function AgentTracePanel({ trace, onClose }: { trace: TraceEntry[]; onClose: () => void }) {
  const hasTerminal = trace.some((entry) => ["RESPONSE_GENERATION", "CLARIFICATION", "HANDOFF_GENERATION"].includes(entry.task) || entry.node === "close_conversation");
  const incomplete = trace.length > 0 && !hasTerminal;
  return (
    <aside className="trace-panel" aria-label="Agent 运行详情">
      <div className="trace-panel__header">
        <div><span className="eyebrow">Live trace</span><h2>Agent 运行详情</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="关闭 Agent 运行详情"><Icon name="close" /></button>
      </div>
      <div className="trace-list">
        {trace.map((entry, index) => (
          <article className="trace-step" key={`${entry.node}-${index}`}>
            <div className="trace-step__rail"><span>{index + 1}</span></div>
            <div>
              <div className="trace-step__title"><h3>{nodeLabels[entry.node] ?? taskLabels[entry.task] ?? entry.task}</h3><StatusBadge tone={entry.status === "completed" ? "success" : "warning"}>{statusLabels[entry.status] ?? entry.status}</StatusBadge></div>
              <p>{entry.summary}</p>
              <dl><div><dt>节点</dt><dd><code>{entry.node}</code></dd></div><div><dt>模型配置</dt><dd>{entry.profile.toLowerCase()}</dd></div></dl>
            </div>
          </article>
        ))}
        {trace.length === 0 && <p className="muted">提交请求后将显示实际执行节点。</p>}
        {incomplete && <article className="trace-step trace-step--planned">
          <div className="trace-step__rail"><Icon name="clock" /></div>
          <div><div className="trace-step__title"><h3>工具选择与执行</h3><StatusBadge tone="planned">规划中</StatusBadge></div><p>当前运行尚未执行工具。</p></div>
        </article>}
        {incomplete && <article className="trace-step trace-step--planned">
          <div className="trace-step__rail"><Icon name="clock" /></div>
          <div><div className="trace-step__title"><h3>结果与回复</h3><StatusBadge tone="planned">规划中</StatusBadge></div><p>当前响应尚未生成最终回复。</p></div>
        </article>}
      </div>
    </aside>
  );
}
