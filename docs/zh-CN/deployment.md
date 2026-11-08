# 部署

`scripts/setup.sh` 是新机器部署入口，支持两种安装方式：

- **source**：`git clone` + `uv sync`（适合开发、需要使用配置台里的“安装客户端”功能）；生产默认 `--no-dev`
- **pypi**：`uv tool install dr-panda-mcp==<版本>`（适合只运行、不改代码的机器）

首次安装必须在 loopback（`127.0.0.1` / `localhost`）完成，再启用远程监听。

## 常用命令

```bash
# 只读体检，不修改任何文件
./scripts/setup.sh check

# 源码安装（默认；在仓库目录内执行时使用当前 checkout）
./scripts/setup.sh install --method source --extras mysql,redis

# 开发机安装（包含 pytest/ruff）
./scripts/setup.sh install --method source --dev

# PyPI 安装到专用目录
sudo ./scripts/setup.sh install --method pypi --version 1.4.0 --dir /opt/dr-panda-mcp

# systemd 服务（Linux、root）；默认专用用户 drpanda
sudo ./scripts/setup.sh service --dir /opt/dr-panda-mcp

# 启动 + 健康检查；没有 systemd 服务时前台运行
./scripts/setup.sh start --dir /opt/dr-panda-mcp

# 状态
./scripts/setup.sh status --dir /opt/dr-panda-mcp

# 升级并重启
sudo ./scripts/setup.sh upgrade --dir /opt/dr-panda-mcp --version 1.0.1
```

## `check` 检查什么

- OS/架构、`curl`、`git`、`uv`、Python >=3.11；
- Linux 的 systemd 是否可用、unit 是否合法；
- `.env` 是否存在、权限是否过宽；
- `data/` 与四个密钥/安装文件；
- 监听地址、端口是否被占用；
- 首次安装规则：`data/install.json` 不存在时，非 loopback 监听会直接失败；
- 已记录安装方式的可执行文件、解释器，以及服务用户能否执行；
- venv Python 是否误指向 `/root`。

安装前后都可以跑，完全只读。

## Python 选择

安装器优先使用系统 Python >=3.11（`/usr/bin/python3.12`、`/usr/bin/python3.11` 或 `python3`）。如果系统没有且以 root 安装，uv managed Python 会放到 `/opt/uv-python`，不会落到 `/root`，避免 `drpanda` 无法执行。

可以用 `--python /path/to/python` 强制指定解释器。

## 镜像

可以直接设置 uv 标准环境变量：

```bash
export UV_DEFAULT_INDEX=https://mirrors.ustc.edu.cn/pypi/simple
export UV_PYTHON_INSTALL_MIRROR=https://mirrors.ustc.edu.cn/github-release/astral-sh/python-build-standalone/
./scripts/setup.sh install --method source --no-dev
```

uv 二进制本身建议用 USTC 的 GitHub Release 镜像安装。

## 首次安装

1. 保持默认 loopback 地址安装；
2. 启动服务或前台运行；
3. 在本机浏览器打开 `http://127.0.0.1:8111/`；服务器没有浏览器时用 SSH 隧道：

```bash
ssh -L 8111:127.0.0.1:8111 user@server
# 本地打开 http://127.0.0.1:8111/
```

4. 完成安装向导，保存 MCP Token 与 `data/` 下的密钥文件；
5. 完成后再改 `.env`（例如 `DR_PANDA_HOST="0.0.0.0"`）并重启。

## systemd

`service` 会按需创建 `drpanda` 系统用户、修正目录归属，并写入 `/etc/systemd/system/dr-panda-mcp.service`。

单元默认：

- `ProtectSystem=strict`，只允许写 `<目录>/data`、已存在的 `.venv` 和 `uv.lock`
- `UV_CACHE_DIR=<目录>/data/.uv-cache`
- `uv` 会复制到 `/usr/local/bin`，服务用户才能执行配置台的一键安装
- 应用目录不在 `/home` 时启用 `ProtectHome=true`
- `NoNewPrivileges=true`
- 失败自动重启

配置台的一键客户端安装只适用于 source 安装。升级部署脚本后，重跑 `sudo ./scripts/setup.sh service --dir <目录>` 刷新 unit，再使用安装按钮。

查看日志：

```bash
journalctl -u dr-panda-mcp -f
```

## 升级与回滚

- 升级前必须备份 `data/`、`secret.key`、`install.json`、`install.key`、`session.key`；
- 应用启动时自动跑 Alembic 迁移；SQLite 只在有 pending migration 时自动备份；
- source：`git pull --ff-only` + `uv sync`；回滚用上一个 tag/commit；
- PyPI：显式安装上一个版本；数据库降级不会自动执行。

## 参数

| 参数 | 含义 |
|---|---|
| `--dir PATH` | 应用目录 |
| `--method source\|pypi` | 安装方式 |
| `--version VER` | PyPI 版本 |
| `--extras LIST` | `mysql,postgres,mongo,redis,kafka,cls` 或 `all` |
| `--python PYTHON` | Python 解释器或 `auto`（默认） |
| `--dev` | 安装 dev 组（仅 source） |
| `--index-url URL` | PyPI 镜像（设置 `UV_DEFAULT_INDEX`） |
| `--python-mirror URL` | python-build-standalone 镜像 |
| `--user USER` | systemd 服务用户（默认 `drpanda`） |
| `--service-name NAME` | systemd unit 名 |
| `--repo URL` | Git 仓库地址 |
| `--yes` | 安装 uv 时不再询问 |
| `--no-start` | 只安装 unit，不启动 |

## Docker

暂不在本脚本范围内；需要时单独评估。
