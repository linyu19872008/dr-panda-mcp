"""网页表单：字段定义、初值、解析与校验（planning 4.2 / 第 7 章）。"""

from __future__ import annotations

import re
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dr_panda_mcp.store.protocol import SecretPatch, Target, TargetDraft

# Tencent CLS LogsetId / TopicId are UUIDs; friendly names must not be registered.
_CLS_TOPIC_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

NAME_PATTERN_HINT = "只允许小写字母、数字与连字符，以字母或数字开头结尾，最长 64"

COMMON_FIELDS = (
    ("timeout_s", "超时（秒）", 15, (1, 120)),
    ("max_rows", "单次行数上限", 100, (1, 1000)),
    ("max_bytes", "单次字节上限", 102_400, (4096, 1_048_576)),
)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str  # text | int | bool | list | select
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] = ()
    help: str = ""


@dataclass(frozen=True)
class SecretField:
    key: str
    label: str
    required: bool = False
    help: str = ""
    pem: bool = False


@dataclass(frozen=True)
class TypeSpec:
    type: str
    label: str
    options: tuple[Field, ...]
    secrets: tuple[SecretField, ...]
    note: str = ""


TYPE_SPECS: dict[str, TypeSpec] = {
    "mysql": TypeSpec(
        "mysql",
        "MySQL",
        (
            Field("host", "主机", "text", required=True),
            Field("port", "端口", "int", default=3306),
            Field("user", "用户", "text", required=True),
            Field("default_db", "默认库", "text", required=True),
            Field("allowed_dbs", "允许的库（一行一个，空=只允许默认库）", "list"),
            Field("ssl", "启用 SSL", "bool", default=False),
            Field(
                "ca_pem",
                "CA 证书 PEM（可选，私有 CA 时填写）",
                "pem",
                help="粘贴 PEM 证书；配置后必须启用 SSL。",
            ),
            Field(
                "allow_processlist",
                "允许 PROCESSLIST（风险）",
                "bool",
                default=False,
                help="默认关闭；开启后 PROCESSLIST 可看到实例内其他库/用户的会话与 SQL。",
            ),
        ),
        (
            SecretField("password", "密码", required=True),
            SecretField(
                "client_cert",
                "客户端证书 PEM（可选）",
                pem=True,
                help="需要和私钥一起填写。",
            ),
            SecretField(
                "client_key",
                "客户端私钥 PEM（可选）",
                pem=True,
                help="不支持带口令的私钥。",
            ),
        ),
        "只会执行单条查询，连接是只读的。",
    ),
    "mongo": TypeSpec(
        "mongo",
        "Mongo",
        (
            Field(
                "auth_mode",
                "认证方式",
                "select",
                required=True,
                default="none",
                choices=("none", "password", "uri"),
                help="none=无认证；password=用户名密码；uri=完整连接串（SRV/X.509/TLS 等高级选项）。",
            ),
            Field("host", "主机", "text"),
            Field("port", "端口", "int", default=27017),
            Field("user", "用户", "text"),
            Field("auth_source", "认证库", "text", default="admin"),
            Field("tls", "启用 TLS", "bool", default=False),
            Field(
                "ca_pem",
                "CA 证书 PEM（可选，私有 CA 时填写）",
                "pem",
                help="配置后必须启用 TLS。",
            ),
            Field("allowed_dbs", "允许的库（一行一个，必须显式列）", "list", required=True),
        ),
        (
            SecretField(
                "uri",
                "连接 URI（auth_mode=uri 时必填，含凭证）",
                help="完整 mongodb:// 或 mongodb+srv:// URI；凭证里未转义的 @、:、% 会自动做 URL 编码；含凭证，加密保存。",
            ),
            SecretField("password", "密码（auth_mode=password 时必填）"),
            SecretField(
                "client_cert",
                "客户端证书 PEM（可选）",
                pem=True,
                help="需要和私钥一起填写。",
            ),
            SecretField(
                "client_key",
                "客户端私钥 PEM（可选）",
                pem=True,
                help="不支持带口令的私钥。",
            ),
        ),
        "只会做带条件的读取。",
    ),
    "elasticsearch": TypeSpec(
        "elasticsearch",
        "Elasticsearch",
        (
            Field("hosts", "地址列表（一行一个）", "list", required=True),
            Field("username", "用户名", "text"),
            Field("allowed_indices", "允许的索引（一行一个）", "list", required=True),
            Field("verify_tls", "校验 TLS", "bool", default=True),
            Field(
                "ca_pem",
                "CA 证书 PEM（可选，私有 CA 时填写）",
                "pem",
                help="粘贴 PEM 证书；配置后必须保持 TLS 校验开启。",
            ),
        ),
        (
            SecretField("password", "密码"),
            SecretField("api_key", "API Key（与用户名密码二选一）"),
            SecretField(
                "client_cert",
                "客户端证书 PEM（可选）",
                pem=True,
                help="需要和私钥一起填写。",
            ),
            SecretField(
                "client_key",
                "客户端私钥 PEM（可选）",
                pem=True,
                help="不支持带口令的私钥。",
            ),
        ),
        "只会查询，不会执行脚本。",
    ),
    "redis": TypeSpec(
        "redis",
        "Redis",
        (
            Field("host", "主机", "text", required=True),
            Field("port", "端口", "int", default=6379),
            Field("db", "DB", "int", default=0),
            Field(
                "protocol",
                "协议版本（RESP）",
                "select",
                default="2",
                choices=("2", "3"),
                help="默认 2（RESP2），兼容 Redis < 6.0 与 Codis/Twemproxy 等代理；仅当服务端 Redis ≥ 6.0 且确需 RESP3 时改为 3。",
            ),
            Field("username", "ACL 用户名（可选）", "text"),
            Field("tls", "启用 TLS", "bool", default=False),
            Field(
                "ca_pem",
                "CA 证书 PEM（可选，私有 CA 时填写）",
                "pem",
                help="配置后必须启用 TLS。",
            ),
            Field("key_prefix", "key 前缀（空=不限）", "text"),
        ),
        (
            SecretField("password", "密码"),
            SecretField(
                "client_cert",
                "客户端证书 PEM（可选）",
                pem=True,
                help="需要和私钥一起填写。",
            ),
            SecretField(
                "client_key",
                "客户端私钥 PEM（可选）",
                pem=True,
                help="不支持带口令的私钥。",
            ),
        ),
        "只会执行允许的读命令。",
    ),
    "gitlab": TypeSpec(
        "gitlab",
        "GitLab",
        (
            Field("base_url", "实例地址", "text", required=True),
            Field("allowed_projects", "允许的项目（一行一个）", "list", required=True),
        ),
        (SecretField("token", "私人 Token", required=True),),
        "只会读取代码，不会写入。",
    ),
    "rabbitmq": TypeSpec(
        "rabbitmq",
        "RabbitMQ",
        (
            Field("management_url", "Management 地址", "text", required=True),
            Field("user", "用户", "text", required=True),
            Field("allowed_vhosts", "允许的 vhost（一行一个）", "list", required=True),
        ),
        (SecretField("password", "密码", required=True),),
        "只查看队列，不取消息。",
    ),
    "kafka": TypeSpec(
        "kafka",
        "Kafka",
        (
            Field("bootstrap_servers", "bootstrap 地址（一行一个）", "list", required=True),
            Field(
                "security_protocol",
                "安全协议",
                "select",
                default="PLAINTEXT",
                choices=("PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"),
            ),
            Field(
                "sasl_mechanism",
                "SASL 机制",
                "select",
                default="PLAIN",
                choices=("PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"),
            ),
            Field("sasl_user", "SASL 用户", "text"),
            Field(
                "ca_pem",
                "CA 证书 PEM（可选，私有 CA 时填写）",
                "pem",
                help="仅 SSL / SASL_SSL 可用。",
            ),
            Field("allowed_topics", "允许的 topic（一行一个）", "list", required=True),
        ),
        (
            SecretField("sasl_password", "SASL 密码"),
            SecretField(
                "client_cert",
                "客户端证书 PEM（可选）",
                pem=True,
                help="需要和私钥一起填写。",
            ),
            SecretField(
                "client_key",
                "客户端私钥 PEM（可选）",
                pem=True,
                help="不支持带口令的私钥。",
            ),
        ),
        "只查看堆积和有限消息，不加入消费组。",
    ),
    "nacos": TypeSpec(
        "nacos",
        "Nacos",
        (
            Field(
                "base_url",
                "Nacos 地址",
                "text",
                required=True,
                help="例如 http://nacos-host:8848；代码会自动补 /nacos。",
            ),
            Field("username", "用户名（可选）", "text"),
            Field(
                "api_version",
                "Nacos API 版本",
                "select",
                default="auto",
                choices=("auto", "v1", "v3"),
                help="auto=自动探测；v1=1.x/2.x OpenAPI；v3=3.x client API。",
            ),
            Field(
                "allowed_namespaces",
                "允许的命名空间（一行一个，public=默认）",
                "list",
                required=True,
            ),
            Field("allowed_groups", "允许的 group（一行一个）", "list", required=True),
            Field(
                "allowed_data_ids",
                "允许的 dataId（一行一个，空=拒绝配置读取）",
                "list",
            ),
            Field(
                "allowed_services",
                "允许的服务名（一行一个，空=拒绝服务读取）",
                "list",
            ),
            Field("verify_tls", "校验 TLS", "bool", default=True),
            Field(
                "ca_pem",
                "CA 证书 PEM（可选，私有 CA 时填写）",
                "pem",
                help="配置后必须保持 TLS 校验开启。",
            ),
        ),
        (SecretField("password", "密码（配置用户名时必填）"),),
        "只读取配置与服务；配置内容可能包含敏感值。",
    ),
    "cls": TypeSpec(
        "cls",
        "CLS",
        (
            Field("region", "地域", "text", required=True, help="例如 ap-shanghai；腾讯云地域通常以 ap- 开头。"),
            Field(
                "allowed_topics",
                "允许的日志主题（一行一个）",
                "list",
                required=True,
                help="格式：日志集ID/日志主题ID（均为控制台 UUID，不是主题名称）。",
            ),
            Field("default_window_minutes", "默认时间窗（分钟）", "int", default=60),
            Field("max_window_minutes", "最大时间窗（分钟）", "int", default=1440),
        ),
        (
            SecretField("secret_id", "SecretId", required=True),
            SecretField("secret_key", "SecretKey", required=True),
        ),
        "搜索必须带时间范围；探活会对每个授权主题做一次轻量 SearchLog。",
    ),
}

TYPE_ORDER = tuple(TYPE_SPECS)


def spec_for(type_: str) -> TypeSpec | None:
    return TYPE_SPECS.get(type_)


def type_options() -> list[tuple[str, str]]:
    return [(spec.type, spec.label) for spec in TYPE_SPECS.values()]


def type_cards() -> list[dict[str, str]]:
    return [
        {"type": spec.type, "label": spec.label, "note": spec.note}
        for spec in TYPE_SPECS.values()
    ]


def initial_values(
    spec: TypeSpec,
    target: Target | None = None,
    *,
    defaults: Mapping[str, int] | None = None,
) -> dict[str, str]:
    """新建用默认值；编辑用库里的 options。

    ``defaults`` 可覆盖全局的新建目标默认值；既有 target 仍以自己的 options 为准。
    """
    values: dict[str, str] = {
        "name": target.name if target else "",
        "enabled": "on" if (target is None or target.enabled) else "",
    }
    options = target.options if target else {}
    if spec.type == "mongo" and target is not None and "auth_mode" not in options:
        options = dict(options)
        options["auth_mode"] = _infer_mongo_auth_mode(target)
    for field in spec.options:
        current = options.get(field.key, field.default)
        values[field.key] = _as_text(field, current)
    for key, _label, default, _ranges in COMMON_FIELDS:
        configured = defaults.get(key, default) if defaults else default
        values[key] = str(options.get(key, configured))
    return values


def parse_form(
    form: Mapping[str, Any],
    *,
    spec: TypeSpec,
    mode: str,
    existing: Target | None = None,
    defaults: Mapping[str, int] | None = None,
    environments: list[Any] | None = None,
) -> tuple[TargetDraft | None, dict[str, str], dict[str, str]]:
    """解析并校验表单。返回 ``(draft, errors, values)``；有错误时 draft 为 None。"""
    errors: dict[str, str] = {}
    values = initial_values(spec, existing, defaults=defaults)

    name = existing.name if existing else _text(form, "name")
    values["name"] = name
    values["enabled"] = "on" if _checked(form, "enabled") else ""
    if not existing and not name:
        errors["name"] = "名称不能为空"
    environment_key = _environment_key(form, existing, environments or [], errors)
    values["environment"] = environment_key

    options: dict[str, Any] = {}
    for field in spec.options:
        raw = _raw(form, field.key)
        values[field.key] = raw if field.kind != "bool" else ("on" if _checked(form, field.key) else "")
        parsed, error = _parse_field(field, raw, form)
        if error:
            errors[field.key] = error
        elif parsed is not None:
            options[field.key] = parsed

    for key, _label, default, (low, high) in COMMON_FIELDS:
        raw = _raw(form, key)
        values[key] = raw
        configured = defaults.get(key, default) if defaults else default
        parsed, error = _parse_int(raw, low, high)
        if error:
            errors[key] = f"{key} 必须是 {low}–{high} 的整数"
        else:
            options[key] = parsed if parsed is not None else configured

    secrets_set: dict[str, str] = {}
    secrets_clear: set[str] = set()
    for secret in spec.secrets:
        raw = _raw(form, f"secret_{secret.key}").strip()
        if raw:
            secrets_set[secret.key] = raw
        elif _checked(form, f"clear_{secret.key}"):
            secrets_clear.add(secret.key)
            if secret.required:
                errors[f"secret_{secret.key}"] = f"{secret.label}不能为空"
        elif secret.required:
            present = bool(existing and secret.key in existing.secret_fields)
            if not present:
                errors[f"secret_{secret.key}"] = f"{secret.label}不能为空"

    _cross_validate(spec, options, secrets_set, secrets_clear, existing, errors, form)

    if errors:
        return None, errors, values

    draft = TargetDraft(
        name=name,
        type=spec.type,
        enabled=values["enabled"] == "on",
        options=options,
        secret_patch=SecretPatch(set=secrets_set, clear=frozenset(secrets_clear)),
        environment_key=environment_key,
    )
    return draft, {}, values


def _environment_key(
    form: Mapping[str, Any],
    existing: Target | None,
    environments: list[Any],
    errors: dict[str, str],
) -> str:
    """新建时选定环境；编辑时环境不可改。只有一个环境时可以不提交。"""
    if existing is not None:
        submitted = _text(form, "environment")
        if submitted and submitted != existing.environment_key:
            errors["environment"] = "环境创建后不可修改"
        return existing.environment_key
    keys = [str(getattr(item, "key", "")) for item in environments]
    chosen = _text(form, "environment")
    if not chosen and len(keys) == 1:
        chosen = keys[0]
    if keys and chosen not in keys or not chosen and len(keys) > 1:
        errors["environment"] = "请选择环境"
    return chosen


def _cross_validate(
    spec: TypeSpec,
    options: Mapping[str, Any],
    secrets_set: Mapping[str, str],
    secrets_clear: set[str],
    existing: Target | None,
    errors: dict[str, str],
    form: Mapping[str, Any],
) -> None:
    if spec.type == "mongo":
        _validate_mongo_auth(
            options, secrets_set, secrets_clear, existing, errors
        )
    if spec.type == "elasticsearch":
        password = secrets_set.get("password") or (
            existing and "password" in existing.secret_fields and "password" not in secrets_clear
        )
        api_key = secrets_set.get("api_key") or (
            existing and "api_key" in existing.secret_fields and "api_key" not in secrets_clear
        )
        has_user_auth = bool(options.get("username")) and bool(password)
        if has_user_auth == bool(api_key):
            errors["_form"] = "Elasticsearch 需要「用户名 + 密码」或 API Key，二选一"
    if spec.type in {"mysql", "elasticsearch", "mongo", "redis", "kafka"}:
        cert = _secret_present(existing, secrets_set, secrets_clear, "client_cert")
        key = _secret_present(existing, secrets_set, secrets_clear, "client_key")
        if cert != key:
            errors["_form"] = "客户端证书与私钥必须同时提供或同时清除"
        elif cert:
            if spec.type == "mysql" and not options.get("ssl"):
                errors["ssl"] = "配置客户端证书时必须启用 SSL"
            if spec.type == "elasticsearch" and not options.get("verify_tls"):
                errors["verify_tls"] = "配置客户端证书时必须保持 TLS 校验开启"
            if spec.type == "mongo" and not options.get("tls"):
                errors["tls"] = "配置客户端证书时必须启用 TLS"
            if spec.type == "redis" and not options.get("tls"):
                errors["tls"] = "配置客户端证书时必须启用 TLS"
            if spec.type == "kafka" and options.get("security_protocol") not in {"SSL", "SASL_SSL"}:
                errors["_form"] = "配置客户端证书时 security_protocol 必须是 SSL 或 SASL_SSL"
    if spec.type == "mongo" and options.get("ca_pem") and not options.get("tls"):
        errors["tls"] = "配置 CA 证书时必须启用 TLS"
    if spec.type == "redis" and options.get("ca_pem") and not options.get("tls"):
        errors["tls"] = "配置 CA 证书时必须启用 TLS"
    if spec.type == "kafka" and options.get("ca_pem") and options.get("security_protocol") not in {"SSL", "SASL_SSL"}:
        errors["_form"] = "配置 CA 证书时 security_protocol 必须是 SSL 或 SASL_SSL"
    if spec.type == "mysql" and options.get("ca_pem") and not options.get("ssl"):
        errors["ssl"] = "配置 CA 证书时必须启用 SSL"
    if spec.type == "elasticsearch" and options.get("ca_pem") and not options.get("verify_tls"):
        errors["verify_tls"] = "配置 CA 证书时必须保持 TLS 校验开启"
    if spec.type == "redis":
        username = str(options.get("username") or "").strip()
        if username and not _secret_present(
            existing, secrets_set, secrets_clear, "password"
        ):
            errors["secret_password"] = "配置 ACL 用户名时必须填写密码"
    if spec.type == "kafka":
        protocol = str(options.get("security_protocol", "PLAINTEXT"))
        mechanism = str(options.get("sasl_mechanism") or "").strip()
        if protocol.startswith("SASL"):
            if mechanism not in {"PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"}:
                errors["sasl_mechanism"] = "SASL 机制必须是 PLAIN / SCRAM-SHA-256 / SCRAM-SHA-512"
            if not options.get("sasl_user"):
                errors["sasl_user"] = "SASL 协议需要填写 SASL 用户"
            if not _secret_present(existing, secrets_set, secrets_clear, "sasl_password"):
                errors["secret_sasl_password"] = "SASL 协议需要填写 SASL 密码"
        else:
            if mechanism and mechanism != "PLAIN":
                errors["sasl_mechanism"] = "非 SASL 协议不应填写 SASL 机制"
            if options.get("sasl_user") or _secret_present(
                existing, secrets_set, secrets_clear, "sasl_password"
            ):
                errors["_form"] = "非 SASL 协议不应填写 SASL 用户或密码"
    if spec.type == "cls":
        default_window = options.get("default_window_minutes")
        max_window = options.get("max_window_minutes")
        if isinstance(default_window, int) and isinstance(max_window, int):
            if default_window > max_window:
                errors["default_window_minutes"] = "默认时间窗不能大于最大时间窗"
            if not 1 <= max_window <= 1440:
                errors["max_window_minutes"] = "最大时间窗必须在 1–1440 分钟"
        topics = options.get("allowed_topics") or []
        if isinstance(topics, list) and any(
            not _CLS_TOPIC_RE.match(str(item).strip()) for item in topics
        ):
            errors["allowed_topics"] = (
                "每行须为「日志集ID/日志主题ID」UUID（控制台复制），不能使用主题名称。"
            )


    if spec.type == "nacos":
        namespaces = options.get("allowed_namespaces") or []
        groups = options.get("allowed_groups") or []
        if not namespaces:
            errors["allowed_namespaces"] = "至少填写一个允许的命名空间"
        if not groups:
            errors["allowed_groups"] = "至少填写一个允许的 group"
        username = str(options.get("username") or "").strip()
        password = _secret_present(existing, secrets_set, secrets_clear, "password")
        if username and not password:
            errors["secret_password"] = "配置用户名时必须填写密码"
        if password and not username:
            errors["username"] = "配置密码时必须填写用户名"
        if options.get("ca_pem") and not options.get("verify_tls"):
            errors["verify_tls"] = "配置 CA 证书时必须保持 TLS 校验开启"

def _infer_mongo_auth_mode(target: Target) -> str:
    if target.secret.get("uri") or "uri" in target.secret_fields:
        return "uri"
    if target.options.get("user") or "password" in target.secret_fields:
        return "password"
    return "none"


def _validate_mongo_auth(
    options: Mapping[str, Any],
    secrets_set: Mapping[str, str],
    secrets_clear: set[str],
    existing: Target | None,
    errors: dict[str, str],
) -> None:
    mode = str(options.get("auth_mode") or "none")
    has_uri = _secret_present(existing, secrets_set, secrets_clear, "uri")
    has_password = _secret_present(existing, secrets_set, secrets_clear, "password")
    user = str(options.get("user") or "").strip()
    host = str(options.get("host") or "").strip()

    if mode == "none":
        if has_uri or user or has_password:
            errors["_form"] = "auth_mode=none 时不能填写 URI、用户或密码"
        if not host:
            errors["host"] = "无认证模式需要填写主机"
    elif mode == "password":
        if has_uri:
            errors["_form"] = "auth_mode=password 时不能填写连接 URI"
        if not host:
            errors["host"] = "密码模式需要填写主机"
        if not user:
            errors["user"] = "密码模式需要填写用户"
        if not has_password:
            errors["secret_password"] = "密码模式需要填写密码"
    elif mode == "uri":
        if not has_uri:
            errors["secret_uri"] = "URI 模式需要填写连接 URI"
        if host or user or has_password:
            errors["_form"] = "auth_mode=uri 时 host、用户、密码必须留空"


def _secret_present(
    existing: Target | None,
    secrets_set: Mapping[str, str],
    secrets_clear: set[str],
    key: str,
) -> bool:
    if secrets_set.get(key):
        return True
    return bool(
        existing
        and key in existing.secret_fields
        and key not in secrets_clear
    )


def _parse_field(field: Field, raw: str, form: Mapping[str, Any]) -> tuple[Any, str | None]:
    if field.kind == "int":
        parsed, error = _parse_int(raw, 1, 65535) if "port" in field.key else _parse_int(raw, 0, 1_000_000)
        if error:
            return None, f"{field.label}必须是整数"
        return (parsed if parsed is not None else field.default), None
    if field.kind == "bool":
        return _checked(form, field.key), None
    if field.kind == "pem":
        value = raw.strip()
        if not value:
            return None, None
        if len(value) > 65_536:
            return None, "CA 证书不能超过 64KB"
        try:
            ssl.create_default_context(cadata=value)
        except ssl.SSLError:
            return None, "CA 证书不是合法 PEM"
        return value, None
    if field.kind == "list":
        items = [line.strip() for line in raw.splitlines() if line.strip()]
        return list(dict.fromkeys(items)), None
    if field.kind == "select":
        value = raw.strip() or field.default
        if field.choices and value not in field.choices:
            return None, f"{field.label}必须是 {', '.join(field.choices)} 之一"
        return value, None
    value = raw.strip()
    if field.required and not value:
        return None, f"{field.label}不能为空"
    return (value or None), None


def _parse_int(raw: str, low: int, high: int) -> tuple[int | None, str | None]:
    if not raw or not str(raw).strip():
        return None, None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None, "不是整数"
    if not low <= value <= high:
        return None, "超出范围"
    return value, None


def _raw(form: Mapping[str, Any], key: str) -> str:
    value = form.get(key)
    return "" if value is None else str(value)


def _text(form: Mapping[str, Any], key: str) -> str:
    return _raw(form, key).strip()


def _checked(form: Mapping[str, Any], key: str) -> bool:
    return form.get(key) is not None


def _as_text(field: Field, value: Any) -> str:
    if value is None:
        return ""
    if field.kind == "bool":
        return "on" if value else ""
    if field.kind == "list":
        if isinstance(value, (list, tuple)):
            return "\n".join(str(item) for item in value)
        return str(value)
    return str(value)


ADVANCED_OPTION_KEYS = frozenset(
    {
        "ssl",
        "tls",
        "verify_tls",
        "ca_pem",
        "allow_processlist",
        "default_window_minutes",
        "max_window_minutes",
    }
)
ADVANCED_SECRET_KEYS = frozenset({"client_cert", "client_key"})
CONNECTION_LIST_KEYS = frozenset({"hosts", "bootstrap_servers"})
SCOPE_KEYS = frozenset({"key_prefix"})


def option_rows(
    spec: TypeSpec,
    values: Mapping[str, str],
    errors: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows = []
    for field in spec.options:
        section = (
            "advanced"
            if field.key in ADVANCED_OPTION_KEYS
            else "connection"
            if field.kind == "list" and field.key in CONNECTION_LIST_KEYS
            else "scope"
            if field.kind == "list" or field.key in SCOPE_KEYS
            else "connection"
        )
        rows.append(
            {
                "key": field.key,
                "label": field.label,
                "kind": field.kind,
                "value": values.get(field.key, ""),
                "error": errors.get(field.key),
                "choices": field.choices,
                "required": field.required,
                "help": field.help,
                "section": section,
                # 授权范围、风险开关和时间窗不影响连通性。
                "gate": field.key not in PROBE_SKIP_OPTION_KEYS and section != "scope",
            }
        )
    return rows


def secret_rows(
    spec: TypeSpec,
    errors: Mapping[str, str],
    existing: Target | None,
) -> list[dict[str, Any]]:
    rows = []
    for secret in spec.secrets:
        has_value = bool(existing and secret.key in existing.secret_fields)
        rows.append(
            {
                "key": secret.key,
                "label": secret.label,
                "required": secret.required,
                "has_value": has_value,
                "pem": secret.pem,
                "error": errors.get(f"secret_{secret.key}"),
                "help": secret.help,
                "section": (
                    "advanced" if secret.key in ADVANCED_SECRET_KEYS else "connection"
                ),
            }
        )
    return rows


# 这些字段不决定能不能连上。保存时若只有它们变化，不再打上游。
PROBE_SKIP_OPTION_KEYS = frozenset(
    {
        "allow_processlist",
        "default_window_minutes",
        "max_window_minutes",
        "max_rows",
        "max_bytes",
        "allowed_dbs",
        "allowed_indices",
        "allowed_projects",
        "allowed_vhosts",
        "allowed_topics",
        "key_prefix",
    }
)


def _option_eq(left: Any, right: Any) -> bool:
    if left == right:
        return True
    empty = (None, False, "", [], ())
    if left in empty and right in empty:
        return True
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return list(left) == list(right)
    return False


def connection_changed(existing: Target, draft: TargetDraft) -> bool:
    """主机、账号、密钥、TLS、超时等相对已保存值是否变化。"""
    if not draft.secret_patch.is_empty():
        return True
    keys = set(existing.options) | set(draft.options)
    for key in keys:
        if key in PROBE_SKIP_OPTION_KEYS:
            continue
        if not _option_eq(existing.options.get(key), draft.options.get(key)):
            return True
    return False


COMMON_UNITS = {"timeout_s": "秒", "max_rows": "行", "max_bytes": "字节"}


def common_rows(
    values: Mapping[str, str],
    errors: Mapping[str, str],
    *,
    defaults: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": label,
            "value": values.get(key, str((defaults or {}).get(key, default))),
            "error": errors.get(key),
            "help": f"默认 {(defaults or {}).get(key, default)}；范围 {low}–{high}",
            "default": (defaults or {}).get(key, default),
            "low": low,
            "high": high,
            "unit": COMMON_UNITS[key],
            "gate": key not in PROBE_SKIP_OPTION_KEYS,
        }
        for key, label, default, (low, high) in COMMON_FIELDS
    ]
