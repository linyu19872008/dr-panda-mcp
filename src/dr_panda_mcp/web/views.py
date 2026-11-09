"""网页视图模型：把 Target 转成不含密钥的展示数据（planning 4.3 / 5.2）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dr_panda_mcp.client_install import INSTALL_EXTRAS
from dr_panda_mcp.errors import sync_extra_command
from dr_panda_mcp.store.protocol import Target
from dr_panda_mcp.web.clock import utc_text
from dr_panda_mcp.web.forms import TYPE_SPECS

EMPTY = "—"
_INSTALL_COMMAND = re.compile(r"uv sync --extra [A-Za-z0-9_-]+(?: --inexact)?")


def split_install_command(text: str | None) -> tuple[str | None, str | None]:
    """把失败说明里的安装命令拆出来。原文不改，只给页面用。"""
    if not text:
        return None, None
    match = _INSTALL_COMMAND.search(text)
    if not match:
        return text, None
    command = match.group(0)
    lead = text[: match.start()].rstrip(" ：:，,\n")
    tail = text[match.end() :].lstrip(" ：:，,\n")
    message = " ".join(part for part in (lead, tail) if part) or None
    return message, command


@dataclass(frozen=True)
class TargetView:
    id: int
    type: str
    type_label: str
    name: str
    enabled: bool
    endpoint: str
    scope: str
    scope_source: str
    scope_params: dict[str, Any]
    secret_fields: tuple[str, ...]
    secret_ok: bool
    updated_at_display: str | None
    last_test_at: datetime | None
    last_test_at_display: str | None
    last_test_ok: bool | None
    last_test_error: str | None
    last_test_message: str | None
    last_test_command: str | None
    client_extra: str | None
    environment_key: str = ""
    environment_title: str = ""
    environment_enabled: bool = True


@dataclass(frozen=True)
class ScopeDetail:
    """一个授权范围分组的细粒度展示（用于只读目标目录）。"""

    label: str
    values: tuple[str, ...] = ()
    unlimited: bool = False


_SCOPE_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "mysql": (("allowed_dbs", "允许的库"),),
    "mongo": (("allowed_dbs", "允许的库"),),
    "elasticsearch": (("allowed_indices", "允许的索引"),),
    "gitlab": (("allowed_projects", "允许的项目"),),
    "rabbitmq": (("allowed_vhosts", "允许的 vhost"),),
    "kafka": (("allowed_topics", "允许的 topic"),),
    "cls": (("allowed_topics", "允许的日志主题"),),
    "nacos": (
        ("allowed_namespaces", "允许的命名空间"),
        ("allowed_groups", "允许的 group"),
        ("allowed_data_ids", "允许的 dataId"),
        ("allowed_services", "允许的服务"),
    ),
    "jenkins": (
        ("allowed_jobs", "允许的 Job"),
        ("allowed_nodes", "允许的节点"),
    ),
}


def scope_details(target: Target) -> list[ScopeDetail]:
    """把授权范围拆成「标签 + 具体值」，只读目录用（不返回任何密钥）。"""
    details: list[ScopeDetail] = []
    if target.type == "redis":
        prefix = str(target.options.get("key_prefix") or "").strip()
        details.append(
            ScopeDetail("key 前缀", (prefix,) if prefix else (), unlimited=not prefix)
        )
        return details
    for key, label in _SCOPE_FIELDS.get(target.type, ()):
        raw = target.options.get(key)
        if isinstance(raw, (list, tuple)):
            values = tuple(str(item).strip() for item in raw if str(item).strip())
        elif raw is None:
            values = ()
        else:
            text = str(raw).strip()
            values = (text,) if text else ()
        details.append(ScopeDetail(label, values))
    return details


@dataclass(frozen=True)
class Stats:
    total: int = 0
    enabled: int = 0
    failed: int = 0
    key_issues: int = 0


def _display_time(value: datetime | None) -> str | None:
    return utc_text(value)


def _first(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else None
    if isinstance(value, str):
        return value.splitlines()[0].strip() or None
    return None


def _endpoint(target: Target) -> str:
    options = target.options
    kind = target.type
    if kind == "mysql":
        host = options.get("host") or EMPTY
        port = options.get("port") or 3306
        db = options.get("default_db") or EMPTY
        return f"{host}:{port} / {db}"
    if kind == "mongo":
        host = options.get("host")
        if host:
            return f"{host}:{options.get('port') or 27017}"
        return "URI（已配置）"
    if kind == "elasticsearch":
        host = _first(options.get("hosts"))
        return host or EMPTY
    if kind == "redis":
        host = options.get("host") or EMPTY
        port = options.get("port") or 6379
        db = options.get("db") or 0
        return f"{host}:{port} / db{db}"
    if kind == "gitlab":
        return str(options.get("base_url") or EMPTY)
    if kind == "rabbitmq":
        return str(options.get("management_url") or EMPTY)
    if kind == "kafka":
        server = _first(options.get("bootstrap_servers"))
        protocol = options.get("security_protocol") or "PLAINTEXT"
        return f"{server or EMPTY} · {protocol}"
    if kind == "cls":
        return str(options.get("region") or EMPTY)
    return EMPTY


def _scope(target: Target) -> tuple[str, dict[str, Any]]:
    options = target.options
    kind = target.type
    if kind == "mysql":
        dbs = options.get("allowed_dbs") or []
        return ("{count} 个库", {"count": len(dbs)}) if dbs else ("默认库", {})
    if kind in {"mongo", "elasticsearch"}:
        key = "allowed_dbs" if kind == "mongo" else "allowed_indices"
        items = options.get(key) or []
        source = "{count} 个库" if kind == "mongo" else "{count} 个索引"
        return (source, {"count": len(items)}) if items else ("未授权", {})
    if kind == "redis":
        prefix = options.get("key_prefix")
        return ("前缀 {prefix}", {"prefix": prefix}) if prefix else ("全部 key", {})
    if kind == "gitlab":
        items = options.get("allowed_projects") or []
        return ("{count} 个项目", {"count": len(items)}) if items else ("未授权", {})
    if kind == "rabbitmq":
        items = options.get("allowed_vhosts") or []
        return ("{count} 个 vhost", {"count": len(items)}) if items else ("未授权", {})
    if kind in {"kafka", "cls"}:
        items = options.get("allowed_topics") or []
        source = "{count} 个 topic" if kind == "kafka" else "{count} 个日志主题"
        return (source, {"count": len(items)}) if items else ("未授权", {})
    return ("—", {})


def client_extra(target_type: str) -> str | None:
    """这个目标类型对应的可选依赖名。没有可选客户端时返回 None。"""
    if target_type in INSTALL_EXTRAS:
        return target_type
    return None


def probe_install_extra(target_type: str, message: str | None) -> str | None:
    """从探测错误里识别“缺少客户端”，返回可安装的固定 extra。"""
    extra = client_extra(target_type)
    if extra is None:
        return None
    _, command = split_install_command(message)
    allowed = {f"uv sync --extra {extra}", sync_extra_command(extra)}
    return extra if command in allowed else None


def requested_install_extra(target: Target) -> str | None:
    """只有「客户端未安装」才允许安装，并且只装这个目标类型自己的 extra。"""
    extra = client_extra(target.type)
    if extra is None:
        return None
    _, command = split_install_command(target.last_test_error)
    allowed = {f"uv sync --extra {extra}", sync_extra_command(extra)}
    if command not in allowed:
        return None
    return extra


def to_view(target: Target) -> TargetView:
    spec = TYPE_SPECS.get(target.type)
    scope_source, scope_params = _scope(target)
    message, command = split_install_command(target.last_test_error)
    return TargetView(
        id=target.id,
        type=target.type,
        type_label=spec.label if spec else target.type,
        name=target.name,
        enabled=target.enabled,
        endpoint=_endpoint(target),
        scope=scope_source,
        scope_source=scope_source,
        scope_params=scope_params,
        secret_fields=tuple(sorted(target.secret_fields)),
        secret_ok=target.secret_ok,
        updated_at_display=_display_time(target.updated_at),
        last_test_at=target.last_test_at,
        last_test_at_display=_display_time(target.last_test_at),
        last_test_ok=target.last_test_ok,
        last_test_error=target.last_test_error,
        last_test_message=message,
        last_test_command=command,
        client_extra=client_extra(target.type),
        environment_key=target.environment_key,
        environment_title=target.environment_title,
        environment_enabled=target.environment_enabled,
    )


def list_views(targets: list[Target]) -> list[TargetView]:
    return [to_view(target) for target in targets]


def filter_views(
    views: list[TargetView],
    *,
    q: str = "",
    type_: str | None = None,
    environment: str | None = None,
) -> list[TargetView]:
    needle = q.strip().lower()
    filtered = views
    if environment:
        filtered = [view for view in filtered if view.environment_key == environment]
    if type_:
        filtered = [view for view in filtered if view.type == type_]
    if needle:
        filtered = [
            view
            for view in filtered
            if needle
            in f"{view.name} {view.type} {view.type_label} {view.endpoint} {view.scope}".lower()
        ]
    return filtered


def stats(views: list[TargetView]) -> Stats:
    return Stats(
        total=len(views),
        enabled=sum(1 for view in views if view.enabled),
        failed=sum(1 for view in views if view.last_test_ok is False),
        key_issues=sum(1 for view in views if view.secret_fields and not view.secret_ok),
    )
