---
type: Wiki Overview
title: 'TASK-1701: Add ZAMMAD_* environment variable declarations to parrot.conf'
id: doc:sdd-tasks-completed-task-1701-zammad-conf-vars-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: All Zammad configuration values must be declared in `parrot/conf.py` before
  the
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-1701: Add ZAMMAD_* environment variable declarations to parrot.conf

**Feature**: FEAT-218 — Zammad Interface & Toolkit
**Spec**: `sdd/specs/zammad-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

All Zammad configuration values must be declared in `parrot/conf.py` before the
interface or toolkit can use them. This is the foundation task — every other task
depends on these env vars being importable.

Implements: Spec §3 Module 1 (Configuration).

---

## Scope

- Add 7 `ZAMMAD_*` environment variable declarations to `packages/ai-parrot/src/parrot/conf.py`,
  following the `ODOO_*` pattern at lines 824–829.

**Variables to add:**
```python
ZAMMAD_INSTANCE = config.get("ZAMMAD_INSTANCE", fallback=None)
ZAMMAD_TOKEN = config.get("ZAMMAD_TOKEN", fallback=None)
ZAMMAD_DEFAULT_CUSTOMER = config.get("ZAMMAD_DEFAULT_CUSTOMER", fallback=None)
ZAMMAD_DEFAULT_GROUP = config.get("ZAMMAD_DEFAULT_GROUP", fallback=None)
ZAMMAD_DEFAULT_CATALOG = config.get("ZAMMAD_DEFAULT_CATALOG", fallback=None)
ZAMMAD_ORGANIZATION = config.get("ZAMMAD_ORGANIZATION", fallback=None)
ZAMMAD_DEFAULT_ROLE = config.get("ZAMMAD_DEFAULT_ROLE", fallback="Customer")
```

**NOT in scope**: ZammadInterface, ZammadToolkit, tests (no logic to test).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Append ZAMMAD_* variables after the ODOO block |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/conf.py uses navconfig.config at the top
from navconfig import config  # verified: used throughout conf.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py — ODOO pattern (lines 824-829)
ODOO_URL = config.get("ODOO_URL", fallback=None)          # line 824
ODOO_DATABASE = config.get("ODOO_DATABASE", fallback=None) # line 825
ODOO_USERNAME = config.get("ODOO_USERNAME", fallback=None)  # line 826
ODOO_PASSWORD = config.get("ODOO_PASSWORD", fallback=None)  # line 827
ODOO_TIMEOUT = config.getint("ODOO_TIMEOUT", fallback=30)   # line 828
ODOO_VERIFY_SSL = config.getboolean("ODOO_VERIFY_SSL", fallback=True) # line 829
```

### Does NOT Exist
- ~~`ZAMMAD_INSTANCE` in `parrot/conf.py`~~ — does not exist yet; must be added
- ~~`config.get_str()`~~ — not a real method; use `config.get()`

---

## Implementation Notes

### Pattern to Follow
Append the new block directly after the ODOO block (after line 829). Use a
comment header `# Zammad` for visual grouping, matching the style used
elsewhere in `conf.py`.

### Key Constraints
- Use `config.get()` with `fallback=None` for optional string values
- Use `config.get()` with `fallback="Customer"` for `ZAMMAD_DEFAULT_ROLE`
- Do NOT use `config.getint()` or `config.getboolean()` — all Zammad vars are strings

---

## Acceptance Criteria

- [ ] 7 ZAMMAD_* variables declared in `parrot/conf.py`
- [ ] Variables are importable: `from parrot.conf import ZAMMAD_INSTANCE, ZAMMAD_TOKEN`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/conf.py`
- [ ] Existing ODOO_* declarations unchanged

---

## Test Specification

No unit tests required — this task adds only configuration declarations with no logic.
Verification is by import:
```python
from parrot.conf import (
    ZAMMAD_INSTANCE, ZAMMAD_TOKEN, ZAMMAD_DEFAULT_CUSTOMER,
    ZAMMAD_DEFAULT_GROUP, ZAMMAD_DEFAULT_CATALOG,
    ZAMMAD_ORGANIZATION, ZAMMAD_DEFAULT_ROLE,
)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/zammad-interface-toolkit.spec.md` for full context
2. **Read** `packages/ai-parrot/src/parrot/conf.py` around lines 824-829 to see the ODOO pattern
3. **Append** the ZAMMAD_* block after line 829
4. **Verify** the import works
5. **Commit** and update status

---

## Completion Note

Appended the 7 `ZAMMAD_*` declarations directly after the `ODOO_*` block
(line 829) in `packages/ai-parrot/src/parrot/conf.py`, following the exact
pattern requested (all via `config.get()`, no `getint`/`getboolean`).
Verified via `PYTHONPATH` import that all 7 names are importable from
`parrot.conf`. Pre-existing `ruff` E402 finding at conf.py:450 is unrelated
to this change (import-not-at-top for `GoogleModel`, predates this task).
