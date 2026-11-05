---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [decision-audit, wiki, snapshot, ledger-fix]
---

# Feature Specification: A hashless ADR page fails the snapshot closed, and the manifest no longer depends on the stored envelope shape

**Feature ID**: FEAT-810
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.0

Source: ledger `issue:c7f16ecf903e` (minor, bug) and `issue:d219d0707031` (low, tech_debt), both
discovered from `review:TASK-5204`. Authored by `/sdd-fix` (SDD lane, group `fixgroup:100d290c57f5`).

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-807 (PR #1959) made `InventorySnapshot.take` compare the hash the store held at the first read
with the hash it holds at the second read, so a legacy envelope no longer blocks the decision gate.
Two consequences of that change were found in the code review of TASK-5204.

**B1 — a hashless page is invisible to the stability check (`issue:c7f16ecf903e`, minor, bug).**
`inventory_with_hashes()` returns `page.get("content_hash")`, which is `None` when the page row stores
no hash (`repository.py:90`). `BaseWikiStore.page_hashes` / `SQLiteWikiStore.page_hashes` also return
`None` for an **absent** row (`store.py:1242-1257`, `store.py:2785-2807`). So for a hashless ADR page
phase one yields `None` and phase two yields `None` whether the page was rewritten, or deleted
outright, between the two reads — `stored == await store.page_hashes(...)` holds and the snapshot
silently includes a record that may no longer exist. Before FEAT-807 the phase-one value was
`record_hash(record)`, which is never `None`, so a hashless page always raised `SNAPSHOT_UNSTABLE`:
the gate failed closed. No supported writer produces one (`DecisionRepository.save` always goes
through `decision_to_page`, which sets `content_hash`), so this needs an out-of-band page — but a
consistency gate must not depend on that.

**B2 — the manifest carries the stored legacy hash (`issue:d219d0707031`, low, tech_debt).**
`SnapshotManifest.inventory` is built as `content_hash or record_hash(record)` (`inventory.py:110`),
so for a page with a legacy envelope it holds the stored **legacy** hash. When the FEAT-808 ingest
later rewrites that page to its canonical envelope the stored hash changes, the manifest changes, the
`input_digest` changes, and every spec rendered in between reports stale generated sections (exit 3)
and must be re-rendered and re-committed. The same manifest also differs between a clone holding
legacy pages and one holding canonical pages until the first clone runs a full ingest. The digest
should describe the *decisions*, not the envelope encoding they happen to be stored in.

### Goals

- **G1** — A decision page whose stored hash is `None` in phase one fails the snapshot closed with
  `SNAPSHOT_UNSTABLE`, naming the pages, instead of comparing `None` with `None`.
- **G2** — `SnapshotManifest.inventory` is derived from the decoded records alone, so it is identical
  for a legacy and a canonical page of the same decision, and unchanged by the FEAT-808 rewrite.
- **G3** — For a plane whose pages are all canonical the manifest is byte-identical to today's, so no
  rendered spec becomes stale on this change.
- **G4** — The FEAT-807 stability check itself is untouched: it still compares **stored** hashes, so an
  unchanged legacy envelope still produces a snapshot (`issue:5918ff019737` does not regress).

### Non-Goals (explicitly out of scope)

- Rewriting legacy envelopes during ingest — FEAT-808, merged in PR #1960.
- Changing `DecisionRepository.inventory_with_hashes()`, the codec, `DecisionRecord`, or the
  `SNAPSHOT_UNSTABLE` code.
- Making `page_hashes` distinguish "absent row" from "row with a null hash" — that is a store-level
  change with many callers; this spec fails closed on the ambiguity instead of resolving it.
- Backfilling `content_hash` on existing pages.

---

## Governing Decisions

<!-- decision-audit: not evaluated at authoring time; `/sdd-done` renders this section -->

## 2. Architectural Design

### Overview

Two edits inside `InventorySnapshot.take`, nothing else in `src/`.

The stability gate gains a precondition: any decision whose phase-one stored hash is `None` makes the
read unverifiable, and an unverifiable read is `SNAPSHOT_UNSTABLE`. The check runs before the
phase-two comparison so the error names the real cause ("no stored content hash") rather than a
mismatch that would not occur.

The manifest comprehension stops reading `content_hash` and uses `record_hash(record)` for every
decision. `record_hash` is the sha1 of `canonical_json(record)` — a function of the decoded record, so
it is the same whichever envelope the record came out of. G3 holds because `decision_to_page` stores
exactly `sha1(canonical envelope)` and, for a canonical page, that equals `record_hash(record)`; the
FEAT-807 test `test_snapshot_manifest_unchanged_for_canonical_pages` already asserts this equality.

### Component Diagram

```
repo.inventory_with_hashes() ──► [(record, stored content_hash | None)]
                                        │
                     ┌──────────────────┴───────────────────┐
                     ▼                                      ▼
  stability gate (stored hashes only)            manifest (records only)
   any hash is None ──► SNAPSHOT_UNSTABLE         inventory = {id: record_hash(record)}
   page_hashes(ids) != stored ──► SNAPSHOT_UNSTABLE
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `InventorySnapshot.take` | modifies | new hashless precondition; manifest comprehension |
| `SnapshotManifest.inventory` | unchanged type | still `dict[str, str]`; now always `record_hash` |
| `DecisionRepository.inventory_with_hashes` | unchanged | still returns `str \| None` per page |
| `BaseWikiStore.page_hashes` | unchanged | still `None` for absent **and** hashless rows |

### Data Models

No model changes.

### New Public Interfaces

None. `take()` keeps its signature and its return type.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Fail-closed hashless gate | yes | the exact edit and error message are fixed below | — |
| M2: Envelope-independent manifest | yes | the exact comprehension is fixed below | — |

### Module 1: Fail-closed hashless gate
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py`,
  `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py`,
  `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py`
- **Responsibility**: refuse a snapshot it cannot verify (`issue:c7f16ecf903e`).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # inventory.py — inside InventorySnapshot.take, between the `stored` map (verified: inventory.py:100)
  # and the phase-two comparison (verified: inventory.py:104):
  unverifiable = sorted(decision_id for decision_id, content_hash in stored.items() if content_hash is None)
  if unverifiable:
      raise DecisionError(
          SNAPSHOT_UNSTABLE,
          "decision pages have no stored content hash, so a mid-read change cannot be detected: "
          + ", ".join(unverifiable),
      )
  # the existing phase-two comparison is unchanged (verified: inventory.py:104-105)
  ```

### Module 2: Envelope-independent manifest
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py`,
  `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py`
- **Responsibility**: make `SnapshotManifest.inventory` a function of the records (`issue:d219d0707031`).
- **Depends on**: M1 (same function, adjacent lines — sequential, same worktree)
- **Interface Skeleton**:
  ```python
  # inventory.py — SnapshotManifest(...) (verified: inventory.py:109-116)
  inventory={record.decision_id: record_hash(record) for record, _content_hash in pairs},
  # the comment at inventory.py:98-99 is extended to say the stored hashes are the stability
  # check's input only, and that the manifest deliberately uses the decoded record.
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_snapshot_unstable_when_a_page_has_no_stored_hash` | M1 | a page upserted with `content_hash=None` raises `SNAPSHOT_UNSTABLE`, and the message names the decision id |
| `test_snapshot_unstable_when_a_hashless_page_disappears_mid_read` | M1 | the regression the ledger asks for: a hashless page deleted between the two reads raises instead of being included |
| `test_inventory_delegates_to_inventory_with_hashes` (existing, strengthened) | M1 | several records **plus one malformed page**: `inventory()` equals the records of `inventory_with_hashes()` in the same order, and `last_diagnostics` is the same through both methods |
| `test_snapshot_manifest_is_independent_of_the_stored_envelope` | M2 | a legacy page and a canonical page of the same record give the same `manifest.inventory` value |
| `test_snapshot_stable_with_legacy_envelope` (existing, updated) | M2 | still a snapshot, but the manifest now holds `record_hash(record)`, not `legacy.content_hash` |
| `test_snapshot_manifest_unchanged_for_canonical_pages` (existing) | M2 | unchanged and still passing — this is G3 |
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
# Reuse, all verified: adr_store (tests/knowledge/wiki/decisions/conftest.py), _record (test_inventory.py:36),
# _snapshot (test_inventory.py:57), _legacy_page (test_inventory.py:150), record_hash (inventory.py:37).
def _hashless_page(record: DecisionRecord) -> WikiPageRecord:
    """decision_to_page(record) with content_hash cleared — the out-of-band page B1 needs."""
    return decision_to_page(record).model_copy(update={"content_hash": None})
```

---

## 5. Acceptance Criteria

- [ ] An ADR page stored without a `content_hash` makes `InventorySnapshot.take` raise
  `DecisionError(SNAPSHOT_UNSTABLE, ...)`, and the message names the offending decision id.
- [ ] A hashless page deleted between the two reads raises instead of appearing in `snapshot.eligible`.
- [ ] `SnapshotManifest.inventory[decision_id] == record_hash(record)` for every decision, whatever
  envelope its page holds.
- [ ] For a plane of canonical pages the manifest is byte-identical to the pre-change manifest
  (`test_snapshot_manifest_unchanged_for_canonical_pages` passes unmodified).
- [ ] An unchanged **legacy** envelope still yields a snapshot — FEAT-807 does not regress.
- [ ] `test_inventory_delegates_to_inventory_with_hashes` establishes ordering and diagnostics parity
  over several records including a malformed page.
- [ ] Every test in the Validation Contract passes.
- [ ] No change to any public signature in `parrot.knowledge.wiki.decisions`.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, record_hash   # verified: decisions/inventory.py:64, :37
from parrot.knowledge.wiki.decisions.repository import DecisionRepository              # verified: decisions/repository.py (class), imported at decisions/inventory.py:22
from parrot.knowledge.wiki.decisions.codec import canonical_json, decision_to_page     # verified: decisions/inventory.py:11, tests/.../test_inventory.py:13
from parrot.knowledge.wiki.decisions.models import SNAPSHOT_UNSTABLE, DecisionError, DecisionRecord  # verified: decisions/inventory.py:14, :17, :18
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord                  # verified: decisions/inventory.py:24, tests/.../test_inventory.py:27
```

### Existing Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py
def record_hash(record: DecisionRecord) -> str                                   # line 37 — sha1(canonical_json(record))
class SnapshotManifest(_Strict):                                                 # line 42 — inventory: dict[str, str] (line 45)
class InventorySnapshot:                                                         # line 64
    @classmethod
    async def take(cls, repo, taxonomy, approvals, adapter, structural_revision, *,
                   store, root, config_digest) -> "InventorySnapshot"            # line 80
    #   pairs = await repo.inventory_with_hashes()                               # line 95
    #   stored = {record.decision_id: content_hash for record, content_hash in pairs}   # line 100
    #   if await store.page_hashes(sorted(stored)) != stored: raise DecisionError(SNAPSHOT_UNSTABLE, …)  # line 104-105
    #   manifest = SnapshotManifest(inventory={... content_hash or record_hash(record) ...}, …)          # line 109-116

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
async def inventory_with_hashes(self) -> list[tuple[DecisionRecord, str | None]]  # line 63 — hash is page.get("content_hash") (line 90)
async def inventory(self) -> list[DecisionRecord]                                 # line 98 — delegates (line 105)
self.last_diagnostics: list[DecisionDiagnostic]                                   # line 43, reset at line 75

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]   # BaseWikiStore line 1242; SQLiteWikiStore line 2785
#   both return None for an absent row AND for a row whose content_hash is NULL
```

### Does NOT Exist (Anti-Hallucination)

- ~~a `SNAPSHOT_HASHLESS` / `ADR_HASH_MISSING` diagnostic code~~ — reuse `SNAPSHOT_UNSTABLE`.
- ~~`store.page_exists` / a `page_hashes` variant distinguishing absent from null~~ — not in `store.py`.
- ~~a `content_hash` attribute on `DecisionRecord`~~ — the hash lives on the page row only.
- ~~`_hashless_page` in the test suite~~ — created by this spec; `_legacy_page` exists (`test_inventory.py:150`).

### Edit Sites (Blueprint Anchors)

Verified against: `a144035e8d`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | MODIFY | `        if await store.page_hashes(sorted(stored)) != stored:` | `inventory.py:104` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | MODIFY | `            inventory={record.decision_id: content_hash or record_hash(record) for record, content_hash in pairs},` | `inventory.py:110` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` | MODIFY | `async def test_snapshot_stable_with_legacy_envelope(adr_store, tmp_path) -> None:` | `test_inventory.py:162` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` | MODIFY | `    async def test_inventory_delegates_to_inventory_with_hashes(self, store, record):` | `test_repository.py:188` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Fail closed: a gate that cannot verify its input refuses, it does not assume.
- The stability check reads **stored** hashes (FEAT-807, `issue:5918ff019737`); the manifest reads
  **records**. Keep the two sources distinct and say so in the comment at `inventory.py:98-99`.

### Known Risks / Gotchas

- `test_snapshot_stable_with_legacy_envelope` (`test_inventory.py:172`) asserts
  `snapshot.manifest.inventory == {"adr:doc:legacy": legacy.content_hash}`. M2 changes that value to
  `record_hash(record)` — the assertion must be updated, not deleted, and the test must still prove
  the snapshot succeeds (G4).
- `test_snapshot_manifest_unchanged_for_canonical_pages` (`test_inventory.py:175`) must pass
  **unmodified**; if it needs editing, G3 is broken and the change is wrong.
- `_legacy_page` keeps `content_hash` set, so it is unaffected by M1.
- `adr_store.upsert_pages` is what writes a page out-of-band; `repo.save` always sets a hash.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none |

---

## 8. Open Questions

- [x] Diagnostic or hard failure for a hashless page? — *Resolved in this spec*: hard failure with
  `SNAPSHOT_UNSTABLE`, restoring the pre-FEAT-807 fail-closed behaviour. A diagnostic would let the
  gate pass on a read it could not verify.
- [x] Document B2 or fix it? — *Resolved in this spec*: fix it. `record_hash` for every page costs
  nothing, removes the one-off staleness and the clone-to-clone divergence, and keeps G3.

---

## 9. Design Research Cross-Check

> Status: skipped (ledger-driven fix authored by `/sdd-fix`; no exploration document)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-810.
- **Module dependency graph**: M1 → M2 (same function, adjacent lines; strictly sequential).
- **Shared files**: `decisions/inventory.py` is also the subject of FEAT-807, already merged (PR #1959).
  No open feature touches it.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-05 | Jesus Lara (with Claude) | Authored by `/sdd-fix` from `issue:c7f16ecf903e` and `issue:d219d0707031` |
