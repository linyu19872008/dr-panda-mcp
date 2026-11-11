# Contributing to DrPanda MCP

[English](CONTRIBUTING.md) · [简体中文](CONTRIBUTING.zh-CN.md)

Thanks for taking the time to contribute. DrPanda MCP is a read-only MCP service for production troubleshooting; changes that weaken the read-only boundary, expose credentials, or broaden target scope will not be accepted.

## Development setup

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/linyu19872008/dr-panda-mcp.git
cd dr-panda-mcp
uv sync --all-extras --dev
uv run pre-commit install   # ruff + README.pypi.md regen on commit
cp .env.example .env        # optional; the app loads ./.env automatically
```

Run the checks before opening a pull request:

```bash
uv run pre-commit run --all-files
uv run ruff check .
uv run pytest -q
uv run python scripts/smoke.py
uv run python scripts/check_docs_links.py
uv run python scripts/build_pypi_readme.py --check
```

If you change files under `alembic/versions/`, also run the real-database setup check (Docker or local MySQL 8 + PostgreSQL 16):

```bash
uv run python scripts/integration/check_db_setup.py
```

Keep the alembic head assertion in that script in the **same commit** as any new migration.

Tests use temporary SQLite databases and temporary keys; do not point them at production systems.

## Pull requests

- Keep changes focused; include tests for behavior changes.
- Update documentation for user-visible behavior (README, relevant files under `docs/`).
- When changing `README.md`, update `README.zh-CN.md` in the same pull request **and** regenerate `README.pypi.md` (`uv run python scripts/build_pypi_readme.py` — pre-commit does this when `README.md` is staged). Do not edit `README.pypi.md` by hand. The same EN/ZH pairing applies to `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`, and `CHANGELOG`.
- Describe what changed, why, and how you verified it. Mention known limitations honestly.
- Do not include secrets, production hostnames, tokens, or customer data in commits, issues, or tests.
- By contributing you agree that your contribution is licensed under the MIT License (see [LICENSE](LICENSE)).

## Reporting security issues

Do not open a public issue for vulnerabilities. Follow [SECURITY.md](SECURITY.md).

## Language

English is the default for code, comments, error codes and this repository's governance files. The UI and product documentation also support Chinese; issues and pull requests may be written in English or Chinese.
