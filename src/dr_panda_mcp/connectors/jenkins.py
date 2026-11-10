"""Jenkins 只读连接器：Job、Build、Console、Node、Queue（只发 GET）。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import base
from dr_panda_mcp.guards import jenkins as jenkins_guard
from dr_panda_mcp.guards.protocol import Decision, require
from dr_panda_mcp.store.protocol import Target

_JOB_TREE = (
    "jobs[name,url,color,description,"
    "jobs[name,url,color,description,"
    "jobs[name,url,color,description]]]"
)


def _items(target: Target, key: str) -> list[str]:
    return [str(item).strip() for item in (target.options.get(key) or []) if str(item).strip()]


def _bounded_builds(target: Target) -> int:
    raw = target.options.get("max_builds", 20)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 20
    return min(max(value, 1), 100)


def _job_path(job: str) -> str:
    name = (job or "").strip().strip("/")
    if not name:
        raise errors.InvalidArgument("job is required")
    parts = [part for part in name.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise errors.InvalidArgument("job name is invalid")
    return "".join(f"/job/{quote(part, safe='')}" for part in parts)


def _full_name_from_url(value: str) -> str:
    path = urlparse(value).path
    if "/job/" not in path:
        return ""
    parts = path.split("/job/")[1:]
    return "/".join(unquote(part.strip("/")) for part in parts)


def ensure_job(target: Target, value: str) -> str:
    allowed = _items(target, "allowed_jobs")
    candidate = (value or "").strip().strip("/")
    if not candidate:
        raise errors.InvalidArgument("job is required")
    if not allowed:
        raise errors.ScopeDenied(f"target {target.name} has no authorized jobs")
    if candidate not in allowed:
        raise errors.ScopeDenied(
            f"job {candidate} is not within the authorized scope of target {target.name}",
            allowed=allowed,
            hint="use a full job name from scope.allowed_jobs",
        )
    return candidate


def ensure_node(target: Target, value: str) -> str:
    allowed = _items(target, "allowed_nodes")
    candidate = (value or "").strip()
    if not allowed:
        raise errors.ScopeDenied(f"target {target.name} has no authorized nodes")
    if candidate not in allowed:
        raise errors.ScopeDenied(
            f"node {candidate} is not within the authorized scope of target {target.name}",
            allowed=allowed,
            hint="use a displayName from scope.allowed_nodes",
        )
    return candidate


class _JenkinsClient:
    def __init__(self, target: Target) -> None:
        self.target = target

    def _client(self) -> httpx.AsyncClient:
        options = self.target.options
        base_url = str(options.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise errors.UpstreamUnavailable("jenkins target has no base_url configured")
        verify: bool | str = bool(options.get("verify_tls", True))
        ca_pem = str(options.get("ca_pem") or "").strip()
        if ca_pem:
            verify = base.build_tls_context(ca_pem=ca_pem)
        username = str(options.get("username") or "").strip()
        token = self.target.secret.get("api_token", "")
        auth = (username, token) if username and token else None
        return httpx.AsyncClient(
            base_url=base_url,
            verify=verify,
            auth=auth,
            timeout=base.timeout_seconds(self.target),
            headers={"Accept": "application/json"},
        )

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        truncate: bool = False,
    ) -> tuple[httpx.Response, bool]:
        require(jenkins_guard.check_jenkins("GET", path))
        client = self._client()
        try:
            return await base.stream_http(
                client,
                "GET",
                path,
                component="jenkins",
                limit=base.max_bytes(self.target),
                params=params,
                truncate=truncate,
            )
        except errors.DrPandaError:
            raise
        except Exception as exc:
            raise errors.UpstreamUnavailable(
                f"jenkins request failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            await client.aclose()

    async def ping(self) -> None:
        await self._get("/api/json", {"tree": "mode,nodeDescription,useSecurity"})

    async def jobs(self) -> list[dict[str, Any]]:
        response, _ = await self._get("/api/json", {"tree": _JOB_TREE})
        payload = _json(response, "jobs")
        root = payload.get("jobs")
        if not isinstance(root, list):
            root = []
        allowed = set(_items(self.target, "allowed_jobs"))
        rows: list[dict[str, Any]] = []

        def walk(items: list[Any]) -> None:
            for item in items:
                if not isinstance(item, dict):
                    continue
                full = str(item.get("fullName") or "") or _full_name_from_url(str(item.get("url") or ""))
                if full and full in allowed:
                    rows.append(
                        {
                            "job": full,
                            "name": item.get("name"),
                            "url": item.get("url"),
                            "color": item.get("color"),
                            "description": item.get("description"),
                        }
                    )
                nested = item.get("jobs")
                if isinstance(nested, list):
                    walk(nested)

        walk(root)
        return rows

    async def job(self, job: str) -> dict[str, Any]:
        chosen = ensure_job(self.target, job)
        response, _ = await self._get(
            f"{_job_path(chosen)}/api/json",
            {
                "tree": (
                    "name,url,color,description,buildable,"
                    "lastBuild[number,result,displayName,duration,timestamp,url],"
                    "lastCompletedBuild[number,result,displayName,duration,timestamp,url],"
                    "lastFailedBuild[number,result,displayName,duration,timestamp,url],"
                    "lastSuccessfulBuild[number,result,displayName,duration,timestamp,url]"
                )
            },
        )
        payload = _json(response, "job")
        return {
            "job": chosen,
            "name": payload.get("name"),
            "url": payload.get("url"),
            "color": payload.get("color"),
            "description": payload.get("description"),
            "buildable": payload.get("buildable"),
            "last_build": base.to_jsonable(payload.get("lastBuild") or {}),
            "last_completed_build": base.to_jsonable(payload.get("lastCompletedBuild") or {}),
            "last_failed_build": base.to_jsonable(payload.get("lastFailedBuild") or {}),
            "last_successful_build": base.to_jsonable(payload.get("lastSuccessfulBuild") or {}),
        }

    async def builds(self, job: str, limit: int | None = None) -> list[dict[str, Any]]:
        chosen = ensure_job(self.target, job)
        count = min(max(int(limit or _bounded_builds(self.target)), 1), 100)
        response, _ = await self._get(
            f"{_job_path(chosen)}/api/json",
            {"tree": f"builds[number,result,displayName,duration,timestamp,url]{{0,{count}}}"},
        )
        payload = _json(response, "builds")
        builds = payload.get("builds")
        if not isinstance(builds, list):
            builds = []
        return [
            {
                "job": chosen,
                "number": item.get("number"),
                "result": item.get("result"),
                "display_name": item.get("displayName"),
                "duration_ms": item.get("duration"),
                "timestamp": item.get("timestamp"),
                "url": item.get("url"),
            }
            for item in builds
            if isinstance(item, dict)
        ]

    async def build(self, job: str, number: int) -> dict[str, Any]:
        chosen = ensure_job(self.target, job)
        if number < 1:
            raise errors.InvalidArgument("build_number must be positive")
        response, _ = await self._get(
            f"{_job_path(chosen)}/{number}/api/json",
            {
                "tree": (
                    "number,result,displayName,duration,timestamp,url,building,description,"
                    "actions[parameters[name,value]]"
                )
            },
        )
        payload = _json(response, "build")
        return {
            "job": chosen,
            "number": payload.get("number"),
            "result": payload.get("result"),
            "display_name": payload.get("displayName"),
            "duration_ms": payload.get("duration"),
            "timestamp": payload.get("timestamp"),
            "url": payload.get("url"),
            "building": payload.get("building"),
            "description": payload.get("description"),
            "parameters": _parameters(payload.get("actions")),
        }

    async def console(self, job: str, number: int) -> tuple[str, bool]:
        chosen = ensure_job(self.target, job)
        if not self.target.options.get("allow_console", False):
            raise errors.ScopeDenied(f"target {self.target.name} does not allow console log reads")
        if number < 1:
            raise errors.InvalidArgument("build_number must be positive")
        response, cut = await self._get(
            f"{_job_path(chosen)}/{number}/consoleText", truncate=True
        )
        return response.text, cut

    async def nodes(self) -> list[dict[str, Any]]:
        allowed = _items(self.target, "allowed_nodes")
        if not allowed:
            raise errors.ScopeDenied(f"target {self.target.name} has no authorized nodes")
        response, _ = await self._get(
            "/computer/api/json",
            {
                "tree": (
                    "computer[displayName,offline,offlineCauseReason,numExecutors,"
                    "busyExecutors,totalExecutors,assignedLabels[name]]"
                )
            },
        )
        payload = _json(response, "nodes")
        computers = payload.get("computer")
        if not isinstance(computers, list):
            computers = []
        selected = set(allowed)
        return [
            {
                "node": item.get("displayName"),
                "offline": item.get("offline"),
                "offline_reason": item.get("offlineCauseReason"),
                "num_executors": item.get("numExecutors"),
                "busy_executors": item.get("busyExecutors"),
                "total_executors": item.get("totalExecutors"),
                "labels": [label.get("name") for label in item.get("assignedLabels") or [] if isinstance(label, dict)],
            }
            for item in computers
            if isinstance(item, dict) and str(item.get("displayName")) in selected
        ]

    async def queue(self) -> list[dict[str, Any]]:
        allowed = set(_items(self.target, "allowed_jobs"))
        response, _ = await self._get(
            "/queue/api/json",
            {
                "tree": (
                    "items[task[name,url],why,inQueueSince,stuck,blocked,"
                    "buildableStartMilliseconds]"
                )
            },
        )
        payload = _json(response, "queue")
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            task = item.get("task") if isinstance(item.get("task"), dict) else {}
            full = str(task.get("fullName") or "") or _full_name_from_url(str(task.get("url") or ""))
            if full not in allowed:
                continue
            rows.append(
                {
                    "job": full,
                    "why": item.get("why"),
                    "in_queue_since": item.get("inQueueSince"),
                    "stuck": item.get("stuck"),
                    "blocked": item.get("blocked"),
                    "buildable_start_ms": item.get("buildableStartMilliseconds"),
                }
            )
        return rows


def _json(response: httpx.Response, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise errors.UpstreamUnavailable(f"jenkins {context} returned non-JSON content") from exc
    if not isinstance(payload, dict):
        raise errors.UpstreamUnavailable(f"jenkins {context} returned an unexpected format")
    return payload


def _parameters(actions: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(actions, list):
        return result
    for action in actions:
        if not isinstance(action, dict):
            continue
        params = action.get("parameters")
        if isinstance(params, list):
            for item in params:
                if isinstance(item, dict):
                    result.append(
                        {"name": item.get("name"), "value": base.to_jsonable(item.get("value"))}
                    )
    return result


class JenkinsConnector:
    name = "jenkins"

    def probe_guard(self) -> Decision:
        return jenkins_guard.check_jenkins("GET", "/api/json")

    def create_client(self, target: Target) -> _JenkinsClient:
        return _JenkinsClient(target)

    async def probe(self, client: _JenkinsClient, target: Target) -> None:
        await client.ping()

    async def close_client(self, client: _JenkinsClient) -> None:
        return None

    async def jobs(
        self, client: _JenkinsClient, target: Target
    ) -> list[dict[str, Any]]:
        return await client.jobs()

    async def job(
        self, client: _JenkinsClient, target: Target, *, job: str
    ) -> dict[str, Any]:
        return await client.job(job)

    async def builds(
        self,
        client: _JenkinsClient,
        target: Target,
        *,
        job: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return await client.builds(job, limit)

    async def build(
        self,
        client: _JenkinsClient,
        target: Target,
        *,
        job: str,
        number: int,
    ) -> dict[str, Any]:
        return await client.build(job, number)

    async def console(
        self,
        client: _JenkinsClient,
        target: Target,
        *,
        job: str,
        number: int,
    ) -> tuple[str, bool]:
        return await client.console(job, number)

    async def nodes(
        self, client: _JenkinsClient, target: Target
    ) -> list[dict[str, Any]]:
        return await client.nodes()

    async def queue(
        self, client: _JenkinsClient, target: Target
    ) -> list[dict[str, Any]]:
        return await client.queue()


connector = JenkinsConnector()
