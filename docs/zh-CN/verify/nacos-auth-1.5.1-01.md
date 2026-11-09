# Nacos 认证与版本兼容验证 1.5.1 · 验证记录

## 验证矩阵

| 项 | 结果 |
|---|---|
| Nacos 2.2.3 + 默认 admin | 通过 |
| 自定义用户 / 自定义角色 | 通过 |
| namespace/group ACL | 通过；授权 group 可读，非授权 group 403 |
| accessToken 短 TTL 刷新 | 发现并修复缓存超过 TTL 的问题 |
| Nacos 1.4.2 + 认证 | 通过 |
| Nacos 3.0.2 | 不兼容，见下 |
| TLS 终止 + 认证 | 通过（TLS 前端代理） |

## 自定义用户与 ACL

Nacos 2.2.3 开启：

```text
NACOS_AUTH_ENABLE=true
NACOS_AUTH_TOKEN=<base64>
NACOS_AUTH_IDENTITY_KEY=nacos
NACOS_AUTH_IDENTITY_VALUE=nacos
```

创建自定义用户 `reader6`、角色 `reader6-role`，授予：

```text
resource=nsA:groupA:*
action=r
```

结果：

- `reader6` 可读取 `nsA/groupA` 下配置；
- 读取 `nsA/groupB` 返回 403 `authorization failed!`；
- 默认 admin 不受该限制。

DrPanda 连接器使用自定义用户密码登录成功；`allowed_data_ids` 继续在 MCP 层做 dataId 白名单过滤。Nacos 2.2.3 的内置 ACL 在本次试验中稳定按 namespace/group 生效；精确 dataId resource 形式没有按预期生效，dataId 粒度由 DrPanda scope 约束。

## accessToken 过期刷新

使用：

```text
NACOS_AUTH_TOKEN_EXPIRE_SECONDS=15
```

首次登录后连接器缓存 token。原实现使用 `max(30, ttl-30)`，短 TTL 时会缓存到服务端过期之后，第二次请求 403。

已修复为：

```python
margin = min(30, max(1, ttl // 10))
expiry = now + max(1, ttl - margin)
```

15 秒 TTL 下等待 16 秒后第二次请求会重新登录并成功。

## Nacos 1.4.2

启动 1.4.2 + 认证，默认 `nacos/nacos` 登录成功；DrPanda 的 `ping`、配置列表、配置内容读取通过。

## Nacos 3.0.2

启动 3.0.2 + 认证后：

- v3 登录：`POST /nacos/v3/auth/user/login` 成功；
- 原 v1 配置 API 返回 `410 Gone`，提示改用 `/v3/...`；
- v3 admin/console API 的路径和响应包络与 v1 不同；
- 1.5.1 的 DrPanda Nacos 连接器基于 v1 OpenAPI，**不支持 Nacos 3.x 默认模式**；1.6.0 已新增 v3 适配，见 [nacos-3-1.6.0-01.md](nacos-3-1.6.0-01.md)。

结论：当前支持 Nacos 1.x / 2.x（v1 OpenAPI）；Nacos 3.x 需要单独适配 v3 API，不能直接宣称兼容。

## TLS + 认证

使用自签名证书在 Nacos 前放置 TLS 终止代理，连接器配置：

```text
base_url=https://localhost:18443
ca_pem=<自签名证书>
username=nacos
password=nacos
```

结果：

- 登录成功；
- 配置列表和内容读取成功；
- 证书校验生效；
- 说明 TLS + accessToken 认证链路可用。

注意：本次验证的是 TLS 终止代理 + Nacos 认证，不是 Nacos 原生 TLS 端口；Nacos 原生 TLS 需按部署方式单独验证。

## 全量验证

- `pytest -q`：**599 passed**；
- `ruff check .`：通过；
- `node --check app.js`：通过；
- `bash -n setup.sh`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.5.1` sdist/wheel。
