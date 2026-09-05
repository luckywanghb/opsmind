"""Deterministic synthetic enterprise adapters for the V0.1 demo.

The dictionaries below are adapter data, not Agent routing.  The graph never
inspects an intent, query string or identifier to pick a capability; a model
selects a registered tool and the adapter simply looks up the supplied typed
arguments.  Unknown records always produce typed ``not_found`` results.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from opsmind.tools.contracts import (
    IncidentQueryRequest,
    IncidentQueryResponse,
    PermissionQueryRequest,
    PermissionQueryResponse,
    ToolFieldPresentation,
    ToolFieldValueKind,
    ToolResultStatus,
    WorkOrderQueryRequest,
    WorkOrderQueryResponse,
)
from opsmind.tools.registry import (
    RegisteredTool,
    ToolHandler,
    ToolMode,
    ToolRegistry,
    ToolSpec,
)

WORK_ORDER_QUERY_NAME = "work_order_query"
PERMISSION_QUERY_NAME = "permission_query"
INCIDENT_QUERY_NAME = "incident_query"


def _field(
    label_zh: str,
    *,
    label_en: str | None = None,
    unit_zh: str | None = None,
    unit_en: str | None = None,
    value_kind: ToolFieldValueKind = ToolFieldValueKind.TEXT,
    semantic: str = "fact",
) -> ToolFieldPresentation:
    """Declare localized presentation metadata for a typed source field."""

    return ToolFieldPresentation(
        label_zh=label_zh,
        label_en=label_en,
        unit_zh=unit_zh,
        unit_en=unit_en,
        value_kind=value_kind,
        semantic=semantic,
    )


_WORK_ORDER_PRESENTATION: Mapping[str, ToolFieldPresentation] = MappingProxyType(
    {
        "result_status": _field(
            "查询结果状态",
            label_en="Result status",
            value_kind=ToolFieldValueKind.ENUM,
            semantic="result_status",
        ),
        "work_order_id": _field(
            "工单编号",
            label_en="Work order ID",
            value_kind=ToolFieldValueKind.IDENTIFIER,
        ),
        "status": _field(
            "状态",
            label_en="Status",
            value_kind=ToolFieldValueKind.ENUM,
            semantic="status",
        ),
        "current_node": _field(
            "当前节点",
            label_en="Current node",
            semantic="fact",
        ),
        "current_handler": _field(
            "当前处理人",
            label_en="Current handler",
            value_kind=ToolFieldValueKind.IDENTIFIER,
            semantic="owner",
        ),
        "waiting_hours": _field(
            "已等待",
            label_en="Elapsed waiting",
            unit_zh=" 小时",
            unit_en="hours",
            value_kind=ToolFieldValueKind.NUMBER,
            semantic="duration",
        ),
        "abnormal": _field(
            "源异常标记",
            label_en="Source anomaly flag",
            value_kind=ToolFieldValueKind.BOOLEAN,
            semantic="source_flag",
        ),
    }
)

_PERMISSION_PRESENTATION: Mapping[str, ToolFieldPresentation] = MappingProxyType(
    {
        "result_status": _field(
            "查询结果状态",
            label_en="Result status",
            value_kind=ToolFieldValueKind.ENUM,
            semantic="result_status",
        ),
        "user_id": _field(
            "用户标识",
            label_en="User ID",
            value_kind=ToolFieldValueKind.IDENTIFIER,
        ),
        "system_id": _field(
            "系统标识",
            label_en="System ID",
            value_kind=ToolFieldValueKind.IDENTIFIER,
        ),
        "roles": _field(
            "角色",
            label_en="Roles",
            value_kind=ToolFieldValueKind.LIST,
            semantic="role",
        ),
        "permissions": _field(
            "已分配权限",
            label_en="Permissions",
            value_kind=ToolFieldValueKind.LIST,
            semantic="permission",
        ),
        "missing_permissions": _field(
            "缺失权限",
            label_en="Missing permissions",
            value_kind=ToolFieldValueKind.LIST,
            semantic="missing_permission",
        ),
    }
)

_INCIDENT_PRESENTATION: Mapping[str, ToolFieldPresentation] = MappingProxyType(
    {
        "result_status": _field(
            "查询结果状态",
            label_en="Result status",
            value_kind=ToolFieldValueKind.ENUM,
            semantic="result_status",
        ),
        "system_id": _field(
            "系统标识",
            label_en="System ID",
            value_kind=ToolFieldValueKind.IDENTIFIER,
        ),
        "site": _field("站点", label_en="Site", semantic="scope"),
        "site_id": _field(
            "站点标识",
            label_en="Site ID",
            value_kind=ToolFieldValueKind.IDENTIFIER,
            semantic="scope",
        ),
        "scope": _field("查询范围", label_en="Scope", semantic="scope"),
        "incident_id": _field(
            "事件编号",
            label_en="Incident ID",
            value_kind=ToolFieldValueKind.IDENTIFIER,
        ),
        "incident_status": _field(
            "事件状态",
            label_en="Incident status",
            value_kind=ToolFieldValueKind.ENUM,
            semantic="status",
        ),
        "impact": _field("影响描述", label_en="Impact", semantic="impact"),
    }
)


# MappingProxyType prevents accidental mutation of module-level fixtures.  A
# future adapter can replace these data sources without changing tool or graph
# contracts.
_WORK_ORDER_DATA: Mapping[str, Mapping[str, object]] = MappingProxyType(
    {
        "WO20260001": MappingProxyType(
            {
                "status": "APPROVING",
                "current_node": "设备主管审批",
                "current_handler": "U10108",
                "waiting_hours": 4,
                "abnormal": False,
            }
        )
    }
)

_PERMISSION_DATA: Mapping[tuple[str, str], Mapping[str, object]] = MappingProxyType(
    {
        ("U10023", "EquipFlow"): MappingProxyType(
            {
                "roles": ("EQUIPMENT_VIEWER",),
                "permissions": ("EQUIPMENT_VIEW",),
                "missing_permissions": ("EQUIPMENT_LEDGER_VIEW",),
            }
        )
    }
)

_INCIDENT_DATA: Mapping[tuple[str | None, str | None], Mapping[str, object]] = (
    MappingProxyType(
        {
            ("EquipFlow", "星川基地"): MappingProxyType(
                {
                    "incident_id": "INC20260904001",
                    "incident_status": "ACTIVE",
                    "impact": "星川基地用户无法访问 EquipFlow",
                }
            )
        }
    )
)


def _fixture_texts(value: object) -> list[str]:
    """Validate and copy a string-list fixture from immutable adapter data."""

    if not isinstance(value, (list, tuple)):
        raise TypeError("synthetic permission fixture lists are malformed")
    return [str(item) for item in value]


async def work_order_query(
    request: WorkOrderQueryRequest,
) -> WorkOrderQueryResponse:
    """Return one work-order snapshot or a typed not-found result."""

    record = _WORK_ORDER_DATA.get(request.work_order_id)
    if record is None:
        return WorkOrderQueryResponse(
            result_status=ToolResultStatus.NOT_FOUND,
            work_order_id=request.work_order_id,
            message="未找到对应工单记录。",
        )
    waiting_hours = record["waiting_hours"]
    if not isinstance(waiting_hours, (int, float)):
        raise TypeError("synthetic waiting_hours fixture must be numeric")
    return WorkOrderQueryResponse(
        result_status=ToolResultStatus.FOUND,
        work_order_id=request.work_order_id,
        status=str(record["status"]),
        current_node=str(record["current_node"]),
        current_handler=str(record["current_handler"]),
        waiting_hours=float(waiting_hours),
        abnormal=bool(record["abnormal"]),
        message="已找到工单状态快照。",
    )


async def permission_query(
    request: PermissionQueryRequest,
) -> PermissionQueryResponse:
    """Return one permission snapshot or a typed not-found result."""

    record = _PERMISSION_DATA.get((request.user_id, request.system_id))
    if record is None:
        return PermissionQueryResponse(
            result_status=ToolResultStatus.NOT_FOUND,
            user_id=request.user_id,
            system_id=request.system_id,
            message="未找到对应用户或系统的权限快照。",
        )
    return PermissionQueryResponse(
        result_status=ToolResultStatus.FOUND,
        user_id=request.user_id,
        system_id=request.system_id,
        roles=_fixture_texts(record["roles"]),
        permissions=_fixture_texts(record["permissions"]),
        missing_permissions=_fixture_texts(record["missing_permissions"]),
        message="已找到权限快照。",
    )


def _incident_key(request: IncidentQueryRequest) -> tuple[str | None, str | None]:
    """Normalize equivalent typed scope fields for adapter lookup only."""

    site = request.site or request.site_id
    return request.system_id, site


async def incident_query(
    request: IncidentQueryRequest,
) -> IncidentQueryResponse:
    """Return a known site/system incident or a typed not-found result."""

    record = _INCIDENT_DATA.get(_incident_key(request))
    if record is None:
        return IncidentQueryResponse(
            result_status=ToolResultStatus.NOT_FOUND,
            system_id=request.system_id,
            site=request.site,
            site_id=request.site_id,
            scope=request.scope,
            message="未找到匹配的事件记录。",
        )
    return IncidentQueryResponse(
        result_status=ToolResultStatus.FOUND,
        system_id=request.system_id,
        site=request.site or request.site_id,
        site_id=request.site_id,
        scope=request.scope,
        incident_id=str(record["incident_id"]),
        incident_status=str(record["incident_status"]),
        impact=str(record["impact"]),
        message="已找到事件记录。",
    )


def _registration(
    *,
    name: str,
    description: str,
    request_model: type[
        WorkOrderQueryRequest | PermissionQueryRequest | IncidentQueryRequest
    ],
    response_model: type[
        WorkOrderQueryResponse | PermissionQueryResponse | IncidentQueryResponse
    ],
    handler: ToolHandler,
    field_presentations: Mapping[str, ToolFieldPresentation],
) -> RegisteredTool:
    return RegisteredTool(
        spec=ToolSpec(
            name=name,
            description=description,
            mode=ToolMode.READ_ONLY,
            field_presentations=dict(field_presentations),
        ),
        request_model=request_model,
        response_model=response_model,
        handler=handler,
    )


@dataclass(frozen=True, slots=True)
class SyntheticToolAdapters:
    """Adapter bundle useful for dependency injection and test isolation."""

    work_order_query: ToolHandler = work_order_query
    permission_query: ToolHandler = permission_query
    incident_query: ToolHandler = incident_query

    def registry(self) -> ToolRegistry:
        """Build a fresh registry containing only the three V0.1 tools."""

        return ToolRegistry(
            [
                _registration(
                    name=WORK_ORDER_QUERY_NAME,
                    description=(
                        "查询一个工单的当前状态、审批节点、处理人、等待时长和异常标记。"
                    ),
                    request_model=WorkOrderQueryRequest,
                    response_model=WorkOrderQueryResponse,
                    handler=self.work_order_query,
                    field_presentations=_WORK_ORDER_PRESENTATION,
                ),
                _registration(
                    name=PERMISSION_QUERY_NAME,
                    description=(
                        "查询指定用户在指定系统中的只读角色、权限和缺失权限事实。"
                    ),
                    request_model=PermissionQueryRequest,
                    response_model=PermissionQueryResponse,
                    handler=self.permission_query,
                    field_presentations=_PERMISSION_PRESENTATION,
                ),
                _registration(
                    name=INCIDENT_QUERY_NAME,
                    description=(
                        "按系统和站点或范围查询已记录的事件、影响范围和状态。"
                    ),
                    request_model=IncidentQueryRequest,
                    response_model=IncidentQueryResponse,
                    handler=self.incident_query,
                    field_presentations=_INCIDENT_PRESENTATION,
                ),
            ]
        )


def build_default_tool_registry() -> ToolRegistry:
    """Return a fresh synthetic read-only registry for one Agent runtime."""

    return SyntheticToolAdapters().registry()


__all__ = [
    "INCIDENT_QUERY_NAME",
    "PERMISSION_QUERY_NAME",
    "WORK_ORDER_QUERY_NAME",
    "SyntheticToolAdapters",
    "build_default_tool_registry",
    "incident_query",
    "permission_query",
    "work_order_query",
]
