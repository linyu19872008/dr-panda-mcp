# CLS SearchLog 毫秒时间戳修复 1.3.1 · 验证记录

## 现象

CLS 主题配置正确、不再报 `TopicNotExist`，但最近 1 小时和 24 小时检索都是 0 条。

## 根因

Tencent Cloud CLS SDK 的 `SearchLogRequest` 文档明确要求：

```text
From、To：Unix 时间戳（毫秒）
```

连接器却传了秒：

```python
request.From = int(start.timestamp())
request.To = int(end.timestamp())
```

秒值被 API 解释成 1970 年，因此时间窗内没有日志。

## 修复

```python
request.From = int(start.timestamp() * 1000)
request.To = int(end.timestamp() * 1000)
```

仍保持 CLS 的左闭右开区间 `[From, To)`。

## 测试

更新 CLS fake SDK：

- `ClsClient` 使用 `(credential, region, profile)` 构造；
- 返回 profile 供断言；
- `SearchLogRequest.From == 1767225600000`；
- `SearchLogRequest.To == 1767229200000`。

全量验证：

- `pytest -q`：**584 passed**；
- `ruff check .`：通过；
- `node --check app.js`：通过；
- `bash -n setup.sh`：通过；
- 文档链接检查：通过；
- `uv build --offline`：成功生成 `dr_panda_mcp-1.3.1` sdist/wheel。

## 发布

- 版本：1.3.1；
- 修复 CLS 检索时间单位，不涉及数据库或 Web 路由行为变更。
