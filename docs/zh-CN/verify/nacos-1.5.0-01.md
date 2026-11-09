# Nacos 只读组件 1.5.0 · 验证记录

## 组件模型

新增 `nacos` 目标类型，使用 Nacos HTTP OpenAPI 只读接入：

- 配置：`/nacos/v1/cs/configs`
- 服务：`/nacos/v1/ns/service/list`
- 实例：`/nacos/v1/ns/instance/list`
- 健康检查：`/nacos/v1/console/health/liveness`

工具：

- `nacos_configs`：列出授权 dataId 的元数据；
- `nacos_config`：读取单个 dataId 内容；
- `nacos_services`：列出授权服务；
- `nacos_instances`：查看服务实例、健康和元数据。

## 授权范围

```text
allowed_namespaces
allowed_groups
allowed_data_ids
allowed_services
```

`public` 命名空间映射到 Nacos 的空 tenant；dataId/service 为空时拒绝读取，不做隐式全量授权。

认证支持 username/password 登录获取 accessToken；TLS 支持 CA 与校验开关。

## 真实 Docker 验证

本机使用 Docker：

```text
nacos/nacos-server:v2.2.3
standalone，NACOS_AUTH_ENABLE=false
```

已手工验证：

- 创建 `demo.yaml` 配置；
- 创建 `demo` 服务实例；
- 连接器 ping；
- configs 列表：返回 `demo.yaml`；
- config 内容：`hello: world`；
- services 列表：`demo`；
- instances：返回 `10.0.0.1:8080`、healthy/enabled/metadata；
- 未授权 dataId/service 返回 `SCOPE_DENIED`。

真实认证模式尚未在 Docker 中启用；登录逻辑有 fake transport 单测覆盖。

## 测试

- `pytest -q`：**598 passed**；
- `ruff check .`：通过；
- `node --check app.js`：通过；
- `bash -n setup.sh`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.5.0` sdist/wheel。

## 边界

- 当前只读支持配置与服务发现，不含 Nacos 用户/权限管理、配置发布/删除、实例变更；
- Nacos OpenAPI 的具体路径需按部署 context path 兼容；默认自动补 `/nacos`；
- Nacos 版本兼容以 2.x HTTP OpenAPI 为基线，后续再补 1.x/3.x 矩阵。
