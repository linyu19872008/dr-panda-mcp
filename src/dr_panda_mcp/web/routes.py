"""配置网页路由（planning 4.1–4.5）。

所有变更走 POST + 表单；Host/Origin 校验由 HTTP 中间件统一完成（3.5）。
主题用 Cookie 三态实现，静态 CSS 由固定路由提供，全程不写 JS。
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from dr_panda_mcp import auth, client_install
from dr_panda_mcp import errors as app_errors
from dr_panda_mcp import settings as settings_module
from dr_panda_mcp.connectors import base as connector_base
from dr_panda_mcp.connectors import get_connector
from dr_panda_mcp.guards.protocol import require
from dr_panda_mcp.masking import redact
from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.store.protocol import ConfigStore, Target
from dr_panda_mcp.web import assets, async_api, clock, forms, i18n, render, theme, views
from dr_panda_mcp.web.audit_page import register_audit_routes
from dr_panda_mcp.web.overview import register_overview_routes
from dr_panda_mcp.web.users_page import register_user_routes

logger = logging.getLogger(__name__)

_FLASH_MESSAGES = {
    "created": ("success", "目标已创建"),
    "updated": ("success", "修改已保存"),
    "toggled": ("success", "启用状态已切换"),
    "deleted": ("success", "目标已删除"),
    "saved": ("success", "系统配置已保存"),
    "reset": ("success", "系统配置已恢复默认值"),
    "env_created": ("success", "环境已创建"),
    "env_updated": ("success", "环境已保存"),
    "env_toggled": ("success", "环境状态已切换"),
    "env_deleted": ("success", "环境已删除"),
}


def register_web_routes(server: FastMCP, runtime: Runtime) -> None:
    register_audit_routes(server, runtime)
    register_overview_routes(server, runtime)
    register_user_routes(server, runtime)
    store = runtime.store

    async def _record_probe_success(target_id: int) -> None:
        """保存时探测已通过：把测试结果顺带写回目标，列表页不再显示“未测试”。"""
        try:
            await store.record_test(target_id, True, None, auth.current_actor())
        except Exception:  # 记录失败不影响保存结果
            logger.warning("保存后记录连接测试结果失败：target=%s", target_id, exc_info=True)

    async def _render_targets(
        request: Request,
        *,
        requested_env: str | None = None,
        env_drawer: bool = False,
        env_values: dict[str, str] | None = None,
        env_errors: dict[str, str] | None = None,
        status: int = 200,
    ) -> HTMLResponse:
        environments = await store.list_environments()
        requested = (
            request.query_params.get("env", "") if requested_env is None else requested_env
        )
        current = _current_environment(environments, requested)
        env_key = current.key if current is not None else ""
        targets = await store.list_all()
        all_views = views.list_views(targets)
        env_views = views.filter_views(all_views, environment=env_key or None)
        q = request.query_params.get("q", "").strip()
        type_ = request.query_params.get("type", "").strip() or None
        if type_ is not None and type_ not in forms.TYPE_SPECS:
            type_ = None
        rows = views.filter_views(env_views, q=q, type_=type_)
        user = auth.current_user()
        if user is not None and user.role != auth.ROLE_ADMIN:
            # 分析员只读：不走管理页模板，只渲染白名单字段与只读动作。
            by_id = {item.id: item for item in targets}
            role_rows = [
                {
                    "name": view.name,
                    "type": view.type,
                    "type_label": view.type_label,
                    "endpoint": view.endpoint,
                    "enabled": view.enabled,
                    "scope": views.scope_details(by_id[view.id]),
                    "last_test_at": view.last_test_at,
                    "last_test_at_display": view.last_test_at_display,
                    "last_test_ok": view.last_test_ok,
                    "last_test_error": view.last_test_error,
                    "last_test_message": view.last_test_message,
                    "last_test_command": view.last_test_command,
                    "environment_key": view.environment_key,
                }
                for view in rows
            ]
            return render.render(
                "targets_readonly.html",
                request=request,
                rows=role_rows,
                stats=views.stats(env_views),
                q=q,
                active_type=type_,
                type_filters=_type_filters(q, type_, env_views, env_key),
                has_targets=bool(env_views),
                environments=environments,
                current_env=current,
                status_code=status,
            )
        return render.render(
            "index.html",
            request=request,
            flash=_flash(request),
            rows=rows,
            stats=views.stats(env_views),
            q=q,
            active_type=type_,
            type_filters=_type_filters(q, type_, env_views, env_key),
            type_cards=forms.type_cards(),
            has_targets=bool(env_views),
            has_any_targets=bool(all_views),
            environments=environments,
            current_env=current,
            env_drawer=env_drawer,
            env_values=env_values,
            env_errors=env_errors or {},
            status_code=status,
        )

    @server.custom_route("/targets", methods=["GET"])
    async def index(request: Request) -> HTMLResponse:
        return await _render_targets(request)

    @server.custom_route("/targets/new", methods=["GET"])
    async def new_target(request: Request) -> Response:
        type_ = request.query_params.get("type", "").strip()
        if not type_:
            environments = await store.list_environments()
            current = _current_environment(environments, _query_env(request))
            return render.render(
                "targets_new.html",
                request=request,
                type_cards=forms.type_cards(),
                env=current.key if current is not None else "",
                current_env=current,
            )
        spec = forms.spec_for(type_)
        if spec is None:
            return _error(request, "未知的目标类型", 400, "无法新建目标")
        current = await settings_module.load(store)
        defaults = settings_module.target_form_defaults(current)
        values = forms.initial_values(spec, defaults=defaults)
        values["environment"] = await _selected_environment(store, request)
        return await _form_page(
            request,
            spec,
            values=values,
            errors={},
            mode="create",
            existing=None,
            common_defaults=defaults,
            store=store,
        )

    @server.custom_route("/targets", methods=["POST"])
    async def create_target(request: Request) -> Response:
        form = await request.form()
        spec = forms.spec_for(str(form.get("type", "")))
        if spec is None:
            return _bad_type(request)
        current = await settings_module.load(store)
        defaults = settings_module.target_form_defaults(current)
        environments = await store.list_environments()
        draft, errors, values = forms.parse_form(
            form, spec=spec, mode="create", defaults=defaults, environments=environments
        )
        if draft is None:
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors=errors,
                mode="create",
                existing=None,
                common_defaults=defaults,
                store=store,
            )
        if str(form.get("action", "")) == "test":
            # 兼容旧表单（HTML 回退）：只探测、不保存；新交互走 /targets/probe。
            result = await _test_draft_target(draft, None)
            return await _probe_render(
                request,
                spec,
                values=values,
                mode="create",
                existing=None,
                result=result,
                common_defaults=defaults,
                store=store,
            )
        # 重名先报错，避免“名冲突”被探测失败掩盖。同一环境内唯一，不同环境可以同名。
        try:
            taken = await store.find(draft.name, environment=draft.environment_key)
        except app_errors.DrPandaError as exc:
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors={"environment": str(exc)},
                mode="create",
                existing=None,
                common_defaults=defaults,
                message=str(exc),
                store=store,
            )
        if taken is not None:
            message = f"目标名 {draft.name} 已存在"
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors={"_form": message},
                mode="create",
                existing=None,
                common_defaults=defaults,
                message=message,
                store=store,
            )
        result = await _test_draft_target(draft, None)
        if not result.get("ok"):
            return await _probe_render(
                request,
                spec,
                values=values,
                mode="create",
                existing=None,
                result=result,
                common_defaults=defaults,
                status=400,
                store=store,
            )
        try:
            created = await store.create(draft, auth.current_actor())
        except app_errors.DrPandaError as exc:
            errors["_form"] = str(exc)
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors=errors,
                mode="create",
                existing=None,
                common_defaults=defaults,
                message=str(exc),
                store=store,
            )
        await _record_probe_success(created.id)
        location = _redirect_target("/targets", flash="created", env=created.environment_key)
        if async_api.wants_json(request):
            return async_api.ok(
                request,
                message="目标已创建",
                data={"redirect": location},
            )
        return _redirect(location)

    @server.custom_route("/targets/probe", methods=["POST"])
    async def probe_new_target(request: Request) -> Response:
        """新建草稿探测：真实调用连接器，不写库、不创建目标。"""
        form = await request.form()
        spec = forms.spec_for(str(form.get("type", "")))
        if spec is None:
            return _bad_type(request)
        current = await settings_module.load(store)
        defaults = settings_module.target_form_defaults(current)
        environments = await store.list_environments()
        draft, errors, values = forms.parse_form(
            form, spec=spec, mode="create", defaults=defaults, environments=environments
        )
        if draft is None:
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors=errors,
                mode="create",
                existing=None,
                common_defaults=defaults,
                store=store,
            )
        result = await _test_draft_target(draft, None)
        return await _probe_render(
            request,
            spec,
            values=values,
            mode="create",
            existing=None,
            result=result,
            common_defaults=defaults,
            store=store,
        )

    @server.custom_route("/targets/{target_id:int}/probe", methods=["POST"])
    async def probe_existing_target(request: Request) -> Response:
        """编辑草稿探测：密钥留空沿用已存值，不写库。"""
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _not_found(request, "目标不存在或已被删除")
        spec = _spec(target)
        form = await request.form()
        environments = await store.list_environments()
        draft, errors, values = forms.parse_form(
            form, spec=spec, mode="edit", existing=target, environments=environments
        )
        if draft is None:
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors=errors,
                mode="edit",
                existing=target,
                store=store,
            )
        result = await _test_draft_target(draft, target)
        return await _probe_render(
            request,
            spec,
            values=values,
            mode="edit",
            existing=target,
            result=result,
            store=store,
        )

    @server.custom_route("/targets/{target_id:int}/edit", methods=["GET"])
    async def edit_target(request: Request) -> Response:
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _error(request, "目标不存在或已被删除", 404, "找不到目标")
        return await _edit_page(
            request,
            target,
            values=forms.initial_values(_spec(target), target),
            errors={},
            store=store,
        )

    @server.custom_route("/targets/{target_id:int}", methods=["POST"])
    async def update_target(request: Request) -> Response:
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _not_found(request, "目标不存在或已被删除")
        spec = _spec(target)
        form = await request.form()
        environments = await store.list_environments()
        draft, errors, values = forms.parse_form(
            form, spec=spec, mode="edit", existing=target, environments=environments
        )
        if draft is None:
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors=errors,
                mode="edit",
                existing=target,
                store=store,
            )
        if str(form.get("action", "")) == "test":
            result = await _test_draft_target(draft, target)
            return await _probe_render(
                request,
                spec,
                values=values,
                mode="edit",
                existing=target,
                result=result,
                store=store,
            )
        probed = False
        if forms.connection_changed(target, draft):
            result = await _test_draft_target(draft, target)
            if not result.get("ok"):
                return await _probe_render(
                    request,
                    spec,
                    values=values,
                    mode="edit",
                    existing=target,
                    result=result,
                    status=400,
                    store=store,
                )
            probed = True
        try:
            await store.update(target.id, draft, auth.current_actor())
        except app_errors.DrPandaError as exc:
            errors["_form"] = str(exc)
            return await _invalid_form(
                request,
                spec,
                values=values,
                errors=errors,
                mode="edit",
                existing=target,
                message=str(exc),
                store=store,
            )
        if probed:
            await _record_probe_success(target.id)
        location = _redirect_target("/targets", flash="updated", env=target.environment_key)
        if async_api.wants_json(request):
            return async_api.ok(
                request,
                message="修改已保存",
                data={"redirect": location},
            )
        return _redirect(location)

    @server.custom_route("/targets/{target_id:int}/toggle", methods=["POST"])
    async def toggle_target(request: Request) -> Response:
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _not_found(request, "目标不存在或已被删除")
        updated = await store.set_enabled(target.id, not target.enabled, auth.current_actor())
        if async_api.wants_json(request):
            label = async_api.translate(request, "已启用" if updated.enabled else "已停用")
            return async_api.ok(
                request,
                data={
                    "enabled": updated.enabled,
                    "label": label,
                    "stats": _stats_payload(
                        await _targets_in_environment(store, updated.environment_key)
                    ),
                },
            )
        return _redirect("/targets", flash="toggled", env=updated.environment_key)

    @server.custom_route("/targets/{target_id:int}/delete", methods=["GET"])
    async def delete_confirm(request: Request) -> Response:
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _error(request, "目标不存在或已被删除", 404, "找不到目标")
        return render.render("delete.html", request=request, target=views.to_view(target))

    @server.custom_route("/targets/{target_id:int}/delete", methods=["POST"])
    async def delete_target(request: Request) -> Response:
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _error(request, "目标不存在或已被删除", 404, "找不到目标")
        env_key = target.environment_key
        await store.delete(target.id, auth.current_actor())
        return _redirect("/targets", flash="deleted", env=env_key)

    async def _probe_saved_target(target: Target) -> tuple[bool, str | None]:
        try:
            await runtime.catalog.test_connection(
                target.name,
                get_connector(target.type),
                environment=target.environment_key,
                allow_disabled_environment=True,
            )
        except app_errors.DrPandaError as exc:
            return False, redact(str(exc), target.secret.values())
        except Exception as exc:
            logger.warning("测试连接失败：%s", target.name, exc_info=True)
            return False, redact(f"未预期错误：{exc}", target.secret.values())
        return True, None

    async def _test_response(
        request: Request, target: Target, ok: bool, message: str | None
    ) -> Response:
        updated = await store.record_test(target.id, ok, message, auth.current_actor())
        if async_api.wants_json(request):
            return async_api.ok(
                request,
                data={
                    **_row_test_payload(updated),
                    "stats": _stats_payload(
                        await _targets_in_environment(store, updated.environment_key)
                    ),
                },
            )
        return _redirect(
            "/targets",
            flash="tested",
            result="ok" if ok else "fail",
            name=target.name,
            env=updated.environment_key,
        )

    @server.custom_route("/targets/{target_id:int}/test", methods=["POST"])
    async def test_target(request: Request) -> Response:
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _not_found(request, "目标不存在或已被删除")
        ok, message = await _probe_saved_target(target)
        return await _test_response(request, target, ok, message)

    @server.custom_route("/targets/install-client", methods=["POST"])
    async def install_form_client(request: Request) -> Response:
        """安装新建/编辑表单探测到的缺失客户端，不写目标记录。"""
        form = await request.form()
        type_ = str(form.get("type", "")).strip()
        spec = forms.spec_for(type_)
        extra = views.client_extra(type_)
        if spec is None or extra is None:
            message = "当前目标类型没有可自动安装的客户端"
            if async_api.wants_json(request):
                return async_api.fail(request, async_api.CODE_BAD_REQUEST, message, status=400)
            return _error(request, message, 400)
        try:
            await client_install.install_extra(extra)
        except client_install.InstallBusy:
            message = "已有客户端正在安装，请稍后再试"
            if async_api.wants_json(request):
                return async_api.fail(request, async_api.CODE_CONFLICT, message, status=409)
            return _error(request, message, 409)
        except client_install.InstallError as exc:
            raw = redact(app_errors.install_failed_message(extra, exc.reason), ())
            message, _ = views.split_install_command(raw)
            message = message or "安装没有完成"
            if async_api.wants_json(request):
                return async_api.fail(
                    request,
                    async_api.CODE_UNAVAILABLE,
                    message,
                    status=400,
                    data={"install_extra": extra},
                )
            return _error(request, message, 400)
        success = "客户端安装完成，请重新测试连接"
        if async_api.wants_json(request):
            return async_api.ok(request, message=success, data={"install_extra": extra})
        target_id = str(form.get("target_id", "")).strip()
        if target_id.isdigit():
            return RedirectResponse(f"/targets/{int(target_id)}/edit", status_code=303)
        return RedirectResponse(f"/targets/new?type={spec.type}", status_code=303)

    @server.custom_route("/targets/{target_id:int}/install-client", methods=["POST"])
    async def install_client(request: Request) -> Response:
        target = await _target(store, request.path_params["target_id"])
        if target is None:
            return _not_found(request, "目标不存在或已被删除")
        extra = views.requested_install_extra(target)
        if extra is None:
            message = "当前失败不是缺少客户端，无需安装"
            if async_api.wants_json(request):
                return async_api.fail(request, async_api.CODE_BAD_REQUEST, message, status=400)
            return _error(request, message, 400)
        try:
            await client_install.install_extra(extra)
        except client_install.InstallBusy:
            message = "已有客户端正在安装，请稍后再试"
            if async_api.wants_json(request):
                return async_api.fail(request, async_api.CODE_CONFLICT, message, status=409)
            return _error(request, message, 409)
        except client_install.InstallError as exc:
            message = redact(
                app_errors.install_failed_message(extra, exc.reason),
                target.secret.values(),
            )
            updated = await store.record_test(target.id, False, message, auth.current_actor())
            if async_api.wants_json(request):
                return async_api.fail(
                    request,
                    async_api.CODE_UNAVAILABLE,
                    "安装没有完成",
                    status=400,
                    data={
                        **_row_test_payload(updated),
                        "stats": _stats_payload(await store.list_all()),
                    },
                )
            return _redirect("/targets", flash="tested", result="fail", name=target.name)
        ok, message = await _probe_saved_target(target)
        return await _test_response(request, target, ok, message)

    async def _render_environments(
        request: Request,
        *,
        env_drawer: bool = False,
        env_values: dict[str, str] | None = None,
        env_errors: dict[str, str] | None = None,
        status: int = 200,
    ) -> HTMLResponse:
        return render.render(
            "environments.html",
            request=request,
            flash=_flash(request),
            environments=await store.list_environments(),
            env_drawer=env_drawer,
            env_values=env_values,
            env_errors=env_errors or {},
            status_code=status,
        )

    @server.custom_route("/environments", methods=["GET"])
    async def environments_index(request: Request) -> HTMLResponse:
        return await _render_environments(request)

    @server.custom_route("/environments/new", methods=["GET"])
    async def new_environment(request: Request) -> HTMLResponse:
        return _environment_form(
            request, mode="create", values={"key": "", "title": "", "enabled": "on"}, errors={}
        )

    async def _environment_create_error(
        request: Request,
        form,
        values: dict[str, str],
        errors: dict[str, str],
        return_to: str,
    ) -> Response:
        if return_to == "stay" and async_api.wants_json(request):
            message = errors.get("_form") or "保存失败"
            return async_api.fail(
                request,
                async_api.CODE_INVALID_INPUT,
                message,
                errors=errors,
            )
        if return_to == "environments":
            return await _render_environments(
                request,
                env_drawer=True,
                env_values=values,
                env_errors=errors,
                status=400,
            )
        if return_to == "targets":
            return await _render_targets(
                request,
                requested_env=str(form.get("context_env", "")),
                env_drawer=True,
                env_values=values,
                env_errors=errors,
                status=400,
            )
        return _environment_form(
            request, mode="create", values=values, errors=errors, status=400
        )

    @server.custom_route("/environments", methods=["POST"])
    async def create_environment(request: Request) -> Response:
        form = await request.form()
        values, errors = _environment_values(form)
        return_to = str(form.get("return_to", ""))
        if return_to not in {"environments", "targets", "stay"}:
            return_to = "page"
        if errors:
            return await _environment_create_error(request, form, values, errors, return_to)
        try:
            created = await store.create_environment(
                values["key"],
                values["title"],
                auth.current_actor(),
                enabled=values["enabled"] == "on",
            )
        except app_errors.EnvironmentKeyTaken as exc:
            errors["key"] = str(exc)
            return await _environment_create_error(request, form, values, errors, return_to)
        except app_errors.InvalidTarget as exc:
            errors["_form"] = str(exc)
            return await _environment_create_error(request, form, values, errors, return_to)
        if return_to == "stay" and async_api.wants_json(request):
            environments = await store.list_environments()
            return async_api.ok(
                request,
                data={
                    "environment": created.key,
                    "environments": _environment_choices(request, environments),
                },
            )
        if return_to == "environments":
            return _redirect("/environments", flash="env_created")
        return _redirect("/targets", flash="env_created", env=created.key)

    @server.custom_route("/environments/{environment_id:int}/edit", methods=["GET"])
    async def edit_environment(request: Request) -> Response:
        env = await _environment(store, request.path_params["environment_id"])
        if env is None:
            return _error(request, "环境不存在或已被删除", 404, "找不到环境")
        return _environment_form(
            request,
            mode="edit",
            values={"key": env.key, "title": env.title, "enabled": "on" if env.enabled else ""},
            errors={},
            environment=env,
        )

    @server.custom_route("/environments/{environment_id:int}", methods=["POST"])
    async def update_environment(request: Request) -> Response:
        env = await _environment(store, request.path_params["environment_id"])
        if env is None:
            return _error(request, "环境不存在或已被删除", 404, "找不到环境")
        form = await request.form()
        values, errors = _environment_values(form, existing_key=env.key)
        if errors:
            return _environment_form(
                request, mode="edit", values=values, errors=errors, environment=env, status=400
            )
        try:
            await store.update_environment(
                env.id,
                title=values["title"],
                enabled=values["enabled"] == "on",
                actor=auth.current_actor(),
            )
        except app_errors.DrPandaError as exc:
            errors["_form"] = str(exc)
            return _environment_form(
                request, mode="edit", values=values, errors=errors, environment=env, status=400
            )
        return _redirect("/environments", flash="env_updated")

    @server.custom_route("/environments/{environment_id:int}/toggle", methods=["POST"])
    async def toggle_environment(request: Request) -> Response:
        env = await _environment(store, request.path_params["environment_id"])
        if env is None:
            return _error(request, "环境不存在或已被删除", 404, "找不到环境")
        await store.update_environment(
            env.id, title=env.title, enabled=not env.enabled, actor=auth.current_actor()
        )
        return _redirect("/environments", flash="env_toggled")

    @server.custom_route("/environments/{environment_id:int}/delete", methods=["POST"])
    async def delete_environment(request: Request) -> Response:
        env = await _environment(store, request.path_params["environment_id"])
        if env is None:
            return _error(request, "环境不存在或已被删除", 404, "找不到环境")
        try:
            await store.delete_environment(env.id, auth.current_actor())
        except app_errors.EnvironmentNotEmpty as exc:
            return render.render(
                "environments.html",
                request=request,
                environments=await store.list_environments(),
                flash={"tone": "danger", "title": "还不能删除这个环境", "detail": str(exc)},
                status_code=400,
            )
        return _redirect("/environments", flash="env_deleted")

    @server.custom_route("/settings", methods=["GET"])
    async def settings_view(request: Request) -> HTMLResponse:
        current = await settings_module.load(store)
        return _settings_page(
            request,
            current,
            errors={},
            values=None,
            startup_rows=_startup_rows(runtime),
            history=await _settings_history(store),
            active_section=request.query_params.get("section", ""),
            flash=_flash(request),
            sqlite_config=runtime.config.database_url.startswith("sqlite"),
        )

    @server.custom_route("/settings", methods=["POST"])
    async def settings_save(request: Request) -> Response:
        form = await request.form()
        section = str(form.get("section", "")).strip() or request.query_params.get("section", "")
        current = await settings_module.load(store)
        values = {
            spec.key: str(form.get(spec.key, getattr(current, spec.key))).strip()
            for spec in settings_module.SETTING_SPECS
        }
        patch: dict[str, str] = {}
        errors: dict[str, str] = {}
        for key, raw in values.items():
            if key not in form:
                continue
            try:
                normalized = settings_module.validate_patch({key: raw})
            except app_errors.InvalidSettings as exc:
                errors[key] = str(exc)
            else:
                patch.update(normalized)
        if not errors:
            try:
                await settings_module.update(store, patch, auth.current_actor())
            except app_errors.InvalidSettings as exc:
                errors["_form"] = str(exc)
        if errors:
            if async_api.wants_json(request):
                return async_api.invalid_input(request, errors)
            return _settings_page(
                request,
                current,
                errors=errors,
                values=values,
                startup_rows=_startup_rows(runtime),
                history=await _settings_history(store),
                active_section=section,
                status=400,
                sqlite_config=runtime.config.database_url.startswith("sqlite"),
            )
        if async_api.wants_json(request):
            return async_api.ok(
                request,
                message="系统配置已保存",
                data={"section": section},
            )
        if section:
            return _redirect("/settings", section=section, flash="saved")
        return _redirect("/settings", flash="saved")

    @server.custom_route("/settings/reset", methods=["GET"])
    async def settings_reset_confirm(request: Request) -> HTMLResponse:
        key = request.query_params.get("key", "").strip()
        section = request.query_params.get("section", "").strip()
        if key and key not in settings_module.DEFAULTS:
            return _error(request, "未知的系统配置键", 400, "无法恢复默认值")
        specs = [settings_module.SPEC_BY_KEY[key]] if key else list(settings_module.SETTING_SPECS)
        current = await settings_module.load(store)
        return render.render(
            "settings_reset.html",
            request=request,
            key=key,
            section=section,
            specs=specs,
            current_values={spec.key: getattr(current, spec.key) for spec in specs},
        )

    @server.custom_route("/settings/reset", methods=["POST"])
    async def settings_reset(request: Request) -> Response:
        form = await request.form()
        key = str(form.get("key", "")).strip()
        section = str(form.get("section", "")).strip()
        if key and key not in settings_module.DEFAULTS:
            return _error(request, "未知的系统配置键", 400, "无法恢复默认值")
        patch = {key: settings_module.DEFAULTS[key]} if key else dict(settings_module.DEFAULTS)
        await settings_module.update(store, patch, auth.current_actor())
        if section:
            return _redirect("/settings", section=section, flash="reset")
        return _redirect("/settings", flash="reset")

    @server.custom_route("/language", methods=["POST"])
    async def set_language(request: Request) -> Response:
        form = await request.form()
        locale = i18n.normalize_locale(str(form.get("lang", "")))
        next_path = theme.safe_next(str(form.get("next", "/")))
        response = RedirectResponse(next_path, status_code=303)
        return i18n.apply_language(response, locale)

    @server.custom_route("/theme", methods=["POST"])
    async def set_theme(request: Request) -> Response:
        form = await request.form()
        mode = theme.normalize_mode(str(form.get("mode", "system")))
        if async_api.wants_json(request):
            response = async_api.ok(request, data={"mode": mode})
        else:
            next_path = theme.safe_next(str(form.get("next", "/")))
            response = RedirectResponse(next_path, status_code=303)
        return theme.apply_theme(response, mode)

    @server.custom_route("/static/app.css", methods=["GET"])
    async def app_css(request: Request) -> Response:
        return assets.css_response(request)

    @server.custom_route("/static/copy-token.js", methods=["GET"])
    async def copy_token_js(request: Request) -> Response:
        return assets.copy_js_response(request)

    @server.custom_route("/static/app.js", methods=["GET"])
    async def app_js(request: Request) -> Response:
        return assets.app_js_response(request)

    @server.custom_route("/static/icon.png", methods=["GET"])
    async def icon_png(request: Request) -> Response:
        return assets.icon_response(request)

    @server.custom_route("/favicon.ico", methods=["GET"])
    async def favicon(request: Request) -> Response:
        return assets.icon_response(request)


async def _target(store: ConfigStore, target_id: int) -> Target | None:
    return await store.get_by_id(target_id)


def _spec(target: Target) -> forms.TypeSpec:
    spec = forms.spec_for(target.type)
    if spec is None:  # pragma: no cover - 库里有未知类型属于数据损坏
        raise ValueError(f"数据库里存在未知类型 {target.type}")
    return spec


def _type_filters(
    q: str,
    active_type: str | None,
    all_views: list[views.TargetView],
    environment: str = "",
) -> list[dict]:
    counts = Counter(view.type for view in all_views)
    items = [
        {
            "type": "",
            "label": "全部",
            "count": len(all_views),
            "href": _list_href(q, None, environment),
            "active": active_type is None,
        }
    ]
    for type_, spec in forms.TYPE_SPECS.items():
        items.append(
            {
                "type": type_,
                "label": spec.label,
                "count": counts.get(type_, 0),
                "href": _list_href(q, type_, environment),
                "active": active_type == type_,
            }
        )
    return items


def _list_href(q: str, type_: str | None, environment: str = "") -> str:
    params: dict[str, str] = {}
    if environment:
        params["env"] = environment
    if q:
        params["q"] = q
    if type_:
        params["type"] = type_
    return "/targets" + (f"?{urlencode(params)}" if params else "")


def _flash(request: Request) -> dict[str, str] | None:
    code = request.query_params.get("flash", "")
    if code == "tested":
        name = request.query_params.get("name", "")
        if request.query_params.get("result") == "ok":
            return {
                "tone": "success",
                "title": "{name} 连接测试成功",
                "title_params": {"name": name},
                "detail": "",
            }
        return {
            "tone": "danger",
            "title": "{name} 连接测试失败",
            "title_params": {"name": name},
            "detail": "失败原因已记录在目标行，可展开查看。",
        }
    message = _FLASH_MESSAGES.get(code)
    if message is None:
        return None
    tone, title = message
    return {"tone": tone, "title": title, "detail": ""}


def _redirect_target(path: str, **params: str) -> str:
    if params:
        return f"{path}?{urlencode(params)}"
    return path


def _redirect(path: str, **params: str) -> RedirectResponse:
    return RedirectResponse(_redirect_target(path, **params), status_code=303)


def _probe_timeout_ms(values: dict[str, str]) -> int:
    """前端等待探测的上限：目标超时 + 10 秒余量，避免前端先于服务端超时。"""
    try:
        seconds = float(values.get("timeout_s", ""))
    except (TypeError, ValueError):
        seconds = 15.0
    seconds = min(max(seconds, 1.0), 120.0)
    return int((seconds + 10) * 1000)


async def _form_page(
    request: Request,
    spec: forms.TypeSpec,
    *,
    values: dict[str, str],
    errors: dict[str, str],
    mode: str,
    existing: Target | None,
    store: ConfigStore,
    status: int = 200,
    common_defaults: dict[str, int] | None = None,
    test_result: dict[str, object] | None = None,
) -> HTMLResponse:
    environments = await store.list_environments()
    if existing is not None:
        values["environment"] = existing.environment_key
    elif not values.get("environment") and len(environments) == 1:
        values["environment"] = environments[0].key
    return render.render(
        "form.html",
        request=request,
        mode=mode,
        spec=spec,
        existing=existing,
        values=values,
        errors=errors,
        environments=environments,
        option_rows=forms.option_rows(spec, values, errors),
        secret_rows=forms.secret_rows(spec, errors, existing),
        common_rows=forms.common_rows(values, errors, defaults=common_defaults),
        test_result=test_result,
        probe_url=(
            f"/targets/{existing.id}/probe"
            if mode == "edit" and existing is not None
            else "/targets/probe"
        ),
        probe_timeout_ms=_probe_timeout_ms(values),
        status_code=status,
    )


async def _edit_page(
    request: Request,
    target: Target,
    *,
    values: dict[str, str],
    errors: dict[str, str],
    store: ConfigStore,
    status: int = 200,
    test_result: dict[str, object] | None = None,
) -> HTMLResponse:
    spec = _spec(target)
    return await _form_page(
        request,
        spec,
        values=values,
        errors=errors,
        mode="edit",
        existing=target,
        store=store,
        status=status,
        test_result=test_result,
    )


def _bad_type(request: Request) -> Response:
    if async_api.wants_json(request):
        return async_api.fail(request, async_api.CODE_BAD_REQUEST, "未知的目标类型", status=400)
    return _error(request, "未知的目标类型", 400, "无法新建目标")


def _not_found(request: Request, message: str) -> Response:
    if async_api.wants_json(request):
        return async_api.fail(request, async_api.CODE_NOT_FOUND, message, status=404)
    return _error(request, message, 404, "找不到目标")


async def _invalid_form(
    request: Request,
    spec: forms.TypeSpec,
    *,
    values: dict[str, str],
    errors: dict[str, str],
    mode: str,
    existing: Target | None,
    store: ConfigStore,
    common_defaults: dict[str, int] | None = None,
    message: str | None = None,
) -> Response:
    """字段校验失败：JSON 内联返回错误，HTML 重渲染表单。"""
    if async_api.wants_json(request):
        field_errors = {key: value for key, value in errors.items() if key != "_form"}
        return async_api.fail(
            request,
            async_api.CODE_INVALID_INPUT,
            message or "有 {count} 处需要修改",
            status=400,
            message_params={"count": len(field_errors)},
            errors=errors or None,
            data={"count": len(field_errors)},
        )
    return await _form_page(
        request,
        spec,
        values=values,
        errors=errors,
        mode=mode,
        existing=existing,
        store=store,
        status=400,
        common_defaults=common_defaults,
    )


async def _probe_render(
    request: Request,
    spec: forms.TypeSpec,
    *,
    values: dict[str, str],
    mode: str,
    existing: Target | None,
    result: dict[str, object],
    store: ConfigStore,
    common_defaults: dict[str, int] | None = None,
    status: int = 200,
) -> Response:
    """探测结果：JSON 直接返回，HTML 重渲染表单并展示结果（不写库）。"""
    if async_api.wants_json(request):
        return _probe_json(request, result)
    return await _form_page(
        request,
        spec,
        values=values,
        errors={},
        mode=mode,
        existing=existing,
        store=store,
        status=status,
        common_defaults=common_defaults,
        test_result=_display_probe_result(result),
    )


def _display_probe_result(result: dict[str, object]) -> dict[str, object]:
    """HTML 展示时隐藏安装命令，只保留业务错误和可安装 extra。"""
    if not result.get("install_extra"):
        return result
    message, _ = views.split_install_command(str(result.get("message") or ""))
    return {**result, "message": message or result.get("message")}


def _probe_json(request: Request, result: dict[str, object]) -> Response:
    checked = result.get("checked_at_at")
    display = _display_probe_result(result)
    data = {
        "checked_at": result.get("checked_at"),
        "checked_at_instant": clock.utc_instant(checked) if isinstance(checked, datetime) else None,
        "duration_ms": result.get("duration_ms"),
    }
    if result.get("install_extra"):
        data["install_extra"] = result["install_extra"]
    if result.get("ok"):
        return async_api.ok(
            request,
            message=str(display.get("message") or "连接测试通过，可以保存。"),
            data=data,
        )
    return async_api.fail(
        request,
        async_api.CODE_PROBE_FAILED,
        str(display.get("message") or "连接测试失败"),
        status=400,
        phase="probe",
        data=data,
    )


def _stats_payload(targets) -> dict[str, int]:
    stats = views.stats(views.list_views(targets))
    return {
        "total": stats.total,
        "enabled": stats.enabled,
        "failed": stats.failed,
        "key_issues": stats.key_issues,
    }


def _row_test_payload(target: Target) -> dict[str, object]:
    view = views.to_view(target)
    return {
        "test_ok": view.last_test_ok,
        "test_time": view.last_test_at_display,
        "tested_at": clock.utc_instant(target.last_test_at),
        "test_error": view.last_test_message,
        "test_command": view.last_test_command,
    }


async def _settings_history(store) -> list[dict[str, object]]:
    changes = await store.list_settings_changes(5)
    return [
        {
            "at": change.created_at,
            "actor": change.actor,
            "summary": change.summary or "（无摘要）",
        }
        for change in changes
    ]


def _startup_rows(runtime: Runtime) -> list[dict[str, str]]:
    config = runtime.config
    scheme = config.database_url.split(":", 1)[0].split("+", 1)[0]
    db_label = {
        "sqlite": "SQLite",
        "mysql": "MySQL",
        "postgresql": "PostgreSQL",
    }.get(scheme, scheme or "未知")
    secret_source = "环境变量 DR_PANDA_SECRET_KEY" if config.secret_key_b64 else "data/secret.key"
    return [
        {"label": "监听地址", "value": f"{config.host}:{config.port}", "note": "环境变量"},
        {"label": "配置库", "value": db_label, "note": "环境变量"},
        {
            "label": "公网地址",
            "value": config.public_url or "未设置",
            "note": "仅展示",
        },
        {"label": "Cookie Secure", "value": config.cookie_secure, "note": "环境变量"},
        {
            "label": "受信 Host",
            "value": "、".join(config.trusted_hosts) or "未设置",
            "note": "环境变量",
        },
        {"label": "日志级别", "value": config.log_level, "note": "环境变量"},
        {"label": "加密密钥来源", "value": secret_source, "note": "只读"},
    ]


def _settings_page(
    request: Request,
    current: settings_module.Settings,
    *,
    errors: dict[str, str],
    values: dict[str, str] | None = None,
    startup_rows: list[dict[str, str]] | None = None,
    history: list[dict[str, str]] | None = None,
    active_section: str = "",
    flash: dict[str, str] | None = None,
    status: int = 200,
    sqlite_config: bool = False,
) -> HTMLResponse:
    groups: list[dict[str, object]] = []
    for group in settings_module.SETTING_GROUPS:
        rows = []
        for spec in settings_module.SETTING_SPECS:
            if spec.group != group["key"]:
                continue
            current_value = getattr(current, spec.key)
            values_for_key = values or {}
            rows.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "value": values_for_key.get(spec.key, str(current_value)),
                    "default": spec.default,
                    "low": spec.low,
                    "high": spec.high,
                    "unit": spec.unit,
                    "effect": spec.effect,
                    "help": spec.help,
                    "subgroup": spec.subgroup,
                    "error": errors.get(spec.key),
                }
            )
        subgroups: list[dict[str, object]] = []
        for row in rows:
            title = str(row["subgroup"] or "")
            if not subgroups or subgroups[-1]["title"] != title:
                subgroups.append({"title": title, "rows": []})
            subgroups[-1]["rows"].append(row)  # type: ignore[union-attr]
        groups.append({**group, "rows": rows, "subgroups": subgroups})
    sections: list[dict[str, str]] = [
        {
            "key": str(group["key"]),
            "title": str(group["title"]),
            "kind": "form",
            "meta": "可编辑",
        }
        for group in groups
    ]
    sections.extend(
        [
            {"key": "security", "title": "安全边界", "kind": "security", "meta": "只读"},
            {"key": "startup", "title": "启动配置", "kind": "startup", "meta": "只读"},
            {"key": "history", "title": "最近变更", "kind": "history", "meta": "只读"},
        ]
    )
    active = (
        active_section
        if any(item["key"] == active_section for item in sections)
        else sections[0]["key"]
    )
    active_group = next((group for group in groups if group["key"] == active), None)
    return render.render(
        "settings.html",
        request=request,
        sections=sections,
        groups=groups,
        active_section=active,
        active_group=active_group,
        startup_rows=startup_rows or [],
        history=history or [],
        errors=errors,
        flash=flash,
        sqlite_config=sqlite_config,
        status_code=status,
    )


def _draft_target(draft, existing: Target | None) -> Target:
    now = datetime.now(UTC)
    secret = dict(existing.secret) if existing else {}
    secret.update(draft.secret_patch.set)
    for key in draft.secret_patch.clear:
        secret.pop(key, None)
    return Target(
        id=existing.id if existing else 0,
        type=draft.type,
        name=draft.name,
        enabled=draft.enabled,
        options=dict(draft.options),
        secret=secret,
        secret_fields=frozenset(secret),
        secret_ok=True,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        last_test_at=existing.last_test_at if existing else None,
        last_test_ok=existing.last_test_ok if existing else None,
        last_test_error=existing.last_test_error if existing else None,
        operator_notes=draft.operator_notes,
    )


def _checked_now() -> dict[str, object]:
    now = datetime.now(UTC)
    return {"checked_at": clock.utc_text(now, seconds=True), "checked_at_at": now}


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _probe_failure(
    started: float, exc: Exception, target: Target, *, unexpected: bool = False
) -> dict[str, object]:
    if unexpected:
        message = redact(f"未预期错误：{exc}", target.secret.values())
        code = None
    else:
        message = redact(str(exc), target.secret.values())
        code = getattr(exc, "code", None)
    return {
        "ok": False,
        "message": message,
        "code": code,
        "install_extra": views.probe_install_extra(target.type, message),
        **_checked_now(),
        "duration_ms": _elapsed_ms(started),
    }


async def _test_draft_target(draft, existing: Target | None) -> dict[str, object]:
    """用草稿配置真实探测一次；不写库、不记录审计。"""
    started = time.monotonic()
    target = _draft_target(draft, existing)
    connector = get_connector(draft.type)
    try:
        require(connector.probe_guard())
        client = connector.create_client(target)
    except app_errors.DrPandaError as exc:
        return _probe_failure(started, exc, target)
    except Exception as exc:
        logger.warning("草稿目标测试连接失败：%s", target.type, exc_info=True)
        return _probe_failure(started, exc, target, unexpected=True)
    try:
        await connector_base.run_with_timeout(
            connector.probe(client, target),
            connector_base.timeout_seconds(target),
        )
    except app_errors.DrPandaError as exc:
        return _probe_failure(started, exc, target)
    except Exception as exc:
        logger.warning("草稿目标测试连接失败：%s", target.type, exc_info=True)
        return _probe_failure(started, exc, target, unexpected=True)
    finally:
        try:
            await connector.close_client(client)
        except Exception:
            logger.warning("关闭草稿测试连接失败", exc_info=True)
    return {
        "ok": True,
        "message": "连接测试通过，可以保存。",
        "code": None,
        **_checked_now(),
        "duration_ms": _elapsed_ms(started),
    }


def _current_environment(environments: list, requested: str):
    key = (requested or "").strip()
    if key:
        match = next((item for item in environments if item.key == key), None)
        if match is not None:
            return match
    return environments[0] if environments else None


def _query_env(request: Request) -> str:
    return request.query_params.get("env", "").strip()


async def _selected_environment(store: ConfigStore, request: Request) -> str:
    environments = await store.list_environments()
    current = _current_environment(environments, _query_env(request))
    return current.key if current is not None else ""


async def _targets_in_environment(store: ConfigStore, key: str) -> list[Target]:
    targets = await store.list_all()
    return [target for target in targets if target.environment_key == key]


async def _environment(store: ConfigStore, environment_id: int):
    environments = await store.list_environments()
    return next((item for item in environments if item.id == environment_id), None)


_ENV_KEY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


def _environment_choices(request: Request, environments) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    for item in environments:
        title = item.title
        if item.key == "default" and item.title == "默认":
            title = async_api.translate(request, "默认")
        choices.append({"key": item.key, "label": f"{title} · {item.key}"})
    return choices


def _environment_values(form, *, existing_key: str = "") -> tuple[dict[str, str], dict[str, str]]:
    title = " ".join(str(form.get("title", "")).split())
    key = existing_key or str(form.get("key", "")).strip()
    enabled = "on" if form.get("enabled") else ""
    values = {"title": title, "key": key, "enabled": enabled}
    errors: dict[str, str] = {}
    if not title:
        errors["title"] = "展示名不能为空"
    elif len(title) > 64:
        errors["title"] = "展示名最长 64 个字符"
    if not existing_key:
        if not key:
            errors["key"] = "调用标识不能为空"
        elif not _ENV_KEY_RE.match(key):
            errors["key"] = "调用标识只允许小写字母、数字与连字符，以字母或数字开头结尾，最长 64"
    return values, errors


def _environment_form(
    request: Request,
    *,
    mode: str,
    values: dict[str, str],
    errors: dict[str, str],
    environment=None,
    status: int = 200,
) -> HTMLResponse:
    return render.render(
        "environment_form.html",
        request=request,
        mode=mode,
        values=values,
        errors=errors,
        environment=environment,
        status_code=status,
    )


def _error(request: Request, message: str, status: int, title: str | None = None) -> HTMLResponse:
    return render.render(
        "error.html",
        request=request,
        message=message,
        code=status,
        status_code=status,
        title=title or ("页面不存在" if status == 404 else "请求有误"),
    )
