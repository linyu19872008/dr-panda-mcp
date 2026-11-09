# Jenkins 只读组件 1.7.0 · 验证记录

## 范围

新增 `jenkins` 目标类型，使用 Jenkins REST API，不连接 Jenkins 的数据库。

工具：

- `jenkins_jobs`
- `jenkins_job`
- `jenkins_builds`
- `jenkins_build`
- `jenkins_console`
- `jenkins_nodes`
- `jenkins_queue`

## 真实 Docker 验证

环境：

```text
jenkins/jenkins:lts-jdk17
Jenkins 2.541.3
本地端口 18080
```

通过 init.groovy.d 创建：

- 管理员用户 `admin`；
- Job `demo-job`；
- 通过 Jenkins API 触发一次构建。

已验证：

- Basic Auth 登录；
- Jenkins API Token 登录（`drpanda-test`）；
- `ping`；
- Job 列表和 Job 详情；
- 构建列表、构建详情；
- `consoleText` 读取；
- 内置节点 `Built-In Node` 及 executor 信息；
- Queue API；
- 构建日志含 `Started by user admin`、`Finished: SUCCESS`。

API Token 是单独生成并验证的，不是用密码模拟。

## 安全边界

- 只允许 GET；
- 只允许 `/api/json`、`/job/.../api/json`、`/job/.../consoleText`、`/computer/api/json`、`/queue/api/json`；
- 禁止 `/script`、`/pluginManager`、`/credentials`、用户管理路径；
- `allowed_jobs` 精确匹配完整 Job 名称；
- `allowed_nodes` 精确匹配节点；
- `allow_console` 默认关闭，需显式开启；
- 构建列表受 `max_builds` 限制；
- 日志受 `max_bytes` 截断。

## 测试

- `pytest -q`：`pytest -q`：**607 passed**；
- `ruff check .`：通过；
- `node --check app.js`：通过；
- `bash -n setup.sh`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.7.0` sdist/wheel。

## 未覆盖边界

- 多级文件夹 Job 的真实 Jenkins 验证；
- Jenkins 反向代理/SSO 场景；
- Queue 非空的真实排队场景；
- Jenkins 原生 TLS（使用反向代理和 CA 配置的路径已有通用能力，但未在本组件单独验证）。
