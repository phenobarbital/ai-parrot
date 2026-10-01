# TASK-3892: `ODOO_HELPDESK_*` configuration keys in `parrot.conf`

**Feature**: FEAT-616 — OdooHelpdeskToolkit — typed helpdesk tools for the Softhealer helpdesk (Odoo 19)
**Spec**: `sdd/specs/odoo-toolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the `parrot.conf` half of spec §3 **Module 2** (G4, AC2). The helpdesk instance has its own
credentials (`ODOO_HELPDESK_URL/USER/PASSWORD/APIKEY` already exist in `env/.env`) and nothing in the code
reads them today. `OdooHelpdeskToolkit` (TASK-3897) imports these constants and must never fall back to the
generic `ODOO_*` keys (design research S2). The key names match the env file exactly; `DATABASE`, `TIMEOUT`
and `VERIFY_SSL` are new optional keys.

---

## Scope

- Add seven constants after the existing `ODOO_*` block in `packages/ai-parrot/src/parrot/conf.py`.
- Nothing else.

**NOT in scope**: the toolkit constructor (TASK-3897), any change to the existing `ODOO_*` keys, `.env` files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `ODOO_HELPDESK_*` block |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# conf.py uses the module-level `config` object (navconfig) — no import needed for this task.
# Consumers (TASK-3897) will do:
from parrot.conf import ODOO_HELPDESK_URL, ODOO_HELPDESK_USER, ODOO_HELPDESK_PASSWORD, ODOO_HELPDESK_APIKEY, ODOO_HELPDESK_DATABASE, ODOO_HELPDESK_TIMEOUT, ODOO_HELPDESK_VERIFY_SSL
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py  (verified at b3141f286)
# line 811: # ── Odoo ERP (JSON-RPC 2.0) ──
ODOO_URL = config.get("ODOO_URL", fallback=None)                         # line 812
ODOO_DATABASE = config.get("ODOO_DATABASE", fallback=None)               # line 813
ODOO_USERNAME = config.get("ODOO_USERNAME", fallback=None)               # line 814
ODOO_PASSWORD = config.get("ODOO_PASSWORD", fallback=None)               # line 815
ODOO_TIMEOUT = config.getint("ODOO_TIMEOUT", fallback=30)                # line 816
ODOO_VERIFY_SSL = config.getboolean("ODOO_VERIFY_SSL", fallback=True)    # line 817
# line 819: # ── Zammad Helpdesk (REST API v1) ──
```

### Does NOT Exist
- ~~`ODOO_HELPDESK_USERNAME`~~ — the env key is `ODOO_HELPDESK_USER`; keep that exact name.
- ~~`ODOO_HELPDESK_PROTOCOL`~~ — not a key; protocol stays a constructor argument.
- ~~a `parrot.conf.helpdesk` submodule~~ — constants live flat in `conf.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Same `config.get / getint / getboolean` pattern as lines 812-817.
- `ODOO_HELPDESK_DATABASE` defaults to `""` (JSON-2 infers the database), not `None`.
- No secrets in code.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the block below the `ODOO_VERIFY_SSL` line — *why*: keeps every Odoo key in one place.
2. `python -c "import parrot.conf"` from the venv — *why*: proves the module still imports.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'ODOO_VERIFY_SSL = config.getboolean("ODOO_VERIFY_SSL", fallback=True)' packages/ai-parrot/src/parrot/conf.py)
# AFTER — insert below `ODOO_VERIFY_SSL = config.getboolean("ODOO_VERIFY_SSL", fallback=True)` (verified: conf.py:817)

# ── Odoo Helpdesk (Softhealer sh_all_in_one_helpdesk, dedicated instance — FEAT-616) ──
# Never merged with the ODOO_* keys above: OdooHelpdeskToolkit reads only these.
ODOO_HELPDESK_URL = config.get("ODOO_HELPDESK_URL", fallback=None)
ODOO_HELPDESK_USER = config.get("ODOO_HELPDESK_USER", fallback=None)
ODOO_HELPDESK_PASSWORD = config.get("ODOO_HELPDESK_PASSWORD", fallback=None)
ODOO_HELPDESK_APIKEY = config.get("ODOO_HELPDESK_APIKEY", fallback=None)
ODOO_HELPDESK_DATABASE = config.get("ODOO_HELPDESK_DATABASE", fallback="")
ODOO_HELPDESK_TIMEOUT = config.getint("ODOO_HELPDESK_TIMEOUT", fallback=30)
ODOO_HELPDESK_VERIFY_SSL = config.getboolean("ODOO_HELPDESK_VERIFY_SSL", fallback=True)
```
**Why**: spec §3 M2 fixes the names and defaults. Nothing to decide.

### FILL IN checklist
- [ ] none — mechanical task

---

## Acceptance Criteria

- [ ] AC2 (spec, conf half): the seven constants import from `parrot.conf`.
- [ ] `ruff check packages/ai-parrot/src/parrot/conf.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -q` — imports `parrot.conf` through `parrot_tools.odoo.toolkit`, so a broken constants block fails collection.

Plus the import check: `PYTHONPATH=packages/ai-parrot/src python -c "from parrot.conf import ODOO_HELPDESK_URL, ODOO_HELPDESK_DATABASE; print('ok')"`
The key-isolation tests (`test_init_*`) are added by TASK-3897.

---

## Test Specification

Covered by TASK-3897's `test_init_*` tests (they monkeypatch these constants).

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug odoo-toolkit-upgrades --feature-id FEAT-616`.
2. **Read the spec** (§3 M2).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run the `grep -c`.
5. **Update status** in `sdd/tasks/index/odoo-toolkit-upgrades.json` → `"in-progress"`, commit only that file.
6. **Implement** the block.
7. **Verify** — import check.
8. **Commit the code** — only `conf.py`.
9. **Close the task** — `scripts/sdd/close_task.sh TASK-3892 odoo-toolkit-upgrades verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
