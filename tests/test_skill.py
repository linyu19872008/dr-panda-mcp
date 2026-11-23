from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    path = ROOT / "scripts" / "check_skill.py"
    spec = importlib.util.spec_from_file_location("check_skill", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_validates() -> None:
    checker = _checker()
    assert checker.validate() == []


def test_skill_catalog_has_all_tools() -> None:
    checker = _checker()
    tools = checker.known_tools()
    assert len(tools) == 39
    assert "systems_status" in tools
    for prefix in (
        "mysql",
        "mongo",
        "es",
        "redis",
        "gitlab",
        "cls",
        "rabbit",
        "kafka",
        "nacos",
        "jenkins",
    ):
        assert any(name.startswith(f"{prefix}_") for name in tools)


def test_skill_frontmatter_is_portable() -> None:
    checker = _checker()
    text = checker.SKILL_FILE.read_text(encoding="utf-8")
    fields = checker.frontmatter(text)
    assert fields["name"] == "dr-panda-mcp"
    assert "DrPanda" in fields["description"]
    assert checker.SKILL_DIR.is_dir()
    assert (ROOT / "skills" / "dr-panda-mcp" / "SKILL.md").is_file()


def test_cursor_rule_and_readme_point_to_skill() -> None:
    rule = (ROOT / ".cursor" / "rules" / "dr-panda-mcp.mdc").read_text(encoding="utf-8")
    assert "SKILL.md" in rule
    assert "systems_status" in rule
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills/dr-panda-mcp/SKILL.md" in readme
