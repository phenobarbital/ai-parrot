# TASK-3228: Ledger event schema and deterministic identifiers

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The event model is the durable contract between lock-free log writers and the rebuildable materialized index.

## Scope

- Create the `ledger` package and Pydantic v2 event/payload models from spec §2.
- Implement canonical payload serialization plus deterministic SHA-1 `compute_event_id` and issue-deduplication ID helpers.
- Validate event kinds, issue status/severity values, and stable equal-input IDs.

**NOT in scope**: file writes, SQLite reductions, CLI parsing, or FEAT-557 store implementation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/__init__.py` | CREATE | Ledger package exports. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` | CREATE | Event models and identifiers. |
| `tests/knowledge/wiki/test_ledger_events.py` | CREATE | Schema/identifier tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# No ledger module exists. Spec §2 defines LedgerEvent and payload fields.
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.ledger`~~ — this task creates the package.
- ~~random UUID event identity~~ — IDs are deterministic SHA-1 prefixes.

## Acceptance Criteria

- [ ] Every literal event kind in spec §2 is represented and invalid values fail validation.
- [ ] Canonical payload serialization makes equal logical inputs produce equal IDs.
- [ ] Issue IDs are deterministic for the same kind, title, and discovery source.
- [ ] `pytest tests/knowledge/wiki/test_ledger_events.py -q` passes.

## Test Specification

Test timestamp/payload ordering determinism and validation failures without a ledger directory.

### Completion Note

Created the `parrot.knowledge.wiki.ledger` package with Pydantic v2 event/payload
models covering every literal event kind in spec §2, canonical payload
serialization, deterministic SHA-1 `compute_event_id`, and issue-deduplication
ID helpers. Verified: `pytest tests/knowledge/wiki/test_ledger_events.py -q` →
9 passed. No files touched outside the task's list.

Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 1 ·
Duration: 31.7s · Tokens: 189220/3039

