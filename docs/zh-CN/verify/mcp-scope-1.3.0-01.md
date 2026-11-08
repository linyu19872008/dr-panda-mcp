# MCP 目标 scope 暴露 1.3.0 · 验证记录

## 背景

LLM 通过 MCP 查目标时，只能从 `systems_status` 看到 name/type/enabled/最近测试；允许的库、索引、主题、vhost、项目、Redis key 前缀没有统一暴露。部分工具只能在省略参数时从 `stats` 间接看到，CLS/Mongo/ES 等则需要猜参数后触发 `SCOPE_DENIED`。

## 改动

`systems_status(environment=...)` 的目标行新增只读 `scope`：

- MySQL/Mongo：`allowed_dbs`、`default_db`
- Elasticsearch：`allowed_indices`
- Redis：`key_prefix`（`null` 表示无前缀限制）
- RabbitMQ：`allowed_vhosts`
- Kafka/CLS：`allowed_topics`
- GitLab：`allowed_projects`

同时：

- MCP 服务器说明和 `investigate_error` 提示词要求只使用 `scope` 中的值；
- `systems_status` 说明补充 `scope` 的非敏感性质；
- 不输出 host、用户、密码、连接串、证书等敏感字段。

## 安全边界

`scope` 是授权边界，不是密钥；只返回目标配置中对应的 selector 列表，按目标类型筛选，避免把其他组件的配置一起带出。

## 测试

新增 `test_systems_status_exposes_non_secret_target_scope`：

- 八种目标类型逐一创建；
- 校验每种类型的 `scope` 字段；
- 校验响应中不含 secret。

全量验证：

- `pytest -q`：**584 passed**；
- `ruff check .`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.3.0` sdist/wheel。

## 发布

- 版本：1.3.0；
- 属于 MCP 输出契约的向后兼容新增字段。
