# TASK-5721: Carry original episode refs through final packed exposure

**Feature**: FEAT-903 — Cross-scope episodic citations and reviews
**Spec**: `sdd/specs/episodic-store-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5720
**Assigned-to**: unassigned
**Discovered-from**: `issue:33b9921c84ac`

## Context

The owner chose original episode namespace with request visibility, and a separate
follow-up feature after PR #2139. Implement this module of approved FEAT-903.

## Scope

Carry original episode refs through final packed exposure. Follow the file-specific blueprint below. Preserve canonical/dedupe
encodings and requesting signal scope. No dependencies, migrations, brain review
expansion, or toolkit exposure changes.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/models.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/unified/context.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY |
| `packages/ai-parrot/tests/memory/dynamics/test_attribution.py` | MODIFY |
| `packages/ai-parrot/tests/memory/unified/test_context.py` | MODIFY |
| `packages/ai-parrot/tests/memory/unified/test_manager_real_store.py` | MODIFY |

## Codebase Contract (Anti-Hallucination)

Verified at 33637365e4 and rechecked at task authoring. The spec §6 records
imports and exact source locations. Existing methods cite/review keep their
signatures and interpret namespace as trusted requester scope. The existing
visible_to_scope and recall_scopes implement the accepted access policy.

### Verified Imports

```python
from parrot.memory.episodic.visibility import recall_scopes, visible_to_scope
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.dynamics.models import MemoryRef, MemoryCitation, MemoryExposure, ReviewCommand, ReviewSignal
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.unified.models import MemoryCandidate, MemoryContext
```

### Does NOT Exist

No typed original ref fields before TASK-5721; no async commit_memory_exposure;
no need for a new dynamics identity encoding or schema migration.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_attribution.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_manager_real_store.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Blueprint

### Steps (in order)

1. Recheck declared anchors and imports; use spec §2 as the semantic contract.
2. Apply the per-file changes below, preserving exact requester provenance.
3. Exercise acceptance cases using real SQLite persistence where state is asserted.
4. Run validation, black and ruff on changed Python files before committing.

### `packages/ai-parrot/src/parrot/memory/unified/models.py` (MODIFY)

```text
Anchor: class MemoryCandidate(BaseModel):
Verified: packages/ai-parrot/src/parrot/memory/unified/models.py:18; occurrences: 1
```

Add optional memory_ref: MemoryRef to MemoryCandidate and memory_refs: tuple[MemoryRef, ...] to MemoryContext. Reject non-episodic, mismatched ID/version/kind/source and invisible candidate refs. Preserve request scope.

### `packages/ai-parrot/src/parrot/memory/unified/context.py` (MODIFY)

```text
Anchor:     def assemble_candidates(
Verified: packages/ai-parrot/src/parrot/memory/unified/context.py:124; occurrences: 1
```

Collect original refs only for candidates whose complete text enters the token budget. Include typed refs in MemoryContext, preserving delivered order. Never collect dropped or non-episodic candidates.

### `packages/ai-parrot/src/parrot/memory/unified/manager.py` (MODIFY)

```text
Anchor:     def commit_memory_exposure(
Verified: packages/ai-parrot/src/parrot/memory/unified/manager.py:240; occurrences: 1
```

Create original refs from returned episode dimensions; source episodic for every visible episode. Replace namespace reconstruction in _delivered_memory_ref with typed-ref lookup; require delivered token match, episode kind/version, visibility and dedupe. Pass request namespace to review for mixed citations. No typed ref means no exposure credit.

### `packages/ai-parrot/tests/memory/dynamics/test_attribution.py` (MODIFY)

```text
Anchor: def test_final_packing_controls_citable_refs()
Verified: packages/ai-parrot/tests/memory/dynamics/test_attribution.py:116; occurrences: 1
```

Update synthetic reviewable candidate fixtures to include original typed refs. Test full delivered-ref equality including model_id, missing typed refs and mixed-scope trusted tool review.

### `packages/ai-parrot/tests/memory/unified/test_context.py` (MODIFY)

```text
Anchor: class TestContextAssembler:
Verified: packages/ai-parrot/tests/memory/unified/test_context.py:46; occurrences: 1
```

Test original refs survive packing only with corresponding complete content, while dropped, mismatched and non-episodic refs cannot enter the manifest.

### `packages/ai-parrot/tests/memory/unified/test_manager_real_store.py` (MODIFY)

```text
Anchor: async def test_only_exact_scope_episodes_enter_the_review_manifest(
Verified: packages/ai-parrot/tests/memory/unified/test_manager_real_store.py:172; occurrences: 1
```

Replace context-only expectation with all visible original refs. Cover cross-session and agent-level final exposure, mixed cite/review using real SQLite when durable updates are asserted, optional filters and anonymous isolation.

### FILL IN checklist

- [ ] Implement every file-specific change and complete behavioral tests.
- [ ] Keep all visibility checks fail-closed without changing canonical/dedupe bytes.
- [ ] Preserve existing negative tests unless their old exact-request rule is explicitly superseded.

## Acceptance Criteria

- [ ] All declared file responsibilities are implemented.
- [ ] Request/recording identity separation preserves isolation, provenance and replay.
- [ ] Scoped tests and configured lint/format checks pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_attribution.py -q`
- `pytest packages/ai-parrot/tests/memory/unified/test_context.py -q`
- `pytest packages/ai-parrot/tests/memory/unified/test_manager_real_store.py -q`

## Test Specification

Use the existing fixtures in the declared tests. Verify positive same-user and
agent-level cases alongside foreign principals, anonymous sessions, optional
filters, full-reference mismatch, dropped content and durable replay as applicable.
Do not add live API calls. Documentation also runs `parrot sdd techwiki check
--spec sdd/specs/episodic-store-fixes.spec.md --root .`.

## Agent Instructions

Work only in the provisioned FEAT-903 worktree and only on declared files.
Use worktree source on PYTHONPATH. Commit implementation, record semantic review
and real validation evidence, then finalize through `parrot sdd task finalize`.

## Completion Note

- Task: TASK-5721
- Feature: episodic-store-fixes
- Implementation SHA: 25515ed86288ae58e9692687ce7b0b1a72fe1101
- Closed at (UTC): 2026-11-16T12:45:14+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| semantic_review | Reviewed typed original refs through complete candidate packing, final delivered-token membership, full-ref equality and requester-scoped mixed reviews. 44 tests passed, including real mixed-scope tool failure; black and ruff passed. Independent feature review pending. |
| tests | 44 passed |
