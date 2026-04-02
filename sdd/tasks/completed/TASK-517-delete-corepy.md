# TASK-517: Delete core.py + Cleanup

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-510, TASK-511, TASK-512, TASK-513, TASK-514, TASK-515, TASK-516
**Assigned-to**: unassigned

---

## Context

Module 8 from the spec. Final cleanup task — delete the orphaned `AgentCoreMemory` in `parrot/memory/core.py` after all its valuable patterns have been ported and verified in TASK-510 through TASK-516.

---

## Scope

- Verify all patterns from `core.py` are ported:
  - BM25 hybrid search → `recall.py` (TASK-511)
  - ValueScorer → `scoring.py` (TASK-510)
  - Cross-domain routing → `routing.py` (TASK-514)
- Grep the entire codebase for any imports of `core.py` or `AgentCoreMemory`
- Delete `parrot/memory/core.py`
- Remove any references from `parrot/memory/__init__.py` (if exported)
- Verify no import errors: `python -c "import parrot.memory"`
- Run full memory test suite to ensure no regressions

**NOT in scope**: Any feature implementation. Only verification and deletion.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/core.py` | DELETE | Orphaned AgentCoreMemory implementation |
| `parrot/memory/__init__.py` | MODIFY | Remove core.py exports if any |

---

## Implementation Notes

### Verification Checklist
```bash
# 1. Check for any imports of core.py or AgentCoreMemory
grep -r "AgentCoreMemory" --include="*.py" .
grep -r "from parrot.memory.core" --include="*.py" .
grep -r "import parrot.memory.core" --include="*.py" .

# 2. Check __init__.py for exports
grep "core" parrot/memory/__init__.py

# 3. Delete
rm parrot/memory/core.py

# 4. Verify imports
python -c "import parrot.memory; print('OK')"

# 5. Run tests
pytest tests/unit/memory/ -v
```

### Key Constraints
- Do NOT delete if any live imports exist — report them and stop
- Do NOT delete any other files
- This task is a gate — only proceed after ALL prior tasks in this feature are done

### References in Codebase
- `parrot/memory/core.py` — file to delete
- `parrot/memory/__init__.py` — may need cleanup

---

## Acceptance Criteria

- [ ] No imports of `AgentCoreMemory` or `parrot.memory.core` exist in codebase
- [ ] `parrot/memory/core.py` is deleted
- [ ] `parrot/memory/__init__.py` has no stale references to core
- [ ] `python -c "import parrot.memory"` succeeds
- [ ] All memory tests pass: `pytest tests/unit/memory/ -v`
- [ ] No regressions in any other test suite

---

## Test Specification

No new tests needed — this task only verifies existing tests pass after deletion.

```bash
# Full verification
pytest tests/unit/memory/ -v
python -c "from parrot.memory import EpisodicMemoryStore, UnifiedMemoryManager; print('All imports OK')"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify ALL TASK-510 through TASK-516 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Run verification checklist** from Implementation Notes
5. **Delete core.py** only if no live imports found
6. **Run full test suite**
7. **Move this file** to `tasks/completed/TASK-517-delete-corepy.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: Verified zero live imports. core.py deleted. All 158 memory tests pass. parrot.memory imports work.

**Deviations from spec**: none
