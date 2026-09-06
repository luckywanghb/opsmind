import type { AgentAction } from "../types/api";

export interface SopFixture {
  id: string;
  title: string;
  category: string;
  summary: string;
  scenarios: string[];
  actions: AgentAction[];
  steps: string[];
  documents: string[];
  owner: string;
  updatedAt: string;
}

export const sops: SopFixture[] = [
  { id: "work-order-submit", title: "工单无法提交排查 SOP", category: "EquipFlow · 工单", summary: "用于定位字段校验、状态约束与流程配置导致的提交失败。", scenarios: ["提交按钮不可用", "提交后出现字段校验错误", "流程未正常发起"], actions: ["ASK_USER", "SEARCH", "TRANSFER_HUMAN"], steps: ["确认工单编号、当前状态与错误提示", "检查必填字段与字段格式", "通过 work_order_query 查询流程状态", "整理已确认事实与未决问题"], documents: ["EquipFlow 工单字段规范", "流程发起常见错误码"], owner: "Ops Knowledge Team", updatedAt: "2026-08-28" },
  { id: "menu-permission", title: "菜单权限异常排查", category: "IAM · 权限", summary: "区分角色配置、站点范围与账号同步问题。", scenarios: ["菜单不可见", "同岗账号权限不一致"], actions: ["ASK_USER", "SEARCH", "TRANSFER_HUMAN"], steps: ["收集账号与菜单信息", "确认站点与角色范围", "查询只读权限快照"], documents: ["IAM 角色映射说明"], owner: "IAM Operations", updatedAt: "2026-08-20" },
  { id: "stale-device-data", title: "设备数据未更新常见原因", category: "EquipFlow · 数据", summary: "排查采集链路、时间窗口与展示缓存造成的数据延迟。", scenarios: ["设备数据长时间不更新"], actions: ["ASK_USER", "SEARCH"], steps: ["确认设备与时间范围", "查询日志与事故记录", "汇总可验证证据"], documents: ["设备数据链路说明"], owner: "Data Platform", updatedAt: "2026-08-15" },
];
