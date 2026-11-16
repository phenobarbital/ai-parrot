# TASK-5710: Complete memory configuration, evidence and status review fixes

**Feature**: FEAT-892 — Agent Memory
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5709
**Assigned-to**: unassigned
**Discovered-from**: `issue:e5d337886d82`

## Context

Follow-up to the claimed ledger review on the implemented FEAT-892 worktree at 983470d620.
The spec body is approved; its legacy frontmatter still says review. This is an explicitly requested
review fix under the existing approved capability/lifecycle contracts, not a new feature approval.

## Scope

Limit MRO config lookup to memory-aware subclasses and ignore descriptors/callables; keep explicit config precedence. Escape recalled markup and preserve data framing. Pass an optional trusted EvidenceTenantResolver through create_memory_manager and the mixin; reject missing/mismatched/tombstoned evidence through existing store checks. Read review synchronization from a healthy SQLite backend capability; unknown/degraded backends must not claim synchronized. Replace timing-based stream cancellation with a barrier and prove one real stored episode for a retried turn. Verify the existing bounded review cache and corrected stale comments; do not revert unrelated historical formatting. Update the agent-memory wiki page for these contracts.

**NOT in scope**: provider base changes, new dependencies, unrelated ledger issues, storage redesign.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/unified/models.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY |
| `packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py` | MODIFY |
| `packages/ai-parrot/tests/memory/agent_memory/test_factory.py` | MODIFY |
| `packages/ai-parrot/tests/memory/agent_memory/test_operations.py` | MODIFY |
| `packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py` | MODIFY |
| `wiki/memory/agent-memory.md` | MODIFY |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryContext
from parrot.memory.user.store import EvidenceTenantResolver
```

### Existing Signatures to Use

- `AgentMemoryMixin.complete_memory(self, event: MemoryEvent) -> None` routes events and owns pending writes.
- `UnifiedMemoryManager.record_event(self, event: MemoryEvent) -> MemoryWriteReceipt` preserves scoped durable receipts.
- `create_memory_manager(config: AgentMemoryConfig, *, namespace: MemoryNamespace) -> UnifiedMemoryManager` owns resource acquisition.
- `UserMemoryStore(path: Path, *, evidence_tenant_resolver: EvidenceTenantResolver | None = None)` fails closed on unavailable ChatStorage evidence.
- `LLMConfig` is a dataclass with client_class/client_instance/model/extra and generation settings; `AbstractBot._llm_config` retains resolved configuration.
- `SQLiteEpisodeBackend._require_database()` rejects closed backends; reviews apply transactionally and have no replay queue.

### Does NOT Exist

- No safe universal client clone method exists; never copy a live provider session.
- No backend review synchronization capability exists yet; unsupported backends must report unknown state.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/factory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_factory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_operations.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py",
      "action": "MODIFY"
    },
    {
      "path": "wiki/memory/agent-memory.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py#AgentMemoryMixin",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/factory.py#create_memory_manager",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py#AgentMemoryToolkit",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryContext",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend"
  ]
}
```

## Implementation Blueprint

### Steps (in order)

1. Preserve the preceding feature implementation and add the scoped contract changes; do not restart completed tasks.
2. Add deterministic offline tests first for the issue's failure paths and ownership boundaries.
3. Implement only the listed targets and run all validation commands against worktree source.
4. Review the actual diff, commit implementation, and finalize through structured evidence.

### `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` (MODIFY)
```python
# Anchor: class AgentMemoryMixin:
# occurrences: 1; verified in feature worktree at packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py:19
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` (MODIFY)
```python
# Anchor: async def create_memory_manager(config: AgentMemoryConfig, *, namespace: MemoryNamespace) -> UnifiedMemoryManager:
# occurrences: 1; verified in feature worktree at packages/ai-parrot/src/parrot/memory/agent_memory/factory.py:144
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py` (MODIFY)
```python
# Anchor: class AgentMemoryToolkit(AbstractToolkit):
# occurrences: 1; verified in feature worktree at packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py:20
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/src/parrot/memory/unified/models.py` (MODIFY)
```python
# Anchor: class MemoryContext(BaseModel):
# occurrences: 1; verified in feature worktree at packages/ai-parrot/src/parrot/memory/unified/models.py:48
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` (MODIFY)
```python
# Anchor: class SQLiteEpisodeBackend(AbstractEpisodeBackend):
# occurrences: 1; verified in feature worktree at packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py:185
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py` (MODIFY)
```python
# Anchor: class _Client(AbstractClient):
# occurrences: 1; verified in feature worktree at packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py:19
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/tests/memory/agent_memory/test_factory.py` (MODIFY)
```python
# Anchor: async def test_user_only_does_not_construct_episodes(tmp_path: Path) -> None:
# occurrences: 1; verified in feature worktree at packages/ai-parrot/tests/memory/agent_memory/test_factory.py:27
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/tests/memory/agent_memory/test_operations.py` (MODIFY)
```python
# Anchor: async def test_explicit_yaml_lazy_construct_close_reopen(
# occurrences: 1; verified in feature worktree at packages/ai-parrot/tests/memory/agent_memory/test_operations.py:41
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py` (MODIFY)
```python
# Anchor: class _Host(AgentMemoryMixin):
# occurrences: 1; verified in feature worktree at packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py:20
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `wiki/memory/agent-memory.md` (MODIFY)
```python
# Anchor: ### Configuration Precedence
# occurrences: 1; verified in feature worktree at wiki/memory/agent-memory.md:61
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### FILL IN checklist

- [ ] Implement all scoped behavior and failure paths.
- [ ] Prove resource ownership and scoped persistence without sleeps or external services.
- [ ] Preserve existing reviewed code and document any compatibility behavior.

## Acceptance Criteria

- [ ] Limit MRO config lookup to memory-aware subclasses and ignore descriptors/callables; keep explicit config precedence. Escape recalled markup and preserve data framing. Pass an optional trusted EvidenceTenantResolver through create_memory_manager and the mixin; reject missing/mismatched/tombstoned evidence through existing store checks. Read review synchronization from a healthy SQLite backend capability; unknown/degraded backends must not claim synchronized. Replace timing-based stream cancellation with a barrier and prove one real stored episode for a retried turn. Verify the existing bounded review cache and corrected stale comments; do not revert unrelated historical formatting. Update the agent-memory wiki page for these contracts.
- [ ] All validation commands pass with the worktree on PYTHONPATH.
- [ ] Changed Python files pass ruff and black (120 columns).

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_lifecycle.py -q`
- `pytest packages/ai-parrot/tests/memory/agent_memory/test_factory.py -q`
- `pytest packages/ai-parrot/tests/memory/agent_memory/test_operations.py -q`
- `pytest packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py -q`
- `pytest packages/ai-parrot/tests/memory/unified/test_models.py -q`
- `pytest packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py -q`
- `pytest packages/ai-parrot/tests/memory/agent_memory/test_documentation.py -q`

## Test Specification

Exercise successful behavior and failure/cancellation boundaries with real local SQLite where persistence matters.
Use per-test temporary paths. For asynchronous ordering, events signal entry and release explicitly.

## Agent Instructions

Implement in the FEAT-892 worktree; preserve unrelated work. Use parrot sdd task finalize with real validation
and semantic-review evidence for the exact implementation commit. Never hand-edit completion state.

## Completion Note

- Task: TASK-5710
- Feature: agent-memory-mixin
- Implementation SHA: eb466548719265c191865493671c2a935d3f5c58
- Closed at (UTC): 2026-11-16T10:45:08+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| summary | Memory-aware configuration lookup; escaped recall; trusted evidence resolver injection; backend review status; deterministic cancellation and durable retry regressions. |
| tests_passed | 66 |
