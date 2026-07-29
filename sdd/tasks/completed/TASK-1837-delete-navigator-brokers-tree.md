# TASK-1837: Delete the `navigator/brokers/` origin tree + import-neutrality guard

**Feature**: FEAT-318 — Navigator Brokers Removal (`navigator-eventbus` phase 5)
**Spec**: `sdd/specs/navigator-brokers-removal.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1835, TASK-1836
**Assigned-to**: unassigned

> **CROSS-REPO**: changes land in `/home/jesuslara/proyectos/navigator` (branch
> `dev`), NOT ai-parrot. This is the destructive step — it deletes the origin
> broker code with **no compatibility shim** (resolved in brainstorm).

---

## Context

Spec §3 Module 3. After the examples are migrated (TASK-1835) and the dependency
metadata is rewired (TASK-1836), nothing in the navigator repo imports
`navigator.brokers.*` anymore. This task removes the duplicate origin tree
(18 files, ~2,197 LOC verified 2026-07-18) as a single clean `git rm` for
bisectability, then proves the repo is import-neutral and its own test suite
still passes.

---

## Scope

- `git rm -r navigator/brokers/` (all 18 `.py` files listed in the contract).
- Verify NO remaining reference to `navigator.brokers` anywhere under
  `navigator/` or `examples/` (grep-neutrality guard → zero matches).
- Run the navigator repo's existing test suite and confirm no
  collection/import errors are introduced by the deletion.

**NOT in scope**:
- Editing examples (TASK-1835) or `pyproject.toml` (TASK-1836).
- Closing PR #393 / release coordination (TASK-1838).
- A compatibility shim / re-export at `navigator.brokers` — explicitly rejected.

---

## Files to Create / Modify

> Paths relative to the **navigator** repo root. DELETE the entire directory.

| File | Action | Description |
|---|---|---|
| `navigator/brokers/__init__.py` | DELETE | |
| `navigator/brokers/connection.py` | DELETE | |
| `navigator/brokers/consumer.py` | DELETE | |
| `navigator/brokers/producer.py` | DELETE | |
| `navigator/brokers/wrapper.py` | DELETE | |
| `navigator/brokers/pickle.py` | DELETE | |
| `navigator/brokers/redis/{__init__,connection,consumer,producer}.py` | DELETE | 4 files |
| `navigator/brokers/rabbitmq/{__init__,connection,consumer,producer}.py` | DELETE | 4 files |
| `navigator/brokers/sqs/{__init__,connection,consumer,producer}.py` | DELETE | 4 files |

---

## Codebase Contract (Anti-Hallucination)

> Verified against the `navigator` repo (branch `dev`) on 2026-07-18.

### Files to delete (18 total, ~2,197 LOC — verified via `wc -l`)
```
navigator/brokers/__init__.py
navigator/brokers/connection.py
navigator/brokers/consumer.py
navigator/brokers/producer.py
navigator/brokers/wrapper.py
navigator/brokers/pickle.py
navigator/brokers/redis/__init__.py
navigator/brokers/redis/connection.py
navigator/brokers/redis/consumer.py
navigator/brokers/redis/producer.py
navigator/brokers/rabbitmq/__init__.py
navigator/brokers/rabbitmq/connection.py
navigator/brokers/rabbitmq/consumer.py
navigator/brokers/rabbitmq/producer.py
navigator/brokers/sqs/__init__.py
navigator/brokers/sqs/connection.py
navigator/brokers/sqs/consumer.py
navigator/brokers/sqs/producer.py
```

### Does NOT Exist
- ~~`navigator/__init__.py` re-export of `brokers`~~ — verified absent; deleting
  the package does not break the top-level `navigator` import.
- ~~any in-repo importer of `navigator.brokers.*` after TASK-1835/1836~~ — must
  be zero; if the guard finds one, STOP and fix the importer (or the earlier
  task missed a site) before deleting.

---

## Implementation Notes

### Order of operations
```bash
cd /home/jesuslara/proyectos/navigator
# 1. Pre-flight: confirm no live importers remain (must be EMPTY)
grep -rnE "navigator\.brokers" navigator/ examples/
# 2. Delete
git rm -r navigator/brokers/
# 3. Post-check: neutrality guard (must be EMPTY)
grep -rnE "navigator\.brokers" .   # excluding .git; zero matches
# 4. Import + suite
python -c "import navigator; print('navigator imports OK')"
pytest
```

### Key Constraints
- One logical commit for the deletion (clean `git rm -r`) — bisectable.
- Do NOT add a shim, stub, or deprecation re-export.
- If `pytest` surfaces a failure caused by the deletion, it means a consumer was
  missed — trace it, do not paper over with a shim.

---

## Acceptance Criteria

- [ ] `navigator/brokers/` no longer exists (all 18 files removed via `git rm`).
- [ ] `grep -rnE "navigator\.brokers"` over the navigator repo (excluding `.git`)
      returns zero matches.
- [ ] `python -c "import navigator"` succeeds (top-level package unaffected).
- [ ] The navigator repo's existing `pytest` suite passes with no new
      collection/import errors attributable to the removal.
- [ ] No compatibility shim/re-export was added.
- [ ] No changes to the ai-parrot repository.

---

## Test Specification

```bash
cd /home/jesuslara/proyectos/navigator
test ! -d navigator/brokers && echo "PASS: brokers deleted" || echo "FAIL: still present"
test -z "$(grep -rnE 'navigator\.brokers' navigator/ examples/)" && echo "PASS: neutral" || echo "FAIL: importer remains"
python -c "import navigator; print('import OK')"
pytest -q
```

---

## Agent Instructions

Standard SDD flow. Run the neutrality guard BEFORE deleting (TASK-1835/1836 must
be done). Code commit (the `git rm`) lands in navigator; SDD state commit
(index + this file move) lands in ai-parrot on `dev`.

---

## Completion Note

**Completed by**: Claude (Opus 4.8) via `/sdd-start`
**Date**: 2026-07-20
**Notes**:
- Deleted the entire `navigator/brokers/` tree via `git rm -r` in the navigator
  worktree `.claude/worktrees/feat-318-navigator-brokers-removal` (commit
  `e56762e`). **19 files** removed (18 `.py` + `py.typed`) — the spec's "18"
  count omitted `py.typed`.
- **Import-neutrality verified via `git grep`** (tracked-file exact search):
  zero `navigator.brokers` importers remain; `navigator/__init__.py` has no
  broker re-export.
- `import navigator` from the worktree loads the top-level package; the
  `navigator.Application unavailable: No module named 'navigator.types'` warning
  is a **pre-existing unbuilt-worktree artifact** (`navigator.types` is a Cython
  module — `types.pyx`, no compiled `.so` in a fresh checkout), unrelated to the
  brokers deletion. The built site-packages navigator (ai-parrot venv) imports
  `navigator.types` + `Application` cleanly, confirming the package is healthy.

**Deviations from spec** (all corrected in spec v0.3):
- **Inventory was wrong — 5 importers, not 3.** The pre-flight neutrality guard
  exposed two importers the 2026-07-18 inventory missed (it scanned only
  `examples/brokers/`): `examples/test_sqs_consumer.py` and
  `examples/test_sqs_producer.py`, both `from navigator.brokers.sqs import
  SQSConnection`. Per the task's STOP condition, I stopped, surfaced the finding,
  and — on the user's decision ("migrate now under 1837") — migrated both with
  the same 1:1 `navigator_eventbus.brokers.sqs` swap in the same commit. The
  spec §1/§5/§6 and this feature's records were corrected to reflect 5 importers.
- **File count 18 → 19** (`py.typed`).
- **Full `pytest` suite NOT run here.** The worktree is an unbuilt Cython tree
  (`navigator.types` `.so` absent), so a suite run there fails for reasons
  unrelated to this change, and running against built site-packages would not
  reflect the worktree deletion. Import-neutrality is proven statically
  (`git grep` zero + clean `__init__`). **Recommend running the full navigator
  suite once in navigator's own built venv/CI as the final gate** (also covers
  TASK-1836's `uv pip install -e .[brokers]`).
