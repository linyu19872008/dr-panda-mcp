"""ConfigStore 的 SQLAlchemy 异步实现（planning 5.2 / 5.4 / 5.8）。

- 唯一写 SQL 的地方；密钥加密/解密也只在这里调用 :class:`SecretBox`
- 写方法与审计在同一事务提交，失败一起回滚
- 读取时容忍单个目标的密钥解密失败：``secret_ok=False``，由上层决定报错
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dr_panda_mcp.crypto import SecretBox
from dr_panda_mcp.errors import (
    EnvironmentDisabled,
    EnvironmentKeyTaken,
    EnvironmentNotEmpty,
    EnvironmentNotFound,
    EnvironmentRequired,
    InvalidTarget,
    SecretUnavailable,
    StorageUnavailable,
    TargetNameTaken,
    TargetNotFound,
)
from dr_panda_mcp.store.models import (
    AuditRow,
    EnvironmentRow,
    SettingRow,
    SettingsHistoryRow,
    TargetRow,
)
from dr_panda_mcp.store.protocol import (
    TARGET_TYPES,
    AuditEntry,
    AuditRecord,
    Environment,
    SecretPatch,
    SettingsChange,
    Target,
    TargetDraft,
)

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


@dataclass(frozen=True)
class _EnvRef:
    id: int
    key: str
    title: str
    enabled: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def _target_update_summary(environment_key: str, patch: SecretPatch, *, notes_changed: bool) -> str:
    parts = [f"env={environment_key}", "options"]
    if notes_changed:
        parts.append("operator_notes")
    secret_bits: list[str] = []
    if patch.set:
        secret_bits.append("set=" + ",".join(sorted(patch.set)))
    if patch.clear:
        secret_bits.append("clear=" + ",".join(sorted(patch.clear)))
    if secret_bits:
        parts.append("secret:" + " ".join(secret_bits))
    return " ".join(parts)


def _contains(column, text: str):
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


class SqlConfigStore:
    """``ConfigStore`` 的 SQLite / MySQL / PostgreSQL 共用实现。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
    ) -> None:
        self._session_factory = session_factory
        self._box = secret_box

    async def ping(self) -> None:
        async with self._session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def list_environments(self) -> list[Environment]:
        async with self._session_factory() as session:
            envs = (
                (await session.execute(select(EnvironmentRow).order_by(EnvironmentRow.id)))
                .scalars()
                .all()
            )
            counts = (
                await session.execute(
                    select(TargetRow.environment_id, TargetRow.enabled, func.count()).group_by(
                        TargetRow.environment_id, TargetRow.enabled
                    )
                )
            ).all()
            tally: dict[int, dict[str, int]] = {}
            for environment_id, enabled, count in counts:
                bucket = tally.setdefault(int(environment_id), {"all": 0, "enabled": 0})
                bucket["all"] += int(count)
                if enabled:
                    bucket["enabled"] += int(count)
            return [_environment(row, tally.get(row.id, {})) for row in envs]

    async def create_environment(
        self, key: str, title: str, actor: str, *, enabled: bool = True
    ) -> Environment:
        key = _valid_key(key, "调用标识")
        title = _valid_title(title)
        now = utc_now()
        row = EnvironmentRow(
            key=key,
            title=title,
            enabled=bool(enabled),
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(row)
                session.add(
                    self._audit_row(
                        actor,
                        "environment.create",
                        key,
                        f"title={title}",
                        environment_key=key,
                    )
                )
                await session.flush()
                return _environment(row, {})
        except IntegrityError as exc:
            raise EnvironmentKeyTaken(f"调用标识 {key} 已存在") from exc
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def update_environment(
        self, environment_id: int, *, title: str, enabled: bool, actor: str
    ) -> Environment:
        title = _valid_title(title)
        enabled = bool(enabled)
        try:
            async with self._session_factory() as session, session.begin():
                row = await session.get(EnvironmentRow, environment_id)
                if row is None:
                    raise EnvironmentNotFound(f"环境 id={environment_id} 不存在")
                changed = row.title != title or row.enabled != enabled
                if row.enabled != enabled:
                    action = "environment.enable" if enabled else "environment.disable"
                else:
                    action = "environment.update"
                row.title = title
                row.enabled = enabled
                row.updated_at = utc_now()
                if changed:
                    session.add(
                        self._audit_row(
                            actor,
                            action,
                            row.key,
                            f"title={title} enabled={enabled}",
                            environment_key=row.key,
                        )
                    )
                counts = await self._environment_counts(session, row.id)
                return _environment(row, counts)
        except EnvironmentNotFound:
            raise
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def delete_environment(self, environment_id: int, actor: str) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                row = await session.get(EnvironmentRow, environment_id)
                if row is None:
                    raise EnvironmentNotFound(f"环境 id={environment_id} 不存在")
                count = await session.scalar(
                    select(func.count())
                    .select_from(TargetRow)
                    .where(TargetRow.environment_id == row.id)
                )
                if count:
                    raise EnvironmentNotEmpty(
                        f"环境 {row.title} 里还有 {int(count)} 个目标，先删除这些目标才能删除环境"
                    )
                key = row.key
                title = row.title
                await session.delete(row)
                session.add(
                    self._audit_row(
                        actor,
                        "environment.delete",
                        key,
                        f"title={title}",
                        environment_key=key,
                    )
                )
        except (EnvironmentNotFound, EnvironmentNotEmpty):
            raise
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def list_all(self) -> list[Target]:
        return await self._select_targets()

    async def list_by_type(self, type: str) -> list[Target]:
        return await self._select_targets(type=type)

    async def list_by_environment(self, key: str) -> list[Target]:
        env = await self._resolve_environment(key, require_enabled=False)
        return await self._select_targets(environment_id=env.id)

    async def get(self, name: str, *, environment: str = "") -> Target | None:
        return await self._get(name, environment, require_enabled=True)

    async def find(self, name: str, *, environment: str = "") -> Target | None:
        """按环境查找目标，不拒绝已停用的环境。网页保存前查重用这个方法。"""
        return await self._get(name, environment, require_enabled=False)

    async def get_by_id(self, target_id: int) -> Target | None:
        return await self._one_target(_joined_targets().where(TargetRow.id == target_id))

    async def create(self, draft: TargetDraft, actor: str) -> Target:
        draft = _validated(draft)
        env = await self._resolve_environment(draft.environment_key, require_enabled=False)
        now = utc_now()
        row = TargetRow(
            environment_id=env.id,
            type=draft.type,
            name=draft.name,
            enabled=draft.enabled,
            options_json=dict(draft.options),
            secret_json=self._box.encrypt(draft.name, draft.secret_patch.set, environment=env.key),
            created_at=now,
            updated_at=now,
            last_test_at=None,
            last_test_ok=None,
            last_test_error=None,
            operator_notes=draft.operator_notes,
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(row)
                    session.add(
                        self._audit_row(
                            actor,
                            "target.create",
                            draft.name,
                            f"env={env.key} type={draft.type}",
                            environment_key=env.key,
                        )
                    )
                    await session.flush()
                return self._to_target(row, env)
        except IntegrityError as exc:
            raise TargetNameTaken(f"目标名 {draft.name} 已存在") from exc
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def update(self, target_id: int, draft: TargetDraft, actor: str) -> Target:
        draft = _validated(draft)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await self._require_row(session, target_id)
                    env_row = await session.get(EnvironmentRow, row.environment_id)
                    if env_row is None:
                        raise StorageUnavailable("目标缺少所属环境")
                    if draft.name != row.name or draft.type != row.type:
                        raise InvalidTarget("target 的名称与类型创建后不可修改")
                    if draft.environment_key and draft.environment_key != env_row.key:
                        raise InvalidTarget("环境创建后不可修改")
                    envelope = dict(row.secret_json or {})
                    for field in draft.secret_patch.clear:
                        envelope.pop(field, None)
                    envelope.update(
                        self._box.encrypt(row.name, draft.secret_patch.set, environment=env_row.key)
                    )
                    notes_changed = (row.operator_notes or "") != draft.operator_notes
                    row.options_json = dict(draft.options)
                    row.secret_json = envelope
                    row.operator_notes = draft.operator_notes
                    row.updated_at = utc_now()
                    session.add(
                        self._audit_row(
                            actor,
                            "target.update",
                            row.name,
                            _target_update_summary(
                                env_row.key, draft.secret_patch, notes_changed=notes_changed
                            ),
                            environment_key=env_row.key,
                        )
                    )
                return self._to_target(row, env_row)
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def set_enabled(self, target_id: int, enabled: bool, actor: str) -> Target:
        action = "target.enable" if enabled else "target.disable"
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await self._require_row(session, target_id)
                    env_row = await session.get(EnvironmentRow, row.environment_id)
                    row.enabled = bool(enabled)
                    row.updated_at = utc_now()
                    session.add(
                        self._audit_row(
                            actor,
                            action,
                            row.name,
                            f"enabled={bool(enabled)}",
                            environment_key=env_row.key if env_row is not None else None,
                        )
                    )
                env_row = await session.get(EnvironmentRow, row.environment_id)
                if env_row is None:
                    raise StorageUnavailable("目标缺少所属环境")
                return self._to_target(row, env_row)
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def delete(self, target_id: int, actor: str) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                row = await self._require_row(session, target_id)
                name = row.name
                env_row = await session.get(EnvironmentRow, row.environment_id)
                await session.delete(row)
                session.add(
                    self._audit_row(
                        actor,
                        "target.delete",
                        name,
                        "deleted",
                        environment_key=env_row.key if env_row is not None else None,
                    )
                )
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def record_test(self, target_id: int, ok: bool, error: str | None, actor: str) -> Target:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await self._require_row(session, target_id)
                    env_row = await session.get(EnvironmentRow, row.environment_id)
                    row.last_test_at = utc_now()
                    row.last_test_ok = bool(ok)
                    row.last_test_error = _truncate(error, 512)
                    row.updated_at = utc_now()
                    summary = "ok" if ok else f"failed: {_truncate(error or '', 200)}"
                    session.add(
                        self._audit_row(
                            actor,
                            "target.test",
                            row.name,
                            summary,
                            environment_key=env_row.key if env_row is not None else None,
                            outcome="ok" if ok else "failed",
                        )
                    )
                env_row = await session.get(EnvironmentRow, row.environment_id)
                if env_row is None:
                    raise StorageUnavailable("目标缺少所属环境")
                return self._to_target(row, env_row)
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

    async def append_audit(self, entry: AuditEntry) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                session.add(
                    AuditRow(
                        created_at=utc_now(),
                        actor=entry.actor,
                        action=entry.action,
                        environment_key=entry.environment_key or None,
                        target_name=entry.target_name,
                        summary=_truncate(entry.summary, 1024),
                        outcome=entry.outcome,
                        error_detail=_truncate(entry.error_detail, 512),
                    )
                )
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc

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
    ) -> tuple[list[AuditRecord], int]:
        filters = [AuditRow.created_at >= since]
        if action:
            filters.append(AuditRow.action == action)
        elif actions:
            filters.append(AuditRow.action.in_(list(actions)))
        if environment_key:
            filters.append(AuditRow.environment_key == environment_key)
        if target_name:
            filters.append(_contains(AuditRow.target_name, target_name))
        if actor:
            filters.append(AuditRow.actor == actor)
        if outcome:
            filters.append(AuditRow.outcome == outcome)
        async with self._session_factory() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(AuditRow).where(*filters))
                or 0
            )
            rows = (
                (
                    await session.execute(
                        select(AuditRow)
                        .where(*filters)
                        .order_by(AuditRow.created_at.desc(), AuditRow.id.desc())
                        .offset(max(offset, 0))
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            AuditRecord(
                created_at=row.created_at,
                actor=row.actor,
                action=row.action,
                environment_key=row.environment_key,
                target_name=row.target_name,
                summary=row.summary,
                outcome=row.outcome,
                error_detail=row.error_detail,
            )
            for row in rows
        ], total

    async def cleanup_audit(
        self,
        retention_days: int,
        *,
        batch_size: int = 1000,
        max_seconds: float = 300.0,
    ) -> int:
        """分批删除早于保留期的审计；返回删除条数（planning 9.6）。"""
        cutoff = utc_now() - timedelta(days=retention_days)
        total = 0
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            async with self._session_factory() as session, session.begin():
                ids = (
                    (
                        await session.execute(
                            select(AuditRow.id)
                            .where(AuditRow.created_at < cutoff)
                            .order_by(AuditRow.created_at)
                            .limit(batch_size)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not ids:
                    break
                await session.execute(delete(AuditRow).where(AuditRow.id.in_(ids)))
            total += len(ids)
            if len(ids) < batch_size:
                break
        return total

    async def get_settings(self) -> dict[str, str]:
        async with self._session_factory() as session:
            rows = (await session.execute(select(SettingRow.key, SettingRow.value))).all()
        return {key: value for key, value in rows}

    async def update_settings(self, patch: Mapping[str, str], actor: str) -> dict[str, str]:
        if not patch:
            return await self.get_settings()
        now = utc_now()
        try:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(
                    select(SettingRow).where(SettingRow.key.in_(list(patch)))
                )
                existing = {row.key: row for row in result.scalars()}
                missing = [key for key in patch if key not in existing]
                if missing:
                    raise StorageUnavailable(
                        f"系统配置缺少定义：{missing[0]}；请先执行迁移"
                    )
                changed = {
                    key: value
                    for key, value in patch.items()
                    if existing[key].value != value
                }
                if not changed:
                    return await self.get_settings()
                changes: list[str] = []
                for key, value in changed.items():
                    row = existing[key]
                    old = row.value
                    row.value = value
                    row.updated_at = now
                    row.updated_by = actor
                    session.add(
                        SettingsHistoryRow(
                            key=key,
                            old_value=old,
                            new_value=value,
                            actor=actor,
                            changed_at=now,
                        )
                    )
                    changes.append(f"{key}: {old} -> {value}")
                session.add(self._audit_row(actor, "settings.update", None, "; ".join(changes)))
        except SQLAlchemyError as exc:
            raise StorageUnavailable(f"配置库写入失败：{exc}") from exc
        return await self.get_settings()

    async def list_settings_changes(self, limit: int = 5) -> list[SettingsChange]:
        if limit < 1:
            return []
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(SettingsHistoryRow)
                        .order_by(
                            SettingsHistoryRow.changed_at.desc(),
                            SettingsHistoryRow.id.desc(),
                        )
                        .limit(min(limit, 50))
                    )
                )
                .scalars()
                .all()
            )
        return [
            SettingsChange(
                created_at=row.changed_at,
                actor=row.actor,
                summary=f"{row.key}: {row.old_value} -> {row.new_value}",
                key=row.key,
                old_value=row.old_value,
                new_value=row.new_value,
            )
            for row in rows
        ]

    async def _get(self, name: str, environment: str, *, require_enabled: bool) -> Target | None:
        env = await self._resolve_environment(environment, require_enabled=require_enabled)
        return await self._one_target(
            _joined_targets().where(TargetRow.environment_id == env.id, TargetRow.name == name)
        )

    async def _resolve_environment(self, key: str, *, require_enabled: bool) -> _EnvRef:
        key = (key or "").strip()
        async with self._session_factory() as session:
            if key:
                row = (
                    await session.execute(select(EnvironmentRow).where(EnvironmentRow.key == key))
                ).scalar_one_or_none()
                if row is None:
                    choices = await _environment_choices(session)
                    suffix = f"。可选：{choices}" if choices else ""
                    raise EnvironmentNotFound(f"环境 {key} 未登记{suffix}")
            else:
                rows = (
                    (await session.execute(select(EnvironmentRow).order_by(EnvironmentRow.id)))
                    .scalars()
                    .all()
                )
                if len(rows) == 1:
                    row = rows[0]
                elif not rows:
                    raise EnvironmentNotFound("还没有登记任何环境")
                else:
                    choices = "、".join(f"{item.key}（{item.title}）" for item in rows)
                    raise EnvironmentRequired(
                        f"登记了多个环境，调用时必须传入 environment。可选：{choices}"
                    )
            if require_enabled and not row.enabled:
                raise EnvironmentDisabled(f"环境 {row.key}（{row.title}）已停用")
            return _EnvRef(row.id, row.key, row.title, bool(row.enabled))

    async def _environment_counts(
        self, session: AsyncSession, environment_id: int
    ) -> dict[str, int]:
        counts = (
            await session.execute(
                select(TargetRow.enabled, func.count())
                .where(TargetRow.environment_id == environment_id)
                .group_by(TargetRow.enabled)
            )
        ).all()
        tally = {"all": 0, "enabled": 0}
        for enabled, count in counts:
            tally["all"] += int(count)
            if enabled:
                tally["enabled"] += int(count)
        return tally

    async def _select_targets(
        self, *, type: str | None = None, environment_id: int | None = None
    ) -> list[Target]:
        query = _joined_targets().order_by(TargetRow.type, TargetRow.name)
        if type is not None:
            query = query.where(TargetRow.type == type)
        if environment_id is not None:
            query = query.where(TargetRow.environment_id == environment_id)
        async with self._session_factory() as session:
            rows = (await session.execute(query)).all()
            return [self._to_target(target, env) for target, env in rows]

    async def _one_target(self, query) -> Target | None:
        async with self._session_factory() as session:
            row = (await session.execute(query)).one_or_none()
            if row is None:
                return None
            return self._to_target(row[0], row[1])

    async def _require_row(self, session: AsyncSession, target_id: int) -> TargetRow:
        row = await session.get(TargetRow, target_id)
        if row is None:
            raise TargetNotFound(f"目标 id={target_id} 不存在")
        return row

    def _audit_row(
        self,
        actor: str,
        action: str,
        target_name: str | None,
        summary: str | None,
        environment_key: str | None = None,
        outcome: str | None = None,
    ) -> AuditRow:
        return AuditRow(
            created_at=utc_now(),
            actor=actor,
            action=action,
            environment_key=environment_key or None,
            target_name=target_name,
            summary=_truncate(summary, 1024),
            outcome=outcome,
        )

    def _to_target(self, row: TargetRow, env: EnvironmentRow | _EnvRef) -> Target:
        envelopes: dict[str, Any] = row.secret_json or {}
        secret: dict[str, str] = {}
        secret_ok = True
        for field, envelope in envelopes.items():
            try:
                secret[field] = self._box.decrypt_field(
                    row.name, field, envelope, environment=env.key
                )
            except SecretUnavailable as exc:
                logger.warning("目标 %s 的密钥无法解密：%s", row.name, exc)
                secret_ok = False
        if not secret_ok:
            secret = {}
        return Target(
            id=row.id,
            type=row.type,
            name=row.name,
            enabled=row.enabled,
            options=dict(row.options_json or {}),
            secret=secret,
            secret_fields=frozenset(envelopes),
            secret_ok=secret_ok,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_test_at=row.last_test_at,
            last_test_ok=row.last_test_ok,
            last_test_error=row.last_test_error,
            environment_key=env.key,
            environment_title=env.title,
            environment_enabled=env.enabled,
            operator_notes=row.operator_notes or "",
        )


def _validated(draft: TargetDraft) -> TargetDraft:
    name = (draft.name or "").strip()
    if not _NAME_RE.match(name):
        raise InvalidTarget("名称只允许小写字母、数字与连字符，以字母或数字开头结尾，最长 64")
    if draft.type not in TARGET_TYPES:
        raise InvalidTarget(f"未知的目标类型：{draft.type}")
    if not isinstance(draft.options, dict):
        raise InvalidTarget("options 必须是对象")
    if not isinstance(draft.secret_patch, SecretPatch):
        raise InvalidTarget("secret_patch 必须是 SecretPatch")
    for field, value in draft.secret_patch.set.items():
        if not field or not isinstance(value, str):
            raise InvalidTarget("密钥字段名不能为空，值必须是字符串")
    for field in draft.secret_patch.clear:
        if not field:
            raise InvalidTarget("要清除的密钥字段名不能为空")
    environment_key = (draft.environment_key or "").strip()
    if environment_key and not _NAME_RE.match(environment_key):
        raise InvalidTarget("调用标识只允许小写字母、数字与连字符，以字母或数字开头结尾，最长 64")
    operator_notes = (draft.operator_notes or "").strip()
    if len(operator_notes) > 512:
        raise InvalidTarget("排查提示最长 512 个字符")
    return TargetDraft(
        name=name,
        type=draft.type,
        enabled=bool(draft.enabled),
        options=dict(draft.options),
        secret_patch=draft.secret_patch,
        environment_key=environment_key,
        operator_notes=operator_notes,
    )


def _joined_targets():
    return select(TargetRow, EnvironmentRow).join(
        EnvironmentRow, TargetRow.environment_id == EnvironmentRow.id
    )


def _environment(row: EnvironmentRow, counts: dict[str, int]) -> Environment:
    return Environment(
        id=row.id,
        key=row.key,
        title=row.title,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
        target_count=int(counts.get("all", 0)),
        enabled_target_count=int(counts.get("enabled", 0)),
    )


def _valid_key(value: str, label: str) -> str:
    key = (value or "").strip()
    if not _NAME_RE.match(key):
        raise InvalidTarget(f"{label}只允许小写字母、数字与连字符，以字母或数字开头结尾，最长 64")
    return key


def _valid_title(value: str) -> str:
    title = " ".join((value or "").split())
    if not title:
        raise InvalidTarget("展示名不能为空")
    if len(title) > 64:
        raise InvalidTarget("展示名最长 64 个字符")
    return title


async def _environment_choices(session: AsyncSession) -> str:
    rows = (
        (await session.execute(select(EnvironmentRow).order_by(EnvironmentRow.id))).scalars().all()
    )
    return "、".join(f"{row.key}（{row.title}）" for row in rows)


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 1] + "…"
