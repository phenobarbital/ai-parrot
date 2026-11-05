---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [decision-audit, wiki, ingest, ledger-fix]
---

# Feature Specification: Decision ingest rewrites a stored ADR page whose envelope is not canonical

**Feature ID**: FEAT-808
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.0

Source: ledger `issue:42977fa3aaeb` (minor, bug), discovered from `spec:FEAT-805`. Authored by `/sdd-fix`
(SDD lane, group `fixgroup:d16f5f59ec73`).

---

## 1. Motivation & Business Requirements

### Problem Statement

`_persist_if_changed` skips the write when `content_fingerprint(existing) == content_fingerprint(record)`.
The fingerprint covers the decision's content, not the shape of its stored envelope, so a page written
by an older codec — an envelope without fields the current `DecisionRecord` adds with defaults — is
counted as unchanged on every refresh. `wikitoolkit build` and `wikitoolkit upsert --changed` leave it
as it is. On 2026-11-05 a full `wikitoolkit build` on the main ai-parrot checkout left 9 such
`adr:doc:*` pages untouched, and the decision gate kept failing until they were re-saved by hand.

### Goals

- **G1** — A refresh rewrites a stored ADR page whose stored hash is not the hash of its record under
  the current codec, even when its content fingerprint is unchanged.
- **G2** — The rewrite keeps everything the stored record holds (revision, review history, links); it
  is the stored record re-encoded, not the freshly parsed one.
- **G3** — The rewrite is idempotent: the next refresh counts the page as unchanged.

### Non-Goals (explicitly out of scope)

- The snapshot stability check — `issue:5918ff019737`, FEAT-807
  (`sdd/specs/decisions-inventory-fixes.spec.md`).
- Pages a refresh does not visit (spec-authored and candidate decisions); only documented ADR sources
  go through `_persist_if_changed`.
- A migration command or a bulk rewrite outside the refresh.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:94234c839b1df450c499df2f2a0a6db54d698466cc9d6aee8656f0bfd36202d7 evaluation_digest=sha256:5c650e4d4a08b4831797bdb4081d11b79213d079ed6285e52e6d9d097191cd1e rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

In `_persist_if_changed`, the fingerprint-equal branch gains one check before it counts the record as
unchanged: the stored hash returned by `repo.get()` is compared with the `content_hash` that
`decision_to_page(existing_record)` produces today. When they differ the stored record is saved back
with `repo.save(existing_record, stored_hash)` — a compare-and-swap against the hash just read — and
counted in `SyncResult.updated`. When they match, behaviour is exactly today's.

A `DecisionError` from encoding or saving (record too large, revision conflict, read-only plane) is
appended to `SyncResult.diagnostics`, as the existing save path already does, and the record is not
counted as updated.

### Component Diagram

```
refresh_decisions ──► _persist_if_changed(repo, record, result)
                           │ existing = repo.get(id)  → (stored record, stored hash)
                           ├─ fingerprint differs ─────────────► repo.save(record, stored hash)        (today)
                           └─ fingerprint equal
                                 ├─ stored hash == canonical hash ─► result.unchanged += 1             (today)
                                 └─ stored hash != canonical hash ─► repo.save(stored record, stored hash); result.updated += 1
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `_persist_if_changed` | modifies | one extra branch |
| `decision_to_page` | uses | source of the canonical hash |
| `DecisionRepository.save` | uses | CAS write, unchanged |

### Data Models

No model changes. `SyncResult.updated` already exists.

### New Public Interfaces

None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Canonical-envelope rewrite | yes | branch condition, record saved, counters and error handling are fixed below | — |

### Module 1: Canonical-envelope rewrite
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py`
- **Responsibility**: rewrite a non-canonical stored envelope during a refresh.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # ingest.py
  from parrot.knowledge.wiki.decisions.codec import content_fingerprint, decision_to_page  # content_fingerprint verified: ingest.py:16

  async def _persist_if_changed(repo: DecisionRepository, record: DecisionRecord, result: SyncResult) -> None:  # verified: ingest.py:259 — signature unchanged
      """Save ``record`` when it differs from the stored version; re-encode the stored record when its
      envelope is not canonical; update ``result`` counters.

      Fingerprint equal and ``existing[1] == decision_to_page(existing[0]).content_hash`` → ``unchanged``.
      Fingerprint equal and the hashes differ → ``repo.save(existing[0], existing[1])`` and ``updated``.
      A ``DecisionError`` from encoding or saving becomes a diagnostic (same shape as verified at
      ingest.py:266-270) and nothing is counted.
      """
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_refresh_rewrites_legacy_envelope` | M1 | after a first refresh, one stored page is replaced by a legacy envelope with a matching hash; the next refresh reports it in `updated`, and its stored hash then equals `decision_to_page(decision_from_page(page)).content_hash` |
| `test_refresh_rewrite_keeps_stored_record` | M1 | the rewritten page decodes to a record equal to the one decoded before the rewrite (revision and review history included) |
| `test_refresh_rewrite_is_idempotent` | M1 | a third refresh counts every record as `unchanged` and writes nothing |
| `test_refresh_canonical_pages_stay_unchanged` | M1 | with no legacy page, counters match today's (`updated == 0`) |
| `test_refresh_rewrite_conflict_is_a_diagnostic` | M1 | `repo.save` raising `ADR_REVISION_CONFLICT` yields a diagnostic and no `updated` |

### Integration Tests

| Test | Description |
|---|---|
| `test_ingest.py` (existing) | the idempotence and counter tests keep passing |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py
markers: none

### Test Data / Fixtures

```python
# Reuse: adr_repo, adr_config, adr_store (tests/knowledge/wiki/decisions/conftest.py:149, :185, :191).
def _legacy_page(page: dict) -> WikiPageRecord:
    """The stored page with the schema-2 keys removed from its envelope and content_hash = sha1(envelope)."""
```

---

## 5. Acceptance Criteria

- [ ] A refresh over a plane holding a legacy envelope for a documented ADR rewrites that page and
  reports it in `SyncResult.updated`.
- [ ] After the rewrite the page's stored hash equals the hash of its record under the current codec.
- [ ] The rewritten record equals the stored record decoded before the rewrite.
- [ ] A second refresh reports the page as `unchanged`.
- [ ] A plane with only canonical pages produces the same counters as before this change.
- [ ] Every test in the Validation Contract passes.
- [ ] No breaking change to the public API of `parrot.knowledge.wiki.decisions`.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.codec import content_fingerprint, decision_to_page, decision_from_page, canonical_json  # verified: decisions/codec.py:60, :180, :212, :55
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions             # verified: decisions/ingest.py:277
from parrot.knowledge.wiki.decisions.models import DecisionDiagnostic, DecisionError, DecisionRecord, SyncResult   # verified: decisions/ingest.py:18-29
from parrot.knowledge.wiki.decisions.repository import DecisionRepository        # verified: decisions/ingest.py:31
```
Paths below are under `packages/ai-parrot/src/parrot/knowledge/wiki/`.

### Existing Class Signatures

```python
# decisions/ingest.py
async def _persist_if_changed(repo: DecisionRepository, record: DecisionRecord, result: SyncResult) -> None   # line 259
#   existing = await repo.get(record.decision_id)                                # line 261
#   expected_hash = existing[1] if existing is not None else None                # line 262
#   if existing is not None and content_fingerprint(existing[0]) == content_fingerprint(record):   # line 263
#       result.unchanged += 1                                                    # line 264
#   except DecisionError as exc: result.diagnostics.append(DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id))   # lines 268-270
async def refresh_decisions(store: BaseWikiStore, root: Path, config: DecisionConfig, paths: list[str] | None = None) -> SyncResult   # line 277

# decisions/repository.py
async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None      # line 45
async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord   # line 96 — raises DecisionError

# decisions/codec.py
def content_fingerprint(record: DecisionRecord) -> str                           # line 60
def decision_to_page(record: DecisionRecord) -> WikiPageRecord                   # line 180 — content_hash=_sha1(envelope) (line 208); raises ADR_RECORD_TOO_LARGE
def decision_from_page(page: dict[str, Any]) -> DecisionRecord                   # line 212

# decisions/models.py
class SyncResult(_Strict):                                                       # line 342 — created, updated, unchanged, missing, unresolved, diagnostics
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| canonical-hash branch | `decision_to_page` | call on the stored record | `decisions/codec.py:180` |
| canonical-hash branch | `DecisionRepository.save` | CAS with the stored hash | `decisions/repository.py:96` |

### Does NOT Exist (Anti-Hallucination)

- ~~an `envelope_hash` / `canonical_hash` helper in `codec.py`~~ — use `decision_to_page(record).content_hash`.
- ~~`record_hash` in `ingest.py` or `codec.py`~~ — it lives in `decisions/inventory.py` and is not imported here.
- ~~a `rewritten` counter on `SyncResult`~~ — the rewrite is counted in `updated`.

### Edit Sites (Blueprint Anchors)

Verified against: `1151c46c92`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | `from parrot.knowledge.wiki.decisions.codec import content_fingerprint` | `ingest.py:16` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | `    if existing is not None and content_fingerprint(existing[0]) == content_fingerprint(record):` | `ingest.py:263` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | MODIFY | `        before = {r.decision_id: r.revision for r in await DecisionRepository(adr_store).inventory()}` | `test_ingest.py:35` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Save back the **stored** record, never the freshly parsed one, in the fingerprint-equal branch: the
  parsed record carries no review history.
- Compare-and-swap with the hash returned by the same `repo.get()` call.
- A per-record failure is a diagnostic, never an exception (`refresh_decisions` contract, ingest.py:288-290).

### Known Risks / Gotchas

- The existing idempotence test (`test_ingest.py:35-38`) asserts revisions do not move across two
  refreshes; a canonical plane must still satisfy it.
- `decision_to_page` can raise `ADR_RECORD_TOO_LARGE`; that becomes a diagnostic and the page is left as it is.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none |

---

## Consequences

<!-- decision-audit: input_digest=sha256:94234c839b1df450c499df2f2a0a6db54d698466cc9d6aee8656f0bfd36202d7 evaluation_digest=sha256:5c650e4d4a08b4831797bdb4081d11b79213d079ed6285e52e6d9d097191cd1e rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/decisions-ingest-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: decision-audit, ingest, ledger-fix
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
      "ingest",
      "ledger-fix"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/decisions-ingest-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:5c650e4d4a08b4831797bdb4081d11b79213d079ed6285e52e6d9d097191cd1e",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:94234c839b1df450c499df2f2a0a6db54d698466cc9d6aee8656f0bfd36202d7",
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

- [x] Save the parsed record or the stored one? — *Resolved in this spec*: the stored one; the parsed
  record has the same content fingerprint but no review history.

---

## 9. Design Research Cross-Check

> Status: skipped (ledger-driven fix authored by `/sdd-fix`; no exploration document)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-808.
- **Module dependency graph**: one module, no edges.
- **Shared files**: none with FEAT-807 (that spec edits `decisions/repository.py`, `decisions/inventory.py`
  and their tests only).
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none. FEAT-807 is independent and may merge in either order.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-05 | Jesus Lara (with Claude) | Authored by `/sdd-fix` from `issue:42977fa3aaeb` |
