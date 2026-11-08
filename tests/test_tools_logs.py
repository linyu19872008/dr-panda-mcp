from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dr_panda_mcp import errors
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.server import create_server
from dr_panda_mcp.store.protocol import SecretPatch, TargetDraft
from dr_panda_mcp.tools import logs as logs_module

CLS_ROW = {"time": "2026-01-01T01:00:00+00:00", "topic": "logset/app", "content": "boom"}


class FakeCLSConnector:
    name = "cls"

    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.context_calls: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = [dict(CLS_ROW) for _ in range(3)]
        self.error: Exception | None = None

    def probe_guard(self):
        raise NotImplementedError

    def create_client(self, target):
        return object()

    async def probe(self, client, target):
        return None

    async def close_client(self, client):
        return None

    async def search_log(self, client, target, **kwargs):
        self.search_calls.append(kwargs)
        if self.error:
            raise self.error
        return [dict(row) for row in self.rows], {
            "mode": "search",
            "next_context": "ctx-next",
            "list_over": False,
            "sort": kwargs.get("sort") or "desc",
        }

    async def describe_context(self, client, target, **kwargs):
        self.context_calls.append(kwargs)
        return [dict(CLS_ROW)]


class FakeGitLabConnector:
    name = "gitlab"

    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.file_calls: list[dict[str, Any]] = []
        self.blame_calls: list[dict[str, Any]] = []
        self.file_content = "print('hello')"
        self.search_rows = [
            {"path": "app/main.py", "startline": 12, "data": "raise ValueError"}
        ]
        self.blame_rows = [
            {
                "commit": {"short_id": "abc12345", "author_name": "Lin", "committed_date": "2026-01-01"},
                "lines": ["line one", "line two"],
            }
        ]
        self.error: Exception | None = None

    def create_client(self, target):
        return object()

    async def probe(self, client, target):
        return None

    async def close_client(self, client):
        return None

    async def search_code(self, client, target, **kwargs):
        self.search_calls.append(kwargs)
        if self.error:
            raise self.error
        return [dict(row) for row in self.search_rows]

    async def get_file(self, client, target, **kwargs):
        self.file_calls.append(kwargs)
        return self.file_content, False

    async def blame(self, client, target, **kwargs):
        self.blame_calls.append(kwargs)
        return [dict(group) for group in self.blame_rows]


async def _create_cls_target(runtime: Runtime, *, max_rows: int = 2) -> None:
    await runtime.store.create(
        TargetDraft(
            name="logs-cls",
            type="cls",
            enabled=True,
            options={
                "region": "ap-guangzhou",
                "allowed_topics": ["logset/app"],
                "max_rows": max_rows,
                "max_bytes": 102400,
                "timeout_s": 15,
            },
            secret_patch=SecretPatch(
                set={"secret_id": "sid", "secret_key": "secret-key-value"}
            ),
        ),
        "anonymous",
    )


async def _create_gitlab_target(runtime: Runtime, *, max_bytes: int = 102400) -> None:
    await runtime.store.create(
        TargetDraft(
            name="code-gitlab",
            type="gitlab",
            enabled=True,
            options={
                "base_url": "https://gitlab.example.com",
                "allowed_projects": ["group/app"],
                "max_rows": 20,
                "max_bytes": max_bytes,
                "timeout_s": 15,
            },
            secret_patch=SecretPatch(set={"token": "token-value"}),
        ),
        "anonymous",
    )


def _patch_connectors(monkeypatch: pytest.MonkeyPatch, cls, gitlab) -> None:
    def fake(type_: str):
        return cls if type_ == "cls" else gitlab

    monkeypatch.setattr(logs_module, "get_connector", fake)


async def _call(runtime: Runtime, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    return result.structured_content


async def test_tools_and_prompt_listed(runtime: Runtime) -> None:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        tools = await client.list_tools()
        prompts = await client.list_prompts()

    names = {tool.name for tool in tools}
    assert {
        "cls_context",
        "cls_search",
        "gitlab_blame",
        "gitlab_get_file",
        "gitlab_search_code",
        "systems_status",
    } <= names
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
    assert [prompt.name for prompt in prompts] == ["investigate_error"]


async def test_cls_search_envelope_and_truncation(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    fake = FakeCLSConnector()
    _patch_connectors(monkeypatch, fake, FakeGitLabConnector())

    payload = await _call(
        runtime,
        "cls_search",
        {
            "target": "logs-cls",
            "query": "level:ERROR",
            "topic": "logset/app",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-01T01:00:00Z",
        },
    )

    assert payload["target"] == "logs-cls"
    assert payload["type"] == "cls"
    assert payload["time_range"]["from"] == "2026-01-01T00:00:00Z"
    assert payload["returned"] == 2
    assert payload["truncated"] is True
    assert payload["truncation"]["reason"] == "rows"
    assert payload["notes"]
    assert fake.search_calls[0]["topic"] == "logset/app"
    assert fake.search_calls[0]["limit"] == 3


async def test_cls_search_dangerous_window(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    fake = FakeCLSConnector()
    _patch_connectors(monkeypatch, fake, FakeGitLabConnector())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "cls_search",
                {
                    "target": "logs-cls",
                    "query": "level:ERROR",
                    "topic": "logset/app",
                    "from": "2026-01-01T00:00:00Z",
                    "to": "2026-01-03T00:00:00Z",
                },
            )

    assert errors.DANGEROUS_OPERATION in str(excinfo.value)
    assert fake.search_calls == []


async def test_cls_search_requires_window_and_scope(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    fake = FakeCLSConnector()
    _patch_connectors(monkeypatch, fake, FakeGitLabConnector())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as bad_window:
            await client.call_tool(
                "cls_search",
                {
                    "target": "logs-cls",
                    "query": "x",
                    "topic": "logset/app",
                    "from": "not-a-time",
                    "to": "2026-01-01T01:00:00Z",
                },
            )
        with pytest.raises(ToolError) as bad_topic:
            await client.call_tool(
                "cls_search",
                {
                    "target": "logs-cls",
                    "query": "x",
                    "topic": "logset/other",
                    "from": "2026-01-01T00:00:00Z",
                    "to": "2026-01-01T01:00:00Z",
                },
            )

    assert errors.GUARD_REJECTED in str(bad_window.value)
    assert errors.SCOPE_DENIED in str(bad_topic.value)
    assert fake.search_calls == []


async def test_cls_context_and_validation(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    fake = FakeCLSConnector()
    _patch_connectors(monkeypatch, fake, FakeGitLabConnector())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        result = await client.call_tool(
            "cls_context",
            {
                "target": "logs-cls",
                "topic": "logset/app",
                "log_id": "pkg-1",
                "btime": "2026-01-01 09:00:00.000",
                "pkg_log_id": 123,
            },
        )
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "cls_context",
                {
                    "target": "logs-cls",
                    "topic": "logset/app",
                    "log_id": "pkg-1",
                    "btime": "2026-01-01 09:00:00.000",
                    "pkg_log_id": 123,
                    "before": 99,
                },
            )

    payload = result.structured_content
    assert payload is not None
    assert payload["rows"][0]["content"] == "boom"
    assert errors.INVALID_ARGUMENT in str(excinfo.value)
    assert fake.context_calls[0]["before"] == 10
    assert fake.context_calls[0]["btime"] == "2026-01-01 09:00:00.000"
    assert fake.context_calls[0]["pkg_log_id"] == 123


async def test_gitlab_search_code_scoped_to_allowed_projects(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_gitlab_target(runtime)
    fake_gitlab = FakeGitLabConnector()
    _patch_connectors(monkeypatch, FakeCLSConnector(), fake_gitlab)

    payload = await _call(
        runtime, "gitlab_search_code", {"target": "code-gitlab", "query": "ValueError"}
    )

    assert payload["returned"] == 1
    assert payload["rows"][0]["project"] == "group/app"
    assert payload["rows"][0]["path"] == "app/main.py"
    assert fake_gitlab.search_calls[0]["project"] == "group/app"


async def test_gitlab_scope_denied(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_gitlab_target(runtime)
    _patch_connectors(monkeypatch, FakeCLSConnector(), FakeGitLabConnector())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "gitlab_search_code",
                {"target": "code-gitlab", "query": "x", "project": "other/repo"},
            )

    assert errors.SCOPE_DENIED in str(excinfo.value)


async def test_gitlab_get_file_truncates_bytes(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_gitlab_target(runtime, max_bytes=4096)
    fake_gitlab = FakeGitLabConnector()
    fake_gitlab.file_content = "x" * 8000
    _patch_connectors(monkeypatch, FakeCLSConnector(), fake_gitlab)

    payload = await _call(
        runtime,
        "gitlab_get_file",
        {"target": "code-gitlab", "project": "group/app", "path": "app/main.py"},
    )

    assert payload["returned"] == 1
    assert payload["truncated"] is True
    assert payload["truncation"]["reason"] == "bytes"
    assert len(payload["rows"][0]["content"].encode()) <= 4096


async def test_gitlab_blame_lines_and_validation(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_gitlab_target(runtime)
    fake_gitlab = FakeGitLabConnector()
    _patch_connectors(monkeypatch, FakeCLSConnector(), fake_gitlab)
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        result = await client.call_tool(
            "gitlab_blame",
            {
                "target": "code-gitlab",
                "project": "group/app",
                "path": "app/main.py",
                "line_from": 5,
            },
        )
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "gitlab_blame",
                {
                    "target": "code-gitlab",
                    "project": "group/app",
                    "path": "app/main.py",
                    "line_from": 10,
                    "line_to": 2,
                },
            )

    payload = result.structured_content
    assert payload is not None
    assert [row["line"] for row in payload["rows"]] == [5, 6]
    assert payload["rows"][0]["commit"] == "abc12345"
    assert errors.INVALID_ARGUMENT in str(excinfo.value)


async def test_upstream_timeout_maps_to_code(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    fake = FakeCLSConnector()
    fake.error = errors.UpstreamTimeout("上游超时")
    _patch_connectors(monkeypatch, fake, FakeGitLabConnector())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "cls_search",
                {
                    "target": "logs-cls",
                    "query": "x",
                    "topic": "logset/app",
                    "from": "2026-01-01T00:00:00Z",
                    "to": "2026-01-01T01:00:00Z",
                },
            )

    assert errors.UPSTREAM_TIMEOUT in str(excinfo.value)


async def test_disabled_and_mismatched_target(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    await _create_gitlab_target(runtime)
    await runtime.store.set_enabled(
        (await runtime.store.get("logs-cls")).id, False, "anonymous"
    )
    _patch_connectors(monkeypatch, FakeCLSConnector(), FakeGitLabConnector())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as disabled:
            await client.call_tool(
                "cls_search",
                {
                    "target": "logs-cls",
                    "query": "x",
                    "topic": "logset/app",
                    "from": "2026-01-01T00:00:00Z",
                    "to": "2026-01-01T01:00:00Z",
                },
            )
        with pytest.raises(ToolError) as mismatched:
            await client.call_tool(
                "cls_context",
                {
                    "target": "code-gitlab",
                    "topic": "logset/app",
                    "log_id": "p",
                    "btime": "2026-01-01 09:00:00.000",
                    "pkg_log_id": 123,
                },
            )

    assert errors.TARGET_DISABLED in str(disabled.value)
    assert errors.TARGET_TYPE_MISMATCH in str(mismatched.value)


async def test_tool_audit_and_masking(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    _patch_connectors(monkeypatch, FakeCLSConnector(), FakeGitLabConnector())

    await _call(
        runtime,
        "cls_search",
        {
            "target": "logs-cls",
            "query": "phone=13800138000 secret=secret-key-value",
            "topic": "logset/app",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-01T01:00:00Z",
        },
    )

    async with runtime.session_factory() as session:
        from sqlalchemy import select

        from dr_panda_mcp.store.models import AuditRow

        rows = (await session.execute(select(AuditRow))).scalars().all()

    tool_rows = [row for row in rows if row.action == "tool.call"]
    assert tool_rows
    summary = tool_rows[-1].summary
    assert "cls_search" in summary and "logs-cls" in summary and "returned=" in summary
    assert "13800138000" not in summary
    assert "secret-key-value" not in summary


async def test_cls_search_wide_window_hint_and_options(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime, max_rows=10)
    fake = FakeCLSConnector()
    fake.rows = [
        {
            "time": "2026-01-01T01:00:00+00:00",
            "topic": "logset/app",
            "package_id": "pkg-1",
            "package_log_id": 1,
            "content": "line-a",
        },
        {
            "time": "2026-01-01T01:00:01+00:00",
            "topic": "logset/app",
            "package_id": "pkg-1",
            "package_log_id": 2,
            "content": "line-b",
        },
        {
            "time": "2026-01-01T01:00:02+00:00",
            "topic": "logset/app",
            "package_id": "pkg-2",
            "package_log_id": 1,
            "content": "other",
        },
    ]
    _patch_connectors(monkeypatch, fake, FakeGitLabConnector())

    payload = await _call(
        runtime,
        "cls_search",
        {
            "target": "logs-cls",
            "query": "level:ERROR",
            "topic": "logset/app",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-01T04:00:00Z",
            "sort": "desc",
            "merge_packages": True,
            "compact": True,
        },
    )

    assert payload["stats"]["mode"] == "search"
    assert payload["stats"]["next_context"] == "ctx-next"
    assert payload["stats"]["sort"] == "desc"
    assert any("newest-first" in note for note in payload["notes"])
    assert payload["returned"] == 2
    assert payload["rows"][0]["content"] == "line-a\nline-b"
    assert fake.search_calls[0]["sort"] == "desc"


async def test_cls_search_internal_error_includes_message(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_cls_target(runtime)
    fake = FakeCLSConnector()
    fake.error = ValueError("fromtimestamp year out of range secret-key-value")
    _patch_connectors(monkeypatch, fake, FakeGitLabConnector())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "cls_search",
                {
                    "target": "logs-cls",
                    "query": "x",
                    "topic": "logset/app",
                    "from": "2026-01-01T00:00:00Z",
                    "to": "2026-01-01T01:00:00Z",
                },
            )

    message = str(excinfo.value)
    assert errors.INTERNAL in message
    assert "ValueError" in message
    assert "fromtimestamp" in message
    assert "secret-key-value" not in message


async def test_prompt_contains_order(runtime: Runtime) -> None:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        prompt = await client.get_prompt(
            "investigate_error",
            {"service": "order", "trace_id": "trace-1", "time_range": "最近1小时"},
        )

    text = prompt.messages[0].content.text
    assert "systems_status" in text
    assert "trace-1" in text
    assert "mysql_tables" in text and "mongo_collections" in text
    assert "Stay read-only throughout" in text
