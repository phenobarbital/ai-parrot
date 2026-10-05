# TASK-4069: Spike S3: stdio MCP host cwd/env probe

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0, spike **S3**: the `--portable` host-config form (spec §3 M5) drops absolute
`cwd`/`--config` paths and relies on the launcher finding the project at run time
(`--project`/`PARROT_PROJECT` → `CLAUDE_PROJECT_DIR` → cwd walk-up, spec §3 M1). Whether that
works depends on what each host actually gives a stdio MCP server: its working directory and
which environment variables. Gemini/Antigravity's config is **user-global**
(`~/.gemini/config/mcp_config.json`), so its cwd is the most suspect.

This task ships a tiny probe MCP server and the report template. Its evidence decides whether
the portable emitters in TASK-4082 (Claude), TASK-4083 (Codex) and TASK-4084 (Google) emit
`env: {"PARROT_PROJECT": ...}` — and in which syntax — or rely on cwd alone (shared brief:
"emit `PARROT_PROJECT` ONLY if the host expands variables, otherwise omit `cwd` and rely on the
launcher's cwd walk").

**The probe launches are human-run**: they need a person with the Claude Code, Codex and
Gemini/Antigravity CLIs installed and logged in. The coding agent writes the probe, its test
and the report skeleton only.

---

## Scope

- Implement `scripts/install/probe_mcp_env.py`: a stdlib-only newline-JSON stdio MCP server
  answering `initialize` and `tools/list` (empty list), that on startup logs cwd, argv,
  `sys.executable` and the env vars `CLAUDE_PROJECT_DIR`, `VIRTUAL_ENV`, `PARROT_PROJECT`,
  `PWD`, `CODEX_HOME` and every `GEMINI_*` to stderr AND appends one JSON line to
  `$PARROT_PROBE_LOG` (default `<tempdir>/parrot-probe-mcp-env.jsonl`).
- Write a subprocess test of the probe (handshake + log line).
- Write `sdd/state/FEAT-633/spikes/S3-host-env-probe.md` with exact registration snippets per
  host/scope and the launch matrix to fill.

**NOT in scope**: changing any host installer or emitter (TASK-4081..4084); deciding the
portable env form in code; launcher project-root logic (TASK-4071).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/probe_mcp_env.py` | CREATE | Stdlib stdio MCP probe server logging cwd/argv/env |
| `packages/ai-parrot/tests/docs/test_probe_mcp_env.py` | CREATE | Subprocess test: initialize + tools/list + JSONL log |
| `sdd/state/FEAT-633/spikes/S3-host-env-probe.md` | CREATE | Registration snippets, launch matrix, decision |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Stdlib only. The probe imports NOTHING from parrot (it must run under any Python a host picks).
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/local_server.py — wire format to mimic exactly
class StdioMCPServer(LocalMCPServerBase):          # line 54
    async def start(self): ...                      # line 70 — one JSON message per stdin line (readline, :87); EOF ends loop (:88-89)
    def _send(self, response): ...                  # line 187 — json.dumps(response) + "\n" on stdout (:193)
    async def _handle_request(self, request): ...   # line 198 — initialize (:205), tools/list (:207), ping → {} (:211),
                                                    #   notifications/* → no response (:213-219), unknown → error -32603 (:233-241)

# packages/ai-parrot/src/parrot/mcp/server_base.py
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")   # lines 17-21
def negotiate_protocol_version(requested: str | None) -> str:              # line 29 (requested if supported, else latest; None → oldest)
async def handle_initialize(self, params) -> dict:                         # line 80 — {"protocolVersion","capabilities":{"tools":{"listChanged":False}},"serverInfo":{...}}

# Host config locations (for the report snippets)
# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:61-63
def default_mcp_config_path() -> Path:   # Path.home() / ".gemini" / "config" / "mcp_config.json"  (USER-GLOBAL)
# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:74-80 — wikitoolkit entry today carries "cwd": str(root.resolve())
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py:188 — project config path root / ".codex" / "config.toml"
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py:19 — MCP_TABLE = "mcp_servers.wikitoolkit" (table naming pattern)
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:114-120 — .mcp.json entry {"command", "args", "env": {}}
```

### Does NOT Exist
- ~~`scripts/install/__init__.py`~~ — load the probe by path in the test.
- ~~`PARROT_PROBE_LOG`, `PARROT_PROJECT`~~ — both new names (spec §6 Does NOT Exist lists `PARROT_PROJECT`).
- ~~a parrot-side `tools/call` handler in the probe~~ — not needed; `tools/list` returns `{"tools": []}`.
- ~~Content-Length framing~~ — parrot's stdio servers are newline-delimited JSON.
- ~~`packages/ai-parrot/tests/docs/__init__.py`~~ — do not create it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/install/probe_mcp_env.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/docs/test_probe_mcp_env.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-633/spikes/S3-host-env-probe.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer._handle_request",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer._send",
    "sym:packages/ai-parrot/src/parrot/mcp/server_base.py#negotiate_protocol_version",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#default_mcp_config_path"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror `StdioMCPServer._handle_request` dispatch (initialize / tools/list / ping /
notifications / unknown → JSON-RPC error) in ~40 lines of synchronous stdlib code.

### Key Constraints
- **stdout is the JSON-RPC channel** — every diagnostic goes to `sys.stderr.write`; the probe
  itself must satisfy spec §5 AC4.
- Log the snapshot **once at startup, before reading stdin** — a host that only spawns the
  server and lists tools must still leave a record.
- The JSONL append must never crash the server (wrap in `try/except OSError`; report to stderr).
- Include a UTC ISO timestamp and `os.getpid()` in each record so multiple hosts/launches can be
  told apart in one log file.
- Python ≥ 3.11 stdlib only; must also run under whatever `python` the host config names.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/local_server.py` — server loop to mimic
- `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` — Gemini user-global config path

---

## Implementation Blueprint

### Steps (in order)
1. Write `collect_snapshot` and `handle` as pure functions — *why*: unit-testable without a subprocess.
2. Write `main` (snapshot → log → stdin loop) — *why*: matches StdioMCPServer's lifecycle.
3. Write the subprocess test — *why*: proves the handshake and the JSONL record end-to-end.
4. Write the S3 report with snippets + matrix — *why*: the human run needs copy-paste configs.

### `scripts/install/probe_mcp_env.py` (CREATE)
```python
#!/usr/bin/env python3
"""Stdio MCP probe: records what a host gives an MCP server (FEAT-633 spike S3).

Register it in Claude Code / Codex / Gemini like any stdio server; it answers
``initialize`` and ``tools/list`` (no tools) and logs cwd, argv, interpreter and
selected env vars to stderr and to ``$PARROT_PROBE_LOG`` (JSON lines).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_KEYS: tuple[str, ...] = ("CLAUDE_PROJECT_DIR", "VIRTUAL_ENV", "PARROT_PROJECT", "PWD", "CODEX_HOME")
ENV_PREFIXES: tuple[str, ...] = ("GEMINI_",)
LOG_ENV = "PARROT_PROBE_LOG"
SUPPORTED = ("2024-11-05", "2025-03-26", "2025-06-18")   # mirrors server_base.py:17-21


def log_path(env: Mapping[str, str]) -> Path:
    """``$PARROT_PROBE_LOG`` or ``<tempdir>/parrot-probe-mcp-env.jsonl``."""
    return Path(env.get(LOG_ENV) or Path(tempfile.gettempdir()) / "parrot-probe-mcp-env.jsonl")


def collect_snapshot(env: Mapping[str, str], argv: list[str], cwd: str) -> dict[str, Any]:
    """Return the record: timestamp, pid, cwd, argv, executable and the selected env vars."""
    selected = {k: env[k] for k in ENV_KEYS if k in env}
    selected.update({k: v for k, v in env.items() if k.startswith(ENV_PREFIXES)})
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "cwd": cwd,
        "argv": argv,
        "executable": sys.executable,
        "env": selected,
    }


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    """Answer one JSON-RPC request; ``None`` for notifications (no response)."""
    method, req_id = request.get("method"), request.get("id")
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "initialize":
        requested = (request.get("params") or {}).get("protocolVersion")
        # FILL IN: negotiate like server_base.negotiate_protocol_version (:29-44) using SUPPORTED;
        #   result = {"protocolVersion", "capabilities": {"tools": {"listChanged": False}},
        #   "serverInfo": {"name": "parrot-probe", "version": "0"}} — bounded by server_base.py:84-98
        raise NotImplementedError
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main() -> int:
    """Log the snapshot, then serve newline-delimited JSON-RPC until stdin EOF."""
    snapshot = collect_snapshot(os.environ, sys.argv, os.getcwd())
    line = json.dumps(snapshot, sort_keys=True)
    sys.stderr.write(f"parrot-probe: {line}\n")
    try:
        with log_path(os.environ).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        sys.stderr.write(f"parrot-probe: cannot append log: {exc}\n")
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        # FILL IN: json.loads (invalid JSON → stderr warning, continue); response = handle(req);
        #   if response: sys.stdout.write(json.dumps(response) + "\n"); sys.stdout.flush()
        #   — bounded by local_server.py:95-99 (skip invalid JSON) and :193 (framing)
        raise NotImplementedError
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: pure `collect_snapshot`/`handle` keep the test cheap; logging before the
stdin loop captures hosts that only spawn + list. `-32601` (method not found) is the JSON-RPC
standard code; parrot's server uses `-32603` for everything — either is acceptable to hosts.

### `packages/ai-parrot/tests/docs/test_probe_mcp_env.py` (CREATE)
```python
"""Tests for scripts/install/probe_mcp_env.py (FEAT-633 spike S3)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "probe_mcp_env.py"


def _run(tmp_path: Path, extra_env: dict[str, str]) -> tuple[list[dict], Path]:
    log = tmp_path / "probe.jsonl"
    env = {**os.environ, "PARROT_PROBE_LOG": str(log), **extra_env}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--marker"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        capture_output=True, text=True, cwd=tmp_path, env=env, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()], log


def test_handshake_and_empty_tool_list(tmp_path):
    responses, _ = _run(tmp_path, {})
    assert [r["id"] for r in responses] == [1, 2]          # notification got no response
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert responses[1]["result"] == {"tools": []}


def test_log_record_contents(tmp_path):
    _, log = _run(tmp_path, {"CLAUDE_PROJECT_DIR": "/x", "GEMINI_FOO": "bar", "PARROT_PROJECT": "/p"})
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert Path(record["cwd"]).resolve() == tmp_path.resolve()
    assert record["argv"][-1] == "--marker"
    assert record["env"]["CLAUDE_PROJECT_DIR"] == "/x"
    assert record["env"]["GEMINI_FOO"] == "bar"
    assert record["env"]["PARROT_PROJECT"] == "/p"
    assert "executable" in record and "pid" in record
```

### `sdd/state/FEAT-633/spikes/S3-host-env-probe.md` (CREATE)
````markdown
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
````

### FILL IN checklist
- [ ] `probe_mcp_env.py::handle` — initialize result with negotiated version; bounded by server_base.py:29-44,84-98
- [ ] `probe_mcp_env.py::main` — stdin loop parse/respond; bounded by local_server.py framing
- [ ] Report snippets — confirm each host's variable-expansion syntax against that host's current docs before the human run

---

## Acceptance Criteria

- [ ] `probe_mcp_env.py` imports only the stdlib and writes nothing but JSON-RPC responses to stdout.
- [ ] `initialize` returns a negotiated `protocolVersion` + `capabilities` + `serverInfo`; `tools/list` returns `{"tools": []}`; notifications get no response.
- [ ] One JSON line per launch is appended to `$PARROT_PROBE_LOG` (default `<tempdir>/parrot-probe-mcp-env.jsonl`) with ts, pid, cwd, argv, executable and the selected env vars (incl. every `GEMINI_*`), and the same record goes to stderr.
- [ ] `S3-host-env-probe.md` has registration snippets for Claude (project + user), Codex (project + user), Gemini (user-global), the 10-row launch matrix, the decision rule, and is marked HUMAN-RUN.
- [ ] `ruff check scripts/install/probe_mcp_env.py packages/ai-parrot/tests/docs/test_probe_mcp_env.py` passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_probe_mcp_env.py -q`

---

## Test Specification

The full test file is the `test_probe_mcp_env.py` blueprint block above: a subprocess
handshake (initialize → notification → tools/list) and a JSONL record assertion. No network,
no parrot import.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4069 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
