# target operator_notes 1.8.0 · 验证记录

## 功能

每个 target 可填写最多 512 个字符的 `operator_notes`：

- 新建/编辑目标时填写；
- `systems_status` 的 target 行完整返回；
- 所有 target 级工具结果完整返回；
- 字段名始终为 `operator_notes`；
- 不改变 scope、只读规则和 guard。

## 数据与迁移

新增：

```text
targets.operator_notes TEXT NOT NULL DEFAULT ''
```

迁移 `0014_target_operator_notes`：

- 已有 target 为空字符串；
- 不需要回填；
- SQLite 迁移测试通过；
- 已覆盖迁移幂等场景。

## 安全与上下文

- 最大 512 字符，服务端和表单双重校验；
- notes 不进入 connector options；
- notes 不参与 scope 计算；
- notes 不作为 secret；
- MCP instructions 明确其为 advisory，不能覆盖授权和只读规则；
- UI 提示不要填写密钥。

## 验证

- store create/get/update notes；
- notes 超长拒绝；
- `systems_status` 返回完整 notes；
- 工具包络包含 `operator_notes`；
- 全量测试通过。
