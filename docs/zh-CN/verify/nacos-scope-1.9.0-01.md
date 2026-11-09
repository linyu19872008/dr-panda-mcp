# Nacos data/service scope modes 1.9.0 · 验证记录

## 变更

新增两个 target option：

```text
data_scope = all | selected
service_scope = all | selected
```

- `all`：允许所选 namespace/group 下全部 dataId 或服务；
- `selected`：只允许 `allowed_data_ids` / `allowed_services` 显式列表；
- 新建 target 默认 `all`；
- 已有 target 没有 mode 时按 `selected` 处理，避免升级后静默扩权；
- 两种模式都仍受 `allowed_namespaces` / `allowed_groups` 约束。

## 连接测试

连接测试不再要求用户从多个 namespace/group 中选一个：

- v1/2.x：依次尝试授权 namespace/group，成功一次即通过；
- v3：验证登录，并在 selected 模式下读取一个具体 dataId/service；
- 多个 namespace/group 不再导致 `namespace is required`。

## 行为验证

- 多 namespace/group 探活通过；
- v1/2.x `data_scope=all` 配置列表不按 dataId 过滤；
- v1/2.x `service_scope=all` 服务列表不按服务名过滤；
- `data_scope=all` 时 `nacos_config` 可按任意 dataId 读取；
- `data_scope=selected` 继续执行原 allowlist；
- Nacos 3 没有全量列表 OpenAPI：`all` 模式下 `nacos_configs`/`nacos_services` 返回明确的限制错误，需要 selected 或 v1 兼容模式。

## 安全

- `all` 不是“无边界”，仍限制在 authorized namespaces/groups；
- 已有 target 不会因升级自动变为 all；
- UI 会提示全部模式可能包含敏感配置；
- `systems_status` 暴露 `data_scope` / `service_scope`，AI 可区分“全部”和“未配置”。
