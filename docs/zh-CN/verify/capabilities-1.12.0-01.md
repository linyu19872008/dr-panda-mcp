# 验证：1.12.0 可用能力面板

**日期**：2026-11-10  
**版本**：1.12.0

## 范围

- 目标表单「可用能力」：MCP 工具勾选、协议标签、风险项默认关
- `enabled_tools` 仅可收紧；旧目标缺省仍为非风险工具全开
- `run_tool` 拒绝未启用工具
- `systems_status.capabilities` 与列表「已启用 N/M」

## 自动化

- `uv run pytest`（含 `test_capabilities`、表单持久化、`systems_status`）
- `uv run ruff check`
- `uv run python scripts/check_docs_links.py`
- `uv run python scripts/build_pypi_readme.py --check`

## 结论

以 GitHub Actions 全绿与 PyPI 1.12.0 上架为发布门槛。
