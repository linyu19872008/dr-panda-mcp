#!/usr/bin/env python3
"""Generate README.pypi.md from README.md.

PyPI does not resolve relative links/images, so the package long description
uses GitHub absolute URLs. The repository README stays relative for local and
GitHub rendering.

Usage:
    python scripts/build_pypi_readme.py                    # regenerate README.pypi.md
    python scripts/build_pypi_readme.py --check            # fail if stale (prints diff)
    python scripts/build_pypi_readme.py --output PATH      # write expected content to PATH
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/linyu19872008/dr-panda-mcp"
RAW = "https://raw.githubusercontent.com/linyu19872008/dr-panda-mcp/main"
SOURCE = ROOT / "README.md"
TARGET = ROOT / "README.pypi.md"

ROOT_FILES = {
    "LICENSE",
    "CONTRIBUTING.md",
    "CONTRIBUTING.zh-CN.md",
    "SECURITY.md",
    "SECURITY.zh-CN.md",
    "CODE_OF_CONDUCT.md",
    "CODE_OF_CONDUCT.zh-CN.md",
    "CHANGELOG.md",
    "CHANGELOG.zh-CN.md",
    "README.zh-CN.md",
    ".env.example",
}


def absolute_url(target: str) -> str:
    target = target.strip()
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return target
    if target.startswith("docs/"):
        path = target.removeprefix("docs/")
        if target.endswith("/"):
            return f"{REPO}/tree/main/docs/{path}"
        return f"{REPO}/blob/main/docs/{path}"
    if target in ROOT_FILES:
        return f"{REPO}/blob/main/{target}"
    return target


def image_url(target: str) -> str:
    target = target.strip()
    if target.startswith("docs/"):
        return f"{RAW}/{target}"
    return target


def rewrite(text: str) -> str:
    # HTML images first (badges, logo, screenshots).
    text = re.sub(
        r'(<img[^>]*\bsrc=")([^"]+)(")',
        lambda match: match.group(1) + image_url(match.group(2)) + match.group(3),
        text,
    )
    # Markdown images.
    text = re.sub(
        r'(!\[[^\]]*\]\()([^)\s]+)(\))',
        lambda match: match.group(1) + image_url(match.group(2)) + match.group(3),
        text,
    )
    # HTML anchors to repository files/pages.
    text = re.sub(
        r'(<a[^>]*\bhref=")([^"]+)(")',
        lambda match: match.group(1) + absolute_url(match.group(2)) + match.group(3),
        text,
    )
    # Markdown links to repository files/pages.
    text = re.sub(
        r'(\[[^\]]*\]\()([^)\s]+)(\))',
        lambda match: match.group(1) + absolute_url(match.group(2)) + match.group(3),
        text,
    )
    return text


def build() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    body = rewrite(source)
    header = "<!-- Generated from README.md by scripts/build_pypi_readme.py. Do not edit by hand. -->\n\n"
    return header + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if README.pypi.md is stale; print a unified diff",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write generated content to this path instead of README.pypi.md",
    )
    args = parser.parse_args(argv)
    content = build()

    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current == content:
            print("README.pypi.md is up to date")
            return 0
        print("README.pypi.md is stale; run python scripts/build_pypi_readme.py", file=sys.stderr)
        sys.stdout.writelines(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile="README.pypi.md (committed)",
                tofile="README.pypi.md (expected)",
            )
        )
        return 1

    destination = args.output if args.output is not None else TARGET
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    try:
        label = destination.relative_to(ROOT)
    except ValueError:
        label = destination
    print(f"wrote {label} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
