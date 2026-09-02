import type { TraceEntry } from "../../types/api";
import { StatusBadge } from "../common/Badges";
import { Icon } from "../common/Icon";

const taskLabels: Record<string, string> = {
  REQUEST_UNDERSTANDING: "Request Understanding",
  ACTION_DECISION: "Action Decision",
};

export function AgentTracePanel({ trace, onClose }: { trace: TraceEntry[]; onClose: () => void }) {
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
              <div className="trace-step__title"><h3>{taskLabels[entry.task] ?? entry.task}</h3><StatusBadge tone="success">Completed</StatusBadge></div>
              <p>{entry.summary}</p>
              <dl><div><dt>Node</dt><dd><code>{entry.node}</code></dd></div><div><dt>Profile</dt><dd>{entry.profile.toLowerCase()}</dd></div></dl>
            </div>
          </article>
        ))}
        {trace.length === 0 && <p className="muted">提交请求后将显示实际执行节点。</p>}
        <article className="trace-step trace-step--planned">
          <div className="trace-step__rail"><Icon name="clock" /></div>
          <div><div className="trace-step__title"><h3>Tool Selection & Execution</h3><StatusBadge tone="planned">Planned</StatusBadge></div><p>Phase 1 尚未接入 Tool Runtime。</p></div>
        </article>
        <article className="trace-step trace-step--planned">
          <div className="trace-step__rail"><Icon name="clock" /></div>
          <div><div className="trace-step__title"><h3>Result & Reply</h3><StatusBadge tone="planned">Planned</StatusBadge></div><p>当前响应止于 Action Decision，不生成业务答案。</p></div>
        </article>
      </div>
    </aside>
  );
}
