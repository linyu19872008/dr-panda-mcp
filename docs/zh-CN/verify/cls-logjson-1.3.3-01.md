# CLS 日志内容字段兼容 1.3.3 · 验证记录

## 背景

CLS `SearchLog` 返回的 `LogInfo` 主要使用：

- `LogJson`：日志内容的 JSON 序列化字符串；
- `RawLog`：索引异常时的原始日志；
- 部分历史响应可能只有 `Log` / `Content`。

原连接器只读取 `Log` / `Content`，当 CLS 返回 `LogJson` 时 `cls_search` 行内容为空。

## 修复

`search_log` 内容优先级：

```text
LogJson → RawLog → Log → Content → ""
```

`describe_context` 内容优先级：

```text
Content → LogJson → RawLog → Log → ""
```

`Time` / `BTime` 仍经过 1.3.2 的秒/毫秒归一化处理。

## 测试

更新 `test_cls_search_log_maps_topic_and_rows`：

- 首条结果使用 `LogJson='{"msg":"boom"}'`；
- 断言 `content == '{"msg":"boom"}'`；
- 第二条结果仍回退到 `Log="second"`。

全量验证：

- `pytest -q`：**585 passed**；
- `ruff check .`：通过；
- `node --check app.js`：通过；
- `bash -n setup.sh`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.3.3` sdist/wheel。

## 发布

- 版本：1.3.3；
- 修复 CLS 返回内容字段兼容，不涉及数据库或 Web 路由行为变更。
