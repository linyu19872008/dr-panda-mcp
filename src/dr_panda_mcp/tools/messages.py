"""消息面：RabbitMQ 与 Kafka 五个只读工具（planning 8.6）。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

from fastmcp import FastMCP

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import base as connectors_base
from dr_panda_mcp.connectors import get_connector
from dr_panda_mcp.guards import kafka as kafka_guard
from dr_panda_mcp.guards import rabbit as rabbit_guard
from dr_panda_mcp.guards.protocol import require
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.store.protocol import Target
from dr_panda_mcp.tools.base import (
    TOOL_ANNOTATIONS,
    EnvironmentParam,
    clamp_limit,
    finish,
    run_tool,
    trim_rows,
)


def _allowed(target: Target, key: str) -> list[str]:
    return [str(item) for item in target.options.get(key, [])]


def ensure_vhost(target: Target, vhost: str) -> str:
    allowed = _allowed(target, "allowed_vhosts")
    value = (vhost or "").strip()
    if not value:
        raise errors.InvalidArgument("vhost is required")
    if not allowed:
        raise errors.ScopeDenied(f"target {target.name} has no authorized vhosts")
    if value not in allowed:
        raise errors.ScopeDenied(
            f"vhost {value} is not within the authorized scope of target {target.name}",
            allowed=allowed,
            hint="use a value from scope.allowed_vhosts",
        )
    return value


def ensure_topic(target: Target, topic: str) -> str:
    allowed = _allowed(target, "allowed_topics")
    value = (topic or "").strip()
    if not allowed:
        raise errors.ScopeDenied(f"target {target.name} has no authorized topics")
    if not value:
        raise errors.InvalidArgument(
            "topic is required",
            allowed=allowed,
            hint="use a value from scope.allowed_topics",
        )
    if value not in allowed:
        raise errors.ScopeDenied(
            f"topic {value} is not within the authorized scope of target {target.name}",
            allowed=allowed,
            hint="use a value from scope.allowed_topics",
        )
    return value


def register_message_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def rabbit_queues(
        target: str, vhost: str = "", environment: EnvironmentParam = ""
    ) -> dict[str, Any]:
        """List queues in authorized vhosts (messages, unacknowledged, consumers)."""
        params = {"vhost": vhost or None}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            allowed = _allowed(tgt, "allowed_vhosts")
            if not allowed:
                raise errors.ScopeDenied(f"target {tgt.name} has no authorized vhosts")
            vhosts = [ensure_vhost(tgt, vhost)] if vhost else allowed
            cap = connectors_base.max_rows(tgt)
            connector = get_connector("rabbitmq")
            client = await runtime.catalog.client(tgt, connector)
            rows: list[dict[str, Any]] = []
            truncated = False
            for index, name in enumerate(vhosts):
                if len(rows) >= cap:
                    truncated = index < len(vhosts)
                    break
                path = f"/api/queues/{quote(name, safe='')}"
                require(rabbit_guard.check_rabbit("GET", path))
                items = await connector.queues(client, tgt, vhost=name)
                for item in items:
                    rows.append(
                        {
                            "queue": item.get("name"),
                            "vhost": item.get("vhost"),
                            "messages": item.get("messages"),
                            "unacked": item.get("messages_unacknowledged"),
                            "consumers": item.get("consumers"),
                            "state": item.get("state"),
                        }
                    )
            truncated = truncated or len(rows) > cap
            return finish(
                tgt,
                summary=f"GET /api/queues vhosts={len(vhosts)}",
                started=started,
                rows=rows[:cap],
                stats={"vhosts": vhosts},
                truncation=connectors_base.Truncation("rows", cap) if truncated else None,
            )

        return await run_tool(
            runtime, tool="rabbit_queues", name=target, environment=environment, target_type="rabbitmq",
            params=params, handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def rabbit_queue(
        target: str, vhost: str, queue: str, environment: EnvironmentParam = ""
    ) -> dict[str, Any]:
        """Show details for a single queue."""
        params = {"vhost": vhost, "queue": queue}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            chosen = ensure_vhost(tgt, vhost)
            if not queue.strip():
                raise errors.InvalidArgument("queue must not be empty")
            path = f"/api/queues/{quote(chosen, safe='')}/{quote(queue, safe='')}"
            require(rabbit_guard.check_rabbit("GET", path))
            connector = get_connector("rabbitmq")
            client = await runtime.catalog.client(tgt, connector)
            item = await connector.queue(client, tgt, vhost=chosen, queue=queue)
            row = {
                "queue": item.get("name"),
                "vhost": item.get("vhost"),
                "messages": item.get("messages"),
                "unacked": item.get("messages_unacknowledged"),
                "consumers": item.get("consumers"),
                "state": item.get("state"),
                "durable": item.get("durable"),
                "arguments": item.get("arguments"),
            }
            return finish(
                tgt,
                summary=f"GET /api/queues/{chosen}/{queue}",
                started=started,
                rows=[row],
                stats={"vhost": chosen, "queue": queue},
            )

        return await run_tool(
            runtime, tool="rabbit_queue", name=target, environment=environment, target_type="rabbitmq",
            params=params, handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def kafka_lag(
        target: str, group: str, topic: str = "", environment: EnvironmentParam = ""
    ) -> dict[str, Any]:
        """Show a consumer group's offsets and lag per partition."""
        params = {"group": group, "topic": topic or None}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            if not group.strip():
                raise errors.InvalidArgument("group must not be empty")
            topics = [ensure_topic(tgt, topic)] if topic else _allowed(tgt, "allowed_topics")
            if not topics:
                raise errors.ScopeDenied(f"target {tgt.name} has no authorized topics")
            require(kafka_guard.check_kafka("describe_consumer_groups", {}))
            cap = connectors_base.max_rows(tgt)
            connector = get_connector("kafka")
            client = await runtime.catalog.client(tgt, connector)
            rows: list[dict[str, Any]] = []
            truncated = False
            for index, name in enumerate(topics):
                if len(rows) >= cap:
                    truncated = index < len(topics)
                    break
                rows.extend(await connector.lag(client, tgt, group=group, topic=name))
            truncated = truncated or len(rows) > cap
            return finish(
                tgt,
                summary=f"Kafka lag group={group} topics={len(topics)}",
                started=started,
                rows=rows[:cap],
                stats={"group": group, "topics": topics},
                truncation=connectors_base.Truncation("rows", cap) if truncated else None,
            )

        return await run_tool(
            runtime, tool="kafka_lag", name=target, environment=environment, target_type="kafka",
            params=params, handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def kafka_offsets(
        target: str, topic: str, environment: EnvironmentParam = ""
    ) -> dict[str, Any]:
        """Show the low / high watermark for each partition of a topic."""
        params = {"topic": topic}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            chosen = ensure_topic(tgt, topic)
            require(kafka_guard.check_kafka("list_offsets", {}))
            connector = get_connector("kafka")
            client = await runtime.catalog.client(tgt, connector)
            rows = await connector.offsets(client, tgt, topic=chosen)
            return finish(
                tgt,
                summary=f"Kafka offsets topic={chosen}",
                started=started,
                rows=rows,
                stats={"topic": chosen},
            )

        return await run_tool(
            runtime, tool="kafka_offsets", name=target, environment=environment, target_type="kafka",
            params=params, handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def kafka_peek(
        target: str,
        topic: str,
        partition: int,
        offset: int,
        limit: int = 10,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Fetch a bounded number of messages from one partition and offset (does not join a consumer group or commit offsets)."""
        params = {
            "topic": topic, "partition": partition, "offset": offset, "limit": limit,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            chosen = ensure_topic(tgt, topic)
            if partition < 0:
                raise errors.InvalidArgument("partition must not be negative")
            if offset < 0:
                raise errors.InvalidArgument("offset must not be negative")
            cap = clamp_limit(limit or None, tgt, 10)
            require(
                kafka_guard.check_kafka(
                    "fetch",
                    {
                        "partition": partition,
                        "offset": offset,
                        "limit": cap,
                    },
                )
            )
            connector = get_connector("kafka")
            client = await runtime.catalog.client(tgt, connector)
            fetched = await connector.peek(
                client,
                tgt,
                topic=chosen,
                partition=partition,
                offset=offset,
                limit=cap + 1,
            )
            rows, truncation = trim_rows(fetched, cap)
            return finish(
                tgt,
                summary=f"Kafka peek {chosen}[{partition}]@{offset} limit={cap}",
                started=started,
                rows=rows,
                stats={"topic": chosen, "partition": partition, "offset": offset, "limit": cap},
                truncation=truncation,
            )

        return await run_tool(
            runtime, tool="kafka_peek", name=target, environment=environment, target_type="kafka",
            params=params, handler=handler,
        )
