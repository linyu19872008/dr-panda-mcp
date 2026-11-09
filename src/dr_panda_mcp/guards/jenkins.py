"""Jenkins 只读闸门：只允许核心读取 API 的 GET 请求。"""

from __future__ import annotations

from dr_panda_mcp.guards.protocol import Decision, allow, guard_rejected

_ALLOWED_PATHS = (
    "/api/json",
    "/me/api/json",
    "/computer/api/json",
    "/queue/api/json",
)
_FORBIDDEN_SEGMENTS = ("/script", "/pluginManager", "/credentials", "/user/")


def check_jenkins(method: str, path: str) -> Decision:
    if not isinstance(method, str) or not isinstance(path, str) or not path:
        return guard_rejected("jenkins.invalid_request", "method and path must not be empty")
    upper = method.upper()
    if upper != "GET":
        return guard_rejected("jenkins.method_not_allowed", f"Jenkins only allows GET, got {upper}")
    if ".." in path or path.startswith("//"):
        return guard_rejected("jenkins.invalid_path", "path traversal is not allowed")
    if any(segment in path for segment in _FORBIDDEN_SEGMENTS):
        return guard_rejected("jenkins.path_not_allowed", f"Jenkins path is not read-only: {path}")
    if path.startswith("/job/"):
        if not path.endswith(("/api/json", "/consoleText")):
            return guard_rejected("jenkins.path_not_allowed", f"Jenkins job path is not allowed: {path}")
        return allow({"method": upper, "path": path})
    if path in _ALLOWED_PATHS or path.startswith("/view/") and path.endswith("/api/json"):
        return allow({"method": upper, "path": path})
    return guard_rejected("jenkins.path_not_allowed", f"Jenkins path is not allowed: {path}")
