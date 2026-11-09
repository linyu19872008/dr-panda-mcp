"""Contract: every tools connector.* call must exist on the real connector."""

from __future__ import annotations

import ast
from pathlib import Path

from dr_panda_mcp.connectors import get_connector

ROOT = Path(__file__).resolve().parents[1] / "src" / "dr_panda_mcp" / "tools"

# tools file -> connector types that file may call through get_connector(...)
FILE_CONNECTORS: dict[str, tuple[str, ...]] = {
    "logs.py": ("cls", "gitlab"),
    "messages.py": ("rabbitmq", "kafka"),
    "data.py": ("mysql", "mongo", "elasticsearch", "redis"),
    "nacos.py": ("nacos",),
    "jenkins.py": ("jenkins",),
}


def _connector_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "connector"
        ):
            names.add(func.attr)
    return names


def test_all_tool_connector_calls_have_facades() -> None:
    missing: list[str] = []
    for path in sorted(ROOT.glob("*.py")):
        types = FILE_CONNECTORS.get(path.name)
        if not types:
            continue
        connectors = [get_connector(name) for name in types]
        for method in sorted(_connector_calls(path)):
            if any(hasattr(connector, method) for connector in connectors):
                continue
            missing.append(
                f"tools/{path.name} calls connector.{method} but none of "
                f"{types} expose it"
            )
    assert not missing, "connector facade gaps:\n" + "\n".join(missing)


def test_nacos_and_jenkins_facades_cover_client_methods() -> None:
    """Regression for the 1.9.0 Nacos AttributeError class of bugs."""
    for type_name, methods in {
        "nacos": ("configs", "config", "services", "instances"),
        "jenkins": ("jobs", "job", "builds", "build", "console", "nodes", "queue"),
    }.items():
        connector = get_connector(type_name)
        for method in methods:
            assert hasattr(connector, method), f"{type_name} missing {method}"
