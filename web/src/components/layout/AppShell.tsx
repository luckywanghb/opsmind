import { NavLink, Outlet } from "react-router-dom";
import { Icon } from "../common/Icon";

const items = [
  { to: "/chat", label: "对话调试", icon: "chat" as const },
  { to: "/agent", label: "Agent 配置", icon: "sliders" as const },
  { to: "/knowledge", label: "SOP / 知识库", icon: "book" as const },
  { to: "/evaluation", label: "运行与评测", icon: "chart" as const },
];

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark"><Icon name="bot" /></span>
          <span><strong>OpsMind</strong><small>智能运维 Agent</small></span>
        </div>
        <nav aria-label="主导航">
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div><span className="status-dot" /> Agent Online</div>
          <div><span>环境</span><strong>Demo</strong></div>
          <div><span>能力边界</span><strong>Read Only</strong></div>
        </div>
      </aside>
      <main className="workspace"><Outlet /></main>
    </div>
  );
}
