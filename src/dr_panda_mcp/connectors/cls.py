"""CLS 只读连接器：列出日志集、检索日志、读取日志上下文。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import base
from dr_panda_mcp.guards import cls as cls_guard
from dr_panda_mcp.guards.protocol import Decision
from dr_panda_mcp.store.protocol import Target

_PROBE_WINDOW = timedelta(minutes=1)


def topic_id(topic: str) -> str:
    """登记的 topic 可以是 ``日志集ID/主题ID``；CLS API 需要最后一段 TopicId。"""
    return topic.rsplit("/", 1)[-1].strip()


def _epoch_seconds(value: float) -> float:
    """Normalize CLS epoch values that may be seconds or milliseconds."""
    ts = float(value)
    # 1e12 ms ≈ 2001-09-09; seconds will not reach 1e12 until year 33658.
    if abs(ts) >= 1_000_000_000_000:
        ts /= 1000.0
    return ts


def _time_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(_epoch_seconds(value), tz=UTC).isoformat(
            timespec="seconds"
        )
    return str(value)


def _btime_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # CLS DescribeLogContext 要求 UTC+8 的 "YYYY-mm-dd HH:MM:SS.FFF"。
        return datetime.fromtimestamp(
            _epoch_seconds(value), tz=timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S.000")
    return str(value)


def _content_from_item(item: Any, *, prefer_content: bool = False) -> str:
    """Map CLS log body fields; SearchLog prefers LogJson, context prefers Content."""
    candidates = (
        ("Content", "LogJson", "RawLog", "Log")
        if prefer_content
        else ("LogJson", "RawLog", "Log", "Content")
    )
    for name in candidates:
        value = getattr(item, name, None)
        if value:
            return str(value)
    return ""


def _looks_like_analysis(query: str) -> bool:
    return "|" in query


def _analysis_rows(response: Any, *, topic: str) -> list[dict[str, Any]]:
    """Map AnalysisResults / AnalysisRecords into flat row dicts."""
    rows: list[dict[str, Any]] = []
    analysis = getattr(response, "AnalysisResults", None) or []
    for item in analysis:
        data = getattr(item, "Data", None) or []
        row: dict[str, Any] = {"topic": topic}
        for pair in data:
            key = getattr(pair, "Key", None) or getattr(pair, "key", None)
            value = getattr(pair, "Value", None)
            if value is None:
                value = getattr(pair, "value", None)
            if key:
                row[str(key)] = value
        if len(row) > 1:
            rows.append(row)
    if rows:
        return rows

    records = getattr(response, "AnalysisRecords", None) or []
    for record in records:
        if isinstance(record, dict):
            rows.append({"topic": topic, **base.to_jsonable(record)})
            continue
        text = str(record)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            rows.append({"topic": topic, "content": text})
            continue
        if isinstance(parsed, dict):
            rows.append({"topic": topic, **base.to_jsonable(parsed)})
        else:
            rows.append({"topic": topic, "content": text})
    return rows


def _result_rows(response: Any, *, topic: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in getattr(response, "Results", None) or []:
        rows.append(
            {
                "time": _time_text(getattr(item, "Time", None)),
                "btime": _btime_text(
                    getattr(item, "BTime", None) or getattr(item, "Time", None)
                ),
                "topic": topic,
                "package_id": getattr(item, "PkgId", None),
                "package_log_id": getattr(item, "PkgLogId", None),
                "content": _content_from_item(item),
            }
        )
    return rows


class _CLSClient:
    def __init__(self, target: Target) -> None:
        self.target = target

    def _sdk(self):
        try:
            from tencentcloud.cls.v20201016 import cls_client, models
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise errors.UpstreamUnavailable(errors.missing_client_message("cls")) from exc
        options = self.target.options
        secrets = self.target.secret
        credential_obj = credential.Credential(
            secrets.get("secret_id", ""), secrets.get("secret_key", "")
        )
        # Tencent SDK's ClsClient/AbstractClient accepts
        # (credential, region, profile), not ``timeout``. The timeout belongs
        # on HttpProfile so it remains compatible across SDK minor versions.
        http_profile = HttpProfile(reqTimeout=int(base.timeout_seconds(self.target)))
        profile = ClientProfile(httpProfile=http_profile)
        client = cls_client.ClsClient(
            credential_obj,
            str(options.get("region", "")),
            profile,
        )
        return client, models

    async def ping(self) -> None:
        try:
            client, models = self._sdk()

            def _call() -> None:
                client.DescribeLogsets(models.DescribeLogsetsRequest())

            await asyncio.to_thread(_call)
        except errors.DrPandaError:
            raise
        except Exception as exc:
            raise errors.UpstreamUnavailable(
                f"cls probe failed: {type(exc).__name__}: {exc}"
            ) from exc

        topics = [str(item) for item in self.target.options.get("allowed_topics") or []]
        if not topics:
            return
        end = datetime.now(UTC)
        start = end - _PROBE_WINDOW
        for topic in topics:
            try:
                await self.search_log(
                    topic=topic,
                    query="*",
                    start=start,
                    end=end,
                    limit=1,
                    offset=0,
                )
            except errors.DrPandaError as exc:
                raise errors.UpstreamUnavailable(
                    f"cls topic probe failed for {topic}: {exc}"
                ) from exc

    async def search_log(
        self,
        *,
        topic: str,
        query: str,
        start: datetime,
        end: datetime,
        limit: int,
        offset: int = 0,
        sort: str = "desc",
        context: str = "",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        sort_value = sort.strip().lower() or "desc"
        if sort_value not in {"desc", "asc"}:
            raise errors.InvalidArgument("sort must be 'desc' or 'asc'")
        try:
            client, models = self._sdk()

            def _call():
                request = models.SearchLogRequest()
                request.TopicId = topic_id(topic)
                request.Query = query
                # Tencent CLS SearchLog requires Unix timestamps in milliseconds.
                request.From = int(start.timestamp() * 1000)
                request.To = int(end.timestamp() * 1000)
                request.Limit = limit
                request.Sort = sort_value
                if context.strip():
                    request.Context = context.strip()
                else:
                    request.Offset = offset
                if _looks_like_analysis(query):
                    # Prefer the newer analysis response shape when querying with `|`.
                    request.UseNewAnalysis = True
                return client.SearchLog(request)

            response = await asyncio.to_thread(_call)
        except errors.DrPandaError:
            raise
        except Exception as exc:
            raise errors.UpstreamUnavailable(
                f"cls search failed: {type(exc).__name__}: {exc}"
            ) from exc

        result_rows = _result_rows(response, topic=topic)
        analysis_rows = _analysis_rows(response, topic=topic)
        if result_rows:
            rows = result_rows
            mode = "search"
        elif analysis_rows:
            rows = analysis_rows
            mode = "analysis"
        elif _looks_like_analysis(query):
            rows = []
            mode = "analysis"
        else:
            rows = []
            mode = "search"

        stats = {
            "mode": mode,
            "next_context": getattr(response, "Context", None) or None,
            "list_over": getattr(response, "ListOver", None),
            "sort": sort_value,
        }
        return rows, stats

    async def describe_context(
        self,
        *,
        topic: str,
        log_id: str,
        btime: str,
        pkg_log_id: int,
        before: int,
        after: int,
    ) -> list[dict[str, Any]]:
        try:
            client, models = self._sdk()

            def _call():
                request = models.DescribeLogContextRequest()
                request.TopicId = topic_id(topic)
                request.PkgId = log_id
                request.BTime = btime
                request.PkgLogId = pkg_log_id
                request.PrevLogs = before
                request.NextLogs = after
                return client.DescribeLogContext(request)

            response = await asyncio.to_thread(_call)
        except errors.DrPandaError:
            raise
        except Exception as exc:
            raise errors.UpstreamUnavailable(
                f"cls context read failed: {type(exc).__name__}: {exc}"
            ) from exc

        items = (
            getattr(response, "LogContextInfos", None)
            or getattr(response, "ContextInfos", None)
            or getattr(response, "Results", None)
            or []
        )
        rows: list[dict[str, Any]] = []
        for item in items:
            rows.append(
                {
                    "time": _time_text(
                        getattr(item, "Time", None) or getattr(item, "BTime", None)
                    ),
                    "topic": topic,
                    "package_id": getattr(item, "PkgId", None),
                    "package_log_id": getattr(item, "PkgLogId", None),
                    "btime": _btime_text(
                        getattr(item, "BTime", None)
                        or getattr(item, "Time", None)
                    ),
                    "content": _content_from_item(item, prefer_content=True),
                }
            )
        return rows


class CLSConnector:
    name = "cls"

    def probe_guard(self) -> Decision:
        return cls_guard.check_cls("describe_logsets", {})

    def create_client(self, target: Target) -> _CLSClient:
        return _CLSClient(target)

    async def probe(self, client: _CLSClient, target: Target) -> None:
        await client.ping()

    async def close_client(self, client: _CLSClient) -> None:
        return None

    async def search_log(
        self,
        client: _CLSClient,
        target: Target,
        *,
        topic: str,
        query: str,
        start: datetime,
        end: datetime,
        limit: int,
        offset: int = 0,
        sort: str = "desc",
        context: str = "",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return await client.search_log(
            topic=topic,
            query=query,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
            sort=sort,
            context=context,
        )

    async def describe_context(
        self,
        client: _CLSClient,
        target: Target,
        *,
        topic: str,
        log_id: str,
        btime: str,
        pkg_log_id: int,
        before: int,
        after: int,
    ) -> list[dict[str, Any]]:
        return await client.describe_context(
            topic=topic,
            log_id=log_id,
            btime=btime,
            pkg_log_id=pkg_log_id,
            before=before,
            after=after,
        )


connector = CLSConnector()
