# TASK-5720: Preserve episode identity through visible citation and review admission

**Feature**: FEAT-903 — Cross-scope episodic citations and reviews
**Spec**: `sdd/specs/episodic-store-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:33b9921c84ac`

## Context

The owner chose original episode namespace with request visibility, and a separate
follow-up feature after PR #2139. Implement this module of approved FEAT-903.

## Scope

Preserve episode identity through visible citation and review admission. Follow the file-specific blueprint below. Preserve canonical/dedupe
encodings and requesting signal scope. No dependencies, migrations, brain review
expansion, or toolkit exposure changes.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/models.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY |
| `packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py` | MODIFY |
| `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` | MODIFY |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY |

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
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py",
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

### `packages/ai-parrot/src/parrot/memory/dynamics/models.py` (MODIFY)

```text
Anchor: class ReviewCommand(BaseModel):
Verified: packages/ai-parrot/src/parrot/memory/dynamics/models.py:393; occurrences: 1
```

For episode refs use visible_to_scope(ref.namespace, signal.scope); keep brain validation and dedupe encoder unchanged. In MemoryCitation.merged_with allow mixed episode namespaces only within one tenant/agent; reject duplicate canonical keys with unequal full refs, preserve order and cardinality.

### `packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py` (MODIFY)

```text
Anchor: def validate_citation(
Verified: packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py:172; occurrences: 1
```

Require full ref equality with a delivered manifest member and visible_to_scope for episode refs. Preserve exact exposure scope and exposure ID; retain brain rules.

### `packages/ai-parrot/src/parrot/memory/episodic/store.py` (MODIFY)

```text
Anchor:     async def cite(
Verified: packages/ai-parrot/src/parrot/memory/episodic/store.py:458; occurrences: 1
```

Resolve via recall_scopes(namespace), using build_filter(null_dimensions=...) and targeted get_by_ids, or scoped count/get_recent fallback. Recheck visible_to_scope. Construct each ref from all stored episode dimensions. Keep signal-to-request namespace comparison exact; admit cited visible refs, verify them against current stored refs before review, and invalidate successfully changed recorded scopes plus request scope.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` (MODIFY)

```text
Anchor:                 latest_cursor = await database.execute(
Verified: packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py:428; occurrences: 1
```

Extend the MAX(outcome_revision) lookup with NULL-safe json_extract(payload, signal.scope dimension) comparisons for tenant_id, agent_id, user_id, session_id. Keep exact episode/ref check and dedupe unchanged; no schema change.

### `packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py` (MODIFY)

```text
Anchor: def test_synthetic_and_forged_scope_rejected()
Verified: packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py:67; occurrences: 1
```

Add visible prior-session/agent refs, anonymous and narrowing rejection, unchanged canonical key and mixed citation conflict tests. Preserve brain rejection.

### `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` (MODIFY)

```text
Anchor: async def test_cite_does_not_reinforce(
Verified: packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py:92; occurrences: 1
```

Add SQLite mixed-scope cite/review, two sessions sharing state, full-ref mismatch rejection, unchanged signal provenance, restart duplicate replay and denied foreign/anonymous scopes. Update tests whose exact-request assumption is explicitly superseded.

### `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` (MODIFY)

```text
Anchor: async def test_apply_review_requires_exact_episode_scope(
Verified: packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py:722; occurrences: 1
```

Add independent same-outcome-ID reviews from distinct request scopes; retain stale revision rejection within one request scope and exact recorded episode checks.

### FILL IN checklist

- [ ] Implement every file-specific change and complete behavioral tests.
- [ ] Keep all visibility checks fail-closed without changing canonical/dedupe bytes.
- [ ] Preserve existing negative tests unless their old exact-request rule is explicitly superseded.

## Acceptance Criteria

- [ ] All declared file responsibilities are implemented.
- [ ] Request/recording identity separation preserves isolation, provenance and replay.
- [ ] Scoped tests and configured lint/format checks pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py -q`
- `pytest packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py -q`
- `pytest packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py -q`

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

- Task: TASK-5720
- Feature: episodic-store-fixes
- Implementation SHA: db9ffedb75efa3a1f863dd5c7f7aba1f0a03c7d6
- Closed at (UTC): 2026-11-16T12:32:10+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| black | passed |
| identity | Original refs and caller signal scope retained; cross-session SQLite replay verified |
| ruff | passed |
| tests | 46 passed |
