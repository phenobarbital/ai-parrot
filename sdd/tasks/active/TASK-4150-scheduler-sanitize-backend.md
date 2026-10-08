# TASK-4150: normalize_backend, clean_misfire_grace_time and clean_method_name sanitizers

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (sanitisation half). The `scheduler_type` jobstore alias is replaced by a `backend` value
(`db` | `redis`) that must fail closed: asking for `redis` when no Redis jobstore is attached is an error, never a
silent downgrade to memory (spec AC15 → HTTP 503). Two new validators guard API input: a per-job
`misfire_grace_time` (None = always catch up) and a `method_name` that can never name a private/dunder method
(design research S5, spec AC3).

`normalize_jobstore_alias` stays in this task (the legacy manager still calls it); TASK-4164 removes it.

---

## Scope

- Add `normalize_backend(value, *, redis_available, strict=False) -> str` returning `'db'` or `'redis'`.
- Add `clean_misfire_grace_time(value) -> Optional[int]`.
- Add `clean_method_name(value) -> Optional[str]`.
- Export the three in `__all__` and add tests to `test_sanitize.py`.

**NOT in scope**: removing `normalize_jobstore_alias` (TASK-4164); any manager/base wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` | MODIFY | Add three sanitizers + __all__ entries |
| `packages/ai-parrot-server/tests/scheduler/test_sanitize.py` | MODIFY | Tests for the new sanitizers |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.scheduler.sanitize import SchedulerConfigError, clean_str, clean_int   # verified: sanitize.py:104,116,148
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/sanitize.py
__all__ = ("SchedulerConfigError", "clean_bool", "clean_int", "clean_str", "normalize_jobstore_alias",
           "normalize_schedule_type", "sanitize_redis_settings", "sanitize_schedule_config")   # lines 53-62
NULL_TOKENS: FrozenSet[str]                       # line 68 — "", "none", "null", ... treated as missing
class SchedulerConfigError(ValueError):           # line 104
def clean_str(value, *, default=None, lower=False, ...) -> Optional[str]    # line 116 (read full signature before use)
def clean_int(value, *, default, minimum=None, maximum=None, field=...)    # line 148 (read full signature before use)
def normalize_jobstore_alias(value, *, available=None, default="default", strict=False) -> str   # line 275 — style reference
```

### Does NOT Exist
- ~~`normalize_backend`~~, ~~`clean_misfire_grace_time`~~, ~~`clean_method_name`~~ — created here.
- ~~a `'memory'` or `'default'` backend value~~ — the only backends accepted from callers are `'db'` and `'redis'` (`'code'` is never caller-supplied).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/sanitize.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_sanitize.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#normalize_jobstore_alias",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#clean_str",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#clean_int",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#SchedulerConfigError"
  ]
}
```

---

## Implementation Notes

### Semantics
- `normalize_backend`: `clean_str(value, lower=True)` → missing ⇒ `'db'`; `'redis'` with `redis_available=False` ⇒
  `SchedulerConfigError` when `strict`, else WARNING + `'db'` (only DB-row recovery uses non-strict, and db rows never
  carry a backend — so in practice every caller passes `strict=True`). Anything other than `db`/`redis` ⇒ `SchedulerConfigError`.
- `clean_misfire_grace_time`: `None` / null tokens ⇒ `None`; int ≥ 0 (accept numeric strings) ⇒ int; bool, negative,
  float with fraction, other ⇒ `SchedulerConfigError`.
- `clean_method_name`: `None` / null tokens ⇒ `None`; must satisfy `str.isidentifier()` and not start with `_` ⇒ else
  `SchedulerConfigError("method_name must be a public identifier")`.

### Key Constraints
- Async-first; never block the event loop. `self.logger` / module `logger`, never `print`.
- Google-style docstrings and strict type hints; 120-column lines; `ruff check` (TID251) must pass on every touched file.
- Every timestamp the scheduler writes goes through `utcnow()` (UTC-aware) — never `datetime.now()` (spec AC7).
- Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes (they come from the
> spec's §3 Interface Skeletons). Anchors were re-verified with `grep -c` at task-generation time.

### Steps (in order)
1. Read `clean_str` / `clean_int` full signatures (lines 116-206) — *why*: reuse them instead of re-implementing null-token handling.
2. Add the three functions after `normalize_jobstore_alias` — *why*: keeps the jobstore/backend helpers together for TASK-4164's removal.
3. Add them to `__all__` and write the tests.

### `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def normalize_jobstore_alias(' packages/ai-parrot-server/src/parrot/scheduler/sanitize.py)
# AFTER the end of `def normalize_jobstore_alias(` (verified: sanitize.py:275) — insert:
BACKENDS: Tuple[str, ...] = ("db", "redis")


def normalize_backend(value: Any, *, redis_available: bool, strict: bool = False) -> str:
    """Normalize a caller-supplied ``backend`` to ``'db'`` or ``'redis'``.

    Raises:
        SchedulerConfigError: unknown backend, or ``'redis'`` without an attached Redis jobstore when ``strict``.
    """
    # FILL IN: semantics in Implementation Notes — never silently downgrade a strict 'redis' request.


def clean_misfire_grace_time(value: Any) -> Optional[int]:
    """``None`` (always catch up) or a non-negative number of seconds."""
    # FILL IN: semantics in Implementation Notes.


def clean_method_name(value: Any) -> Optional[str]:
    """A public Python identifier (no leading underscore) or ``None``."""
    # FILL IN: semantics in Implementation Notes (design research S5).
```
```python
# occurrences: 1 (verified: grep -c '"normalize_jobstore_alias",' packages/ai-parrot-server/src/parrot/scheduler/sanitize.py)
# __all__ (verified: sanitize.py:53-62) — add, keeping alphabetical order:
    "clean_method_name",
    "clean_misfire_grace_time",
    "normalize_backend",
```
**Why**: these are the only validators the HTTP/RPC/Python entry points run on the new fields; putting them here keeps
`sanitize.py` the single input-policy module (its docstring's "trim / filter / coerce / fall back or raise" rule).

### FILL IN checklist
- [ ] `normalize_backend` — db default, strict redis check, unknown → error.
- [ ] `clean_misfire_grace_time` — None / non-negative int only.
- [ ] `clean_method_name` — public identifier only.

---

## Acceptance Criteria

- [ ] `normalize_backend('redis', redis_available=False, strict=True)` raises `SchedulerConfigError`; `normalize_backend(None, redis_available=False)` == `'db'`.
- [ ] `clean_misfire_grace_time('600') == 600`; `-1`, `True`, `1.5` raise.
- [ ] `clean_method_name('_private')`, `'__init__'`, `'bad-name'` raise; `'run'` passes; `None` → `None`.
- [ ] Existing `test_sanitize.py` tests still pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_sanitize.py -q`

---

## Test Specification

```python
# additions to packages/ai-parrot-server/tests/scheduler/test_sanitize.py
@pytest.mark.parametrize("value,expected", [(None, "db"), ("", "db"), (" DB ", "db"), ("redis", "redis")])
def test_normalize_backend_values(value, expected): ...        # redis_available=True
def test_normalize_backend_strict_redis_unavailable(): ...     # SchedulerConfigError
def test_normalize_backend_unknown(): ...                       # "memory" → SchedulerConfigError
def test_clean_misfire_grace_time(): ...
def test_clean_method_name(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug scheduler-manager-base --feature-id FEAT-644 --spec sdd/specs/scheduler-manager-base.spec.md --index sdd/tasks/index/scheduler-manager-base.json`)
2. **Read the spec** at `sdd/specs/scheduler-manager-base.spec.md` (§2 Overview, the CRUD matrix, Data Models, and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/scheduler-manager-base.json`
4. **Verify the Codebase Contract** — re-`grep` every anchor and signature before writing code; if one moved, fix
   the contract in this file first; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** — `ruff check` the touched files and run every Validation Command
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(scheduler-manager-base): TASK-4150 — normalize_backend, clean_misfire_grace_time and clean_method_name sanitizers`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4150 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4150 — normalize_backend, clean_misfire_grace_time and clean_method_name sanitizers`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
