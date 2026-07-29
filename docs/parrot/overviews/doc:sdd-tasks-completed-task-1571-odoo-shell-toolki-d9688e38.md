---
type: Wiki Overview
title: 'TASK-1571: OdooToolkit `odoo-bin` / `odoo-cli` shell functions'
id: doc:sdd-tasks-completed-task-1571-odoo-shell-toolkit-functions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of the spec. The existing `OdooToolkit` is RPC-only
relates_to:
- concept: mod:parrot_tools.odoo
  rel: mentions
---

# TASK-1571: OdooToolkit `odoo-bin` / `odoo-cli` shell functions

**Feature**: FEAT-240 — Odoo PageIndex Documentation Agent
**Spec**: `sdd/specs/odoo-pageindex-documentation-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. The existing `OdooToolkit` is RPC-only
(JSON-2 / XML-RPC / JSON-RPC). This task adds subprocess-based tools that drive
the local `odoo-bin` / `odoo-cli` binaries (module install/upgrade, scaffold,
generic CLI passthrough), gated by HITL confirmation. Enables G9 / AC10.

---

## Scope

- Add `packages/ai-parrot-tools/src/parrot_tools/odoo/shell.py` with a typed
  `ShellResult` Pydantic model and helpers to resolve the binary/config/db from
  env (`ODOO_BIN`, `ODOO_CONF`, `ODOO_TEST_DATABASE`).
- Add new async tools to `OdooToolkit` (in `toolkit.py`, or a mixed-in class
  composed from `shell.py`):
  - `odoo_shell_install_module(modules: list[str], database: str | None, upgrade: bool=False)`
  - `odoo_shell_upgrade_module(modules: list[str], database: str | None)`
  - `odoo_cli_command(subcommand: str, args: list[str], database: str | None)`
- Build argv with `asyncio.create_subprocess_exec` — **never** `shell=True`.
  Install/upgrade use `odoo-bin -d <db> -i|-u <csv> --stop-after-init`.
- Validate inputs: reject empty module lists; whitelist allowed CLI subcommands;
  reject shell metacharacters in module/subcommand names.
- Enforce a timeout; capture stdout/stderr/returncode into `ShellResult`.
- When `ODOO_BIN` is unset/unreachable, the tools must **self-disable** with a
  clear message (return a `ShellResult(success=False, ...)` or skip registration)
  — never raise an unhandled exception / crash toolkit init.
- Register every new shell tool in `OdooToolkit.confirming_tools` so the HITL
  guard requires confirmation before execution.
- Unit tests under `packages/ai-parrot-tools/tests/`.

**NOT in scope**: the agent wiring (TASK-1574); the ConfirmationGuard instance
(TASK-1574 attaches it); doc generation (TASK-1572).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/shell.py` | CREATE | `ShellResult`, env resolution, argv builders, subprocess runner |
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add the 3 shell tools; extend `confirming_tools` |
| `packages/ai-parrot-tools/tests/test_odoo_shell.py` | CREATE | Unit tests (argv build, whitelist, self-disable, confirming) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.odoo import OdooToolkit          # verified: parrot_tools/odoo/__init__.py exports OdooToolkit
from pydantic import BaseModel, Field
import asyncio  # asyncio.create_subprocess_exec
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
class OdooToolkit(AbstractToolkit):                 # line 159 ; tool_prefix = "odoo" (line 178)
    def __init__(self, url=None, database=None, username=None, password=None,
                 timeout=None, verify_ssl=None, protocol="auto",
                 transport=None, **kwargs): ...      # lines 180-191
    async def cleanup(self) -> None: ...

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    confirming_tools: frozenset[str] = frozenset()  # lines 264-276
    # Method names listed in confirming_tools get
    # routing_meta["requires_confirmation"] = True applied at tool-build time
    # (toolkit.py:575-578). Public async methods become tools automatically.
```

### Does NOT Exist
- ~~existing `odoo-bin`/`odoo-cli`/shell tools on `OdooToolkit`~~ — RPC-only today; these are NEW.
- ~~`OdooToolkit.run_shell()` / `OdooToolkit.exec_cli()`~~ — do not exist; create them.
- ~~a global "shell enabled" flag~~ — gate by presence of `ODOO_BIN` env var.

---

## Implementation Notes

### Pattern to Follow
- Public async methods on a toolkit become tools automatically; name them
  `odoo_shell_*` / `odoo_cli_*` so the `odoo` prefix yields clear tool names.
- Mirror existing toolkit method style in `toolkit.py` (`@tool_schema` Pydantic
  inputs, typed return envelope) — read 2-3 existing tools first.

### Key Constraints
- `asyncio.create_subprocess_exec(*argv, ...)` only — no `shell=True`, no string
  command interpolation.
- Validate every interpolated token (module names, subcommand) against a strict
  allowlist regex (e.g. `^[a-zA-Z0-9_.-]+$`); raise `ValueError` otherwise.
- Whitelist CLI subcommands (e.g. `{"scaffold", "populate", "db", "shell"}` — pick a
  conservative set and document it).
- Default `database` to `os.getenv("ODOO_TEST_DATABASE")`.
- async throughout; `self.logger` at start/finish/failure of each shell call.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` — toolkit + tool style, `confirming_tools` usage.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:264-276,575-578` — `confirming_tools` → `requires_confirmation`.

---

## Acceptance Criteria

- [ ] `odoo_shell_install_module` builds `odoo-bin -d <db> -i <csv> --stop-after-init` argv; no `shell=True`.
- [ ] `odoo_shell_upgrade_module` uses `-u`.
- [ ] Non-whitelisted CLI subcommands rejected with `ValueError`.
- [ ] Empty module list / illegal chars rejected.
- [ ] All shell tools present in `confirming_tools` → built tools have `routing_meta["requires_confirmation"] is True`.
- [ ] Tools self-disable cleanly (no crash) when `ODOO_BIN` unset.
- [ ] No breaking change to existing RPC tools.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/test_odoo_shell.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/odoo/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_odoo_shell.py
import pytest
from parrot_tools.odoo import OdooToolkit


def test_install_argv(monkeypatch):
    monkeypatch.setenv("ODOO_BIN", "/opt/odoo/odoo-bin")
    monkeypatch.setenv("ODOO_TEST_DATABASE", "odoo")
    tk = OdooToolkit(url="http://x", database="odoo", username="u", password="p")
    argv = tk._build_install_argv(["sale", "stock"], database="odoo", upgrade=False)
    assert "shell" not in argv  # not shell=True
    assert "-i" in argv and "sale,stock" in argv and "--stop-after-init" in argv


def test_subcommand_whitelist(monkeypatch):
    monkeypatch.setenv("ODOO_BIN", "/opt/odoo/odoo-bin")
    tk = OdooToolkit(url="http://x", database="odoo", username="u", password="p")
    with pytest.raises(ValueError):
        tk._validate_subcommand("rm -rf /")


def test_shell_tools_are_confirming():
    assert "odoo_shell_install_module" in OdooToolkit.confirming_tools


def test_disabled_without_bin(monkeypatch):
    monkeypatch.delenv("ODOO_BIN", raising=False)
    tk = OdooToolkit(url="http://x", database="odoo", username="u", password="p")
    # init must not crash; tool returns a clear disabled result (shape per impl)
    assert tk is not None
```

---

## Agent Instructions

1. Read the spec (§3 Module 1, §6, §7) for full context.
2. Verify the Codebase Contract before writing code.
3. Update index status → `in-progress`.
4. Implement per scope; keep RPC API intact.
5. Verify all acceptance criteria.
6. Move this file to `sdd/tasks/completed/`.
7. Update index → `done`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Implemented `shell.py` with `ShellResult`, token validation, argv builders, and `run_odoo_subprocess`. Added `odoo_shell_install_module`, `odoo_shell_upgrade_module`, and `odoo_cli_command` methods to `OdooToolkit` with all 3 listed in `confirming_tools`. All 19 unit tests pass.

**Deviations from spec**: none
