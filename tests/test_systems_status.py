from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from dr_panda_mcp import auth
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.server import create_server
from dr_panda_mcp.store.models import AuditRow


async def test_systems_status_tool_listed(runtime: Runtime) -> None:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        tools = await client.list_tools()

    names = sorted(tool.name for tool in tools)
    assert "systems_status" in names
    systems_tool = next(tool for tool in tools if tool.name == "systems_status")
    assert systems_tool.annotations is not None
    assert systems_tool.annotations.read_only_hint is True


async def test_systems_status_returns_envelope(runtime: Runtime) -> None:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        result = await client.call_tool("systems_status", {})

    payload = result.structured_content
    assert payload is not None
    assert set(payload) == {
        "target",
        "type",
        "summary",
        "time_range",
        "returned",
        "truncated",
        "truncation",
        "elapsed_ms",
        "rows",
        "stats",
        "notes",
    }
    assert payload["target"] == "*"
    assert payload["type"] == "all"
    assert payload["rows"] == [
        {
            "key": "default",
            "title": "Default",
            "enabled": True,
            "targets": 0,
            "enabled_targets": 0,
        }
    ]
    assert payload["stats"]["environments"] == 1
    assert payload["stats"]["targets"] == 0
    assert payload["notes"]


async def test_systems_status_is_audited(runtime: Runtime) -> None:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        with auth.use_actor(
            "admin",
            client=auth.ClientIdentity(name="Cursor", prefix="abcdefghijkl"),
        ):
            await client.call_tool("systems_status", {"environment": "default"})
            with pytest.raises(ToolError):
                await client.call_tool("systems_status", {"environment": "missing"})

    async with runtime.session_factory() as session:
        rows = (
            await session.execute(
                select(AuditRow).where(AuditRow.action == "tool.call").order_by(AuditRow.id)
            )
        ).scalars().all()

    assert rows[0].environment_key == "default"
    assert rows[0].summary is not None
    assert "systems_status" in rows[0].summary
    assert "client=Cursor" in rows[0].summary
    assert "prefix=abcdefghijkl" in rows[0].summary
    assert "error=-" in rows[0].summary
    assert rows[1].environment_key == "missing"
    assert rows[1].summary is not None
    assert "error=-" not in rows[1].summary


async def test_systems_status_exposes_non_secret_target_scope(runtime: Runtime) -> None:
    from dr_panda_mcp.store.protocol import SecretPatch, TargetDraft

    targets = [
        ("mysql-a", "mysql", {"allowed_dbs": ["chat", "logs"], "default_db": "chat"}),
        ("mongo-a", "mongo", {"allowed_dbs": ["events"], "default_db": "events"}),
        ("es-a", "elasticsearch", {"allowed_indices": ["test_orders"]}),
        ("redis-a", "redis", {"key_prefix": "orders:"}),
        ("rabbit-a", "rabbitmq", {"allowed_vhosts": ["cloud_21_test"]}),
        ("kafka-a", "kafka", {"allowed_topics": ["orders.created"]}),
        ("cls-a", "cls", {"allowed_topics": ["logset/topic-a"]}),
        ("gitlab-a", "gitlab", {"allowed_projects": ["group/app"]}),
    ]
    for name, type_, options in targets:
        await runtime.store.create(
            TargetDraft(
                name=name,
                type=type_,
                enabled=True,
                options=options,
                secret_patch=SecretPatch(set={}),
                environment_key="default",
            ),
            "anonymous",
        )

    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        result = await client.call_tool("systems_status", {"environment": "default"})

    payload = result.structured_content
    assert payload is not None
    rows = {row["name"]: row for row in payload["rows"]}
    assert rows["mysql-a"]["scope"] == {
        "allowed_dbs": ["chat", "logs"],
        "default_db": "chat",
    }
    assert rows["mongo-a"]["scope"] == {
        "allowed_dbs": ["events"],
        "default_db": "events",
    }
    assert rows["es-a"]["scope"] == {"allowed_indices": ["test_orders"]}
    assert rows["redis-a"]["scope"] == {"key_prefix": "orders:"}
    assert rows["rabbit-a"]["scope"] == {"allowed_vhosts": ["cloud_21_test"]}
    assert rows["kafka-a"]["scope"] == {"allowed_topics": ["orders.created"]}
    assert rows["cls-a"]["scope"] == {"allowed_topics": ["logset/topic-a"]}
    assert rows["gitlab-a"]["scope"] == {"allowed_projects": ["group/app"]}
    assert any("logsetId/topicId" in note for note in payload["notes"])
    assert "secret" not in str(payload).lower()
