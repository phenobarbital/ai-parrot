# TASK-5709: Own background extraction clients and drain writes

**Feature**: FEAT-892 — Agent Memory
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5708, TASK-5681, TASK-5704
**Assigned-to**: unassigned
**Discovered-from**: `issue:f83b1577d523`

## Context

Follow-up to the claimed ledger review on the implemented FEAT-892 worktree at 983470d620.
The spec body is approved; its legacy frontmatter still says review. This is an explicitly requested
review fix under the existing approved capability/lifecycle contracts, not a new feature approval.

## Scope

Preserve detached owned response writes; bind a client factory once, using resolved LLMConfig construction or an explicit memory_extraction_client_factory. Never enter or mutate the response client. Construct and close a fresh extraction client per write; retain standalone manager client compatibility. Drain before resource shutdown and reconfiguration, including caller cancellation. Prove latency isolation and concurrent client ownership with event barriers.

**NOT in scope**: provider base changes, new dependencies, unrelated ledger issues, storage redesign.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY |
| `packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py` | MODIFY |
| `packages/ai-parrot/tests/memory/agent_memory/test_facade.py` | MODIFY |
| `packages/ai-parrot/tests/memory/agent_memory/test_background_extraction.py` | CREATE |

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
      "path": "packages/ai-parrot/src/parrot/memory/unified/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_facade.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_background_extraction.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py#AgentMemoryMixin",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager"
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

### `packages/ai-parrot/src/parrot/memory/unified/manager.py` (MODIFY)
```python
# Anchor: class UnifiedMemoryManager:
# occurrences: 1; verified in feature worktree at packages/ai-parrot/src/parrot/memory/unified/manager.py:65
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

### `packages/ai-parrot/tests/memory/agent_memory/test_facade.py` (MODIFY)
```python
# Anchor: class _ToolFacade(_Facade):
# occurrences: 1; verified in feature worktree at packages/ai-parrot/tests/memory/agent_memory/test_facade.py:232
# FILL IN: apply the scoped behavior below this anchor, bounded by the acceptance criteria.
```
Preserve existing public behavior outside this issue; use the tests to constrain edge cases.

### `packages/ai-parrot/tests/memory/agent_memory/test_background_extraction.py` (CREATE)
Create typed offline regression tests with pytest and asyncio.Event barriers for the acceptance criteria. No provider/network calls.

### FILL IN checklist

- [ ] Implement all scoped behavior and failure paths.
- [ ] Prove resource ownership and scoped persistence without sleeps or external services.
- [ ] Preserve existing reviewed code and document any compatibility behavior.

## Acceptance Criteria

- [ ] Preserve detached owned response writes; bind a client factory once, using resolved LLMConfig construction or an explicit memory_extraction_client_factory. Never enter or mutate the response client. Construct and close a fresh extraction client per write; retain standalone manager client compatibility. Drain before resource shutdown and reconfiguration, including caller cancellation. Prove latency isolation and concurrent client ownership with event barriers.
- [ ] All validation commands pass with the worktree on PYTHONPATH.
- [ ] Changed Python files pass ruff and black (120 columns).

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_background_extraction.py -q`
- `pytest packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py -q`
- `pytest packages/ai-parrot/tests/memory/agent_memory/test_facade.py -q`
- `pytest packages/ai-parrot/tests/memory/unified/test_manager.py -q`

## Test Specification

Exercise successful behavior and failure/cancellation boundaries with real local SQLite where persistence matters.
Use per-test temporary paths. For asynchronous ordering, events signal entry and release explicitly.

## Agent Instructions

Implement in the FEAT-892 worktree; preserve unrelated work. Use parrot sdd task finalize with real validation
and semantic-review evidence for the exact implementation commit. Never hand-edit completion state.
