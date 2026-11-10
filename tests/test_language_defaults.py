"""Default-language policy: English catalog completeness and docs layout."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from dr_panda_mcp import capabilities
from dr_panda_mcp.settings import SETTING_GROUPS, SETTING_SPECS
from dr_panda_mcp.web.forms import COMMON_FIELDS, TYPE_SPECS
from dr_panda_mcp.web.i18n import t, use_locale
from dr_panda_mcp.web.labels import ERROR_CODE_DISPLAY, ERROR_LABELS

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u4e00-\u9fff]")


def _template_keys() -> set[str]:
    keys: set[str] = set()
    for path in (ROOT / "src/dr_panda_mcp/web/templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        keys.update(match.group(2) for match in re.finditer(r"\b(?:t|plural)\(\s*(['\"])(.*?)\1", text))
    return keys


def _python_keys() -> set[str]:
    keys: set[str] = set()
    for path in (ROOT / "src/dr_panda_mcp/web").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"t", "plural"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    return keys


def _metadata_keys() -> set[str]:
    keys: set[str] = set()
    for spec in SETTING_SPECS:
        keys.update({spec.group, spec.label, spec.unit, spec.effect, spec.help, spec.subgroup})
    for group in SETTING_GROUPS:
        for value in group.values():
            if isinstance(value, str):
                keys.add(value)
            elif isinstance(value, list):
                for subgroup in value:
                    if isinstance(subgroup, dict):
                        keys.update(v for v in subgroup.values() if isinstance(v, str))
    for spec in TYPE_SPECS.values():
        keys.update({spec.label, spec.note})
        for field in (*spec.options, *spec.secrets):
            keys.update({field.label, field.help})
    keys.update(label for _key, label, _default, _range in COMMON_FIELDS)
    return keys


def test_english_catalog_covers_source_keys() -> None:
    catalog = json.loads(
        (ROOT / "src/dr_panda_mcp/web/locales/en.json").read_text(encoding="utf-8")
    )
    keys = _template_keys() | _python_keys() | _metadata_keys()
    keys.update(ERROR_LABELS.values())
    keys.update(capabilities.ui_summary_keys())
    keys.add(ERROR_CODE_DISPLAY)
    missing = sorted(key for key in keys if key and CJK.search(key) and key not in catalog)
    assert missing == [], f"missing English catalog keys: {missing[:10]}"


def test_english_catalog_values_have_no_chinese() -> None:
    catalog = json.loads(
        (ROOT / "src/dr_panda_mcp/web/locales/en.json").read_text(encoding="utf-8")
    )
    bad = [key for key, value in catalog.items() if CJK.search(str(value))]
    assert bad == [], f"English values contain Chinese: {bad[:10]}"


def test_default_docs_are_english_and_chinese_docs_are_isolated() -> None:
    english_docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    for path in english_docs:
        text = path.read_text(encoding="utf-8")
        # The language switcher and localized screenshots may contain the label itself.
        text = text.replace("简体中文", "").replace("默认", "")
        assert not CJK.search(text), f"Chinese text in default English file: {path}"

    assert "](docs/zh-CN/" not in (ROOT / "README.md").read_text(encoding="utf-8")
    chinese_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    assert "docs/zh-CN/planning.md" in chinese_readme
    assert "docs/planning.md" not in chinese_readme
    assert (ROOT / "docs" / "zh-CN" / "README.md").is_file()


def test_missing_english_translation_does_not_fallback_to_chinese() -> None:
    with use_locale("en"), pytest.raises(KeyError):
        t("这条文案没有英文翻译")
