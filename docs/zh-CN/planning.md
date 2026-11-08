# DrPanda MCP 规划

> 线上排查用的 MCP 服务。Cursor、Codex、DeepSeek Harness 通过 Streamable HTTP 调用它，查日志、代码、数据库和消息堆积。连接信息在网页上配置，首次启动完成安装后登录使用。
>
> 本文只定方案与实现契约，不包含业务代码。文中的接口签名、表结构、JSON 示例是约束，不是实现。

## 文档信息

| 项 | 值 |
|---|---|
| 版本 | v0.41 |
| 更新 | 2026-11-03 |
| 状态 | M0–M7 基础认证与首次安装已实现；MySQL/PostgreSQL 安装已验证；远程 TLS 待实机 |
| 范围 | 目标、决策、形态、网页、配置库、系统配置、密钥加密、绝对只读、危险与高开销操作、类型字段、工具、运行、结构、依赖、测试、分期、未决 |
| 契约地位 | 第 5、6、8 章是实现契约，代码偏离前先改本文 |

修订记录：

| 版本 | 日期 | 内容 |
|---|---|---|
| v0.1 | 2026-11-01 | 初稿：目标、决策、形态、网页、配置库、只读、字段、工具、分期 |
| v0.2 | 2026-11-01 | 补齐实现契约：ConfigStore 接口与表、闸门接口与拒绝矩阵、工具返回包络与错误码、八类字段表、运行与可观测性、依赖与工程准备、测试验收、每期验收、未决事项 |
| v0.3 | 2026-11-01 | 拍板四项：补 schema 发现工具、MySQL 闸门用 sqlglot、网页用 Jinja2、`secret_json` 应用层加密；MySQL/PostgreSQL 契约测试推迟到第一期之后 |
| v0.4 | 2026-11-01 | 系统配置入数据库并加 `/settings` 页（审计保留期默认 90 天、每 target 并发默认 10）；新增危险与高开销命令绝对规则（6.6） |
| v0.5 | 2026-11-01 | M1 落地同步：`Target` 增加 `secret_fields` / `secret_ok`，`ConfigStore` 增加 `ping`；SQLite 备份路径改为数据库同目录 `backup/` |
| v0.6 | 2026-11-01 | M2 落地同步：`Decision` 增加 `error_code`/`reason`，管理类与高开销类分别由白名单、危险清单拦截；Mongo 允许 `$lookup`（须先 `$match`）；补充连接器可选依赖 |
| v0.7 | 2026-11-01 | M3 落地同步：`systems_status` 是全局工具，包络 `target` 用 `*`、`type` 用 `all`；网页、系统配置页、审计清理任务按 4.x/9.6 落地 |
| v0.8 | 2026-11-01 | M3.5 视觉重构：手写 CSS 静态资源、Cookie 三态主题、列表改单表 + 统计/搜索/类型筛选、类型选择页、表单分区与错误摘要；仍为零 JS |
| v0.9 | 2026-11-01 | M4 落地同步：CLS/GitLab 五个工具与 `investigate_error` 上线；补充 CLS topic 语义与 GitLab 项目省略时的范围规则 |
| v0.10 | 2026-11-01 | M5 落地同步：数据面十七个工具上线；补充强制 LIMIT、聚合尾 `$limit`、ES `size` 上限、Redis 前缀与有界读取、schema 工具可用性 |
| v0.11 | 2026-11-01 | M6 落地同步：RabbitMQ/Kafka 五个工具上线；补充 vhost 遍历、消费组位点读取、low watermark 硬校验与无消费组拉取 |
| v0.12 | 2026-11-02 | 硬化：MySQL 可执行注释拒绝、工具级并发/超时、截断哨兵、必填密钥、SSL、重定向与若干连接器修复；文档与验证口径同步 |
| v0.13 | 2026-11-02 | 目标级 CA：MySQL / Elasticsearch 增加可选 `ca_pem`，私有 CA 不再依赖进程级 `SSL_CERT_FILE` |
| v0.14 | 2026-11-02 | mTLS：MySQL / Elasticsearch 增加可选客户端证书与私钥（加密字段），支持双向 TLS |
| v0.15 | 2026-11-02 | Mongo 认证模式：none/password/uri，旧 target 自动推断；增加 TLS/CA/客户端证书字段 |
| v0.16 | 2026-11-02 | Mongo 高级认证联调：X.509 与 replica set 经 URI 模式真实验证；LDAP/AWS IAM/OIDC/SRV 因企业版/云/DNS 依赖暂不验证 |
| v0.17 | 2026-11-02 | P0 安全收口：MySQL PROCESSLIST 显式开关、Mongo 系统集合拒绝、ES 负数 size/聚合边界、stats 字节上限、CLS 上下文与时间窗修复 |
| v0.18 | 2026-11-02 | IO 流上限；Redis ACL/TLS/mTLS；Mongo/ES/CLS/GitLab 分页；CLS context 字段修复 |
| v0.19 | 2026-11-02 | 系统配置扩展：新建目标默认限制、审计清理间隔；`/settings` 分组与字段级错误 |
| v0.20 | 2026-11-02 | 系统配置 reset 确认页与最近变更历史 |
| v0.21 | 2026-11-02 | 高级资源 `catalog_max_clients` 可配置；单项恢复默认；真实 Chrome 1440/390 与键盘走查 |
| v0.22 | 2026-11-02 | `/settings` 改为左侧子菜单分组切换，保存只提交当前分组并保留 section |
| v0.23 | 2026-11-02 | SQLite 启动/正常关闭 checkpoint，WAL 下外部查看器可见性收口 |
| v0.24 | 2026-11-02 | settings 自描述元数据 + 7 行完整 seed + settings_history 结构化历史 |
| v0.25 | 2026-11-02 | 设置页单列字段行、状态/操作分层、并发与审计子分组 |
| v0.26 | 2026-11-02 | Web 多语言：默认英文，支持 zh-Hans；Cookie 切换与页面文案迁移 |
| v0.27 | 2026-11-02 | SQLite 备份仅在 pending migration 时执行，保留上限 20 且系统配置可调 |
| v0.28 | 2026-11-02 | M7：users、首次安装向导、登录 Session/CSRF、MCP Bearer、Session 有效期配置、远程开关 |
| v0.29 | 2026-11-02 | M7：/me 账号页、Token 轮换、修改密码、Token 元数据 |
| v0.30 | 2026-11-02 | M7：多 Token 表、创建/物理删除、20 条分页、顶部“我的”导航 |
| v0.31 | 2026-11-02 | M7：Token 复制渐进增强；创建/删除改为同页 CSS 弹窗 |
| v0.32 | 2026-11-02 | 前端约束从严格零 JS 调整为服务端优先 + 局部渐进增强；原生 dialog 与复制脚本 |
| v0.33 | 2026-11-02 | 全站交互审计：无 JS 关闭回退、安装页复制、登录导航、404、CSRF HTML |
| v0.34 | 2026-11-02 | 目标/设置确认弹窗、表单加载态、Token 名称检查、管理员本地重置密码 |
| v0.35 | 2026-11-02 | 目标表单重构：连接分组、高级折叠、保存前测试连接、TLS 条件显示 |
| v0.36 | 2026-11-03 | 前端约束 v2：允许同源 fetch；探测接口与保存门槛；列表/设置/登录/安装向导异步化；CSP |
| v0.37 | 2026-11-03 | 配置台交互需要 JavaScript；只在连接字段变化时探测；Session 最短 30 分钟并与 CSRF 同步续期 |
| v0.38 | 2026-11-03 | 可选依赖改为 `uv sync --extra <name> --inexact`，避免精确同步卸掉其他客户端；失败详情完整显示该命令 |
| v0.39 | 2026-11-03 | 客户端未安装时，列表提供「安装」：服务在当前项目执行 `--inexact` 同步并立刻再测 |
| v0.40 | 2026-11-03 | 失败详情不再展示或复制安装命令，只保留「安装」 |
| v0.41 | 2026-11-03 | 环境是一等实体。目标名在环境内唯一；工具增加可选 `environment`；`systems_status` 先列环境；新密钥信封 v2 把环境写入 AAD |

## 1. 目标

模型拿到的是一组只读排查工具，不是线上系统的管理入口。人在网页里登记 MySQL、Mongo、Elasticsearch、Redis、GitLab、RabbitMQ、Kafka、CLS（腾讯云日志服务）的地址、凭证和允许访问的范围。工具在调用时按名字读取这些登记，模型不能自己传入主机、账号或密码。凭证即使带有写权限，本服务对这八个组件发出的请求也全部是只读的。

三个客户端都支持 Streamable HTTP，所以服务以 HTTP 方式提供，路径 `/mcp`。同一进程同时提供给人用的配置网页。

服务本身不做自动排查、不做自动修复、不做多系统一键扇出：关联由模型逐步调用工具完成，服务端只保证每次调用只读、有界、可审计。

只读之外还有一条绝对规则：不执行任何危险命令或高开销操作。即使命令是只读的、即使通过了白名单，只要可能全表扫描、无界遍历、执行脚本、深度分页、大聚合、全局阻塞或改动管理面，就一律拒绝（6.6）。这条规则没有开关。

## 2. 已定决策

| # | 决策 | 说明 |
|---|---|---|
| 1 | 传输 | 单进程同时提供 `/mcp`（Streamable HTTP）与 `/`（配置网页） |
| 2 | 鉴权 | 第一版不做登录、不做 Bearer Token、不做 OAuth；网页与 `/mcp` 都匿名 |
| 3 | 目标登记 | 连接与访问范围由网页写入配置库；每台 MySQL、每个 topic 都是库里的行，不写进环境变量 |
| 4 | 配置库 | 默认本机 SQLite，可换 MySQL 或 PostgreSQL；三种库共用同一套表、迁移与仓储接口；契约测试第一期只跑 SQLite（见 18） |
| 5 | 监听 | 默认 `127.0.0.1:8111`；`DR_PANDA_HOST`、`DR_PANDA_PORT` 可改 |
| 6 | 只读 | 对八个排查组件绝对只读，没有例外开关；账号能否写入不影响这条规则 |
| 7 | 鉴权外壳 | 以后加一层身份检查，包住网页和 `/mcp`；工具、配置库、只读限制都不改 |
| 8 | 返回契约 | 所有工具共用一套返回包络（8.1）与错误码（8.2） |
| 9 | 浏览器防护 | 网页与 `/mcp` 共挂 FastMCP 的 Host/Origin 校验；浏览器跨站提交被 403 拦下；第一版不做 CSRF token |
| 10 | 工具注解 | 每个工具声明 `readOnlyHint: true`，客户端可据此提示模型与用户 |
| 11 | 依赖 | SQLAlchemy 2 异步、Alembic、Jinja2、uvicorn、aiosqlite、cryptography、sqlglot（均有明确用途，见 11.1） |
| 12 | 启动 | 一条 `uv run dr-panda-mcp`；启动即迁移；任一前置失败以非零码退出并打印原因 |
| 13 | 文档地位 | 第 5、6、8 章是契约；改契约先改本文，再改代码 |
| 14 | 网页模板 | 用 Jinja2 服务端渲染，模板放 `web/templates/`，开启自动转义；配置台交互需要本地 JavaScript，不引入框架或 CDN |
| 15 | MySQL 闸门 | 用 sqlglot（`dialect="mysql"`）解析语法树做白名单；解析失败、多语句、非白名单节点一律拒绝 |
| 16 | 密钥存储 | `secret_json` 在应用层用 AES-256-GCM 加密后落盘；密钥来源与失败处理见 5.8 |
| 17 | schema 发现 | 提供 `mysql_tables`、`mysql_describe`、`mongo_collections`、`es_mapping` 四个只读工具，归入第二批（数据面） |
| 18 | 契约测试范围 | 第一期只跑 SQLite 契约测试；MySQL/PostgreSQL 的同一套测试推迟到首次需要外部库时再验收 |
| 19 | 系统配置 | 少量非敏感运行策略存配置库 `settings` 表，网页 `/settings` 可改；默认值写在代码里，改动即审计 |
| 20 | 审计保留期 | `audit_retention_days` 默认 90 天，范围 1–3650；每小时清理一轮过期审计 |
| 21 | 目标并发 | `target_max_concurrency` 默认 10，范围 1–50；按 target 生效，改动后下一次调用即用新值 |
| 22 | 危险操作 | 新增绝对规则：危险与高开销命令一律拒绝，独立于只读白名单，没有配置或环境变量可以放开（见 6.6） |

## 3. 总体形态

### 3.1 进程与入口

一个 Python 进程，两套入口：

| 入口 | 谁用 | 做什么 |
|---|---|---|
| `/` | 人，浏览器 | 登记、修改、停用、测试各个线上目标 |
| `/mcp` | Cursor、Codex、DeepSeek Harness | 调用排查工具 |

FastMCP 4.1.4 的 `custom_route` 就是用来挂这类协议之外的 HTTP 端点的。配置页走这条路径，MCP 仍走 `http_app` 的 `/mcp`。不另起前端工程，也不把配置页做成 MCP App：凭证要在普通浏览器里填写，Codex 和 DeepSeek Harness 也不保证能渲染 MCP 内嵌界面。

已于 FastMCP 4.1.4 核对（仓库未用该结论写代码）：`custom_route` 注册的路由会并入 `http_app` 返回的 Starlette 应用，因此网页与 `/mcp` 可由同一个 uvicorn 进程提供。

默认监听 `127.0.0.1:8111`。端口用 `DR_PANDA_PORT` 修改，监听网卡用 `DR_PANDA_HOST` 修改（`127.0.0.1` / `0.0.0.0` / 指定 IP）。首次安装必须在 loopback 完成；安装后改为非 loopback 即对外监听，建议通过 HTTPS 反向代理访问。`DR_PANDA_PUBLIC_URL` 仅用于展示，不参与安全判断；Cookie Secure 由 `DR_PANDA_COOKIE_SECURE` 控制，`/mcp` 的 Host 白名单由 `DR_PANDA_TRUSTED_HOSTS` 控制。

stdio 只用于本机调试 MCP 工具，不作为三端的正式接法。正式使用时客户端只配置 URL，例如 `http://127.0.0.1:8111/mcp`。端口改过时，客户端 URL 使用同一个端口。DeepSeek Harness 的 `serverName` 用短名 `drpanda`，模型看到的工具名会是 `mcp__drpanda__mysql_query` 这种形式，所以工具名保持短且稳定。

### 3.2 启动序列

进程启动按固定顺序执行，任何一步失败都打印明确原因并以非零码退出：

1. 读取并校验环境变量（3.3）。数据库 URL 补上异步驱动；URL 指向某种库但驱动未安装时，提示要安装哪一组依赖。
2. 创建配置库引擎；SQLite 打开 WAL、外键约束和 `busy_timeout`。
3. 读取 `data/install.json`：未安装 → 首次安装向导；已安装 → 连接配置库并检查 pending migration，仅 SQLite 且存在 pending 时先备份，再迁移（5.5）。
4. 加载密钥（5.8）：`DR_PANDA_SECRET_KEY` 优先，否则读 `data/secret.key`。文件不存在且配置库里还没有密文时生成新密钥（权限 0600）；库里有密文但当前密钥解不开时启动失败，提示恢复密钥备份或重新录入目标。
5. 创建 FastMCP 实例，注册服务器说明、工具、`investigate_error` prompt 与网页路由。
6. 构建 `http_app(path="/mcp")`，挂 Host/Origin 校验，用 uvicorn 监听 `DR_PANDA_HOST:DR_PANDA_PORT`。
7. 端口被占用时明确提示改 `DR_PANDA_PORT`，不静默重试。

### 3.3 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DR_PANDA_HOST` | `127.0.0.1` | 监听网卡 |
| `DR_PANDA_PORT` | `8111` | 网页与 `/mcp` 共用 |
| `DR_PANDA_DATABASE_URL` | 未使用 | 当前版本不参与实际建库：配置库由安装向导选择，之后以 `data/install.json` 为准；设置后仅做启动校验 |
| `DR_PANDA_SECRET_KEY` | 未设置 | base64 编码的 32 字节密钥，用于加密 `secret_json`；未设置时用 `data/secret.key` |
| `DR_PANDA_LOG_LEVEL` | `INFO` | 进程日志级别 |
| `DR_PANDA_PUBLIC_URL` | 未设置 | 仅展示用访问地址（MCP 地址/页面显示），不参与安全判断 |
| `DR_PANDA_COOKIE_SECURE` | `auto` | Cookie Secure：auto/always/never |
| `DR_PANDA_TRUSTED_HOSTS` | 未设置 | `/mcp` Host 白名单（逗号分隔） |

启动入口会自动加载**当前工作目录的 `./.env`**（文件不存在则跳过；真实环境变量优先；权限过宽或格式非法时启动失败）。除此之外不引入其他环境变量。目标的主机、账号、密钥、范围全部来自配置库，不读环境变量；加密密钥是例外，它不描述任何目标，只用于本地解密。

### 3.4 客户端接入

三个客户端只配 URL，不配命令：

```json
{
  "mcpServers": {
    "drpanda": {
      "url": "http://127.0.0.1:8111/mcp"
    }
  }
}
```

- Cursor：写入其 MCP 配置文件，字段名以该客户端版本为准；同时配置 `Authorization: Bearer <token>`。
- Codex：`[mcp_servers.drpanda]` 下配置 `url` 与 Authorization header。
- DeepSeek Harness：`serverName` 用 `drpanda`，模型侧工具名前缀为 `mcp__drpanda__`。

具体配置文件路径与字段名随客户端版本变化，本文只固定两件事：URL 是 `http://<DR_PANDA_HOST>:<DR_PANDA_PORT>/mcp`，serverName 是 `drpanda`。

### 3.5 安全基线

- 默认只监听回环地址；改为非 loopback 即对外监听（建议 HTTPS 反代），首次安装必须先在本机完成。
- 网页与 `/mcp` 共用 `host_origin_protection=True`：Host 头不在允许列表返回 421（防 DNS rebinding），Origin 不同源返回 403。
- 网页 POST 使用双提交 Cookie CSRF（`drpanda_csrf` + `_csrf`），失败 403；`/mcp` 使用 Bearer，不使用 CSRF。
- 全局安全响应头：`Content-Security-Policy`（`script-src 'self'`、`connect-src 'self'`、`form-action 'self'`、`frame-ancestors 'none'` 等）、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: same-origin`。
- 工具返回值、网页、日志、审计里都不出现密钥与连接串；错误信息同样处理。
- 加密密钥（5.8）不写日志、不写审计、不回显；密钥文件权限 0600，丢失后已登记的密钥不可恢复，只能重新录入。
- 第一版不做限流；由单进程 + 每目标并发上限（9.3）约束对线上系统的压力。

### 3.6 认证边界

安装前只开放 `/setup`、`/healthz`、`/static`；`/mcp` 返回 503。安装完成后：

- 网页未认证 303 → `/login`；`/mcp` 未认证 401；
- 网页使用账号密码 + 签名 Session Cookie；`/mcp` 使用独立 Bearer Token；
- 角色：`admin` 可进入全部管理页，并额外拥有 `/admin/overview` 管理概览；`analyst` 只能 `GET /targets`（只读目标目录，不含写操作），环境、系统配置、用户、管理概览与其他目标写路由均 403；
- 审计 actor 记录管理员身份；
- 工具、只读规则、危险清单、目标范围与系统配置语义不变；
- 认证失败与配置库故障区分：前者 401/303，后者 503/启动失败。

## 4. 配置网页

服务端渲染的表单页面，样式从简。页面只做配置，不承担排查。

### 4.1 路由

| 方法 | 路径 | 用途 | 成功 | 失败 |
|---|---|---|---|---|
| GET | `/` | 个人概览（所有角色） | 200 | 500 |
| GET | `/admin/overview` | 管理概览（仅管理员） | 200 | 403 |
| GET | `/targets/new` | 类型选择页（未带 type 时） | 200 | — |
| GET | `/targets/new?type=mysql` | 新建表单 | 200 | 400 未知类型 |
| POST | `/targets` | 提交新建（保存前必探测） | 303 → `/` | 400 校验失败 / 探测失败 |
| POST | `/targets/probe` | 新建草稿探测，不写库 | 200（JSON）/ 200（HTML 结果） | 400 校验失败 / 探测失败 |
| GET | `/targets/{id}/edit` | 编辑表单 | 200 | 404 |
| POST | `/targets/{id}` | 提交修改（保存前必探测） | 303 → `/` | 400 / 404 / 409 / 探测失败 |
| POST | `/targets/{id}/probe` | 编辑草稿探测，密钥留空沿用，不写库 | 200（JSON）/ 200（HTML 结果） | 400 / 404 |
| POST | `/targets/{id}/toggle` | 启用或停用 | 303 → `/` | 404 |
| GET | `/targets/{id}/delete` | 删除确认页 | 200 | 404 |
| POST | `/targets/{id}/delete` | 确认删除 | 303 → `/` | 404 |
| POST | `/targets/{id}/test` | 测试连接，结果写回目标 | 303 → `/` | 404 |
| GET | `/settings?section=<key>` | 系统配置页（4.5，子菜单分组） | 200 | 500 |
| POST | `/settings` | 提交系统配置（成功后带 `?flash=saved`） | 303 → `/settings` | 400 校验失败 |
| GET | `/settings/reset` | 恢复默认值确认页 | 200 | — |
| POST | `/settings/reset` | 确认恢复全部系统配置默认值 | 303 → `/settings` | 500 |
| POST | `/theme` | 主题三态（system / light / dark），写 Cookie | 303 → 站内 next | — |
| POST | `/language` | 语言切换（en / zh-Hans），写 Cookie | 303 → 站内 next | — |
| GET | `/me` | 账号、MCP Token 列表（20/页）、修改密码 | 200 | 未登录 303 |
| POST | `/me/password` | 修改管理员密码并失效旧 Session | 303 → `/login` | 400 校验失败 |
| GET | `/me/tokens/new` | 新建 Token 表单 | 200 | 未登录 303 |
| POST | `/me/tokens` | 创建 Token，显示一次 | 200 | 400 名称过长 |
| GET | `/me/tokens/{id}/delete` | 删除确认 | 200 | 404 |
| POST | `/me/tokens/{id}/delete` | 物理删除 Token | 303 → `/me` | 404 |
| GET | `/static/app.css` | 手写样式表（ETag、短缓存） | 200 / 304 | 404 |
| GET | `/healthz` | 健康检查（9.2） | 200 JSON | 503 |

约定：

- 所有变更都走 POST + 表单按钮，不用 GET 触发副作用；删除先到确认页再提交。
- 列表页的 GET 不发起任何外呼。测试连接只在用户点按钮时执行。
- 重定向后回列表，避免刷新重复提交。
- 每组 POST 路由同时服务两种客户端：普通表单（无 JS / JS 失败）返回 303 或 HTML 重渲染；同源 fetch 带 `Accept: application/json` 时返回统一 JSON `{ok, code, message, errors, phase, redirect}`。两种形态走同一份服务端校验。
- 保存目标前服务端必须完成一次真实探测：探测失败返回 400 且不落库；探测成功才写库并把结果写回 `last_test_*`。

### 4.2 表单与校验

公共字段：

| 字段 | 存储位置 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| 名称 | `name` | 是 | — | `^[a-z0-9][a-z0-9-]{0,63}$`，不以 `-` 结尾；在所属环境内唯一，不同环境可同名；创建后不可改 |
| 类型 | `type` | 是 | — | 八种之一，创建后不可改 |
| 启用 | `enabled` | 是 | true | 复选框 |
| 超时 | `options.timeout_s` | 否 | 15 | 整数 1–120，单位秒 |
| 行数上限 | `options.max_rows` | 否 | 100 | 整数 1–1000 |
| 字节上限 | `options.max_bytes` | 否 | 102400 | 整数 4096–1048576 |

各类型额外字段见第 7 章。列表类字段（库、索引、topic、项目、vhost）用多行文本域，一行一条，去空行、去重、保持输入顺序。

校验失败时重新渲染表单，保留用户输入（密钥字段除外），显示字段级错误，HTTP 400，不落库。未知 `type` 直接 400。

表单交互约定：顶部给出错误摘要并锚点到对应字段；每个错误字段有 `aria-invalid` 与 `aria-describedby`；保存/取消放在底部固定操作条，窄屏时按钮拉通。

### 4.3 密钥处理

- `secret_json` 落盘只存密文（5.8），不存原值。页面只显示"已设置 / 未设置"，不显示明文，也不显示掩码串（掩码会泄露长度和前缀）。
- 新建：该类型要求的密钥字段必填。
- 编辑：留空表示沿用原值；勾选"清除"表示显式置空；填写新值表示替换。三者互斥。
- 后端只认一个补丁结构：`{"set": {"password": "..."}, "clear": ["password"]}`。表单负责把"留空 / 清除 / 新值"翻译成这个结构，仓储不解释页面语义。
- 加密在仓储写入前完成：`set` 的字段逐个加密，`clear` 的字段删除密文；加密失败直接报错，不允许退回明文写入。
- 错误信息、日志、审计、工具返回值都不出现密钥。上游错误摘要落库前，把本次连接用到的密钥字面量替换为 `***`。

### 4.4 页面风格与交互

**技术形态**

- 用 Jinja2 服务端渲染 HTML；样式是仓库内手写的 `web/static/app.css`，由 `GET /static/app.css` 提供（ETag + 短缓存），不引前端框架、不引 CSS/JS 构建链、不引外部字体或 CDN。
- 模板放 `src/dr_panda_mcp/web/templates/`，开启自动转义（`autoescape=True`）；表单字段值靠模板上下文传入，不拼接 HTML。
- **服务端渲染 + 本地脚本**：页面由 Jinja2 输出；配置台交互需要启用 JavaScript。认证、CSRF、Host/Origin、字段校验和只读闸门只在服务端执行。
  - `app.js`：同源 JSON 命令、dialog、主题即时切换、离开确认；
  - `copy-token.js`：Token 复制按钮；
  - 禁止前端框架、构建链、第三方 CDN/脚本；脚本不得代替服务端校验，不得记录 Token。

**明暗主题**

- 三态：跟随系统（默认）/ 浅色 / 深色。无 Cookie 时不输出 `data-theme`，由 CSS `prefers-color-scheme` 跟随系统；选择浅/深后 `POST /theme` 写 `drpanda_theme` Cookie，服务端渲染 `data-theme`，无闪烁。
- 主题变量集中在 CSS 自定义属性：背景/表面/边框/文本/强调色/语义色/阴影/圆角/间距/字体；浅深两套 token 值必须满足对比度（正文 ≥4.5:1，大字与图标 ≥3:1）。
- 主题切换是顶栏的三段式按钮（跟随系统/浅色/深色），当前项 `aria-pressed`；浏览器立即改 `data-theme`，并用 JSON 写入 Cookie，不整页刷新。语言切换仍整页加载；未保存表单会先确认。

**视觉与布局**

- 设计系统：中性低饱和、单一蓝色强调；14px 基准字号；4px 间距栅格；6/10px 圆角；状态用徽标 + 色点 + 文字三重表达，不只用颜色。
- 页面骨架：左侧菜单（品牌，以及排查 / 记录 / 系统三组）、顶栏（版本 / 语言 / 主题 / 账号）、页面头（h1 + 说明 + 主操作）、内容容器（最大 1180px，从菜单右侧左对齐）、跳过链接与语义化 landmark。登录和安装不显示菜单。
- 列表页改为**单表 + 统计条 + 搜索 + 类型筛选**：目标总数/已启用/最近测试失败/密钥异常四项统计；按类型徽标展示，支持 `q` 搜索与 `type` 筛选；空状态给出八类型入口；视口 ≤1120px 时表格转为卡片列表，避免和左侧菜单抢宽度。
- 表单页：两栏（主表单 + 帮助侧栏）、分区卡片（基本信息/连接/授权范围/高级设置）；每张卡片一个主按钮。布尔字段用行内复选框；密钥显示「已设置」徽标，留空表示不改。
- 删除确认在列表页 dialog 中展示名称、类型、端点、授权范围和最近测试；设置页每项带单位、默认值、允许范围与影响说明。
- 创建、删除成功后回到列表并显示 flash。设置保存留在当前分组，用页内提示。
- 可访问性：跳转链接、可见焦点环、label/for、错误与 `aria-live`、表格 `scope`、`aria-current`、`prefers-reduced-motion`。按钮约 34px，主题图标点击区域约 32px。

### 4.5 系统配置页

`/settings` 只放非敏感、可在线调整的运行策略。值存配置库 `settings` 表（5.3），默认值写在代码 `settings.py`，页面同时显示当前值、默认值与允许范围。

| 分组 | 配置键 | 含义 | 默认 | 范围 | 生效时机 |
|---|---|---|---|---|---|
| 新建目标默认值 | `default_target_timeout_s` | 新建目标默认超时 | 15 | 1–120 | 新建目标表单 |
| 新建目标默认值 | `default_target_max_rows` | 新建目标默认行数上限 | 100 | 1–1000 | 新建目标表单 |
| 新建目标默认值 | `default_target_max_bytes` | 新建目标默认字节上限 | 102400 | 4096–1048576 | 新建目标表单 |
| 并发与审计 | `target_max_concurrency` | 每 target 并发上限 | 10 | 1–50 | 下一次取槽 |
| 并发与审计 | `global_max_concurrent_calls` | 进程内全局并发上限（0=不限） | 0 | 0–200 | 下一次取槽 |
| 并发与审计 | `audit_retention_days` | 审计保留天数 | 90 | 1–3650 | 下一轮清理任务 |
| 并发与审计 | `audit_cleanup_interval_minutes` | 审计清理间隔 | 60 | 5–1440 | 下一轮清理周期 |
| 并发与审计 | `audit_cleanup_batch_size` | 审计清理每批条数 | 1000 | 100–5000 | 下一轮清理 |
| 并发与审计 | `audit_cleanup_max_seconds` | 单轮清理最长秒数 | 300 | 10–3600 | 下一轮清理 |
| 高级资源 | `catalog_max_clients` | 进程内连接器客户端缓存上限 | 32 | 4–128 | 下一次取客户端 |
| 高级资源 | `catalog_idle_seconds` | 连接器空闲回收秒数（0=不回收） | 0 | 0–3600 | 下一次取客户端 |
| 认证与会话 | `session_ttl_minutes` | Web Session 有效期 | 720 | 30–10080 | 下一次请求 |
| 高级资源 | `backup_keep_count` | SQLite 备份保留数量 | 20 | 1–20 | 下一次启动迁移 |

- 新建目标默认值只作用于新建表单；既有 target 已保存的 `timeout_s` / `max_rows` / `max_bytes` 不因系统配置改变。
- 页面使用左侧子菜单切换分组：可编辑的“新建目标默认值 / 并发与审计 / 认证与会话（Session、登录保护、MCP Token）/ 高级资源”，只读的“安全边界 / 启动配置 / 最近变更”；每次只渲染当前分组，保存只提交当前分组并保留 `section`。启动配置展示监听地址、配置库、公网地址、远程监听、日志级别和密钥来源。
- “恢复默认值”走独立确认页，支持全局或单项恢复，并写审计。
- 字段级错误、`aria-invalid`/`aria-describedby`、顶部错误摘要锚点；保存失败保留输入。

- 只能改这里列出的键；键白名单写死在 `settings.py`，未知键返回 400，不做"任意键值"配置。
- 校验：整数、闭区间；非整数或越界返回 400，回显当前值，不落库。
- 保存：一次事务内更新 `settings`；只把实际变化的键写入 `settings_history` 与一条 `settings.update` 审计（summary 记录 `键: 旧值 -> 新值`），没有变化时不写。
- 保存后按各项自己的生效时机读取：并发上限在下一次取槽时读取，已经在跑的调用不取消；Session 在下一次请求续期或失效。
- 系统配置不能放开只读、危险命令、密钥与目标范围，这些键不在白名单里。
- 页面不涉及密钥。恢复默认会列出当前值与默认值，并写审计；目标、密钥和只读边界不受影响。

### 4.6 异步交互与保存门槛

前端约束见 `docs/verify/frontend-js-policy.md` v3：配置台需要 JavaScript；不引入框架、构建链或第三方脚本。服务端仍是认证、校验和只读闸门的唯一事实来源。非 JSON 的 POST 仍返回 303 或 HTML，供测试与直接请求使用；浏览器里的按钮一律走 JSON。

- 探测接口：`/targets/probe`、`/targets/{id}/probe` 只做只读探测，不写库、不写审计。
- 新建目标：保存前必须测试通过。编辑目标：主机、账号、密钥、TLS、超时没变时可以直接保存；这些字段变化后必须重新测试。授权范围、启停、行数和字节上限不触发探测。
- 保存兜底：连接字段有变化时，服务端写库前再探测一次，失败不写库，也不把这次失败记成最近测试成功。只改范围或上限时不探测。
- 其他页面：列表行内测试/启停、系统配置保存、修改密码、登录、安装向导的测试与完成安装走 JSON。失败留在当前页。主题切换不刷新页面。
- 错误契约：401 → 跳登录；403 → 页面过期提示；400 携带字段错误；409 冲突；网络/超时给可重试提示。JSON 响应 `Cache-Control: no-store`。

## 5. 配置库

配置库只保存本服务自己的数据：排查目标、密钥、审计。它和网页里登记的线上 MySQL 是两套连接。配置库需要插入、更新和删除；线上 MySQL 只供排查工具做只读查询。配置库的地址来自环境变量，不能登记成一个排查目标，排查工具也不能改配置库。

### 5.1 选型与环境变量

环境变量 `DR_PANDA_DATABASE_URL`。未设置时使用本机 SQLite：

```
sqlite:///data/dr-panda.sqlite
```

`data/` 不进 git。换成另外两种库时只改这个 URL：

```
mysql://user:pass@host:3306/dr_panda
postgresql://user:pass@host:5432/dr_panda
```

进程启动时把 `mysql://` 补成异步驱动 `mysql+asyncmy://`，把 `postgresql://` 补成 `postgresql+asyncpg://`，调用方不用写驱动名。URL 指向某种库但对应驱动没安装时，启动直接失败，并说明要安装哪一组依赖。

默认安装包含 SQLite 驱动，开箱可用。MySQL 和 PostgreSQL 的驱动做成可选依赖：`dr-panda-mcp[mysql]`、`dr-panda-mcp[postgres]`。仓储代码不因装了哪一组依赖而分叉。

### 5.2 ConfigStore 接口

网页、MCP 工具、连接器只依赖 `ConfigStore`，不出现 SQLite、MySQL、PostgreSQL 的类型和 SQL。接口保持很小：

```python
class ConfigStore(Protocol):
    async def list_all(self) -> list[Target]: ...
    async def list_by_type(self, type: str) -> list[Target]: ...
    async def get(self, name: str) -> Target | None: ...
    async def get_by_id(self, target_id: int) -> Target | None: ...

    async def create(self, draft: TargetDraft, actor: str) -> Target: ...
    async def update(self, target_id: int, draft: TargetDraft, actor: str) -> Target: ...
    async def set_enabled(self, target_id: int, enabled: bool, actor: str) -> Target: ...
    async def delete(self, target_id: int, actor: str) -> None: ...
    async def record_test(
        self, target_id: int, ok: bool, error: str | None, actor: str
    ) -> Target: ...
    async def append_audit(self, entry: AuditEntry) -> None: ...

    # 健康检查与系统配置
    async def ping(self) -> None: ...
    async def get_settings(self) -> dict[str, str]: ...
    async def update_settings(
        self, patch: dict[str, str], actor: str
    ) -> dict[str, str]: ...
```

数据对象：

```python
@dataclass(frozen=True)
class Target:
    id: int
    type: str
    name: str
    enabled: bool
    options: dict[str, Any]      # options_json 反序列化
    secret: dict[str, str]       # 解密后的密钥，仅进程内使用；secret_ok=False 时为空
    secret_fields: frozenset[str]  # 密文里存在哪些字段名（不需要解密即可得到）
    secret_ok: bool              # 是否全部解密成功；False 时上层报 SECRET_UNAVAILABLE
    created_at: datetime
    updated_at: datetime
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_error: str | None

@dataclass(frozen=True)
class TargetDraft:              # 新建与修改共用
    name: str
    type: str
    enabled: bool
    options: dict[str, Any]
    secret_patch: SecretPatch

@dataclass(frozen=True)
class SecretPatch:
    set: dict[str, str]          # 覆盖或新增
    clear: frozenset[str]        # 置空

@dataclass(frozen=True)
class AuditEntry:
    actor: str                   # 登录之前固定 anonymous
    action: str                  # 见 5.4
    target_name: str | None
    summary: str | None

@dataclass(frozen=True)
class TargetView:                # 网页专用视图，不含密钥
    id: int
    type: str
    name: str
    enabled: bool
    options: dict[str, Any]
    secret_fields: frozenset[str]  # 已设置的密钥字段名，例如 {"password"}
    created_at: datetime
    updated_at: datetime
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_error: str | None

@dataclass(frozen=True)
class Settings:                  # 解析并校验后的运行时策略
    audit_retention_days: int    # 默认 90，范围 1–3650
    target_max_concurrency: int  # 默认 10，范围 1–50
    default_target_timeout_s: int = 15
    default_target_max_rows: int = 100
    default_target_max_bytes: int = 102400
    audit_cleanup_interval_minutes: int = 60
    catalog_max_clients: int = 32
```

约定：

- `get` / `get_by_id` 返回的 `Target` 带解密后的密钥，仅供工具与连接器在进程内使用；网页不直接用 `Target`，而是先转成 `TargetView`，`secret_fields` 直接来自密文键名（不需要解密）。
- 单个目标的密钥解不开时读取不报错：`secret_ok=False`、`secret={}`、`secret_fields` 保留；连接器与工具据此返回 `SECRET_UNAVAILABLE`，网页标注"密钥不可用，请重新录入"。
- 所有写方法（`create`、`update`、`set_enabled`、`delete`、`record_test`）都在同一次事务里追加一条审计；失败时两者一起回滚。
- 时间一律 UTC 带时区，写入与读出都按 UTC。
- 系统配置值通过 `settings.py` 访问：它持有默认值、键白名单与范围校验；仓储读写值，数据库同时保存元数据与结构化历史；读取时缺键补默认值，不缓存。
- 异常：`TargetNotFound`（网页 404）、`TargetNameTaken`（409）、`InvalidTarget`（400）、`StorageUnavailable`（500）、`SecretUnavailable`（密钥解不开，网页提示重新录入，工具返回 `SECRET_UNAVAILABLE`）。异常信息不含密钥。

### 5.3 表

`users`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BigInteger | 主键自增 | |
| `username` | String(64) | NOT NULL, UNIQUE | 安装时固定 `admin` |
| `password_hash` | String(255) | NOT NULL | scrypt 哈希，不存明文 |
| `role` | String(32) | NOT NULL | `admin` 或 `analyst`。安装时只有管理员；分析员只读 `/targets`，其余管理页 403 |
| `is_enabled` | Boolean | NOT NULL | 停用后不能登录，已有 Token 也不能调用 |
| `auth_version` | Integer | NOT NULL | 改密后递增，使旧 Session 失效 |
| `must_change_password` | Boolean | NOT NULL | 分析员创建和重置密码后为真，本人改密成功后清除 |
| `last_login_at` | DateTime(timezone=True) | NULL | 最近登录 |
| `created_at` / `updated_at` | DateTime(timezone=True) | NOT NULL | UTC |

`mcp_tokens`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BigInteger | 主键自增 | |
| `user_id` | BigInteger | NOT NULL, FK users.id | 归属管理员 |
| `name` | String(64) | NULL | 可选名称；旧 Token 不迁移 |
| `token_hash` | String(64) | NOT NULL, UNIQUE | Bearer Token 的 SHA-256 |
| `token_prefix` | String(16) | NULL | 页面识别前缀 |
| `created_at` | DateTime(timezone=True) | NOT NULL | UTC |
| `last_used_at` | DateTime(timezone=True) | NULL | 最近认证时间 |

`environments`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BigInteger | 主键自增 | |
| `key` | String(64) | NOT NULL, UNIQUE | 调用标识，创建后不可改。规则同 target 名 |
| `title` | String(64) | NOT NULL | 展示名，可改，允许中文 |
| `enabled` | Boolean | NOT NULL | 停用后排查工具拒绝该环境，网页仍可改配置、测连接 |
| `created_at` / `updated_at` | DateTime(timezone=True) | NOT NULL | UTC |

迁移总会种下 `key=default`、`title=默认`。只有这一个环境时，工具可以省略 `environment`。

`targets`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BigInteger | 主键自增 | |
| `environment_id` | BigInteger | NOT NULL, FK environments.id | 创建后不可改 |
| `type` | String(32) | NOT NULL | 类型枚举在应用层校验 |
| `name` | String(64) | NOT NULL | 在所属环境内唯一；不同环境可以同名 |
| `enabled` | Boolean | NOT NULL | 默认 true |
| `options_json` | JSON | NOT NULL | 非密钥项，整份读写 |
| `secret_json` | JSON | NOT NULL | 密钥项：字段名 → 密文信封（5.8），整份读写；默认 `{}` 由应用层写入 |
| `created_at` | DateTime(timezone=True) | NOT NULL | UTC |
| `updated_at` | DateTime(timezone=True) | NOT NULL | UTC |
| `last_test_at` | DateTime(timezone=True) | NULL | UTC |
| `last_test_ok` | Boolean | NULL | |
| `last_test_error` | String(512) | NULL | 已打码 |

索引：`uq_targets_environment_name`（environment_id, name）、`ix_targets_type`（type）、`ix_targets_environment_id`。`uq_environments_key`（key 唯一）。

`audit`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BigInteger | 主键自增 | |
| `created_at` | DateTime(timezone=True) | NOT NULL | UTC |
| `actor` | String(64) | NOT NULL | 登录之前为 `anonymous` |
| `action` | String(32) | NOT NULL | 见 5.4 |
| `environment_key` | String(64) | NULL | 这次操作所属环境的调用标识；与环境无关时为空。旧记录不回填 |
| `target_name` | String(64) | NULL | 工具调用与配置变更都写 |
| `summary` | String(1024) | NULL | 已打码 |
| `outcome` | String(8) | NULL | `ok` / `failed`；只有工具调用与测试连接有成败语义，其余为 NULL。0010 迁移按 summary 回填旧行 |
| `error_detail` | String(512) | NULL | 工具调用失败时的错误消息（已打码、截断）；旧记录与成功调用为 NULL，不回填 |

索引：`ix_audit_created_at`。审计只追加，不更新；唯一的删除路径是按保留期清理（9.6）。

`settings`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `key` | String(64) | 主键 | 键名，白名单见 4.5 |
| `value` | String(64) | NOT NULL | 字符串原值；解析与范围校验在 `settings.py` |
| `value_type` | String(16) | NOT NULL | int/bool/string/enum |
| `group_key` | String(64) | NOT NULL | 分组键 |
| `group_title` | String(128) | NOT NULL | 分组展示名 |
| `label` | String(128) | NOT NULL | 字段名 |
| `description` | Text | NOT NULL | 帮助说明 |
| `default_value` | String(64) | NOT NULL | 默认值 |
| `min_value` / `max_value` | BigInteger | NULL | 数值范围 |
| `unit` | String(16) | NOT NULL | 秒/行/字节/分钟/个 |
| `effect` | String(64) | NOT NULL | 生效方式 |
| `editable` | Boolean | NOT NULL | 是否可网页编辑 |
| `requires_restart` | Boolean | NOT NULL | 是否需要重启 |
| `sort_order` | BigInteger | NOT NULL | 页面顺序 |
| `updated_at` | DateTime(timezone=True) | NOT NULL | UTC |
| `updated_by` | String(64) | NOT NULL | 修改人；M7 后为登录管理员 |

`settings_history`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BigInteger | 主键自增 | |
| `key` | String(64) | NOT NULL | 配置键，索引 |
| `old_value` | String(64) | NULL | 旧值 |
| `new_value` | String(64) | NOT NULL | 新值 |
| `actor` | String(64) | NOT NULL | 操作者 |
| `changed_at` | DateTime(timezone=True) | NOT NULL | UTC，索引 |

初始化时写入两个默认值：`audit_retention_days=90`、`target_max_concurrency=10`。这张表只放 4.5 列出的运行策略，不做通用键值配置，也不存任何密钥。

表结构遵守能在三种库上执行的子集：

- 主键优先用自增整数，不用某种库专有的序列语法；例外是 `settings`，它用固定键名做主键（键集合由代码白名单决定，不存在并发插入问题）
- `type` 用定长字符串，合法值在应用层检查，不用数据库 ENUM
- `enabled`、`last_test_ok` 用布尔
- 时间用带时区的时间戳，应用层一律写 UTC、按 UTC 读出
- `options_json`、`secret_json` 用 JSON 类型，整份读写；第一版不在 SQL 里按 JSON 内部字段过滤，避免依赖某种库的 JSON 运算符
- JSON 列不给数据库默认值，由应用层写入 `{}`
- 字符串给出 MySQL 需要的长度：`name` 64，`type` 32，审计动作 32，调用方 64，设置键 64，设置值 64
- 密钥在应用层加密（5.8），三种库存的是同一种密文格式，数据库不参与加解密

### 5.4 事务与审计

- 配置变更：`targets` 写入与 `audit` 追加在同一个事务里提交，任一失败整体回滚。
- 工具调用：先按主键读一次配置，调用结束后追加一条审计，用独立短事务，尽力而为；写失败只记 WARNING，不影响工具结果，也不因审计失败重试外呼。
- 审计动作取值：

| action | 触发 |
|---|---|
| `target.create` | 网页新建 |
| `target.update` | 网页修改 |
| `target.enable` / `target.disable` | 网页启用/停用 |
| `target.delete` | 网页删除 |
| `target.test` | 网页或工具执行连通性测试 |
| `tool.call` | 任何 MCP 工具调用 |
| `settings.update` | 网页修改系统配置 |
| `app.start` | 进程启动完成 |

- 打码规则：密钥字段永不落盘。`tool.call` 的 summary 记工具名、环境、target、参数摘要（先打码，再截到 200 字符）、返回条数、耗时、错误码。经 `/mcp` 的调用另记 Token 名称和前缀，不记完整 Token。`systems_status` 同样记 `tool.call`。summary 落盘前对手机号（`1` 开头 11 位）、18 位身份证号、`password=`/`token=`/`secret=` 形式的值替换为 `***`。
- 网页 `/audit` 只读查看近 24 小时、7 天或 30 天的记录，可按动作、环境、结果（成功/失败）和对象名筛选。不提供删除。
- 审计保留期由系统配置 `audit_retention_days`（默认 90 天）控制，清理任务见 9.6。清理动作只记日志、不写审计，避免审计表自增。

### 5.5 迁移与启动

- Alembic 单版本链，适用全部方言；进程启动时 `upgrade head`，重复启动幂等。
- 迁移同时初始化 `settings` 的两个默认行：键不存在才写入，已存在不覆盖，重复启动不会把用户改过的值重置。
- SQLite：仅在存在 pending migration 时，把数据库文件复制到与数据库同目录的 `backup/<时间戳>.sqlite`；保留数量由 `backup_keep_count` 控制（默认 20，范围 1–20，系统配置可调）。无 pending 的普通启动不产生新备份。
- MySQL / PostgreSQL：不自动备份；迁移失败则退出，提示先用数据库侧备份恢复。
- 不提供 downgrade 流程。回滚方式是按备份恢复或重建配置库后重新登记。
- 第一版按单进程使用；多进程共用同一 MySQL/PostgreSQL 时再给迁移加锁。

### 5.6 方言边界

三种库共用一个 SQLAlchemy 2 异步实现，不各写一套仓储。方言差异收拢在三处：URL 解析、引擎创建、Alembic 迁移。SQLite 在建引擎时打开 WAL、外键约束和 `busy_timeout`；这段逻辑不进入仓储语句。再增加一种关系型数据库时，补 URL 方案、驱动依赖，并用同一套契约测试验收，而不是复制一份增删改。

### 5.7 存储层契约测试

`ConfigStore` 的行为用同一套测试描述。第一期只在 SQLite 上跑；把 `DR_PANDA_TEST_DATABASE_URL` 指到 MySQL 或 PostgreSQL 时跑同一套，作为这两种库的验收，但这项验收推迟到首次需要外部库时执行（14.3）。

- 名称唯一：重复创建抛 `TargetNameTaken`；名称大小写与非法字符被拒。
- 密钥不回显：网页视图只拿到"已设置字段名集合"，拿不到明文。
- 停用语义：停用后 `get` 仍返回目标，但 `enabled=False`，工具据此拒绝。
- 同事务：`targets` 与 `audit` 一起提交；模拟审计写失败时目标变更回滚。
- 时区：写入 UTC，读出 UTC；跨进程重启后仍然一致。
- JSON 往返：`options_json` 整份写入读出一致，不丢未知键。
- 密钥补丁：`set` 覆盖、`clear` 置空、留空沿用三种语义正确。
- 并发：两个事务同时创建同名目标，只有一个成功。
- 密文落盘：直接查原始行，`secret_json` 的文本里不含任何明文密钥。
- 绑定关系：把 A 目标的密文换到 B 目标的同名字段，解密失败（AAD 绑定 target 名与字段名）。
- 密钥缺失：用错误的密钥读取，抛 `SecretUnavailable`，不返回明文也不返回空值。
- 清除：`clear` 后该字段的密文键消失，页面显示"未设置"。
- 解密失败标记：换错密钥读取时 `secret_ok=False`、`secret={}`，`secret_fields` 仍保留；不抛异常、不拖垮列表。
- 系统配置默认值：全新库迁移后有 9 个配置行，含新建目标默认值、并发、审计、认证 Session、高级资源与备份保留数量；读取 `get_settings` 返回全部当前值。
- 系统配置校验：`audit_retention_days=0`、`3651`、`abc` 与非整数被拒；`target_max_concurrency=0`、`51` 被拒；合法值写入后读出一致。
- 系统配置同事务：更新值、写 `settings_history`（old/new）与 `settings.update` 审计一起提交。
- 系统配置白名单：未知键（例如 `target_max_concurrency_x`、`readonly=false`）直接拒绝，仓储不写入未知键。

### 5.8 密钥加密

`secret_json` 在应用层加密后落盘，数据库只存密文。落盘形态：

```json
{
  "password": {"v": 1, "kid": "k1", "nonce": "base64", "ct": "base64"}
}
```

- 算法 AES-256-GCM，每个字段独立随机 nonce；字段名是明文键，字段值与长度都在密文中。
- AAD 绑定"target 名 + 字段名"（例如 `drpanda:order-mysql:password`），密文不能跨目标或跨字段挪用。
- `kid` 记录密钥版本，第一版只有 `k1`；为以后轮换预留字段，不实现轮换流程。
- 写：`set` 的字段逐个加密后替换，`clear` 的字段删除密文，留空不动。加密失败报错，不回退明文。
- 读：网页只读密文键名（不解密）；工具与连接器在调用时解密用到的字段，明文只在调用期间存在于内存，不写日志、不进缓存、不进审计。
- 密钥来源（3.2 第 4 步）：`DR_PANDA_SECRET_KEY`（base64 编码的 32 字节）优先；未设置时用 `data/secret.key`，文件不存在且库里还没有密文时自动生成，权限 0600。密钥文件与配置库同等重要，必须一起备份。
- 失败处理：
  - 启动时库里已有密文但当前密钥解不开：启动失败，提示恢复 `secret.key` 或 `DR_PANDA_SECRET_KEY` 备份；不静默生成新密钥覆盖。
  - 运行中单个目标解密失败（库被手工改动等）：该目标工具返回 `SECRET_UNAVAILABLE`，网页标注"密钥不可用，请重新录入"；其他目标不受影响。
  - 密钥丢失且无备份：只能重新录入全部密钥，已加密数据不可恢复。
- 不做明文兼容：第一版从零开始；若有人手工往 `secret_json` 写明文，读取时按解密失败处理。
- 加解密代码集中在 `crypto.py`，仓储是唯一调用方；测试用临时生成的密钥，不读用户真实密钥。

## 6. 绝对只读

MySQL、Mongo、Elasticsearch、Redis、GitLab、RabbitMQ、Kafka、CLS 的每一次调用，包括网页上的测试连接，都是只读的。用户配进来的账号即使可以插入、更新、删除、建表、清队列、发消息或改配置，本服务也不行使这些权限。

这条规则没有例外开关。网页上不出现"允许写入"。工具列表里没有写操作。连接器不提供"执行任意命令"。新增组件时必须同时交出读方法、闸门，以及"写操作被拒绝且没有发出网络请求"的测试，否则不接入。

### 6.1 检查顺序

工具实现固定按下列顺序执行，跳过即为缺陷：

1. 按 `name` 读配置（单条主键读，不缓存）。
2. 校验存在、启用、类型匹配。不满足抛 `TARGET_*` 错误。
3. 校验作用域：库、索引、topic、项目、vhost、key 前缀，不在范围的抛 `SCOPE_DENIED`。
4. 过闸门白名单与危险清单：命令、SQL 语法树、HTTP 方法+路径、聚合阶段、危险与高开销判定（6.6）。白名单不通过抛 `GUARD_REJECTED`，危险判定不通过抛 `DANGEROUS_OPERATION`，此时都还没有建立连接。
5. 建立或复用连接；组件支持会话级只读时（MySQL）先打开。
6. 发请求，边读边截断到上限（8.3）。
7. 按统一包络包装返回（8.1）。

第 4 步必须发生在第 5 步之前。任何"先连上再判断"的写法都违反本文。

### 6.2 闸门接口

每个组件一个纯函数：不联网、不读数据库、可单测。调用方只执行它返回的规范化结果。

```python
@dataclass(frozen=True)
class Decision:
    allowed: bool
    error_code: str | None = None   # GUARD_REJECTED / DANGEROUS_OPERATION
    reason: str | None = None       # 内部拒绝码，例如 "mysql.multi_statement"
    detail: str | None = None       # 人读说明，不含密钥
    normalized: Any | None = None   # 解析后的操作，连接器据此执行

def allow(normalized=None) -> Decision: ...
def guard_rejected(reason: str, detail: str) -> Decision: ...
def dangerous(reason: str, detail: str) -> Decision: ...
def require(decision: Decision) -> Any: ...  # 拒绝时抛 GuardRejected（带错误码）

def check_sql(sql: str) -> Decision: ...                      # MySQL
def check_mongo_command(command: str, doc: dict) -> Decision: ...
def check_mongo_pipeline(pipeline: list[dict]) -> Decision: ...
def check_http(method: str, path: str, body: dict | None = None) -> Decision: ...
def check_gitlab(method: str, path: str) -> Decision: ...
def check_rabbit(method: str, path: str) -> Decision: ...
def check_kafka(action: str, request: dict) -> Decision: ...
def check_cls(action: str, request: dict) -> Decision: ...
def check_redis(command: str, args: list) -> Decision: ...
```

管理/变更类命令优先由白名单拦截（``GUARD_REJECTED``）；只读但高开销的操作由危险清单拦截（``DANGEROUS_OPERATION``）。闸门常量集中在 ``guards/forbidden.py``，不从系统配置读取。

约束：

- 解析失败、语义不确定、不在白名单，一律拒绝；拒绝码用于测试与日志，不直接展示给模型。
- 闸门函数不 import 任何连接库，防止"顺手发个请求"。
- 规范化结果可以携带解析后的语法树或命令参数，但不得携带任何密钥。
- MySQL 的 `check_sql` 用 sqlglot（`dialect="mysql"`）解析后按节点类型判定，不做字符串前缀匹配。

### 6.3 各组件白名单

#### MySQL

只允许单条 `SELECT`、`SHOW`、`DESCRIBE`，以及内层语句同样属于这个白名单的 `EXPLAIN`。用 sqlglot 以 `dialect="mysql"` 解析语法树，按节点白名单判定；以 `SELECT` 开头的字符串不能作为放行依据。

- 解析失败、`sqlglot.parse` 返回多于一个语句、任一语句不在白名单，一律拒绝。
- 允许的节点类型：`Select`（含 `Union` 与子查询）、`Show`、`Describe`。`Show` 再按命令关键字二次白名单：`TABLES`、`COLUMNS`、`FULL COLUMNS`、`INDEX`、`KEYS`、`CREATE TABLE`、`STATUS`、`VARIABLES`、`PROCESSLIST`、`DATABASES`、`TABLE STATUS`。`EXPLAIN` 的内层语句复用同一套判定，内层不合法同样拒绝。
- 白名单只认解析后的结构，不接受"字符串前缀匹配"或"正则粗筛"作为兜底；sqlglot 版本在实现时锁定，并针对上述节点写拒绝用例。

拒绝多语句、`INSERT`、`UPDATE`、`DELETE`、`REPLACE`、DDL、`CALL`、`DO`、`SET`、`HANDLER`、`LOCK`、`SELECT ... INTO OUTFILE`、`INTO DUMPFILE`、`INTO` 变量、`FOR UPDATE`、`LOCK IN SHARE MODE`、`LOAD_FILE`。解析失败即拒绝。

每条连接在执行语句前把本会话设为事务只读（MySQL 的 `SET SESSION TRANSACTION READ ONLY`）。读写账号、甚至管理账号，在这个会话里执行写语句也会被 MySQL 拒绝。本服务不执行 `SET GLOBAL read_only`。

`SHOW` 类白名单明确包含 `SHOW PROCESSLIST`，供 `mysql_processlist` 使用；`SHOW` 之外的管理语句（如 `SET`、`FLUSH`、`KILL`）仍拒绝。

schema 发现工具（`mysql_tables`、`mysql_describe`）只用 `SHOW TABLES` / `SHOW COLUMNS` / `SHOW INDEX`，不查 `information_schema`：那是跨库系统库，会绕开允许库列表，也容易被用来拼出任意元数据查询。

#### Mongo

只允许 `find`、`aggregate`、`count`、`distinct`、`collStats`、`dbStats`、`listCollections`、`listIndexes`、`ping`、`serverStatus`、`currentOp`。`find` 必须带过滤条件。聚合阶段只允许 `$match`、`$project`、`$group`、`$sort`、`$limit`、`$lookup`；`$group` 与 `$lookup` 之前必须先有 `$match`，否则整条拒绝。

拒绝 `insert`、`update`、`delete`、`findAndModify`、`bulkWrite`、`drop`、建索引、`mapReduce`、`eval`，以及聚合里的 `$out`、`$merge`。Mongo 没有"特权账号也写不进去"的会话开关，因此命令名和聚合阶段的白名单就是硬边界。连接器只实现上述读方法，发出前再检查一次。

`mongo_collections` 只用 `listCollections` 与 `collStats`，不执行 `find` 空条件计数。

`$where`、`$function`、`$accumulator` 等 JS 执行、`allowDiskUse: true`、`hint` 一律拒绝。

#### Elasticsearch

只发出 `GET`、`HEAD`，以及路径限于 `_search`、`_count` 的 `POST`。其余路径限于集群健康、索引统计和 mapping 读取。

拒绝 `PUT`、`DELETE`、`PATCH`，以及 `_bulk`、`_update`、`_update_by_query`、`_delete_by_query`、`_reindex`、建索引、改别名。API Key 即使具备写权限，这些请求也不会发出。

`es_mapping` 只发 `GET /{index}/_mapping` 与 `GET /{index}/_settings`，索引须在允许列表内。

#### Redis

命令白名单：`PING`、`GET`、`MGET`、`STRLEN`、`EXISTS`、`TYPE`、`TTL`、`PTTL`、`SCAN`、`HGET`、`HMGET`、`HLEN`、`HSCAN`、`LLEN`、`LRANGE`、`SCARD`、`SMEMBERS`、`ZCARD`、`ZRANGE`、`INFO`、`SLOWLOG GET`、`DBSIZE`、`MEMORY USAGE`。列表、集合、有序集合的返回条数受该目标的上限约束。`SMEMBERS` 这类无界集合命令先用 `SCARD` 探测，超过上限拒绝；`LRANGE` / `ZRANGE` 的 end 为 -1 视为无界，直接拒绝。

其余命令一律拒绝，包括 `SET`、`DEL`、`GETSET`、`GETDEL`、`FLUSHALL`、`FLUSHDB`、`CONFIG`、`DEBUG`、`EVAL`、`EVALSHA`、`SCRIPT`、`KEYS`、`SORT`、`MIGRATE`、`RESTORE`、`ACL`、`SHUTDOWN`、`SUBSCRIBE`。Redis 主库不会因为会话设置而拦住一个有写权限的账号，所以未列入白名单的命令在客户端就被丢弃，不会发送。

#### GitLab

只发 `GET`：搜代码、读文件、blame、读提交和流水线状态。创建问题、评论、合并请求、触发流水线、改文件、改项目设置都不会发出。Token 即使是完整的 `api` 权限也一样。

#### RabbitMQ

Management API 只发 `GET`，读取队列深度、消费者数量、未确认数和连接摘要。拒绝 purge、发布、ack 和修改策略。不使用会把消息从队列中取走的 AMQP `basic.get` 和 `basic.consume`。

#### Kafka

只使用描述类管理接口，以及按分区和 offset 的有限拉取。拉取使用 assign 和 seek，不加入已有消费组，不提交 offset。代码路径里不创建生产者。拒绝创建或删除 topic、修改配置、删除记录、改写消费组 offset。

#### CLS

只调用检索和只读描述：搜索日志、取一条日志的上下文、列出已授权主题。拒绝上传日志、删除或修改主题、创建或删除导出任务。

### 6.4 拒绝用例矩阵

每个组件至少覆盖表中三类用例；拒绝路径必须断言"没有发出网络请求"（6.5）。

| 组件 | 允许（正例） | 拒绝（直接写） | 拒绝（伪装成读） |
|---|---|---|---|
| MySQL | 单条 `SELECT 1`、`SHOW TABLES`、`SHOW COLUMNS`、`SHOW PROCESSLIST`、`EXPLAIN SELECT ...` | `UPDATE t SET a=1`、`DELETE FROM t`、`CREATE TABLE t (...)` | `SELECT 1; DROP TABLE t`、`SELECT ... INTO OUTFILE '/tmp/x'`、`SELECT ... FOR UPDATE`、`CALL p()` |
| Mongo | `find` 带过滤、`listCollections`、`collStats`、`aggregate` 只含 `$match`/`$limit` | `insert`、`update`、`delete`、`drop` | `aggregate` 含 `$out`/`$merge`、`findAndModify`、`eval` |
| Elasticsearch | `GET /_cluster/health`、`GET /idx/_mapping`、`POST /idx/_search` | `PUT /idx`、`DELETE /idx`、`POST /_bulk` | `POST /idx/_update_by_query`、`POST /_reindex`、`POST /idx/_delete_by_query` |
| Redis | `GET k`、`SCAN 0 COUNT 10`、`INFO` | `SET k v`、`DEL k`、`FLUSHALL` | `EVAL ...`、`CONFIG SET ...`、`KEYS *`、`SORT` |
| GitLab | `GET /projects/1/repository/files/...` | `POST /projects/1/issues`、`PUT .../repository/files/...` | 触发流水线 `POST .../pipeline`、改设置 `PUT .../projects/1` |
| RabbitMQ | `GET /api/queues`、`GET /api/overview` | `DELETE /api/queues/vhost/q`、`POST /api/exchanges/.../publish` | 改策略 `PUT /api/policies/...`、`POST .../get`（会取走消息） |
| Kafka | `DescribeTopics`、按分区 `assign+seek` 有限拉取 | `CreateTopics`、`DeleteTopics`、`DeleteRecords` | 加入消费组、提交 offset、`AlterConfigs` |
| CLS | `SearchLog`、`DescribeLogContext`、`DescribeTopics` | `UploadLog`、`DeleteTopic`、`CreateExportTask` | `ModifyTopic`、`DeleteExportTask` |

上表只覆盖白名单与写操作；危险与高开销用例见 6.6，两类拒绝都要断言错误码。

### 6.5 无网络请求的验证

- 单测：拒绝路径把连接工厂替换成"一调用就失败"的桩，断言闸门拒绝后桩未被调用；再对 socket 打桩做一次兜底。
- 集成：对本地假服务（计数端点）发起被拒绝的调用，断言计数不变。
- 每个拒绝用例同时断言错误码与"连接次数为 0"；6.6 的危险与高开销用例同样适用。

### 6.6 危险与高开销命令

绝对规则：即使命令通过了 6.3 的只读白名单，只要属于"管理/变更类"或"只读但开销不可控"，也一律拒绝。拒绝码 `DANGEROUS_OPERATION`。这条规则没有配置、环境变量或 target 开关可以放开；以后只允许按目标"再收紧"，不允许放宽。

判定分两类：

1. **管理/变更类**：改配置、加锁、复制、维护、管理命令。它们可能修改状态、阻塞其他会话或影响集群。
2. **开销放大类**：全表/全集合扫描、无界遍历、脚本或表达式执行、深度分页、大聚合、大结果集。它们不改状态，但单次调用就可能压垮生产。

兜底约束（只降低影响，不能把危险命令变成允许）：

- MySQL 连接建立后由服务端设置会话级 `transaction_read_only`、`max_execution_time`、`sql_select_limit`；用户 SQL 里不允许出现 `SET`。
- 每次工具调用受 `asyncio.timeout(timeout_s)`、行数上限、字节上限约束。
- Mongo 聚合强制 `maxTimeMS`；ES 限制分页窗口与 `size`；Redis 限制 `SCAN COUNT` 与元素条数；CLS 限制时间窗；Kafka 限制条数与字节。
- 每 target 并发由系统配置 `target_max_concurrency`（默认 10）控制。

各组件清单：

| 组件 | 拒绝：管理/变更类 | 拒绝：高开销/放大类 | 允许的替代 |
|---|---|---|---|
| MySQL | `SET`、`FLUSH`、`RESET`、`PURGE`、`KILL`、`ANALYZE`、`OPTIMIZE`、`CHECK`、`REPAIR`、`CHECKSUM TABLE`、`LOCK`/`UNLOCK`、`HANDLER`、`CALL`、`LOAD`/`CACHE INDEX`、`INSTALL`/`UNINSTALL`、`GRANT`/`REVOKE`、DDL、`SHUTDOWN`、`STOP/START REPLICA`、`CHANGE MASTER`；`information_schema`、`performance_schema`、`mysql`、`sys` 等系统库一律拒绝 | `EXPLAIN ANALYZE`（会真正执行）、`SELECT SLEEP()`/`BENCHMARK()`/`GET_LOCK()`/`RELEASE_LOCK()`、无 WHERE 却带 `ORDER BY`/`GROUP BY`/`DISTINCT`/聚合的 SELECT、`FOR UPDATE`/`LOCK IN SHARE MODE` | 先 `mysql_tables`/`mysql_describe` 看结构；查询补 WHERE 与 LIMIT；用不带 ANALYZE 的 `mysql_explain` 看计划 |
| Mongo | 写与管理命令（6.3 已拒）、`fsyncLock`/`fsyncUnlock`、`replSet*`、`shutdown`、`killOp`、`setParameter`、`compact`、`validate` | `$where`、`$function`、`$accumulator`（JS 执行）、`allowDiskUse: true`、`hint`、`find` 空过滤、`$group`/`$lookup` 前没有 `$match` | `mongo_collections` 看集合；先 `$match` 收口再 `$group`/`$lookup`；`limit` 与 `maxTimeMS` 由服务端强制 |
| Redis | `CONFIG`、`DEBUG`、`SCRIPT`、`FUNCTION`、`EVAL`/`EVALSHA`、`ACL`、`CLIENT`、`SHUTDOWN`、`REPLICAOF`/`SLAVEOF`、`FAILOVER`、`PSYNC`、`SAVE`/`BGSAVE`/`BGREWRITEAOF`、`WAIT`、`MULTI`/`EXEC`/`DISCARD`、`MONITOR`、`SUBSCRIBE`/`PSUBSCRIBE`、`PUBLISH`、`FLUSHALL`/`FLUSHDB`、`SWAPDB`、`MIGRATE`、`RESTORE`、`SORT`、`KEYS`、`CLUSTER` | 无界范围（`LRANGE 0 -1`、`ZRANGE 0 -1`、`SMEMBERS` 全量）一律拒绝；有界范围先用 `LLEN`/`SCARD`/`ZCARD` 探测，超过 `max_rows` 拒绝；`SCAN COUNT` ≤ 200；`SLOWLOG GET` count ≤ `max_rows` | `redis_scan` 游标分页；`redis_get` 单 key；先探测长度再取范围 |
| Elasticsearch | 非白名单方法/路径（6.3）、`_scripts`、`_snapshot`、`_cluster/settings`、`_nodes` 写、`_tasks` 写、`_reindex`、`_bulk` | 请求体含 `script`、`script_fields`、`scripted_metric`、`runtime_mappings`；`from + size > 10000`；`track_total_hits: true`；`size > max_rows`；`terms` 聚合 `size > 100`；索引 `_all`/`*` | `es_mapping` 看结构；用 `_count` 代替取全量；分页窗口内翻页 |
| Kafka | 管理写（6.3）：创建/删除 topic、改配置、删记录、提交 offset、加入消费组 | 拉取条数与字节双上限；只允许单分区；只能 seek 到保留范围内的位点（不得早于 low watermark） | 先 `kafka_lag`/`kafka_offsets` 看位点，再小范围 `kafka_peek` |
| GitLab | 非 GET（6.3） | 代码搜索必须带 term；项目限定在允许列表；文件按字节上限截断 | 用异常类名或日志原文缩小搜索范围 |
| RabbitMQ | 非 GET（6.3）、purge、publish、ack、改策略 | 队列列表按上限截断；不使用 `basic.get`/`basic.consume` | `rabbit_queues` 概览后再看单队列 |
| CLS | 写/导出/删除（6.3） | 必须带时间窗；单次窗口 ≤ 24h、默认 1h；条数上限 | 先缩小时间窗，再按 trace id 收口 |

实施与测试：

- 危险判定与白名单在同一次解析里完成，仍在建立连接之前；`guards/*` 依据结果返回 `DANGEROUS_OPERATION` 或 `GUARD_REJECTED`。
- 跨组件的高开销阈值（行、字节、超时、分页窗口、探测长度）由 `connectors/base.py` 统一执行。
- 禁止清单是代码里的常量（`guards/forbidden.py` 加各组件的补充），不从 `settings` 读取；系统配置里没有对应键。
- 拒绝用例：每个组件至少覆盖表中各一条，断言拒绝码与"连接次数为 0"。

## 7. 目标类型与字段

每一项目标都有公共项（4.2），下面是各类型额外字段。密钥与范围分开写。范围只缩小可读边界，不能把"绝对只读"放宽。账号可以是读写账号，调用时仍由闸门截住写操作。

键名以 `options.` 开头表示存于 `options_json`，以 `secret.` 开头表示存于 `secret_json`，网页不可回显。

### MySQL

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| 主机 | `options.host` | 是 | — | 主机名或 IP |
| 端口 | `options.port` | 否 | 3306 | 1–65535 |
| 用户 | `options.user` | 是 | — | |
| 密码 | `secret.password` | 是 | — | 保存后不回显 |
| 客户端证书 | `secret.client_cert` | 否 | 空 | PEM；与私钥必须同时提供 |
| 客户端私钥 | `secret.client_key` | 否 | 空 | PEM；加密落盘，当前不支持带口令私钥 |
| 默认库 | `options.default_db` | 是 | — | |
| 允许的库 | `options.allowed_dbs` | 否 | `[]` | 空表示只允许默认库 |
| 是否 SSL | `options.ssl` | 否 | false | |
| CA 证书 | `options.ca_pem` | 否 | 空 | PEM 文本；配置时 `ssl` 必须为 true，仅用于校验服务端证书 |
| 允许 PROCESSLIST | `options.allow_processlist` | 否 | false | 默认关闭；开启后 PROCESSLIST 可看到其他库/用户会话 |

查询强制补上 `LIMIT`，并设置语句执行超时。语句种类、会话只读见 6.3。

### Mongo

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| 认证方式 | `options.auth_mode` | 是 | none | none / password / uri；旧 target 缺失时按 uri→password→none 推断 |
| URI | `secret.uri` | 条件 | — | auth_mode=uri 必填；用户/密码里未转义的 `@`、`:`、非法 `%` 由服务端自动做百分号编码（已有 `%XX` 保留），加密保存 |
| 主机 | `options.host` | 条件 | — | none/password 模式必填；uri 模式必须留空 |
| 端口 | `options.port` | 否 | 27017 | |
| 用户 | `options.user` | 否 | — | 与 URI 互斥 |
| 密码 | `secret.password` | 条件 | — | password 模式必填；uri 模式必须留空 |
| 认证库 | `options.auth_source` | 否 | admin | password 模式使用 |
| 是否 TLS | `options.tls` | 否 | false | |
| CA 证书 | `options.ca_pem` | 否 | 空 | PEM；配置时必须启用 TLS |
| 客户端证书 | `secret.client_cert` | 否 | 空 | PEM；与私钥同时提供 |
| 客户端私钥 | `secret.client_key` | 否 | 空 | PEM；加密保存，不支持带口令私钥 |
| 允许的库 | `options.allowed_dbs` | 是 | — | 空表示拒绝全部，必须显式列；`system.*` 集合仍拒绝 |

`find` 必须带过滤条件，空条件视为扫全表并拒绝。聚合设置 `maxTimeMS`。允许的阶段和写命令的拒绝见 6.3。

认证方式：`none` / `password` / `uri`。X.509、replica set、`mongodb+srv` 以及 LDAP/AWS IAM/OIDC 等高级选项通过 `auth_mode=uri` 的完整连接串透传；其中 X.509 与单节点 replica set 已用真实 Docker 验证，LDAP/AWS IAM/OIDC/SRV 仍需企业版/云/DNS 环境。

### Elasticsearch

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| 地址列表 | `options.hosts` | 是 | — | 至少一个，多行填写 |
| 用户名 | `options.username` | 二选一 | — | 与 API Key 互斥 |
| 密码 | `secret.password` | 二选一 | — | |
| API Key | `secret.api_key` | 二选一 | — | |
| 客户端证书 | `secret.client_cert` | 否 | 空 | PEM；与私钥必须同时提供 |
| 客户端私钥 | `secret.client_key` | 否 | 空 | PEM；加密落盘，当前不支持带口令私钥 |
| 允许的索引 | `options.allowed_indices` | 是 | — | 空表示拒绝；`_all` 与单独 `*` 不接受 |
| 校验 TLS | `options.verify_tls` | 否 | true | |
| CA 证书 | `options.ca_pem` | 否 | 空 | PEM 文本；配置时 `verify_tls` 必须为 true，仅用于校验服务端证书 |

搜索的 `size` 不超过该目标的返回上限。允许的 HTTP 方法和路径见 6.3。

### Redis

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| 主机 | `options.host` | 是 | — | |
| 端口 | `options.port` | 否 | 6379 | |
| 密码 | `secret.password` | 否 | — | |
| ACL 用户名 | `options.username` | 否 | — | Redis 6+ ACL；填写时密码必填 |
| DB | `options.db` | 否 | 0 | 0–15 |
| 协议版本 | `options.protocol` | 否 | 2 | 2=RESP2（默认，兼容 Redis < 6.0 与 Codis/Twemproxy 等代理）；3=RESP3，仅服务端 ≥ 6.0 且确需时 |
| 是否 TLS | `options.tls` | 否 | false | |
| CA 证书 | `options.ca_pem` | 否 | 空 | PEM；配置时必须启用 TLS |
| 客户端证书 | `secret.client_cert` | 否 | 空 | PEM；与私钥同时提供 |
| 客户端私钥 | `secret.client_key` | 否 | 空 | PEM；加密保存 |
| key 前缀 | `options.key_prefix` | 否 | `""` | 空表示不限；非空只读此前缀下的 key |

`SCAN` 带 `COUNT` 上限。列表、集合、哈希、有序集合的返回条数受该目标上限约束。命令白名单见 6.3。

客户端默认使用 RESP2（`protocol=2`）：redis-py 8.0 起库默认 RESP3，连接时先发 `HELLO 3`，而 Redis < 6.0 与 Codis/Twemproxy 等代理不认该命令。target 未配置 `options.protocol` 时按 2 处理；只有服务端 Redis ≥ 6.0 且确需 RESP3 特性时才设为 3。若服务端返回 `unknown command 'HELLO'`，连接器会提示把该目标的协议版本改回 2。

### GitLab

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| 实例地址 | `options.base_url` | 是 | — | 例如 `https://gitlab.example.com` |
| 私人 Token | `secret.token` | 是 | — | 只发 GET，Token 权限更大也一样 |
| 允许的项目 | `options.allowed_projects` | 是 | — | 项目路径列表，空表示拒绝 |

列表之外的项目不读。调用只发 `GET`，见 6.3。

### RabbitMQ

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| Management 地址 | `options.management_url` | 是 | — | 例如 `http://host:15672` |
| 用户 | `options.user` | 是 | — | |
| 密码 | `secret.password` | 是 | — | |
| 允许的 vhost | `options.allowed_vhosts` | 是 | — | 空表示拒绝 |

只通过 Management API 的 `GET` 查看队列和连接，见 6.3。

### Kafka

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| bootstrap 地址 | `options.bootstrap_servers` | 是 | — | `host:9092` 列表 |
| 安全协议 | `options.security_protocol` | 否 | PLAINTEXT | PLAINTEXT / SSL / SASL_PLAINTEXT / SASL_SSL |
| SASL 机制 | `options.sasl_mechanism` | 条件 | PLAIN | PLAIN / SCRAM-SHA-256 / SCRAM-SHA-512；SASL 协议必填 |
| SASL 用户 | `options.sasl_user` | 条件 | — | 同上 |
| SASL 密码 | `secret.sasl_password` | 条件 | — | 同上 |
| CA 证书 | `options.ca_pem` | 否 | 空 | 仅 SSL / SASL_SSL |
| 客户端证书 | `secret.client_cert` | 否 | 空 | 仅 SSL / SASL_SSL |
| 客户端私钥 | `secret.client_key` | 否 | 空 | 仅 SSL / SASL_SSL |
| 允许的 topic | `options.allowed_topics` | 是 | — | 空表示拒绝 |

抽取条数受该目标上限约束。不加入消费组、不提交 offset、不创建生产者，见 6.3。

### CLS

| 字段 | 键 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| 地域 | `options.region` | 是 | — | 例如 `ap-guangzhou` |
| SecretId | `secret.secret_id` | 是 | — | |
| SecretKey | `secret.secret_key` | 是 | — | |
| 允许的日志主题 | `options.allowed_topics` | 是 | — | `日志集/topic` 列表，空表示拒绝 |
| 默认时间窗 | `options.default_window_minutes` | 否 | 60 | 1–1440 |
| 最大时间窗 | `options.max_window_minutes` | 否 | 1440 | 不超过 1440 |

搜索必须带时间窗，默认不超过 1 小时，单次上限 24 小时。只调用检索和只读描述，见 6.3。

### 范围空值语义

| 范围字段 | 空值含义 |
|---|---|
| MySQL `allowed_dbs` | 只允许 `default_db` |
| Mongo `allowed_dbs` | 拒绝全部 |
| Elasticsearch `allowed_indices` | 拒绝全部 |
| Redis `key_prefix` | 不限前缀（命令白名单仍是硬边界） |
| GitLab `allowed_projects` | 拒绝全部 |
| RabbitMQ `allowed_vhosts` | 拒绝全部 |
| Kafka `allowed_topics` | 拒绝全部 |
| CLS `allowed_topics` | 拒绝全部 |

## 8. MCP 工具

### 8.1 返回包络

所有工具成功时返回同一个 JSON 对象；失败按 8.2 抛 `ToolError`，不返回半截结果。

```json
{
  "target": "order-mysql",
  "type": "mysql",
  "summary": "SELECT id, status FROM orders WHERE status = 'paid' LIMIT 100",
  "time_range": null,
  "returned": 12,
  "truncated": false,
  "truncation": null,
  "elapsed_ms": 23,
  "rows": [{"id": 1, "status": "paid"}],
  "stats": null,
  "notes": []
}
```

| 键 | 类型 | 说明 |
|---|---|---|
| `target` | string | 目标名 |
| `type` | string | 目标类型 |
| `summary` | string | 本次调用的可读摘要（SQL、查询、路径），截断到 200 字符，不含密钥 |
| `time_range` | object / null | `{"from": "...Z", "to": "...Z"}`；日志类必填，其他为 null |
| `returned` | int | 返回条数 |
| `truncated` | bool | 是否截断 |
| `truncation` | object / null | 截断时 `{"reason": "rows" \| "bytes", "limit": n}` |
| `elapsed_ms` | int | 服务端耗时 |
| `rows` | array\<object\> | 条目化结果；空结果为 `[]` |
| `stats` | object / null | 非条目化结果（健康、聚合统计） |
| `notes` | array\<string\> | 人读提示，例如"仅返回前 100 行" |

规则：

- 顶层键固定；工具特有的内容只能放进 `rows` 或 `stats`，不新增其他顶层键。
- 返回 dict，由 MCP 结构化输出承载；不返回 Markdown 文本。
- 不返回主机、账号、连接串、密钥；`summary` 里也不出现。
- 时间一律 UTC、ISO8601、带 `Z`。
- 空结果 `rows=[]`、`returned=0`、`truncated=false`。
- 截断必须如实标记，并在 `notes` 里说明缺了什么；不允许把残缺结果当全量返回。

### 8.2 错误码

失败一律 `raise ToolError("CODE: message")`，不返回半截结果。message 不含密钥与连接串，也不直接外抛上游原始异常（可能带凭证）。

| code | 场景 | 模型侧建议 |
|---|---|---|
| `ENVIRONMENT_REQUIRED` | 登记了多个环境，但调用没传 `environment` | 先 `systems_status`，再带上 key |
| `ENVIRONMENT_NOT_FOUND` | 调用标识未登记 | 用 `systems_status` 对照展示名 |
| `ENVIRONMENT_DISABLED` | 环境已停用 | 让用户确认是否启用；不要改查别的环境 |
| `TARGET_NOT_FOUND` | 该环境里没有这个名称 | 让用户去网页登记 |
| `TARGET_DISABLED` | 目标已停用 | 让用户确认是否启用 |
| `TARGET_TYPE_MISMATCH` | 工具与目标类型不符 | 换工具或换目标 |
| `NO_ENABLED_TARGET` | 该类型还没有启用目标 | 提示去网页登记 |
| `INVALID_ARGUMENT` | 参数缺失、越界、时间窗超限 | 修正参数 |
| `GUARD_REJECTED` | 只读白名单拒绝：写操作或无法解析 | 改写成只读语句 |
| `DANGEROUS_OPERATION` | 危险或高开销命令（6.6）：管理/变更类、全表扫描、脚本执行、深度分页等 | 缩小范围或换更安全的工具 |
| `SCOPE_DENIED` | 超出库、索引、topic、项目、vhost 范围 | 缩小范围或让用户扩范围 |
| `UPSTREAM_NOT_FOUND` | 上游 404：库、索引、文件不存在 | 核对名称 |
| `UPSTREAM_TIMEOUT` | 超时，含目标并发等待超时 | 缩小时间窗或稍后重试 |
| `UPSTREAM_UNAVAILABLE` | 连接失败、连接中断、上游 5xx、连接数满 | 让用户检查目标连通性，稍后重试 |
| `UPSTREAM_QUERY_ERROR` | 上游拒绝了查询：SQL 语法/字段/表不存在、Mongo 命令或管道非法、ES 查询 DSL 非法、Redis 命令参数错误 | 修正 SQL / 管道 / DSL / 命令参数，不要等服务恢复 |
| `UPSTREAM_AUTH` | 上游认证或授权失败：账号密码、库权限、认证方式 | 让用户核对密钥与授权，不要重试 |
| `STORAGE_UNAVAILABLE` | 配置库不可用 | 提示联系维护者 |
| `SECRET_UNAVAILABLE` | 该目标的密钥解不开（密钥缺失、被替换或密文损坏） | 让用户到网页重新录入密钥 |
| `INTERNAL` | 未预期异常 | 附 trace id，重试或上报 |

### 8.3 上限与截断

- 行数：上游支持 `limit` 的工具取 `min(请求值, 目标上限) + 1` 作为哨兵，多出一条即 `truncated=true`、`reason="rows"`；schema/list 这类没有 limit 参数的接口只能返回后按上限截断（此时无法区分"恰好等于上限"与"还有更多"）。
- 字节：序列化 `rows` 时增量累计，超过 `max_bytes` 即停，`reason="bytes"`；显式截断同样受字节上限约束。Redis 字符串先 `STRLEN`，超过目标 `max_bytes` 直接拒绝，避免先读入大 value。
- 时间：整个工具调用（含排队）包在 `asyncio.timeout(timeout_s)` 内；上游超时映射 `UPSTREAM_TIMEOUT`。
- 并发：每 target 的并发上限读系统配置 `target_max_concurrency`（默认 10），用 Semaphore 控制；工具调用与测试连接共用这个闸门，排队时间计入该 target 的超时。
- 行数、字节、时间三者先触达者为准；截断信息必须回传。
- 上限优先于结果完整性；不允许为了"取全"绕过上限。

### 8.4 第一批：日志对上代码

三批工具的闸门列只写白名单与范围；所有工具同时受 6.6 危险与高开销规则约束，命中时返回 `DANGEROUS_OPERATION`。

| 工具 | 参数 | 返回 | 闸门与范围 | 上限 |
|---|---|---|---|---|
| `systems_status` | `environment` 可空 | 不传时 `rows` 是环境：key、title、enabled、targets、enabled_targets。传入 key 时 `rows` 是该环境的目标：name、type、enabled、scope、last_test_*。`scope` 只含该类型授权的库/索引/主题/vhost/项目/Redis 前缀，不含连接串或密钥。包络仍是 `target="*"`、`type="all"`，不新增顶层键 | 只读配置库，不外呼。未知 key 返回 `ENVIRONMENT_NOT_FOUND` | 全部环境，或该环境的全部目标 |
| `cls_search` | `target`、`query`、`from`、`to`（必填）、`topic`（唯一授权时可省略）、`limit`、`offset` | `rows`: time、topic、content 等 | `SearchLog`；主题须在允许列表；时间窗必填 | 窗口默认 1h、上限 24h；条数上限 |
| `cls_context` | `target`、`topic`、`log_id`、`btime`、`pkg_log_id`、`before=10`、`after=10` | `rows`: 同一条日志前后若干条 | `DescribeLogContext`；主题须在允许列表 | before/after 各 ≤ 20 |
| `gitlab_search_code` | `target`、`query`、`project`（可空）、`ref`、`limit=20`、`page=1` | `rows`: project、path、line、snippet | 只发 GET；项目在允许列表 | 条数上限 |
| `gitlab_get_file` | `target`、`project`、`path`、`ref` | `rows`: path、ref、content | 只发 GET；项目在允许列表 | 字节上限 |
| `gitlab_blame` | `target`、`project`、`path`、`ref`、`line_from`、`line_to` | `rows`: 提交、作者、时间、行号范围 | 只发 GET；项目在允许列表 | 条数上限 |

第一批上线后补充两条实现约定：

- CLS 的 `topic` 使用网页登记值；值里带 `/` 时（如 `日志集/topic`），调用 CLS API 时取最后一段作为 `TopicId`。`cls_search` 必须指定 `topic`；目标只授权了一个主题时可省略，自动使用该主题。
- `gitlab_search_code` 不填 `project` 时，只在目标授权的项目列表内逐个搜索，不发起全局搜索；跨项目结果总量仍受 `limit` 与目标上限约束。

### 8.5 第二批：数据面

| 工具 | 参数 | 返回 | 闸门与范围 | 上限 |
|---|---|---|---|---|
| `mysql_tables` | `target`、`db`（可空，默认 `default_db`） | `rows`: 表名、类型（基表/视图）、行数估算、注释 | `SHOW TABLES` 等价；库在允许列表 | 目标行数 |
| `mysql_describe` | `target`、`table`、`db`（可空） | `rows`: 字段名、类型、是否可空、键、默认值、额外信息；`stats`: 索引 | `SHOW COLUMNS` / `SHOW INDEX`；表与库在允许范围 | 目标行数 |
| `mysql_query` | `target`、`sql`、`limit`（不超过目标上限） | `rows`；`stats`: db、limit | 单条 SELECT/SHOW/DESCRIBE/EXPLAIN；库在允许列表；强制补 LIMIT | 目标行数/字节 |
| `mysql_explain` | `target`、`sql` | `rows`: 执行计划行 | `EXPLAIN` 内层语句同白名单；库在允许列表 | 目标行数 |
| `mysql_processlist` | `target` | `rows`: 会话列表 | 等价 `SHOW PROCESSLIST`，只读 | 目标行数 |
| `mongo_collections` | `target`、`db`（必填） | `rows`: 集合名、类型、文档数估算、索引数 | `listCollections` + `collStats`；库在允许列表 | 目标行数 |
| `mongo_find` | `target`、`db`、`collection`、`filter`（必填非空）、`projection`、`sort`、`limit` | `rows`: 文档 | `find`；库在允许列表；过滤器必填 | 目标行数 |
| `mongo_aggregate` | `target`、`db`、`collection`、`pipeline`、`limit` | `rows`: 聚合结果 | 阶段白名单；`maxTimeMS`；库在允许列表 | 目标行数/字节 |
| `mongo_stats` | `target`、`db`、`collection`（可空） | `stats`: 统计 | `collStats`/`dbStats`；库在允许列表 | 单次 |
| `es_mapping` | `target`、`index` | `rows`: 字段、类型、分词器；`stats`: 分片与副本设置 | `GET /{index}/_mapping`、`_settings`；索引在允许列表 | 字节上限 |
| `es_search` | `target`、`index`、`query`、`from`、`size`、`sort`、`search_after` | `rows`: hit 源（含 `_sort`）；`stats`: total、took | `POST .../_search`；索引在允许列表；size ≤ 目标上限；根级聚合仅允许有界 terms | 目标行数/字节 |
| `es_health` | `target` | `stats`: status、节点数、分片等 | `GET _cluster/health` | 单次 |
| `es_index_stats` | `target`、`index` | `rows`: 索引统计 | `GET .../_stats`；索引在允许列表 | 目标行数 |
| `redis_get` | `target`、`key` | `rows`: key、type、ttl、value | 命令白名单；key 前缀限制 | 字节上限 |
| `redis_scan` | `target`、`pattern`、`count`、`cursor` | `rows`: key 列表；`stats`: cursor | `SCAN` 带 COUNT 上限；key 前缀限制 | 目标行数 |
| `redis_info` | `target`、`section` | `stats`: INFO 键值 | 只读 INFO | 字节上限 |
| `redis_slowlog` | `target`、`count=10` | `rows`: 慢日志条目 | `SLOWLOG GET` | 目标行数 |

第二批上线后补充实现约定：

- `mysql_query` 对 `SELECT` 用 sqlglot 重写 `LIMIT`（取请求值与目标 `max_rows` 较小者）；`SHOW` / `DESCRIBE` / `EXPLAIN` 不补 LIMIT。`mysql_tables` / `mysql_describe` 只用 `SHOW` 类语句，不查 `information_schema`；库引用必须在 `allowed_dbs` 内，`SHOW DATABASES` 在目标级被拒绝。
- `mongo_aggregate` 在管道末尾追加 `$limit`，并统一带 `maxTimeMS`；`mongo_find` 同样带 `maxTimeMS`。`mongo_collections` 用 `listCollections` + `collStats`，不执行空条件 `find`。
- `es_search` 的 `size` 不能超过目标 `max_rows`（超过直接 `DANGEROUS_OPERATION`）；`size` 不能为负数；`from + size` 仍受 10000 窗口限制。根级聚合仅允许 `terms` 且 size ≤ 100。`es_mapping` 只发 `GET _mapping` 与 `GET _settings`。
- `redis_get` 按类型做有界读取：list/set/zset 先探测长度，超过 `max_rows` 直接拒绝；hash 用 `HSCAN`。配置了 `key_prefix` 时，`redis_scan` 的 `pattern` 也必须以该前缀开头。`redis_slowlog` 的 count 取请求值与 `max_rows` 较小者。

### 8.6 第三批：消息面

| 工具 | 参数 | 返回 | 闸门与范围 | 上限 |
|---|---|---|---|---|
| `rabbit_queues` | `target`、`vhost`（可空） | `rows`: 队列、消息数、未确认、消费者 | Management API GET；vhost 在允许列表 | 目标行数 |
| `rabbit_queue` | `target`、`vhost`、`queue` | `rows`: 单队列详情 | 同上 | 单条 |
| `kafka_lag` | `target`、`group`、`topic`（可空） | `rows`: 组、topic、分区、位点、滞后 | 只读描述消费组；topic 在允许列表 | 目标行数 |
| `kafka_offsets` | `target`、`topic` | `rows`: 分区、low、high | 只读描述；topic 在允许列表 | 目标行数 |
| `kafka_peek` | `target`、`topic`、`partition`、`offset`、`limit` | `rows`: 消息 | `assign` + `seek` 有限拉取；不加入消费组、不提交 offset、不建生产者 | 目标行数/字节 |

第三批上线后补充实现约定：

- `rabbit_queues` 不传 `vhost` 时只遍历目标授权的 vhost，逐个 `GET /api/queues/{vhost}`，不做一次全量拉取后再过滤；`rabbit_queue` 只 `GET /api/queues/{vhost}/{queue}`。两者都只发 GET。
- `kafka_lag` 用 Admin API 读取消费组已提交位点，再用 `group_id=None` 的消费者读取分区 high watermark，计算滞后；不加入消费组、不提交 offset。
- `kafka_offsets` 用 `group_id=None` 的消费者读取各分区 low/high watermark。
- `kafka_peek` 用 `assign + seek` 单分区拉取；low watermark 由连接器硬校验，offset 早于 low 直接 `DANGEROUS_OPERATION`；不创建生产者、不提交 offset，条数受目标 `max_rows` 约束。

### 8.7 排查 prompt

提供一个 MCP prompt `investigate_error`，参数 `description`、`service`、`trace_id`、`time_range`（均可空，缺省由模型向用户确认）。该 prompt 在第二期上线；第 2 步的 schema 发现工具已在 M5（第三期数据面）上线，可直接使用。内容把推荐顺序写给模型：

1. 先用 `systems_status` 看清哪些目标可用、最近是否连通。
2. 需要写查询前先看结构：MySQL 用 `mysql_tables`、`mysql_describe`，Mongo 用 `mongo_collections`，Elasticsearch 用 `es_mapping`。不要凭猜写表名和字段名。
3. 有 trace id 时先 `cls_search` 按 trace id 搜；否则按服务名 + 时间窗搜。
4. 用异常类名、堆栈或日志原文调用 `gitlab_search_code`；命中后 `gitlab_get_file` 读代码，`gitlab_blame` 看最近改动。
5. 现象像慢查询或数据不一致，走 `mysql_explain`、`mysql_query`；缓存放 `redis_get`、`redis_scan`、`redis_info`；搜索放 `es_search`、`es_health`。
6. 现象像堆积或延迟，走 `rabbit_queues`、`kafka_lag`、`kafka_peek`。
7. 结论必须写明时间窗、目标、证据（工具返回的具体条目）；结果被截断要说明。
8. 证据不足就明确说缺什么，不猜、不编造行号与数值。
9. 全程只读，不尝试写操作。

关联由模型逐步调用完成，服务端不把八个系统一次扇出。

### 8.8 服务器说明

服务器说明（instructions）与 prompt 写同一套纪律：

- 八个组件绝对只读，且不能由调用方关闭。
- 日志与搜索必须带时间窗；优先使用 trace id。
- 拒绝全表扫描和无上限拉取；SQL 必须能补上 LIMIT。
- 查数据前先看结构（`mysql_tables`/`mysql_describe`/`mongo_collections`/`es_mapping`），不要凭猜写字段。
- 结果截断必须向用户说明。
- 工具只接受 `target` 名，不接受主机、DSN、账号、密码。
- 先 `systems_status`，再按现象选工具。

### 8.9 工具元信息

- 工具名等于函数名，短且稳定；客户端看到的形如 `mcp__drpanda__mysql_query`。
- 每个工具声明 `annotations={"readOnlyHint": True}`。
- 工具清单不随配置变化，不做动态注册；某类型无启用目标时返回 `NO_ENABLED_TARGET`。
- 每次调用按 `name` 读配置库，网页新增或停用立即生效，不用重启，也不用动态增删 MCP 工具。
- 工具名、参数名一旦发布不再改；确需改时同时改 prompt、服务器说明与本文。

## 9. 运行与可观测性

### 9.1 日志

- 用标准库 logging，级别由 `DR_PANDA_LOG_LEVEL` 控制，默认 INFO，输出到 stdout，一行一条。访问日志由本服务的 `http` 事件承担，不再使用 uvicorn 自带的访问行。
- 字段按需出现：`request`、`actor`、`tool`、`env`、`target`、`elapsed_ms`、`returned`、`error`，后面是一句说明。不含密钥、请求体、连接串和结果行。启动日志只写监听地址和数据库种类。
- 每个 HTTP 请求生成 8 位请求号，放进响应头 `X-Request-Id`，并写进该次工具审计摘要的末尾。`/static/`、图标和成功的 `/healthz` 只在 DEBUG 出现。5xx 记 WARNING。
- 工具调用结束时记一行：成功是 `tool.call` INFO；超时和上游失败是 `upstream.error` WARNING；配置库失败是 `store.error` WARNING；其它预期失败是 `tool.call` WARNING。未预期的异常是 `tool.call` ERROR，堆栈先脱敏。默认不打印 SQL。DEBUG 再附大约 120 字的脱敏参数开头。
- 事件还包括 `app.start`、`migrate.done`、`audit.cleanup`。网页上已经写入审计的配置变更不另打一条 INFO。

### 9.2 健康检查

`GET /healthz` 返回 `200 {"ok": true, "version": "...", "db": "ok"}`；配置库 ping（`SELECT 1`）失败返回 `503 {"ok": false, "db": "error"}`。健康检查不检查各排查目标，避免每次探活外呼八个系统。

### 9.3 连接器缓存与并发

- 按 target 缓存**连接器对象**（不是网络连接池），key 为 `(target_id, updated_at)`；配置一保存就丢弃旧对象，下次调用重建。具体网络客户端（httpx / asyncmy / motor / redis / kafka）仍由连接器在每次操作内创建与关闭。
- 进程内最多保留 32 个 target 连接器对象，LRU 淘汰最久未用并关闭；创建过程由进程内锁串行化，避免并发首次访问重复创建。
- 每 target 并发上限读系统配置 `target_max_concurrency`（默认 10，范围 1–50）；上限变化后重新构造该目标的信号量，下一次调用生效；等待时间计入该 target 的超时。
- 进程退出时关闭全部客户端与配置库引擎。
- 不缓存 target 配置：每次调用按主键读一次库足够轻，也避免多进程共用 MySQL/PostgreSQL 时读到过期配置。

### 9.4 关闭

收到 SIGINT/SIGTERM：停止接收新请求 → 等现有调用完成（最多 5 秒）→ 关排查客户端 → 关配置库引擎 → 退出 0。超过 5 秒打印 WARNING 后退出。

### 9.5 故障行为

| 情况 | 行为 |
|---|---|
| 配置库 URL 指向未安装驱动 | 启动失败，提示安装 `[mysql]` 或 `[postgres]` |
| 迁移失败 | 启动失败；SQLite 提示备份文件路径 |
| 密钥缺失或与库中密文不匹配 | 启动失败，提示恢复 `secret.key` 或 `DR_PANDA_SECRET_KEY` 备份，不静默生成新密钥 |
| 单个目标解密失败（密钥被换、密文损坏） | 该目标工具返回 `SECRET_UNAVAILABLE`，网页标注"密钥不可用，请重新录入"，其他目标不受影响 |
| 端口被占用 | 启动失败，提示改 `DR_PANDA_PORT` |
| 运行中配置库不可用 | 工具返回 `STORAGE_UNAVAILABLE`，网页 500 |
| 上游超时或不可用 | 对应错误码；不重试、不切换到其他 target |
| 目标已停用 | `TARGET_DISABLED` |
| 审计写失败 | 记 WARNING，工具结果照常返回 |
| 系统配置值非法（被手工改库） | 读取时回退到代码默认值并记 WARNING；网页显示默认值，允许重新保存修正 |
| 审计清理失败 | 记 WARNING，下一轮重试；不影响工具调用与网页 |

### 9.6 审计清理

- 保留天数读系统配置 `audit_retention_days`（默认 90，范围 1–3650），每轮清理前读取，改配置后无需重启。
- 周期任务：启动 60 秒后首跑，之后每 3600 秒一轮；进程退出时取消任务。
- 每轮从最早的记录开始，分批删除 `created_at < now - retention_days` 的审计，每批 1000 行，直到没有可删为止；单轮总耗时上限 5 分钟，超出留到下一轮。
- 清理只记日志（`audit.cleanup`，含删除条数与耗时），不写审计，避免审计表自增；删除是不可逆操作，日志里只记条数不记内容。
- 清理使用配置库连接，与工具调用互不影响；单进程部署天然只有一个清理实例。
- 第一版不做按人、按目标、按动作的差异化保留期。

## 10. 代码结构

实现时按下面拆开。网页、工具、连接器只通过 `ConfigStore` 读写配置，不接触具体数据库驱动。

```
src/dr_panda_mcp/
  __init__.py          main()：按 3.2 的启动序列执行
  __main__.py          python -m dr_panda_mcp 入口
  config.py            读取与校验环境变量，补全数据库 URL
  crypto.py            密钥加载（环境变量或 secret.key）、AES-256-GCM 加解密
  settings.py          系统配置默认值、键白名单、范围校验、读取与更新入口
  errors.py            错误码常量与 ToolError 映射
  server.py            FastMCP 实例、服务器说明、注册工具/prompt/网页路由、http_app
  runtime.py           运行时装配：引擎、迁移、密钥、ConfigStore；提供关闭
  web/
    routes.py          custom_route 注册 4.1 全部路由（含 /theme、/static/app.css）
    theme.py           三态主题 Cookie 与站内跳转校验
    assets.py          手写 CSS 的读取、ETag 与缓存响应
    static/app.css     设计 token、组件与响应式样式
    forms.py           表单解析与字段校验（纯函数）
    render.py          Jinja2 环境与页面渲染
    views.py           TargetView 组装（密钥只暴露"已设置字段名"）
    templates/         Jinja2 模板（列表、表单、确认页、settings.html），随包分发
  store/
    protocol.py        ConfigStore、Target、TargetDraft、SecretPatch、AuditEntry、Settings、异常
    models.py          SQLAlchemy 2 声明式表
    repository.py      异步实现，唯一写 SQL 的地方；唯一调用 crypto 的地方
    url.py             DATABASE_URL 解析、驱动补全、引擎创建（SQLite PRAGMA）
    migrate.py         Alembic 升级与迁移前 SQLite 备份（保留 5 份）
    alembic/           env.py、script.py.mako 与 versions/ 迁移脚本
  catalog.py           按 name 读配置、校验启用与类型、作用域、客户端池与失效
  guards/
    protocol.py        Decision 与各 check_* 签名
    forbidden.py       跨组件的危险与高开销命令常量（6.6）
    mysql.py mongo.py es.py redis.py gitlab.py rabbit.py kafka.py cls.py
  connectors/
    base.py            超时、行数/字节截断、包络包装
    mysql.py mongo.py es.py redis.py gitlab.py rabbit.py kafka.py cls.py
  tools/
    system.py systems_status
    logs.py cls_* 与 gitlab_*
    data.py mysql_* mongo_* es_* redis_*
    messages.py rabbit_* kafka_*
  prompts.py           investigate_error
  audit.py             审计写入、打码与按保留期清理
  masking.py           密钥、手机号、证件号打码
data/                  默认 SQLite、备份与 secret.key，不进 git
tests/                 见 12
scripts/smoke.py       冒烟：启动进程并探活
```

## 11. 依赖与工程准备

### 11.1 运行时依赖

| 包 | 用途 | 形态 |
|---|---|---|
| `fastmcp>=4.1.4` | MCP 服务、`custom_route`、`http_app` | 必需 |
| `sqlalchemy[asyncio]>=2.0` | 配置库 ORM 与异步引擎 | 必需 |
| `alembic` | 配置库迁移 | 必需 |
| `jinja2` | 网页模板（已定） | 必需 |
| `uvicorn` | 运行 `http_app` | 必需（FastMCP 传递依赖，仍显式声明） |
| `aiosqlite` | 默认 SQLite 异步驱动 | 必需 |
| `cryptography` | `secret_json` 的 AES-256-GCM 加解密 | 必需 |
| `sqlglot` | MySQL 语法树白名单（已定） | 必需，实现时锁定版本 |
| `httpx` | ES / GitLab / RabbitMQ 的 HTTP 探测 | 必需 |
| `asyncmy` | MySQL 异步驱动 | 可选 `dr-panda-mcp[mysql]` |
| `asyncpg` | PostgreSQL 异步驱动 | 可选 `dr-panda-mcp[postgres]` |
| `motor` | Mongo 异步驱动 | 可选 `dr-panda-mcp[mongo]` |
| `redis` | Redis 异步客户端 | 可选 `dr-panda-mcp[redis]` |
| `aiokafka` | Kafka 管理客户端 | 可选 `dr-panda-mcp[kafka]` |
| `tencentcloud-sdk-python-cls` | CLS 客户端 | 可选 `dr-panda-mcp[cls]` |

组件客户端库按需安装，未安装时服务仍能启动，测试连接返回明确错误。`uv sync --extra <name>` 是精确同步，会卸掉没有点名的其他 extra。补一个客户端用 `uv sync --extra <name> --inexact`，在运行服务的项目目录执行，装好后直接再测。一次装齐用 `uv sync --all-extras`。列表上的「安装」只对「客户端未安装」出现，由服务按目标类型执行这条命令，不接受页面传入的命令文本；装完立刻再测。同一时间只跑一个安装。审计清理用 asyncio 周期任务实现，不引入 APScheduler 等调度库。

### 11.2 开发依赖

| 包 | 用途 |
|---|---|
| `pytest`、`pytest-asyncio` | 单元与契约测试 |
| `ruff` | 可选，格式与静态检查 |

### 11.3 pyproject 必补项

- `description` 改为实际描述（当前是脚手架占位 `Add your description here`）。
- `[project.optional-dependencies]`：`mysql`、`postgres` 两组。
- `[dependency-groups]`：`dev` 下的测试依赖。
- `[tool.pytest.ini_options]`：`asyncio_mode = "auto"`，测试路径 `tests`。
- `[project.scripts]` 已存在，保持 `dr-panda-mcp = "dr_panda_mcp:main"`。
- Jinja2 模板放在包内 `web/templates/`，打包后做一次 `uv run` 冒烟，确认读得到模板。

### 11.4 仓库卫生

- `.gitignore` 补 `data/`（含 `data/backup/` 与 `data/secret.key`），与 5.1 的"`data/` 不进 git"一致。
- `README.md` 至少写明：一句话定位、启动命令、环境变量表（含 `DR_PANDA_SECRET_KEY` 与密钥备份提醒）、三个客户端配置示例、八类目标登记要点、系统配置页与两个可调项、绝对只读与危险命令规则、测试命令。
- 提交信息按 `feat: 配置台（第一期）` 这类格式；当前那次 `1` 只作历史保留，不回写。
- 第一期完成后打 tag `v1.1.0`，作为配置台可用的里程碑。

### 11.5 明确不引入

- Node 工具链、前端框架、CSS/JS 构建链。
- 第二套 ORM 或手写 SQL 方言分支。
- pydantic v1 兼容层。
- 除 fastmcp 之外的第二个 MCP 框架。

## 12. 测试与验收

### 12.1 分层

| 层 | 覆盖 | 手段 | 外部依赖 |
|---|---|---|---|
| 单元 | 闸门全矩阵、危险清单（6.6）、系统配置校验与白名单、URL 解析、打码、加解密与 AAD 绑定、表单校验、作用域校验、包络与错误码 | pytest | 无 |
| 存储契约 | 5.7 全部条目；第一期只跑 SQLite。MySQL/PostgreSQL 用同一套测试，但推迟到首次需要外部库时验收 | pytest + 临时库 | 无（第一期） |
| 网页 | 路由状态码、表单校验、密钥不回显、启停删、测试连接（mock 连接器）、`/healthz`、密钥不可用提示、系统配置页读写与非法值 | httpx ASGITransport | 无 |
| MCP | 工具清单稳定、`systems_status`、错误码（含 `DANGEROUS_OPERATION`）、拒绝路径无外呼、返回包络字段齐全 | `fastmcp.Client` 内存传输 | 无 |
| 审计清理 | 保留期边界（1/90/3650）、分批删除、非法配置回退默认、清理不写审计 | pytest + 临时库 | 无 |
| 冒烟 | 起 uvicorn → 客户端连 `/mcp` → 调 `systems_status` → `/healthz` | 脚本 | 本机端口 |

### 12.2 第一期验收清单

- [ ] `uv run dr-panda-mcp` 冷启动成功，`/healthz` 返回 ok。
- [ ] 网页可新建、编辑、启停、删除、测试连接八类目标；密钥不回显，编辑留空沿用、勾选清除生效。
- [ ] 配置变更与审计同事务提交；审计与日志中 grep 不到任何密钥明文。
- [ ] 密钥以密文落盘：直接查配置库原始行 grep 不到明文；换错密钥启动失败，单目标解密失败返回 `SECRET_UNAVAILABLE`。
- [ ] `/settings` 可读可写：默认值 90 天 / 10，非法值被拒；保存后审计有 `settings.update` 记录，并发与保留期在下一轮生效。
- [ ] 审计清理任务按保留期删除过期行，日志有 `audit.cleanup` 条数与耗时，且清理不产生新的审计行。
- [ ] 危险与高开销清单抽查通过：`SELECT SLEEP(10)`、`EXPLAIN ANALYZE`、无 WHERE 的 `ORDER BY`、`KEYS *`、`MONITOR`、`LRANGE 0 -1`、ES `script` 查询都被拒绝且无外呼。
- [ ] `/mcp` 上 `systems_status` 列出目标与最近测试结果，工具名稳定。
- [ ] 三个客户端均能连上 `/mcp` 并看到工具清单。
- [ ] `pytest` 全绿；拒绝路径"无外呼"断言通过。
- [ ] SQLite 契约测试通过；MySQL/PostgreSQL 契约测试未跑（推迟，见 14.3）。
- [ ] README 与本文状态同步更新。

### 12.3 测试约束

- 测试不连真实线上系统：连接器用桩或本地假服务，拒绝用例不产生真实请求。
- 不在测试夹具里写真实凭证；假凭证用固定占位值。
- 加解密测试用临时生成的密钥（每次测试新建），不读用户真实的 `secret.key` 或 `DR_PANDA_SECRET_KEY`。
- 审计清理测试用临时库与构造的过期行，不碰真实审计数据。
- 契约测试清理自己创建的数据；失败时不留脏库。

## 13. 分期

### 13.1 五期

任务拆分与验证目标见 [milestones.md](milestones.md)（M0–M7）。

1. **配置台。** HTTP 进程、网页的增删改、启用停用、密钥打码与加密落盘、配置审计、系统配置页（保留期、并发）、审计清理任务、八种类型的表单和测试连接、`/mcp` 上的 `systems_status`。配置库默认 SQLite；同一套迁移和 `ConfigStore` 通过 `DR_PANDA_DATABASE_URL` 用于 MySQL 和 PostgreSQL（两种库的契约测试推迟，见 14.3）。测试连接接入只读与危险两道闸门，并先落地 MySQL 的连接级兜底（事务只读、`max_execution_time`、`sql_select_limit`）。这一期结束时，人可以在网页里把连接配好、看到测试结果、改系统配置，三个客户端能连上并看到已登记目标。
   验收：12.2 全部满足。

2. **日志到代码。** `cls_search`、`cls_context`、GitLab 三个工具、`investigate_error`，以及 CLS 和 GitLab 的闸门、危险清单与拒绝测试。多数报错在这一期就可以查。
   验收：CLS 与 GitLab 拒绝用例通过；用真实（只读）凭证手测一次搜索到定位的完整链路。

3. **数据面。** MySQL、Mongo、Elasticsearch、Redis 的只读工具（含 `mysql_tables`、`mysql_describe`、`mongo_collections`、`es_mapping` 四个 schema 发现工具），以及各自的闸门、危险清单（6.6）和拒绝测试。
   验收：四类组件拒绝用例与"无外呼"断言通过；schema 工具能按允许范围列出库/表/字段/mapping；`mysql_explain` 在慢查询场景跑通。

4. **消息面。** RabbitMQ 队列，Kafka lag、位点、有限抽取，以及各自的闸门、危险清单和拒绝测试。
   验收：拒绝用例通过；`kafka_peek` 不加入消费组、不提交 offset 有测试兜住。

5. **首次安装与登录。** users 表、安装向导、网页 Session/CSRF、`/mcp` Bearer；审计记到 admin。
   验收：安装向导完成；网页未认证跳登录；`/mcp` 未认证 401；审计 actor=admin；工具名/包络不变。

### 13.2 第一期拆解顺序

1. `pyproject.toml`、依赖（含 `cryptography`、`sqlglot`）、`.gitignore`、README 地基。
2. `store/`：`crypto.py` → url → models（含 `settings` 表）→ alembic（含默认值初始化）→ repository → protocol，并让 5.7 契约测试在 SQLite 上通过。
3. `settings.py`（默认值、键白名单、范围校验）→ `catalog.py` 与作用域校验（纯函数 + 单测）。
4. `web/`：目标页、`/settings` 页、路由、表单、视图、Jinja2 模板、网页测试。
5. `guards/`：`forbidden.py` + sqlglot 版 MySQL 白名单与危险清单 + 八类连接器的"测试连接"最小只读实现；MySQL 连接级兜底。
6. `tools/system.py` 的 `systems_status` + MCP 内存测试。
7. `audit.py` 清理任务 + 冒烟脚本 + README + 本文状态更新。

## 14. 未决事项

以下问题仍未拍板，确认后写回本文再动代码。已拍板项（Jinja2、sqlglot、密钥加密、schema 发现工具、SQLite-only 契约测试、系统配置、审计保留期、目标并发、危险命令规则）已写入第 2 章与对应章节，不再重复列出。

| # | 问题 | 推荐 | 影响 |
|---|---|---|---|
| 1 | 密钥轮换与多 `kid` | 第一版只有 `k1`，不做轮换；以后加"新 kid 加密、旧 kid 解密"的在线轮换 | 换密钥需重录全部目标 |
| 2 | 密钥备份的辅助手段 | 只写 README 提醒，不提供备份命令；`secret.key` 与配置库一起备份 | 备份遗漏则密钥不可恢复 |
| 3 | MySQL/PostgreSQL 契约测试的触发时机 | 首次需要把配置库换成外部库时执行同一套测试 | 两种库在上线前未验收 |
| 4 | 危险清单是否支持按目标再收紧 | 以后支持"只收紧"的补充清单（例如某目标额外禁用一批命令），永不支持放宽 | 需要额外的表或字段，第一版不做 |

## 15. 这一版明确不做

- 多用户、角色管理、OAuth/OIDC，以及按人限制可用 target
- 写库、清队列、改消费位点、发消息、重启服务
- 按目标或全局关闭只读，以及把"执行任意命令"暴露给模型
- 模型可填写的主机、DSN、密码参数
- 独立的前端工程或 MCP 内嵌配置界面
- 把八个系统合成一个自动扇出的"一键排查"工具
- 为 SQLite、MySQL、PostgreSQL 各写一套仓储或手写 SQL
- 在配置库的 SQL 里使用某一种数据库独有的类型或 JSON 运算符
- 把配置库指到业务库，或让排查工具修改配置库
- 在工具里执行任意 HTTP 请求或任意命令；GitLab、ES、RabbitMQ、CLS 都只走固定方法与路径
- 通过工具改表结构、建索引、改配置；schema 发现只读元数据，不做结构变更
- 密钥轮换、按目标独立密钥、KMS/HSM，以及对 `secret_json` 明文的兼容
- 审计导出页面、多租户、按人配额
- 缓存目标配置（第一版每次读库）
- 迁移降级流程；回滚只按备份恢复或重建
- 通过 `/settings` 或任何配置放宽只读、危险命令、密钥与目标范围约束
- 危险与高开销清单的可配置化（规则写死在代码里，配置不参与）
- 按人、按目标、按动作的差异化审计保留期
- 审计清理周期的自定义 cron（固定每小时一轮）
- 系统配置页的"恢复默认"按钮（默认值只用于初始化与展示）
- 对线上系统的任何自动修复动作
