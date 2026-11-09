from __future__ import annotations

from typing import Any

import httpx
import pytest

from dr_panda_mcp import errors
from dr_panda_mcp.connectors.nacos import _NacosClient
from tests.fakes import make_target


def _target(*, data_ids: list[str] | None = None, services: list[str] | None = None,
            username: str = "", api_version: str = "auto",
            data_scope: str = "selected", service_scope: str = "selected",
            namespaces: list[str] | None = None, groups: list[str] | None = None) -> Any:
    options: dict[str, Any] = {
        "base_url": "http://nacos.test:8848",
        "api_version": api_version,
        "allowed_namespaces": namespaces if namespaces is not None else ["public"],
        "allowed_groups": groups if groups is not None else ["DEFAULT_GROUP"],
        "data_scope": data_scope,
        "allowed_data_ids": data_ids if data_ids is not None else ["demo.yaml"],
        "service_scope": service_scope,
        "allowed_services": services if services is not None else ["demo"],
        "timeout_s": "10",
    }
    if username:
        options["username"] = username
    secret = {"password": "secret"} if username else {}
    return make_target(type_="nacos", options=options, secret=secret)


def _client(target: Any, handler) -> _NacosClient:
    client = _NacosClient(target)
    transport = httpx.MockTransport(handler)

    def fake_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://nacos.test:8848/nacos", transport=transport
        )

    client._client = fake_client  # type: ignore[method-assign]
    return client


async def test_nacos_ping_and_config_list() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/v1/cs/configs"):
            return httpx.Response(
                200,
                json={
                    "totalCount": 2,
                    "pageItems": [
                        {"dataId": "demo.yaml", "group": "DEFAULT_GROUP", "type": "yaml"},
                        {"dataId": "other.yaml", "group": "DEFAULT_GROUP", "type": "yaml"},
                    ],
                },
            )
        return httpx.Response(404)

    client = _client(_target(), handler)
    await client.ping()
    rows, total = await client.configs(namespace="", group="", page=1, page_size=10)

    assert requests[0].url.path.endswith("/v1/console/health/liveness")
    config_request = next(
        request for request in requests if request.url.path.endswith("/v1/cs/configs")
    )
    assert config_request.url.params["group"] == "DEFAULT_GROUP"
    assert config_request.url.params["tenant"] == ""
    assert total == 2
    assert rows == [
        {
            "data_id": "demo.yaml",
            "group": "DEFAULT_GROUP",
            "namespace": "public",
            "type": "yaml",
            "app_name": None,
            "md5": None,
        }
    ]


async def test_nacos_config_content_and_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hello: world")

    client = _client(_target(), handler)
    assert await client.config(namespace="", group="", data_id="demo.yaml") == "hello: world"

    scoped = _client(_target(data_ids=[]), handler)
    with pytest.raises(errors.ScopeDenied):
        await scoped.configs(namespace="", group="", page=1, page_size=10)
    with pytest.raises(errors.ScopeDenied):
        await scoped.config(namespace="", group="", data_id="demo.yaml")


async def test_nacos_services_and_instances() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/ns/service/list"):
            return httpx.Response(200, json={"count": 2, "doms": ["demo", "other"]})
        if request.url.path.endswith("/v1/ns/instance/list"):
            return httpx.Response(
                200,
                json={
                    "hosts": [
                        {
                            "ip": "10.0.0.1",
                            "port": 8080,
                            "clusterName": "DEFAULT",
                            "healthy": True,
                            "enabled": True,
                            "weight": 1.0,
                            "ephemeral": False,
                            "metadata": {"zone": "a"},
                        }
                    ]
                },
            )
        return httpx.Response(404)

    client = _client(_target(), handler)
    services, total = await client.services(namespace="", group="", page=1, page_size=10)
    instances = await client.instances(namespace="", group="", service="demo")

    assert total == 2
    assert services == [{"service": "demo", "group": "DEFAULT_GROUP", "namespace": "public"}]
    assert instances[0]["ip"] == "10.0.0.1"
    assert instances[0]["healthy"] is True


async def test_nacos_login_token_is_sent() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/v1/auth/login"):
            return httpx.Response(200, json={"accessToken": "tok-1", "tokenTtl": 3600})
        return httpx.Response(
            200,
            json={"totalCount": 1, "pageItems": [{"dataId": "demo.yaml", "group": "DEFAULT_GROUP"}]},
        )

    client = _client(_target(username="nacos"), handler)
    await client.ping()
    await client.configs(namespace="", group="", page=1, page_size=10)

    login_request = next(
        request for request in requests if request.url.path.endswith("/v1/auth/login")
    )
    assert login_request.url.path.endswith("/v1/auth/login")
    assert any(request.url.params.get("accessToken") == "tok-1" for request in requests)


async def test_nacos_short_token_ttl_does_not_exceed_server_expiry() -> None:
    import time

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/auth/login"):
            return httpx.Response(200, json={"accessToken": "short", "tokenTtl": 5})
        return httpx.Response(
            200, json={"totalCount": 0, "pageItems": []}
        )

    client = _client(_target(username="nacos"), handler)
    await client.ping()

    remaining = client._token_expiry - time.monotonic()
    assert 0 < remaining <= 5


async def test_nacos_v3_detects_and_uses_client_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/v1/console/health/liveness"):
            return httpx.Response(410, json={"message": "use v3"})
        if path.endswith("/v3/client/cs/config"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"content": "hello-v3", "contentType": "yaml"}},
            )
        if path.endswith("/v3/client/ns/instance/list"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "ip": "10.0.0.3",
                            "port": 8081,
                            "clusterName": "DEFAULT",
                            "healthy": True,
                            "enabled": True,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    client = _client(_target(), handler)
    await client.ping()
    rows, total = await client.configs(namespace="", group="", page=1, page_size=10)
    content = await client.config(namespace="", group="", data_id="demo.yaml")
    services, service_total = await client.services(namespace="", group="", page=1, page_size=10)
    instances = await client.instances(namespace="", group="", service="demo")

    assert client._version == "v3"
    assert rows[0]["data_id"] == "demo.yaml"
    assert total == 1
    assert content == "hello-v3"
    assert services[0]["service"] == "demo"
    assert service_total == 1
    assert instances[0]["ip"] == "10.0.0.3"
    assert all(
        not request.url.path.startswith("/v3/admin")
        for request in requests
    )


async def test_nacos_probe_selects_a_scope_when_multiple_are_configured() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/v1/console/health/liveness"):
            return httpx.Response(200, json={"status": "UP"})
        if request.url.path.endswith("/v1/cs/configs"):
            return httpx.Response(200, json={"totalCount": 0, "pageItems": []})
        return httpx.Response(404)

    target = _target(
        namespaces=["cloud_21_test", "public_dubbo"],
        groups=["DEFAULT_GROUP", "mapping", "dubbo"],
    )
    await _client(target, handler).ping()

    config_request = next(
        request for request in requests if request.url.path.endswith("/v1/cs/configs")
    )
    assert config_request.url.params["tenant"] == "cloud_21_test"
    assert config_request.url.params["group"] == "DEFAULT_GROUP"


async def test_nacos_all_scope_v1_lists_unfiltered_and_reads_any_data_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/v1/console/health/liveness"):
            return httpx.Response(200, json={"status": "UP"})
        if request.url.path.endswith("/v1/cs/configs"):
            if request.url.params.get("dataId"):
                return httpx.Response(200, text="unrestricted")
            return httpx.Response(
                200,
                json={
                    "totalCount": 2,
                    "pageItems": [
                        {"dataId": "a.yaml", "group": "DEFAULT_GROUP", "type": "yaml"},
                        {"dataId": "b.yaml", "group": "DEFAULT_GROUP", "type": "yaml"},
                    ],
                },
            )
        return httpx.Response(404)

    target = _target(
        data_ids=[], services=[], data_scope="all", service_scope="all"
    )
    client = _client(target, handler)
    await client.ping()
    rows, total = await client.configs(namespace="", group="", page=1, page_size=10)
    content = await client.config(namespace="", group="", data_id="anything.yaml")

    assert total == 2
    assert [row["data_id"] for row in rows] == ["a.yaml", "b.yaml"]
    assert content == "unrestricted"


async def test_nacos_all_scope_v3_configs_reports_listing_limitation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/console/health/liveness"):
            return httpx.Response(410, json={"message": "use v3"})
        if request.url.path.endswith("/v3/client/cs/config"):
            return httpx.Response(200, json={"code": 0, "data": {"content": "x"}})
        return httpx.Response(404)

    client = _client(
        _target(data_ids=[], services=[], data_scope="all", service_scope="all"),
        handler,
    )
    with pytest.raises(errors.InvalidArgument):
        await client.configs(namespace="", group="", page=1, page_size=10)
