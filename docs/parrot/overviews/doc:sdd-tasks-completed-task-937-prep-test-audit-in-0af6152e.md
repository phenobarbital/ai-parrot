---
type: Wiki Overview
title: 'TASK-937: Prep — Test Audit & Infrastructure'
id: doc:sdd-tasks-completed-task-937-prep-test-audit-infrastructure-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Before migrating AgentCrew to consume `flows.core` primitives, we need to:'
relates_to:
- concept: mod:parrot.bots.flows.core.storage.synthesis
  rel: mentions
---

# TASK-937: Prep — Test Audit & Infrastructure

**Feature**: FEAT-137 — AgentCrew Primitives Migration
**Spec**: `sdd/specs/agentcrew-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Before migrating AgentCrew to consume `flows.core` primitives, we need to:
1. Audit existing AgentCrew tests to understand current coverage and identify invariant gaps.
2. Set up `@pytest.mark.real_llm` marker infrastructure for real-LLM regression tests.
3. Update storage imports in `crew.py` from the old path to the canonical new path.

This is Module 0 of the spec — all subsequent tasks depend on it.

---

## Scope

- Audit existing tests in `packages/ai-parrot/tests/test_agent_crew_examples.py` and classify each test by: which invariant it covers, whether it uses mock or real LLM, happy-path vs edge case.
- Register `@pytest.mark.real_llm` marker in `pytest.ini` (where `integration` and `live` markers are defined).
- Add skip logic: tests marked `real_llm` skip unless `PARROT_TEST_REAL_LLM=1` env var is set.
- Update storage imports in `crew.py` from `from ..flow.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin` to `from ..flows.core.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin`.
- Update `from ..flow.storage.synthesis import SYNTHESIS_PROMPT` to the canonical path.
- Verify all existing tests still pass after import changes.

**NOT in scope**: Writing new tests (that's for subsequent tasks). Modifying any types or classes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pytest.ini` | MODIFY | Add `real_llm` marker definition |
| `packages/ai-parrot/tests/conftest.py` | MODIFY | Add skip logic for `real_llm` marker |
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Update storage imports (lines 50-51) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# OLD storage imports in crew.py (lines 50-51) — TO BE REPLACED:
from ..flow.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin  # crew.py:50
from ..flow.storage.synthesis import SYNTHESIS_PROMPT  # crew.py:51

# NEW canonical storage imports — REPLACE WITH:
from ..flows.core.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin
# For SYNTHESIS_PROMPT, verify its location:
# It may be in flows.core.storage.synthesis or may need to stay at the old path.
# VERIFY before changing: grep -rn "SYNTHESIS_PROMPT" packages/ai-parrot/src/parrot/
```

### Existing Signatures to Use

```python
# pytest.ini — current markers (lines 3-5):
# markers =
#     integration: Integration tests with external APIs
#     live: Live integration tests that require external services

# packages/ai-parrot/tests/test_agent_crew_examples.py — existing tests:
# test_agentcrew_sequential_execution_passes_context()        line 111
# test_agentcrew_parallel_execution_returns_all_results()     line 152
# test_agentcrew_parallel_execution_all_results()             line 188
# test_agentcrew_flow_execution_respects_dependencies()       line 226
# test_agentcrew_loop_execution_stops_when_condition_met()    line 266
# test_agentsflow_fsm_execution_records_transitions()         line 320
```

### Does NOT Exist

- ~~`@pytest.mark.real_llm`~~ — does NOT exist yet; this task creates it
- ~~`PARROT_TEST_REAL_LLM`~~ — env var not referenced anywhere yet
- ~~`parrot.bots.flows.core.storage.synthesis.SYNTHESIS_PROMPT`~~ — verify if this was moved by FEAT-134 or still only at old path

---

## Implementation Notes

### Pattern to Follow

```python
# In pytest.ini, add under existing markers:
#     real_llm: Real LLM integration tests (require PARROT_TEST_REAL_LLM=1)

# In conftest.py, add skip logic:
import os
def pytest_collection_modifyitems(config, items):
    if not os.environ.get("PARROT_TEST_REAL_LLM"):
        skip_real_llm = pytest.mark.skip(reason="Set PARROT_TEST_REAL_LLM=1 to run")
        for item in items:
            if "real_llm" in item.keywords:
                item.add_marker(skip_real_llm)
```

### Key Constraints

- Do NOT modify any existing test logic — only add marker infrastructure.
- The `SYNTHESIS_PROMPT` import path change needs verification: check if FEAT-134 moved it to `flows.core.storage.synthesis` or if it only exists at the old path. If it wasn't moved, keep the old import for now and document the gap.
- After changing imports, run: `pytest packages/ai-parrot/tests/test_agent_crew_examples.py -v`

---

## Acceptance Criteria

- [ ] `@pytest.mark.real_llm` marker registered in `pytest.ini`
- [ ] Skip logic works: `pytest -m real_llm` skips all without env var, runs with `PARROT_TEST_REAL_LLM=1`
- [ ] Storage imports in `crew.py` updated to canonical `flows.core.storage` path
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/test_agent_crew_examples.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/orchestration/crew.py`
- [ ] Test audit documented in completion note (which tests cover which invariants, gaps identified)

---

## Test Specification

```python
# No new test files created by this task.
# Verification is that all EXISTING tests pass after import changes.
# Run: pytest packages/ai-parrot/tests/test_agent_crew_examples.py -v
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-937-prep-test-audit-infrastructure.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
