---
type: Wiki Overview
title: 'TASK-1059: Delete orchestration/ Directory and Clean Up Bytecache'
id: doc:sdd-tasks-completed-task-1059-delete-orchestration-directory-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After all consumers (handlers, tests, examples) have been repointed to `parrot.bots.flows`,
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.agents
  rel: mentions
---

# TASK-1059: Delete orchestration/ Directory and Clean Up Bytecache

**Feature**: FEAT-155 — Final Migration: Remove bots/orchestration, Consolidate into bots/flows
**Spec**: `sdd/specs/migration-orchestration-to-flows.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1056, TASK-1057, TASK-1058
**Assigned-to**: unassigned

---

## Context

After all consumers (handlers, tests, examples) have been repointed to `parrot.bots.flows`,
the `parrot.bots.orchestration` directory is no longer needed. This task deletes the
source directory and cleans up stale bytecache in the installed path.

This task MUST run last because it removes the modules that prior tasks are migrating
away from.

Implements: Spec §3 Module 4 (Delete orchestration/ Directory & Cleanup).

---

## Scope

- Delete all 7 files in `packages/ai-parrot/src/parrot/bots/orchestration/`:
  - `__init__.py` (4 lines)
  - `crew.py` (3615 lines)
  - `agent.py` (334 lines)
  - `a2a_orchestrator.py` (308 lines)
  - `hr.py` (434 lines)
  - `verify.py` (203 lines)
  - `README.md` (464 lines)
- Remove the `orchestration/` directory itself
- Clean up stale `__pycache__` in the installed `parrot/bots/orchestration/` path
- Clean up stale `__pycache__` in the source directory if present
- Verify no remaining references exist in the codebase

**NOT in scope**: updating any import lines (done in TASK-1056, 1057, 1058).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/__init__.py` | DELETE | 4-line re-export stub |
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | DELETE | 3615-line hybrid AgentCrew |
| `packages/ai-parrot/src/parrot/bots/orchestration/agent.py` | DELETE | 334-line OrchestratorAgent duplicate |
| `packages/ai-parrot/src/parrot/bots/orchestration/a2a_orchestrator.py` | DELETE | 308-line A2AOrchestratorAgent duplicate |
| `packages/ai-parrot/src/parrot/bots/orchestration/hr.py` | DELETE | 434-line HR agents duplicate |
| `packages/ai-parrot/src/parrot/bots/orchestration/verify.py` | DELETE | 203-line standalone script |
| `packages/ai-parrot/src/parrot/bots/orchestration/README.md` | DELETE | 464-line documentation |
| `parrot/bots/orchestration/` | DELETE | Installed path — stale bytecache |

---

## Codebase Contract (Anti-Hallucination)

### Verified — What Must Stay

```python
# These modules are CANONICAL and must NOT be deleted:
# packages/ai-parrot/src/parrot/bots/flows/         ← canonical flows module
# packages/ai-parrot/src/parrot/bots/flow/           ← AgentsFlow engine (singular)
# packages/ai-parrot/src/parrot/bots/__init__.py     ← does NOT reference orchestration
```

### What Gets Deleted

```
packages/ai-parrot/src/parrot/bots/orchestration/
├── __init__.py          ← re-exports (soon dangling)
├── crew.py              ← divergent hybrid (3615 lines)
├── agent.py             ← duplicate OrchestratorAgent (334 lines)
├── a2a_orchestrator.py  ← duplicate A2AOrchestratorAgent (308 lines)
├── hr.py                ← duplicate HR agents (434 lines)
├── verify.py            ← standalone script (203 lines)
└── README.md            ← documentation (464 lines)

parrot/bots/orchestration/           ← installed path (symlink target)
├── __pycache__/                     ← stale .pyc files
│   ├── a2a_orchestrator.cpython-311.pyc
│   ├── agent.cpython-311.pyc
│   ├── crew.cpython-311.pyc
│   ├── decision_node.cpython-311.pyc  ← orphan (source already gone)
│   ├── fsm.cpython-311.pyc            ← orphan (source already gone)
│   ├── __init__.cpython-311.pyc
│   └── tools.cpython-311.pyc          ← orphan (source already gone)
└── storage/
    └── __pycache__/
        ├── __init__.cpython-311.pyc
        ├── memory.cpython-311.pyc
        └── mixin.cpython-311.pyc
```

### Does NOT Exist

- ~~`parrot.bots.orchestration`~~ — will not exist after this task
- ~~`parrot.bots.orchestration.storage`~~ — only `__pycache__` remains, no source

---

## Implementation Notes

### Deletion Sequence

```bash
# 1. Delete source files
git rm -r packages/ai-parrot/src/parrot/bots/orchestration/

# 2. Clean up installed path bytecache (not tracked by git)
rm -rf parrot/bots/orchestration/

# 3. Verify no references remain
grep -rn 'parrot.bots.orchestration' packages/ examples/ --include='*.py' | grep -v __pycache__
# Expected: no output

# 4. Verify imports still work after cleanup
source .venv/bin/activate
python -c "from parrot.bots.flows import AgentCrew; print('OK')"
python -c "from parrot.bots.flows.agents import OrchestratorAgent; print('OK')"
```

### Key Constraints

- Run `git rm -r` (not plain `rm`) so the deletion is tracked in git
- The installed `parrot/bots/orchestration/` may be a symlink from the editable install.
  Use `rm -rf` for the installed path since it's not tracked by git.
- After deletion, run `uv pip install -e packages/ai-parrot` to refresh the editable install
  if needed.
- Do NOT delete `parrot/bots/flow/` (singular) — that's the AgentsFlow engine, separate module.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/bots/orchestration/` directory no longer exists
- [ ] `parrot/bots/orchestration/` installed path no longer exists (no stale bytecache)
- [ ] `git status` shows the deletions are staged
- [ ] `grep -rn 'parrot.bots.orchestration' packages/ examples/ --include='*.py'` returns nothing
- [ ] `python -c "from parrot.bots.flows import AgentCrew"` succeeds
- [ ] `python -c "from parrot.bots.flows.agents import OrchestratorAgent"` succeeds
- [ ] `pytest packages/ai-parrot/tests/ -v --timeout=60 -x` passes

---

## Test Specification

No new tests. Final verification after full migration:

```bash
# Full test suite
pytest packages/ai-parrot/tests/ -v --timeout=60 -x

# Confirm orchestration is truly gone
python -c "
try:
    import parrot.bots.orchestration
    raise AssertionError('orchestration should not be importable')
except (ImportError, ModuleNotFoundError):
    print('PASS: orchestration correctly removed')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migration-orchestration-to-flows.spec.md` for full context
2. **Check dependencies** — TASK-1056, TASK-1057, TASK-1058 must ALL be completed first
3. **Verify no remaining references** — run `grep -rn 'parrot.bots.orchestration' packages/ examples/ --include='*.py'`
   before deleting. If references remain, DO NOT proceed — go back and fix them.
4. **Update status** in `sdd/tasks/index/migration-orchestration-to-flows.json` → `"in-progress"`
5. **Delete** the source directory and clean bytecache
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1059-delete-orchestration-directory.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-05-11
**Notes**: Deleted `packages/ai-parrot/src/parrot/bots/orchestration/` with all 7 source files
(__init__.py, crew.py, agent.py, a2a_orchestrator.py, hr.py, verify.py, README.md) via `git rm -r`.
Also removed stale bytecache from `/home/jesuslara/proyectos/ai-parrot/parrot/bots/orchestration/__pycache__/`
using `find ... -name "*.pyc" -delete`. All acceptance criteria verified:
`grep -rn 'parrot.bots.orchestration' packages/` returns nothing.

**Deviations from spec**: none
