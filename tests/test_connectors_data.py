from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import es as es_module
from dr_panda_mcp.connectors import mongo as mongo_module
from dr_panda_mcp.connectors import mysql as mysql_module
from dr_panda_mcp.connectors import redis as redis_module
from dr_panda_mcp.store.protocol import Target
from dr_panda_mcp.tools.data import _mysql_scope, force_limit
from tests.fakes import make_target


def _mysql_target() -> Target:
    return make_target(
        type_="mysql",
        options={
            "host": "127.0.0.1",
            "port": 3306,
            "user": "ro",
            "default_db": "app",
            "allowed_dbs": ["app"],
            "timeout_s": "15",
            "max_rows": 100,
        },
        secret={"password": "pw"},
    )


class _Cursor:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements
        self.description = [("id",), ("name",)]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)

    async def fetchall(self):
        return [(1, "a"), (2, "b")]

    async def fetchone(self):
        return (1,)


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False

    def cursor(self):
        return _Cursor(self.statements)

    async def ensure_closed(self):
        self.closed = True


async def test_mysql_fetch_rows_sets_session_and_returns_dicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def fake_connect(asyncmy, target):
        return connection

    monkeypatch.setitem(sys.modules, "asyncmy", types.SimpleNamespace(connect=None))
    monkeypatch.setattr(mysql_module, "_connect", fake_connect)

    target = _mysql_target()
    client = mysql_module.connector.create_client(target)
    rows = await client.fetch_rows("SELECT id, name FROM users LIMIT 2")

    assert rows == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert connection.statements[:3] == [
        "SET SESSION TRANSACTION READ ONLY",
        "SET SESSION max_execution_time = 15000",
        "SET SESSION sql_select_limit = 100",
    ]
    assert connection.statements[-1] == "SELECT id, name FROM users LIMIT 2"
    assert connection.closed is True


def test_force_limit_and_mysql_scope() -> None:
    assert "LIMIT 100" in force_limit("SELECT * FROM users", 100)
    capped = force_limit("SELECT * FROM users LIMIT 5000", 100)
    assert "LIMIT 100" in capped
    assert force_limit("SHOW TABLES", 100) == "SHOW TABLES"

    target = make_target(
        type_="mysql", options={"allowed_dbs": ["app"], "default_db": "app"}
    )
    _mysql_scope(target, "SELECT * FROM users", "app")
    _mysql_scope(target, "SELECT * FROM app.users", "app")
    with pytest.raises(errors.ScopeDenied):
        _mysql_scope(target, "SELECT * FROM other.users", "app")
    with pytest.raises(errors.ScopeDenied):
        _mysql_scope(target, "SHOW DATABASES", "app")

    default_only = make_target(
        type_="mysql", options={"allowed_dbs": [], "default_db": "app"}
    )
    _mysql_scope(default_only, "SELECT * FROM users", "app")
    _mysql_scope(default_only, "SELECT * FROM app.users", "app")
    with pytest.raises(errors.ScopeDenied):
        _mysql_scope(default_only, "SELECT * FROM other.users", "app")


def _es_target() -> Target:
    return make_target(
        type_="elasticsearch",
        options={
            "hosts": ["http://es:9200"],
            "allowed_indices": ["logs-2026"],
            "timeout_s": "15",
        },
    )


async def test_es_mapping_search_health_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    client = es_module.connector.create_client(_es_target())
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, path: str, *, body=None):
        calls.append((method, path))
        payloads: dict[str, Any] = {
            "/logs-2026/_mapping": {
                "logs-2026": {
                    "mappings": {
                        "properties": {
                            "message": {"type": "text", "analyzer": "standard"},
                            "ctx": {"properties": {"code": {"type": "keyword"}}},
                        }
                    }
                }
            },
            "/logs-2026/_settings": {
                "logs-2026": {"settings": {"index": {"number_of_shards": "2", "number_of_replicas": "1"}}}
            },
            "/logs-2026/_search": {
                "took": 4,
                "hits": {
                    "total": {"value": 1},
                    "hits": [{"_index": "logs-2026", "_id": "a", "_score": 1.0, "_source": {"message": "boom"}}],
                },
            },
            "/_cluster/health": {"status": "green", "number_of_nodes": 3},
            "/logs-2026/_stats": {
                "indices": {
                    "logs-2026": {
                        "primaries": {"docs": {"count": 5}, "store": {"size_in_bytes": 10}},
                        "total": {"docs": {"count": 5}, "store": {"size_in_bytes": 10}},
                    }
                }
            },
        }
        return httpx.Response(200, json=payloads[path], request=httpx.Request(method, f"http://es:9200{path}"))

    monkeypatch.setattr(client, "_request", fake_request)

    rows, stats = await client.mapping("logs-2026")
    search_rows, search_stats = await client.search("logs-2026", {"query": {"match_all": {}}})
    health = await client.health()
    index_rows = await client.index_stats("logs-2026")

    assert [row["field"] for row in rows] == ["message", "ctx.code"]
    assert stats == {"shards": "2", "replicas": "1"}
    assert search_rows[0]["message"] == "boom"
    assert search_stats == {"total": 1, "took": 4}
    assert health["status"] == "green"
    assert index_rows[0]["total_docs"] == 5


class _FakeRedis:
    def __init__(self) -> None:
        self.kind = "string"
        self.size = 1
        self.closed = False

    async def type(self, key):
        return self.kind

    async def ttl(self, key):
        return -1

    async def strlen(self, key):
        return len(self.value) if hasattr(self, "value") else 1

    async def get(self, key):
        return getattr(self, "value", "v")

    async def llen(self, key):
        return self.size

    async def lrange(self, key, start, stop):
        return [str(index) for index in range(start, stop + 1)]

    async def scan(self, cursor, match, count):
        return 2, ["pay:1", "pay:2"]

    async def info(self, section):
        return {"redis_version": "7.0"}

    async def slowlog_get(self, count):
        return [{"id": 1, "duration": 1000}]

    async def aclose(self):
        self.closed = True


def _redis_target() -> Target:
    return make_target(
        type_="redis",
        options={"host": "127.0.0.1", "port": 6379, "db": 0, "key_prefix": "pay:"},
    )


def _fake_redis_package(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> None:
    """安装假的 redis.asyncio，捕获传给 Redis(...) 的 kwargs。"""
    module = types.ModuleType("redis.asyncio")

    class _FakeRedis:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    module.Redis = _FakeRedis
    redis_package = types.ModuleType("redis")
    redis_package.asyncio = module
    monkeypatch.setitem(sys.modules, "redis", redis_package)
    monkeypatch.setitem(sys.modules, "redis.asyncio", module)


@pytest.mark.parametrize(("configured", "expected"), [(None, 2), ("2", 2), ("3", 3)])
def test_redis_client_protocol(
    monkeypatch: pytest.MonkeyPatch, configured: str | None, expected: int
) -> None:
    """redis-py 8 默认 RESP3 会发 HELLO；未配置时固定 2，配置 3 才启用 RESP3。"""
    captured: dict[str, Any] = {}
    _fake_redis_package(monkeypatch, captured)
    options: dict[str, Any] = {"host": "127.0.0.1", "port": 6379, "db": 0}
    if configured is not None:
        options["protocol"] = configured
    target = make_target(type_="redis", options=options)

    redis_module.connector.create_client(target)._client()

    assert captured["protocol"] == expected
    assert captured["host"] == "127.0.0.1"
    assert captured["db"] == 0


@pytest.mark.parametrize("configured", ["4", "resp2", "abc"])
def test_redis_client_rejects_invalid_protocol(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    captured: dict[str, Any] = {}
    _fake_redis_package(monkeypatch, captured)
    target = make_target(
        type_="redis", options={"host": "127.0.0.1", "protocol": configured}
    )

    with pytest.raises(errors.UpstreamUnavailable) as excinfo:
        redis_module.connector.create_client(target)._client()

    assert "protocol version" in str(excinfo.value)
    assert captured == {}


class _FailingPingClient:
    def __init__(self, message: str) -> None:
        self.message = message
        self.closed = False

    async def ping(self) -> None:
        raise RuntimeError(self.message)

    async def aclose(self) -> None:
        self.closed = True


async def test_redis_hello_error_gets_resp2_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = redis_module.connector.create_client(_redis_target())
    fake = _FailingPingClient("unknown command 'HELLO'")
    monkeypatch.setattr(client, "_client", lambda: fake)

    with pytest.raises(errors.UpstreamUnavailable) as excinfo:
        await client.ping()

    message = str(excinfo.value)
    assert "RESP3" in message
    assert "protocol version" in message
    assert fake.closed is True


async def test_redis_other_errors_keep_wrapped_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = redis_module.connector.create_client(_redis_target())
    fake = _FailingPingClient("boom")
    monkeypatch.setattr(client, "_client", lambda: fake)

    with pytest.raises(errors.UpstreamUnavailable) as excinfo:
        await client.ping()

    assert str(excinfo.value) == "redis read failed: boom"


async def test_redis_inspect_bounded_and_unbounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis()
    client = redis_module.connector.create_client(_redis_target())
    monkeypatch.setattr(client, "_client", lambda: fake)

    string_row = await client.inspect("pay:1", limit=10, byte_limit=1024)
    assert string_row["value"] == "v"
    assert string_row["type"] == "string"

    fake.kind = "list"
    fake.size = 100
    with pytest.raises(errors.GuardRejected) as excinfo:
        await client.inspect("pay:1", limit=10, byte_limit=1024)
    assert excinfo.value.code == errors.DANGEROUS_OPERATION

    fake.size = 2
    list_row = await client.inspect("pay:1", limit=10, byte_limit=1024)
    assert list_row["value"] == [str(index) for index in range(10)]
    assert fake.closed is True


class _FakeMongoCursor:
    def __init__(self, documents):
        self.documents = documents
        self.sort_value = None
        self.limit_value = None

    def sort(self, pairs):
        self.sort_value = pairs
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    async def to_list(self, length):
        return self.documents[:length]


class _FakeMongoCollection:
    def __init__(self) -> None:
        self.find_args = None
        self.aggregate_args = None

    def find(self, filter_, projection, max_time_ms=None):
        self.find_args = (filter_, projection, max_time_ms)
        return _FakeMongoCursor([{"_id": "1", "status": "paid"}])

    def aggregate(self, pipeline, maxTimeMS=None):
        self.aggregate_args = (pipeline, maxTimeMS)
        return _FakeMongoCursor([{"status": "paid", "count": 1}])


class _FakeMongoDB:
    def __init__(self, collection) -> None:
        self.collection = collection

    def __getitem__(self, name):
        return self.collection

    async def list_collection_names(self):
        return ["orders"]

    async def command(self, name, *args):
        return {"count": 1, "index_count": 1}


class _FakeMotor:
    def __init__(self) -> None:
        self.collection = _FakeMongoCollection()
        self.db = _FakeMongoDB(self.collection)
        self.closed = False

    def __getitem__(self, name):
        return self.db

    def close(self):
        self.closed = True


def _mongo_target() -> Target:
    return make_target(
        type_="mongo", options={"host": "127.0.0.1", "port": 27017, "allowed_dbs": ["app"]}
    )


async def test_mongo_find_limit_and_aggregate_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMotor()
    client = mongo_module.connector.create_client(_mongo_target())

    @asynccontextmanager
    async def fake_connected():
        try:
            yield fake
        finally:
            fake.close()

    monkeypatch.setattr(client, "_connected", fake_connected)

    rows = await client.find(
        "app", "orders", {"status": "paid"}, {"_id": 0}, {"ts": -1}, 5
    )
    aggregate_rows = await client.aggregate(
        "app", "orders", [{"$match": {"status": "paid"}}], 3
    )

    assert rows == [{"_id": "1", "status": "paid"}]
    assert fake.collection.find_args[0] == {"status": "paid"}
    cursor = fake.collection
    assert aggregate_rows[0]["count"] == 1
    pipeline, _ = cursor.aggregate_args
    assert pipeline[-1] == {"$limit": 3}
    assert fake.closed is True


def test_mongo_uri_encodes_credentials() -> None:
    from dr_panda_mcp.connectors.mongo import _build_uri

    target = make_target(
        type_="mongo",
        options={"host": "mongo", "port": 27017, "user": "ro@corp", "auth_source": "admin"},
        secret={"password": "p@ss:word"},
    )

    assert _build_uri(target) == "mongodb://ro%40corp:p%40ss%3Aword@mongo:27017/?authSource=admin"


def _mongo_uri_target(uri: str) -> Target:
    return make_target(
        type_="mongo", options={"auth_mode": "uri"}, secret={"uri": uri}
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "mongodb://ro:p@ss@mongo:27017/?authSource=admin",
            "mongodb://ro:p%40ss@mongo:27017/?authSource=admin",
        ),
        ("mongodb://ro:pa:ss@mongo:27017/", "mongodb://ro:pa%3Ass@mongo:27017/"),
        ("mongodb://ro:100%zz@mongo:27017/", "mongodb://ro:100%25zz@mongo:27017/"),
        (
            "mongodb://ro@corp:p@ss:word@mongo:27017/",
            "mongodb://ro%40corp:p%40ss%3Aword@mongo:27017/",
        ),
        (
            "mongodb://u:p@ss@h1:27017,h2:27017/db?replicaSet=rs0",
            "mongodb://u:p%40ss@h1:27017,h2:27017/db?replicaSet=rs0",
        ),
        (
            "mongodb+srv://u:p@ss@cluster.mongodb.net/?retryWrites=true",
            "mongodb+srv://u:p%40ss@cluster.mongodb.net/?retryWrites=true",
        ),
    ],
)
def test_mongo_uri_mode_normalizes_unescaped_credentials(raw: str, expected: str) -> None:
    from dr_panda_mcp.connectors.mongo import _build_uri

    assert _build_uri(_mongo_uri_target(raw)) == expected


@pytest.mark.parametrize(
    "escaped",
    [
        "mongodb://ro%40corp:p%40ss%3Aword@mongo:27017/?authSource=admin",
        "mongodb://ro:p%40ss@mongo:27017/",
        "mongodb://mongo:27017/",
        "mongodb+srv://cluster/?retryWrites=true",
    ],
)
def test_mongo_uri_mode_keeps_valid_uri_untouched(escaped: str) -> None:
    from dr_panda_mcp.connectors.mongo import _build_uri

    assert _build_uri(_mongo_uri_target(escaped)) == escaped


def test_mongo_uri_mode_rejects_empty_username() -> None:
    from dr_panda_mcp.connectors.mongo import _build_uri

    with pytest.raises(errors.UpstreamUnavailable):
        _build_uri(_mongo_uri_target("mongodb://:pw@mongo:27017/"))


async def test_mongo_client_construction_error_is_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = types.ModuleType("motor.motor_asyncio")

    class _BoomClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("bad uri")

    module.AsyncIOMotorClient = _BoomClient
    monkeypatch.setitem(sys.modules, "motor", types.ModuleType("motor"))
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", module)

    client = mongo_module.connector.create_client(_mongo_target())
    with pytest.raises(errors.UpstreamUnavailable) as excinfo:
        async with client._connected():
            pass
    assert "cannot be parsed" in str(excinfo.value)


async def test_redis_string_over_byte_limit_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis()
    fake.value = "x" * 100
    client = redis_module.connector.create_client(_redis_target())
    monkeypatch.setattr(client, "_client", lambda: fake)

    with pytest.raises(errors.GuardRejected) as excinfo:
        await client.inspect("pay:1", limit=10, byte_limit=50)

    assert excinfo.value.code == errors.DANGEROUS_OPERATION


def _ca_pem() -> str:
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "drpanda-test-ca")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        .not_valid_after(dt.datetime(2030, 1, 1, tzinfo=dt.UTC))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_mysql_ca_context_uses_target_ca() -> None:
    from dr_panda_mcp.connectors.mysql import _ssl_context

    target = make_target(
        type_="mysql",
        options={"ssl": True, "ca_pem": _ca_pem()},
        secret={"password": "pw"},
    )
    context = _ssl_context(target)
    assert context.cert_store_stats()["x509"] >= 1


def test_es_client_uses_target_ca() -> None:
    import ssl as ssl_module

    from dr_panda_mcp.connectors.es import _tls_verify

    target = make_target(
        type_="elasticsearch",
        options={"hosts": ["https://es:9200"], "ca_pem": _ca_pem(), "verify_tls": True},
    )
    verify = _tls_verify(target)
    assert isinstance(verify, ssl_module.SSLContext)


def test_mongo_auth_modes() -> None:
    from dr_panda_mcp.connectors.mongo import _auth_mode, _build_uri

    no_auth = make_target(
        type_="mongo", options={"host": "mongo", "port": 27017, "auth_mode": "none"}
    )
    assert _auth_mode(no_auth) == "none"
    assert _build_uri(no_auth) == "mongodb://mongo:27017/"

    uri = make_target(
        type_="mongo",
        options={"auth_mode": "uri"},
        secret={"uri": "mongodb+srv://cluster/?retryWrites=true"},
    )
    assert _auth_mode(uri) == "uri"
    assert _build_uri(uri).startswith("mongodb+srv://")

    legacy = make_target(
        type_="mongo",
        options={"host": "mongo", "port": 27017, "user": "ro"},
        secret={"password": "pw"},
    )
    assert _auth_mode(legacy) == "password"
    assert "ro:pw@mongo" in _build_uri(legacy)

    with pytest.raises(errors.UpstreamUnavailable):
        _build_uri(make_target(type_="mongo", options={"auth_mode": "password", "host": "mongo"}))


def test_mongo_tls_kwargs_use_target_ca_and_client_pair() -> None:
    from dr_panda_mcp.connectors.mongo import _MongoClient

    ca = "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----"
    cert = "-----BEGIN CERTIFICATE-----\ncert\n-----END CERTIFICATE-----"
    key = "-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----"
    target = make_target(
        type_="mongo",
        options={"auth_mode": "none", "host": "mongo", "tls": True, "ca_pem": ca},
        secret={"client_cert": cert, "client_key": key},
    )
    client = _MongoClient(target)
    kwargs, paths = client._tls_kwargs()
    try:
        assert kwargs["tls"] is True
        assert kwargs["tlsCAFile"].endswith(".ca.pem")
        assert kwargs["tlsCertificateKeyFile"].endswith(".client.pem")
        assert len(paths) == 2
    finally:
        from dr_panda_mcp.connectors.mongo import _unlink

        for path in paths:
            _unlink(path)


def test_redis_acl_and_tls_client_options() -> None:
    from dr_panda_mcp.connectors.redis import _RedisClient

    target = make_target(
        type_="redis",
        options={
            "host": "127.0.0.1",
            "port": 6379,
            "username": "drpanda",
            "tls": True,
            "ca_pem": _ca_pem(),
        },
        secret={"password": "pw"},
    )
    client = _RedisClient(target)._client()
    try:
        kwargs = client.connection_pool.connection_kwargs
        assert kwargs["username"] == "drpanda"
        assert kwargs["password"] == "pw"
        assert kwargs["ssl_ca_data"].startswith("-----BEGIN CERTIFICATE-----")
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_kafka_sasl_tls_client_options() -> None:
    from dr_panda_mcp.connectors.kafka import _KafkaClient

    target = make_target(
        type_="kafka",
        options={
            "bootstrap_servers": ["127.0.0.1:9092"],
            "security_protocol": "SASL_SSL",
            "sasl_mechanism": "SCRAM-SHA-256",
            "sasl_user": "drpanda",
            "allowed_topics": ["orders"],
            "ca_pem": _ca_pem(),
        },
        secret={"sasl_password": "pw"},
    )
    kwargs = _KafkaClient(target)._kwargs()
    assert kwargs["security_protocol"] == "SASL_SSL"
    assert kwargs["sasl_mechanism"] == "SCRAM-SHA-256"
    assert kwargs["sasl_plain_username"] == "drpanda"
    assert kwargs["sasl_plain_password"] == "pw"
    assert kwargs["ssl_context"] is not None
