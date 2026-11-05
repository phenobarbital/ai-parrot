---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [decision-audit, wiki, ingest, tests, ledger-fix]
---

# Feature Specification: Envelope-rewrite tests pin the stored record, the CAS hash and the encode failure

**Feature ID**: FEAT-809
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.0

Source: ledger `issue:d251f4df988b` (major, tech_debt), discovered from `review:TASK-5205`. Authored by
`/sdd-fix` (SDD lane, group `fixgroup:bd0ac98ab0a4`).

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-808 made `_persist_if_changed` re-encode a stored ADR page whose envelope is not canonical. The
code review of TASK-5205 found the production code correct and three gaps in its tests
(`tests/knowledge/wiki/decisions/test_ingest.py::TestCanonicalEnvelope`):

1. `test_refresh_rewrite_keeps_stored_record` starts from a freshly ingested record — revision 1, no
   review history. The freshly parsed record is then equal to the stored one, so a change that saves
   the parsed record instead of the stored one passes the test while discarding revision and review
   history. The rewrite branch runs for every stored page each time `DecisionRecord` gains a field.
2. `test_refresh_rewrite_conflict_is_a_diagnostic` patches `DecisionRepository.save` to raise without
   looking at its arguments. It cannot tell a compare-and-swap against the hash that was read from one
   against any other value.
3. Nothing covers `decision_to_page` raising inside the rewrite branch (`ADR_RECORD_TOO_LARGE`).

### Goals

- **G1** — A test fails when the rewrite saves anything other than the stored record: a stored record
  with a non-default revision and one review event keeps both across the rewrite.
- **G2** — A test fails when the rewrite calls `save` with a record or an expected hash other than the
  ones `repo.get()` returned.
- **G3** — A test covers an encoding failure in the rewrite branch: one diagnostic, the page untouched,
  the rest of the refresh completed.

### Non-Goals (explicitly out of scope)

- Any change to production code. `decisions/ingest.py` is not edited.
- The read-only-plane behaviour of the rewrite (`issue:84c5f270394d`) and the snapshot findings
  (`issue:c7f16ecf903e`, `issue:d219d0707031`) — separate ledger groups.
- What a refresh does to revision and review history when a documented ADR's *content* changed — that
  is the pre-existing changed-content path, not the rewrite branch.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:2e39ccd38e39ad9d099bb07e4b6e47a2abbbdaf6176d0fc2dbf5361542f5daf7 evaluation_digest=sha256:5cdcd8c13f99c8f35f042eb3942db50fa64ca637927456d7cc606e81065b0f61 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Test-only change in one file. One private helper seeds review state on a stored record; two existing
tests are tightened and one test is added, all inside `TestCanonicalEnvelope`.

- `_seed_review_state` reads the stored record with `DecisionRepository.get`, sets `revision=2` and one
  `ReviewEvent`, and saves it back with the hash just read. `revision` and `review_history` are outside
  `content_fingerprint`, so the next refresh still takes the fingerprint-equal branch.
- `test_refresh_rewrite_keeps_stored_record` seeds review state before making the envelope legacy and
  asserts the revision and the review history after the rewrite.
- `test_refresh_rewrite_conflict_is_a_diagnostic` records the arguments `save` receives for the legacy
  page and asserts they are the stored record and the legacy hash; it also asserts the page still holds
  the legacy hash afterwards.
- `test_refresh_rewrite_encode_failure_is_a_diagnostic` patches the `decision_to_page` name bound in
  `decisions/ingest.py` so it raises `ADR_RECORD_TOO_LARGE` for the legacy page only.
  `DecisionRepository.save` uses its own binding in `decisions/repository.py` and is not affected.

### Component Diagram

```
TestCanonicalEnvelope
  ├─ _seed_review_state(store, id) ──► DecisionRepository.get / .save          (new helper)
  ├─ test_refresh_rewrite_keeps_stored_record        (tightened: seeded revision + review history)
  ├─ test_refresh_rewrite_conflict_is_a_diagnostic   (tightened: save() arguments + page untouched)
  └─ test_refresh_rewrite_encode_failure_is_a_diagnostic   (new: ingest.decision_to_page raises)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `_persist_if_changed` | tested | not modified |
| `DecisionRepository.get` / `.save` | uses | to seed review state |
| `_make_legacy` (test helper) | uses | unchanged |

### Data Models

No model changes.

### New Public Interfaces

None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Envelope-rewrite test hardening | yes | helper signature, the three tests and their assertions are fixed below | — |

### Module 1: Envelope-rewrite test hardening
- **Path**: `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py`
- **Responsibility**: make the three properties of the rewrite branch fail a test when broken.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # test_ingest.py
  from parrot.knowledge.wiki.decisions.models import (  # extends the import verified at test_ingest.py:13
      ADR_RECORD_TOO_LARGE, ADR_REVISION_CONFLICT, DecisionConfig, DecisionError, DecisionRecord, ReviewEvent,
  )

  async def _seed_review_state(store: BaseWikiStore, decision_id: str) -> DecisionRecord:
      """Give one stored ADR record revision 2 and one review event; return the record as saved."""

  class TestCanonicalEnvelope:  # verified: test_ingest.py:463
      async def test_refresh_rewrite_keeps_stored_record(self, adr_repo, adr_config, adr_store): ...          # verified: test_ingest.py:479 — tightened
      async def test_refresh_rewrite_conflict_is_a_diagnostic(self, adr_repo, adr_config, adr_store, monkeypatch): ...   # verified: test_ingest.py:506 — tightened
      async def test_refresh_rewrite_encode_failure_is_a_diagnostic(self, adr_repo, adr_config, adr_store, monkeypatch): ...   # new
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_refresh_rewrite_keeps_stored_record` | M1 | seed revision 2 + one review event, make the envelope legacy, refresh; the decoded record equals the one decoded before, `revision == 2`, one review event |
| `test_refresh_rewrite_conflict_is_a_diagnostic` | M1 | `save` for the legacy page receives the stored record and the legacy hash, raises `ADR_REVISION_CONFLICT`; one diagnostic, `updated == 0`, the page still holds the legacy hash |
| `test_refresh_rewrite_encode_failure_is_a_diagnostic` | M1 | `ingest.decision_to_page` raises `ADR_RECORD_TOO_LARGE` for the legacy page; one diagnostic with that code and id, `updated == 0`, the page still holds the legacy hash, the other records are counted `unchanged` |

### Integration Tests

| Test | Description |
|---|---|
| `test_ingest.py` (existing) | every other test keeps passing |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py
markers: none

### Test Data / Fixtures

```python
# Reuse: adr_repo, adr_config, adr_store (tests/knowledge/wiki/decisions/conftest.py:149, :185, :191),
# _make_legacy, _canonical_hash, _LEGACY_SOURCE (test_ingest.py:429, :458, :426).
```

---

## 5. Acceptance Criteria

- [ ] `test_refresh_rewrite_keeps_stored_record` fails when `_persist_if_changed` saves `record` instead
  of the stored record in the rewrite branch, and passes on the unmodified code.
- [ ] `test_refresh_rewrite_conflict_is_a_diagnostic` fails when the rewrite passes an expected hash
  other than the one read, and passes on the unmodified code.
- [ ] `test_refresh_rewrite_encode_failure_is_a_diagnostic` fails when `decision_to_page` is called
  outside the `try` of the rewrite branch, and passes on the unmodified code.
- [ ] Every test in the Validation Contract passes.
- [ ] `git diff --name-only` for the feature lists no file under `packages/*/src/`.
- [ ] `ruff check` reports nothing on `test_ingest.py`.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page, documented_decision_id   # verified: test_ingest.py:11
from parrot.knowledge.wiki.decisions.ingest import discover_adr_sources, refresh_decisions                     # verified: test_ingest.py:12
from parrot.knowledge.wiki.decisions.models import ADR_REVISION_CONFLICT, DecisionConfig, DecisionError, DecisionRecord   # verified: test_ingest.py:13
from parrot.knowledge.wiki.decisions.models import ADR_RECORD_TOO_LARGE, ReviewEvent                           # verified: decisions/models.py:23, :174
from parrot.knowledge.wiki.decisions.repository import DecisionRepository                                      # verified: test_ingest.py:14
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord                                          # verified: test_ingest.py:15
```
Source paths below are under `packages/ai-parrot/src/parrot/knowledge/wiki/`.

### Existing Class Signatures

```python
# decisions/ingest.py
from parrot.knowledge.wiki.decisions.codec import content_fingerprint, decision_to_page   # line 16 — the binding the new test patches
async def _persist_if_changed(repo: DecisionRepository, record: DecisionRecord, result: SyncResult) -> None   # line 259
#   existing = await repo.get(record.decision_id)                                # line 265
#   stored_record, stored_hash = existing                                        # line 270
#   try:                                                                         # line 271
#       canonical_hash = decision_to_page(stored_record).content_hash            # line 272
#       ...
#       await repo.save(stored_record, stored_hash)                              # line 276
#   except DecisionError as exc: result.diagnostics.append(DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id))

# decisions/repository.py
async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None
async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord   # line 107 — calls its own decision_to_page binding

# decisions/models.py
class ReviewEvent(_Strict):                                                      # line 174
#   revision: int (ge=1); action: Literal["accept", "reject", "revise", "link"]; actor: str; timestamp: str;
#   reason: str = ""; before_sha1: str = ""; after_sha1: str = ""
class DecisionRecord(_Strict):                                                   # line 224
#   revision: int = 1 (line 229); review_history: list[ReviewEvent] = [] (line 244)

# decisions/codec.py
def content_fingerprint(record: DecisionRecord) -> str   # line 60 — excludes content_fingerprint, revision, review_history

# tests/knowledge/wiki/decisions/test_ingest.py
_LEGACY_SOURCE = "docs/adr/0001-use-pgvector.md"                                 # line 426
async def _make_legacy(store: BaseWikiStore, decision_id: str) -> str            # line 429 — returns the legacy hash
def _canonical_hash(page: dict) -> str                                           # line 458
class TestCanonicalEnvelope                                                      # line 463
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_seed_review_state` | `DecisionRepository.get` / `.save` | read, `model_copy`, CAS save | `decisions/repository.py:107` |
| encode-failure test | `decisions.ingest.decision_to_page` | `monkeypatch.setattr` on the module attribute | `decisions/ingest.py:16` |

### Does NOT Exist (Anti-Hallucination)

- ~~a fixture that yields a reviewed documented record~~ — seed it in the test with `_seed_review_state`.
- ~~`DecisionRepository.review` / `.set_revision`~~ — reviews go through `DecisionService.review`; the
  test writes the seeded record with `DecisionRepository.save`.
- ~~a size-bound fixture or a `MAX_RECORD_BYTES` override hook~~ — the test patches
  `decisions.ingest.decision_to_page`; it does not build an oversized record.

### Edit Sites (Blueprint Anchors)

Verified against: `d9a9d93031`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | MODIFY | `from parrot.knowledge.wiki.decisions.models import ADR_REVISION_CONFLICT, DecisionConfig, DecisionError, DecisionRecord` | `test_ingest.py:13` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | MODIFY | `    async def test_refresh_rewrite_keeps_stored_record(self, adr_repo, adr_config, adr_store):` | `test_ingest.py:479` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | MODIFY | `    async def test_refresh_rewrite_conflict_is_a_diagnostic(self, adr_repo, adr_config, adr_store, monkeypatch):` | `test_ingest.py:506` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Seed with `ReviewEvent(...)` objects, not dicts: `model_copy(update=...)` does not validate, and a dict
  in `review_history` triggers a pydantic serializer warning.
- Seed **before** `_make_legacy`: `_make_legacy` rewrites the stored envelope and keeps whatever
  revision and review history it holds.
- Leave `review_status` alone when seeding — it is part of `content_fingerprint`, and changing it would
  send the next refresh down the changed-content path instead of the rewrite branch.
- Patch the attribute on the `parrot.knowledge.wiki.decisions.ingest` module, delegating to the original
  for every other decision id.

### Known Risks / Gotchas

- Each tightened test must be shown to fail against the matching mutation of `ingest.py` (acceptance
  criteria 1–3). Apply the mutation in the feature worktree only, run the one test, and restore the
  file before committing; `ingest.py` must not appear in the diff.
- `test_refresh_rewrite_is_idempotent` and `test_refresh_canonical_pages_stay_unchanged` are not edited.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none |

---

## Consequences

<!-- decision-audit: input_digest=sha256:2e39ccd38e39ad9d099bb07e4b6e47a2abbbdaf6176d0fc2dbf5361542f5daf7 evaluation_digest=sha256:5cdcd8c13f99c8f35f042eb3942db50fa64ca637927456d7cc606e81065b0f61 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/decisions-test-ingest-tech-debt.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: decision-audit, ingest, ledger-fix, tests
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
      "ledger-fix",
      "tests"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/decisions-test-ingest-tech-debt.spec.md"
    }
  ],
  "evaluation_digest": "sha256:5cdcd8c13f99c8f35f042eb3942db50fa64ca637927456d7cc606e81065b0f61",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:2e39ccd38e39ad9d099bb07e4b6e47a2abbbdaf6176d0fc2dbf5361542f5daf7",
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

- [x] Tighten the two existing tests or add parallel ones? — *Resolved in this spec*: tighten them; the
  weaker versions add nothing once the stricter assertions exist.
- [x] Real oversized record or a patched encoder for the encode failure? — *Resolved in this spec*: a
  patched encoder; an oversized record would depend on `MAX_RECORD_BYTES` and on the fixture ADR's size.

---

## 9. Design Research Cross-Check

> Status: skipped (ledger-driven fix authored by `/sdd-fix`; no exploration document)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-809.
- **Module dependency graph**: one module, no edges.
- **Shared files**: `test_ingest.py` is also the test file of ledger group `decisions-ingest-tech-debt`
  (`issue:84c5f270394d`); if that group is fixed first, re-verify the Edit Sites.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: FEAT-808 (merged in PR #1960).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-05 | Jesus Lara (with Claude) | Authored by `/sdd-fix` from `issue:d251f4df988b` |
