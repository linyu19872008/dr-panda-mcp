# 变更记录

[English](CHANGELOG.md) · [简体中文](CHANGELOG.zh-CN.md)

记录本项目的显著变更。格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，版本遵循 [语义化版本](https://semver.org/)。

## [Unreleased]

## [1.3.3] - 2026-11-08

### 修复

- CLS `SearchLog` 结果正文改为优先读取 `LogJson`/`RawLog`；此前只读 `Log`/`Content`，导致 `cls_search` 返回空 `content`。

## [1.3.2] - 2026-11-08

### 修复

- CLS 检索结果里的 `Time`/`BTime` 若为毫秒时间戳，先换算成秒再格式化；此前 `datetime.fromtimestamp` 会因年份越界抛 `ValueError`，表现为 `cls_search` 内部错误。

## [1.3.1] - 2026-11-08

### 修复

- CLS `SearchLog` 的 `From`/`To` 改为毫秒时间戳，符合腾讯云 API 契约；此前传秒会被解释为 1970 年，导致检索永远 0 条。
- 更新 CLS fake SDK 与回归断言，校验 13 位毫秒请求值。

## [1.3.0] - 2026-11-08

### 新增

- `systems_status` 的目标行新增非敏感 `scope`，包含该类型授权的 selector：
  - MySQL/Mongo：`allowed_dbs`、`default_db`
  - Elasticsearch：`allowed_indices`
  - Redis：`key_prefix`
  - RabbitMQ：`allowed_vhosts`
  - Kafka/CLS：`allowed_topics`
  - GitLab：`allowed_projects`
- MCP 服务器说明与排查提示词要求使用 `scope` 中的值选择库/索引/主题/vhost/项目/key。

## [1.2.5] - 2026-11-07

### 修复

- CLS 客户端不再向 `ClsClient` 传入 SDK 不支持的 `timeout` 参数，改为通过 `ClientProfile`/`HttpProfile.reqTimeout` 设置，兼容当前腾讯云 SDK。
- CLS 探测/搜索/上下文读取的客户端初始化错误统一包装为上游失败，并保留异常类型与信息。
- CLS 表单增加地域示例提示（`ap-shanghai`）。

## [1.2.4] - 2026-11-07

### 修复

- HTTP 连接器收到 `Content-Encoding: gzip` 响应（典型为 Elasticsearch）时，httpx 已解压一次，重建 `httpx.Response` 时又按原响应头解压第二次，报 `Error -3 while decompressing data: incorrect header check`。
- 重建响应时移除 `content-encoding`、`content-length`、`transfer-encoding`，保留已解码内容和其它响应头。
- 新增 `stream_http` 与 Elasticsearch ping 的 gzip 回归测试。

## [1.2.3] - 2026-11-07

### 修复

- 目标表单的“安装客户端”按钮错误地从外部隐藏表单查找，导致 `doInstall()` 提前返回、没有发请求；现在从主表单查找按钮。

## [1.2.2] - 2026-11-07

### 修复

- `setup.sh service` 在写 unit 前确保把当前 `uv` 复制到 `/usr/local/bin`，包括 `uv` 只在 `/root/.local/bin` 的情况。

## [1.2.1] - 2026-11-07

### 修复

- systemd 沙箱下无法使用一键客户端安装：服务 PATH 中没有 `uv`、没有可写 uv cache，且 `ProtectSystem=strict` 阻止写 `.venv`。
- 新生成的 unit 会把 `uv` 安装到 `/usr/local/bin`，把 `UV_CACHE_DIR` 放到 `data/`，并只放行已有 `.venv`/`uv.lock` 的写入。

## [1.2.0] - 2026-11-07

### 新增

- 新建/编辑目标表单复用列表页的一键客户端安装，覆盖 `mysql`、`mongo`、`redis`、`kafka`、`cls` 所有可选客户端。
- probe 响应增加结构化 `install_extra`；表单显示安装按钮，安装后自动重新测试连接。
- 新增 `POST /targets/install-client` 接口，仅接受目标类型，服务端推导固定 extra，用于未保存表单。
- 安装失败展示业务错误，不再把原始 `uv sync` 命令暴露给页面。

## [1.1.3] - 2026-11-07

### 修复

- 未登录时登录页语言/主题切换被鉴权拦截，跳转成 `/login?next=/language`；登录后浏览器 GET `/language` 返回 405。
- `/language` 和 `/theme` 改为公开的 Cookie-only 路由。
- 登录 `next` 不再接受 POST-only 路由，未登录的非 GET 请求不保留 POST 路径作为登录后落点。

## [1.1.2] - 2026-11-07

### 修复

- MySQL 迁移 0007 的 `batch.alter_column` 因 MySQL 要求提供现有列类型而失败；现在传入 `existing_type` 和 `existing_nullable`。
- 新增真实 MySQL/PostgreSQL 首次安装集成检查：完整 SetupApp 流程、页面、schema 校验和幂等迁移。
- CI 增加 MySQL 8.0 / PostgreSQL 16 service container 任务。

## [1.1.1] - 2026-11-07

### 修复

- MySQL 首次安装迁移在 `0007_environments` 中因 `key` 是 MySQL 保留字而失败；迁移改用 SQLAlchemy 表达式，由方言自动引用标识符。
- 新增 MySQL 方言下的环境查询/插入编译回归测试。

## [1.1.0] - 2026-11-06

### 新增

- 部署脚本 `scripts/setup.sh`：`check`、`install`、`service`、`start`、`status`、`upgrade`。
- source（`git + uv sync`）与 PyPI（`uv tool install`）两种安装方式。
- 专用 `drpanda` 用户的 systemd 服务、沙箱配置与健康检查启动。
- Python 自动选择（优先系统 >=3.11，fallback 到共享 `/opt/uv-python`）、生产 `--no-dev`、可选 PyPI/Python 镜像。
- 安装前后检查解释器可访问性、服务用户执行权限和 systemd unit 合法性。

### 变更

- 仓库从 `DrPanda` 重命名为 `dr-panda-mcp`，与包名/CLI 对齐。
- 文档默认英文在 `docs/`，中文在 `docs/zh-CN/`。

### 修复

- systemd unit 的路径指令不再使用引号。
- 服务启动失败不再被误报为安装成功。

## [1.0.0] - 2026-11-06

### 新增

- 面向 MySQL、MongoDB、Elasticsearch、Redis、GitLab、RabbitMQ、Kafka、CLS 的只读 MCP 服务。
- 配置台：目标登记、连接测试、加密密钥、环境与 MCP Token 管理。
- 首次安装向导、登录 Session、CSRF、登录失败锁定与 MCP Bearer Token。
- 审计日志：结果/失败详情、筛选与保留期清理。
- 系统配置：新建目标默认值、并发、审计维护、Session/Token 限制、备份保留。
- 自动加载 `./.env`，严格校验权限与格式，真实环境变量优先。
- 界面、MCP、CLI 与文档默认英文；中文文档在 `docs/zh-CN/`。
- GitHub 开源文档：双语 README、贡献/安全/行为准则、Issue/PR 模板与 CI。

### 安全

- 绝对只读闸门 + 危险/高开销规则 + 目标范围限制。
- 目标密钥加密保存，MCP Token 只存哈希；日志与审计不出现凭证。
- 可配置 Cookie Secure 策略与可选 `/mcp` Host 白名单。

### 说明

- Kafka、CLS、GitLab 工具已实现并有单测，但未用真实上游做端到端验收。
- 反向代理后的 HTTPS/TLS 部署仍需按环境自行验收。
