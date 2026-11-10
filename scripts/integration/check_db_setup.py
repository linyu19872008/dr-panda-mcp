#!/usr/bin/env python3
"""Run the full first-install flow against real MySQL/PostgreSQL test databases.

Requires:
    DR_PANDA_TEST_MYSQL_URL=mysql+asyncmy://user:pass@host:port/drpanda_test?...
    DR_PANDA_TEST_POSTGRES_URL=postgresql+asyncpg://user:pass@host:port/drpanda_test

Only databases whose name ends with ``_test`` are reset. The script drops all
tables/schema in those test databases, then exercises SetupApp over HTTP.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic.script import ScriptDirectory

from dr_panda_mcp import auth
from dr_panda_mcp.config import Config
from dr_panda_mcp.setup import SetupApp
from dr_panda_mcp.store.migrate import _alembic_config, migrate
from dr_panda_mcp.store.url import create_engine

BASE = "http://127.0.0.1"


@dataclass(frozen=True)
class Target:
    kind: str
    url: str


async def reset_database(url: str, kind: str) -> None:
    parsed = make_url(url)
    database = parsed.database or ""
    if not database.endswith("_test"):
        raise SystemExit(f"refusing to reset non-test database: {database!r}")
    engine = create_engine(url)
    try:
        async with engine.begin() as connection:
            if kind == "mysql":
                await connection.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                tables = (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = DATABASE()"
                        )
                    )
                ).scalars().all()
                for table in tables:
                    await connection.execute(text(f"DROP TABLE `{table}`"))
                await connection.execute(text("SET FOREIGN_KEY_CHECKS=1"))
            else:
                await connection.execute(text("DROP SCHEMA public CASCADE"))
                await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


async def run_setup(target: Target) -> None:
    await reset_database(target.url, target.kind)
    parsed = make_url(target.url)
    with tempfile.TemporaryDirectory(prefix=f"drpanda-{target.kind}-") as tmp:
        tmp_path = Path(tmp)
        cfg = Config(
            host="127.0.0.1",
            port=8111,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'placeholder.sqlite'}",
            secret_key_b64=None,
            log_level="INFO",
            install_file=tmp_path / "install.json",
            install_key_file=tmp_path / "install.key",
            session_key_file=tmp_path / "session.key",
        )
        app = SetupApp(cfg)
        try:
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url=BASE,
                cookies={"drpanda_lang": "en"},
            ) as client:
                page = await client.get("/setup/admin")
                csrf = client.cookies.get(auth.CSRF_COOKIE)
                assert csrf and page.status_code == 200
                response = await client.post(
                    "/setup/admin",
                    data={"_csrf": csrf, "password": "abcdefgh", "confirm": "abcdefgh"},
                    follow_redirects=False,
                )
                assert response.status_code == 303, response.text

                page = await client.get("/setup/database")
                csrf = client.cookies.get(auth.CSRF_COOKIE)
                form = {
                    "_csrf": csrf,
                    "db_type": target.kind,
                    "host": parsed.host or "",
                    "port": str(parsed.port or ("3306" if target.kind == "mysql" else "5432")),
                    "database": parsed.database or "",
                    "username": parsed.username or "",
                    "password": parsed.password or "",
                }
                response = await client.post(
                    "/setup/database",
                    data={**form, "action": "test"},
                    headers={"accept": "application/json"},
                )
                assert response.status_code == 200, response.text
                assert response.json()["can_finish"] is True

                response = await client.post(
                    "/setup/database",
                    data={**form, "action": "finish"},
                    headers={"accept": "application/json"},
                )
                assert response.status_code == 200, response.text
                assert response.json()["redirect"] == "/"

                health = await client.get("/healthz")
                assert health.status_code == 200, health.text
                for path in ("/", "/targets", "/settings", "/audit", "/me"):
                    response = await client.get(path)
                    assert response.status_code == 200, f"{path}: {response.status_code}"
        finally:
            await app.close()

        engine = create_engine(target.url)
        try:
            async with engine.connect() as connection:
                version = (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one()
                environment = (
                    await connection.execute(
                        text("SELECT title FROM environments ORDER BY id LIMIT 1")
                    )
                ).scalar_one()
                admin_count = (
                    await connection.execute(
                        text("SELECT COUNT(*) FROM users WHERE username = 'admin'")
                    )
                ).scalar_one()
            heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
            assert len(heads) == 1, heads
            assert version == heads[0], version
            assert environment == "Default", environment
            assert admin_count == 1, admin_count
            # Ensure migrations are idempotent on an already-migrated database.
            await migrate(engine)
        finally:
            await engine.dispose()
    print(f"OK {target.kind}: full setup, pages, schema and idempotent migration")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysql-url", default=os.environ.get("DR_PANDA_TEST_MYSQL_URL"))
    parser.add_argument(
        "--postgres-url", default=os.environ.get("DR_PANDA_TEST_POSTGRES_URL")
    )
    args = parser.parse_args()
    targets = [
        Target("mysql", args.mysql_url),
        Target("postgresql", args.postgres_url),
    ]
    targets = [target for target in targets if target.url]
    if not targets:
        raise SystemExit(
            "set DR_PANDA_TEST_MYSQL_URL and/or DR_PANDA_TEST_POSTGRES_URL"
        )
    for target in targets:
        await run_setup(target)


if __name__ == "__main__":
    asyncio.run(main())
