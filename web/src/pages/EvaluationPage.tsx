import { ActionBadge, StatusBadge, ToolBadge } from "../components/common/Badges";
import { PageHeader } from "../components/common/PageHeader";
import { evaluationCases } from "../demo/fixtures";

export function EvaluationPage() {
  return <div className="page page-enter">
    <PageHeader eyebrow="Golden Cases · Demo fixture" title="运行与评测" description="检查 Canonical Action 与 Tool 选择的预期一致性。" action={<button className="primary-button" disabled>运行评测 · Planned</button>} />
    <div className="metric-strip"><div><span>Golden Cases</span><strong>8</strong></div><div><span>Passed</span><strong>7</strong></div><div><span>Failed</span><strong>1</strong></div><div><span>Pass Rate</span><strong>87.5%</strong></div><p>设计演示数据，不代表生产遥测</p></div>
    <div className="evaluation-table"><div className="evaluation-head"><span>Case</span><span>Expected</span><span>Actual</span><span>Status</span></div>{evaluationCases.map((item) => <article key={item.id} className="evaluation-row"><div><small>{item.id}</small><strong>{item.title}</strong></div><div><ActionBadge action={item.expectedAction} />{item.expectedTool === "—" ? <span>—</span> : <ToolBadge>{item.expectedTool}</ToolBadge>}</div><div><ActionBadge action={item.actualAction} />{item.actualTool === "—" ? <span>—</span> : <ToolBadge>{item.actualTool}</ToolBadge>}</div><StatusBadge tone={item.status === "Passed" ? "success" : "warning"}>{item.status}</StatusBadge></article>)}</div>
  </div>;
}
