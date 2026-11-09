from __future__ import annotations

import pytest

from dr_panda_mcp import errors
from dr_panda_mcp.connectors.jenkins import ensure_job, ensure_node
from dr_panda_mcp.guards.jenkins import check_jenkins
from tests.fakes import make_target


def _target(**options: object):
    return make_target(
        type_="jenkins",
        options={
            "base_url": "http://jenkins.test:8080",
            "allowed_jobs": ["team-a/service-build"],
            "allowed_nodes": ["Built-In Node"],
            **options,
        },
    )


def test_jenkins_guard_allows_read_only_paths() -> None:
    assert check_jenkins("GET", "/api/json").allowed
    assert check_jenkins("GET", "/job/team-a/job/service-build/api/json").allowed
    assert check_jenkins("GET", "/job/demo/1/consoleText").allowed
    assert check_jenkins("GET", "/computer/api/json").allowed
    assert not check_jenkins("POST", "/api/json").allowed
    assert not check_jenkins("GET", "/script").allowed
    assert not check_jenkins("GET", "/credentials/store/system/domain/_/api/json").allowed
    assert not check_jenkins("GET", "/job/../api/json").allowed


def test_jenkins_scope() -> None:
    target = _target()
    assert ensure_job(target, "team-a/service-build") == "team-a/service-build"
    assert ensure_node(target, "Built-In Node") == "Built-In Node"
    with pytest.raises(errors.ScopeDenied):
        ensure_job(target, "other-job")
    with pytest.raises(errors.ScopeDenied):
        ensure_node(target, "other-node")


def test_jenkins_scope_denies_empty_node_list() -> None:
    target = _target(allowed_nodes=[])
    with pytest.raises(errors.ScopeDenied):
        ensure_node(target, "Built-In Node")
