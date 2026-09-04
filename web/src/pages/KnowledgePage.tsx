import { Link } from "react-router-dom";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/Badges";
import { Icon } from "../components/common/Icon";
import { sops } from "../demo/fixtures";

export function KnowledgePage() {
  return <div className="page page-enter">
    <PageHeader eyebrow="Demo fixtures · Read only" title="SOP / 知识库" description="浏览可供未来 Knowledge Search 使用的结构化运维知识。" action={<div className="header-actions"><button className="secondary-button" disabled>导入文档 · Planned</button><button className="primary-button" disabled>新建 SOP · Planned</button></div>} />
    <div className="knowledge-toolbar"><div className="search-shell"><Icon name="search" /><span>搜索 SOP 标题、系统或场景</span></div><span><strong>{sops.length}</strong> 条 Demo 内容</span></div>
    <div className="knowledge-list">
      <div className="knowledge-list__head"><span>名称</span><span>适用域</span><span>状态</span><span>更新日期</span><span /></div>
      {sops.map((sop) => <Link to={`/knowledge/${sop.id}`} key={sop.id} className="knowledge-row"><div><strong>{sop.title}</strong><p>{sop.summary}</p></div><span>{sop.category}</span><StatusBadge tone="neutral">Demo</StatusBadge><span>{sop.updatedAt}</span><Icon name="chevron" /></Link>)}
    </div>
  </div>;
}
