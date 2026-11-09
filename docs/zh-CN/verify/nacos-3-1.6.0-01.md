# Nacos 3.x 只读支持 1.6.0 · 验证记录

## 支持范围

| Nacos 版本 | API | 状态 |
|---|---|---|
| 1.4.2 | v1 OpenAPI | 支持 |
| 2.2.3 | v1 OpenAPI | 支持 |
| 3.0.2 | v3 client/API | 支持 |

目标配置新增：

```text
api_version = auto | v1 | v3
```

默认 `auto`：

- v1 liveness 返回 200 → v1；
- v1 liveness 返回 410 → v3。

## Nacos 3.0.2 验证

Docker：

```text
nacos/nacos-server:v3.0.2
standalone
NACOS_AUTH_ENABLE=true
```

验证：

- v3 登录 `/nacos/v3/auth/user/login` 成功；
- 连接器自动识别为 v3；
- 配置详情通过 `/nacos/v3/client/cs/config` 读取；
- 配置列表通过 `allowed_data_ids` 逐个查询，不使用 Admin API；
- 服务列表通过 `allowed_services` scope 生成，不要求管理员权限；
- 实例列表通过 `/nacos/v3/client/ns/instance/list` 读取；
- 认证失败仍映射为 `UPSTREAM_AUTH_ERROR`。

## Nacos 2.2.3 回归

同一套连接器在 Nacos 2.2.3 + 认证下：

- 自动识别为 v1；
- 配置列表和配置内容读取通过；
- 原有工具行为不变。

## 安全边界

- 只允许 GET；
- 不使用 v3 `/v3/admin/*` 配置/服务列表；
- 不依赖 v1 兼容开关；
- `allowed_data_ids` / `allowed_services` 仍是显式 allowlist。

## 测试

- `pytest -q`：**600 passed**；
- `ruff check .`：通过；
- `node --check app.js`：通过；
- `bash -n setup.sh`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.6.0` sdist/wheel。

## 边界

- v3 配置列表没有等价 OpenAPI，返回的是 allowlist 内 dataId，不保证与 Nacos 全量配置列表一致；
- v3 服务列表同样是 scope 派生；需要“发现全部服务”时应另加显式管理员能力；
- Nacos 3.x 原生 TLS 组合仍需按部署方式单独验证。
