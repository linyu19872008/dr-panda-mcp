"""Nacos 只读工具：配置目录、配置内容、服务与实例。"""

from __future__ import annotations

import time
from typing import Any

from fastmcp import FastMCP

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import get_connector
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.store.protocol import Target
from dr_panda_mcp.tools.base import (
    TOOL_ANNOTATIONS,
    EnvironmentParam,
    finish,
    run_tool,
)


def _check_page(page: int, page_size: int) -> None:
    if page < 1 or page > 10_000:
        raise errors.InvalidArgument("page must be between 1 and 10000")
    if page_size < 1 or page_size > 100:
        raise errors.InvalidArgument("page_size must be between 1 and 100")


def register_nacos_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def nacos_configs(
        target: str,
        namespace: str = "",
        group: str = "",
        page: int = 1,
        page_size: int = 50,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """List authorized Nacos config metadata (dataId, group, type).

        namespace/group default when the target has exactly one authorized value.
        dataId content is not returned by this tool; use nacos_config to read it.
        """
        params = {
            "namespace": namespace or None,
            "group": group or None,
            "page": page,
            "page_size": page_size,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            _check_page(page, page_size)
            connector = get_connector("nacos")
            client = await runtime.catalog.client(tgt, connector)
            rows, total = await connector.configs(
                client,
                tgt,
                namespace=namespace,
                group=group,
                page=page,
                page_size=page_size,
            )
            return finish(
                tgt,
                summary=f"Nacos configs namespace={namespace or 'auto'} group={group or 'auto'}",
                started=started,
                rows=rows,
                stats={"page": page, "page_size": page_size, "total": total},
            )

        return await run_tool(
            runtime,
            tool="nacos_configs",
            name=target,
            environment=environment,
            target_type="nacos",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def nacos_config(
        target: str,
        data_id: str,
        namespace: str = "",
        group: str = "",
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Read one authorized Nacos config by dataId/group/namespace."""
        params = {
            "data_id": data_id,
            "namespace": namespace or None,
            "group": group or None,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("nacos")
            client = await runtime.catalog.client(tgt, connector)
            content = await connector.config(
                client,
                tgt,
                namespace=namespace,
                group=group,
                data_id=data_id,
            )
            return finish(
                tgt,
                summary=f"Nacos config {data_id}",
                started=started,
                rows=[
                    {
                        "data_id": data_id,
                        "group": group or None,
                        "namespace": namespace or None,
                        "content": content,
                    }
                ],
                stats={"bytes": len(content.encode("utf-8"))},
            )

        return await run_tool(
            runtime,
            tool="nacos_config",
            name=target,
            environment=environment,
            target_type="nacos",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def nacos_services(
        target: str,
        namespace: str = "",
        group: str = "",
        page: int = 1,
        page_size: int = 50,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """List authorized Nacos services (not instances)."""
        params = {
            "namespace": namespace or None,
            "group": group or None,
            "page": page,
            "page_size": page_size,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            _check_page(page, page_size)
            connector = get_connector("nacos")
            client = await runtime.catalog.client(tgt, connector)
            rows, total = await connector.services(
                client,
                tgt,
                namespace=namespace,
                group=group,
                page=page,
                page_size=page_size,
            )
            return finish(
                tgt,
                summary=f"Nacos services namespace={namespace or 'auto'} group={group or 'auto'}",
                started=started,
                rows=rows,
                stats={"page": page, "page_size": page_size, "total": total},
            )

        return await run_tool(
            runtime,
            tool="nacos_services",
            name=target,
            environment=environment,
            target_type="nacos",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def nacos_instances(
        target: str,
        service: str,
        namespace: str = "",
        group: str = "",
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """List instances of one authorized Nacos service with health and metadata."""
        params = {
            "service": service,
            "namespace": namespace or None,
            "group": group or None,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("nacos")
            client = await runtime.catalog.client(tgt, connector)
            rows = await connector.instances(
                client,
                tgt,
                namespace=namespace,
                group=group,
                service=service,
            )
            return finish(
                tgt,
                summary=f"Nacos instances {service}",
                started=started,
                rows=rows,
                stats={"service": service},
            )

        return await run_tool(
            runtime,
            tool="nacos_instances",
            name=target,
            environment=environment,
            target_type="nacos",
            params=params,
            handler=handler,
        )
