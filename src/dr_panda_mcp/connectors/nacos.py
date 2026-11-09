"""Nacos 只读连接器：配置查询与服务发现（只发 GET）。

同时支持 Nacos 1.x/2.x 的 v1 OpenAPI 与 Nacos 3.x 的 v3 client API。
v3 的配置/服务列表没有等价的 OpenAPI，因此列表按目标配置的显式白名单
（allowed_data_ids / allowed_services）生成，不要求 Nacos 管理员权限。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from dr_panda_mcp import errors
from dr_panda_mcp.connectors import base
from dr_panda_mcp.guards import nacos as nacos_guard
from dr_panda_mcp.guards.protocol import Decision, require
from dr_panda_mcp.store.protocol import Target

_DEFAULT_GROUP = "DEFAULT_GROUP"
_TOKEN_TTL_FALLBACK = 1800
_API_VERSIONS = {"auto", "v1", "v3"}


def _base_url(target: Target) -> str:
    raw = str(target.options.get("base_url") or "").strip().rstrip("/")
    if not raw:
        raise errors.UpstreamUnavailable("nacos target has no base_url configured")
    return raw if raw.endswith("/nacos") else f"{raw}/nacos"


def _items(target: Target, key: str) -> list[str]:
    return [str(item).strip() for item in (target.options.get(key) or []) if str(item).strip()]


def _tenant(namespace: str) -> str:
    """Nacos public namespace is represented by an empty tenant/namespace ID."""
    return "" if (namespace or "").strip().lower() == "public" else (namespace or "").strip()


def _api_version(target: Target) -> str:
    value = str(target.options.get("api_version") or "auto").strip().lower()
    return value if value in _API_VERSIONS else "auto"


def ensure_namespace(target: Target, value: str) -> str:
    allowed = _items(target, "allowed_namespaces")
    candidate = (value or "").strip()
    if not candidate:
        if len(allowed) == 1:
            candidate = allowed[0]
        else:
            raise errors.InvalidArgument("namespace is required (the target has multiple allowed namespaces)")
    if candidate not in allowed:
        raise errors.ScopeDenied(
            f"namespace {candidate} is not within the authorized scope of target {target.name}"
        )
    return candidate


def ensure_group(target: Target, value: str) -> str:
    allowed = _items(target, "allowed_groups")
    candidate = (value or "").strip()
    if not candidate:
        if len(allowed) == 1:
            candidate = allowed[0]
        else:
            raise errors.InvalidArgument("group is required (the target has multiple allowed groups)")
    if candidate not in allowed:
        raise errors.ScopeDenied(
            f"group {candidate} is not within the authorized scope of target {target.name}"
        )
    return candidate


def ensure_data_id(target: Target, value: str) -> str:
    allowed = _items(target, "allowed_data_ids")
    candidate = (value or "").strip()
    if not candidate:
        raise errors.InvalidArgument("data_id is required")
    if not allowed:
        raise errors.ScopeDenied(f"target {target.name} has no authorized data IDs")
    if candidate not in allowed:
        raise errors.ScopeDenied(
            f"data_id {candidate} is not within the authorized scope of target {target.name}"
        )
    return candidate


def ensure_service(target: Target, value: str) -> str:
    allowed = _items(target, "allowed_services")
    candidate = (value or "").strip()
    if not candidate:
        raise errors.InvalidArgument("service is required")
    if not allowed:
        raise errors.ScopeDenied(f"target {target.name} has no authorized services")
    if candidate not in allowed:
        raise errors.ScopeDenied(
            f"service {candidate} is not within the authorized scope of target {target.name}"
        )
    return candidate


def _json_object(response: httpx.Response, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise errors.UpstreamUnavailable(f"nacos {context} returned non-JSON content") from exc
    if not isinstance(payload, dict):
        raise errors.UpstreamUnavailable(f"nacos {context} returned an unexpected format")
    return payload


def _v3_data(response: httpx.Response, context: str) -> Any:
    payload = _json_object(response, context)
    code = payload.get("code")
    if code not in (0, "0", None):
        message = str(payload.get("message") or "nacos request failed")
        if int(code) in (401, 403):
            raise errors.UpstreamAuthError(message)
        if int(code) in (404, 20004):
            raise errors.UpstreamNotFound(message)
        raise errors.UpstreamUnavailable(f"nacos {context} failed: code={code} message={message}")
    return payload.get("data")


def _v3_config_content(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        content = data.get("content")
        if content is None:
            return ""
        return str(content)
    return ""


class _NacosClient:
    def __init__(self, target: Target) -> None:
        self.target = target
        self._access_token: str | None = None
        self._token_expiry = 0.0
        self._version: str | None = None

    def _client(self) -> httpx.AsyncClient:
        options = self.target.options
        verify: bool | str = bool(options.get("verify_tls", True))
        ca_pem = str(options.get("ca_pem") or "").strip()
        if ca_pem:
            verify = base.build_tls_context(ca_pem=ca_pem)
        return httpx.AsyncClient(
            base_url=_base_url(self.target),
            verify=verify,
            timeout=base.timeout_seconds(self.target),
        )

    async def _ensure_version(self, client: httpx.AsyncClient) -> str:
        if self._version:
            return self._version
        configured = _api_version(self.target)
        if configured in ("v1", "v3"):
            self._version = configured
            return configured
        # Nacos 1.x/2.x answers the public v1 liveness endpoint with 200.
        # Nacos 3.x answers with 410 Gone and points at the v3 API.
        response = await client.get("/v1/console/health/liveness")
        self._version = "v3" if response.status_code == 410 else "v1"
        return self._version

    async def _login(self, client: httpx.AsyncClient) -> str:
        username = str(self.target.options.get("username") or "").strip()
        password = self.target.secret.get("password", "")
        if not username:
            return ""
        if not password:
            raise errors.UpstreamAuthError("nacos username is configured but password is missing")
        version = await self._ensure_version(client)
        login_path = "/v3/auth/user/login" if version == "v3" else "/v1/auth/login"
        response = await client.post(
            login_path,
            data={"username": username, "password": password},
        )
        if response.status_code in (401, 403):
            raise errors.UpstreamAuthError("nacos authentication failed")
        if response.status_code >= 400:
            raise errors.UpstreamUnavailable(f"nacos login returned HTTP {response.status_code}")
        payload = _json_object(response, "login")
        token = str(payload.get("accessToken") or "").strip()
        if not token:
            raise errors.UpstreamAuthError("nacos login returned no accessToken")
        ttl = max(1, int(payload.get("tokenTtl") or payload.get("tokenTTL") or _TOKEN_TTL_FALLBACK))
        # Refresh shortly before server expiry without ever caching past it.
        # For the normal 18000s TTL this leaves 30s; very short TTLs still
        # get an early refresh.
        margin = min(30, max(1, ttl // 10))
        self._access_token = token
        self._token_expiry = time.monotonic() + max(1, ttl - margin)
        return token

    async def _token(self, client: httpx.AsyncClient) -> str:
        if self._access_token and time.monotonic() < self._token_expiry:
            return self._access_token
        return await self._login(client)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        require(nacos_guard.check_nacos("GET", path))
        client = self._client()
        try:
            await self._ensure_version(client)
            token = await self._token(client)
            query = dict(params or {})
            if token:
                query["accessToken"] = token
            response, _ = await base.stream_http(
                client,
                "GET",
                path,
                component="nacos",
                limit=base.max_bytes(self.target),
                params=query,
            )
            return response
        except errors.DrPandaError:
            raise
        except Exception as exc:
            raise errors.UpstreamUnavailable(f"nacos request failed: {type(exc).__name__}: {exc}") from exc
        finally:
            await client.aclose()

    async def _v3_config(self, namespace: str, group: str, data_id: str) -> str:
        response = await self._get(
            "/v3/client/cs/config",
            {
                "dataId": data_id,
                "groupName": group,
                "namespaceId": _tenant(namespace),
            },
        )
        return _v3_config_content(_v3_data(response, "config"))

    async def ping(self) -> None:
        namespace = ensure_namespace(self.target, "")
        group = ensure_group(self.target, "")
        client = self._client()
        try:
            version = await self._ensure_version(client)
        finally:
            await client.aclose()
        if version == "v1":
            # A config list request validates both auth and namespace/group access.
            await self._get(
                "/v1/cs/configs",
                {
                    "search": "accurate",
                    "dataId": "",
                    "group": group,
                    "tenant": _tenant(namespace),
                    "pageNo": 1,
                    "pageSize": 1,
                },
            )
        else:
            # v3 client API has no list endpoint; validate login and, when
            # configured, one real config rather than calling an admin API.
            client = self._client()
            try:
                await self._token(client)
            finally:
                await client.aclose()
            allowed_ids = _items(self.target, "allowed_data_ids")
            if allowed_ids:
                await self._v3_config(namespace, group, allowed_ids[0])

    async def configs(
        self,
        *,
        namespace: str,
        group: str,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        chosen_namespace = ensure_namespace(self.target, namespace)
        chosen_group = ensure_group(self.target, group)
        allowed_ids = _items(self.target, "allowed_data_ids")
        if not allowed_ids:
            raise errors.ScopeDenied(f"target {self.target.name} has no authorized data IDs")

        client = self._client()
        try:
            version = await self._ensure_version(client)
        finally:
            await client.aclose()

        if version == "v1":
            response = await self._get(
                "/v1/cs/configs",
                {
                    "search": "accurate",
                    "dataId": "",
                    "group": chosen_group,
                    "tenant": _tenant(chosen_namespace),
                    "pageNo": page,
                    "pageSize": page_size,
                },
            )
            payload = _json_object(response, "config list")
            items = payload.get("pageItems")
            if not isinstance(items, list):
                items = []
            rows = [
                {
                    "data_id": item.get("dataId"),
                    "group": item.get("group"),
                    "namespace": chosen_namespace,
                    "type": item.get("type"),
                    "app_name": item.get("appName"),
                    "md5": item.get("md5"),
                }
                for item in items
                if isinstance(item, dict) and (item.get("dataId") in allowed_ids)
            ]
            total = int(payload.get("totalCount") or 0)
            return rows, total

        # v3: the scope is the inventory. Query each allowed dataId through the
        # read-only client API; no admin list endpoint is required.
        start = (page - 1) * page_size
        candidates = allowed_ids[start : start + page_size]
        rows: list[dict[str, Any]] = []
        for data_id in candidates:
            try:
                await self._v3_config(chosen_namespace, chosen_group, data_id)
            except errors.UpstreamNotFound:
                continue
            rows.append(
                {
                    "data_id": data_id,
                    "group": chosen_group,
                    "namespace": chosen_namespace,
                    "type": None,
                    "app_name": None,
                    "md5": None,
                }
            )
        return rows, len(allowed_ids)

    async def config(self, *, namespace: str, group: str, data_id: str) -> str:
        chosen_namespace = ensure_namespace(self.target, namespace)
        chosen_group = ensure_group(self.target, group)
        chosen_id = ensure_data_id(self.target, data_id)

        client = self._client()
        try:
            version = await self._ensure_version(client)
        finally:
            await client.aclose()
        if version == "v3":
            return await self._v3_config(chosen_namespace, chosen_group, chosen_id)

        response = await self._get(
            "/v1/cs/configs",
            {
                "dataId": chosen_id,
                "group": chosen_group,
                "tenant": _tenant(chosen_namespace),
            },
        )
        return response.text

    async def services(
        self,
        *,
        namespace: str,
        group: str,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        chosen_namespace = ensure_namespace(self.target, namespace)
        chosen_group = ensure_group(self.target, group)
        allowed_services = _items(self.target, "allowed_services")
        if not allowed_services:
            raise errors.ScopeDenied(f"target {self.target.name} has no authorized services")

        client = self._client()
        try:
            version = await self._ensure_version(client)
        finally:
            await client.aclose()
        if version == "v3":
            # v3 client OpenAPI exposes instance lookup but not service list.
            # Return the explicit scope rather than requiring an admin token.
            start = (page - 1) * page_size
            selected = allowed_services[start : start + page_size]
            rows = [
                {"service": name, "group": chosen_group, "namespace": chosen_namespace}
                for name in selected
            ]
            return rows, len(allowed_services)

        response = await self._get(
            "/v1/ns/service/list",
            {
                "pageNo": page,
                "pageSize": page_size,
                "namespaceId": _tenant(chosen_namespace),
                "groupName": chosen_group,
            },
        )
        payload = _json_object(response, "service list")
        names = payload.get("services") or payload.get("doms") or []
        if not isinstance(names, list):
            names = []
        rows = [
            {"service": str(name), "group": chosen_group, "namespace": chosen_namespace}
            for name in names
            if str(name) in allowed_services
        ]
        total = int(payload.get("count") or 0)
        return rows, total

    async def instances(self, *, namespace: str, group: str, service: str) -> list[dict[str, Any]]:
        chosen_namespace = ensure_namespace(self.target, namespace)
        chosen_group = ensure_group(self.target, group)
        chosen_service = ensure_service(self.target, service)

        client = self._client()
        try:
            version = await self._ensure_version(client)
        finally:
            await client.aclose()
        if version == "v3":
            response = await self._get(
                "/v3/client/ns/instance/list",
                {
                    "serviceName": chosen_service,
                    "groupName": chosen_group,
                    "namespaceId": _tenant(chosen_namespace),
                },
            )
            hosts = _v3_data(response, "instance list")
        else:
            response = await self._get(
                "/v1/ns/instance/list",
                {
                    "serviceName": chosen_service,
                    "groupName": chosen_group,
                    "namespaceId": _tenant(chosen_namespace),
                },
            )
            payload = _json_object(response, "instance list")
            hosts = payload.get("hosts")
        if not isinstance(hosts, list):
            hosts = []
        return [
            {
                "service": chosen_service,
                "group": chosen_group,
                "namespace": chosen_namespace,
                "ip": host.get("ip"),
                "port": host.get("port"),
                "cluster": host.get("clusterName"),
                "healthy": host.get("healthy"),
                "enabled": host.get("enabled"),
                "weight": host.get("weight"),
                "ephemeral": host.get("ephemeral"),
                "metadata": base.to_jsonable(host.get("metadata") or {}),
            }
            for host in hosts
            if isinstance(host, dict)
        ]


class NacosConnector:
    name = "nacos"

    def probe_guard(self) -> Decision:
        return nacos_guard.check_nacos("GET", "/v1/console/health/liveness")

    def create_client(self, target: Target) -> _NacosClient:
        return _NacosClient(target)

    async def probe(self, client: _NacosClient, target: Target) -> None:
        await client.ping()

    async def close_client(self, client: _NacosClient) -> None:
        return None


connector = NacosConnector()
