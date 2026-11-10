"""Per-target MCP tool capabilities (narrow-only).

The MCP tool inventory stays fixed. Operators may disable tools on a target;
they cannot add tools or relax protocol / dangerous guards in ``forbidden.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dr_panda_mcp import errors
from dr_panda_mcp.store.protocol import Target

ENABLED_TOOLS_KEY = "enabled_tools"

# Option keys rendered in the capability panel (not in connection/scope grids).
CAPABILITY_OPTION_KEYS = frozenset({"allow_processlist", "allow_console"})


@dataclass(frozen=True)
class Capability:
    """One MCP tool offered for a target type."""

    tool: str
    summary: str  # Chinese UI source string (translated via t())
    summary_en: str  # English text for MCP / systems_status
    protocol: tuple[str, ...] = ()
    # When set, enablement is stored on this bool option (default off / risk).
    risk_option: str | None = None


def _cap(
    tool: str,
    summary: str,
    summary_en: str,
    protocol: tuple[str, ...] = (),
    *,
    risk_option: str | None = None,
) -> Capability:
    return Capability(tool, summary, summary_en, protocol, risk_option)


_CATALOG: dict[str, tuple[Capability, ...]] = {
    "mysql": (
        _cap("mysql_tables", "列出授权库中的表", "List tables in an authorized database", ("SHOW TABLES",)),
        _cap(
            "mysql_describe",
            "查看单表的列与索引",
            "Describe columns and indexes for one table",
            ("SHOW FULL COLUMNS", "SHOW INDEX"),
        ),
        _cap(
            "mysql_query",
            "执行单条只读 SQL",
            "Run a single read-only SQL statement",
            ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN"),
        ),
        _cap("mysql_explain", "解释只读 SQL 的执行计划", "Explain a read-only SQL statement", ("EXPLAIN",)),
        _cap(
            "mysql_processlist",
            "查看进程列表（可能看到其他会话）",
            "Show server process list (may expose other sessions)",
            ("SHOW PROCESSLIST",),
            risk_option="allow_processlist",
        ),
    ),
    "mongo": (
        _cap("mongo_collections", "列出授权库中的集合", "List collections in an authorized database", ("listCollections",)),
        _cap("mongo_find", "按条件查找文档", "Find documents with a filter", ("find",)),
        _cap("mongo_aggregate", "执行有界聚合管道", "Run a bounded aggregation pipeline", ("aggregate",)),
        _cap("mongo_stats", "集合或库统计", "Collection or database stats", ("collStats", "dbStats", "count")),
    ),
    "elasticsearch": (
        _cap("es_mapping", "读取索引 mapping", "Read index mappings", ("GET mapping",)),
        _cap("es_search", "在授权索引中搜索", "Search documents within authorized indices", ("POST _search",)),
        _cap("es_health", "集群健康摘要", "Cluster health summary", ("GET _cluster/health",)),
        _cap("es_index_stats", "索引统计", "Index statistics", ("GET _stats",)),
    ),
    "redis": (
        _cap(
            "redis_get",
            "查看单个 key（类型、TTL、有界值）",
            "Inspect one key (type, ttl, bounded value)",
            ("TYPE", "TTL", "GET", "LRANGE", "HSCAN", "…"),
        ),
        _cap("redis_scan", "按模式扫描 key", "Scan keys by pattern", ("SCAN",)),
        _cap("redis_info", "读取 INFO 分段", "Server INFO section", ("INFO",)),
        _cap("redis_slowlog", "最近慢日志", "Recent slowlog entries", ("SLOWLOG GET",)),
    ),
    "gitlab": (
        _cap("gitlab_search_code", "在授权项目中搜索代码", "Search code in authorized projects", ("GET search",)),
        _cap("gitlab_get_file", "读取项目中的单个文件", "Read one file from a project", ("GET file",)),
        _cap("gitlab_blame", "查看文件 blame", "Blame one file", ("GET blame",)),
    ),
    "cls": (
        _cap("cls_search", "在授权主题与时间窗内检索日志", "Search logs in an authorized topic/window", ("search_log",)),
        _cap("cls_context", "读取单条日志上下文", "Fetch log context around a record", ("describe_log_context",)),
    ),
    "rabbitmq": (
        _cap("rabbit_queues", "列出授权 vhost 中的队列", "List queues in an authorized vhost", ("GET /api/queues",)),
        _cap("rabbit_queue", "查看单个队列", "Inspect one queue", ("GET /api/queues/…",)),
    ),
    "kafka": (
        _cap("kafka_lag", "授权 topic 的消费组堆积", "Consumer group lag for authorized topics", ("describe_groups",)),
        _cap("kafka_offsets", "topic/partition 位点", "Topic/partition offsets", ("list_offsets",)),
        _cap("kafka_peek", "有界窥探消息", "Peek a bounded batch of messages", ("fetch",)),
    ),
    "nacos": (
        _cap("nacos_configs", "列出授权命名空间/group 的配置", "List configs in authorized namespace/group", ("config list",)),
        _cap("nacos_config", "按 dataId 读取配置", "Read one config by dataId", ("config get",)),
        _cap("nacos_services", "列出服务", "List services", ("service list",)),
        _cap("nacos_instances", "列出单个服务的实例", "List instances for one service", ("instance list",)),
    ),
    "jenkins": (
        _cap("jenkins_jobs", "列出授权 Job", "List authorized jobs", ("GET job list",)),
        _cap("jenkins_job", "Job 详情与最近构建", "Job details and last builds", ("GET job",)),
        _cap("jenkins_builds", "某个 Job 的最近构建", "Recent builds for a job", ("GET builds",)),
        _cap("jenkins_build", "单个构建详情", "One build detail", ("GET build",)),
        _cap(
            "jenkins_console",
            "读取有界构建日志",
            "Read a bounded build console log",
            ("GET consoleText",),
            risk_option="allow_console",
        ),
        _cap("jenkins_nodes", "列出授权节点", "List authorized nodes", ("GET computer",)),
        _cap("jenkins_queue", "查看构建队列", "Read the build queue", ("GET queue",)),
    ),
}

_BY_TOOL: dict[str, Capability] = {
    item.tool: item for items in _CATALOG.values() for item in items
}


def catalog_for(type_: str) -> tuple[Capability, ...]:
    return _CATALOG.get(type_, ())


def default_tools(type_: str) -> list[str]:
    """Non-risk tools enabled when ``enabled_tools`` is unset."""
    return [item.tool for item in catalog_for(type_) if item.risk_option is None]


def known_tools(type_: str) -> set[str]:
    return {item.tool for item in catalog_for(type_)}


def enabled_tool_names(options: Mapping[str, Any], type_: str) -> set[str]:
    """Resolved non-risk tool names for a target's options."""
    defaults = default_tools(type_)
    default_set = set(defaults)
    raw = options.get(ENABLED_TOOLS_KEY)
    if raw is None:
        return set(default_set)
    if not isinstance(raw, (list, tuple)):
        return set(default_set)
    return {str(item) for item in raw if str(item) in default_set}


def is_tool_enabled(target: Target, tool: str) -> bool:
    capability = _BY_TOOL.get(tool)
    if capability is None:
        return True
    if capability.risk_option:
        return bool(target.options.get(capability.risk_option))
    return tool in enabled_tool_names(target.options, target.type)


def ensure_tool_enabled(target: Target, tool: str) -> None:
    if is_tool_enabled(target, tool):
        return
    capability = _BY_TOOL.get(tool)
    allowed = sorted(enabled_for_status(target))
    if capability and capability.risk_option:
        raise errors.ScopeDenied(
            f"tool {tool} is not enabled on target {target.name}",
            allowed=allowed,
            hint=f"enable {capability.risk_option} on the target (risk opt-in)",
        )
    raise errors.ScopeDenied(
        f"tool {tool} is not enabled on target {target.name}",
        allowed=allowed,
        hint="enable the tool under Available capabilities, or use a tool from allowed",
    )


def enabled_for_status(target: Target) -> list[str]:
    """All currently enabled tool names (including risk opt-ins)."""
    return [item.tool for item in catalog_for(target.type) if is_tool_enabled(target, item.tool)]


def capabilities_payload(target: Target) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in catalog_for(target.type):
        rows.append(
            {
                "tool": item.tool,
                "enabled": is_tool_enabled(target, item.tool),
                "summary": item.summary_en,
                "protocol": list(item.protocol),
                "risk": item.risk_option is not None,
            }
        )
    return rows


def counts(target: Target) -> tuple[int, int]:
    """Return ``(enabled, total)`` including risk tools."""
    items = catalog_for(target.type)
    total = len(items)
    enabled = sum(1 for item in items if is_tool_enabled(target, item.tool))
    return enabled, total


def parse_enabled_tools(form: Mapping[str, Any], type_: str) -> list[str]:
    """Non-risk tools checked on the form; always an explicit list on save."""
    selected = set(_getlist(form, "enabled_tool"))
    return [name for name in default_tools(type_) if name in selected]


def form_rows(
    type_: str,
    *,
    options: Mapping[str, Any] | None = None,
    values: Mapping[str, Any] | None = None,
    selected_tools: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Rows for the Available capabilities form section."""
    options = options or {}
    values = values or {}
    if selected_tools is None:
        recovered = selected_from_values(values)
        selected = set(recovered) if recovered is not None else enabled_tool_names(options, type_)
    else:
        selected = set(selected_tools)
    rows: list[dict[str, Any]] = []
    for item in catalog_for(type_):
        if item.risk_option:
            if item.risk_option in values:
                checked = bool(values.get(item.risk_option))
            else:
                checked = bool(options.get(item.risk_option))
            name = item.risk_option
            value = "on"
        else:
            checked = item.tool in selected
            name = "enabled_tool"
            value = item.tool
        rows.append(
            {
                "tool": item.tool,
                "summary": item.summary,
                "protocol": item.protocol,
                "risk": item.risk_option is not None,
                "name": name,
                "value": value,
                "checked": checked,
            }
        )
    return rows


def selected_from_values(values: Mapping[str, Any]) -> list[str] | None:
    """Recover checkbox selection after a failed form post."""
    raw = values.get("_enabled_tools")
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    text = str(raw)
    if not text:
        return []
    return [part for part in text.split("\n") if part]


def ui_summary_keys() -> set[str]:
    """Chinese summary strings that must appear in the English locale catalog."""
    return {item.summary for items in _CATALOG.values() for item in items}


def _getlist(form: Mapping[str, Any], key: str) -> list[str]:
    getter = getattr(form, "getlist", None)
    if callable(getter):
        return [str(item) for item in getter(key) if str(item)]
    value = form.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    text = str(value)
    return [text] if text else []
