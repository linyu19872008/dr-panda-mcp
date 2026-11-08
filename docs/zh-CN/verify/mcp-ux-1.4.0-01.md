# MCP 可用性改进 1.4.0 · 验证记录

## 范围

对应工作包 W1–W6：CLS 登记/探活、Agent 可见错误、指令下沉、Analysis/分页、窄窗提示与压缩、上游 E2E 清单。

## 行为变化

| 项 | 行为 |
|---|---|
| CLS 表单 | `allowed_topics` 须为 UUID/`UUID`；友好名保存失败 |
| CLS 探活 | `DescribeLogsets` + 每主题 1 分钟 `SearchLog` |
| `cls_search` | 返回 `mode`/`next_context`；支持 analysis、`sort`/`context`/`merge_packages`/`compact` |
| 宽窗 hint | desc 且窗 >2h 时 notes 提示收窄 |
| `INTERNAL` | ToolError 含脱敏短消息 |
| annotations | readOnly + destructive=false + idempotent + openWorld |

## 测试

- 连接器：analysis 映射、探活扫主题、毫秒时间与 LogJson 回归
- 工具：宽窗 hint、merge/compact、INTERNAL 消息脱敏
- 网页：友好主题名 400
- `systems_status`：CLS UUID 提示 note

全量：

- `pytest -q`：**590 passed**
- `ruff check .`：通过
- `python scripts/check_docs_links.py`：通过
