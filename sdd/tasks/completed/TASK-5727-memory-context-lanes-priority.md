# TASK-5727: Pack recall lanes and enforce user memory budgets

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5724
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Implement M3 assembler behavior using TASK-5724 fields and rendering.

## Scope

- Implement M3 assembler behavior using TASK-5724 fields and rendering.
- Use one episodic budget, warning-first ordering, whole-record admission and the packed-text len//4 estimate including separators.
- Implement both priority modes and stable reference order independently of packing order.
- Retain the existing 10% headroom in both modes: effective_budget = int(max_context_tokens * 0.9), supplied by self._max_tokens. Do not apply headroom twice.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/context.py` | MODIFY | Pack recall lanes and enforce user memory budgets |
| `packages/ai-parrot/tests/memory/unified/test_context.py` | MODIFY | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
import pytest
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.models import MemoryCandidate, MemoryContext, MemoryConfig
from parrot.memory.agent_memory.models import MemoryRequestScope
```

### Dependency-created Imports

No unimplemented import is assumed before its dependency is complete.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler.assemble_candidates` — `packages/ai-parrot/src/parrot/memory/unified/context.py:125`: `def assemble_candidates(self, candidates: list[MemoryCandidate], *, scope: MemoryRequestScope) -> MemoryContext`
- `sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler._estimate_tokens` — `packages/ai-parrot/src/parrot/memory/unified/context.py:235`: `def _estimate_tokens(text: str) -> int`
- `sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler._candidate_ref` — `packages/ai-parrot/src/parrot/memory/unified/context.py:247`: `def _candidate_ref(candidate: MemoryCandidate) -> str`
- `sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryCandidate` — `packages/ai-parrot/src/parrot/memory/unified/models.py:20`: `class MemoryCandidate(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryContext` — `packages/ai-parrot/src/parrot/memory/unified/models.py:68`: `class MemoryContext(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryConfig` — `packages/ai-parrot/src/parrot/memory/unified/models.py:164`: `class MemoryConfig(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope` — `packages/ai-parrot/src/parrot/memory/agent_memory/models.py:52`: `class MemoryRequestScope(BaseModel)`

### Does NOT Exist

- There is no separate recall token budget or provider-token guarantee; profile records must not be truncated.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_context.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler.assemble_candidates",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler._estimate_tokens",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler._candidate_ref",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryCandidate",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryContext",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryConfig",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#MemoryRequestScope"
  ]
}
```

## Implementation Notes

Consumes MemoryCandidate.lane, MemoryContext.episodic_recall and MemoryConfig cap/priority fields from TASK-5724.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.

User-approved decision (2026-11-16; spec revision 0.5): retain the existing 10% headroom in both modes. Use budget = self._max_tokens = int(config.max_context_tokens * 0.9). High priority reserves min(user_context_tokens, budget); normal keeps weighted allocation plus rollover within the same effective budget. With a None user cap, high uses its normalized weighted share. Equality is required only when both allocations admit the same records, not for default settings unconditionally.

## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot/src/parrot/memory/unified/context.py` (MODIFY)

```python
# Anchor:         for section in ("episodic", "skills", "brain", "user_knowledge"):
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/unified/context.py:194
# Anchor:             section_budget = int(budget * weights[section]) + rollover
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/unified/context.py:197
# Anchor: episodic_warnings=packed_sections.get("episodic", ""),
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/unified/context.py:216
# MODIFY assemble_candidates in place; preserve its signature and scope-first admission.
def assemble_candidates(
    self, candidates: list[MemoryCandidate], *, scope: MemoryRequestScope
) -> MemoryContext:
    """Pack whole scoped candidates with one episodic budget and an explicit user ceiling."""
    # Keep budget = self._max_tokens; the existing constructor already applies 10% headroom.
    # FILL IN: episodic warnings precede recalls, each retaining the existing stable sort key.
    # Keep separate lane texts; estimate their combined packed text including separators.
    # normal: weighted shares plus rollover, user allocation clamped to non-None ceiling.
    # high: pack users first at min(cap, budget); None cap uses normalized weighted share.
    # Keep all enabled weights; later rollover starts at zero, never unused user budget.
    # Clamp each later section to remaining budget; zero user cap admits no text or refs.
    # Build prompt and both ref tuples in fixed episodic, skills, brain, user order.
    # Construct MemoryContext with both episodic fields, then compute the final prompt digest.
    raise NotImplementedError
```

**Why**: Packing order changes allocation, but rendering/reference order and review identities stay stable.

### `packages/ai-parrot/tests/memory/unified/test_context.py` (MODIFY)

```python
# Anchor: def test_packed_original_refs_follow_complete_candidate_content() -> None:
# occurrences: 1; grep -F -c verified at packages/ai-parrot/tests/memory/unified/test_context.py:48
# INSERT new tests at module scope before this definition; preserve it.
def test_assembler_splits_episodic_lanes_within_one_budget() -> None:
    """Warnings pack first; recalls use their shared remaining budget."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

def test_user_section_cap_applies_after_normalization_and_rollover() -> None:
    """Normalization and rollover cannot raise the user ceiling."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

def test_user_section_cap_zero_and_legacy_none() -> None:
    """Zero suppresses even tiny records and refs; None adds no user-specific cap."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

def test_user_priority_high_reserves_ceiling_before_weighted_sections() -> None:
    """At configured 400/effective 360, high admits 125 profile tokens; normal has 108."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError

def test_user_priority_modes_agree_when_weighted_share_reaches_ceiling() -> None:
    """Content, refs and digests agree when both allocations admit the same records."""
    # FILL IN: assert the real behavior and adversarial boundaries in this task's ACs.
    raise NotImplementedError
```

**Why**: Preserve existing regressions while adding focused behavior checks.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/unified/context.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/tests/memory/unified/test_context.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: Warnings/recall share one budget; omitted content never leaks delivered_refs or memory_refs.
- [ ] **AC-2**: A 600-token user ceiling omits an 800-token record whole even under normalized-only-user or rollover allocation.
- [ ] **AC-3**: Zero suppresses text/refs even when len(text)//4 is zero; None adds no user-specific ceiling.
- [ ] **AC-4**: At configured maximum 400/effective budget 360 and default four-section shares with no rollover, normal has 108 user tokens while high can admit a 125-token profile; total tokens never exceed 360. Retain the existing effective budget for normal/None direct callers too.
- [ ] **AC-5**: With configured maximum 2400 and default shares, test identical admitted records produce identical content/refs/digests. At configured maximum 2000, no rollover and a 550-token profile, high may admit it while normal (540 user tokens) cannot. Also cover high/None, both modes with zero cap, integer rounding and fixed section/ref ordering; tokens_used never exceeds int(max_context_tokens * 0.9).

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_context.py -q`

## Test Specification

Use named blueprint cases as the acceptance matrix. Cover the adversarial boundaries in Scope/ACs and preserve existing regressions.

## Agent Instructions

1. Use the host session and feature worktree provisioned by `parrot sdd worktree ensure --slug user-memory-recall-e2e --feature-id FEAT-904`; never implement on dev.
2. Read the spec and confirm every dependency is done in `sdd/tasks/index/user-memory-recall-e2e.json`.
3. Re-verify contracts and use sdd-start lifecycle; never silently expand target files.
4. Activate the shared venv and set PYTHONPATH=packages/ai-parrot/src for worktree tests; never uv sync there.
5. Run scoped validation and applicable lint; retain logs in artifacts/logs/.
6. Commit implementation, then use parrot sdd task finalize with real TaskCompletionEvidence and exact implementation HEAD.
7. Inspect generated Completion Note and active-to-completed move; commit only task SDD state. Do not hand-edit completion state or push from the worker.

## Completion Note

Pending; the task finalizer generates this after implementation and validation.


## Completion Note

Implemented by seat gpt-5.6-luna (codex), 1 attempt, 0 review fixes. Merge-tier validation: 104 passed. Closed via close_task.sh.
