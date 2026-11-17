# TASK-5739: Wire and verify agent memory configuration

**Feature**: FEAT-907 — Agent Memory Configuration Contracts
**Spec**: `sdd/specs/agent-memory-factory-fixes.spec.md`
**Discovered-from**: `issue:8861056e6f3c`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Resolve the remaining verified gaps in issue:8861056e6f3c, as specified in FEAT-907.

## Scope

Add an optional typed skill registry to both factory return paths, gated by include_relevant_skills. Bind existing host skills before prepare_context. Preserve zero section allocations. Document unsupported compatibility fields and the operator-only dynamics switch in model descriptions. Add behavioral regression coverage for every reported knob.

Not in scope: new reflection algorithms, dynamics policies, skill tenancy, or unrelated lifecycle refactors.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` | MODIFY | Wire and verify agent memory configuration |
| `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` | MODIFY | Wire and verify agent memory configuration |
| `packages/ai-parrot/src/parrot/memory/agent_memory/models.py` | MODIFY | Wire and verify agent memory configuration |
| `packages/ai-parrot/tests/memory/agent_memory/test_config_contract.py` | CREATE | Wire and verify agent memory configuration |

## Codebase Contract

### Verified Imports

```python
from parrot.memory.agent_memory.factory import _manager_config, _warn_unsupported_knobs, create_memory_manager
from parrot.memory.agent_memory.mixin import AgentMemoryMixin
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryRequestScope
from parrot.memory.agent_memory.toolkit import AgentMemoryToolkit
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import SkillRegistry, UnifiedMemoryManager
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.models import MemoryCandidate
from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path
import pytest
```

### Existing Signatures to Use

- factory.py:86 `_manager_config(config: AgentMemoryConfig) -> MemoryConfig`.
- factory.py:148 async `create_memory_manager(config, *, namespace, evidence_tenant_resolver=None)`.
- mixin.py:80 async `prepare_memory(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext`.
- mixin.py:146 `_bind_skill_registry(self, manager: UnifiedMemoryManager) -> None`.
- unified/manager.py:39 SkillRegistry protocol; manager constructor already accepts skill_registry.
- unified/context.py:125 `assemble_candidates(candidates, *, scope)`.
- agent_memory/toolkit.py:154 async `memory_review(memory_ids, signal, exposure_id)` checks memory_dynamics before parsing the signal.
Paths are relative to packages/ai-parrot/src/parrot/memory/.

### Does NOT Exist

No factory skill_registry parameter exists before TASK-5739. No manager consumers exist for reflection, suppression or startup flushing.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/factory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_config_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Blueprint

1. Import the existing SkillRegistry protocol alongside UnifiedMemoryManager. Add keyword-only skill_registry: SkillRegistry | None = None to create_memory_manager; explain that injected registries follow manager lifecycle. Pass it only when include_relevant_skills is true to both manager constructors, so neither the persistent nor storage-free path loses skills.
2. Replace the guarded weight loop with unconditional assignments using tokens / total if total else 0.0, so explicit all-zero allocations never restore defaults.
3. Bind the existing host registry before context retrieval, preserving _bind_skill_registry's enabled check and existing-manager override behavior. Do not call registry.configure in the request path.
4. Add Field descriptions for the unsupported compatibility flags, relative section allocations, user hard ceiling, and explicit operator review gate. Preserve defaults and existing warning semantics.
5. Build registry doubles and scoped MemoryCandidate objects to test real context output, not just internal assignments. Parameterize each knob, include all-zero, disabled/missing skills, both factory resource paths, first-turn recall and explicit registry preservation. Check each unsupported warning separately and the existing toolkit dynamics gate.

### factory.py (MODIFY)
Anchor `async def create_memory_manager(` occurs once at line 148. The weights block begins `    total = sum(shares.values())` (one occurrence).
```python
from parrot.memory.unified.manager import SkillRegistry, UnifiedMemoryManager
# New keyword-only parameter:
skill_registry: SkillRegistry | None = None
# Pass in each UnifiedMemoryManager construction:
skill_registry=skill_registry if config.include_relevant_skills else None
# Assign every weight, including an all-zero allocation:
for name, tokens in shares.items():
    setattr(manager_config, name, tokens / total if total else 0.0)
```
Why: both resource paths must expose the same public configuration contract.

### mixin.py (MODIFY)
Anchor `        return await manager.prepare_context(query, scope=scope)` occurs once at line 99. Insert immediately before it:
```python
self._bind_skill_registry(manager)
```
Why: first context preparation precedes complete_memory, where binding previously happened.

### models.py (MODIFY)
Anchor `class AgentMemoryConfig(BaseModel):` occurs once at line 15. Replace the affected field declarations with typed Field declarations preserving defaults and validation. Descriptions must explain relative allocations, the user ceiling, unsupported reflection/suppression/flushing and operator-only dynamics gating.

### test_config_contract.py (CREATE)
```python
"""Behavioral regressions for agent memory configuration contracts."""
from __future__ import annotations

from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.memory.agent_memory.factory import _manager_config, _warn_unsupported_knobs, create_memory_manager
from parrot.memory.agent_memory.mixin import AgentMemoryMixin
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryRequestScope
from parrot.memory.agent_memory.toolkit import AgentMemoryToolkit
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.models import MemoryCandidate
```
Add typed fixtures and tests for the behavior in the acceptance criteria. Use tmp_path for persistent SQLite; always clean up constructed managers.

### FILL IN checklist
- [ ] Implement the bounded factory/mixin edits and schema descriptions.
- [ ] Add executable tests for each field and skill recall path.


## Acceptance Criteria

- [ ] Scope implemented with no unrelated changes.
- [ ] Every reported option has tested behavior or an explicitly documented unsupported contract.
- [ ] Disabled/missing skills are safe and first-turn skills work when available.
- [ ] All-zero section allocations do not restore defaults.
- [ ] Validation commands pass; changed Python files pass Black and Ruff.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_config_contract.py packages/ai-parrot/tests/memory/agent_memory/test_factory.py packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py packages/ai-parrot/tests/memory/agent_memory/test_facade.py packages/ai-parrot/tests/memory/agent_memory/test_config.py -q`


## Test Specification

Use the spec section 4 matrix. Tests use temporary SQLite storage and registry doubles; no network or provider calls. Documentation validation resolves the existing page and module references.

## Agent Instructions

Implement only in the FEAT-907 worktree. Verify the task contract, run validation, commit scoped files, record review evidence and finalize using parrot sdd task finalize with the exact implementation HEAD.

## Completion Note

- Task: TASK-5739
- Feature: agent-memory-factory-fixes
- Implementation SHA: 8d41f357e4a6161073604882bb5f83850bed89e6
- Closed at (UTC): 2026-11-17T14:17:42+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| lint | Black and Ruff passed |
| scope | Factory skills injection, first-turn skills binding, all-zero allocations and explicit configuration contracts |
| tests | 51 passed |
