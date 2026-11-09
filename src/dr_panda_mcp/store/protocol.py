"""ConfigStore 接口与数据对象（planning 5.2）。

网页、工具、连接器只依赖这里；不出现 SQLite / MySQL / PostgreSQL 的类型或 SQL。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

TARGET_TYPES = frozenset(
    {"mysql", "mongo", "elasticsearch", "redis", "gitlab", "rabbitmq", "kafka", "cls", "nacos"}
)


@dataclass(frozen=True)
class Environment:
    """一组排查目标所属的环境。``key`` 是模型传入的调用标识，``title`` 是展示名。"""

    id: int
    key: str
    title: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    target_count: int = 0
    enabled_target_count: int = 0


@dataclass(frozen=True)
class Target:
    """配置库里的一个排查目标。``secret`` 是解密后的值，只在进程内使用。"""

    id: int
    type: str
    name: str
    enabled: bool
    options: dict[str, Any]
    secret: dict[str, str]
    secret_fields: frozenset[str]
    secret_ok: bool
    created_at: datetime
    updated_at: datetime
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_error: str | None
    environment_key: str = ""
    environment_title: str = ""
    environment_enabled: bool = True


@dataclass(frozen=True)
class SecretPatch:
    """密钥补丁：``set`` 覆盖或新增，``clear`` 置空。"""

    set: dict[str, str] = field(default_factory=dict)
    clear: frozenset[str] = field(default_factory=frozenset)

    def is_empty(self) -> bool:
        return not self.set and not self.clear


@dataclass(frozen=True)
class TargetDraft:
    """新建与修改共用的入参。修改时 ``name`` 与 ``type`` 必须与库中一致。"""

    name: str
    type: str
    enabled: bool
    options: dict[str, Any]
    secret_patch: SecretPatch = field(default_factory=SecretPatch)
    environment_key: str = ""


@dataclass(frozen=True)
class AuditEntry:
    actor: str
    action: str
    target_name: str | None = None
    summary: str | None = None
    environment_key: str | None = None
    outcome: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class AuditRecord:
    created_at: datetime
    actor: str
    action: str
    environment_key: str | None
    target_name: str | None
    summary: str | None
    outcome: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class SettingsChange:
    """一次系统配置修改的结构化历史。"""

    created_at: datetime
    actor: str
    summary: str | None
    key: str | None = None
    old_value: str | None = None
    new_value: str | None = None


@dataclass(frozen=True)
class Settings:
    """解析并校验后的运行时策略（planning 4.5）。"""

    audit_retention_days: int
    target_max_concurrency: int
    default_target_timeout_s: int = 15
    default_target_max_rows: int = 100
    default_target_max_bytes: int = 102_400
    audit_cleanup_interval_minutes: int = 60
    catalog_max_clients: int = 32
    backup_keep_count: int = 20
    session_ttl_minutes: int = 720
    login_max_attempts: int = 5
    login_lockout_minutes: int = 5
    mcp_token_max_per_user: int = 5
    mcp_token_ttl_days: int = 0
    global_max_concurrent_calls: int = 0
    catalog_idle_seconds: int = 0
    audit_cleanup_batch_size: int = 1000
    audit_cleanup_max_seconds: int = 300


@runtime_checkable
class ConfigStore(Protocol):
    """配置库接口。所有写方法都在同一事务里追加审计。"""

    async def ping(self) -> None: ...
    async def list_environments(self) -> list[Environment]: ...
    async def create_environment(
        self, key: str, title: str, actor: str, *, enabled: bool = True
    ) -> Environment: ...
    async def update_environment(
        self, environment_id: int, *, title: str, enabled: bool, actor: str
    ) -> Environment: ...
    async def delete_environment(self, environment_id: int, actor: str) -> None: ...
    async def list_all(self) -> list[Target]: ...
    async def list_by_type(self, type: str) -> list[Target]: ...
    async def list_by_environment(self, key: str) -> list[Target]: ...
    async def get(self, name: str, *, environment: str = "") -> Target | None: ...
    async def find(self, name: str, *, environment: str = "") -> Target | None: ...
    async def get_by_id(self, target_id: int) -> Target | None: ...

    async def create(self, draft: TargetDraft, actor: str) -> Target: ...
    async def update(self, target_id: int, draft: TargetDraft, actor: str) -> Target: ...
    async def set_enabled(self, target_id: int, enabled: bool, actor: str) -> Target: ...
    async def delete(self, target_id: int, actor: str) -> None: ...
    async def record_test(
        self, target_id: int, ok: bool, error: str | None, actor: str
    ) -> Target: ...
    async def append_audit(self, entry: AuditEntry) -> None: ...
    async def list_audit(
        self,
        *,
        since: datetime,
        action: str | None = None,
        environment_key: str | None = None,
        target_name: str | None = None,
        actor: str | None = None,
        actions: tuple[str, ...] | None = None,
        outcome: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditRecord], int]: ...

    async def get_settings(self) -> dict[str, str]: ...
    async def update_settings(self, patch: Mapping[str, str], actor: str) -> dict[str, str]: ...
    async def list_settings_changes(
        self, limit: int = 5
    ) -> list[SettingsChange]: ...
