"""CLS 只读闸门（planning 6.3 / 6.6）。

只允许检索与只读描述；搜索必须带时间窗，单次窗口不超过 24 小时。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from dr_panda_mcp.guards import forbidden
from dr_panda_mcp.guards.protocol import (
    Decision,
    allow,
    dangerous,
    guard_rejected,
)


def check_cls(
    action: str,
    request: Mapping[str, Any] | None = None,
    *,
    max_window_minutes: int | None = None,
) -> Decision:
    if not isinstance(action, str) or not action:
        return guard_rejected("cls.empty_action", "action must not be empty")
    if action in forbidden.CLS_DANGEROUS_ACTIONS:
        return dangerous("cls.write_action", f"CLS write operations are not allowed: {action}")
    if action not in forbidden.CLS_READ_ACTIONS:
        return guard_rejected("cls.action_not_allowed", f"action not allowed: {action}")

    request = request or {}
    if not isinstance(request, Mapping):
        return guard_rejected("cls.invalid_request", "request must be an object")

    normalized: dict[str, Any] = {"action": action, "request": dict(request)}
    if action == "search_log":
        start = _parse_time(request.get("from"))
        end = _parse_time(request.get("to"))
        if start is None or end is None:
            return guard_rejected(
                "cls.time_window_required",
                "log search requires a from / to time window "
                "(ISO-8601, year between 2000 and 2100)",
            )
        if end < start:
            return guard_rejected("cls.invalid_window", "to must not be earlier than from")
        for label, moment in (("from", start), ("to", end)):
            if moment.year < 2000 or moment.year > 2100:
                return guard_rejected(
                    "cls.invalid_timestamp",
                    f"{label} year {moment.year} is out of range; use ISO-8601 between 2000 and 2100",
                )
        limit = forbidden.CLS_MAX_WINDOW
        if max_window_minutes is not None:
            limit = min(limit, timedelta(minutes=max(int(max_window_minutes), 1)))
        if end - start > limit:
            return dangerous(
                "cls.window_too_large",
                f"a single time window must not exceed "
                f"{int(limit.total_seconds() // 60)} minutes",
            )
        normalized.update({"from": start, "to": end})

    return allow(normalized)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None
