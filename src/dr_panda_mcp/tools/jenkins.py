"""Jenkins 只读工具：Job、构建、日志、节点和队列。"""

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


def register_jenkins_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def jenkins_jobs(
        target: str,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """List authorized Jenkins jobs with status color and description."""
        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("jenkins")
            client = await runtime.catalog.client(tgt, connector)
            rows = await client.jobs()
            return finish(
                tgt,
                summary="Jenkins jobs",
                started=started,
                rows=rows,
                stats={"jobs": len(rows)},
            )

        return await run_tool(
            runtime,
            tool="jenkins_jobs",
            name=target,
            environment=environment,
            target_type="jenkins",
            params={},
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def jenkins_job(
        target: str,
        job: str,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Read one authorized Jenkins job's status and last builds."""
        params = {"job": job}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("jenkins")
            client = await runtime.catalog.client(tgt, connector)
            row = await client.job(job)
            return finish(
                tgt,
                summary=f"Jenkins job {job}",
                started=started,
                rows=[row],
                stats={"job": job},
            )

        return await run_tool(
            runtime,
            tool="jenkins_job",
            name=target,
            environment=environment,
            target_type="jenkins",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def jenkins_builds(
        target: str,
        job: str,
        limit: int = 0,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """List recent builds for one authorized Jenkins job (bounded)."""
        params = {"job": job, "limit": limit}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            if limit and not 1 <= limit <= 100:
                raise errors.InvalidArgument("limit must be between 1 and 100")
            connector = get_connector("jenkins")
            client = await runtime.catalog.client(tgt, connector)
            rows = await client.builds(job, limit or None)
            return finish(
                tgt,
                summary=f"Jenkins builds {job}",
                started=started,
                rows=rows,
                stats={"job": job, "returned": len(rows)},
            )

        return await run_tool(
            runtime,
            tool="jenkins_builds",
            name=target,
            environment=environment,
            target_type="jenkins",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def jenkins_build(
        target: str,
        job: str,
        build_number: int,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Read one authorized Jenkins build's result, duration and parameters."""
        params = {"job": job, "build_number": build_number}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("jenkins")
            client = await runtime.catalog.client(tgt, connector)
            row = await client.build(job, build_number)
            return finish(
                tgt,
                summary=f"Jenkins build {job} #{build_number}",
                started=started,
                rows=[row],
                stats={"job": job, "build_number": build_number},
            )

        return await run_tool(
            runtime,
            tool="jenkins_build",
            name=target,
            environment=environment,
            target_type="jenkins",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def jenkins_console(
        target: str,
        job: str,
        build_number: int,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Read a bounded Jenkins build console log (target must allow it)."""
        params = {"job": job, "build_number": build_number}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("jenkins")
            client = await runtime.catalog.client(tgt, connector)
            content, cut = await client.console(job, build_number)
            return finish(
                tgt,
                summary=f"Jenkins console {job} #{build_number}",
                started=started,
                rows=[
                    {
                        "job": job,
                        "build_number": build_number,
                        "content": content,
                        "truncated": cut,
                    }
                ],
                stats={"job": job, "build_number": build_number, "bytes": len(content.encode("utf-8"))},
            )

        return await run_tool(
            runtime,
            tool="jenkins_console",
            name=target,
            environment=environment,
            target_type="jenkins",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def jenkins_nodes(
        target: str,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """List authorized Jenkins nodes, offline reasons and executors."""
        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("jenkins")
            client = await runtime.catalog.client(tgt, connector)
            rows = await client.nodes()
            return finish(
                tgt,
                summary="Jenkins nodes",
                started=started,
                rows=rows,
                stats={"nodes": len(rows)},
            )

        return await run_tool(
            runtime,
            tool="jenkins_nodes",
            name=target,
            environment=environment,
            target_type="jenkins",
            params={},
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def jenkins_queue(
        target: str,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """List authorized Jenkins queue items and blocking reasons."""
        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            connector = get_connector("jenkins")
            client = await runtime.catalog.client(tgt, connector)
            rows = await client.queue()
            return finish(
                tgt,
                summary="Jenkins queue",
                started=started,
                rows=rows,
                stats={"items": len(rows)},
            )

        return await run_tool(
            runtime,
            tool="jenkins_queue",
            name=target,
            environment=environment,
            target_type="jenkins",
            params={},
            handler=handler,
        )
