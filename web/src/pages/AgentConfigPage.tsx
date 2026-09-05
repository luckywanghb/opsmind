import { ActionBadge, StatusBadge, ToolBadge } from "../components/common/Badges";
import { PageHeader } from "../components/common/PageHeader";
import type { AgentAction } from "../types/api";

const actions: AgentAction[] = ["ASK_USER", "SEARCH", "REPLY", "TRANSFER_HUMAN", "END_CONVERSATION"];
const tools = [["WorkOrder Query", "work_order_query"], ["Permission Query", "permission_query"], ["Incident Query", "incident_query"]];

export function AgentConfigPage() {
  return <div className="page page-enter">
    <PageHeader eyebrow="Configuration · Read only" title="Agent 配置" description="查看模型路由、Prompt 契约、动作空间与硬安全边界。" action={<StatusBadge tone="neutral">信息视图</StatusBadge>} />
    <section className="config-section"><div className="section-title"><span>01</span><div><h2>Model Gateway</h2><p>运行时使用逻辑 Profile，具体模型由服务端配置。</p></div></div><div className="profile-list"><article><div><strong>cheap</strong><StatusBadge tone="success">Active</StatusBadge></div><p>常规 Agent 节点的成本优先路由</p><small>Provider · Server configured</small></article><article><div><strong>strong</strong><StatusBadge tone="planned">Planned</StatusBadge></div><p>由评测结果驱动的强模型升级路径</p></article><article><div><strong>fallback</strong><StatusBadge tone="planned">Planned</StatusBadge></div><p>主路由不可用时的显式备用路径</p></article></div></section>
    <section className="config-section"><div className="section-title"><span>02</span><div><h2>Prompt Contracts</h2><p>当前 Agent Kernel 中已实现的模型任务。</p></div></div><div className="prompt-contracts"><article><span>REQUEST_UNDERSTANDING</span><h3>Request Understanding</h3><p>提取 primary_intent、request_type、symptom、entities、risk_signal 与 uncertainty。</p></article><article><span>ACTION_DECISION</span><h3>Action Decision</h3><p>根据 Request Understanding、当前上下文、Action Space 和 Guardrail，决定下一步 Canonical Action。</p></article><article><span>TOOL_SELECTION · TOOL_RESULT_REVIEW</span><h3>Tool Loop</h3><p>由模型选择已注册只读工具，并复核类型化结果后再决定回复、澄清或转人工。</p></article></div></section>
    <section className="config-section two-column"><div><div className="section-title"><span>03</span><div><h2>Canonical Action Space</h2><p>Action 描述下一步意图，不等同于 Node 或 Tool。</p></div></div><div className="action-list">{actions.map((action) => <ActionBadge key={action} action={action} />)}</div></div><div><div className="section-title"><span>04</span><div><h2>Registered Read-only Tools</h2><p>Runtime 当前提供三个类型化只读查询工具；是否调用由模型选择，策略边界由运行时执行。</p></div></div><div className="tool-list">{tools.map(([label, id]) => <div key={id}><span>{label}</span><ToolBadge>{id}</ToolBadge><StatusBadge tone="success">Active</StatusBadge></div>)}</div></div></section>
    <section className="safety-section"><div><span className="eyebrow">Hard safety boundary</span><h2>READ ONLY</h2><p>模型可以建议动作，但不能绕过确定性的运行时能力边界。</p></div><div><h3>允许</h3><p>查询知识 · 查询工单 · 查询权限 · 查询业务数据 · 查询日志 · 查询事故 · 输出建议</p></div><div><h3>禁止</h3><p>修改生产数据 · 修改权限 · 修改配置 · 执行生产脚本 · 重启服务 · 不可逆操作</p></div><div><h3>人工转交</h3><p>大范围异常 · 生产中断 · 安全风险 · 高权限请求 · 超出工具能力 · 无法形成可靠判断</p></div></section>
  </div>;
}
