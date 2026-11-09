"""Nacos 只读闸门：只允许配置与命名服务的 GET 查询。"""

from __future__ import annotations

from dr_panda_mcp.guards.protocol import Decision, allow, guard_rejected

_ALLOWED_PREFIXES = (
    "/v1/cs/configs",
    "/v1/ns/service/list",
    "/v1/ns/instance/list",
    "/v1/console/health/liveness",
)


def check_nacos(method: str, path: str) -> Decision:
    if not isinstance(method, str) or not isinstance(path, str) or not path:
        return guard_rejected("nacos.invalid_request", "method and path must not be empty")
    upper = method.upper()
    if upper != "GET":
        return guard_rejected("nacos.method_not_allowed", f"Nacos only allows GET, got {upper}")
    if ".." in path or path.startswith("//"):
        return guard_rejected("nacos.invalid_path", "path traversal is not allowed")
    if not path.startswith(_ALLOWED_PREFIXES):
        return guard_rejected("nacos.path_not_allowed", f"Nacos path is not read-only: {path}")
    return allow({"method": upper, "path": path})
