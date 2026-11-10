from __future__ import annotations

import pytest

from dr_panda_mcp import capabilities, errors
from tests.fakes import make_target


def test_legacy_target_enables_all_default_mysql_tools() -> None:
    target = make_target(type_="mysql", name="db", options={"default_db": "app"})
    assert capabilities.is_tool_enabled(target, "mysql_query")
    assert capabilities.is_tool_enabled(target, "mysql_tables")
    assert not capabilities.is_tool_enabled(target, "mysql_processlist")
    enabled, total = capabilities.counts(target)
    assert enabled == 4
    assert total == 5


def test_enabled_tools_can_narrow() -> None:
    target = make_target(
        type_="mysql",
        name="db",
        options={
            "default_db": "app",
            "enabled_tools": ["mysql_tables", "mysql_describe"],
        },
    )
    assert capabilities.is_tool_enabled(target, "mysql_tables")
    assert not capabilities.is_tool_enabled(target, "mysql_query")
    with pytest.raises(errors.ScopeDenied) as caught:
        capabilities.ensure_tool_enabled(target, "mysql_query")
    assert "allowed: mysql_describe, mysql_tables" in str(caught.value)


def test_risk_opt_in_processlist() -> None:
    target = make_target(
        type_="mysql",
        name="db",
        options={"default_db": "app", "allow_processlist": True},
    )
    assert capabilities.is_tool_enabled(target, "mysql_processlist")


def test_parse_enabled_tools_from_form() -> None:
    form = {"enabled_tool": ["mysql_query", "mysql_tables", "bogus"]}
    assert capabilities.parse_enabled_tools(form, "mysql") == [
        "mysql_tables",
        "mysql_query",
    ]


def test_form_rows_default_check_non_risk() -> None:
    rows = capabilities.form_rows("redis", options={})
    by_tool = {row["tool"]: row for row in rows}
    assert by_tool["redis_get"]["checked"] is True
    assert by_tool["redis_scan"]["name"] == "enabled_tool"
    assert by_tool["redis_get"]["risk"] is False


def test_jenkins_console_maps_to_allow_console() -> None:
    rows = capabilities.form_rows(
        "jenkins",
        options={"allow_console": True, "allowed_jobs": ["demo"]},
    )
    console = next(row for row in rows if row["tool"] == "jenkins_console")
    assert console["name"] == "allow_console"
    assert console["checked"] is True
    assert console["risk"] is True


def test_capabilities_payload_english_summary() -> None:
    target = make_target(type_="mysql", name="db", options={"default_db": "app"})
    payload = capabilities.capabilities_payload(target)
    query = next(item for item in payload if item["tool"] == "mysql_query")
    assert query["enabled"] is True
    assert "SQL" in query["summary"]
    assert query["protocol"] == ["SELECT", "SHOW", "DESCRIBE", "EXPLAIN"]
