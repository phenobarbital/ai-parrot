---
type: feature
base_branch: dev
projects: [core]
tags: [memory, configuration]
docs:
  policy: required
  pages: [wiki/memory/agent-memory.md]
  api_modules: [parrot.memory.agent_memory.factory, parrot.memory.agent_memory.models]
---

# Feature Specification: Agent Memory Configuration Contracts

**Feature ID**: FEAT-907
**Date**: 2026-11-17
**Author**: Codex
**Status**: approved

## 1. Motivation & Business Requirements

Resolve `issue:8861056e6f3c`. Current dev already maps user priority, retrieval limits and nonzero section allocations, and warns about three unsupported settings. Remaining gaps are first-turn skill recall (binding happens only on completion), missing registry injection in the public factory, all-zero allocations reverting to defaults, and inaccurate option documentation.

Goals: every reported setting has a tested consumer or an explicit documented compatibility contract; relevant skills can be recalled on the first turn. Preserve existing defaults and callers.
Non-goals: implement reflection, tool suppression, startup flushing, change dynamics algorithms, change skill tenancy, or refactor the unified manager lifecycle.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:6cfd8cdb50d9fde6bb9edf4a343d347e2ac69eb61a2bb3188034bfb079944ae0 evaluation_digest=sha256:90e115e2fedd252608984aef8641d3c3078f0480e4681f7eb02432e1d2a606d6 rules_version=1 status=pass -->

## 2. Architectural Design

Keep the existing factory, mixin and manager boundaries. Add an optional keyword-only `skill_registry` argument to `create_memory_manager`, forwarded only when skills are enabled on both resource-construction paths. Directly injected registries follow UnifiedMemoryManager's existing configure/cleanup lifecycle contract. Do not instantiate a registry or add dependencies.

Call the existing `_bind_skill_registry` immediately before `prepare_context`; retain late binding on completion and preserve explicitly supplied registries. Host binding remains lazy so initialization order does not prevent first-turn recall.

Always assign the four section weights from configured allocations; use zero for every weight when their sum is zero. Preserve normalized enabled-section allocation and rollover behavior. These values are relative allocations, not independent hard limits; user_context_tokens remains an additional hard ceiling.

Describe `enable_reflection`, `suppress_trivial_tools` and `flush_on_startup` as unsupported compatibility settings in Pydantic field descriptions and wiki text. Non-default values continue producing warnings. Describe `memory_dynamics` as enabling explicit operator review through the toolkit/CLI, not as a manager/store dynamics switch.

## 3. Module Breakdown

1. Configuration wiring and regressions: factory.py, mixin.py, models.py and test_config_contract.py.
2. Documentation: update wiki/memory/agent-memory.md after the configuration contract is implemented.

### Interface Skeletons

```python
async def create_memory_manager(
    config: AgentMemoryConfig,
    *,
    namespace: MemoryNamespace,
    evidence_tenant_resolver: EvidenceTenantResolver | None = None,
    skill_registry: SkillRegistry | None = None,
) -> UnifiedMemoryManager:
    """Build enabled resources and accept an optional caller-provided skill registry."""

async def prepare_memory(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext:
    """Bind available host skills before retrieving supplementary context."""
```

Existing skeleton anchors: factory.py:148, mixin.py:80. SkillRegistry is the existing structural protocol in unified/manager.py:39. No new model fields or defaults are introduced.

Delegation eligibility: none; implementation and tests require behavioral review.

## 4. Test Specification

Parameterize all four section allocation knobs; verify normalized proportions and zero allocations. Exercise assembled context with all-zero allocations. Verify max context and warning/recall/record limits and both user priorities are forwarded.

Exercise factory registry injection with and without persistent storage, disabled skills and absent registries. Verify actual first-turn prepare_memory output using a registry double, and that explicit manager registries are preserved. Verify unsupported warning behavior separately for each setting and explicit dynamics-review gating. No provider or network calls.

### Validation Contract

```yaml
tests:
  - packages/ai-parrot/tests/memory/agent_memory/test_config_contract.py
  - packages/ai-parrot/tests/memory/agent_memory/test_factory.py
  - packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py
  - packages/ai-parrot/tests/memory/agent_memory/test_facade.py
  - packages/ai-parrot/tests/memory/agent_memory/test_config.py
  - packages/ai-parrot/tests/memory/agent_memory/test_documentation.py
markers: []
```

## 5. Acceptance Criteria

- [ ] Each reported option is covered by a consumer test or unsupported-contract test.
- [ ] First-turn context can include skills; disabled and missing registries yield no skill text.
- [ ] All-zero allocations yield no supplementary content.
- [ ] Existing retrieval limits and priority mappings remain unchanged.
- [ ] Wiki and schema descriptions state compatibility and dynamics limitations.
- [ ] Focused tests, formatting and lint pass; no new dependencies.

## 6. Codebase Contract

Verified against `ea1ee267be4a3f8af0b8730366871fb17566893a`.
Paths below are relative to `packages/ai-parrot/src/parrot/memory/` unless absolute repository paths are shown.

### Verified Imports

```python
from parrot.memory.agent_memory.factory import create_memory_manager, _manager_config, _warn_unsupported_knobs
from parrot.memory.agent_memory.mixin import AgentMemoryMixin
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryRequestScope
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import SkillRegistry, UnifiedMemoryManager
from parrot.memory.unified.models import MemoryCandidate
from parrot.memory.unified.context import ContextAssembler
```

### Existing Signatures and Integration Points

- factory.py:86 `_manager_config(config: AgentMemoryConfig) -> MemoryConfig` translates enabled lanes and limits.
- mixin.py:146 `_bind_skill_registry(self, manager: UnifiedMemoryManager) -> None` preserves nonempty manager registries and ignores disabled skills.
- unified/manager.py:46 `SkillRegistry.get_relevant_skills(query, max_skills=3) -> str` is async.
- unified/manager.py:97 `UnifiedMemoryManager.__init__` already accepts skill_registry; configure/cleanup visit non-None subsystems.
- unified/context.py:125 `ContextAssembler.assemble_candidates(candidates, *, scope)` consumes normalized_section_weights.
- agent_memory/toolkit.py:154 `AgentMemoryToolkit.memory_review` gates explicit reviews on memory_dynamics.

### Does NOT Exist

- There is no create_memory_manager skill_registry parameter before this change.
- There is no unified-manager reflection, tool suppression or startup-flush consumer of these AgentMemoryConfig options.

### Edit Sites

| File | Action | Verbatim anchor | Occurrences |
|---|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` | MODIFY | `async def create_memory_manager(` | 1 |
| `packages/ai-parrot/src/parrot/memory/agent_memory/mixin.py` | MODIFY | `        return await manager.prepare_context(query, scope=scope)` | 1 |
| `packages/ai-parrot/src/parrot/memory/agent_memory/models.py` | MODIFY | `class AgentMemoryConfig(BaseModel):` | 1 |
| `packages/ai-parrot/tests/memory/agent_memory/test_config_contract.py` | CREATE | — | — |
| `wiki/memory/agent-memory.md` | MODIFY | `### AgentMemoryConfig` | 1 |

## 7. Implementation Notes & Constraints

Use the shared environment without installing dependencies. Set PYTHONPATH to worktree package sources so tests import the implementation branch. Preserve existing skill lifecycle ownership; do not add configure calls to prepare_memory. All-zero allocations must stay zero instead of restoring defaults. Logs live under the main checkout's artifacts/logs/FEAT-907.

Worktree strategy: one feature worktree provisioned with `parrot sdd worktree ensure --slug agent-memory-factory-fixes --feature-id FEAT-907`. Implementation only in that checkout. Two tasks; docs depend on the implemented configuration signatures.

## Consequences

<!-- decision-audit: input_digest=sha256:6cfd8cdb50d9fde6bb9edf4a343d347e2ac69eb61a2bb3188034bfb079944ae0 evaluation_digest=sha256:90e115e2fedd252608984aef8641d3c3078f0480e4681f7eb02432e1d2a606d6 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/agent-memory-factory-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: memory
- Unmapped tags: configuration
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "memory"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "configuration"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/agent-memory-factory-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:90e115e2fedd252608984aef8641d3c3078f0480e4681f7eb02432e1d2a606d6",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:6cfd8cdb50d9fde6bb9edf4a343d347e2ac69eb61a2bb3188034bfb079944ae0",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

None. The ledger explicitly allows documenting unsupported options; compatibility defaults remain accepted.

## 9. Design Research Cross-Check

Skipped optional design research: localized wiring correction with verified existing contracts. Independent implementation review remains required at closeout.

## 10. Documentation

Policy: required. Update `wiki/memory/agent-memory.md`: option table, section-budget semantics, unsupported settings, dynamics-review scope and first-turn skills. No new wiki pages.
