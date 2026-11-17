# TASK-5740: Documentation — agent memory option contracts

**Feature**: FEAT-907 — Agent Memory Configuration Contracts
**Spec**: `sdd/specs/agent-memory-factory-fixes.spec.md`
**Discovered-from**: `issue:8861056e6f3c`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5739
**Assigned-to**: unassigned

## Context

Resolve the remaining verified gaps in issue:8861056e6f3c, as specified in FEAT-907.

## Scope

Update the existing agent-memory page to describe the configuration contract implemented by TASK-5739. Correct unsupported settings, relative allocations, all-zero behavior, user cap, first-turn skills and memory_dynamics scope.

Not in scope: new reflection algorithms, dynamics policies, skill tenancy, or unrelated lifecycle refactors.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/memory/agent-memory.md` | MODIFY | Documentation — agent memory option contracts |

## Codebase Contract

### Verified Imports

```python
# Documentation task; no imports are introduced.
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
      "path": "wiki/memory/agent-memory.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Blueprint

1. Update the option table under `### AgentMemoryConfig` (one occurrence at line 43), preserving unrelated documentation.
2. Explain relative allocations across enabled sources, rollover, the independent user ceiling, and no supplementary content when all section allocations are zero.
3. Describe factory registry injection and host binding before first preparation; caller-injected registries follow the existing manager lifecycle.
4. Explain that reflection, suppression and startup flushing are compatibility-only and non-default values warn. Dynamics gates explicit toolkit/CLI reviews rather than turning store algorithms on/off.

### wiki/memory/agent-memory.md (MODIFY)
Attachment anchor: `### AgentMemoryConfig` (one occurrence, line 43).
Replace affected table descriptions and add a concise Configuration limitations subsection before Automatic Recall and Packing.
Why: callers must be able to distinguish supported behavior from accepted compatibility fields.

### FILL IN checklist
- [ ] Update the option reference against implemented behavior and validate wiki references.


## Acceptance Criteria

- [ ] Documentation check passes: `parrot sdd techwiki check --spec sdd/specs/agent-memory-factory-fixes.spec.md --root .`.

- [ ] Scope implemented with no unrelated changes.
- [ ] Every reported option has tested behavior or an explicitly documented unsupported contract.
- [ ] Disabled/missing skills are safe and first-turn skills work when available.
- [ ] All-zero section allocations do not restore defaults.
- [ ] Validation commands pass; changed Python files pass Black and Ruff.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_documentation.py -q`

## Test Specification

Use the spec section 4 matrix. Tests use temporary SQLite storage and registry doubles; no network or provider calls. Documentation validation resolves the existing page and module references.

## Agent Instructions

Implement only in the FEAT-907 worktree. Verify the task contract, run validation, commit scoped files, record review evidence and finalize using parrot sdd task finalize with the exact implementation HEAD.

## Completion Note

- Task: TASK-5740
- Feature: agent-memory-factory-fixes
- Implementation SHA: 6e812bdd31d503bc62e5cf76092b5e5a84fb3eb0
- Closed at (UTC): 2026-11-17T14:20:00+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| scope | Configuration reference, limitations, allocations and skill lifecycle |
| techwiki | required - ok |
| tests | 11 passed |
