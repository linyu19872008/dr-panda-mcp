# Agent skill

DrPanda MCP ships a portable playbook for agents that call the server. It is
designed for hosts that support skills (DeepSeek Harness, Claude Code) and for
hosts that use project rules or `AGENTS.md` (Cursor, Codex, other clients).

The skill is **advisory**. The server's `instructions`, runtime `scope`,
`capabilities`, read-only guards, and audit remain authoritative.

## What ships

| Path | Purpose |
|---|---|
| [`.dsh/skills/dr-panda-mcp/SKILL.md`](../.dsh/skills/dr-panda-mcp/SKILL.md) | Canonical playbook and skill frontmatter |
| [`skills/dr-panda-mcp/SKILL.md`](../skills/dr-panda-mcp/SKILL.md) | Portable symlink to the canonical bundle |
| [`.cursor/rules/dr-panda-mcp.mdc`](../.cursor/rules/dr-panda-mcp.mdc) | Cursor project rule that points at the playbook |
| [`AGENTS.md`](../AGENTS.md) | Short repository-level instructions for Codex and other agents |
| [`scripts/check_skill.py`](../scripts/check_skill.py) | Structural validator for CI and pre-commit |

The skill bundle contains:

- `SKILL.md` — when to use it, discovery, symptom → tool routing, result
  handling, error recovery, reporting, and hard stops.
- `references/playbooks.md` — step-by-step flows for common incidents.
- `references/connectors.md` — scope names and per-connector rules.
- `references/errors.md` — error code → action.
- `references/results.md` — envelope, truncation, paging, analysis rows.
- `references/security.md` — read-only, secrets, untrusted notes.
- `references/examples.md` — three short transcripts.

## Why a skill instead of only server instructions

`SERVER_INSTRUCTIONS` is the always-on contract: it must stay short and must be
present even when no skill is loaded. The skill is the on-demand layer: it adds
symptom routing, per-connector rules, error recovery, and examples without
paying that token cost on every request.

This separation matters for three reasons:

1. **Discoverability** — hosts select skills by their `description`; a README
   or a server instruction is not a skill catalog entry.
2. **Progressive disclosure** — the long reference files are loaded only when
   the current symptom needs them.
3. **Evaluability** — a skill can be checked with fixed scenarios and a
   structural validator; prose in a README cannot.

## Loading

### DeepSeek Harness

The filesystem skill provider scans `<projectRoot>/.dsh/skills` (and
`<projectRoot>/.agents/skills`). The canonical bundle is already at
`.dsh/skills/dr-panda-mcp/`, so it appears in the session catalog when this
repository is the project root. The provider watches the root; a new skill is
visible without a restart.

### Claude Code

Copy or symlink the bundle into the user's skill directory:

```bash
mkdir -p ~/.claude/skills
ln -sfn "$PWD/.dsh/skills/dr-panda-mcp" ~/.claude/skills/dr-panda-mcp
```

### Cursor

Cursor reads project rules from `.cursor/rules/`. The rule in this repository
points the agent at the playbook when DrPanda MCP tools are available. A Cursor
rule is a pointer, not a second copy of the skill.

### Codex and other clients

Use [`AGENTS.md`](../AGENTS.md) for the short form, or point the agent at
`skills/dr-panda-mcp/SKILL.md`. Clients without skill support still receive the
server `instructions` and the `investigate_error` prompt.

## Source of truth

- Runtime `systems_status`, `scope`, `capabilities`, and guard errors win over
  any text in the skill.
- The skill must never contain target names, hostnames, credentials, or
  environment-specific selectors. Examples use placeholders such as `<env>`,
  `<target>`, and `<logsetId>/<topicId>`.
- Tool names in the skill must exist in `src/dr_panda_mcp/capabilities.py`.
  `scripts/check_skill.py` fails CI on an unknown name, a hardcoded
  `mcp__drpanda__`, a broken reference, a missing README/Cursor link, or a
  possible secret.
- The skill declares `metadata.version` and `metadata.requires`; update both
  when the tool surface or minimum server version changes.

## Validation

```bash
uv run python scripts/check_skill.py
uv run ruff check .
uv run pytest -q
uv run python scripts/check_docs_links.py
```

CI runs the skill check in the test job; pre-commit runs it when the skill,
validator, tests, or README changes.

The check is deliberately dependency-free: it reads
`src/dr_panda_mcp/capabilities.py` as text, so it also works in a bare Python
environment.

## Evaluation

Before changing behavior, run the 10 scenarios in
[`references/playbooks.md`](../.dsh/skills/dr-panda-mcp/references/playbooks.md)
with a fresh session, with and without the skill. Track:

- first correct tool call;
- wrong environment or target rate;
- retry-after-denial rate;
- average tool calls per incident;
- truncated results reported as complete (must be zero);
- forbidden write attempts (must be zero).

## Design rules

- Keep `SKILL.md` short enough to load comfortably; put detail in references.
- Do not duplicate the 39-tool catalog; use the live tool schema.
- Do not duplicate the entire README; link to it.
- Do not make the skill a security boundary; guards are the boundary.
- Do not hardcode a server name, environment, target, or selector.
- Prefer one clear next action over a menu of ten.

## What it does not do

- It does not register targets, create tokens, or change settings.
- It does not add tools or permissions.
- It does not replace the web console or operator documentation.
- It does not work when the DrPanda MCP server is not configured; it tells the
  agent to stop and ask.
