# TASK-5156: Promote `check_bwrap_sandbox` to public API in doctor.py

**Feature**: FEAT-799 — `parrot claude install` Welcome Wizard
**Spec**: `sdd/specs/claude-install-welcome-wizard.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §7 "Patterns to Follow" (and §8 Q4, resolved here per the spec's
recommendation): the welcome wizard (TASK-5157) must reuse the bwrap
nested-userns diagnostic, but it is private (`_check_bwrap_sandbox`).
Promote it to a public name and keep the private alias so existing callers
and tests (`tests/self_/test_doctor_sdd.py` monkeypatches `_check_bwrap_sandbox`)
keep working.

---

## Scope

- Rename `def _check_bwrap_sandbox()` → `def check_bwrap_sandbox()` in `doctor.py`.
- Add the module-level alias `_check_bwrap_sandbox = check_bwrap_sandbox` right after it.
- Keep `_check_sdd()` calling `_check_bwrap_sandbox()` (the alias) — **because**
  `test_doctor_sdd.py:53` monkeypatches `doctor._check_bwrap_sandbox`; calling the
  public name there would bypass that patch and run real bwrap in tests.
- Add one test asserting the alias and public name are the same object.

**NOT in scope**: any change to the diagnostic logic itself; welcome.py.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | Rename + alias |
| `packages/ai-parrot/tests/self_/test_doctor_bwrap_public.py` | CREATE | Alias test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.self_ import doctor  # verified: packages/ai-parrot/src/parrot/self_/doctor.py
from parrot.self_.doctor import DoctorCheck  # verified: doctor.py:40
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/self_/doctor.py:221
def _check_bwrap_sandbox() -> list[DoctorCheck]:   # returns [] when sys.platform != "linux"
# doctor.py:289-292
def _check_sdd(root: Path) -> list[DoctorCheck]:
    ...
    checks.extend(_check_bwrap_sandbox())           # line 292 — leave as is
```

### Does NOT Exist
- ~~`parrot.self_.doctor.check_bwrap_sandbox`~~ — created by this task
- ~~`parrot.self_.bwrap`~~ — no separate bwrap module; do not create one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/self_/doctor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/self_/test_doctor_bwrap_public.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_bwrap_sandbox",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_sdd"
  ]
}
```

---

## Implementation Notes

The docstring stays; only the name changes. Two-line diff plus alias.

---

## Implementation Blueprint

### Steps (in order)
1. Rename the def at doctor.py:221 — *why*: cross-package import from `claude_code/welcome.py` must not reach into a private name.
2. Insert the alias directly after the function body (before `def _check_sdd`) — *why*: keeps the monkeypatch seam used by existing tests.
3. Write the test file and run both test files.

### `packages/ai-parrot/src/parrot/self_/doctor.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def _check_bwrap_sandbox() -> list\[DoctorCheck\]:' doctor.py)
# REPLACE line 221
def check_bwrap_sandbox() -> list[DoctorCheck]:

# occurrences: 1 (verified: grep -c '^def _check_sdd(root: Path)' doctor.py)
# BEFORE — insert above `def _check_sdd(root: Path) -> list[DoctorCheck]:` (verified: doctor.py:289), keeping two blank lines
#: Backward-compatible private alias — `_check_sdd` and existing tests patch this name.
_check_bwrap_sandbox = check_bwrap_sandbox
```
**Why**: public name for reuse; alias preserves the test seam at `test_doctor_sdd.py:53`.

### `packages/ai-parrot/tests/self_/test_doctor_bwrap_public.py` (CREATE)
```python
"""FEAT-799: check_bwrap_sandbox is public and aliased."""

from parrot.self_ import doctor


def test_public_name_is_alias() -> None:
    assert doctor.check_bwrap_sandbox is doctor._check_bwrap_sandbox


def test_non_linux_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    assert doctor.check_bwrap_sandbox() == []
```

### FILL IN checklist
- [ ] none — mechanical task

---

## Acceptance Criteria

- [ ] `from parrot.self_.doctor import check_bwrap_sandbox` works
- [ ] `test_doctor_sdd.py` still passes unchanged
- [ ] `ruff check` clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/self_/test_doctor_bwrap_public.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`

---

## Agent Instructions

Standard SDD flow: work in the FEAT-799 worktree, mark in-progress in
`sdd/tasks/index/claude-install-welcome-wizard.json`, implement, run validation,
commit only listed files, `parrot sdd task close TASK-5156 claude-install-welcome-wizard verified`.

---

## Completion Note

*(Agent fills this in when done)*
