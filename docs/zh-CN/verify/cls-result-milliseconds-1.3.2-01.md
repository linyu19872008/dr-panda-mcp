# CLS 返回时间毫秒兼容修复 1.3.2 · 验证记录

## 背景

1.3.1 已把 `SearchLog` 请求的 `From`/`To` 改为毫秒，但 CLS 返回结果中的 `Time`/`BTime` 也可能直接是毫秒时间戳。原格式化逻辑按秒调用 `datetime.fromtimestamp`，可能因年份越界抛出 `ValueError`，表现为 `cls_search` 内部错误。

## 修复

新增 `_epoch_seconds()`：

- 小于 `1e12` 的值按秒处理；
- 大于等于 `1e12` 的值按毫秒处理，除以 1000；
- `Time` 和 `BTime` 格式化前统一经过该函数。

阈值说明：`1e12` 毫秒约等于 2001-09-09，秒级时间戳要到 33658 年才会达到 `1e12`，不会误判当前时间。

## 测试

新增 `test_cls_search_log_accepts_millisecond_result_time`：

```text
Time = 1767229200000
→ time  = 2026-01-01T01:00:00+00:00
→ btime = 2026-01-01 09:00:00.000
```

全量验证：

- `pytest -q`：**585 passed**；
- `ruff check .`：通过；
- `node --check app.js`：通过；
- `bash -n setup.sh`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.3.2` sdist/wheel。

## 发布

- 版本：1.3.2；
- 修复 CLS 返回时间毫秒兼容性，不涉及数据库或 Web 路由行为变更。
