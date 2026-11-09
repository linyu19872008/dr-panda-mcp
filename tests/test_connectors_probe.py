from __future__ import annotations

import sys
import types
from typing import Self

import pytest

from dr_panda_mcp.catalog import Catalog
from dr_panda_mcp.connectors import connector_names, get_connector
from dr_panda_mcp.connectors import mysql as mysql_module
from tests.fakes import FakeConnector, FakeStore, make_target

TARGET_TYPES = [
    "mysql",
    "mongo",
    "elasticsearch",
    "redis",
    "gitlab",
    "rabbitmq",
    "kafka",
    "cls",
    "nacos",
]


class _FakeCursor:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def execute(self, statement: str) -> None:
        self._statements.append(statement)

    async def fetchone(self):
        return (1,)


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False
        self._cursor = _FakeCursor(self.statements)

    def cursor(self) -> _FakeCursor:
        return self._cursor

    async def ensure_closed(self) -> None:
        self.closed = True


async def test_mysql_probe_sets_session_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeConnection()

    async def fake_connect(asyncmy, target):
        return connection

    monkeypatch.setitem(sys.modules, "asyncmy", types.SimpleNamespace(connect=None))
    monkeypatch.setattr(mysql_module, "_connect", fake_connect)

    target = make_target(
        type_="mysql",
        options={"host": "127.0.0.1", "default_db": "app", "timeout_s": "15"},
        secret={"password": "pw"},
    )
    connector = mysql_module.connector
    client = connector.create_client(target)

    await connector.probe(client, target)

    assert connection.statements == [
        "SET SESSION TRANSACTION READ ONLY",
        "SET SESSION max_execution_time = 15000",
        "SET SESSION sql_select_limit = 100",
        "SELECT 1",
    ]
    assert connection.closed is True


def test_connector_registry_covers_nine_types() -> None:
    assert connector_names() == sorted(TARGET_TYPES)


@pytest.mark.parametrize("type_", TARGET_TYPES)
def test_real_connectors_probe_guard_allows(type_: str) -> None:
    assert get_connector(type_).probe_guard().allowed is True


@pytest.mark.parametrize("type_", TARGET_TYPES)
async def test_eight_types_test_connection(type_: str) -> None:
    target = make_target(type_=type_)
    catalog = Catalog(FakeStore([target]))
    connector = FakeConnector(name=type_)

    await catalog.test_connection(target.name, connector)

    assert connector.created == 1
    assert connector.probes == 1
    await catalog.close()


async def test_mysql_connect_passes_ssl_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeAsyncmy:
        @staticmethod
        async def connect(**kwargs):
            captured.update(kwargs)
            return object()

    target = make_target(
        type_="mysql",
        options={"host": "127.0.0.1", "default_db": "app", "ssl": True},
        secret={"password": "pw"},
    )

    await mysql_module._connect(FakeAsyncmy, target)

    assert captured["ssl"] is not None
