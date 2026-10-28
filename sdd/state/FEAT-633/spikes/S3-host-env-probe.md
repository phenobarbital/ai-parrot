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


## Claude Code rows (FEAT-633 R8, run 2026-10-28)
Claude Code 2.1.312, headless (`claude -p … --max-turns 1`), Linux, run inside the Claude Code Bubblewrap sandbox. The
host was a throwaway git repo (`repo/`) with a linked worktree (`wt/`), and `${CLAUDE_PROJECT_DIR}`, `VIRTUAL_ENV`
and `PARROT_PROJECT` were unset in the launching shell.
- **Project scope:** `.mcp.json` in `repo/` and in `wt/`, approved non-interactively with
  `--settings '{"enableAllProjectMcpServers": true}'`. Its `env` held `PARROT_PROJECT: "${CLAUDE_PROJECT_DIR}"`.
- **User scope** was not run: registering it writes `~/.claude.json`, which the sandbox keeps read-only. The closest
  stand-in, `--mcp-config <file> --strict-mcp-config` with `PARROT_PROJECT: "${PWD}"`, is reported as "dynamic".

| Host | Scope | Launched from | cwd | CLAUDE_PROJECT_DIR | PWD | PARROT_PROJECT (expanded?) | VIRTUAL_ENV | Other |
|---|---|---|---|---|---|---|---|---|
| Claude Code | project | repo root | repo | repo | repo | `${CLAUDE_PROJECT_DIR}`, **literal** | unset | — |
| Claude Code | project | linked worktree | wt | wt | wt | `${CLAUDE_PROJECT_DIR}`, **literal** | unset | — |
| Claude Code | project | `repo/sub/deep` | **repo/sub/deep** | **repo/sub/deep** | repo/sub/deep | `${CLAUDE_PROJECT_DIR}`, **literal** | unset | `.mcp.json` found by walking up |
| Claude Code | dynamic (`--mcp-config`) | repo root | repo | repo | repo | `${PWD}` → repo (expanded) | unset | — |
| Claude Code | dynamic (`--mcp-config`) | linked worktree | wt | wt | wt | `${PWD}` → wt (expanded) | unset | — |

Findings:
1. **`${CLAUDE_PROJECT_DIR}` is not expanded in `env`.** Claude expands `${VAR}` from its own environment, and
   `CLAUDE_PROJECT_DIR` is only set for its children. Emitting `PARROT_PROJECT: "${CLAUDE_PROJECT_DIR}"` would hand the
   server a literal string. Omitting `PARROT_PROJECT` (rev 0.5) is correct. The server receives `CLAUDE_PROJECT_DIR`
   directly anyway.
2. **The server's cwd is the launch directory, not the project root.** Claude finds the project `.mcp.json` by walking
   up, but starts the server where it was launched, and `CLAUDE_PROJECT_DIR` is that directory too. So "cwd reliable"
   holds only from the root or a worktree root.
   - `wikitoolkit mcp` walks up, so it is unaffected.
   - Portable `parrot mcp-local … --config .parrot/mcp-toolkits.yaml` resolved the relative config against the cwd and
     failed from a subdirectory (`ValueError: Toolkit config file not found`).
   - Fixed in this branch: `mcp/local_cli.py::_project_root_for` walks up to the nearest ancestor that holds the config,
     bounded by the enclosing git root.
   - Baked entries pin an absolute `--config` and `cwd`, so they were never affected.
3. With the cwd walk fixed, the Claude rule stays: **portable = omit `cwd` and `PARROT_PROJECT`**.

## Rows still to run (HUMAN-RUN)
- **Codex:** `codex` cannot start inside the sandbox (`~/.codex` is read-only).
- **Gemini/Antigravity:** no Gemini CLI is installed on this machine.
- **Claude Code user scope:** needs writes to `~/.claude.json`.

Nothing else blocks on these: Gemini emits baked entries only, and Codex follows the same omit rule. A person
with both CLIs can fill the remaining rows with the snippets above.

## Verdict
- Claude Code: portable rule = omit `cwd` and `PARROT_PROJECT`; consumers walk up from the cwd. 2026-10-28, Claude Code
  2.1.312.
- Codex, Gemini: pending (HUMAN-RUN).
