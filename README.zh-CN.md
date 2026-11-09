<p align="center">
  <img src="docs/assets/logo.png" width="96" alt="DrPanda MCP">
</p>

<p align="center">
  <a href="https://github.com/linyu19872008/dr-panda-mcp/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/linyu19872008/dr-panda-mcp/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://pypi.org/project/dr-panda-mcp/"><img alt="PyPI" src="https://img.shields.io/pypi/v/dr-panda-mcp?cache=20261109"></a>
  <a href="LICENSE"><img alt="License: MIT" src="docs/assets/badge-license.png" height="20"></a>
  <a href="https://www.python.org/"><img alt="Python 3.11+" src="docs/assets/badge-python.png" height="20"></a>
</p>

<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>

# DrPanda MCP

面向线上故障排查的**只读 MCP 服务**。

在网页里登记 MySQL、MongoDB、Elasticsearch、Redis、GitLab、RabbitMQ、Kafka、CLS 的地址、凭证和允许访问的范围；Cursor、Codex、DeepSeek Harness 等 MCP 客户端通过 Streamable HTTP 调用 `/mcp`，模型只能按 `target` 名称使用只读工具。

**模型不能自行传入主机、账号或密码。**

![中文配置台](docs/zh-CN/assets/screenshot-zh.png)

---

## 为什么用它

线上排障时，模型经常需要同时看日志、代码、数据库、缓存和消息堆积。直接把生产凭证交给模型风险太高；只读代理、临时截图、人工代查又难以复现和审计。

DrPanda MCP 把“能查什么”提前收敛成三类边界：

1. **连接边界**：只允许访问网页里登记过的 target；
2. **操作边界**：只执行只读白名单，管理命令与高开销查询在连接前拒绝；
3. **身份边界**：网页登录和 MCP Bearer Token 独立，所有调用记录到真实管理员。

---

## 当前状态

M0–M7 已落地并通过测试：

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0–M2 | 工程地基、配置库、密钥加密、八类只读闸门 | 完成 |
| M3 | 配置台网页、MCP `/mcp` 接入 | 完成 |
| M4 | CLS 日志、GitLab 代码（5 个工具） | 完成 |
| M5 | MySQL / Mongo / ES / Redis（17 个工具） | 完成 |
| M6 | RabbitMQ / Kafka（5 个工具） | 完成 |
| M7 | 首次安装、登录、多 Token、审计到人 | 完成 |

- 工具总数：**28**
- 质量门禁：GitHub Actions（pytest / ruff / 文档链接检查），状态见顶部 CI 徽标
- 默认监听：`127.0.0.1:8111`
- 默认语言：英文（界面、MCP、CLI、文档）；中文文档在 `docs/zh-CN/`
- 首次安装支持 SQLite / MySQL / PostgreSQL 配置库
- 前端采用服务端渲染；配置台交互需要 JavaScript，认证与校验仍只在服务端执行

真实联调覆盖：

- MySQL / MongoDB / Elasticsearch / Redis / RabbitMQ 已用 Docker 真实上游验证；
- MySQL TLS/mTLS、target 级 CA、ES 多 host failover、Mongo 多种认证方式已覆盖；
- Kafka、CLS、GitLab 工具代码和单测已完成，但**尚未用真实上游做端到端验收**。

---

## 快速开始

### 环境

- Python `>= 3.11`
- [uv](https://docs.astral.sh/uv/)
- 首次启动默认使用 SQLite，无需额外数据库

从源码运行（推荐参与开发）：

```bash
git clone https://github.com/linyu19872008/dr-panda-mcp.git
cd dr-panda-mcp
uv sync
cp .env.example .env   # 可选；不建则使用环境变量与默认值
uv run dr-panda-mcp    # 自动加载当前目录 ./.env
```

或从 PyPI 安装为命令行工具：

```bash
uv tool install dr-panda-mcp
# 需要 MySQL/PostgreSQL 配置库时：
# uv tool install 'dr-panda-mcp[mysql]'
# uv tool install 'dr-panda-mcp[postgres]'
dr-panda-mcp
```

PyPI 安装会在当前工作目录使用 `data/`，建议在专用目录启动。

浏览器打开：

```text
http://127.0.0.1:8111/
```

首次进入安装向导：

1. 设置管理员密码（至少 8 位）；
2. 选择配置库：SQLite（推荐本地使用）/ MySQL / PostgreSQL；
3. 测试连接（通过后「完成安装」才可点）；
4. 完成安装，保存安装完成页显示的 MCP Token。

登记排查目标时，新建必须先测试连接成功才能保存；编辑时如果主机、账号、密钥、TLS 或超时没有变化，可以直接保存范围和运行上限。保存时服务端只在连接字段变化后再次探测，失败不会落库。

健康检查：

```bash
curl -fsS http://127.0.0.1:8111/healthz
# {"ok":true,"version":"1.5.0","db":"ok"}
```

### 可选依赖

`uv sync --extra <name>` 会把环境收成「默认依赖 + 这一个 extra」，已经装好的其他客户端会被卸掉。补一个时加上 `--inexact`。一次装齐用 `--all-extras`。命令要在运行 `uv run dr-panda-mcp` 的项目目录执行。

列表里出现「客户端未安装」时，可以点「安装」。服务会在当前项目执行带 `--inexact` 的命令，然后立刻再测一次。装好的新客户端不用先重启。

```bash
# 配置库
uv sync --extra mysql --inexact       # asyncmy
uv sync --extra postgres --inexact    # asyncpg

# 排查组件（GitLab、RabbitMQ 不需要 extra）
uv sync --extra mongo --inexact
uv sync --extra redis --inexact
uv sync --extra kafka --inexact
uv sync --extra cls --inexact

# 配置库和排查组件一次装齐
uv sync --all-extras
```

---

## 部署脚本

新机器建议用 [scripts/setup.sh](scripts/setup.sh) 代替手工命令：

```bash
./scripts/setup.sh check
./scripts/setup.sh install --method source --extras mysql,redis
sudo ./scripts/setup.sh service --dir /opt/dr-panda-mcp
./scripts/setup.sh start --dir /opt/dr-panda-mcp
```

也支持 PyPI 安装（`--method pypi --version 1.5.0`）、健康检查、升级和专用 `drpanda` systemd 用户。详见 [docs/zh-CN/deployment.md](docs/zh-CN/deployment.md)。

---

## 首次安装会生成哪些文件

安装完成后会在 `data/` 下生成：

| 文件 | 作用 | 丢失后果 |
|---|---|---|
| `install.json` | 记录配置库 URL（加密） | 需恢复备份，否则无法自动找到配置库 |
| `install.key` | 解密 `install.json` | 无法恢复安装状态 |
| `session.key` | 网页 Session 签名密钥 | 所有网页 Session 失效，可重新登录 |
| `secret.key` | 加密 target 密钥 | 已登记密钥不可恢复 |
| `dr-panda.sqlite` | 默认 SQLite 配置库 | 丢失目标、审计和配置 |

- 安装状态文件权限为 `0600`；
- **备份配置库时必须同时备份 `secret.key`、`install.json`、`install.key`、`session.key`**；
- 不要把 `data/` 提交到 Git。

---

## 客户端接入

在所有客户端中配置 MCP URL 和 Bearer Token：

```json
{
  "mcpServers": {
    "drpanda": {
      "url": "http://127.0.0.1:8111/mcp",
      "headers": {
        "Authorization": "Bearer <在“我的”页面创建的 MCP Token>"
      }
    }
  }
}
```

### Cursor

把上面的 `mcpServers` 配置写入 Cursor 的 MCP 配置文件。

### Codex

```toml
[mcp_servers.drpanda]
url = "http://127.0.0.1:8111/mcp"

[mcp_servers.drpanda.headers]
Authorization = "Bearer <token>"
```

### DeepSeek Harness

`serverName` 使用 `drpanda`，模型侧工具名形如：

```text
mcp__drpanda__mysql_query
mcp__drpanda__cls_search
mcp__drpanda__systems_status
```

说明：

- `/mcp` 未携带有效 Bearer Token 时返回 `401`；
- 网页登录 Session **不能**代替 MCP Token；
- Token 只存哈希，完整值只在创建时显示一次；丢失只能删除后重新生成；
- 修改端口后，客户端 URL 要同步修改。

---

## 登记目标与工具

目标属于一个环境。环境有展示名和调用标识。展示名可以改；调用标识创建后不能改，排查时要传这个值。不同环境可以有同名目标；同一个环境里同一种类型可以有多台，靠名称区分，不会自动挑一台。

只有一个环境时，工具可以省略 `environment`，迁移种下的就是 `default`（展示名 `Default`）。登记了多个环境之后，每次调用都要传 `environment`。先调用不带参数的 `systems_status` 看环境，再带上调用标识看这个环境里的目标。网页「排查目标」按环境切换；停用的环境不能查，配置仍保留。

工具调用时只传 `environment` 和 `target` 名称，不能传主机、账号或密码。

| 类型 | 工具 |
|---|---|
| `mysql` | `mysql_tables`、`mysql_describe`、`mysql_query`、`mysql_explain`、`mysql_processlist` |
| `mongo` | `mongo_collections`、`mongo_find`、`mongo_aggregate`、`mongo_stats` |
| `elasticsearch` | `es_mapping`、`es_search`、`es_health`、`es_index_stats` |
| `redis` | `redis_get`、`redis_scan`、`redis_info`、`redis_slowlog` |
| `gitlab` | `gitlab_search_code`、`gitlab_get_file`、`gitlab_blame` |
| `cls` | `cls_search`、`cls_context` |
| `rabbitmq` | `rabbit_queues`、`rabbit_queue` |
| `kafka` | `kafka_lag`、`kafka_offsets`、`kafka_peek` |
| `nacos` | `nacos_configs`、`nacos_config`、`nacos_services`、`nacos_instances` |
| 全局 | `systems_status` |

另有 `investigate_error` prompt，用于从错误现象开始组织排查路径。

目标范围只能缩小可读边界：

- MySQL：库 / 表；
- MongoDB：库 / 集合；
- Elasticsearch：索引；
- Redis：key 前缀 / 命令范围；
- GitLab：项目 / 分支；
- RabbitMQ：vhost / queue；
- Kafka：topic / partition；
- CLS：日志主题与时间范围；
- Nacos：命名空间、group、dataId 与服务。

目标名称只允许小写字母、数字和连字符，创建后不可修改。密钥只存密文，列表不回显。

---

## 安全模型

### 绝对只读

- 各已注册组件的所有工具（包括网页“测试连接”）只读；
- 账号即使有写权限也不会被使用；
- 只读白名单之外还有绝对危险规则：
  - 管理/变更类命令；
  - 无界扫描、大聚合、深度分页、脚本执行等；
- 危险判定在建立连接之前完成，拒绝码 `DANGEROUS_OPERATION`；
- 每次调用受超时、行数、字节和每 target 并发上限约束，截断会明确标记。

### 认证与请求保护

- 网页登录：管理员密码 + HMAC 签名 Session Cookie；
- 表单：CSRF 双提交校验；
- `/mcp`：独立 Bearer Token，只存 SHA-256 哈希；
- Host/Origin 校验：拒绝异常 Origin；
- 默认只监听 loopback；改为 `0.0.0.0` 或指定网卡 IP 即对外监听，建议通过 HTTPS 反向代理访问；
- 配置库变更写审计，审计 actor 为真实管理员。

### 前端

- Jinja2 服务端渲染；
- 核心流程无 JS 可用；
- 仅使用自托管、无依赖的小脚本：
  - `app.js`：原生 `<dialog>`、表单加载态；
  - `copy-token.js`：复制 Token；
- 不引入前端框架、Node 构建链、第三方 CDN；
- 无 JS 时提供独立表单/确认页或手动复制提示，不显示假按钮。

详见 [frontend-js-policy.md](docs/zh-CN/verify/frontend-js-policy.md)。

---

## 系统配置

登录后进入 `/settings` 修改。配置存在配置库中，带范围校验；只把实际变化的配置项写审计和 `settings_history`。

| 配置键 | 默认 | 范围 | 说明 |
|---|---:|---:|---|
| `default_target_timeout_s` | 15 秒 | 1–120 | 新建目标默认超时 |
| `default_target_max_rows` | 100 行 | 1–1000 | 新建目标默认行数 |
| `default_target_max_bytes` | 102400 字节 | 4096–1048576 | 新建目标默认字节上限 |
| `target_max_concurrency` | 10 | 1–50 | 每 target 并发上限 |
| `global_max_concurrent_calls` | 0 | 0–200 | 进程内全局并发上限（0=不限） |
| `audit_retention_days` | 90 天 | 1–3650 | 审计保留期 |
| `audit_cleanup_interval_minutes` | 60 | 5–1440 | 审计清理间隔 |
| `audit_cleanup_batch_size` | 1000 | 100–5000 | 审计清理每批条数 |
| `audit_cleanup_max_seconds` | 300 | 10–3600 | 单轮清理最长秒数 |
| `catalog_max_clients` | 32 | 4–128 | 进程内连接器缓存上限 |
| `catalog_idle_seconds` | 0 | 0–3600 | 连接器空闲回收秒数（0=不回收） |
| `session_ttl_minutes` | 720 | 30–10080 | 网页 Session 有效期（分钟） |
| `login_max_attempts` | 5 | 1–50 | 同一来源 IP 的登录失败次数上限 |
| `login_lockout_minutes` | 5 | 1–1440 | 达到上限后的拒绝时长（分钟） |
| `mcp_token_max_per_user` | 5 | 1–50 | 每个账号最多保留的 Token 数量 |
| `mcp_token_ttl_days` | 0 | 0–3650 | Token 有效期（天，0 表示不过期） |
| `backup_keep_count` | 20 | 1–100 | SQLite 迁移前备份保留数量 |

系统配置只能调整运行策略，**不能放宽只读规则、危险规则、密钥管理或目标范围**。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DR_PANDA_HOST` | `127.0.0.1` | 监听地址 |
| `DR_PANDA_PORT` | `8111` | 网页与 `/mcp` 共用端口 |
| `DR_PANDA_DATABASE_URL` | 未使用 | 当前版本不参与实际建库：配置库由首次安装向导选择，之后以 `data/install.json` 为准；设置后仅做启动校验，不建议配置 |
| `DR_PANDA_SECRET_KEY` | 未设置 | base64 编码的 32 字节密钥；未设置时使用 `data/secret.key` |
| `DR_PANDA_LOG_LEVEL` | `INFO` | 日志级别 |
| `DR_PANDA_PUBLIC_URL` | 未设置 | 仅用于展示的访问地址（MCP 地址/页面显示），不参与安全判断 |
| `DR_PANDA_COOKIE_SECURE` | `auto` | Cookie Secure 策略：auto（按请求 scheme）/ always / never |
| `DR_PANDA_TRUSTED_HOSTS` | 未设置 | `/mcp` Host 白名单（逗号分隔），不设则按 FastMCP 默认策略 |

仓库根目录提供 [`.env.example`](.env.example)，默认值以注释形式给出；本地不配置任何变量即可启动。

服务启动时会**自动加载当前工作目录的 `./.env`**；文件不存在时直接使用环境变量与代码默认值。需要覆盖时：

```bash
cp .env.example .env
# 按需修改 .env（.env 已被 .gitignore 忽略，不要提交）
uv run dr-panda-mcp
```

规则：

- 优先级：**真实环境变量 > `.env` > 代码默认值**（systemd/Docker/CI 注入的变量始终优先）；
- 只认当前目录的 `.env`，不向上级目录或家目录查找；
- `.env` 权限过宽（如 0644）、不是普通文件、行格式非法时**启动失败**，避免密钥文件被他人读取或配置静默不生效；
- 没有“禁用自动加载”开关；Docker/systemd 不挂载 `.env` 即可。

修改监听地址/端口/公网地址后需重启进程生效；配置库不要通过环境变量指定（见上表说明）。

远程部署建议：

- 推荐使用 HTTPS 反向代理；`DR_PANDA_PUBLIC_URL` 只影响页面/复制出来的地址，不影响安全策略；
- 不要直接把管理台暴露到公网；首次安装仍必须在本机 loopback 完成；
- 如需 `/mcp` 的 Host 白名单，设置 `DR_PANDA_TRUSTED_HOSTS`（例如 `mcp.example.com`）；
- 反向代理的真实 TLS 环境仍需自行验收。

---

## 运维

### 管理员密码重置

本地执行：

```bash
uv run dr-panda-mcp-admin reset-password
```

重置后会递增 `auth_version`，所有现有网页 Session 失效；MCP Token 不受影响。

### SQLite 备份

- 仅在存在 pending Alembic migration 时自动备份；
- 备份写入 `data/backup/`；
- 保留数量由 `backup_keep_count` 控制；
- 手动备份请同时复制配置库和四个密钥/安装文件。

### 审计

- 每次工具调用、目标变更、配置变更都写入 `audit`，并记下所属环境；
- 网页「审计」可按时间、动作、环境和对象查看，不能从页面删除；
- 审计清理默认 90 天保留，每小时检查一轮；
- 清理只记日志，不写审计，避免自增。

---

## 开发与测试

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
uv run python scripts/smoke.py
```

- 测试使用临时 SQLite 和临时密钥，不连接真实线上系统；
- Docker 联调脚本在 `scripts/integration/`；
- 全量测试数量不写死在 README，以 CI 徽标和实际运行结果为准。

### 项目结构

```text
src/dr_panda_mcp/
  __init__.py         启动入口
  config.py           环境变量与配置
  setup.py            首次安装向导
  admin.py            管理员本地维护命令
  auth.py             密码、Session、CSRF、MCP Token
  server.py           FastMCP、/mcp 与网页装配
  runtime.py          引擎、迁移、密钥、ConfigStore
  settings.py         系统配置默认值/范围/分组
  connectors/         上游组件连接器
  guards/             只读白名单与危险命令规则
  tools/              MCP 工具实现与审计
  prompts.py          investigate_error
  web/                routes/templates/static/渲染
  store/              SQLAlchemy 模型、仓储、Alembic 迁移
tests/                单元、契约、网页、工具与迁移测试
docs/                 英文文档（默认）
docs/zh-CN/           中文规划、里程碑、UI 规范与验证记录
scripts/              冒烟与 Docker 联调脚本
```

---

## 已验证与未验证

### 已验证

- SQLite / MySQL / PostgreSQL 配置库安装；
- 多 MCP Token 创建、复制、删除、分页；
- 登录、Session、CSRF、登出与密码修改；
- 目标增删改、启停、测试连接（探测通过才能保存）、密钥加密；
- 同源异步交互：列表行内测试/启停、保存门槛、系统配置/登录/改密/安装向导局部反馈，无 JS 时回退普通表单；
- 系统配置保存、逐项/全局恢复默认、历史记录；
- 明暗主题、中英文、1440/390 响应式布局；
- MySQL / Mongo / ES / Redis / RabbitMQ Docker 真实上游；
- 只读闸门、危险命令拒绝、超时/行数/字节限制。

### 未验证 / 边界

- Kafka 真实上游端到端（镜像不可用）；
- CLS、GitLab 真实凭证端到端；
- 反向代理后的真实 HTTPS/TLS 验收；
- 多用户、RBAC、OAuth/OIDC、MFA；
- 密码找回页面（仅提供本地 CLI 重置）；
- `install.json` / `install.key` / `secret.key` 丢失后的自动恢复。

未验证能力不会因为其他组件通过就视为可用。

---

## 文档

- [docs/zh-CN/README.md](docs/zh-CN/README.md)：中文文档索引
- [docs/zh-CN/planning.md](docs/zh-CN/planning.md)：方案、接口、数据模型、只读/危险规则
- [docs/zh-CN/milestones.md](docs/zh-CN/milestones.md)：里程碑与验收口径
- [docs/zh-CN/ui-design.md](docs/zh-CN/ui-design.md)：配置台设计系统与页面规格
- [docs/zh-CN/verify/m7-01.md](docs/zh-CN/verify/m7-01.md)：M7 安装、登录、多 Token
- [docs/zh-CN/verify/frontend-js-policy.md](docs/zh-CN/verify/frontend-js-policy.md)：前端 JS 约束 v3（配置台需要 JavaScript，校验仍在服务端）
- [docs/zh-CN/verify/async-ux-01.md](docs/zh-CN/verify/async-ux-01.md)：异步交互与保存门槛、真实 Chrome 验证
- [docs/zh-CN/verify/ux-audit-01.md](docs/zh-CN/verify/ux-audit-01.md)：全站交互审计与修复
- [docs/zh-CN/verify/form-ux-01.md](docs/zh-CN/verify/form-ux-01.md)：目标表单重组与保存前测试连接
- [docs/zh-CN/verify/settings-03.md](docs/zh-CN/verify/settings-03.md)：系统配置结构化
- [docs/zh-CN/verify/](docs/zh-CN/verify/)：全部里程碑、集成与硬化验证记录


## 贡献与安全

- [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)：开发环境、测试、PR 与双语文档同步规则；
- [SECURITY.zh-CN.md](SECURITY.zh-CN.md)：漏洞上报渠道与范围；
- [CODE_OF_CONDUCT.zh-CN.md](CODE_OF_CONDUCT.zh-CN.md)：行为准则；
- [CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)：版本变更；
- [LICENSE](LICENSE)：MIT。

> 中文设计/验证文档目前是主要设计资料；英文 README 面向国际读者，设计文档暂不逐篇翻译。
