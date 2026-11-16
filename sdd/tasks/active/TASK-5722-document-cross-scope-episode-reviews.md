# TASK-5722: Document original episode identity and request-scoped review evidence

**Feature**: FEAT-903 — Cross-scope episodic citations and reviews
**Spec**: `sdd/specs/episodic-store-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-5720, TASK-5721
**Assigned-to**: unassigned
**Discovered-from**: `issue:33b9921c84ac`

## Context

The owner chose original episode namespace with request visibility, and a separate
follow-up feature after PR #2139. Implement this module of approved FEAT-903.

## Scope

Document original episode identity and request-scoped review evidence. Follow the file-specific blueprint below. Preserve canonical/dedupe
encodings and requesting signal scope. No dependencies, migrations, brain review
expansion, or toolkit exposure changes.

## Files to Create / Modify

| File | Action |
|---|---|
| `wiki/memory/agent-memory.md` | MODIFY |

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
      "path": "wiki/memory/agent-memory.md",
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

### `wiki/memory/agent-memory.md` (MODIFY)

```text
Anchor: ### Dynamics and Reviews
Verified: wiki/memory/agent-memory.md:201; occurrences: 1
```

Replace exact-request context-only claim with recorded identity plus request visibility. Explain mixed namespaces, caller provenance, shared state, unchanged keys, operator-only evidence tooling and anonymous/filter isolation.

### FILL IN checklist

- [ ] Implement every file-specific change and complete behavioral tests.
- [ ] Keep all visibility checks fail-closed without changing canonical/dedupe bytes.
- [ ] Preserve existing negative tests unless their old exact-request rule is explicitly superseded.

## Acceptance Criteria

- [ ] All declared file responsibilities are implemented.
- [ ] Request/recording identity separation preserves isolation, provenance and replay.
- [ ] Scoped tests and configured lint/format checks pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_documentation.py -q`

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
