from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.server import create_server
from dr_panda_mcp.store.protocol import SecretPatch, TargetDraft
from dr_panda_mcp.tools import jenkins as jenkins_module

JENKINS_TOOLS = {
    "jenkins_jobs",
    "jenkins_job",
    "jenkins_builds",
    "jenkins_build",
    "jenkins_console",
    "jenkins_nodes",
    "jenkins_queue",
}


class FakeJenkinsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def jobs(self):
        self.calls.append(("jobs", None))
        return [{"job": "demo-job", "color": "blue"}]

    async def job(self, job):
        self.calls.append(("job", job))
        return {"job": job, "color": "blue"}

    async def builds(self, job, limit=None):
        self.calls.append(("builds", (job, limit)))
        return [{"job": job, "number": 1, "result": "SUCCESS"}]

    async def build(self, job, number):
        self.calls.append(("build", (job, number)))
        return {"job": job, "number": number, "result": "SUCCESS"}

    async def console(self, job, number):
        self.calls.append(("console", (job, number)))
        return "log line", False

    async def nodes(self):
        self.calls.append(("nodes", None))
        return [{"node": "Built-In Node", "offline": False}]

    async def queue(self):
        self.calls.append(("queue", None))
        return [{"job": "demo-job", "why": "waiting"}]


class FakeJenkinsConnector:
    name = "jenkins"

    def __init__(self) -> None:
        self.client = FakeJenkinsClient()

    def create_client(self, target):
        return self.client

    async def close_client(self, client):
        return None


async def _setup(runtime: Runtime) -> None:
    await runtime.store.create(
        TargetDraft(
            name="jenkins-a",
            type="jenkins",
            enabled=True,
            options={
                "base_url": "http://jenkins.test:8080",
                "username": "admin",
                "allowed_jobs": ["demo-job"],
                "allowed_nodes": ["Built-In Node"],
                "allow_console": True,
                "max_builds": 20,
            },
            secret_patch=SecretPatch(set={"api_token": "token"}),
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


async def test_jenkins_tools(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(runtime)
    fake = FakeJenkinsConnector()
    monkeypatch.setattr(jenkins_module, "get_connector", lambda _: fake)

    jobs = await _call(runtime, "jenkins_jobs", {"target": "jenkins-a"})
    job = await _call(runtime, "jenkins_job", {"target": "jenkins-a", "job": "demo-job"})
    builds = await _call(
        runtime, "jenkins_builds", {"target": "jenkins-a", "job": "demo-job"}
    )
    build = await _call(
        runtime,
        "jenkins_build",
        {"target": "jenkins-a", "job": "demo-job", "build_number": 1},
    )
    console = await _call(
        runtime,
        "jenkins_console",
        {"target": "jenkins-a", "job": "demo-job", "build_number": 1},
    )
    nodes = await _call(runtime, "jenkins_nodes", {"target": "jenkins-a"})
    queue = await _call(runtime, "jenkins_queue", {"target": "jenkins-a"})

    assert jobs["rows"][0]["job"] == "demo-job"
    assert job["rows"][0]["color"] == "blue"
    assert builds["rows"][0]["result"] == "SUCCESS"
    assert build["rows"][0]["number"] == 1
    assert console["rows"][0]["content"] == "log line"
    assert nodes["rows"][0]["node"] == "Built-In Node"
    assert queue["rows"][0]["why"] == "waiting"
    assert fake.client.calls == [
        ("jobs", None),
        ("job", "demo-job"),
        ("builds", ("demo-job", None)),
        ("build", ("demo-job", 1)),
        ("console", ("demo-job", 1)),
        ("nodes", None),
        ("queue", None),
    ]
