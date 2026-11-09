from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.server import create_server
from dr_panda_mcp.store.protocol import SecretPatch, TargetDraft
from dr_panda_mcp.tools import nacos as nacos_module


class FakeNacos:
    name = "nacos"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_client(self, target):
        return object()

    async def close_client(self, client):
        return None

    async def configs(self, client, target, **kwargs):
        self.calls.append("configs")
        return [
            {"data_id": "demo.yaml", "group": "DEFAULT_GROUP", "namespace": "public"}
        ], 1

    async def config(self, client, target, **kwargs):
        self.calls.append("config")
        return "hello: world"

    async def services(self, client, target, **kwargs):
        self.calls.append("services")
        return [{"service": "demo", "group": "DEFAULT_GROUP", "namespace": "public"}], 1

    async def instances(self, client, target, **kwargs):
        self.calls.append("instances")
        return [{"service": "demo", "ip": "10.0.0.1", "port": 8080, "healthy": True}]


async def _setup(runtime: Runtime) -> None:
    await runtime.store.create(
        TargetDraft(
            name="nacos-a",
            type="nacos",
            enabled=True,
            options={
                "base_url": "http://nacos.test:8848",
                "allowed_namespaces": ["public"],
                "allowed_groups": ["DEFAULT_GROUP"],
                "allowed_data_ids": ["demo.yaml"],
                "allowed_services": ["demo"],
            },
            secret_patch=SecretPatch(set={}),
            environment_key="default",
        ),
        "anonymous",
    )


async def _call(runtime: Runtime, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    server = create_server(runtime.config, runtime)
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    return result.structured_content


async def test_nacos_tools(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    await _setup(runtime)
    fake = FakeNacos()
    monkeypatch.setattr(nacos_module, "get_connector", lambda _: fake)

    configs = await _call(runtime, "nacos_configs", {"target": "nacos-a"})
    config = await _call(
        runtime, "nacos_config", {"target": "nacos-a", "data_id": "demo.yaml"}
    )
    services = await _call(runtime, "nacos_services", {"target": "nacos-a"})
    instances = await _call(
        runtime, "nacos_instances", {"target": "nacos-a", "service": "demo"}
    )

    assert configs["rows"][0]["data_id"] == "demo.yaml"
    assert config["rows"][0]["content"] == "hello: world"
    assert services["rows"][0]["service"] == "demo"
    assert instances["rows"][0]["ip"] == "10.0.0.1"
    assert fake.calls == ["configs", "config", "services", "instances"]
