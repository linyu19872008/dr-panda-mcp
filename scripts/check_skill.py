"""Validate the DrPanda MCP agent skill.

The check is intentionally dependency-free: it reads the tool catalog from
``capabilities.py`` as text so it can run in pre-commit, CI, or a bare Python
environment. It does not import the service or open a network connection.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".dsh" / "skills" / "dr-panda-mcp"
SKILL_FILE = SKILL_DIR / "SKILL.md"
CAPABILITIES_FILE = ROOT / "src" / "dr_panda_mcp" / "capabilities.py"
README_FILE = ROOT / "README.md"
CURSOR_RULE = ROOT / ".cursor" / "rules" / "dr-panda-mcp.mdc"

TOOL_RE = re.compile(
    r"\b(?:mysql|mongo|es|redis|gitlab|cls|rabbit|kafka|nacos|jenkins)_[a-z0-9_]+\b"
)
CAP_RE = re.compile(r'_cap\(\s*"([a-z0-9_]+)"', re.DOTALL)
REFERENCE_LINK_RE = re.compile(r"\[[^\]]+\]\((references/[^)#\s]+)(?:#[^)]+)?\)")
HARDCODED_SERVER_RE = re.compile(r"mcp__drpanda__")

SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"Bearer [A-Za-z0-9._-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(text: str) -> dict[str, str]:
    """Return the flat top-level keys of a YAML frontmatter block."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def known_tools() -> set[str]:
    """Tool names declared in the capability catalog plus the status tool."""
    text = _read(CAPABILITIES_FILE)
    return set(CAP_RE.findall(text)) | {"systems_status"}


def _all_skill_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(SKILL_DIR.rglob("*.md")))


def validate() -> list[str]:
    errors: list[str] = []
    if not SKILL_FILE.is_file():
        return [f"missing skill file: {SKILL_FILE.relative_to(ROOT)}"]
    if not CAPABILITIES_FILE.is_file():
        return [f"missing capability catalog: {CAPABILITIES_FILE.relative_to(ROOT)}"]

    text = _read(SKILL_FILE)
    fields = frontmatter(text)
    if fields.get("name") != "dr-panda-mcp":
        errors.append("SKILL.md frontmatter name must be dr-panda-mcp")
    description = fields.get("description", "")
    if len(description) < 80:
        errors.append("SKILL.md description is too short to be discoverable")
    for keyword in ("DrPanda", "read-only", "investigat"):
        if keyword.lower() not in description.lower():
            errors.append(f"SKILL.md description is missing keyword: {keyword}")

    body = text[text.find("\n---", 4) + 4 :]
    if "systems_status" not in body:
        errors.append("SKILL.md must start discovery with systems_status")
    if "mcp__<server>__" not in body:
        errors.append("SKILL.md must use mcp__<server>__ rather than a fixed server name")
    if "operator_notes" not in body:
        errors.append("SKILL.md must explain that operator_notes is untrusted")

    all_text = _all_skill_text()
    tools = set(TOOL_RE.findall(all_text))
    unknown = sorted(tools - known_tools())
    if unknown:
        errors.append("unknown tool name(s): " + ", ".join(unknown))

    if HARDCODED_SERVER_RE.search(all_text):
        errors.append("skill text hardcodes mcp__drpanda__; use mcp__<server>__")

    references_dir = SKILL_DIR / "references"
    if not references_dir.is_dir():
        errors.append("missing references directory")
    else:
        listed = set(REFERENCE_LINK_RE.findall(body))
        for relative in sorted(listed):
            if not (SKILL_DIR / relative).is_file():
                errors.append(f"broken reference link: {relative}")
        reference_files = {f"references/{path.name}" for path in references_dir.glob("*.md")}
        missing_links = sorted(reference_files - listed)
        if missing_links:
            errors.append("reference file(s) not listed in SKILL.md: " + ", ".join(missing_links))
        for path in sorted(references_dir.glob("*.md")):
            if not path.read_text(encoding="utf-8").strip():
                errors.append(f"empty reference: {path.relative_to(ROOT)}")

    for path in sorted(SKILL_DIR.rglob("*.md")):
        content = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                errors.append(f"possible secret in {path.relative_to(ROOT)}: {pattern.pattern}")

    body_lines = body.count("\n") + 1
    if body_lines > 300:
        errors.append(f"SKILL.md body is {body_lines} lines; keep it at or below 300")

    if README_FILE.is_file() and "skills/dr-panda-mcp/SKILL.md" not in _read(README_FILE):
        errors.append("README.md does not link to skills/dr-panda-mcp/SKILL.md")
    if CURSOR_RULE.is_file():
        rule = _read(CURSOR_RULE)
        if "SKILL.md" not in rule or "systems_status" not in rule:
            errors.append("Cursor rule must point to SKILL.md and systems_status")
    else:
        errors.append(f"missing Cursor rule: {CURSOR_RULE.relative_to(ROOT)}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("skill check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    tools = known_tools()
    print(
        "OK: dr-panda-mcp skill validated "
        f"({len(tools)} tools, {len(list(SKILL_DIR.rglob('*.md')))} markdown files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
