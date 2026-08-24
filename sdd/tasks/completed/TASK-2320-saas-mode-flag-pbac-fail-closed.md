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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Added `PARROT_SAAS_MODE` boolean flag (`config.getboolean`,
fallback `False`) next to the other `ENABLE_*` flags in `conf.py`. In
`pbac.py`, extracted a `_fail_open_or_closed(reason)` helper and routed
all SIX `return None, None, None` fail-open sites through it (the task's
Scope named three by line number as examples but said "every path that
today returns (None, None, None)" — the codebase actually has six such
sites: ImportError, missing/invalid policy dir, policy-load error,
evaluator-load error, PDP construction error, PDP.setup(app) error). When
`PARROT_SAAS_MODE=True`, each raises `RuntimeError` naming the original
failure cause; when `False`, behavior is byte-for-byte unchanged
(`(None, None, None)`). Docstring updated to document both modes.
`setup_pbac`'s call signature at `app.py:343` was not touched (verified
via grep, no fail-closed kwarg added — gated on the conf flag only, per
Key Constraints). Added
`packages/ai-parrot/tests/unit/auth/test_pbac_fail_closed.py` — 6 tests
covering flag default/env-parsing and fail-open vs fail-closed for both
the missing-policy-dir and ImportError paths.
Verified no import cycle: `parrot.conf` has zero `parrot.*` imports.
`ruff check --fix` applied to the new test file only (clean); `pbac.py`
and `conf.py` already carried pre-existing, unrelated ruff findings
(BLE001 broad-except, I001 import-sort, UP037/UP045 typing-style) before
this task's edits — confirmed via before/after diff against `dev` — and
were left untouched per the no-scope-creep rule; my added code reuses
the same pre-existing style conventions as its surrounding function.
`pytest packages/ai-parrot/tests/unit/auth/test_pbac_fail_closed.py -v`
— 6 passed.

Note on running tests in this worktree: the shared venv's editable
install resolves `parrot.*` back to the main repo's `packages/*/src`
(not the worktree). Tests were run with `PYTHONPATH` prepended to the
worktree's own `packages/*/src` directories so the worktree's code was
actually exercised. The compiled Cython extensions
(`parrot/utils/types*.so`, `parrot/utils/parsers/toml*.so`) are
gitignored build artifacts absent from the worktree checkout; they were
copied over from the main repo (binary-compatible, untouched by this
feature) purely to make imports resolve for local test runs — not part
of the commit.

**Deviations from spec**: Fail-closed applied to all six fail-open
return sites in `pbac.py` (only three were named as examples in the
task's Scope/Acceptance-Criteria line numbers); this follows the
Scope's own "every path that today returns (None, None, None)" language
and Goal G5 ("setup_pbac() is fail-closed when PARROT_SAAS_MODE=true"),
not a narrowing to exactly three.
