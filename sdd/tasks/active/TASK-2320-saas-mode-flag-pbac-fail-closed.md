# TASK-2320: `PARROT_SAAS_MODE` flag + `setup_pbac` fail-closed

**Feature**: FEAT-446 — SaaS Auth Hardening (S0 of Parrot Research Cloud)
**Spec**: `sdd/specs/saas-auth-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / Goal G5. Everything else in FEAT-446 gates its
SaaS-only behavior on a single config flag, and the PBAC bootstrap must stop
failing open when that flag is set. This task creates the flag and the
fail-closed branch; it is a prerequisite for TASK-2322/2324 and independent
of TASK-2321.

---

## Scope

- Add `PARROT_SAAS_MODE` (boolean, env-driven, default `false`) to
  `packages/ai-parrot/src/parrot/conf.py`, following the existing
  `config.get(..., fallback=...)` style of its neighbors.
- Modify `setup_pbac()` in `packages/ai-parrot/src/parrot/auth/pbac.py`:
  when `PARROT_SAAS_MODE` is true, every path that today returns
  `(None, None, None)` (lines ~94, ~104, ~140) must instead raise
  `RuntimeError` with a message naming the failure cause. Behavior with the
  flag off is byte-for-byte unchanged.
- Update the fail-open docstring (`pbac.py:57-59`) to document both modes.
- Write unit tests for flag parsing and both `setup_pbac` behaviors.

**NOT in scope**: touching `_check_pbac_agent_access` in `handlers/agent.py`
(stays fail-open outside SaaS mode; TASK-2325 only probes it), the tenant
resolver (TASK-2322), any handler or exclude_list change (TASK-2323/2324).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | add `PARROT_SAAS_MODE` |
| `packages/ai-parrot/src/parrot/auth/pbac.py` | MODIFY | fail-closed branch |
| `packages/ai-parrot/tests/unit/auth/test_pbac_fail_closed.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import PARROT_SCHEMA  # pattern neighbor: conf.py:103
# navconfig-style access used throughout conf.py:
#   X = config.get('X', fallback='...')
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/pbac.py
def setup_pbac(app, policy_dir=..., ...):
    # docstring documents fail-open at lines 57-59
    # returns (None, None, None) at lines 94 (ImportError), 104 (missing/empty
    # policy dir), 140 (broad Exception during init)
    # caller: app.py:339-343 — pdp, evaluator, guardian = setup_pbac(self.app, policy_dir=...)

# packages/ai-parrot/src/parrot/conf.py
PARROT_SCHEMA = config.get('PARROT_SCHEMA', fallback='navigator')          # line 103
CREW_RESULT_STORAGE = config.get('CREW_RESULT_STORAGE', fallback='documentdb')  # line 309
```

### Does NOT Exist
- ~~`PARROT_SAAS_MODE`~~ — this task creates it; nothing references it yet.
- ~~`parrot.conf.SAAS_MODE` / `parrot.settings`~~ — wrong names/modules.
- ~~a fail-closed kwarg on `setup_pbac`~~ — gate on the conf flag, not a parameter.

---

## Implementation Notes

### Pattern to Follow
```python
# conf.py — boolean neighbors use navconfig's boolean coercion; follow the
# closest existing boolean flag in the file (grep "getboolean\|fallback=False"
# and mirror it exactly).
PARROT_SAAS_MODE = config.getboolean('PARROT_SAAS_MODE', fallback=False)
```

### Key Constraints
- Import the flag lazily inside `setup_pbac` OR at module top following
  pbac.py's existing conf imports — do not create import cycles
  (`parrot.conf` must not import `parrot.auth`).
- The `RuntimeError` message must include the original failure reason so a
  misconfigured SaaS deployment fails loudly and debuggably at startup.
- Google-style docstrings, strict typing.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/pbac.py` — the three return sites
- `app.py:339-343` — the only call site (verify with grep before changing the signature; do NOT change the signature)

---

## Acceptance Criteria

- [ ] `PARROT_SAAS_MODE` defaults to `False`; env `PARROT_SAAS_MODE=true` flips it
- [ ] Flag true + any of the three failure paths → `RuntimeError` (test with a
      missing policy dir and a monkeypatched ImportError)
- [ ] Flag false → `(None, None, None)` exactly as today (regression test)
- [ ] `pytest packages/ai-parrot/tests/unit/auth/test_pbac_fail_closed.py -v` green
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_pbac_fail_closed.py
import pytest

class TestSaasModeFlag:
    def test_default_false(self): ...
    def test_env_true(self, monkeypatch): ...

class TestSetupPbacFailClosed:
    def test_missing_policy_dir_raises_in_saas_mode(self, monkeypatch, tmp_path): ...
    def test_missing_policy_dir_returns_nones_legacy(self, tmp_path): ...
    def test_import_error_raises_in_saas_mode(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — line numbers drift; re-grep the three
   `return None, None, None` sites before editing
4. **Update status** in `sdd/tasks/index/saas-auth-hardening.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
