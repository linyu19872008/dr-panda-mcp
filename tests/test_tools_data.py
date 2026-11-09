from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dr_panda_mcp import errors
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.server import create_server
from dr_panda_mcp.store.protocol import SecretPatch, TargetDraft
from dr_panda_mcp.tools import data as data_module

DATA_TOOLS = {
    "mysql_tables", "mysql_describe", "mysql_query", "mysql_explain", "mysql_processlist",
    "mongo_collections", "mongo_find", "mongo_aggregate", "mongo_stats",
    "es_mapping", "es_search", "es_health", "es_index_stats",
    "redis_get", "redis_scan", "redis_info", "redis_slowlog",
}


class FakeMySQL:
    name = "mysql"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delay = 0.0
        self.active = 0
        self.max_active = 0
        self.rows: dict[str, list[dict[str, Any]]] = {
            "TABLE STATUS": [
                {"Name": "users", "Engine": "InnoDB", "Rows": 10, "Comment": ""},
                {"Name": "orders", "Engine": "InnoDB", "Rows": 20, "Comment": ""},
                {"Name": "audit", "Engine": "InnoDB", "Rows": 30, "Comment": ""},
            ],
            "FULL COLUMNS": [
                {
                    "Field": "id", "Type": "bigint", "Null": "NO", "Key": "PRI",
                    "Default": None, "Extra": "auto_increment",
                }
            ],
            "INDEX": [
                {"Key_name": "PRIMARY", "Column_name": "id", "Non_unique": 0, "Index_type": "BTREE"}
            ],
            "PROCESSLIST": [{"Id": 1, "User": "app", "Command": "Query"}],
            "LIMIT": [{"id": 1}, {"id": 2}, {"id": 3}],
            "EXPLAIN": [{"id": 1, "select_type": "SIMPLE"}],
        }

    def create_client(self, target):
        return object()

    async def close_client(self, client):
        return None

    async def fetch_rows(self, client, target, sql):
        self.calls.append(sql)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                import asyncio

                await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
        for marker, rows in self.rows.items():
            if marker in sql:
                return [dict(row) for row in rows]
        return []


class FakeMongo:
    name = "mongo"

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def create_client(self, target):
        return object()

    async def close_client(self, client):
        return None

    async def collections(self, client, target, *, db, limit):
        self.calls.append(("collections", {"db": db, "limit": limit}))
        return [
            {"collection": "orders", "type": "collection", "documents": 3, "indexes": 1},
            {"collection": "system.users", "type": "collection", "documents": 1, "indexes": 1},
        ]

    async def find(self, client, target, **kwargs):
        self.calls.append(("find", kwargs))
        return [{"_id": "1", "status": "paid"}]

    async def aggregate(self, client, target, **kwargs):
        self.calls.append(("aggregate", kwargs))
        return [{"status": "paid", "count": 2}]

    async def stats(self, client, target, **kwargs):
        self.calls.append(("stats", kwargs))
        return [{"ns": "app.orders", "count": 3}]


class FakeES:
    name = "elasticsearch"

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def create_client(self, target):
        return object()

    async def close_client(self, client):
        return None

    async def mapping(self, client, target, *, index):
        self.calls.append(("mapping", index))
        return [{"field": "message", "type": "text", "analyzer": "standard"}], {
            "shards": "1", "replicas": "1"
        }

    async def search(self, client, target, *, index, body):
        self.calls.append(("search", {"index": index, "body": body}))
        return [{"_id": "1", "message": "boom"}], {"total": 1, "took": 3}

    async def health(self, client, target):
        self.calls.append(("health", None))
        return {"status": "green", "number_of_nodes": 3}

    async def index_stats(self, client, target, *, index):
        self.calls.append(("index_stats", index))
        return [{"index": index, "total_docs": 10}]


class FakeRedis:
    name = "redis"

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def create_client(self, target):
        return object()

    async def close_client(self, client):
        return None

    async def inspect(self, client, target, *, key, limit, byte_limit):
        self.calls.append(("inspect", {"key": key, "limit": limit, "byte_limit": byte_limit}))
        return {"key": key, "type": "string", "ttl": -1, "value": "v"}

    async def scan(self, client, target, *, pattern, count, cursor):
        self.calls.append(("scan", {"pattern": pattern, "count": count, "cursor": cursor}))
        return ["pay:1", "pay:2"], 7

    async def info(self, client, target, *, section):
        self.calls.append(("info", section))
        return {"redis_version": "7.0", "connected_clients": "2"}

    async def slowlog(self, client, target, *, count):
        self.calls.append(("slowlog", count))
        return [
            {"id": 1, "duration": 1000, "command": "GET pay:1"},
            {"id": 2, "duration": 2000, "command": "GET other:1"},
        ]


async def _target(runtime: Runtime, type_: str, name: str, options: dict, secret: dict | None = None) -> None:
    await runtime.store.create(
        TargetDraft(
            name=name,
            type=type_,
            enabled=True,
            options=options,
            secret_patch=SecretPatch(set=secret or {}),
        ),
        "anonymous",
    )


async def _setup(runtime: Runtime) -> None:
    await _target(runtime, "mysql", "db-mysql", {
        "host": "127.0.0.1", "port": 3306, "user": "ro", "default_db": "app",
        "allowed_dbs": ["app", "logs"], "max_rows": 2, "max_bytes": 102400,
        "timeout_s": 15, "allow_processlist": True,
    }, {"password": "pw"})
    await _target(runtime, "mongo", "db-mongo", {
        "host": "127.0.0.1", "port": 27017, "allowed_dbs": ["app"],
        "max_rows": 2, "max_bytes": 102400, "timeout_s": 15,
    })
    await _target(runtime, "elasticsearch", "db-es", {
        "hosts": ["http://es:9200"], "allowed_indices": ["logs-2026"],
        "max_rows": 2, "max_bytes": 102400, "timeout_s": 15,
    })
    await _target(runtime, "redis", "db-redis", {
        "host": "127.0.0.1", "port": 6379, "db": 0, "key_prefix": "pay:",
        "max_rows": 2, "max_bytes": 102400, "timeout_s": 15,
    })


def _patch(monkeypatch: pytest.MonkeyPatch, mysql=None, mongo=None, es=None, redis=None):
    connectors = {
        "mysql": mysql or FakeMySQL(),
        "mongo": mongo or FakeMongo(),
        "elasticsearch": es or FakeES(),
        "redis": redis or FakeRedis(),
    }
    monkeypatch.setattr(data_module, "get_connector", lambda type_: connectors[type_])
    return connectors


async def _call(runtime: Runtime, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    return result.structured_content


async def _error(runtime: Runtime, tool: str, arguments: dict[str, Any]) -> str:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(tool, arguments)
    return str(excinfo.value)


async def test_tool_list_has_28(runtime: Runtime) -> None:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert len(names) == 32
    assert DATA_TOOLS <= names
    for tool in tools:
        assert tool.annotations is not None and tool.annotations.read_only_hint is True


async def test_mysql_tables_describe_and_truncation(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mysql = FakeMySQL()
    _patch(monkeypatch, mysql=mysql)

    tables = await _call(runtime, "mysql_tables", {"target": "db-mysql"})
    describe = await _call(
        runtime, "mysql_describe", {"target": "db-mysql", "table": "users"}
    )

    assert tables["returned"] == 2
    assert tables["truncated"] is True
    assert tables["rows"][0]["table"] == "users"
    assert describe["rows"][0]["field"] == "id"
    assert describe["stats"]["indexes"][0]["name"] == "PRIMARY"
    assert any("FULL COLUMNS" in sql for sql in mysql.calls)
    assert any("SHOW INDEX" in sql for sql in mysql.calls)


async def test_mysql_query_forces_limit(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mysql = FakeMySQL()
    _patch(monkeypatch, mysql=mysql)

    payload = await _call(
        runtime, "mysql_query", {"target": "db-mysql", "sql": "SELECT * FROM users"}
    )

    assert payload["returned"] == 2
    assert payload["truncated"] is True
    assert "LIMIT 3" in mysql.calls[-1]
    assert payload["stats"]["limit"] == 2


async def test_mysql_rejections_no_upstream(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mysql = FakeMySQL()
    _patch(monkeypatch, mysql=mysql)

    dangerous = await _error(
        runtime, "mysql_query", {"target": "db-mysql", "sql": "SELECT SLEEP(10)"}
    )
    system = await _error(
        runtime, "mysql_query", {"target": "db-mysql", "sql": "SELECT * FROM mysql.user LIMIT 1"}
    )
    scope = await _error(
        runtime, "mysql_query", {"target": "db-mysql", "sql": "SELECT * FROM other.users LIMIT 1"}
    )
    multi = await _error(
        runtime, "mysql_query", {"target": "db-mysql", "sql": "SELECT 1; DROP TABLE users"}
    )

    assert errors.DANGEROUS_OPERATION in dangerous
    assert errors.DANGEROUS_OPERATION in system
    assert errors.SCOPE_DENIED in scope
    assert errors.GUARD_REJECTED in multi
    assert mysql.calls == []


async def test_mysql_explain_and_processlist(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mysql = FakeMySQL()
    _patch(monkeypatch, mysql=mysql)

    explain = await _call(
        runtime, "mysql_explain", {"target": "db-mysql", "sql": "SELECT * FROM users"}
    )
    processlist = await _call(runtime, "mysql_processlist", {"target": "db-mysql"})
    prefixed = await _call(
        runtime,
        "mysql_explain",
        {"target": "db-mysql", "sql": "EXPLAIN SELECT * FROM users"},
    )

    assert explain["rows"][0]["select_type"] == "SIMPLE"
    assert "EXPLAIN SELECT" in mysql.calls[0]
    assert processlist["rows"][0]["Command"] == "Query"
    # 入参自带 EXPLAIN 时不能拼成 EXPLAIN EXPLAIN。
    assert prefixed["rows"][0]["select_type"] == "SIMPLE"
    assert mysql.calls[-1] == "EXPLAIN SELECT * FROM users"


async def test_mongo_find_aggregate_scope_and_guard(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mongo = FakeMongo()
    _patch(monkeypatch, mongo=mongo)

    find = await _call(runtime, "mongo_find", {
        "target": "db-mongo", "db": "app", "collection": "orders",
        "filter": '{"status":"paid"}',
    })
    aggregate = await _call(runtime, "mongo_aggregate", {
        "target": "db-mongo", "db": "app", "collection": "orders",
        "pipeline": '[{"$match":{"status":"paid"}},{"$group":{"_id":"$status"}}]',
    })

    assert find["rows"][0]["status"] == "paid"
    assert aggregate["returned"] == 1
    no_filter = await _error(runtime, "mongo_find", {
        "target": "db-mongo", "db": "app", "collection": "orders", "filter": "{}",
    })
    no_match = await _error(runtime, "mongo_aggregate", {
        "target": "db-mongo", "db": "app", "collection": "orders",
        "pipeline": '[{"$group":{"_id":"$status"}}]',
    })
    scope = await _error(runtime, "mongo_find", {
        "target": "db-mongo", "db": "other", "collection": "orders",
        "filter": '{"a":1}',
    })
    assert errors.GUARD_REJECTED in no_filter
    assert errors.DANGEROUS_OPERATION in no_match
    assert errors.SCOPE_DENIED in scope


async def test_mongo_find_skip_and_cap(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mongo = FakeMongo()
    _patch(monkeypatch, mongo=mongo)

    payload = await _call(runtime, "mongo_find", {
        "target": "db-mongo", "db": "app", "collection": "orders",
        "filter": '{"status":"paid"}', "skip": 5,
    })
    assert payload["stats"]["skip"] == 5
    assert mongo.calls[-1][1]["skip"] == 5
    too_deep = await _error(runtime, "mongo_find", {
        "target": "db-mongo", "db": "app", "collection": "orders",
        "filter": '{"status":"paid"}', "skip": 10001,
    })
    assert errors.DANGEROUS_OPERATION in too_deep


async def test_es_search_after_and_negative_size(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    es = FakeES()
    _patch(monkeypatch, es=es)

    payload = await _call(runtime, "es_search", {
        "target": "db-es", "index": "logs-2026",
        "query": '{"match_all":{}}', "sort": '[{"ts":"desc"}]',
        "search_after": '[1767229200000, 10]',
    })
    assert payload["returned"] == 1
    body = es.calls[-1][1]["body"]
    assert body["from"] == 0
    assert body["search_after"] == [1767229200000, 10]

    with_after = await _error(runtime, "es_search", {
        "target": "db-es", "index": "logs-2026",
        "query": '{"match_all":{}}', "sort": '[{"ts":"desc"}]',
        "search_after": '[1]', "from": 1,
    })
    missing_sort = await _error(runtime, "es_search", {
        "target": "db-es", "index": "logs-2026",
        "query": '{"match_all":{}}', "search_after": '[1]',
    })
    assert errors.INVALID_ARGUMENT in with_after
    assert errors.INVALID_ARGUMENT in missing_sort


async def test_mongo_collections_and_stats(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mongo = FakeMongo()
    _patch(monkeypatch, mongo=mongo)

    collections = await _call(runtime, "mongo_collections", {"target": "db-mongo", "db": "app"})
    stats = await _call(runtime, "mongo_stats", {"target": "db-mongo", "db": "app"})

    assert collections["rows"][0]["collection"] == "orders"
    assert all(not row["collection"].startswith("system.") for row in collections["rows"])
    assert stats["rows"][0]["ns"] == "app.orders"


async def test_es_mapping_search_scope_and_limits(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    es = FakeES()
    _patch(monkeypatch, es=es)

    mapping = await _call(runtime, "es_mapping", {"target": "db-es", "index": "logs-2026"})
    search = await _call(runtime, "es_search", {
        "target": "db-es", "index": "logs-2026", "query": '{"match":{"message":"boom"}}',
        "from": 1, "size": 2,
    })

    assert mapping["rows"][0]["field"] == "message"
    assert mapping["stats"]["shards"] == "1"
    assert search["rows"][0]["message"] == "boom"
    assert search["stats"]["total"] == 1
    assert es.calls[-1][1]["body"]["from"] == 1
    size = await _error(runtime, "es_search", {
        "target": "db-es", "index": "logs-2026", "query": '{"match_all":{}}', "size": 3,
    })
    script = await _error(runtime, "es_search", {
        "target": "db-es", "index": "logs-2026",
        "query": '{"script":{"script":{"source":"1"}}}',
    })
    scope = await _error(runtime, "es_search", {
        "target": "db-es", "index": "other", "query": '{"match_all":{}}',
    })
    negative = await _error(runtime, "es_search", {
        "target": "db-es", "index": "logs-2026", "query": '{"match_all":{}}', "size": -1,
    })
    assert errors.DANGEROUS_OPERATION in size
    assert errors.INVALID_ARGUMENT in negative
    assert errors.DANGEROUS_OPERATION in script
    assert errors.SCOPE_DENIED in scope


async def test_es_health_and_stats(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    _patch(monkeypatch, es=FakeES())

    health = await _call(runtime, "es_health", {"target": "db-es"})
    stats = await _call(runtime, "es_index_stats", {"target": "db-es", "index": "logs-2026"})

    assert health["stats"]["status"] == "green"
    assert stats["rows"][0]["index"] == "logs-2026"


async def test_redis_get_scan_info_slowlog(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    redis = FakeRedis()
    _patch(monkeypatch, redis=redis)

    get = await _call(runtime, "redis_get", {"target": "db-redis", "key": "pay:1"})
    scan = await _call(runtime, "redis_scan", {"target": "db-redis", "pattern": "pay:*"})
    info = await _call(runtime, "redis_info", {"target": "db-redis", "section": "server"})
    slowlog = await _call(runtime, "redis_slowlog", {"target": "db-redis"})

    assert get["rows"][0]["value"] == "v"
    assert scan["returned"] == 2 and scan["stats"]["cursor"] == 7
    assert info["stats"]["redis_version"] == "7.0"
    assert slowlog["rows"][0]["id"] == 1


async def test_redis_scope_and_scan_limit(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    redis = FakeRedis()
    _patch(monkeypatch, redis=redis)

    key_scope = await _error(runtime, "redis_get", {"target": "db-redis", "key": "other:1"})
    pattern_scope = await _error(runtime, "redis_scan", {"target": "db-redis", "pattern": "other:*"})
    too_large = await _error(runtime, "redis_scan", {
        "target": "db-redis", "pattern": "pay:*", "count": 500,
    })

    assert errors.SCOPE_DENIED in key_scope
    assert errors.SCOPE_DENIED in pattern_scope
    assert errors.DANGEROUS_OPERATION in too_large
    assert redis.calls == []


async def test_processlist_requires_explicit_target_switch(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _target(
        runtime,
        "mysql",
        "db-mysql-no-process",
        {
            "host": "127.0.0.1", "port": 3306, "user": "ro", "default_db": "app",
            "allowed_dbs": ["app"], "max_rows": 10, "max_bytes": 102400,
            "timeout_s": 15,
        },
        {"password": "pw"},
    )
    _patch(monkeypatch, mysql=FakeMySQL())
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as process:
            await client.call_tool("mysql_processlist", {"target": "db-mysql-no-process"})
        with pytest.raises(ToolError) as query:
            await client.call_tool(
                "mysql_query",
                {"target": "db-mysql-no-process", "sql": "SHOW PROCESSLIST"},
            )

    assert errors.SCOPE_DENIED in str(process.value)
    assert errors.SCOPE_DENIED in str(query.value)


async def test_mongo_system_collection_is_rejected(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mongo = FakeMongo()
    _patch(monkeypatch, mongo=mongo)
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        for tool, args in [
            ("mongo_find", {"collection": "system.users", "filter": '{"_id":1}'}),
            ("mongo_stats", {"collection": "system.users"}),
        ]:
            with pytest.raises(ToolError) as excinfo:
                await client.call_tool(
                    tool, {"target": "db-mongo", "db": "app", **args}
                )
            assert errors.SCOPE_DENIED in str(excinfo.value)
    assert mongo.calls == []


async def test_tool_calls_respect_target_concurrency(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    await _setup(runtime)
    mysql = FakeMySQL()
    mysql.delay = 0.03
    _patch(monkeypatch, mysql=mysql)
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        await asyncio.gather(
            *[
                client.call_tool(
                    "mysql_query",
                    {"target": "db-mysql", "sql": "SELECT * FROM users"},
                )
                for _ in range(11)
            ]
        )

    assert mysql.max_active <= 10
    assert mysql.max_active >= 2


async def test_tool_call_has_whole_call_timeout(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mysql = FakeMySQL()
    mysql.delay = 0.2
    _patch(monkeypatch, mysql=mysql)
    monkeypatch.setattr(
        "dr_panda_mcp.connectors.base.timeout_seconds", lambda _target: 0.05
    )
    server = create_server(runtime.config, runtime)

    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "mysql_query",
                {"target": "db-mysql", "sql": "SELECT * FROM users"},
            )

    assert errors.UPSTREAM_TIMEOUT in str(excinfo.value)


async def test_stats_larger_than_byte_limit_is_truncated(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _target(
        runtime,
        "redis",
        "db-redis-tiny",
        {
            "host": "127.0.0.1", "port": 6379, "db": 0, "key_prefix": "pay:",
            "max_rows": 10, "max_bytes": 4096, "timeout_s": 15,
        },
    )
    redis = FakeRedis()

    async def huge_info(client, target, *, section):
        return {"blob": "x" * 10_000}

    redis.info = huge_info  # type: ignore[method-assign]
    _patch(monkeypatch, redis=redis)

    payload = await _call(runtime, "redis_info", {"target": "db-redis-tiny"})

    assert payload["stats"]["truncated"] is True
    assert payload["stats"]["reason"] == "bytes"
    assert any("Statistics were truncated" in note for note in payload["notes"])


async def test_mysql_query_keeps_lower_existing_limit(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    mysql = FakeMySQL()
    _patch(monkeypatch, mysql=mysql)

    await _call(
        runtime,
        "mysql_query",
        {"target": "db-mysql", "sql": "SELECT * FROM users LIMIT 1"},
    )

    assert mysql.calls[-1].upper().endswith("LIMIT 1")
    assert "LIMIT 3" not in mysql.calls[-1]
