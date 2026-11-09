from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import make_url

from dr_panda_mcp import settings
from dr_panda_mcp.crypto import SecretBox
from dr_panda_mcp.errors import (
    InvalidSettings,
    InvalidTarget,
    TargetNameTaken,
    TargetNotFound,
)
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.store.protocol import AuditEntry, SecretPatch, Settings, TargetDraft
from dr_panda_mcp.store.repository import SqlConfigStore

SECRET_VALUE = "p@ss-明文-值"


def _draft(
    name: str = "order-mysql",
    type_: str = "mysql",
    options: dict[str, Any] | None = None,
    set_secrets: dict[str, str] | None = None,
    clear: tuple[str, ...] = (),
    enabled: bool = True,
    operator_notes: str = "",
) -> TargetDraft:
    return TargetDraft(
        name=name,
        type=type_,
        enabled=enabled,
        options=options if options is not None else {"host": "127.0.0.1"},
        secret_patch=SecretPatch(set=set_secrets or {}, clear=frozenset(clear)),
        operator_notes=operator_notes,
    )


def _db_path(runtime: Runtime) -> Path:
    return Path(make_url(str(runtime.engine.url)).database)


def _raw(runtime: Runtime, sql: str, params: tuple = ()) -> list[tuple]:
    with sqlite3.connect(_db_path(runtime)) as connection:
        return connection.execute(sql, params).fetchall()


async def test_create_and_get(runtime: Runtime) -> None:
    created = await runtime.store.create(
        _draft(set_secrets={"password": SECRET_VALUE, "token": "tok"}),
        "anonymous",
    )

    assert created.id > 0
    assert created.type == "mysql"
    assert created.enabled is True
    assert created.secret_fields == frozenset({"password", "token"})
    assert created.secret_ok is True
    assert created.secret == {"password": SECRET_VALUE, "token": "tok"}

    fetched = await runtime.store.get("order-mysql")
    assert fetched is not None
    assert fetched.name == created.name
    assert fetched.secret == created.secret
    assert fetched.created_at == created.created_at


async def test_duplicate_name_rejected(runtime: Runtime) -> None:
    await runtime.store.create(_draft(), "anonymous")

    with pytest.raises(TargetNameTaken):
        await runtime.store.create(_draft(), "anonymous")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "Order-mysql"},
        {"name": "order_mysql"},
        {"name": "-order"},
        {"name": "order-"},
        {"name": "a" * 65},
        {"type_": "oracle"},
    ],
)
async def test_invalid_target_rejected(runtime: Runtime, kwargs: dict[str, Any]) -> None:
    with pytest.raises(InvalidTarget):
        await runtime.store.create(_draft(**kwargs), "anonymous")


async def test_invalid_options_rejected(runtime: Runtime) -> None:
    draft = TargetDraft(
        name="order-mysql",
        type="mysql",
        enabled=True,
        options="not-a-dict",  # type: ignore[arg-type]
        secret_patch=SecretPatch(),
    )

    with pytest.raises(InvalidTarget):
        await runtime.store.create(draft, "anonymous")


async def test_list_and_filter(runtime: Runtime) -> None:
    for name, type_ in [
        ("order-mysql", "mysql"),
        ("pay-redis", "redis"),
        ("search-es", "elasticsearch"),
    ]:
        await runtime.store.create(_draft(name=name, type_=type_), "anonymous")

    all_names = [target.name for target in await runtime.store.list_all()]
    assert all_names == ["search-es", "order-mysql", "pay-redis"]

    redis_targets = await runtime.store.list_by_type("redis")
    assert [target.name for target in redis_targets] == ["pay-redis"]


async def test_enable_disable_and_audit(runtime: Runtime) -> None:
    created = await runtime.store.create(_draft(), "anonymous")

    disabled = await runtime.store.set_enabled(created.id, False, "anonymous")
    assert disabled.enabled is False

    fetched = await runtime.store.get("order-mysql")
    assert fetched is not None and fetched.enabled is False

    actions = [row[0] for row in _raw(runtime, "SELECT action FROM audit")]
    assert "target.disable" in actions


async def test_secret_patch_semantics(runtime: Runtime) -> None:
    created = await runtime.store.create(
        _draft(set_secrets={"password": "old-pass", "token": "keep-me"}),
        "anonymous",
    )

    updated = await runtime.store.update(
        created.id,
        _draft(
            options={"host": "10.0.0.1"},
            set_secrets={"api_key": "new-key"},
            clear=("password",),
        ),
        "anonymous",
    )

    assert updated.options == {"host": "10.0.0.1"}
    assert updated.secret_fields == frozenset({"token", "api_key"})
    assert updated.secret == {"token": "keep-me", "api_key": "new-key"}
    assert updated.secret_ok is True
    summary, environment_key = _raw(
        runtime,
        "SELECT summary, environment_key FROM audit WHERE action = 'target.update'",
    )[-1]
    assert environment_key == "default"
    assert "secret:set=api_key clear=password" in summary
    assert "old-pass" not in summary
    assert "new-key" not in summary


async def test_name_and_type_are_immutable(runtime: Runtime) -> None:
    created = await runtime.store.create(_draft(), "anonymous")

    with pytest.raises(InvalidTarget):
        await runtime.store.update(created.id, _draft(name="other-mysql"), "anonymous")
    with pytest.raises(InvalidTarget):
        await runtime.store.update(
            created.id, _draft(type_="redis"), "anonymous"
        )


async def test_secret_is_encrypted_at_rest(runtime: Runtime) -> None:
    await runtime.store.create(
        _draft(set_secrets={"password": SECRET_VALUE}), "anonymous"
    )

    raw_rows = _raw(runtime, "SELECT secret_json FROM targets")
    assert raw_rows
    raw_text = raw_rows[0][0]
    assert SECRET_VALUE not in raw_text

    envelopes = json.loads(raw_text)
    assert set(envelopes) == {"password"}
    assert set(envelopes["password"]) == {"v", "kid", "nonce", "ct"}


async def test_aad_blocks_cross_target_ciphertext_swap(runtime: Runtime) -> None:
    first = await runtime.store.create(
        _draft(name="order-mysql", set_secrets={"password": "a-secret"}), "anonymous"
    )
    await runtime.store.create(
        _draft(name="pay-mysql", set_secrets={"password": "b-secret"}), "anonymous"
    )
    swapped = _raw(
        runtime, "SELECT secret_json FROM targets WHERE name = ?", ("order-mysql",)
    )[0][0]
    with sqlite3.connect(_db_path(runtime)) as connection:
        connection.execute(
            "UPDATE targets SET secret_json = ? WHERE name = ?",
            (swapped, "pay-mysql"),
        )

    fetched = await runtime.store.get("pay-mysql")
    assert fetched is not None
    assert fetched.secret_fields == frozenset({"password"})
    assert fetched.secret_ok is False
    assert fetched.secret == {}
    assert first.id > 0


async def test_wrong_key_marks_secret_unavailable(runtime: Runtime) -> None:
    await runtime.store.create(
        _draft(set_secrets={"password": SECRET_VALUE}), "anonymous"
    )
    other_store = SqlConfigStore(runtime.session_factory, SecretBox(b"\x09" * 32))

    fetched = await other_store.get("order-mysql")
    assert fetched is not None
    assert fetched.secret_ok is False
    assert fetched.secret == {}
    assert fetched.secret_fields == frozenset({"password"})


async def test_utc_roundtrip(runtime: Runtime) -> None:
    created = await runtime.store.create(_draft(), "anonymous")
    fetched = await runtime.store.get("order-mysql")

    assert fetched is not None
    assert fetched.created_at == created.created_at
    assert fetched.created_at.utcoffset() == timedelta(0)
    assert fetched.updated_at.utcoffset() == timedelta(0)


async def test_options_json_roundtrip(runtime: Runtime) -> None:
    options = {"host": "127.0.0.1", "nested": {"a": [1, 2]}, "flag": True}
    created = await runtime.store.create(_draft(options=options), "anonymous")
    fetched = await runtime.store.get("order-mysql")

    assert created.options == options
    assert fetched is not None and fetched.options == options


async def test_settings_defaults(runtime: Runtime) -> None:
    assert await runtime.store.get_settings() == {
        "audit_retention_days": "90",
        "target_max_concurrency": "10",
        "default_target_timeout_s": "15",
        "default_target_max_rows": "100",
        "default_target_max_bytes": "102400",
        "audit_cleanup_interval_minutes": "60",
        "catalog_max_clients": "32",
        "backup_keep_count": "20",
        "session_ttl_minutes": "720",
        "login_max_attempts": "5",
        "login_lockout_minutes": "5",
        "mcp_token_max_per_user": "5",
        "mcp_token_ttl_days": "0",
        "global_max_concurrent_calls": "0",
        "catalog_idle_seconds": "0",
        "audit_cleanup_batch_size": "1000",
        "audit_cleanup_max_seconds": "300",
    }
    assert await settings.load(runtime.store) == Settings(
        audit_retention_days=90, target_max_concurrency=10
    )


async def test_settings_noop_update_writes_no_history_or_audit(
    runtime: Runtime,
) -> None:
    audit_before = _raw(runtime, "SELECT COUNT(*) FROM audit")[0][0]
    history_before = _raw(runtime, "SELECT COUNT(*) FROM settings_history")[0][0]

    await settings.update(
        runtime.store, {"audit_retention_days": "90"}, "anonymous"
    )

    assert _raw(runtime, "SELECT COUNT(*) FROM audit")[0][0] == audit_before
    assert (
        _raw(runtime, "SELECT COUNT(*) FROM settings_history")[0][0]
        == history_before
    )


async def test_settings_partial_patch_records_only_changed_keys(
    runtime: Runtime,
) -> None:
    await settings.update(
        runtime.store,
        {"audit_retention_days": "30", "target_max_concurrency": "10"},
        "anonymous",
    )

    rows = _raw(
        runtime,
        "SELECT key, old_value, new_value FROM settings_history ORDER BY id",
    )
    assert rows == [("audit_retention_days", "90", "30")]
    summary = _raw(
        runtime, "SELECT summary FROM audit WHERE action = 'settings.update'"
    )[0][0]
    assert "audit_retention_days: 90 -> 30" in summary
    assert "target_max_concurrency" not in summary


async def test_settings_update_is_audited(runtime: Runtime) -> None:
    result = await settings.update(
        runtime.store, {"audit_retention_days": "30"}, "anonymous"
    )

    assert result == Settings(audit_retention_days=30, target_max_concurrency=10)
    rows = _raw(
        runtime,
        "SELECT summary FROM audit WHERE action = 'settings.update'",
    )
    assert rows
    assert "audit_retention_days: 90 -> 30" in rows[0][0]


@pytest.mark.parametrize(
    "patch",
    [
        {"target_max_concurrency": "0"},
        {"audit_retention_days": "3651"},
        {"audit_retention_days": "abc"},
        {"readonly": "false"},
    ],
)
async def test_settings_invalid_rejected_without_side_effects(
    runtime: Runtime, patch: dict[str, str]
) -> None:
    audit_before = _raw(runtime, "SELECT COUNT(*) FROM audit")[0][0]

    with pytest.raises(InvalidSettings):
        await settings.update(runtime.store, patch, "anonymous")

    assert await runtime.store.get_settings() == {
        "audit_retention_days": "90",
        "target_max_concurrency": "10",
        "default_target_timeout_s": "15",
        "default_target_max_rows": "100",
        "default_target_max_bytes": "102400",
        "audit_cleanup_interval_minutes": "60",
        "catalog_max_clients": "32",
        "backup_keep_count": "20",
        "session_ttl_minutes": "720",
        "login_max_attempts": "5",
        "login_lockout_minutes": "5",
        "mcp_token_max_per_user": "5",
        "mcp_token_ttl_days": "0",
        "global_max_concurrent_calls": "0",
        "catalog_idle_seconds": "0",
        "audit_cleanup_batch_size": "1000",
        "audit_cleanup_max_seconds": "300",
    }
    assert _raw(runtime, "SELECT COUNT(*) FROM audit")[0][0] == audit_before


async def test_rollback_when_audit_write_fails(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self, *args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(SqlConfigStore, "_audit_row", boom)

    with pytest.raises(RuntimeError, match="audit down"):
        await runtime.store.create(_draft(), "anonymous")

    assert await runtime.store.get("order-mysql") is None
    assert await runtime.store.list_all() == []


async def test_record_test_and_delete(runtime: Runtime) -> None:
    created = await runtime.store.create(_draft(), "anonymous")

    tested = await runtime.store.record_test(created.id, True, None, "anonymous")
    assert tested.last_test_ok is True
    assert tested.last_test_at is not None

    failed = await runtime.store.record_test(
        created.id, False, "connection refused", "anonymous"
    )
    assert failed.last_test_ok is False
    assert failed.last_test_error == "connection refused"

    await runtime.store.delete(created.id, "anonymous")
    assert await runtime.store.get("order-mysql") is None

    actions = [row[0] for row in _raw(runtime, "SELECT action FROM audit")]
    assert "target.test" in actions
    assert "target.delete" in actions


async def test_missing_target_raises(runtime: Runtime) -> None:
    with pytest.raises(TargetNotFound):
        await runtime.store.update(999, _draft(), "anonymous")
    with pytest.raises(TargetNotFound):
        await runtime.store.set_enabled(999, False, "anonymous")
    with pytest.raises(TargetNotFound):
        await runtime.store.delete(999, "anonymous")


async def test_append_audit(runtime: Runtime) -> None:
    await runtime.store.append_audit(
        AuditEntry(actor="anonymous", action="app.start", summary="test")
    )

    rows = _raw(runtime, "SELECT actor, action, summary FROM audit")
    assert rows == [("anonymous", "app.start", "test")]


async def test_audit_error_detail_persisted(runtime: Runtime) -> None:
    await runtime.store.append_audit(
        AuditEntry(
            actor="admin",
            action="tool.call",
            summary="select 1",
            outcome="failed",
            error_detail="connection refused",
        )
    )

    since = datetime(2000, 1, 1, tzinfo=UTC)
    rows, _total = await runtime.store.list_audit(since=since)
    assert rows[0].error_detail == "connection refused"
    assert _raw(runtime, "SELECT error_detail FROM audit") == [("connection refused",)]


async def test_concurrent_same_name_only_one_wins(runtime: Runtime) -> None:
    results = await asyncio.gather(
        runtime.store.create(_draft(), "anonymous"),
        runtime.store.create(_draft(), "anonymous"),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], TargetNameTaken)


async def test_settings_changes_are_listed(runtime: Runtime) -> None:
    await settings.update(
        runtime.store, {"audit_cleanup_interval_minutes": "15"}, "anonymous"
    )
    changes = await runtime.store.list_settings_changes(5)
    assert changes
    assert "audit_cleanup_interval_minutes" in (changes[0].summary or "")
    assert changes[0].actor == "anonymous"


async def test_settings_history_keeps_old_and_new_values(runtime: Runtime) -> None:
    await settings.update(
        runtime.store, {"catalog_max_clients": "64"}, "anonymous"
    )
    changes = await runtime.store.list_settings_changes(5)
    latest = changes[0]
    assert latest.key == "catalog_max_clients"
    assert latest.old_value == "32"
    assert latest.new_value == "64"
    assert latest.summary == "catalog_max_clients: 32 -> 64"


async def test_audit_outcome_persisted_and_filterable(runtime: Runtime) -> None:
    await runtime.store.append_audit(
        AuditEntry(actor="admin", action="tool.call", summary="select 1", outcome="ok")
    )
    await runtime.store.append_audit(
        AuditEntry(actor="admin", action="tool.call", summary="select 2", outcome="failed")
    )
    await runtime.store.append_audit(
        AuditEntry(actor="admin", action="target.create", summary="created")
    )

    since = datetime(2000, 1, 1, tzinfo=UTC)
    failed, failed_total = await runtime.store.list_audit(since=since, outcome="failed")
    ok, ok_total = await runtime.store.list_audit(since=since, outcome="ok")
    everything, everything_total = await runtime.store.list_audit(since=since)

    assert [row.summary for row in failed] == ["select 2"]
    assert failed_total == 1
    assert [row.summary for row in ok] == ["select 1"]
    assert ok_total == 1
    assert everything_total == 3
    assert {row.summary: row.outcome for row in everything} == {
        "select 1": "ok",
        "select 2": "failed",
        "created": None,
    }
    assert _raw(runtime, "SELECT summary, outcome FROM audit ORDER BY id")[-1] == (
        "created",
        None,
    )


async def test_operator_notes_roundtrip_and_update(runtime: Runtime) -> None:
    created = await runtime.store.create(
        _draft(operator_notes="生产主库，只读排障。"),
        "anonymous",
    )
    assert created.operator_notes == "生产主库，只读排障。"

    updated = await runtime.store.update(
        created.id,
        _draft(operator_notes="生产主库，默认看最近 30 分钟。"),
        "anonymous",
    )
    assert updated.operator_notes == "生产主库，默认看最近 30 分钟。"
    fetched = await runtime.store.get("order-mysql")
    assert fetched is not None and fetched.operator_notes == updated.operator_notes


async def test_operator_notes_are_bounded(runtime: Runtime) -> None:
    with pytest.raises(InvalidTarget):
        await runtime.store.create(_draft(operator_notes="x" * 513), "anonymous")
