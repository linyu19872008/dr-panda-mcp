# Agent Skill

DrPanda MCP 自带一份给 AI agent 使用的排障 playbook。它面向支持 skill 的宿主
（DeepSeek Harness、Claude Code），也照顾使用项目规则或 `AGENTS.md` 的宿主
（Cursor、Codex、其他客户端）。

skill 是**建议层**。服务端的 `instructions`、运行时 `scope`、`capabilities`、
只读闸门和审计始终优先。

## 仓库里有什么

| 路径 | 用途 |
|---|---|
| [`.dsh/skills/dr-panda-mcp/SKILL.md`](../../.dsh/skills/dr-panda-mcp/SKILL.md) | 规范 playbook 与 skill frontmatter |
| [`skills/dr-panda-mcp/SKILL.md`](../../skills/dr-panda-mcp/SKILL.md) | 指向规范目录的便携软链 |
| [`.cursor/rules/dr-panda-mcp.mdc`](../../.cursor/rules/dr-panda-mcp.mdc) | Cursor 项目规则，指向该 playbook |
| [`AGENTS.md`](../../AGENTS.md) | 给 Codex 等 agent 的仓库级短说明 |
| [`scripts/check_skill.py`](../../scripts/check_skill.py) | CI 与 pre-commit 的结构校验 |

skill bundle 包含：

- `SKILL.md`——何时使用、目标发现、症状 → 工具路由、结果处理、错误恢复、
  报告模板和只读红线。
- `references/playbooks.md`——常见故障的分步流程。
- `references/connectors.md`——scope 字段名与每类连接器的规则。
- `references/errors.md`——错误码 → 动作。
- `references/results.md`——结果包络、截断、分页、分析行。
- `references/security.md`——只读、密钥、不可信 notes。
- `references/examples.md`——三段短 transcript。

## 为什么不是只靠 server instructions

`SERVER_INSTRUCTIONS` 是常驻契约：它必须短，而且即使没有 skill 也必须存在。
skill 是按需加载层：它补上症状路由、连接器规则、错误恢复和示例，而不用在每次
请求里都付这份 token。

分开的理由有三点：

1. **可发现性**——宿主按 `description` 选择 skill；README 或 server instruction
   不是 skill 目录条目。
2. **渐进披露**——长的 reference 只在当前症状需要时加载。
3. **可评估**——skill 可以用固定场景和结构校验来验收；README 散文不行。

## 加载方式

### DeepSeek Harness

filesystem skill provider 会扫描 `<projectRoot>/.dsh/skills`（以及
`<projectRoot>/.agents/skills`）。规范 bundle 已在
`.dsh/skills/dr-panda-mcp/`，所以本仓库作为项目根目录时会自动出现在 skill
目录；provider 会 watch 该目录，新增 skill 不需要重启。

### Claude Code

复制或软链到用户 skill 目录：

```bash
mkdir -p ~/.claude/skills
ln -sfn "$PWD/.dsh/skills/dr-panda-mcp" ~/.claude/skills/dr-panda-mcp
```

### Cursor

Cursor 从 `.cursor/rules/` 读取项目规则。本仓库的规则会在 DrPanda MCP 工具
可用时把 agent 指向 playbook。Cursor 规则是入口，不是 skill 的第二份拷贝。

### Codex 与其他客户端

使用 [`AGENTS.md`](../../AGENTS.md) 的短版，或直接把 agent 指向
`skills/dr-panda-mcp/SKILL.md`。不支持 skill 的客户端仍会拿到服务端
`instructions` 和 `investigate_error` prompt。

## 真相优先级

- 运行时 `systems_status`、`scope`、`capabilities` 和 guard 错误高于 skill 里的
  任何文字。
- skill 里不允许出现 target 名、主机名、凭证或环境特定 selector。示例只用
  `<env>`、`<target>`、`<logsetId>/<topicId>` 之类占位符。
- skill 里的工具名必须存在于 `src/dr_panda_mcp/capabilities.py`。
  `scripts/check_skill.py` 会在未知工具名、硬编码 `mcp__drpanda__`、断链、
  README/Cursor 入口缺失或疑似密钥时让 CI 失败。
- skill 声明 `metadata.version` 和 `metadata.requires`；工具面或最低服务端版本
  变化时两者都要更新。

## 校验

```bash
uv run python scripts/check_skill.py
uv run ruff check .
uv run pytest -q
uv run python scripts/check_docs_links.py
```

CI 在 test job 里跑 skill 校验；pre-commit 在 skill、校验脚本、测试或 README
变化时运行。

校验脚本刻意不依赖第三方包：它把 `src/dr_panda_mcp/capabilities.py` 当文本读，
因此在裸 Python 环境里也能跑。

## 评估

改行为之前，用
[`references/playbooks.md`](../../.dsh/skills/dr-panda-mcp/references/playbooks.md)
里的 10 个场景做 fresh session 对照（有/无 skill）。记录：

- 首次正确工具调用；
- 错 environment / target 率；
- 被拒后重试率；
- 单次排障平均工具调用数；
- 把截断结果当完整的次数（必须为 0）；
- 尝试写操作的次数（必须为 0）。

## 设计规则

- `SKILL.md` 保持短小；细节放 references。
- 不要复制 39 个工具的目录；以实时 tool schema 为准。
- 不要复制整份 README；链接过去。
- 不要把 skill 当安全边界；闸门才是边界。
- 不要硬编码 server 名、环境、目标或 selector。
- 宁可给一个明确的下一步，也不要给十个选项。

## 它不做什么

- 不登记 target、不创建 Token、不改设置。
- 不增加工具或权限。
- 不替代 Web 控制台或运维文档。
- DrPanda MCP 未配置时不会工作；它会提示 agent 停下来问用户。
