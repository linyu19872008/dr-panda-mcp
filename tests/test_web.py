from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from dr_panda_mcp.errors import missing_client_message
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.server import create_app
from dr_panda_mcp.web.views import split_install_command

BASE_URL = "http://127.0.0.1"

COMMON = {"timeout_s": "15", "max_rows": "100", "max_bytes": "102400"}

PAYLOADS: dict[str, dict[str, str]] = {
    "mysql": {
        "type": "mysql",
        "name": "mysql-target",
        "enabled": "on",
        "host": "127.0.0.1",
        "port": "3306",
        "user": "u",
        "default_db": "app",
        "secret_password": "pw",
        **COMMON,
    },
    "mongo": {
        "type": "mongo",
        "name": "mongo-target",
        "enabled": "on",
        "host": "127.0.0.1",
        "port": "27017",
        "auth_source": "admin",
        "allowed_dbs": "app\npay",
        **COMMON,
    },
    "elasticsearch": {
        "type": "elasticsearch",
        "name": "es-target",
        "enabled": "on",
        "hosts": "http://127.0.0.1:9200",
        "allowed_indices": "orders\npay",
        "username": "u",
        "secret_password": "pw",
        **COMMON,
    },
    "redis": {
        "type": "redis",
        "name": "redis-target",
        "enabled": "on",
        "host": "127.0.0.1",
        "port": "6379",
        "db": "0",
        **COMMON,
    },
    "gitlab": {
        "type": "gitlab",
        "name": "gitlab-target",
        "enabled": "on",
        "base_url": "https://gitlab.example.com",
        "allowed_projects": "group/app",
        "secret_token": "tok",
        **COMMON,
    },
    "rabbitmq": {
        "type": "rabbitmq",
        "name": "rabbit-target",
        "enabled": "on",
        "management_url": "http://127.0.0.1:15672",
        "user": "guest",
        "allowed_vhosts": "/",
        "secret_password": "guest",
        **COMMON,
    },
    "kafka": {
        "type": "kafka",
        "name": "kafka-target",
        "enabled": "on",
        "bootstrap_servers": "127.0.0.1:9092",
        "security_protocol": "PLAINTEXT",
        "allowed_topics": "orders",
        **COMMON,
    },
    "cls": {
        "type": "cls",
        "name": "cls-target",
        "enabled": "on",
        "region": "ap-guangzhou",
        "allowed_topics": (
            "11111111-1111-1111-1111-111111111111/"
            "22222222-2222-2222-2222-222222222222"
        ),
        "secret_secret_id": "id",
        "secret_secret_key": "key",
        **COMMON,
    },
}


def _client(runtime: Runtime, locale: str | None = "zh-Hans") -> httpx.AsyncClient:
    kwargs = {"cookies": {"drpanda_lang": locale}} if locale else {}
    return httpx.AsyncClient(
        transport=ASGITransport(app=create_app(runtime.config, runtime, auth_required=False)),
        base_url=BASE_URL,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _probe_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """保存前会做一次真实探测；单测里替换为“通过”，避免外呼。

    需要探测失败的用例可以在测试体内再次 monkeypatch。
    """
    from dr_panda_mcp.web import routes as routes_module

    async def fake_probe(draft, existing):
        return {
            "ok": True,
            "message": "连接测试通过，可以保存。",
            "code": None,
            "checked_at": "2026-01-01 00:00:00 UTC",
            "duration_ms": 1,
        }

    monkeypatch.setattr(routes_module, "_test_draft_target", fake_probe)


@pytest.mark.parametrize(("type_", "label"), [
    ("mysql", "MySQL"),
    ("mongo", "Mongo"),
    ("elasticsearch", "Elasticsearch"),
    ("redis", "Redis"),
    ("gitlab", "GitLab"),
    ("rabbitmq", "RabbitMQ"),
    ("kafka", "Kafka"),
    ("cls", "CLS"),
])
async def test_create_each_type(runtime: Runtime, type_: str, label: str) -> None:
    async with _client(runtime) as client:
        response = await client.post("/targets", data=PAYLOADS[type_])
        index = await client.get("/targets")

    assert response.status_code == 303
    target = await runtime.store.get(PAYLOADS[type_]["name"])
    assert target is not None and target.type == type_
    assert PAYLOADS[type_]["name"] in index.text
    assert label in index.text


async def test_cls_rejects_friendly_topic_names(runtime: Runtime) -> None:
    payload = {
        **PAYLOADS["cls"],
        "name": "cls-bad-topic",
        "allowed_topics": "gateway-prod",
    }
    async with _client(runtime) as client:
        response = await client.post("/targets", data=payload)

    assert response.status_code == 400
    assert "UUID" in response.text or "日志集ID" in response.text
    assert await runtime.store.get("cls-bad-topic") is None


async def test_create_nacos_target(runtime: Runtime) -> None:
    payload = {
        "type": "nacos",
        "name": "nacos-target",
        "enabled": "on",
        "base_url": "http://127.0.0.1:8848",
        "allowed_namespaces": "public",
        "allowed_groups": "DEFAULT_GROUP",
        "allowed_data_ids": "demo.yaml",
        "allowed_services": "demo",
        **COMMON,
    }
    async with _client(runtime) as client:
        response = await client.post("/targets", data=payload)

    assert response.status_code == 303
    target = await runtime.store.get("nacos-target")
    assert target is not None
    assert target.type == "nacos"
    assert target.options["allowed_data_ids"] == ["demo.yaml"]


async def test_new_form_and_unknown_type(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        form = await client.get("/targets/new?type=mysql")
        unknown = await client.get("/targets/new?type=oracle")

    assert form.status_code == 200
    assert "MySQL" in form.text and "密码" in form.text
    assert unknown.status_code == 400


async def test_post_unknown_type_rejected(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        response = await client.post(
            "/targets", data={"type": "oracle", "name": "oracle-target", **COMMON}
        )

    assert response.status_code == 400
    assert "未知的目标类型" in response.text


async def test_duplicate_name_rejected(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        response = await client.post("/targets", data=PAYLOADS["mysql"])

    assert response.status_code == 400
    assert "已存在" in response.text


async def test_invalid_name_rejected(runtime: Runtime) -> None:
    payload = dict(PAYLOADS["mysql"])
    payload["name"] = "Order-Mysql"

    async with _client(runtime) as client:
        response = await client.post("/targets", data=payload)

    assert response.status_code == 400
    assert "名称" in response.text


async def test_missing_required_secret_rejected(runtime: Runtime) -> None:
    payload = dict(PAYLOADS["mysql"])
    payload.pop("secret_password")

    async with _client(runtime) as client:
        response = await client.post("/targets", data=payload)

    assert response.status_code == 400
    assert "密码" in response.text


async def test_secret_not_displayed(runtime: Runtime) -> None:
    payload = dict(PAYLOADS["mysql"])
    payload["secret_password"] = "super-secret-value"

    async with _client(runtime) as client:
        await client.post("/targets", data=payload)
        target = await runtime.store.get("mysql-target")
        index = await client.get("/targets")
        edit = await client.get(f"/targets/{target.id}/edit")

    assert "super-secret-value" not in index.text
    assert "super-secret-value" not in edit.text
    assert "已设置" in edit.text


async def test_secret_keep_clear_and_replace(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        target = await runtime.store.get("mysql-target")

        keep = dict(PAYLOADS["mysql"])
        keep.pop("secret_password")
        await client.post(f"/targets/{target.id}", data=keep)
        kept = await runtime.store.get("mysql-target")
        assert kept.secret == {"password": "pw"}

        cleared = dict(keep)
        cleared["clear_password"] = "on"
        rejected = await client.post(f"/targets/{target.id}", data=cleared)
        cleared_target = await runtime.store.get("mysql-target")
        assert rejected.status_code == 400
        assert "不能为空" in rejected.text
        assert cleared_target.secret_fields == frozenset({"password"})

        replaced = dict(keep)
        replaced["secret_password"] = "new-pass"
        await client.post(f"/targets/{target.id}", data=replaced)
        replaced_target = await runtime.store.get("mysql-target")
        assert replaced_target.secret == {"password": "new-pass"}


async def test_toggle_and_delete(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["redis"])
        target = await runtime.store.get("redis-target")

        toggled = await client.post(f"/targets/{target.id}/toggle")
        disabled = await runtime.store.get("redis-target")
        confirm = await client.get(f"/targets/{target.id}/delete")
        removed = await client.post(f"/targets/{target.id}/delete")

    assert toggled.status_code == 303
    assert disabled.enabled is False
    assert confirm.status_code == 200 and "redis-target" in confirm.text
    assert removed.status_code == 303
    assert await runtime.store.get("redis-target") is None


async def test_test_connection_failure_recorded(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dr_panda_mcp import errors

    async def failing(name: str, connector, **_kwargs) -> None:
        raise errors.UpstreamUnavailable("mysql 模拟连接失败")

    monkeypatch.setattr(runtime.catalog, "test_connection", failing)

    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        target = await runtime.store.get("mysql-target")
        await client.post(f"/targets/{target.id}/test")
        index = await client.get("/targets")

    tested = await runtime.store.get("mysql-target")
    assert tested.last_test_ok is False
    assert tested.last_test_error
    assert "mysql" in tested.last_test_error.lower()
    assert "pw" not in tested.last_test_error
    assert "失败" in index.text


def test_split_install_command_keeps_old_and_new_forms() -> None:
    old_message, old_command = split_install_command(
        "mongo 客户端未安装：uv sync --extra mongo"
    )
    assert old_message == "mongo 客户端未安装"
    assert old_command == "uv sync --extra mongo"

    message, command = split_install_command(missing_client_message("mongo"))
    assert command == "uv sync --extra mongo --inexact"
    assert message == "mongo client is not installed"
    assert "uv sync" not in message


async def test_missing_client_offers_install_without_copy(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mongo"])
        target = await runtime.store.get("mongo-target")
        await runtime.store.record_test(
            target.id, False, missing_client_message("mongo"), "test"
        )
        page = await client.get("/targets")

    assert "mongo client is not installed" in page.text
    assert "uv sync" not in page.text
    assert "data-copy-command" not in page.text
    assert "data-test-command" not in page.text
    assert 'data-dialog-open="install-client-' in page.text
    assert "/install-client" in page.text
    assert "确认安装" in page.text


async def test_connection_failure_has_no_install_button(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mongo"])
        target = await runtime.store.get("mongo-target")
        await runtime.store.record_test(target.id, False, "mongo 探测失败：refused", "test")
        page = await client.get("/targets")

    assert "mongo 探测失败" in page.text
    assert 'data-dialog-open="install-client-' not in page.text


async def test_install_client_runs_inexact_then_retests(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed: list[str] = []

    async def fake_install(extra: str) -> None:
        installed.append(extra)

    async def fake_test(name: str, connector, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "dr_panda_mcp.web.routes.client_install.install_extra", fake_install
    )
    monkeypatch.setattr(runtime.catalog, "test_connection", fake_test)
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mongo"])
        target = await runtime.store.get("mongo-target")
        await runtime.store.record_test(
            target.id, False, "mongo 客户端未安装：uv sync --extra mongo", "test"
        )
        response = await client.post(
            f"/targets/{target.id}/install-client",
            headers={"accept": "application/json"},
        )

    tested = await runtime.store.get("mongo-target")
    assert response.status_code == 200
    assert response.json()["test_ok"] is True
    assert installed == ["mongo"]
    assert tested.last_test_ok is True


async def test_install_failure_keeps_command(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dr_panda_mcp.client_install import InstallError

    async def fake_install(extra: str) -> None:
        raise InstallError("network down uv sync --extra mongo --inexact")

    monkeypatch.setattr(
        "dr_panda_mcp.web.routes.client_install.install_extra", fake_install
    )
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mongo"])
        target = await runtime.store.get("mongo-target")
        await runtime.store.record_test(
            target.id, False, missing_client_message("mongo"), "test"
        )
        response = await client.post(
            f"/targets/{target.id}/install-client",
            headers={"accept": "application/json"},
        )

    body = response.json()
    tested = await runtime.store.get("mongo-target")
    assert response.status_code == 400
    assert body["ok"] is False
    assert "network down" in body["test_error"]
    assert body["test_command"] == "uv sync --extra mongo --inexact"
    assert tested.last_test_ok is False
    assert "pw" not in (tested.last_test_error or "")


async def test_install_rejects_when_client_is_present(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    async def fake_install(extra: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "dr_panda_mcp.web.routes.client_install.install_extra", fake_install
    )
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["elasticsearch"])
        target = await runtime.store.get("es-target")
        await runtime.store.record_test(target.id, False, "es 探测失败：down", "test")
        response = await client.post(
            f"/targets/{target.id}/install-client",
            headers={"accept": "application/json"},
        )

    assert response.status_code == 400
    assert called is False
    assert "无需安装" in response.json()["message"]


async def test_test_connection_success_recorded(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(name: str, connector, **_kwargs) -> None:
        return None

    monkeypatch.setattr(runtime.catalog, "test_connection", fake)
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["redis"])
        target = await runtime.store.get("redis-target")
        await client.post(f"/targets/{target.id}/test")

    tested = await runtime.store.get("redis-target")
    assert tested.last_test_ok is True


async def test_settings_page_and_update(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        page = await client.get("/settings?section=runtime")
        saved = await client.post(
            "/settings",
            data={"audit_retention_days": "30", "target_max_concurrency": "5"},
        )
        after = await client.get("/settings?section=runtime")
        invalid = await client.post(
            "/settings",
            data={"audit_retention_days": "0", "target_max_concurrency": "10"},
        )

    assert page.status_code == 200 and "90" in page.text and "10" in page.text
    assert saved.status_code == 303
    assert "30" in after.text and "5" in after.text
    stored = await runtime.store.get_settings()
    assert stored["audit_retention_days"] == "30"
    assert stored["target_max_concurrency"] == "5"
    assert len(stored) == 17
    assert invalid.status_code == 400


async def test_cross_site_post_rejected(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        response = await client.post(
            "/targets",
            data=PAYLOADS["mysql"],
            headers={"origin": "http://evil.example"},
        )

    assert response.status_code == 403
    assert await runtime.store.get("mysql-target") is None


async def test_unknown_target_404(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        for method, path in [
            ("GET", "/targets/999/edit"),
            ("POST", "/targets/999/toggle"),
            ("GET", "/targets/999/delete"),
            ("POST", "/targets/999/delete"),
            ("POST", "/targets/999/test"),
        ]:
            response = await client.request(method, path)
            assert response.status_code == 404, (method, path)


# ---------------------------------------------------------------------------
# 界面骨架、主题与静态资源
# ---------------------------------------------------------------------------
async def test_index_shell_and_default_theme(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        page = await client.get("/")
        targets = await client.get("/targets")
        admin_overview = await client.get("/admin/overview")

    text = page.text
    assert '<html lang="zh-Hans">' in text
    assert 'class="skip-link"' in text
    assert 'id="main"' in text
    assert 'aria-current="page"' in text
    assert 'aria-label="主导航"' in text
    assert 'class="sidebar"' in text
    nav = text.split('aria-label="主导航"', 1)[1]
    assert (
        nav.index("概览")
        < nav.index("管理概览")
        < nav.index("目标")
        < nav.index("环境")
        < nav.index("审计")
    )
    assert nav.index("审计") < nav.index("系统配置") < nav.index("用户") < nav.index("我的")
    assert 'name="mode" value="dark"' in text
    assert "/static/app.css?v=" in text
    assert 'src="/static/icon.png?v=' in text
    assert "可查询的目标" in text
    assert 'href="/admin/overview"' in text
    assert "没有需要处理的目标" in admin_overview.text
    assert text.count("<h1") == 1
    assert 'class="brand__name">DrPanda<' in text
    assert "<title>概览 · DrPanda MCP</title>" in text
    assert "还没有登记任何目标" in targets.text
    assert "<title>目标 · DrPanda MCP</title>" in targets.text


async def test_theme_cookie_roundtrip(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        dark = await client.post("/theme", data={"mode": "dark", "next": "/"})
        page = await client.get("/")
        assert dark.status_code == 303
        assert dark.headers["location"] == "/"
        assert 'data-theme="dark"' in page.text

        await client.post("/theme", data={"mode": "light", "next": "/"})
        page = await client.get("/")
        assert 'data-theme="light"' in page.text

        await client.post("/theme", data={"mode": "system", "next": "/"})
        page = await client.get("/")
        assert '<html lang="zh-Hans">' in page.text


async def test_theme_rejects_open_redirect(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        response = await client.post(
            "/theme", data={"mode": "dark", "next": "//evil.example/x"}
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/"


async def test_static_css_route(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        first = await client.get("/static/app.css")
        cached = await client.get(
            "/static/app.css", headers={"if-none-match": first.headers["etag"]}
        )
        missing = await client.get("/static/nope.css")
        icon = await client.get("/static/icon.png")
        favicon = await client.get("/favicon.ico")

    assert first.status_code == 200
    assert "text/css" in first.headers["content-type"]
    assert "--accent" in first.text
    assert first.headers.get("etag")
    assert cached.status_code == 304
    assert missing.status_code == 404
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/png")
    assert icon.content.startswith(b"\x89PNG")
    assert favicon.status_code == 200
    assert favicon.content == icon.content


async def test_type_chooser_page(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        page = await client.get("/targets/new")

    assert page.status_code == 200
    assert "选择目标类型" in page.text
    for label in ["MySQL", "Mongo", "Elasticsearch", "Redis", "GitLab", "RabbitMQ", "Kafka", "CLS"]:
        assert label in page.text
    assert "/targets/new?type=mysql" in page.text


# ---------------------------------------------------------------------------
# 搜索、筛选、统计与反馈
# ---------------------------------------------------------------------------
async def test_search_and_type_filter(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        await client.post("/targets", data=PAYLOADS["redis"])

        search = await client.get("/targets", params={"q": "mysql-target"})
        filtered = await client.get("/targets", params={"type": "redis"})
        no_match = await client.get("/targets", params={"q": "no-such-target"})

    assert "mysql-target" in search.text
    assert "redis-target" not in search.text
    assert "redis-target" in filtered.text
    assert "mysql-target" not in filtered.text
    assert "没有匹配的目标" in no_match.text


async def test_stats_and_flash_messages(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        created = await client.post("/targets", data=PAYLOADS["redis"])
        location = created.headers["location"]
        page = await client.get(location)
        target = await runtime.store.get("redis-target")

        toggled = await client.post(f"/targets/{target.id}/toggle")
        toggled_page = await client.get(toggled.headers["location"])

        deleted = await client.post(f"/targets/{target.id}/delete")
        deleted_page = await client.get(deleted.headers["location"])

    assert "flash=created" in location
    assert "目标已创建" in page.text
    assert "目标总数" in page.text
    assert "启用状态已切换" in toggled_page.text
    assert "目标已删除" in deleted_page.text


# ---------------------------------------------------------------------------
# 表单与错误页
# ---------------------------------------------------------------------------
async def test_form_sections_and_error_summary(runtime: Runtime) -> None:
    payload = dict(PAYLOADS["mysql"])
    payload.pop("secret_password")

    async with _client(runtime) as client:
        form = await client.get("/targets/new?type=mysql")
        invalid = await client.post("/targets", data=payload)

    assert form.status_code == 200
    for section in ["基本信息", "连接", "授权范围", "密钥", "运行限制"]:
        assert section in form.text
    assert 'name="secret_password"' in form.text
    assert invalid.status_code == 400
    assert "有 1 处需要修改" in invalid.text
    assert 'aria-invalid="true"' in invalid.text
    assert "#err-secret_password" in invalid.text


async def test_edit_form_shows_secret_badge(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        target = await runtime.store.get("mysql-target")
        page = await client.get(f"/targets/{target.id}/edit")

    assert page.status_code == 200
    assert "已设置" in page.text
    assert "清除已保存的密钥" in page.text
    assert "value=\"pw\"" not in page.text


async def test_html_error_pages(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        not_found = await client.get("/targets/999/edit")
        bad_type = await client.get("/targets/new?type=oracle")

    assert not_found.status_code == 404
    assert "找不到目标" in not_found.text
    assert "返回概览" in not_found.text
    assert bad_type.status_code == 400
    assert "未知的目标类型" in bad_type.text


async def test_table_accessibility_markup(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        page = await client.get("/targets")

    assert page.text.count('scope="col"') >= 6
    assert 'aria-label="按类型筛选"' in page.text
    assert 'data-test-status' in page.text
    assert 'data-test-label' in page.text
    assert 'data-stat="total"' in page.text


async def test_no_javascript_and_css_budget(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        pages = [
            await client.get("/"),
            await client.get("/targets/new?type=mysql"),
            await client.get("/settings"),
        ]
        css = await client.get("/static/app.css")

    for page in pages:
        # 只允许全局渐进增强 app.js；不允许内联脚本或其他第三方脚本。
        assert page.text.count("<script") == 1
        assert 'src="/static/app.js' in page.text
        assert "<script>" not in page.text
    assert len(css.content) < 55_000


async def test_required_secret_cannot_be_cleared_on_edit(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        target = await runtime.store.get("mysql-target")
        payload = dict(PAYLOADS["mysql"])
        payload["clear_password"] = "on"
        payload.pop("secret_password", None)
        response = await client.post(f"/targets/{target.id}", data=payload)

    assert response.status_code == 400
    assert "不能为空" in response.text
    stored = await runtime.store.get("mysql-target")
    assert stored is not None and "password" in stored.secret_fields


def test_theme_next_rejects_backslash_variants() -> None:
    from dr_panda_mcp.web.theme import safe_next

    assert safe_next("/") == "/"
    assert safe_next("/settings?x=1") == "/settings?x=1"
    assert safe_next("/\\evil.example") == "/"
    assert safe_next("/%5Cevil.example") == "/"
    assert safe_next("//evil.example") == "/"
    assert safe_next("/language") == "/"
    assert safe_next("/language?next=/") == "/"
    assert safe_next("/theme") == "/"


async def test_ca_pem_validation_and_persistence(runtime: Runtime) -> None:
    from tests.test_connectors_data import _ca_pem

    async with _client(runtime) as client:
        form = await client.get("/targets/new?type=mysql")
        invalid = dict(PAYLOADS["mysql"])
        invalid["ssl"] = "on"
        invalid["ca_pem"] = "not a certificate"
        bad = await client.post("/targets", data=invalid)

        no_ssl = dict(PAYLOADS["mysql"])
        no_ssl["ca_pem"] = _ca_pem()
        rejected = await client.post("/targets", data=no_ssl)

        valid = dict(PAYLOADS["mysql"])
        valid["ssl"] = "on"
        valid["ca_pem"] = _ca_pem()
        created = await client.post("/targets", data=valid)
        target = await runtime.store.get("mysql-target")

    assert "CA 证书 PEM" in form.text
    assert bad.status_code == 400 and "CA 证书不是合法 PEM" in bad.text
    assert rejected.status_code == 400 and "必须启用 SSL" in rejected.text
    assert created.status_code == 303
    assert target is not None and target.options["ca_pem"].startswith("-----BEGIN CERTIFICATE-----")


async def test_client_cert_pair_validation(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        only_cert = dict(PAYLOADS["mysql"])
        only_cert["ssl"] = "on"
        only_cert["secret_client_cert"] = "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----"
        rejected = await client.post("/targets", data=only_cert)

        both = dict(only_cert)
        both["secret_client_key"] = "-----BEGIN PRIVATE KEY-----\ny\n-----END PRIVATE KEY-----"
        created = await client.post("/targets", data=both)
        target = await runtime.store.get("mysql-target")

    assert rejected.status_code == 400
    assert "必须同时提供" in rejected.text
    assert created.status_code == 303
    assert target is not None
    assert {"client_cert", "client_key"} <= target.secret_fields
    assert target.secret["client_key"].startswith("-----BEGIN PRIVATE KEY-----")


async def test_mongo_auth_mode_validation(runtime: Runtime) -> None:
    base = {
        "type": "mongo",
        "name": "mongo-auth-target",
        "enabled": "on",
        "port": "27017",
        "auth_source": "admin",
        "allowed_dbs": "app",
        **COMMON,
    }

    async with _client(runtime) as client:
        none_with_user = dict(base)
        none_with_user["user"] = "ro"
        rejected = await client.post("/targets", data=none_with_user)

        password_missing = dict(base)
        password_missing["auth_mode"] = "password"
        password_missing["host"] = "127.0.0.1"
        password_missing["user"] = "ro"
        missing = await client.post("/targets", data=password_missing)

        password_ok = dict(password_missing)
        password_ok["secret_password"] = "pw"
        created = await client.post("/targets", data=password_ok)
        target = await runtime.store.get("mongo-auth-target")

        uri_with_host = dict(base)
        uri_with_host["auth_mode"] = "uri"
        uri_with_host["host"] = "127.0.0.1"
        uri_with_host["secret_uri"] = "mongodb://127.0.0.1:27017/"
        conflict = await client.post("/targets", data=uri_with_host)

    assert rejected.status_code == 400 and "不能填写" in rejected.text
    assert missing.status_code == 400 and "密码" in missing.text
    assert created.status_code == 303
    assert target is not None and target.options["auth_mode"] == "password"
    assert target.secret_fields == frozenset({"password"})
    assert conflict.status_code == 400 and "必须留空" in conflict.text


async def test_redis_acl_and_tls_fields(runtime: Runtime) -> None:
    from tests.test_connectors_data import _ca_pem

    base = {
        "type": "redis",
        "name": "redis-acl",
        "enabled": "on",
        "host": "127.0.0.1",
        "port": "6379",
        "db": "0",
        "username": "drpanda",
        "tls": "on",
        "ca_pem": _ca_pem(),
        **COMMON,
    }
    async with _client(runtime) as client:
        no_password = dict(base)
        rejected = await client.post("/targets", data=no_password)

        valid = dict(base)
        valid["secret_password"] = "pw"
        created = await client.post("/targets", data=valid)
        target = await runtime.store.get("redis-acl")

    assert rejected.status_code == 400 and "密码" in rejected.text
    assert created.status_code == 303
    assert target is not None
    assert target.options["username"] == "drpanda"
    assert target.options["tls"] is True
    assert target.secret_fields == frozenset({"password"})


async def test_kafka_sasl_fields_validation(runtime: Runtime) -> None:
    base = {
        "type": "kafka",
        "name": "kafka-sasl",
        "enabled": "on",
        "bootstrap_servers": "127.0.0.1:9092",
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-256",
        "allowed_topics": "orders",
        **COMMON,
    }
    async with _client(runtime) as client:
        no_user = dict(base, secret_sasl_password="pw")
        rejected = await client.post("/targets", data=no_user)

        valid = dict(no_user, sasl_user="drpanda")
        created = await client.post("/targets", data=valid)
        target = await runtime.store.get("kafka-sasl")

        non_sasl = dict(base)
        non_sasl["security_protocol"] = "PLAINTEXT"
        non_sasl["sasl_user"] = "drpanda"
        non_sasl["secret_sasl_password"] = "pw"
        conflict = await client.post("/targets", data=non_sasl)

    assert rejected.status_code == 400 and "SASL 用户" in rejected.text
    assert created.status_code == 303
    assert target is not None
    assert target.options["sasl_mechanism"] == "SCRAM-SHA-256"
    assert target.secret_fields == frozenset({"sasl_password"})
    assert conflict.status_code == 400 and "非 SASL" in conflict.text


async def test_settings_page_is_grouped(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        page = await client.get("/settings")

    assert "新建目标默认值" in page.text
    assert "并发与审计" in page.text
    assert "高级资源" in page.text
    assert "安全边界" in page.text
    assert "启动配置" in page.text
    assert "settings-nav" in page.text
    assert "仅新建目标" in page.text
    assert "立即生效" not in page.text


async def test_new_target_uses_system_default_limits(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_test(name: str, connector, **_kwargs) -> None:
        return None

    monkeypatch.setattr(runtime.catalog, "test_connection", fake_test)
    async with _client(runtime) as client:
        await client.post(
            "/settings",
            data={
                "default_target_timeout_s": "30",
                "default_target_max_rows": "20",
                "default_target_max_bytes": "8192",
            },
        )
        page = await client.get("/targets/new?type=mysql")
        payload = dict(PAYLOADS["mysql"])
        payload.pop("timeout_s")
        payload.pop("max_rows")
        payload.pop("max_bytes")
        created = await client.post("/targets", data=payload)
        target = await runtime.store.get("mysql-target")

    assert created.status_code == 303
    assert target is not None
    assert target.options["timeout_s"] == 30
    assert target.options["max_rows"] == 20
    assert target.options["max_bytes"] == 8192
    assert 'value="30"' in page.text
    assert 'value="20"' in page.text
    assert 'value="8192"' in page.text


async def test_settings_field_error_preserves_input(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        response = await client.post(
            "/settings",
            data={
                "default_target_timeout_s": "0",
                "default_target_max_rows": "100",
                "default_target_max_bytes": "102400",
                "target_max_concurrency": "10",
                "audit_retention_days": "90",
                "audit_cleanup_interval_minutes": "60",
            },
        )

    assert response.status_code == 400
    assert "默认超时" in response.text
    assert 'value="0"' in response.text


async def test_settings_reset_and_history(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        saved = await client.post(
            "/settings",
            data={
                "default_target_timeout_s": "30",
                "default_target_max_rows": "20",
                "default_target_max_bytes": "8192",
                "target_max_concurrency": "5",
                "audit_retention_days": "30",
                "audit_cleanup_interval_minutes": "15",
            },
        )
        confirm = await client.get("/settings/reset")
        page = await client.get("/settings")
        reset = await client.post("/settings/reset")
        after_runtime = await client.get("/settings?section=runtime")

    assert saved.status_code == 303
    assert confirm.status_code == 200
    assert "恢复默认配置" in confirm.text
    assert "最近变更" in page.text
    assert reset.status_code == 303
    assert "60" in after_runtime.text
    current = await runtime.store.get_settings()
    assert current["default_target_timeout_s"] == "15"
    assert current["audit_cleanup_interval_minutes"] == "60"


async def test_single_setting_reset(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post(
            "/settings",
            data={
                "default_target_timeout_s": "30",
                "default_target_max_rows": "20",
                "default_target_max_bytes": "8192",
                "target_max_concurrency": "5",
                "audit_retention_days": "30",
                "audit_cleanup_interval_minutes": "15",
                "catalog_max_clients": "16",
            },
        )
        confirm = await client.get("/settings/reset?key=default_target_timeout_s")
        reset = await client.post(
            "/settings/reset", data={"key": "default_target_timeout_s"}
        )
        row = await runtime.store.get_settings()

    assert confirm.status_code == 200
    assert "默认超时" in confirm.text
    assert "每 target 并发" not in confirm.text
    assert reset.status_code == 303
    assert row["default_target_timeout_s"] == "15"
    assert row["default_target_max_rows"] == "20"
    assert row["target_max_concurrency"] == "5"


async def test_settings_group_advanced_and_single_reset_links(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        page = await client.get("/settings?section=advanced")

    assert "高级资源" in page.text
    assert "连接器缓存上限" in page.text
    assert "settings/reset?key=catalog_max_clients" in page.text


async def test_settings_section_switching_and_save(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        advanced = await client.get("/settings?section=advanced")
        security = await client.get("/settings?section=security")
        saved = await client.post(
            "/settings",
            data={"section": "advanced", "catalog_max_clients": "64"},
        )
        advanced_after = await client.get("/settings?section=advanced")
        invalid = await client.get("/settings?section=not-a-section")

    assert "连接器缓存上限" in advanced.text
    assert 'name="default_target_timeout_s"' not in advanced.text
    assert "安全边界" in security.text
    assert "settings-field__reset" not in security.text
    assert saved.status_code == 303
    assert "section=advanced" in saved.headers["location"]
    assert 'value="64"' in advanced_after.text
    assert invalid.status_code == 200
    assert "默认超时" in invalid.text


async def test_settings_runtime_uses_field_rows_and_subgroups(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        page = await client.get("/settings?section=runtime")

    assert "并发控制" in page.text
    assert "审计维护" in page.text
    assert "settings-field-row" in page.text
    assert "恢复本项默认" in page.text
    assert "settings-field__reset" in page.text
    assert "下一次取槽" in page.text


async def test_default_english_and_language_switch(runtime: Runtime) -> None:
    async with _client(runtime, locale=None) as client:
        home = await client.get("/")
        settings = await client.get("/settings?section=runtime")
        switched = await client.post(
            "/language", data={"lang": "zh-Hans", "next": "/settings?section=runtime"}
        )
        chinese = await client.get("/settings?section=runtime")

    assert '<html lang="en">' in home.text
    assert "Targets" in home.text
    assert "Settings" in settings.text
    assert "Concurrency &amp; audit" in settings.text
    assert settings.headers["content-language"] == "en"
    assert switched.status_code == 303
    assert switched.headers["location"] == "/settings?section=runtime"
    assert '<html lang="zh-Hans">' in chinese.text
    assert "系统配置" in chinese.text
    assert chinese.headers["content-language"] == "zh-Hans"


async def test_invalid_language_falls_back_to_english(runtime: Runtime) -> None:
    async with _client(runtime, locale=None) as client:
        await client.post("/language", data={"lang": "xx", "next": "/"})
        page = await client.get("/")

    assert '<html lang="en">' in page.text
    assert "Targets" in page.text


async def test_english_pages_are_fully_translated(runtime: Runtime) -> None:
    import re

    urls = [
        "/",
        "/targets",
        "/users",
        "/environments",
        "/environments/new",
        "/audit",
        "/targets/new",
        "/targets/new?type=mysql",
        "/targets/new?type=mongo",
        "/targets/new?type=elasticsearch",
        "/settings",
        "/settings?section=runtime",
        "/settings?section=auth",
        "/settings?section=advanced",
        "/settings?section=security",
        "/settings?section=startup",
        "/settings?section=history",
        "/settings/reset?key=default_target_timeout_s",
        "/nope",
    ]
    async with _client(runtime, locale=None) as client:
        for url in urls:
            response = await client.get(url)
            assert response.status_code in {200, 404}
            chinese = [
                chunk
                for chunk in re.findall(r"[\u4e00-\u9fff][^<>]*", response.text)
                if chunk.strip().strip('"') not in {"简体中文", "中文"}
            ]
            assert not chinese, f"{url} has untranslated Chinese: {chinese[:5]}"


async def test_english_validation_errors_are_translated(runtime: Runtime) -> None:
    import re

    payload = dict(PAYLOADS["mysql"])
    payload.pop("name")
    payload["port"] = "not-a-number"
    async with _client(runtime, locale=None) as client:
        response = await client.post("/targets", data=payload)

    assert response.status_code == 400
    assert "Name is required" in response.text
    assert "Port must be an integer" in response.text
    assert not [c for c in re.findall(r"[\u4e00-\u9fff][^<>]*", response.text) if c.strip().strip('"') not in {"简体中文", "中文"}]


async def test_destructive_confirm_dialogs_markup(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mysql"])
        index = await client.get("/targets")
        settings = await client.get("/settings?section=runtime")

    assert 'data-dialog-open="delete-target-' in index.text
    assert '<dialog id="delete-target-' in index.text
    assert 'href="/targets/1/delete"' in index.text
    assert 'data-dialog-open="reset-all-settings"' in settings.text
    assert '<dialog id="reset-all-settings"' in settings.text
    assert 'data-dialog-open="reset-setting-audit_retention_days"' in settings.text


async def test_form_advanced_layout_and_copy(runtime: Runtime) -> None:
    async with _client(runtime) as client:
        form = await client.get("/targets/new?type=mysql")

    assert form.status_code == 200
    assert "Default ; range —" not in form.text
    assert 'data-probe-button' in form.text
    assert 'type="button"' in form.text
    assert 'data-submit-loading' in form.text
    assert '<details class="card form-section form-advanced"' in form.text
    assert "高级设置" in form.text
    assert 'class="field field--full"' in form.text
    assert "TLS、证书、运行限制" in form.text


async def test_test_connection_action_does_not_save(
    runtime: Runtime, monkeypatch
) -> None:
    from dr_panda_mcp.web import routes as routes_module

    async def fake_test(draft, existing):
        return {"ok": True, "message": "连接可用，可以保存目标。"}

    monkeypatch.setattr(routes_module, "_test_draft_target", fake_test)
    async with _client(runtime) as client:
        response = await client.post(
            "/targets", data={**PAYLOADS["mysql"], "action": "test"}
        )
        target = await runtime.store.get("mysql-target")

    assert response.status_code == 200
    assert "连接测试通过" in response.text
    assert target is None


def test_probe_install_extra_matches_fixed_commands() -> None:
    from dr_panda_mcp.web import views

    for extra in ("mysql", "mongo", "redis", "kafka", "cls"):
        assert views.probe_install_extra(extra, missing_client_message(extra)) == extra
    assert views.probe_install_extra("mongo", "mongo 探测失败：refused") is None
    assert views.probe_install_extra("elasticsearch", missing_client_message("mongo")) is None


async def test_probe_json_exposes_install_extra(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dr_panda_mcp.web import routes as routes_module

    async def fake_probe(draft, existing):
        return {
            "ok": False,
            "message": missing_client_message("mongo"),
            "code": None,
            "install_extra": "mongo",
            "checked_at": "2026-01-01 00:00:00 UTC",
            "duration_ms": 1,
        }

    monkeypatch.setattr(routes_module, "_test_draft_target", fake_probe)
    async with _client(runtime) as client:
        response = await client.post(
            "/targets/probe",
            data=PAYLOADS["mongo"],
            headers={"accept": "application/json"},
        )
        html = await client.post(
            "/targets/probe",
            data=PAYLOADS["mongo"],
            headers={"accept": "text/html"},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["install_extra"] == "mongo"
    assert "uv sync" not in body["message"]
    assert html.status_code == 200
    assert "data-probe-install" in html.text
    assert 'form="target-install-client-form"' in html.text
    assert "/targets/install-client" in html.text
    assert "uv sync" not in html.text


async def test_form_install_route_uses_fixed_extra(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dr_panda_mcp.web import routes as routes_module

    installed: list[str] = []

    async def fake_install(extra: str) -> None:
        installed.append(extra)

    monkeypatch.setattr(routes_module.client_install, "install_extra", fake_install)
    async with _client(runtime) as client:
        response = await client.post(
            "/targets/install-client",
            data={"type": "mongo"},
            headers={"accept": "application/json"},
        )
        unsupported = await client.post(
            "/targets/install-client",
            data={"type": "elasticsearch"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 200
    assert response.json()["install_extra"] == "mongo"
    assert installed == ["mongo"]
    assert unsupported.status_code == 400


async def test_probe_failure_marks_install_extra(runtime: Runtime) -> None:
    from dr_panda_mcp.web import routes as routes_module

    async with _client(runtime) as client:
        await client.post("/targets", data=PAYLOADS["mongo"])
    target = await runtime.store.get("mongo-target")
    result = routes_module._probe_failure(
        0, Exception(missing_client_message("mongo")), target
    )
    assert result["install_extra"] == "mongo"
    assert "uv sync" in result["message"]


async def test_form_install_failure_is_clean(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dr_panda_mcp.client_install import InstallError
    from dr_panda_mcp.web import routes as routes_module

    async def fake_install(extra: str) -> None:
        raise InstallError("network down uv sync --extra mongo --inexact")

    monkeypatch.setattr(routes_module.client_install, "install_extra", fake_install)
    async with _client(runtime) as client:
        response = await client.post(
            "/targets/install-client",
            data={"type": "mongo"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["install_extra"] == "mongo"
    assert "network down" in body["message"]
    assert "uv sync" not in body["message"]
