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

## 边界复验（补充）

### 多级文件夹 Job

在 Jenkins 中创建：

```text
team-a/
  sub/
    service-build
```

使用 Jenkins `cloudbees-folder` 插件。

验证：

- `jenkins_jobs` 返回完整名称 `team-a/sub/service-build`；
- `jenkins_job` 通过 `/job/team-a/job/sub/job/service-build/` 成功读取；
- 多级 `/job/` 路径和 URL 编码正常。

### Queue 非空

将内置节点 executor 临时设为 0，触发 `team-a/sub/service-build`：

```text
why = Waiting for next available executor
```

`jenkins_queue` 返回未授权的任务时会被过滤，授权任务正常返回 `why`、`inQueueSince`、`stuck` 等字段。

### 反向代理 + TLS

使用 TLS 终止代理转发到 Jenkins HTTP 端口，连接器：

```text
base_url=https://localhost:18444
ca_pem=<代理自签名证书>
username=admin
api_token=<token>
```

`ping` 和 Job 列表通过，TLS 证书校验生效。

### SSO（HTTP Header）

在 Jenkins 配置 reverse-proxy-auth-plugin，使用：

```text
X-Forwarded-User: admin
```

直接请求 Jenkins：

- 不带 header：HTTP 403；
- 带 header：HTTP 200。

但当前 DrPanda Jenkins 连接器使用 Basic Auth / API Token，**不能携带反向代理 SSO 的 header**：

- 在 SSO realm 下，Basic Auth 请求返回 401；
- 因此当前组件不直接兼容 header-based SSO。

这是明确的兼容边界。若生产 Jenkins 使用 SSO，通常需要在 Jenkins 前由可信代理注入服务身份，或后续增加受控的自定义认证 header 选项；不能把任意 header 直接做成用户可配置项。

### Jenkins 原生 TLS

使用 Jenkins Winstone：

```text
--httpsPort=8443
--httpsKeyStore=... 
--httpsKeyStorePassword=...
```

连接器配置 `https://localhost:18443` + `ca_pem`：

- `ping` 通过；
- 多级 Job 列表通过。

结论：Jenkins 原生 TLS 可用；TLS 终止代理也可用；header-based SSO 仍需额外适配。
