"""日志到代码：CLS 与 GitLab 五个只读工具（planning 8.4）。"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import base as connectors_base
from dr_panda_mcp.connectors import get_connector
from dr_panda_mcp.guards import cls as cls_guard
from dr_panda_mcp.guards import gitlab as gitlab_guard
from dr_panda_mcp.guards.protocol import require
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.store.protocol import Target
from dr_panda_mcp.tools.base import (
    TOOL_ANNOTATIONS,
    EnvironmentParam,
    allowed_projects,
    clamp_limit,
    ensure_project,
    ensure_topic,
    finish,
    run_tool,
    trim_rows,
)

_WIDE_WINDOW_HINT_MINUTES = 120
_COMPACT_CONTENT_LIMIT = 2000
_COMPACT_KEYS = ("time", "btime", "package_id", "package_log_id", "content")


def _utc_iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _merge_packages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent rows that share the same package_id into one content block."""
    merged: list[dict[str, Any]] = []
    for row in rows:
        package_id = row.get("package_id")
        if (
            package_id
            and merged
            and merged[-1].get("package_id") == package_id
            and "content" in row
        ):
            previous = merged[-1]
            previous_content = str(previous.get("content") or "")
            next_content = str(row.get("content") or "")
            if previous_content and next_content:
                previous["content"] = previous_content + "\n" + next_content
            elif next_content:
                previous["content"] = next_content
            continue
        merged.append(dict(row))
    return merged


def _compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for row in rows:
        item = {key: row.get(key) for key in _COMPACT_KEYS if key in row}
        content = item.get("content")
        if isinstance(content, str) and len(content) > _COMPACT_CONTENT_LIMIT:
            item["content"] = content[: _COMPACT_CONTENT_LIMIT - 1] + "…"
            item["content_truncated"] = True
        compacted.append(item)
    return compacted


def register_logs_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def cls_search(
        target: str,
        query: str,
        topic: str,
        from_: Annotated[str, Field(alias="from")],
        to: Annotated[str, Field(alias="to")],
        limit: int = 0,
        offset: int = 0,
        sort: str = "desc",
        context: str = "",
        merge_packages: bool = False,
        compact: bool = False,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Search CLS logs. Requires from/to (ISO8601); window max 24h.

        topic must be an authorized scope value: logsetId/topicId UUIDs, not a
        friendly name. Default sort is desc (newest first); for a specific
        incident time, shrink from/to around that moment. Queries with
        `| SELECT` return analysis rows (stats.mode=analysis). Pass
        stats.next_context as context to page beyond offset. Optional
        merge_packages joins adjacent same-package lines; compact keeps a
        smaller field set.
        """
        params = {
            "query": query,
            "topic": topic,
            "from": from_,
            "to": to,
            "limit": limit or None,
            "offset": offset or None,
            "sort": sort or None,
            "context": context or None,
            "merge_packages": merge_packages or None,
            "compact": compact or None,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            if not query.strip():
                raise errors.InvalidArgument("query must not be empty")
            if offset < 0 or offset > 10_000:
                raise errors.InvalidArgument("offset must be between 0 and 10000")
            sort_value = (sort or "desc").strip().lower() or "desc"
            if sort_value not in {"desc", "asc"}:
                raise errors.InvalidArgument("sort must be 'desc' or 'asc'")
            max_window = int(tgt.options.get("max_window_minutes", 1440) or 1440)
            window = require(
                cls_guard.check_cls(
                    "search_log",
                    {"from": from_, "to": to},
                    max_window_minutes=max_window,
                )
            )
            chosen_topic = ensure_topic(tgt, topic)
            cap = clamp_limit(limit or None, tgt, connectors_base.max_rows(tgt))
            connector = get_connector("cls")
            client = await runtime.catalog.client(tgt, connector)
            fetched, search_stats = await connector.search_log(
                client,
                tgt,
                topic=chosen_topic,
                query=query,
                start=window["from"],
                end=window["to"],
                limit=cap + 1,
                offset=offset,
                sort=sort_value,
                context=context,
            )
            if merge_packages:
                fetched = _merge_packages(fetched)
            if compact:
                fetched = _compact_rows(fetched)
            rows, truncation = trim_rows(fetched, cap)
            notes: list[str] = []
            window_minutes = (window["to"] - window["from"]).total_seconds() / 60.0
            if (
                sort_value == "desc"
                and window_minutes > _WIDE_WINDOW_HINT_MINUTES
                and search_stats.get("mode") == "search"
            ):
                notes.append(
                    "Results are newest-first within a wide window; for a specific "
                    "incident time, shrink from/to around that moment."
                )
            if context.strip() and offset:
                notes.append(
                    "Both context and offset were set; CLS paging used context and "
                    "ignored offset."
                )
            stats = {
                "topic": chosen_topic,
                "query": query,
                "offset": offset,
                "sort": sort_value,
                "mode": search_stats.get("mode"),
                "next_context": search_stats.get("next_context"),
                "list_over": search_stats.get("list_over"),
                "merge_packages": bool(merge_packages),
                "compact": bool(compact),
            }
            return finish(
                tgt,
                summary=f"SearchLog topic={chosen_topic} query={query[:80]}",
                started=started,
                rows=rows,
                stats=stats,
                time_range={
                    "from": _utc_iso(window["from"]),
                    "to": _utc_iso(window["to"]),
                },
                truncation=truncation,
                notes=notes,
            )

        return await run_tool(
            runtime,
            tool="cls_search",
            name=target, environment=environment,
            target_type="cls",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def cls_context(
        target: str,
        topic: str,
        log_id: str,
        btime: str,
        pkg_log_id: int,
        before: int = 10,
        after: int = 10,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Read context around one CLS log (use package_id/btime/package_log_id from cls_search).

        topic must be an authorized logsetId/topicId from scope.allowed_topics.
        """
        params = {
            "topic": topic,
            "log_id": log_id,
            "btime": btime,
            "pkg_log_id": pkg_log_id,
            "before": before,
            "after": after,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            require(cls_guard.check_cls("describe_log_context", {}))
            chosen_topic = ensure_topic(tgt, topic)
            if not log_id.strip():
                raise errors.InvalidArgument("log_id must not be empty")
            if not btime.strip():
                raise errors.InvalidArgument(
                    "btime must not be empty (use the btime returned by cls_search)"
                )
            if pkg_log_id < 1:
                raise errors.InvalidArgument(
                    "pkg_log_id must be a positive integer "
                    "(use the package_log_id returned by cls_search)"
                )
            if not 0 <= before <= 20 or not 0 <= after <= 20:
                raise errors.InvalidArgument(
                    "before / after must be between 0 and 20"
                )
            connector = get_connector("cls")
            client = await runtime.catalog.client(tgt, connector)
            rows = await connector.describe_context(
                client,
                tgt,
                topic=chosen_topic,
                log_id=log_id,
                btime=btime,
                pkg_log_id=pkg_log_id,
                before=before,
                after=after,
            )
            return finish(
                tgt,
                summary=f"DescribeLogContext topic={chosen_topic} pkg={log_id}",
                started=started,
                rows=rows,
                stats={
                    "topic": chosen_topic,
                    "before": before,
                    "after": after,
                    "package_log_id": pkg_log_id,
                },
            )

        return await run_tool(
            runtime,
            tool="cls_context",
            name=target, environment=environment,
            target_type="cls",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def gitlab_search_code(
        target: str,
        query: str,
        project: str = "",
        ref: str = "",
        limit: int = 20,
        page: int = 1,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Search code in GitLab projects; when project is omitted, only authorized projects are searched."""
        params = {
            "query": query,
            "project": project or None,
            "ref": ref or None,
            "limit": limit,
            "page": page,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            if not query.strip():
                raise errors.InvalidArgument("query must not be empty")
            require(gitlab_guard.check_gitlab("GET", "/api/v4/projects/search"))
            projects = (
                [ensure_project(tgt, project)] if project else allowed_projects(tgt)
            )
            if page < 1 or page > 10_000:
                raise errors.InvalidArgument("page must be between 1 and 10000")
            cap = clamp_limit(limit, tgt, 20)
            connector = get_connector("gitlab")
            client = await runtime.catalog.client(tgt, connector)
            rows: list[dict[str, Any]] = []
            for name in projects:
                if len(rows) >= cap + 1:
                    break
                items = await connector.search_code(
                    client,
                    tgt,
                    project=name,
                    query=query,
                    ref=ref or None,
                    limit=min(cap + 1 - len(rows), 100),
                    page=page,
                )
                for item in items:
                    rows.append(
                        {
                            "project": name,
                            "path": item.get("path") or item.get("filename"),
                            "line": item.get("startline"),
                            "snippet": (item.get("data") or "").strip()[:500],
                        }
                    )
            # 跨项目搜索时保持结果总量受上限约束
            rows, truncation = trim_rows(rows, cap)
            return finish(
                tgt,
                summary=f"GitLab search blobs query={query[:80]} projects={len(projects)}",
                started=started,
                rows=rows,
                stats={"projects": projects, "query": query, "page": page},
                truncation=truncation,
            )

        return await run_tool(
            runtime,
            tool="gitlab_search_code",
            name=target, environment=environment,
            target_type="gitlab",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def gitlab_get_file(
        target: str,
        project: str,
        path: str,
        ref: str = "",
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Read one file from a GitLab project (truncated at the byte limit)."""
        params = {"project": project, "path": path, "ref": ref or None}

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            chosen_project = ensure_project(tgt, project)
            require(gitlab_guard.check_gitlab("GET", "/api/v4/projects/repository/files"))
            if not path.strip():
                raise errors.InvalidArgument("path must not be empty")
            connector = get_connector("gitlab")
            client = await runtime.catalog.client(tgt, connector)
            content, upstream_truncated = await connector.get_file(
                client, tgt, project=chosen_project, path=path, ref=ref or None
            )
            byte_limit = connectors_base.max_bytes(tgt)
            truncated = upstream_truncated or len(content.encode("utf-8")) > byte_limit
            if truncated and not upstream_truncated:
                # 给 JSON 字段名留余量，避免包络二次字节检查把整行丢掉
                content = content.encode("utf-8")[: max(byte_limit - 1024, 1)].decode(
                    "utf-8", "ignore"
                )
            return finish(
                tgt,
                summary=f"GitLab file {chosen_project}/{path}",
                started=started,
                rows=[{"path": path, "ref": ref or None, "content": content}],
                stats={"path": path, "ref": ref or None, "bytes": len(content.encode())},
                truncation=connectors_base.Truncation("bytes", byte_limit)
                if truncated
                else None,
            )

        return await run_tool(
            runtime,
            tool="gitlab_get_file",
            name=target, environment=environment,
            target_type="gitlab",
            params=params,
            handler=handler,
        )

    @server.tool(annotations=TOOL_ANNOTATIONS)
    async def gitlab_blame(
        target: str,
        project: str,
        path: str,
        ref: str = "",
        line_from: int = 0,
        line_to: int = 0,
        environment: EnvironmentParam = "",
    ) -> dict[str, Any]:
        """Show recent changes to a file (optionally restricted to a line range)."""
        params = {
            "project": project,
            "path": path,
            "ref": ref or None,
            "line_from": line_from or None,
            "line_to": line_to or None,
        }

        async def handler(tgt: Target) -> dict[str, Any]:
            started = time.monotonic()
            chosen_project = ensure_project(tgt, project)
            require(gitlab_guard.check_gitlab("GET", "/api/v4/projects/repository/blame"))
            if not path.strip():
                raise errors.InvalidArgument("path must not be empty")
            if line_from < 0 or line_to < 0 or (line_to and line_from and line_to < line_from):
                raise errors.InvalidArgument("invalid line number range")
            connector = get_connector("gitlab")
            client = await runtime.catalog.client(tgt, connector)
            payload = await connector.blame(
                client,
                tgt,
                project=chosen_project,
                path=path,
                ref=ref or None,
                line_from=line_from or None,
                line_to=line_to or None,
            )
            rows: list[dict[str, Any]] = []
            line_number = line_from or 1
            for group in payload:
                commit = group.get("commit") or {}
                for text in group.get("lines") or []:
                    rows.append(
                        {
                            "line": line_number,
                            "commit": (commit.get("short_id") or commit.get("id") or "")[:10],
                            "author": commit.get("author_name"),
                            "date": commit.get("committed_date")
                            or commit.get("authored_date"),
                            "content": str(text)[:500],
                        }
                    )
                    line_number += 1
            return finish(
                tgt,
                summary=f"GitLab blame {chosen_project}/{path}",
                started=started,
                rows=rows,
                stats={"path": path, "ref": ref or None},
            )

        return await run_tool(
            runtime,
            tool="gitlab_blame",
            name=target, environment=environment,
            target_type="gitlab",
            params=params,
            handler=handler,
        )
