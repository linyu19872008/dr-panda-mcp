from __future__ import annotations

from dr_panda_mcp.connectors import base
from tests.fakes import make_target


def test_list_http_budget_raises_small_target_cap() -> None:
    target = make_target(
        type_="nacos",
        name="test-nacos",
        options={
            "base_url": "http://nacos.example",
            "allowed_namespaces": ["ns"],
            "allowed_groups": ["DEFAULT_GROUP"],
            "data_scope": "all",
            "service_scope": "all",
            "max_bytes": 102_400,
        },
    )
    assert base.max_bytes(target) == 102_400
    assert base.list_http_max_bytes(target) == 1_048_576


def test_type_default_max_bytes_for_nacos() -> None:
    target = make_target(
        type_="nacos",
        name="test-nacos",
        options={
            "base_url": "http://nacos.example",
            "allowed_namespaces": ["ns"],
            "allowed_groups": ["DEFAULT_GROUP"],
            "data_scope": "all",
            "service_scope": "all",
        },
    )
    assert base.max_bytes(target) == 1_048_576
