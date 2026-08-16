# TASK-2220: REPL Worker & Config Cleanup — Remove matplotlib from sanitizer and config

**Feature**: FEAT-423 — Purge Matplotlib & Heavy Renderer Libraries
**Spec**: `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2218
**Assigned-to**: unassigned

---

## Context

With PythonREPLTool cleaned up (TASK-2218), the surrounding infrastructure must
be updated: the sandbox allowlist must stop whitelisting matplotlib/seaborn
imports, the REPL worker docstring must drop matplotlib references, and
`clients/base.py` must remove the `plt_style` parameter.

Implements spec §Module 3.

---

## Scope

- **Remove** `"matplotlib"`, `"matplotlib.pyplot"`, and `"seaborn"` from
  `_GENERAL_IMPORTS` in `python_sanitizer.py` (lines 70–72).
- **Update** `worker.py` docstring (lines 1–21) — remove "matplotlib, connection
  pools" references.
- **Remove** `plt_style` param from `clients/base.py` (lines 106, 1228).

**NOT in scope**:
- PythonREPLTool code changes (TASK-2218)
- System prompt changes (TASK-2219)
- Documentation updates (TASK-2223)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/python_sanitizer.py` | MODIFY | Remove matplotlib/seaborn from `_GENERAL_IMPORTS` |
| `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | MODIFY | Update docstring |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Remove `plt_style` param |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/security/python_sanitizer.py
# No external imports needed for this change — modifying a frozenset literal
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/security/python_sanitizer.py (lines 66-78):
_GENERAL_IMPORTS: FrozenSet[str] = frozenset(
    {
        "pandas",
        "numpy",
        "matplotlib",         # line 70 — REMOVE
        "matplotlib.pyplot",  # line 71 — REMOVE
        "seaborn",            # line 72 — REMOVE
        "altair",             # KEEP
        "plotly",             # KEEP
        "scipy",              # KEEP
        "sklearn",            # KEEP
    }
)

# packages/ai-parrot/src/parrot/clients/base.py:
# line 106: plt_style: str = 'seaborn-v0_8-whitegrid',  — REMOVE
# line 1228: plt_style: str = 'seaborn-v0_8-whitegrid',  — REMOVE

# packages/ai-parrot/src/parrot/tools/repl_worker/worker.py:
# lines 1-21: module docstring referencing matplotlib — UPDATE
```

### Does NOT Exist

- ~~`python_sanitizer.py._BLOCKED_IMPORTS`~~ — the sanitizer uses an allowlist
  pattern (`_GENERAL_IMPORTS`), not a blocklist. The blocklist is on
  `PythonREPLTool.BLOCKED_IMPORTS` (handled in TASK-2218).
- ~~`worker.py.matplotlib_config`~~ — not a real attribute; matplotlib
  config was in the PythonREPLTool instance passed via `_worker_repl_kwargs`.

---

## Implementation Notes

### Key Constraints

- The `_GENERAL_IMPORTS` frozenset after removal should be:
  ```python
  _GENERAL_IMPORTS: FrozenSet[str] = frozenset(
      {
          "pandas",
          "numpy",
          "altair",
          "plotly",
          "scipy",
          "sklearn",
      }
  )
  ```
- In `clients/base.py`, search for all `plt_style` usages — there are exactly
  two (lines 106 and 1228). Remove the parameter and any code that passes it
  to PythonREPLTool.
- In `worker.py`, the docstring mentions "matplotlib, connection pools and
  parent threads do not tolerate it" — rewrite to just "connection pools and
  parent threads do not tolerate it" (the fork-safety concern remains valid
  for connection pools even without matplotlib).

---

## Acceptance Criteria

- [ ] `_GENERAL_IMPORTS` in `python_sanitizer.py` does NOT contain `matplotlib`,
  `matplotlib.pyplot`, or `seaborn`
- [ ] `clients/base.py` has no `plt_style` parameter
- [ ] `worker.py` docstring does not reference matplotlib
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/security/python_sanitizer.py`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/base.py`
- [ ] Existing tests pass: `pytest packages/ai-parrot/tests/ -v -k "sanitizer or worker or client"`

---

## Test Specification

```python
# packages/ai-parrot/tests/security/test_sanitizer_no_matplotlib.py
from parrot.security.python_sanitizer import general_profile


def test_matplotlib_not_in_general_imports():
    """matplotlib must not be in the general profile allowlist."""
    profile = general_profile()
    allowed = profile.allowed_imports
    assert "matplotlib" not in allowed
    assert "matplotlib.pyplot" not in allowed


def test_seaborn_not_in_general_imports():
    """seaborn must not be in the general profile allowlist."""
    profile = general_profile()
    assert "seaborn" not in profile.allowed_imports


def test_altair_still_allowed():
    """altair must remain in the general profile allowlist."""
    profile = general_profile()
    assert "altair" in profile.allowed_imports
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
2. **Check dependencies** — TASK-2218 must be completed first
3. **Verify the Codebase Contract** — confirm line numbers
4. **Update status** in `sdd/tasks/index/purge-matplotlib-renderer-libs.json` → `"in-progress"`
5. **Implement** the three file changes
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
