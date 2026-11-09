"""`systems_status`：先列出环境，再列出某个环境里的目标。"""

from __future__ import annotations

import time
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import base
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.store.protocol import Target
from dr_panda_mcp.tools.base import (
    TOOL_ANNOTATIONS,
    EnvironmentParam,
    code_for,
    write_tool_audit,
)


def register_systems_status(server: FastMCP, runtime: Runtime) -> None:
    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def systems_status(environment: EnvironmentParam = "") -> dict[str, Any]:
        """List environments, or list one environment's targets with recent connectivity.

        When environment is omitted, only environments are returned (key, display
        title, target count). When it is provided, only that environment's targets
        are returned. Each target row includes a non-secret scope object with
        the authorized database/index/topic/vhost/project selectors. When there
        is more than one target of the same type, later calls must name the target.
        CLS scope.allowed_topics entries are logsetId/topicId UUIDs, not topic names.
        """
        key = environment.strip()
        started = time.monotonic()
        returned = 0
        error_code: str | None = None
        error_message = ""
        try:
            with base.Stopwatch() as watch:
                payload = (
                    await _environments(runtime)
                    if not key
                    else await _targets(runtime, key)
                )
                payload["elapsed_ms"] = watch.elapsed_ms
            returned = int(payload.get("returned", 0))
            return payload
        except errors.DrPandaError as exc:
            error_code = code_for(exc)
            error_message = str(exc)
            raise ToolError(f"{error_code}: {exc}") from exc
        except Exception as exc:
            error_code = errors.INTERNAL
            detail = str(exc).strip()
            if len(detail) > 200:
                detail = detail[:199] + "…"
            error_message = detail or str(exc)
            suffix = f": {detail}" if detail else ""
            raise ToolError(
                f"{errors.INTERNAL}: tool execution failed ({type(exc).__name__}){suffix}"
            ) from exc
        finally:
            await write_tool_audit(
                runtime,
                tool="systems_status",
                name="",
                environment_key=key or None,
                params={"environment": key},
                target=None,
                returned=returned,
                started=started,
                error_code=error_code,
                error_message=error_message,
            )


async def _environments(runtime: Runtime) -> dict[str, Any]:
    environments = await runtime.store.list_environments()
    rows = [
        {
            "key": item.key,
            "title": item.title,
            "enabled": item.enabled,
            "targets": item.target_count,
            "enabled_targets": item.enabled_target_count,
        }
        for item in environments
    ]
    notes = [
        (
            "This is the environment list, not the target list. To see the "
            "targets inside one environment, pass environment=<its key>."
        ),
        (
            "title is the display name; key is the tool argument. When multiple "
            "environments are registered, later calls must pass environment."
        ),
        (
            "An environment may contain several targets of the same type; calls "
            "must pass target, with no automatic selection."
        ),
    ]
    if len(environments) == 1:
        notes.append(
            "Only one environment is registered, so tool calls may omit environment."
        )
    return _envelope(
        summary="environments",
        rows=rows,
        stats={
            "environments": len(rows),
            "enabled": sum(1 for row in rows if row["enabled"]),
            "targets": sum(int(row["targets"]) for row in rows),
            "enabled_targets": sum(int(row["enabled_targets"]) for row in rows),
        },
        notes=notes,
    )


async def _targets(runtime: Runtime, key: str) -> dict[str, Any]:
    environments = await runtime.store.list_environments()
    match = next((item for item in environments if item.key == key), None)
    if match is None:
        choices = ", ".join(f"{item.key} ({item.title})" for item in environments)
        suffix = f". Available: {choices}" if choices else ""
        raise errors.EnvironmentNotFound(f"environment {key} is not registered{suffix}")
    targets = await runtime.store.list_by_environment(key)
    rows = [
        {
            "name": target.name,
            "type": target.type,
            "enabled": target.enabled,
            "operator_notes": target.operator_notes,
            "scope": _target_scope(target),
            "last_test_at": _iso(target.last_test_at),
            "last_test_ok": target.last_test_ok,
            "last_test_error": target.last_test_error,
        }
        for target in targets
    ]
    notes = [
        f"Environment {match.key} ({match.title}).",
        (
            "When there is more than one target of the same type, pass the "
            "corresponding target; there is no automatic selection."
        ),
        (
            "Each target's scope lists its authorized selectors. Pass only values "
            "from scope.allowed_dbs / allowed_indices / allowed_topics / "
            "allowed_vhosts / allowed_projects; an empty list means no value is "
            "authorized. A null key_prefix means no Redis prefix restriction."
        ),
    ]
    if any(target.type == "cls" for target in targets):
        notes.append(
            "CLS allowed_topics entries are logsetId/topicId UUIDs from the "
            "Tencent Cloud console, not friendly topic names."
        )
    if not match.enabled:
        notes.append(
            f"Environment {match.key} ({match.title}) is disabled; investigation "
            "tools will reject calls."
        )
    return _envelope(
        summary=f"environment {match.key}",
        rows=rows,
        stats={
            "environment": match.key,
            "title": match.title,
            "targets": len(rows),
            "enabled": sum(1 for row in rows if row["enabled"]),
        },
        notes=notes,
    )


_SCOPE_FIELDS: dict[str, tuple[str, ...]] = {
    "mysql": ("allowed_dbs", "default_db"),
    "mongo": ("allowed_dbs", "default_db"),
    "elasticsearch": ("allowed_indices",),
    "redis": ("key_prefix",),
    "rabbitmq": ("allowed_vhosts",),
    "kafka": ("allowed_topics",),
    "cls": ("allowed_topics",),
    "gitlab": ("allowed_projects",),
    "nacos": ("allowed_namespaces", "allowed_groups", "allowed_data_ids", "allowed_services"),
    "jenkins": ("allowed_jobs", "allowed_nodes"),
}


def _target_scope(target: Target) -> dict[str, Any]:
    """Return the non-secret authorization scope for one target."""
    scope: dict[str, Any] = {}
    for field in _SCOPE_FIELDS.get(target.type, ()):
        value = target.options.get(field)
        if field in {"default_db", "key_prefix"}:
            text = str(value).strip() if value is not None else ""
            scope[field] = text or None
        else:
            scope[field] = [str(item) for item in (value or [])]
    return scope


def _envelope(
    *,
    summary: str,
    rows: list[dict[str, Any]],
    stats: dict[str, Any],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "target": "*",
        "type": "all",
        "summary": summary,
        "time_range": None,
        "returned": len(rows),
        "truncated": False,
        "truncation": None,
        "elapsed_ms": 0,
        "rows": rows,
        "stats": stats,
        "notes": notes,
    }


def _iso(value) -> str | None:
    return (
        value.isoformat(timespec="seconds").replace("+00:00", "Z")
        if value is not None
        else None
    )
