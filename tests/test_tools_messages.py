from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from dr_panda_mcp import errors
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.server import create_server
from dr_panda_mcp.store.protocol import SecretPatch, TargetDraft
from dr_panda_mcp.tools import messages as messages_module

MESSAGE_TOOLS = {"rabbit_queues", "rabbit_queue", "kafka_lag", "kafka_offsets", "kafka_peek"}


class FakeRabbit:
    name = "rabbitmq"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def create_client(self, target):
        return object()

    async def close_client(self, client):
        return None

    async def queues(self, client, target, *, vhost):
        self.calls.append(("queues", vhost))
        rows = [
            {
                "name": f"q-{vhost.strip('/') or 'root'}",
                "vhost": vhost,
                "messages": 5,
                "messages_unacknowledged": 1,
                "consumers": 2,
                "state": "running",
            },
            {
                "name": f"q2-{vhost.strip('/') or 'root'}",
                "vhost": vhost,
                "messages": 0,
                "messages_unacknowledged": 0,
                "consumers": 1,
                "state": "idle",
            },
        ]
        return rows

    async def queue(self, client, target, *, vhost, queue):
        self.calls.append(("queue", f"{vhost}/{queue}"))
        return {
            "name": queue,
            "vhost": vhost,
            "messages": 5,
            "messages_unacknowledged": 1,
            "consumers": 2,
            "state": "running",
            "durable": True,
            "arguments": {},
        }


class FakeKafka:
    name = "kafka"

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.peek_error: Exception | None = None

    def create_client(self, target):
        return object()

    async def close_client(self, client):
        return None

    async def lag(self, client, target, *, group, topic):
        self.calls.append(("lag", {"group": group, "topic": topic}))
        return [
            {
                "group": group,
                "topic": topic,
                "partition": 0,
                "committed": 90,
                "high": 100,
                "lag": 10,
            }
        ]

    async def offsets(self, client, target, *, topic):
        self.calls.append(("offsets", topic))
        return [{"topic": topic, "partition": 0, "low": 5, "high": 100}]

    async def peek(self, client, target, *, topic, partition, offset, limit):
        self.calls.append(
            ("peek", {"topic": topic, "partition": partition, "offset": offset, "limit": limit})
        )
        if self.peek_error:
            raise self.peek_error
        return [
            {
                "topic": topic,
                "partition": partition,
                "offset": offset,
                "timestamp": 1767229200000,
                "key": None,
                "value": "payload",
                "headers": [],
            }
        ]


async def _setup(runtime: Runtime) -> None:
    await runtime.store.create(
        TargetDraft(
            name="mq-rabbit",
            type="rabbitmq",
            enabled=True,
            options={
                "management_url": "http://rabbit:15672",
                "user": "ro",
                "allowed_vhosts": ["/", "pay"],
                "max_rows": 2,
                "max_bytes": 102400,
                "timeout_s": 15,
            },
            secret_patch=SecretPatch(set={"password": "pw"}),
        ),
        "anonymous",
    )
    await runtime.store.create(
        TargetDraft(
            name="mq-kafka",
            type="kafka",
            enabled=True,
            options={
                "bootstrap_servers": ["kafka:9092"],
                "security_protocol": "PLAINTEXT",
                "allowed_topics": ["orders", "payments"],
                "max_rows": 2,
                "max_bytes": 102400,
                "timeout_s": 15,
            },
            secret_patch=SecretPatch(set={}),
        ),
        "anonymous",
    )


def _patch(monkeypatch: pytest.MonkeyPatch, rabbit=None, kafka=None):
    connectors = {"rabbitmq": rabbit or FakeRabbit(), "kafka": kafka or FakeKafka()}
    monkeypatch.setattr(messages_module, "get_connector", lambda type_: connectors[type_])
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


async def test_message_tools_listed(runtime: Runtime) -> None:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert len(names) == 39
    assert MESSAGE_TOOLS <= names
    for tool in tools:
        if tool.name in MESSAGE_TOOLS:
            assert tool.annotations is not None and tool.annotations.read_only_hint is True


async def test_rabbit_queues_scope_and_rows(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    rabbit = FakeRabbit()
    _patch(monkeypatch, rabbit=rabbit)

    all_vhosts = await _call(runtime, "rabbit_queues", {"target": "mq-rabbit"})
    one_vhost = await _call(
        runtime, "rabbit_queues", {"target": "mq-rabbit", "vhost": "pay"}
    )

    assert all_vhosts["returned"] == 2
    assert all_vhosts["truncated"] is True
    assert [row["vhost"] for row in one_vhost["rows"]] == ["pay"] * 2
    assert rabbit.calls == [("queues", "/"), ("queues", "pay")]


async def test_rabbit_queue_detail_and_vhost_scope(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    rabbit = FakeRabbit()
    _patch(monkeypatch, rabbit=rabbit)

    detail = await _call(
        runtime,
        "rabbit_queue",
        {"target": "mq-rabbit", "vhost": "/", "queue": "orders"},
    )
    denied = await _error(
        runtime,
        "rabbit_queue",
        {"target": "mq-rabbit", "vhost": "other", "queue": "orders"},
    )

    assert detail["rows"][0]["durable"] is True
    assert "orders" in detail["summary"]
    assert errors.SCOPE_DENIED in denied
    assert rabbit.calls == [("queue", "//orders")]


async def test_kafka_lag_and_topic_scope(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    kafka = FakeKafka()
    _patch(monkeypatch, kafka=kafka)

    one = await _call(
        runtime, "kafka_lag", {"target": "mq-kafka", "group": "g1", "topic": "orders"}
    )
    all_topics = await _call(runtime, "kafka_lag", {"target": "mq-kafka", "group": "g1"})
    denied = await _error(
        runtime, "kafka_lag", {"target": "mq-kafka", "group": "g1", "topic": "other"}
    )

    assert one["rows"][0]["lag"] == 10
    assert all_topics["returned"] == 2
    assert errors.SCOPE_DENIED in denied
    assert [call[1]["topic"] for call in kafka.calls] == ["orders", "orders", "payments"]


async def test_kafka_offsets_and_peek(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    kafka = FakeKafka()
    _patch(monkeypatch, kafka=kafka)

    offsets = await _call(runtime, "kafka_offsets", {"target": "mq-kafka", "topic": "orders"})
    peek = await _call(
        runtime,
        "kafka_peek",
        {"target": "mq-kafka", "topic": "orders", "partition": 0, "offset": 10, "limit": 50},
    )

    assert offsets["rows"][0]["low"] == 5
    assert peek["rows"][0]["value"] == "payload"
    assert kafka.calls[-1][1]["limit"] == 3  # cap+1 哨兵
    assert peek["stats"]["limit"] == 2


async def test_kafka_peek_low_watermark(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    kafka = FakeKafka()
    kafka.peek_error = errors.GuardRejected(
        "offset 1 早于分区 low watermark 5", code=errors.DANGEROUS_OPERATION
    )
    _patch(monkeypatch, kafka=kafka)

    denied = await _error(
        runtime,
        "kafka_peek",
        {"target": "mq-kafka", "topic": "orders", "partition": 0, "offset": 1},
    )

    assert errors.DANGEROUS_OPERATION in denied
