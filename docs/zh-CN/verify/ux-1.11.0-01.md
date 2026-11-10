# 验证：1.11.0 排障可用性与审计结构化

**日期**：2026-11-10  
**版本**：1.11.0

## 范围

- 可行动错误（Scope / InvalidArgument 附带 allowed + hint）
- Nacos 列表 HTTP 预算与按类型默认 max_bytes（Nacos/Jenkins 1MB）
- CLS 时间年份边界 2000–2100
- Jenkins `last_failed_build` / `last_successful_build`
- 审计列 `tool` / `elapsed_ms` / `error_code`（迁移 0015）
- README 目录 + 排障 AI 提示；工具数 39 / 组件 10

## 自动化

- `uv run pytest`（含 `test_errors_guidance`、`test_nacos_list_budget`、`test_forms_max_bytes_defaults`、`test_cls_time_bounds`）
- `uv run ruff check`
- `uv run python scripts/check_docs_links.py`
- `uv run python scripts/build_pypi_readme.py --check`

## 结论

代码与文档随 1.11.0 一并合入；以 GitHub Actions 全绿为发布门槛。
