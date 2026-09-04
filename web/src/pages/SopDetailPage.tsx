import { Link, useParams } from "react-router-dom";
import { ActionBadge, StatusBadge } from "../components/common/Badges";
import { Icon } from "../components/common/Icon";
import { sops } from "../demo/fixtures";

export function SopDetailPage() {
  const { id } = useParams();
  const sop = sops.find((item) => item.id === id) ?? sops[0];
  return <div className="page page-enter sop-detail">
    <Link to="/knowledge" className="back-link">← 返回 SOP / 知识库</Link>
    <header className="sop-hero"><div><span className="eyebrow">{sop.category}</span><h1>{sop.title}</h1><p>{sop.summary}</p></div><StatusBadge tone="neutral">Demo · Read only</StatusBadge></header>
    <div className="sop-layout"><div className="sop-main"><section><h2>适用场景</h2><ul className="plain-list">{sop.scenarios.map((item) => <li key={item}><Icon name="check" />{item}</li>)}</ul></section><section><h2>可触发动作</h2><div className="action-list">{sop.actions.map((action) => <ActionBadge key={action} action={action} />)}</div></section><section><h2>结构化处理步骤</h2><ol className="steps">{sop.steps.map((step, index) => <li key={step}><span>{String(index + 1).padStart(2, "0")}</span><p>{step}</p></li>)}</ol></section><blockquote>若 Agent 无法形成可靠判断，则生成标准化排查摘要，并建议转交 L2/L3 人工运维专家。</blockquote></div><aside className="sop-meta"><section><h3>关联知识文档</h3>{sop.documents.map((document) => <div className="document-link" key={document}><Icon name="book" /><span>{document}<small>Demo reference</small></span></div>)}</section><section><h3>SOP Metadata</h3><dl><div><dt>Owner</dt><dd>{sop.owner}</dd></div><div><dt>Updated</dt><dd>{sop.updatedAt}</dd></div><div><dt>Mode</dt><dd>READ_ONLY</dd></div></dl></section></aside></div>
  </div>;
}
