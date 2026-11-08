"""工具公共层：错误码映射、目标解析、审计与统一包络（planning 8.1–8.3）。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from dr_panda_mcp import auth, errors
from dr_panda_mcp.connectors import base as connectors_base
from dr_panda_mcp.log import (
    current_request_id,
    failure_text,
    log_tool_call,
)
from dr_panda_mcp.log import logger as event_logger
from dr_panda_mcp.masking import redact
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.store.protocol import AuditEntry, Target

logger = logging.getLogger(__name__)

TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

EnvironmentParam = Annotated[
    str,
    Field(
        description=(
            "Environment call key, not the display name. "
            "When the user gives a name like Lechang Production, first call "
            "systems_status and match it against title to get the key. "
            "Required when multiple environments are registered; can be omitted "
            "when there is only one. "
            "When there is more than one target of the same type you must still "
            "pass target; nothing is selected automatically."
        )
    ),
]

_ERROR_CODES: tuple[tuple[type[errors.DrPandaError], str], ...] = (
    (errors.TargetNotFound, errors.TARGET_NOT_FOUND),
    (errors.TargetDisabled, errors.TARGET_DISABLED),
    (errors.TargetTypeMismatch, errors.TARGET_TYPE_MISMATCH),
    (errors.EnvironmentRequired, errors.ENVIRONMENT_REQUIRED),
    (errors.EnvironmentNotFound, errors.ENVIRONMENT_NOT_FOUND),
    (errors.EnvironmentDisabled, errors.ENVIRONMENT_DISABLED),
    (errors.SecretUnavailable, errors.SECRET_UNAVAILABLE),
    (errors.ScopeDenied, errors.SCOPE_DENIED),
    (errors.InvalidArgument, errors.INVALID_ARGUMENT),
    (errors.UpstreamTimeout, errors.UPSTREAM_TIMEOUT),
    (errors.UpstreamNotFound, errors.UPSTREAM_NOT_FOUND),
    (errors.UpstreamUnavailable, errors.UPSTREAM_UNAVAILABLE),
    (errors.UpstreamQueryError, errors.UPSTREAM_QUERY_ERROR),
    (errors.UpstreamAuthError, errors.UPSTREAM_AUTH),
    (errors.StorageUnavailable, errors.STORAGE_UNAVAILABLE),
)


def code_for(exc: errors.DrPandaError) -> str:
    if isinstance(exc, errors.GuardRejected):
        return exc.code or errors.GUARD_REJECTED
    for exception_type, code in _ERROR_CODES:
        if isinstance(exc, exception_type):
            return code
    return errors.INTERNAL


_SUMMARY_LIMIT = 1024
_TRUNCATED_MARK = " params_truncated=1"


def mask_params(params: dict[str, Any], target: Target | None) -> str:
    """整段脱敏。截短放到写入摘要时，按剩余空间在空白处截断。"""
    raw = json.dumps(params, ensure_ascii=False, default=str)
    secrets = list(target.secret.values()) if target else []
    return redact(raw, secrets)


def fit_audit_params(redacted: str, limit: int) -> tuple[str, bool]:
    """把已脱敏的参数收进 ``limit``。放不下时优先保留短字段和 SQL 开头。"""
    if limit <= 0:
        return "", True
    if len(redacted) <= limit:
        return redacted, False
    try:
        payload = json.loads(redacted)
    except json.JSONDecodeError:
        return _clip_text(redacted, limit), True
    if isinstance(payload, dict):
        compact = json.dumps(payload, ensure_ascii=False, default=str)
        if len(compact) <= limit:
            return compact, False
        fitted = _fit_object(payload, limit)
        if fitted is not None:
            return fitted, True
    return _clip_text(redacted, limit), True


def build_tool_summary(
    *,
    tool: str,
    name: str,
    environment_key: str | None,
    params: dict[str, Any],
    target: Target | None,
    returned: int,
    elapsed_ms: int,
    error_code: str | None,
    client_prefix: str = "",
    request_id: str = "",
) -> str:
    """拼一条不超过 1024 字的工具审计。参数放不下时标明 ``params_truncated=1``。"""
    head = f"{client_prefix}{tool} env={environment_key or '-'} target={name or '-'} params="
    request = f" request={request_id}" if _request_id(request_id) else ""
    tail = f" returned={returned} elapsed_ms={elapsed_ms} error={error_code or '-'}{request}"
    redacted = mask_params(params, target)
    room = _SUMMARY_LIMIT - len(head) - len(tail)
    if room >= len(redacted):
        return f"{head}{redacted}{tail}"
    if room <= len(_TRUNCATED_MARK):
        bare = f"{head}{tail}"
        return bare if len(bare) <= _SUMMARY_LIMIT else bare[:_SUMMARY_LIMIT]
    text, cut = fit_audit_params(redacted, room - len(_TRUNCATED_MARK))
    if not cut and len(text) <= room:
        return f"{head}{text}{tail}"
    summary = f"{head}{text}{_TRUNCATED_MARK}{tail}"
    if len(summary) <= _SUMMARY_LIMIT:
        return summary
    overflow = len(summary) - _SUMMARY_LIMIT
    text = text[:-overflow] if overflow < len(text) else ""
    return f"{head}{text}{_TRUNCATED_MARK}{tail}"


def _fit_object(payload: dict[str, Any], limit: int) -> str | None:
    kept: dict[str, Any] = {}
    order: list[str] = []
    for key in _param_priority(payload):
        value = payload[key]
        trial = dict(kept)
        trial[key] = value
        if _json_len(trial) <= limit:
            kept[key] = value
            order.append(key)
            continue
        if isinstance(value, str):
            shortened = _shrink_string(kept, key, value, limit)
            if shortened:
                kept[key] = shortened
                order.append(key)
    if not kept:
        return None
    ordered: dict[str, Any] = {}
    if "sql" in kept:
        ordered["sql"] = kept["sql"]
    for key in order:
        if key != "sql":
            ordered[key] = kept[key]
    dumped = json.dumps(ordered, ensure_ascii=False, default=str)
    if len(dumped) > limit:
        return None
    return dumped


def _param_priority(payload: dict[str, Any]) -> list[str]:
    small: list[str] = []
    sql: list[str] = []
    rest: list[str] = []
    for key, value in payload.items():
        if key == "sql" and isinstance(value, str):
            sql.append(key)
        elif _is_small(value):
            small.append(key)
        else:
            rest.append(key)
    return small + sql + rest


def _is_small(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and len(value) <= 80


def _json_len(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def _shrink_string(kept: dict[str, Any], key: str, value: str, limit: int) -> str | None:
    best: str | None = None
    low = 1
    high = len(value)
    while low <= high:
        mid = (low + high) // 2
        candidate = _cut_at_space(value, mid)
        if not candidate:
            high = mid - 1
            continue
        trial = dict(kept)
        trial[key] = candidate
        if _json_len(trial) <= limit:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _clip_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return _cut_at_space(text, limit)


def _cut_at_space(value: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(value) <= max_len:
        return value.rstrip()
    chunk = value[:max_len]
    space = chunk.rfind(" ")
    if space > 0:
        return chunk[:space].rstrip()
    return chunk.rstrip()


def _request_id(value: str) -> str:
    if len(value) == 8 and all(char in "0123456789abcdef" for char in value):
        return value
    return ""


def _client_prefix() -> str:
    client = auth.current_client()
    if client is None:
        return ""
    return f"client={client.name or '-'} prefix={client.prefix or '-'} "


async def write_tool_audit(
    runtime: Runtime,
    *,
    tool: str,
    name: str,
    environment_key: str | None,
    params: dict[str, Any],
    target: Target | None,
    returned: int,
    started: float,
    error_code: str | None,
    error_message: str = "",
) -> None:
    """工具调用结束后记一行日志，再追加一条审计。写失败不影响工具结果。"""
    secrets = [str(item) for item in target.secret.values() if item] if target else []
    hint = (
        _clip_text(mask_params(params, target), 120)
        if event_logger.isEnabledFor(logging.DEBUG)
        else ""
    )
    log_tool_call(
        tool=tool,
        target_name=name,
        environment_key=environment_key,
        returned=returned,
        started=started,
        error_code=error_code,
        error_message=error_message,
        secrets=secrets,
        debug_hint=hint,
    )
    summary = build_tool_summary(
        tool=tool,
        name=name,
        environment_key=environment_key,
        params=params,
        target=target,
        returned=returned,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        error_code=error_code,
        client_prefix=_client_prefix(),
        request_id=current_request_id(),
    )
    error_detail = _clip_text(redact(error_message, secrets), 512) if error_message else ""
    try:
        await runtime.store.append_audit(
            AuditEntry(
                actor=auth.current_actor(),
                action="tool.call",
                target_name=name or None,
                summary=summary,
                environment_key=environment_key or None,
                outcome="failed" if error_code else "ok",
                error_detail=error_detail or None,
            )
        )
    except Exception:  # noqa: BLE001 - 审计写失败不影响工具结果
        logger.warning(failure_text("store.error", "failed to write tool audit", tool=tool))


async def run_tool(
    runtime: Runtime,
    *,
    tool: str,
    name: str,
    target_type: str,
    params: dict[str, Any],
    handler: Callable[[Target], Awaitable[dict[str, Any]]],
    environment: str = "",
) -> dict[str, Any]:
    """解析目标 → 执行 → 统一错误码与审计（审计失败不影响结果）。"""
    started = time.monotonic()
    environment = (environment or str(params.get("environment") or "")).strip()
    target: Target | None = None
    returned = 0
    error_code: str | None = None
    error_message = ""
    timeout = connectors_base.DEFAULT_TIMEOUT_SECONDS
    try:
        target = await runtime.catalog.resolve(
            name, environment=environment, expected_type=target_type
        )
        timeout = connectors_base.timeout_seconds(target)
        # 整个调用（含排队）共用同一个 deadline；排队时间计入超时（planning 8.3/9.3）。
        async with asyncio.timeout(timeout):
            async with runtime.catalog.slot(target):
                envelope = await handler(target)
        returned = int(envelope.get("returned", 0))
        return envelope
    except ToolError:
        raise
    except TimeoutError as exc:
        error_code = errors.UPSTREAM_TIMEOUT
        error_message = (
            f"tool call exceeded {timeout:.0f}s (including queueing); "
            "the target may be busy"
        )
        raise ToolError(f"{errors.UPSTREAM_TIMEOUT}: {error_message}") from exc
    except errors.DrPandaError as exc:
        error_code = code_for(exc)
        error_message = redact(str(exc), target.secret.values() if target else [])
        raise ToolError(f"{error_code}: {error_message}") from exc
    except Exception as exc:
        error_code = errors.INTERNAL
        secrets = target.secret.values() if target else []
        detail = _clip_text(redact(str(exc), secrets), 200)
        error_message = detail or str(exc)
        suffix = f": {detail}" if detail else ""
        raise ToolError(
            f"{errors.INTERNAL}: tool execution failed ({type(exc).__name__}){suffix}"
        ) from exc
    finally:
        environment_key = (
            target.environment_key
            if target is not None and target.environment_key
            else (environment or None)
        )
        await write_tool_audit(
            runtime,
            tool=tool,
            name=name,
            environment_key=environment_key,
            params=params,
            target=target,
            returned=returned,
            started=started,
            error_code=error_code,
            error_message=error_message,
        )


def finish(
    target: Target,
    *,
    summary: str,
    started: float,
    rows: list[dict[str, Any]],
    stats: dict[str, Any] | None = None,
    time_range: dict[str, str] | None = None,
    truncation: connectors_base.Truncation | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """按目标上限截断并生成 11 键包络。

    调用方已显式截断（例如文件内容）时只标记、不再二次裁行，避免把行整条丢掉。
    """
    kept, auto_truncation = connectors_base.apply_row_limits(
        rows, connectors_base.max_rows(target), connectors_base.max_bytes(target)
    )
    effective = truncation or auto_truncation
    built = (
        ["Results were truncated; narrow the query range, time window, or row count."]
        if effective
        else []
    )
    if target.environment_key:
        label = target.environment_title or target.environment_key
        built.insert(0, f"Environment {target.environment_key} ({label}).")
    if notes:
        built.extend(notes)
    stats, stats_truncated = _cap_stats(stats, connectors_base.max_bytes(target))
    if stats_truncated:
        built.append("Statistics were truncated due to the target byte limit.")
    return connectors_base.build_envelope(
        target,
        summary=summary[:200],
        elapsed_ms=int((time.monotonic() - started) * 1000),
        rows=kept,
        stats=stats,
        time_range=time_range,
        truncation=effective,
        notes=built,
    )


def _cap_stats(
    stats: dict[str, Any] | None, byte_limit: int
) -> tuple[dict[str, Any] | None, bool]:
    if stats is None:
        return None, False
    raw = json.dumps(stats, ensure_ascii=False, default=str).encode("utf-8")
    if len(raw) <= byte_limit:
        return stats, False
    return {"truncated": True, "reason": "bytes", "limit": byte_limit}, True


def trim_rows(
    rows: list[dict[str, Any]], cap: int
) -> tuple[list[dict[str, Any]], connectors_base.Truncation | None]:
    """用 cap+1 哨兵判断是否还有更多数据；返回前 cap 行与截断信息。"""
    if len(rows) > cap:
        return rows[:cap], connectors_base.Truncation("rows", cap)
    return rows, None


def ensure_topic(target: Target, topic: str) -> str:
    """校验日志主题在授权范围内。"""
    allowed = [str(item) for item in target.options.get("allowed_topics", [])]
    if not allowed:
        raise errors.ScopeDenied(
            f"target {target.name} has no authorized log topics"
        )
    value = topic.strip()
    if not value and len(allowed) == 1:
        return allowed[0]
    if not value:
        raise errors.InvalidArgument(
            "topic is required (this target authorizes multiple topics)"
        )
    if value not in allowed:
        raise errors.ScopeDenied(
            f"topic {value} is not within the authorized scope of target {target.name}"
        )
    return value


def ensure_project(target: Target, project: str) -> str:
    allowed = [str(item) for item in target.options.get("allowed_projects", [])]
    value = project.strip()
    if not allowed:
        raise errors.ScopeDenied(f"target {target.name} has no authorized projects")
    if value not in allowed:
        raise errors.ScopeDenied(
            f"project {value} is not within the authorized scope of target {target.name}"
        )
    return value


def allowed_projects(target: Target) -> list[str]:
    values = [str(item) for item in target.options.get("allowed_projects", [])]
    if not values:
        raise errors.ScopeDenied(f"target {target.name} has no authorized projects")
    return values


def clamp_limit(value: int | None, target: Target, default: int) -> int:
    limit = default if value is None else int(value)
    if limit < 1:
        raise errors.InvalidArgument("limit must be greater than 0")
    return min(limit, connectors_base.max_rows(target))
