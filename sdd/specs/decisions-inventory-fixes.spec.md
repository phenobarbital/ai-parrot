---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [decision-audit, wiki, snapshot, ledger-fix]
---

# Feature Specification: Decision snapshot compares stored hashes, so a legacy ADR envelope no longer blocks the gate

**Feature ID**: FEAT-807
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.0

Source: ledger `issue:5918ff019737` (major, bug), discovered from `spec:FEAT-805`. Authored by `/sdd-fix`
(SDD lane, group `fixgroup:297f100e9e39`).

---

## 1. Motivation & Business Requirements

### Problem Statement

`InventorySnapshot.take` decides whether the decision inventory changed between its two reads by
comparing `record_hash(record)` — the sha1 of the record **re-encoded with the current model** — with
`store.page_hashes()`, the `content_hash` stored when the envelope was written. An ADR page written by
an older codec (an envelope without the fields FEAT-784 added) decodes to a record that re-encodes with
those fields at their defaults, so the two hashes never match.

The result is `SNAPSHOT_UNSTABLE: decision inventory changed while reading`, exit 3, for **every** spec
on that plane — `parrot sdd spec consequences`, `wikitoolkit spec governing` and the
`wiki_spec_consequences` MCP tool — although nothing changed. Reproduced on 2026-11-05 on the main
ai-parrot checkout: 9 of 9 `adr:doc:*` seed pages, written 2026-11-01 before the v2 model reached `dev`;
`sha1(stored envelope) == content_hash` held for all 9 and re-encoding added exactly 11 keys.

### Goals

- **G1** — The stability check compares what was stored at the first read with what is stored at the
  second read. A page that did not change is never reported as changed, whatever codec wrote it.
- **G2** — A real change between the two reads is still reported as `SNAPSHOT_UNSTABLE`.
- **G3** — For a plane whose pages are all canonical, the snapshot manifest is byte-identical to
  today's, so no rendered spec becomes stale.

### Non-Goals (explicitly out of scope)

- Rewriting legacy envelopes during ingest — `issue:42977fa3aaeb`, FEAT-808
  (`sdd/specs/decisions-ingest-fixes.spec.md`).
- Changing the `SNAPSHOT_UNSTABLE` message, the codec, or `DecisionRecord`.
- Changing the return type of `DecisionRepository.inventory()` (nine production and test call sites).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:e9593ff4030311b1cdd1831b92f8871c27cbe4bae21ed7699c2653697ad5e7a5 evaluation_digest=sha256:40a858ec7f8457ccfd94b5eac94e743355c3a09a93c659c050823c086c4237f9 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

`DecisionRepository` gains `inventory_with_hashes()`, which returns each decoded record together with
the `content_hash` of the page it was decoded from — the same pairing `get()` already returns for one
record. `inventory()` keeps its signature and delegates to it.

`InventorySnapshot.take` reads the pairs, builds its phase-one hash map from the **stored** hashes, and
compares that map with `store.page_hashes()` exactly as today. The snapshot manifest records, per
decision, the stored hash, falling back to `record_hash(record)` only when the page has no stored hash.
For a canonical page the stored hash equals `record_hash(record)`, which is why G3 holds.

### Component Diagram

```
DecisionRepository.inventory_with_hashes() ──► [(record, stored content_hash)]
        │                                              │
        └─► inventory()  (unchanged signature)         ▼
                                      InventorySnapshot.take: phase-one map = stored hashes
                                                       │
                                      store.page_hashes(ids)  ── differs ──► SNAPSHOT_UNSTABLE
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DecisionRepository.inventory` | modifies | delegates to the new method; same result |
| `InventorySnapshot.take` | modifies | phase-one map from stored hashes |
| `SnapshotManifest.inventory` | unchanged type | `dict[str, str]`; stored hash, else `record_hash` |

### Data Models

No model changes.

### New Public Interfaces

```python
class DecisionRepository:
    async def inventory_with_hashes(self) -> list[tuple[DecisionRecord, str | None]]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Stored-hash snapshot | yes | method name, return type, the two edits in `take()` and the manifest fallback are fixed below | — |

### Module 1: Stored-hash snapshot
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py`
- **Responsibility**: pair each record with its stored page hash; use that hash in the stability check.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # repository.py
  class DecisionRepository:  # verified: repository.py:26
      async def inventory_with_hashes(self) -> list[tuple[DecisionRecord, str | None]]:
          """Load the complete bounded ADR inventory with each page's stored ``content_hash``.

          Same bound, same skip of a page deleted mid-read and same ``last_diagnostics`` handling as
          ``inventory()`` today (verified: repository.py:63-94). The hash is ``page.get("content_hash")``,
          as in ``get()`` (verified: repository.py:45-61).

          Raises:
              DecisionError: ``ADR_INVENTORY_LIMIT`` when the plane holds more than ``max_records`` ADR pages.
          """

      async def inventory(self) -> list[DecisionRecord]:  # verified: repository.py:63 — signature unchanged
          """The records of ``inventory_with_hashes()``."""

  # inventory.py — InventorySnapshot.take (verified: inventory.py:80-114)
  #   :95  pairs = await repo.inventory_with_hashes(); records = [record for record, _ in pairs]
  #   :97  stored = {record.decision_id: content_hash for record, content_hash in pairs}
  #   :101 if await store.page_hashes(sorted(stored)) != stored: raise DecisionError(SNAPSHOT_UNSTABLE, …)   # message unchanged
  #   :107 SnapshotManifest(inventory={record.decision_id: content_hash or record_hash(record) for record, content_hash in pairs}, …)
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_inventory_with_hashes_pairs_stored_hash` | M1 | every pair's hash equals `store.page_hashes()` for that id |
| `test_inventory_delegates_to_inventory_with_hashes` | M1 | same records, same order, same diagnostics |
| `test_snapshot_stable_with_legacy_envelope` | M1 | a page whose envelope lacks the schema-2 keys (hash = sha1 of that envelope) yields a snapshot, not `SNAPSHOT_UNSTABLE`, and the record is in the inventory |
| `test_snapshot_manifest_unchanged_for_canonical_pages` | M1 | for pages saved through `repo.save`, `manifest.inventory[id] == record_hash(record)` |
| `test_snapshot_unstable_is_incomplete` (existing) | M1 | a changed phase-two hash still raises |

### Integration Tests

| Test | Description |
|---|---|
| `test_consequences.py` (existing) | the consequence service still evaluates and renders over a stored inventory |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences.py
markers: none

### Test Data / Fixtures

```python
# Reuse: adr_store (tests/knowledge/wiki/decisions/conftest.py:191), _record / _snapshot (test_inventory.py:36, :55).
def _legacy_page(record: DecisionRecord) -> WikiPageRecord:
    """decision_to_page(record) with the schema-2 keys removed from the envelope and content_hash = sha1(envelope)."""
```

---

## 5. Acceptance Criteria

- [ ] A plane holding an ADR page written without the schema-2 fields produces a snapshot; the decision
  gate no longer reports `SNAPSHOT_UNSTABLE` for it.
- [ ] A page whose stored hash differs between the two reads still raises `SNAPSHOT_UNSTABLE`.
- [ ] For canonical pages the manifest inventory equals today's (`record_hash`).
- [ ] `DecisionRepository.inventory()` returns the same list as before for every existing caller.
- [ ] Every test in the Validation Contract passes.
- [ ] No breaking change to the public API of `parrot.knowledge.wiki.decisions`.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.repository import DecisionRepository        # verified: decisions/repository.py:26
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, record_hash  # verified: decisions/inventory.py:64, :37
from parrot.knowledge.wiki.decisions.codec import canonical_json, decision_to_page, decision_from_page  # verified: decisions/codec.py:55, :180, :212
from parrot.knowledge.wiki.decisions.models import SNAPSHOT_UNSTABLE, DecisionError, DecisionRecord     # verified: tests/.../test_inventory.py:13-22
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord            # verified: tests/.../test_inventory.py:25
```
Paths below are under `packages/ai-parrot/src/parrot/knowledge/wiki/`.

### Existing Class Signatures

```python
# decisions/repository.py
class DecisionRepository:                                                        # line 26
    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None  # line 29
    last_diagnostics: list[DecisionDiagnostic]                                   # line 43
    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None   # line 45 — returns page.get("content_hash")
    async def inventory(self) -> list[DecisionRecord]                            # line 63
    #   stubs = await self._store.list_pages(category=ADR_CATEGORY, limit=self._max_records + 1)   # line 74
    #   page = await self._store.get_page(concept_id, include_body=True)         # line 83
    async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord   # line 96

# decisions/inventory.py
def record_hash(record: DecisionRecord) -> str                                   # line 37 — sha1(canonical_json(record))
class SnapshotManifest(_Strict):                                                 # line 42 — inventory: dict[str, str]
class InventorySnapshot:                                                         # line 64
    @classmethod
    async def take(cls, repo, taxonomy, approvals, adapter, structural_revision, *, store, root, config_digest)   # line 80
    #   records = await repo.inventory()                                         # line 95
    #   hashes = {record.decision_id: record_hash(record) for record in records} # line 97
    #   if await store.page_hashes(sorted(hashes)) != hashes:                    # line 101

# decisions/codec.py
def canonical_json(record: DecisionRecord) -> str                                # line 55
def decision_to_page(record: DecisionRecord) -> WikiPageRecord                   # line 180 — content_hash=_sha1(envelope) (line 208)
def decision_from_page(page: dict[str, Any]) -> DecisionRecord                   # line 212

# store.py
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]  # SQLiteWikiStore, line 2785
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `inventory_with_hashes` | `InventorySnapshot.take` | call replacing `repo.inventory()` | `decisions/inventory.py:95` |
| `inventory_with_hashes` | `inventory` | delegation | `decisions/repository.py:63` |

### Does NOT Exist (Anti-Hallucination)

- ~~`DecisionRepository.inventory_with_hashes`~~ — created by this spec.
- ~~a `content_hash` attribute on `DecisionRecord`~~ — the hash lives on the page row only.
- ~~`DecisionRepository.page_hashes`~~ — `page_hashes` is a store method.

### Edit Sites (Blueprint Anchors)

Verified against: `1151c46c92`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py` | MODIFY | `    async def inventory(self) -> list[DecisionRecord]:` | `repository.py:63` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | MODIFY | `        records = await repo.inventory()` | `inventory.py:95` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | MODIFY | `        hashes = {record.decision_id: record_hash(record) for record in records}` | `inventory.py:97` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` | MODIFY | `async def test_snapshot_unstable_is_incomplete(adr_store, tmp_path, monkeypatch) -> None:` | `test_inventory.py:119` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` | MODIFY | `class TestInventory:` | `test_repository.py:116` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pair a record with the hash to compare against, as `DecisionRepository.get()` does; never recompute a
  hash that the store already holds.
- Keep `inventory()` a thin delegate so its nine callers are untouched.

### Known Risks / Gotchas

- `test_snapshot_unstable_is_incomplete` monkeypatches `adr_store.page_hashes`; it must keep failing the
  snapshot after the change.
- A page with a null stored hash: the comparison uses `None` on both sides; only the manifest falls back
  to `record_hash`.
- The manifest digest must not move for canonical planes, or every rendered spec turns stale.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none |

---

## Consequences

<!-- decision-audit: input_digest=sha256:e9593ff4030311b1cdd1831b92f8871c27cbe4bae21ed7699c2653697ad5e7a5 evaluation_digest=sha256:40a858ec7f8457ccfd94b5eac94e743355c3a09a93c659c050823c086c4237f9 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/decisions-inventory-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: decision-audit, ledger-fix, snapshot
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
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "decision-audit",
      "ledger-fix",
      "snapshot"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/decisions-inventory-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:40a858ec7f8457ccfd94b5eac94e743355c3a09a93c659c050823c086c4237f9",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:e9593ff4030311b1cdd1831b92f8871c27cbe4bae21ed7699c2653697ad5e7a5",
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
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Change `inventory()`'s return type or add a method? — *Resolved in this spec*: add
  `inventory_with_hashes()`; nine call sites depend on the current return type.

---

## 9. Design Research Cross-Check

> Status: skipped (ledger-driven fix authored by `/sdd-fix`; no exploration document)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-807.
- **Module dependency graph**: one module, no edges.
- **Shared files**: none with FEAT-808 (that spec edits `decisions/ingest.py` and `test_ingest.py` only).
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none. FEAT-808 is independent and may merge in either order.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-05 | Jesus Lara (with Claude) | Authored by `/sdd-fix` from `issue:5918ff019737` |
