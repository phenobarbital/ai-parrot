# Spike S3 — what stdio MCP hosts give a server (FEAT-633)

> **Status (2026-10-29): complete.** Claude Code was run in the sandbox (2026-10-28). Codex, the Antigravity CLI and
> Claude Code user scope were run by a human (2026-10-29). The verdict is at the end of this file.
>
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
   - Fixed in this branch: `mcp/local_cli.py::_project_root_for` walks up to the nearest ancestor that holds the config, never
     past the nearest project marker (`.mcp.json`, `.codex/config.toml`, `.git`), and then changes into that root as a baked `cwd` would.
   - Baked entries pin an absolute `--config` and `cwd`, so they were never affected.
3. With the cwd walk fixed, the Claude rule stays: **portable = omit `cwd` and `PARROT_PROJECT`**.

## Codex, Antigravity and Claude user-scope rows (FEAT-633 R8, human run 2026-10-29)
A human ran these outside the sandbox on Linux with Claude Code 2.1.312, Codex CLI 0.163.0 and Antigravity CLI
(`agy`) 1.4.9. The lab was the same layout as above: a throwaway repo `repo/`, a linked worktree `wt/`, and
`repo/sub/deep`. A launch marker was written before each host start and matched to the probe records by time and
label. Raw data is 18 launches and 27 probe starts, including the Antigravity re-run. Every host config was restored afterwards: Codex and Gemini are
byte-identical to their backups, and `claude mcp list` / `codex mcp list` / `agy mcp list` show no probe.

- **Claude Code user scope:** `claude mcp add --scope user … -e 'PARROT_PROJECT=${PWD}'`, then `claude -p`.
- **Codex project scope:** `<repo>/.codex/config.toml` and `<wt>/.codex/config.toml` with
  `env = { PARROT_PROJECT = "${PWD}" }`, launched as an interactive `codex`.
- **Codex user scope:** `codex mcp add … --env 'PARROT_PROJECT=${PWD}'`, then `codex exec`.
- **Antigravity user-global:** `agy mcp add -e 'PARROT_PROJECT=${workspaceFolder}' …`, then `agy --print`. This writes
  `~/.gemini/config/mcp_config.json`.
  - The first pass exited 1 on an account eligibility check, after the MCP servers had already started.
  - It was re-run with an eligible account the same day: all three launches exited 0 and the agent answered.
  - Both passes recorded the same cwd and env (3 + 3 probe starts).
  - The Antigravity IDE (`~/.gemini/antigravity/mcp_config.json`) was not exercised.

The probe records only `CLAUDE_PROJECT_DIR`, `VIRTUAL_ENV`, `PARROT_PROJECT`, `PWD`, `CODEX_HOME` and `GEMINI_*`.
"absent" below means the host did not pass that variable to the server.

| Host | Scope | Launched from | cwd | CLAUDE_PROJECT_DIR | PWD | PARROT_PROJECT (expanded?) | VIRTUAL_ENV | Other |
|---|---|---|---|---|---|---|---|---|
| Claude Code | user | repo root | repo | repo | repo | `${PWD}` → repo (expanded) | unset | project `.mcp.json` server also started |
| Claude Code | user | linked worktree | wt | wt | wt | `${PWD}` → wt (expanded) | unset | project server also started |
| Claude Code | user | `repo/sub/deep` | **repo/sub/deep** | repo/sub/deep | repo/sub/deep | `${PWD}` → repo/sub/deep | unset | project server also started (walk-up) |
| Codex | project | repo root | repo | absent | absent | `${PWD}`, **literal** | absent | 2 server starts per interactive session |
| Codex | project | linked worktree | wt | absent | absent | `${PWD}`, **literal** | absent | 2 starts per session |
| Codex | project | `repo/sub/deep` | **repo/sub/deep** | absent | absent | `${PWD}`, **literal** | absent | `.codex/config.toml` found by walking up |
| Codex | user | repo root | repo | absent | absent | `${PWD}`, **literal** | absent | project server also started |
| Codex | user | linked worktree | wt | absent | absent | `${PWD}`, **literal** | absent | project server also started |
| Codex | user | `repo/sub/deep` | **repo/sub/deep** | absent | absent | `${PWD}`, **literal** | absent | project server also started |
| Antigravity CLI | user-global | repo root | repo | absent | repo | `${workspaceFolder}`, **literal** | absent | session exit 0 |
| Antigravity CLI | user-global | linked worktree | wt | absent | wt | `${workspaceFolder}`, **literal** | absent | session exit 0 |
| Antigravity CLI | user-global | `repo/sub/deep` | **repo/sub/deep** | absent | repo/sub/deep | `${workspaceFolder}`, **literal** | absent | session exit 0 |

Findings:
4. **All three hosts start the server in the launch directory.** No host moves it to the project root, so the Claude
   finding (2) holds for Codex and Antigravity too. A launch from a subdirectory gives a subdirectory cwd.
5. **No host expands a project variable in `env`.**
   - Codex passes `${PWD}` through literally and strips `PWD` from the server environment.
   - Antigravity passes `${workspaceFolder}` through literally.
   - Claude Code expands only variables from its own environment. `${PWD}` works there, but it is the launch
     directory again, so it adds nothing over the cwd.
   - A `PARROT_PROJECT` pin would therefore be either a literal string or the cwd, so the installers are right to
     emit none.
6. **Codex finds the project `.codex/config.toml` by walking up from a subdirectory**, as Claude does with `.mcp.json`.
   The R8 fix (`_project_root_for`) covers both, because `.codex/config.toml` is one of its project markers.
   - Antigravity's portable config is user-global, so the nearest `.git` is the boundary.
   - In a directory with no `.parrot/mcp-toolkits.yaml` up to that boundary, a portable `parrot-*` entry fails with
     "Toolkit config file not found". That is expected for a user-global entry outside a parrot project.
   - `wikitoolkit mcp` walks up on its own.
7. Codex passes neither `CLAUDE_PROJECT_DIR` nor `PWD`, so the launcher's `find_project_root` falls through to its
   `.git` walk-up from the cwd.
   - That finds the right project, including a linked worktree, because `wt/.git` is a file.
   - Under Claude Code, `CLAUDE_PROJECT_DIR` is the launch subdirectory; this is tracked as `issue:7c1d07eaa1f1`.

## Verdict
Portable rule for all three hosts: **omit `cwd` and `PARROT_PROJECT`; consumers walk up from the cwd.** This is what
the Claude, Codex and Gemini installers already emit.
- Claude Code 2.1.312: project and user scope.
- Codex CLI 0.163.0: project and user scope.
- Antigravity CLI 1.4.9: user-global.

No installer change is needed beyond the R8 cwd walk already on this branch. Re-check if a host adds variable
expansion, or a project-root cwd, in a later release.
