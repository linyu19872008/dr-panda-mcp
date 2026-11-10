"""错误码与异常基类。

错误码是对外契约的一部分（planning 8.2），工具失败时以 ``CODE: message`` 形式返回；
内部一律用异常传递。M0 只落地常量与基础异常，ToolError 映射在 M2 接入。
"""

from __future__ import annotations

import re

# 目标相关
TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
TARGET_DISABLED = "TARGET_DISABLED"
TARGET_TYPE_MISMATCH = "TARGET_TYPE_MISMATCH"
NO_ENABLED_TARGET = "NO_ENABLED_TARGET"
ENVIRONMENT_REQUIRED = "ENVIRONMENT_REQUIRED"
ENVIRONMENT_NOT_FOUND = "ENVIRONMENT_NOT_FOUND"
ENVIRONMENT_DISABLED = "ENVIRONMENT_DISABLED"

# 参数与闸门
INVALID_ARGUMENT = "INVALID_ARGUMENT"
GUARD_REJECTED = "GUARD_REJECTED"
DANGEROUS_OPERATION = "DANGEROUS_OPERATION"
SCOPE_DENIED = "SCOPE_DENIED"

# 上游
UPSTREAM_NOT_FOUND = "UPSTREAM_NOT_FOUND"
UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
UPSTREAM_QUERY_ERROR = "UPSTREAM_QUERY_ERROR"
UPSTREAM_AUTH = "UPSTREAM_AUTH"

# 本服务自身
STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
SECRET_UNAVAILABLE = "SECRET_UNAVAILABLE"
INTERNAL = "INTERNAL"

ALL_CODES = frozenset(
    {
        TARGET_NOT_FOUND,
        TARGET_DISABLED,
        TARGET_TYPE_MISMATCH,
        NO_ENABLED_TARGET,
        ENVIRONMENT_REQUIRED,
        ENVIRONMENT_NOT_FOUND,
        ENVIRONMENT_DISABLED,
        INVALID_ARGUMENT,
        GUARD_REJECTED,
        DANGEROUS_OPERATION,
        SCOPE_DENIED,
        UPSTREAM_NOT_FOUND,
        UPSTREAM_TIMEOUT,
        UPSTREAM_UNAVAILABLE,
        UPSTREAM_QUERY_ERROR,
        UPSTREAM_AUTH,
        STORAGE_UNAVAILABLE,
        SECRET_UNAVAILABLE,
        INTERNAL,
    }
)


class DrPandaError(Exception):
    """本服务所有可预期异常的基类。"""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ConfigError(DrPandaError):
    """环境变量或启动配置不合法，进程应以非零码退出。"""


class StartupError(DrPandaError):
    """启动过程中不可继续的错误（端口占用、迁移失败等）。"""


class TargetNotFound(DrPandaError):
    """按名字或 id 找不到目标。"""


class TargetNameTaken(DrPandaError):
    """目标名已被占用（唯一约束）。"""


class InvalidTarget(DrPandaError):
    """目标字段不合法，或试图修改不可变字段。"""


class StorageUnavailable(DrPandaError):
    """配置库不可用。"""


class SecretUnavailable(DrPandaError):
    """密钥无法解密（密钥缺失、被替换或密文损坏）。"""


class InvalidSettings(DrPandaError):
    """系统配置键或取值不合法。"""


def guidance_message(
    message: str,
    *,
    allowed: list[str] | None = None,
    hint: str | None = None,
    allowed_limit: int = 20,
) -> str:
    """Append allowlist / recovery hint so agents can retry without guessing."""
    parts = [message.rstrip(".")]
    if allowed:
        shown = ", ".join(str(item) for item in allowed[:allowed_limit])
        extra = len(allowed) - allowed_limit
        suffix = f" (+{extra} more)" if extra > 0 else ""
        parts.append(f"allowed: {shown}{suffix}")
    if hint:
        parts.append(hint.rstrip("."))
    return "; ".join(parts)


class ScopeDenied(DrPandaError):
    """请求超出该目标授权的范围（库/索引/topic/项目/vhost）。"""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        allowed: list[str] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            guidance_message(message, allowed=allowed, hint=hint),
            code=code or SCOPE_DENIED,
        )


class InvalidArgument(DrPandaError):
    """工具参数不合法（缺失、越界、时间窗超限等）。"""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        allowed: list[str] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            guidance_message(message, allowed=allowed, hint=hint),
            code=code or INVALID_ARGUMENT,
        )


class TargetDisabled(DrPandaError):
    """目标已停用，工具拒绝使用。"""


class TargetTypeMismatch(DrPandaError):
    """目标的类型与调用的工具不一致。"""


class EnvironmentRequired(DrPandaError):
    """登记了多个环境，调用却没有指定 environment。"""


class EnvironmentNotFound(DrPandaError):
    """按调用标识找不到环境。"""


class EnvironmentDisabled(DrPandaError):
    """环境已停用，工具拒绝使用其中的目标。"""


class EnvironmentKeyTaken(DrPandaError):
    """环境调用标识已被占用。"""


class EnvironmentNotEmpty(DrPandaError):
    """环境里还有目标，不能删除。"""


class GuardRejected(DrPandaError):
    """只读白名单或危险清单拒绝了请求（code 取 ``GUARD_REJECTED`` / ``DANGEROUS_OPERATION``）。"""


class UpstreamError(DrPandaError):
    """排查目标（上游系统）返回错误或不可用。"""


class UpstreamTimeout(UpstreamError):
    """上游调用超时。"""


class UpstreamUnavailable(UpstreamError):
    """上游连接失败、连接中断或返回 5xx。"""


class UpstreamQueryError(UpstreamError):
    """上游拒绝了查询：SQL / 管道 / DSL / 命令参数有误。"""


class UpstreamAuthError(UpstreamError):
    """上游认证或授权失败：凭据、权限或认证方式有问题。"""


class UpstreamNotFound(UpstreamError):
    """上游返回 404（库、索引、文件不存在）。"""


def sync_extra_command(extra: str) -> str:
    """补装一个 extra，并保留环境里已经装好的其他包。

    ``uv sync --extra`` 默认是精确同步，未点名的 extra 会被卸掉。
    ``--inexact`` 只把这一个装进当前项目环境。
    """
    return f"uv sync --extra {extra} --inexact"


def missing_client_message(extra: str) -> str:
    """排查客户端不在当前服务环境时的说明。命令留在句末，页面只用来判断能否安装。"""
    return f"{extra} client is not installed: {sync_extra_command(extra)}"


_SYNC_EXTRA = re.compile(r"uv sync --extra [A-Za-z0-9_-]+(?: --inexact)?")


def install_failed_message(extra: str, reason: str) -> str:
    """安装失败后仍保留句末命令，页面据此继续显示安装按钮。"""
    cleaned = " ".join(reason.split())
    cleaned = _SYNC_EXTRA.sub("", cleaned)
    cleaned = cleaned.strip(" ：:，,.")
    if len(cleaned) > 300:
        cleaned = cleaned[:300].rstrip() + "…"
    if not cleaned:
        cleaned = "uv sync did not succeed"
    return f"{extra} client is not installed. Installation did not finish: {cleaned}: {sync_extra_command(extra)}"
