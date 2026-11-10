"""SQLAlchemy 2 声明式表（planning 5.3）。

四张表：``targets``、``audit``、``settings``、``settings_history``。所有时间列用 UTC 带时区语义：
SQLite 存不带偏移的文本，读出时由 :class:`UTCDateTime` 统一补成 UTC。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _pk_type():
    """主键类型：多数库用 BIGINT，SQLite 退化为 INTEGER 才能自增。"""
    return BigInteger().with_variant(Integer, "sqlite")


class UTCDateTime(TypeDecorator):
    """统一按 UTC 读写的时间类型，兼容 SQLite 丢失时区的问题。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("时间必须带时区（UTC）")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EnvironmentRow(Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("key", name="uq_environments_key"),)

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class TargetRow(Base):
    __tablename__ = "targets"
    __table_args__ = (
        UniqueConstraint("environment_id", "name", name="uq_targets_environment_name"),
        Index("ix_targets_type", "type"),
        Index("ix_targets_environment_id", "environment_id"),
    )

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True, autoincrement=True)
    environment_id: Mapped[int] = mapped_column(
        _pk_type(), ForeignKey("environments.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    secret_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    operator_notes: Mapped[str] = mapped_column(
        String(512), nullable=False, default="", server_default=""
    )


class AuditRow(Base):
    __tablename__ = "audit"
    __table_args__ = (
        Index("ix_audit_created_at", "created_at"),
        Index("ix_audit_tool_created_at", "tool", "created_at"),
    )

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    environment_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 结构化结果：ok / failed；只有 tool.call、target.test 等有成败语义的动作会写，
    # 旧行为 NULL，由 0010 迁移按 summary 回填。
    outcome: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # 失败原因摘要（已脱敏、截断），只有 tool.call 失败时写；旧行为 NULL。
    error_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # tool.call 结构化字段（旧行为 NULL，由 summary 仍可解析）。
    tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    group_key: Mapped[str] = mapped_column(String(64), nullable=False)
    group_title: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    default_value: Mapped[str] = mapped_column(String(64), nullable=False)
    min_value: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    max_value: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    effect: Mapped[str] = mapped_column(String(64), nullable=False)
    editable: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    requires_restart: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    sort_order: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    is_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    auth_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class McpTokenRow(Base):
    __tablename__ = "mcp_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mcp_tokens_token_hash"),
        Index("ix_mcp_tokens_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        _pk_type(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SettingsHistoryRow(Base):
    __tablename__ = "settings_history"
    __table_args__ = (
        Index("ix_settings_history_key", "key"),
        Index("ix_settings_history_changed_at", "changed_at"),
    )

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_value: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
