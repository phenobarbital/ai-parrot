---
type: Wiki Overview
title: 'TASK-943: Cleanup & Final Regression'
id: doc:sdd-tasks-completed-task-943-cleanup-final-regression-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'After all four execution modes are migrated (TASK-939 through TASK-942),
  crew.py still contains dead local definitions that are no longer used: the local
  `FlowContext` class, local type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`),
  and possibly other dead code left '
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-943: Cleanup & Final Regression

**Feature**: FEAT-137 — AgentCrew Primitives Migration
**Spec**: `sdd/specs/agentcrew-primitives.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-942
**Assigned-to**: unassigned

---

## Context

After all four execution modes are migrated (TASK-939 through TASK-942), crew.py still contains dead local definitions that are no longer used: the local `FlowContext` class, local type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`), and possibly other dead code left over from the incremental migration.

This task removes all dead definitions, verifies backward-compatible re-exports still work, runs the full regression suite, and checks performance baseline.

This is Module 6 (final) of the spec.

---

## Scope

- Remove dead local definitions from crew.py:
  - Local `FlowContext` class (crew.py:61-128 approximately).
  - Local `AgentRef` type alias (crew.py:55).
  - Local `DependencyResults` type alias.
  - Local `PromptBuilder` type alias.
  - Any other dead code identified during migration.
- Preserve backward-compatible re-exports:
  - `from parrot.bots.orchestration.crew import AgentNode` must work (alias to `_CrewAgentNode`).
  - `from parrot.bots.orchestration.crew import FlowContext` must work (re-export from `flows.core`).
- Add explicit re-export test.
- Run full test suite — ALL existing tests must pass.
- Performance baseline: run 5-agent parallel flow, verify ≤10% regression vs baseline.
- Verify `CrewResult` structure unchanged: all fields, aliases, `to_dict()`.

**NOT in scope**: Any behavioral changes. New features. Performance optimization.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Remove dead local definitions, add re-exports |
| `packages/ai-parrot/tests/test_crew_final_regression.py` | CREATE | Final regression + re-export + performance tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# After cleanup, crew.py should import these from flows.core:
from parrot.bots.flows.core import (
    FlowContext,
    AgentRef,
    DependencyResults,
    PromptBuilder,
    determine_run_status,
    NodeExecutionInfo,
    AgentTaskMachine,
    TransitionCondition,
    AgentLike,
    FlowStatus,
)

# Re-exports to preserve for backward compat:
# At module level in crew.py, ensure these are importable:
# AgentNode (= _CrewAgentNode)
# FlowContext (from flows.core)
```

### Existing Signatures to Use

```python
# Dead definitions to remove from crew.py:
# class FlowContext:                    # crew.py:61 — REMOVE (use flows.core)
# AgentRef = Union[str, ...]            # crew.py:55 — REMOVE (use flows.core)
# DependencyResults = Dict[str, str]    # crew.py — REMOVE
# PromptBuilder = Callable[...]         # crew.py — REMOVE

# Preserved definitions (NOT removed):
# class _CrewAgentNode(AgentNode):      # crew.py — KEEP (subclass of core)
# AgentNode = _CrewAgentNode            # crew.py:241 — KEEP (backward compat)
# class AgentCrew(...):                 # crew.py:244 — KEEP (main class)
```

### Does NOT Exist

- ~~`crew.py` re-exporting `AgentTaskMachine`~~ — not expected; users import FSM from `flows.core`
- ~~`crew.py` `__all__`~~ — verify if exists; if not, re-exports work via direct import

---

## Implementation Notes

### Re-export Pattern

```python
# At module level in crew.py, after removing local definitions:
from parrot.bots.flows.core import FlowContext  # re-export for backward compat
# This makes `from parrot.bots.orchestration.crew import FlowContext` work
```

### Performance Baseline Test

```python
@pytest.mark.real_llm
async def test_performance_baseline_5_agent_parallel():
    """5-agent parallel flow wall-clock time within 10% of baseline."""
    import time
    start = time.monotonic()
    result = await crew.run_parallel(
        [{"task": f"task-{i}"} for i in range(5)]
    )
    elapsed = time.monotonic() - start
    # Compare against a stored baseline or just verify it completes
    # within a reasonable time (e.g., < 30 seconds for 5 agents)
    assert result.status == "completed"
    assert elapsed < 30  # generous ceiling
```

### Key Constraints

- Every `from parrot.bots.orchestration.crew import X` that worked before MUST still work after.
- The `CrewResult` return type from all `run_*` methods must be structurally identical.
- Run full test suite: `pytest packages/ai-parrot/tests/ -v`

---

## Acceptance Criteria

- [ ] Local `FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder` removed from crew.py
- [ ] `from parrot.bots.orchestration.crew import AgentNode` works (re-export)
- [ ] `from parrot.bots.orchestration.crew import FlowContext` works (re-export)
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/ -v`
- [ ] All new regression tests from TASK-939 through TASK-942 pass
- [ ] `CrewResult` structure and `to_dict()` output unchanged
- [ ] Performance: 5-agent parallel ≤10% regression (or within generous ceiling)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/orchestration/crew.py`
- [ ] No circular import issues

---

## Test Specification

```python
# packages/ai-parrot/tests/test_crew_final_regression.py
import pytest


class TestBackwardCompatImports:
    def test_import_agentnode_from_crew(self):
        from parrot.bots.orchestration.crew import AgentNode
        assert AgentNode is not None

    def test_import_flowcontext_from_crew(self):
        from parrot.bots.orchestration.crew import FlowContext
        assert FlowContext is not None

    def test_import_crewresult_from_models(self):
        from parrot.models.crew import CrewResult
        assert CrewResult is not None

    def test_agentnode_is_crewagentnode(self):
        from parrot.bots.orchestration.crew import AgentNode, _CrewAgentNode
        assert AgentNode is _CrewAgentNode


class TestCrewResultStructure:
    async def test_result_has_expected_fields(self, crew_with_3_stub_agents):
        result = await crew_with_3_stub_agents.run_sequential("test")
        assert hasattr(result, "output")
        assert hasattr(result, "status")
        assert hasattr(result, "agents")
        assert hasattr(result, "errors")
        assert hasattr(result, "total_time")
        assert hasattr(result, "metadata")
        assert hasattr(result, "execution_log")

    async def test_result_to_dict(self, crew_with_3_stub_agents):
        result = await crew_with_3_stub_agents.run_sequential("test")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "output" in d
        assert "status" in d


class TestNoCircularImports:
    def test_flows_core_does_not_import_crew(self):
        """flows.core must NOT import from orchestration.crew."""
        import parrot.bots.flows.core as core
        import inspect
        source_file = inspect.getfile(core)
        # grep the flows/core directory for crew imports
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "orchestration.crew", source_file.rsplit("/", 1)[0]],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", f"Circular import detected: {result.stdout}"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-942 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm all dead definitions are still present (not already removed)
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-943-cleanup-final-regression.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
