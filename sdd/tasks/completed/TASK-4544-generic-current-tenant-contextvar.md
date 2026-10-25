# TASK-4544: Generic current_tenant ContextVar reused by skills tenancy

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / Goal G3. ai-parrot must have exactly one tenant ContextVar. Today the only one is the skills-scoped `_skill_tenant` (`skills/tenancy.py:77`). This task adds the generic `current_tenant` and makes `skills/tenancy.py` reuse the same object, so FEAT-707 helpers keep working unchanged.

---

## Scope

- Add `current_tenant: ContextVar[Optional[str]]` (name `parrot_current_tenant`, default `None`) to `observability/context.py` and document it in the module docstring.
- Export it from `parrot.observability.context` (module-level name).
- In `skills/tenancy.py`, replace the `_skill_tenant` ContextVar construction with `_skill_tenant = current_tenant`, imported from `parrot.observability.context`.
- Keep `current_skill_tenant`, `bind_skill_tenant`, `reset_skill_tenant` names and behavior unchanged.
- Write unit tests.

**NOT in scope**: binding the tenant in `BaseBot` (TASK-4545); event fields (TASK-4546).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/context.py` | MODIFY | Add current_tenant ContextVar |
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | MODIFY | Alias _skill_tenant to current_tenant |
| `packages/ai-parrot/tests/unit/observability/test_tenant_contextvar.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from contextvars import ContextVar  # verified: packages/ai-parrot/src/parrot/observability/context.py:48
from parrot.skills.tenancy import current_skill_tenant, bind_skill_tenant, reset_skill_tenant  # verified: skills/tenancy.py:81-94
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/context.py
current_session_id: ContextVar[Optional[str]] = ContextVar("parrot_current_session_id", default=None)   # :67
current_memory_key_id: ContextVar[Optional[str]] = ContextVar("parrot_current_memory_key_id", default=None)  # :73
# packages/ai-parrot/src/parrot/skills/tenancy.py
_skill_tenant: ContextVar[Optional[str]] = ContextVar("parrot_skill_tenant", default=None)  # :77
def current_skill_tenant() -> Optional[str]                    # :81
def bind_skill_tenant(tenant: Optional[str]) -> Token          # :86
def reset_skill_tenant(token: Token) -> None                   # :91
```

### Does NOT Exist
- ~~`parrot.observability.context.current_tenant`~~ — created by this task
- ~~`current_program_slug`~~ — must never be created (spec non-goal)
- ~~`parrot.core.tenancy`~~ — no such module

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/skills/tenancy.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_tenant_contextvar.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#bind_skill_tenant",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#current_skill_tenant"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Add `current_tenant` right after `current_memory_key_id` in `context.py` — *why*: all request-scoped observability ContextVars live together there.
2. Replace the `_skill_tenant` construction in `tenancy.py` with an alias — *why*: one ContextVar object means a skill bind is visible as the generic tenant, and vice versa.
3. Write the tests.

### `packages/ai-parrot/src/parrot/observability/context.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'current_memory_key_id: ContextVar' packages/ai-parrot/src/parrot/observability/context.py)
# AFTER — insert below `current_memory_key_id: ContextVar[...] = ContextVar("parrot_current_memory_key_id", default=None)` (verified: :73)
#: FEAT-710 — server-resolved tenant of the current invocation (FEAT-707 resolution), or None.
#: The single tenant ContextVar of the codebase; ``parrot.skills.tenancy`` aliases it.
current_tenant: ContextVar[Optional[str]] = ContextVar("parrot_current_tenant", default=None)
```
**Why**: same declaration style as its neighbours. Also add a `current_tenant` bullet to the module docstring list (`:12-36`).

### `packages/ai-parrot/src/parrot/skills/tenancy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_skill_tenant: ContextVar' packages/ai-parrot/src/parrot/skills/tenancy.py)
# REPLACE line 77 `_skill_tenant: ContextVar[Optional[str]] = ContextVar("parrot_skill_tenant", default=None)` with:
from parrot.observability.context import current_tenant  # noqa: E402  FEAT-710: one tenant ContextVar

_skill_tenant = current_tenant
```
**Why**: aliasing keeps every `_skill_tenant.get/set/reset` call site working. Move the import to the top-level import block if it creates no cycle; `# FILL IN: confirm `python -c "import parrot.skills.tenancy"` has no circular import` — bounded by AC-3.

### `packages/ai-parrot/tests/unit/observability/test_tenant_contextvar.py` (CREATE)
```python
"""FEAT-710 TASK-4544 — generic current_tenant ContextVar."""
from parrot.observability.context import current_tenant
from parrot.skills.tenancy import bind_skill_tenant, current_skill_tenant, reset_skill_tenant


def test_default_is_none() -> None:
    assert current_tenant.get() is None


def test_skill_bind_visible_as_current_tenant() -> None:
    tok = bind_skill_tenant("acme")
    try:
        assert current_tenant.get() == "acme"
        assert current_skill_tenant() == "acme"
    finally:
        reset_skill_tenant(tok)
    assert current_tenant.get() is None


def test_generic_bind_visible_to_skills() -> None:
    # FILL IN: set current_tenant, assert current_skill_tenant() sees it, reset — bounded by AC-2
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `tenancy.py` import placement without circular import — AC-3
- [ ] `test_generic_bind_visible_to_skills` body — AC-2

---

## Acceptance Criteria

- [ ] `current_tenant` exists in `parrot.observability.context` and is the only tenant ContextVar (`grep -rn 'ContextVar("parrot_.*tenant' packages/` returns one hit).
- [ ] `_skill_tenant is current_tenant`; FEAT-707 helpers behave as before.
- [ ] `import parrot.skills.tenancy` and `import parrot.observability.context` work (no cycle).
- [ ] `ruff check` passes on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_tenant_contextvar.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_context.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4544 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note



**Completed by**: sdd-worker orchestrator (coder: codex/gpt-5.6-terra)
**Date**: 2026-10-22
**Notes**: Delivered, merged and merge-tier validated green (no review fixes needed).

**Deviations from spec**: none
