from __future__ import annotations

from dr_panda_mcp.web.forms import TYPE_SPECS, initial_values


def test_nacos_and_jenkins_default_max_bytes_are_1mb() -> None:
    nacos = initial_values(TYPE_SPECS["nacos"], None, defaults={"max_bytes": 102_400})
    jenkins = initial_values(TYPE_SPECS["jenkins"], None, defaults={"max_bytes": 102_400})
    mysql = initial_values(TYPE_SPECS["mysql"], None, defaults={"max_bytes": 102_400})
    assert nacos["max_bytes"] == "1048576"
    assert jenkins["max_bytes"] == "1048576"
    assert mysql["max_bytes"] == "102400"
