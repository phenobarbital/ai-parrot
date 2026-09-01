# TASK-2647: `parrot mcp-local` CLI command + lazy registration

**Feature**: FEAT-485 — Expose Toolkits as Local MCP
**Spec**: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2646
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The user-facing entry point every `.mcp.json` /
`.codex/config.toml` entry invokes. Top-level lazy command `mcp-local`
(the `parrot mcp` Click group is OWNED by ai-parrot-server — core cannot
attach a subcommand to it; precedent: agentd's `mcp-serve`).

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/mcp/local_cli.py`:
  - Click command `mcp_local` exposed so `LazyGroup` can load it (mirror
    how other lazy modules export their command — check one, e.g.
    `parrot.cli.generate_keys`, for the exported symbol convention).
  - `parrot mcp-local <name> [--config PATH] [--include NAME ...]
    [--exclude NAME ...]`: build server via
    `create_toolkit_mcp_server(name, root, ...)`, then
    `asyncio.run(server.start())`. Project root = cwd (the MCP host starts
    servers in the project dir; document this).
  - `parrot mcp-local --list`: print resolvable names (builtins + config
    sections) with enabled state and class path. Listing does NOT import
    toolkit classes (fast path; spec open question resolved minimally —
    names + enabled state only).
  - Resolution/instantiation failures → message on **stderr**, exit
    non-zero. KeyboardInterrupt → clean exit 0.
- MODIFY `packages/ai-parrot/src/parrot/cli/__init__.py`: add
  `"mcp-local": "parrot.mcp.local_cli"` to `cli._lazy_commands`.
- Unit tests via `click.testing.CliRunner`.

**NOT in scope**: the factory logic (TASK-2646); installer entries
(TASK-2648/2649); a `parrot mcp local` alias in the server package
(explicit non-v1 per spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | CREATE | click command |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | one registry line |
| `tests/mcp/test_local_cli.py` | CREATE | CliRunner tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click
from parrot.mcp.toolkit_server import create_toolkit_mcp_server  # created by TASK-2646
from parrot.mcp.toolkit_config import load_toolkits_config       # created by TASK-2645
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):  # line ~19
    def get_command(self, ctx, cmd_name):  # line 70 — importlib.import_module(module_path)
    # After import, LazyGroup looks up the command object in the module —
    # READ get_command's body (lines 70-100) to confirm the exact attribute
    # convention (module-level click command matching the registered name,
    # hyphens vs underscores) before choosing the exported symbol name.
cli._lazy_commands = {  # line 109 — ADD "mcp-local": "parrot.mcp.local_cli"
    # existing entries include "mcp": "parrot.mcp.cli" (SERVER pkg — do not touch),
    # "mcp-serve": "parrot.integrations.agentd.cli" (naming precedent)
}
cli._lazy_extras = {  # line ~131 — optional install-hint registry; not needed
    # for mcp-local (core module, no extra), do not add an entry
}

# packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer:
    async def start(self):  # line 44 — blocking serve loop; run with asyncio.run()
    async def stop(self):   # line 80

# Reference for a lazy command module shape:
#   packages/ai-parrot/src/parrot/cli/generate_keys.py (registered as
#   "generate-keys" → "parrot.cli.generate_keys")
# Reference for stdio entry `main()` structure:
#   packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:192
```

### Does NOT Exist
- ~~`parrot/mcp/local_cli.py`~~ — this task creates it.
- ~~`parrot mcp local`~~ — cannot exist from core; the command is the
  top-level `mcp-local`.
- ~~`parrot/mcp/cli.py` in core~~ — forbidden filename; the server package
  owns it. Never create or import-modify it.
- ~~a `--list` that imports toolkit classes~~ — out of scope; list names,
  enabled state, and class path strings only.

---

## Implementation Notes

### Key Constraints
- Nothing may print to stdout before/around the serve loop — stdout is the
  JSON-RPC channel. `--list` output (a human command) goes to stdout
  normally; the SERVE path must keep stdout pure.
- Heavy imports (`toolkit_server` → toolkit classes) happen inside the
  command function, not at module top, so `parrot --help` stays fast and
  a bare `import parrot.mcp.local_cli` cannot pollute stdout.
- Exit codes: 0 clean/interrupt, non-zero on resolution/instantiation
  failure.

---

## Acceptance Criteria

- [ ] `parrot mcp-local --list` shows 3 builtins (+ config sections) with enabled state
- [ ] `parrot mcp-local nonsense` exits non-zero, stderr lists resolvable names
- [ ] `cli._lazy_commands["mcp-local"]` resolves via `LazyGroup.get_command`
- [ ] `--include`/`--exclude`/`--config` reach `create_toolkit_mcp_server` as overrides
- [ ] Serve path verified against the stub toolkit (CliRunner + mocked `server.start`)
- [ ] Tests pass: `pytest tests/mcp/test_local_cli.py -v`; ruff clean

---

## Test Specification

```python
# tests/mcp/test_local_cli.py
from click.testing import CliRunner
# import the command via the same path LazyGroup uses:
from parrot.cli import cli


def test_list_shows_builtins(tmp_path): ...
def test_unknown_name_nonzero(tmp_path): ...
def test_lazy_registration():
    from parrot.cli import cli as group
    assert group._lazy_commands["mcp-local"] == "parrot.mcp.local_cli"
def test_overrides_passed(monkeypatch): ...  # assert factory called with include/exclude
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2646 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — especially `LazyGroup.get_command`'s
   symbol-lookup convention (read cli/__init__.py:70-100 first)
4. **Update status** in `sdd/tasks/index/expose-toolkits-as-local-mcp.json` → `"in-progress"`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index** → `"done"`, **fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-start (Claude)
**Date**: 2026-09-01
**Notes**:
- Created `packages/ai-parrot/src/parrot/mcp/local_cli.py` exporting the
  `mcp_local` Click command (`@click.command("mcp-local")`), matching
  `LazyGroup.get_command`'s `cmd_name.replace("-", "_")` symbol-lookup
  convention (verified against `cli/__init__.py:70-100` first).
  `NAME` is a required-unless-`--list` argument; `--config`/`--include`
  (repeatable)/`--exclude` (repeatable) build an `overrides` dict passed
  to `create_toolkit_mcp_server(name, root, **overrides)` — only keys the
  user actually supplied are included. `--list` loads
  `load_toolkits_config(root)` and prints `name\tstate\tclass_path` without
  ever importing a toolkit class (regression-tested via `sys.modules`
  membership). Root logging is switched to stderr-only before the heavy
  `toolkit_server` import (deferred to inside the command function, so
  `parrot --help` / bare module import stay fast and stdout-clean).
  Resolution/instantiation failures (`ValueError`/`ImportError`) print to
  stderr and exit 1 (the underlying `ValueError` message already lists
  resolvable names); `KeyboardInterrupt` around `asyncio.run(server.start())`
  exits 0.
- Registered `"mcp-local": "parrot.mcp.local_cli"` in
  `packages/ai-parrot/src/parrot/cli/__init__.py`'s `cli._lazy_commands`
  (single line; did not touch `_lazy_extras` — no optional extra applies).
- Added `tests/mcp/test_local_cli.py` (9 tests, `click.testing.CliRunner`):
  `--list` shows the 3 built-ins with enabled state and never imports a
  toolkit class; unknown name exits non-zero with resolvable names on
  stderr; missing `NAME` without `--list` exits non-zero;
  `cli._lazy_commands["mcp-local"]` and `LazyGroup.get_command` resolution;
  `--config`/`--include`/`--exclude` reach `create_toolkit_mcp_server` as
  overrides (mocked factory + mocked `asyncio.run`); serve path against
  `tests.mcp.stub_toolkit.StubToolkit` with `StdioMCPServer.start` mocked;
  clean exit 0 on `KeyboardInterrupt`. All 9 pass; `ruff check` clean on
  both new/modified files.
- Pre-existing failures in `tests/mcp/test_toolkit_server.py` (8 tests,
  from TASK-2646 "done-with-issues") are unrelated to this task — verified
  identical failures on the pre-task commit via `git stash`. Not touched
  (out of scope; TASK-2646 already flagged this for follow-up).

**Deviations from spec**: none. One pre-existing gap noted for awareness:
`create_toolkit_mcp_server` (TASK-2646) documents a `config_path` override
in its docstring but does not actually thread it into `load_toolkits_config`
(always loads `root/.parrot/mcp-toolkits.yaml`). This task's acceptance
criterion is only that `--config` "reaches `create_toolkit_mcp_server` as
an override" — verified — not that the factory honors it yet; wiring
`config_path` through `load_toolkits_config` is a TASK-2646 follow-up, out
of this task's file scope.
