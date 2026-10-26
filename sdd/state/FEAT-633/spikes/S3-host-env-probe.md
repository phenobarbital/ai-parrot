# Spike S3 — what stdio MCP hosts give a server (FEAT-633)

> **HUMAN-RUN**: requires a person with Claude Code, Codex CLI and Gemini/Antigravity installed.
> Replace `<PY>` with an absolute Python ≥ 3.11 and `<REPO>` with the absolute repo path.
> Optional: `export PARROT_PROBE_LOG=/tmp/probe.jsonl` before launching each host.

## Registration snippets
**Claude Code — project scope** (`<REPO>/.mcp.json`):
```json
{"mcpServers": {"parrot-probe": {"command": "<PY>", "args": ["<REPO>/scripts/install/probe_mcp_env.py"],
  "env": {"PARROT_PROJECT": "${CLAUDE_PROJECT_DIR}"}}}}
```
**Claude Code — user scope**: `claude mcp add --scope user parrot-probe -- <PY> <REPO>/scripts/install/probe_mcp_env.py`
**Codex — project** (`<REPO>/.codex/config.toml`) and **user** (`~/.codex/config.toml`):
```toml
[mcp_servers.parrot-probe]
command = "<PY>"
args = ["<REPO>/scripts/install/probe_mcp_env.py"]
env = { PARROT_PROJECT = "${PWD}" }
```
**Gemini/Antigravity — user-global** (`~/.gemini/config/mcp_config.json`, google/assets.py:61-63):
```json
{"mcpServers": {"parrot-probe": {"command": "<PY>", "args": ["<REPO>/scripts/install/probe_mcp_env.py"],
  "env": {"PARROT_PROJECT": "${workspaceFolder}"}}}}
```
The `env` values test variable expansion: record whether the logged value is the literal string or expanded.

## Launch matrix (fill from the JSONL log)
| Host | Scope | Launched from | cwd | CLAUDE_PROJECT_DIR | PWD | PARROT_PROJECT (expanded?) | VIRTUAL_ENV | Other |
|---|---|---|---|---|---|---|---|---|
| Claude Code | project | repo root | | | | | | |
| Claude Code | project | linked worktree | | | | | | |
| Claude Code | user | repo root | | | | | | |
| Claude Code | user | linked worktree | | | | | | |
| Codex | project | repo root | | | | | | |
| Codex | project | linked worktree | | | | | | |
| Codex | user | repo root | | | | | | |
| Codex | user | linked worktree | | | | | | |
| Gemini | user-global | repo root | | | | | | |
| Gemini | user-global | linked worktree | | | | | | |

## Decision it feeds (TASK-4082 / 4083 / 4084)
Per host: does the server's cwd equal the project (or worktree) root? Does the host expand
variables in `env`, and with which syntax? ⇒ portable emission rule per host:
- cwd reliable ⇒ omit `cwd` and `PARROT_PROJECT`; the launcher's cwd walk finds the root.
- cwd unreliable but env expansion works ⇒ emit `env.PARROT_PROJECT` with the verified syntax.
- neither ⇒ portable mode for that host requires `--project` in args or is documented unsupported.

## Verdict
<!-- per host: rule chosen, date, host CLI versions -->
