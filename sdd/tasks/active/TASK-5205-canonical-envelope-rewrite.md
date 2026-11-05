# TASK-5205: Decision ingest rewrites a non-canonical stored envelope

**Feature**: FEAT-808 — Decision ingest rewrites a stored ADR page whose envelope is not canonical
**Spec**: `sdd/specs/decisions-ingest-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:42977fa3aaeb`

---

## Context

Implements spec §3 Module 1. `_persist_if_changed` counts a stored ADR page as unchanged whenever its
content fingerprint matches the freshly parsed record. The fingerprint does not cover the shape of the
stored envelope, so a page written by an older codec is never rewritten: `wikitoolkit build` and
`upsert --changed` leave it as it is (ledger `issue:42977fa3aaeb`). The fix re-encodes the stored record
when its stored hash is not the hash the current codec produces for it.

---

## Scope

- In `_persist_if_changed`, inside the fingerprint-equal branch, compare the stored hash with
  `decision_to_page(stored_record).content_hash`; when they differ, save the **stored** record back with
  a compare-and-swap against the stored hash and count it in `SyncResult.updated`.
- Turn a `DecisionError` from encoding or saving into a diagnostic, as the existing save path does.
- Write the five tests listed in the Test Specification.

**NOT in scope**: `decisions/inventory.py` and `decisions/repository.py` (TASK-5204 / FEAT-807), pages a
refresh does not visit (spec-authored and candidate decisions), any migration command, `SyncResult`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | canonical-envelope branch in `_persist_if_changed` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | MODIFY | new `TestCanonicalEnvelope` class |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.codec import content_fingerprint, decision_to_page   # verified: decisions/codec.py:60, :180 (content_fingerprint already imported at ingest.py:16)
from parrot.knowledge.wiki.decisions.codec import decision_from_page, documented_decision_id   # verified: decisions/codec.py:212, :112 (documented_decision_id already imported at tests/.../test_ingest.py:9)
from parrot.knowledge.wiki.decisions.ingest import discover_adr_sources, refresh_decisions   # verified: tests/.../test_ingest.py:10
from parrot.knowledge.wiki.decisions.models import ADR_REVISION_CONFLICT, DecisionConfig, DecisionError, DecisionRecord   # verified: decisions/repository.py:12-22 imports ADR_REVISION_CONFLICT from models
from parrot.knowledge.wiki.decisions.repository import DecisionRepository   # verified: tests/.../test_ingest.py:12
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord       # verified: knowledge/wiki/store.py:601 (WikiPageRecord), tests/.../test_ingest.py:13
import hashlib, json                                                        # stdlib; not yet imported in test_ingest.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
async def _persist_if_changed(repo: DecisionRepository, record: DecisionRecord, result: SyncResult) -> None:   # line 259
    existing = await repo.get(record.decision_id)                           # line 261
    expected_hash = existing[1] if existing is not None else None           # line 262
    if existing is not None and content_fingerprint(existing[0]) == content_fingerprint(record):   # line 263
        result.unchanged += 1                                               # line 264
        return                                                              # line 265
    try:                                                                    # line 266
        await repo.save(record, expected_hash)                              # line 267
    except DecisionError as exc:                                            # line 268
        result.diagnostics.append(DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id))   # line 269
        return                                                              # line 270
async def refresh_decisions(store: BaseWikiStore, root: Path, config: DecisionConfig, paths: list[str] | None = None) -> SyncResult   # line 277

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None   # line 45
async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord   # line 96 — raises DecisionError (ADR_REVISION_CONFLICT, ADR_READ_ONLY, ADR_RECORD_TOO_LARGE)

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py
def decision_to_page(record: DecisionRecord) -> WikiPageRecord              # line 180 — body = f"{marker}\n{envelope}\n\n{markdown}"; content_hash = sha1(envelope); raises ADR_RECORD_TOO_LARGE
def decision_from_page(page: dict[str, Any]) -> DecisionRecord              # line 212

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class SyncResult(_Strict): created, updated, unchanged, missing, unresolved, diagnostics   # line 342

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel)                                             # line 601 — pydantic
async def upsert_pages(self, pages: list[WikiPageRecord]) -> int            # BaseWikiStore, line 912 — keeps a supplied content_hash
async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]   # BaseWikiStore, line 933

# packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py
class TestRefresh:                                                          # line 27
# fixtures: adr_repo (conftest.py:149 — includes docs/adr/0001-use-pgvector.md, an accepted ADR), adr_config (:185), adr_store (:191)
```

### Does NOT Exist
- ~~an `envelope_hash` / `canonical_hash` helper in `codec.py`~~ — use `decision_to_page(record).content_hash`.
- ~~`record_hash` importable from `ingest.py` or `codec.py`~~ — it lives in `decisions/inventory.py`; do not import it here.
- ~~a `rewritten` counter on `SyncResult`~~ — the rewrite is counted in `updated`.
- ~~`WikiPageRecord(**page_dict)` round-trip of a `get_page` row~~ — a row carries read-only keys
  (`created_at`, `attrs`); build the record from the named fields, as the blueprint does.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#_persist_if_changed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#refresh_decisions",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.get",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.save",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#decision_to_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#decision_from_page"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Save back the **stored** record (`existing[0]`), never the parsed one: the parsed record has the same
  fingerprint but none of the stored review history.
- Compare-and-swap with the hash returned by the same `repo.get()` call (`existing[1]`).
- A per-record failure is a diagnostic, never an exception (`refresh_decisions` docstring, ingest.py:288-290).
- A plane with only canonical pages must behave exactly as today (`test_second_sync_is_a_no_op`).
- Tests are plain `async def` methods (pytest-asyncio auto mode, as the rest of the file).

### References in Codebase
- `decisions/ingest.py:266-270` — the diagnostic shape to reuse.
- `tests/knowledge/wiki/decisions/test_ingest.py:32-39` — the idempotence test the change must keep green.

---

## Implementation Blueprint

### Steps (in order)
1. Import `decision_to_page` next to `content_fingerprint` — *why*: it is the only source of the
   canonical hash; `record_hash` lives in `inventory.py` and must not be imported here.
2. Replace the fingerprint-equal branch of `_persist_if_changed` with the block below — *why*: an equal
   fingerprint says the content is the same, not that the envelope is canonical.
3. Add `TestCanonicalEnvelope` at the end of `test_ingest.py` and run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from parrot.knowledge.wiki.decisions.codec import content_fingerprint' ingest.py)
# REPLACE that import line (verified: ingest.py:16) with:
from parrot.knowledge.wiki.decisions.codec import content_fingerprint, decision_to_page

# occurrences: 1 (verified: grep -cF '    if existing is not None and content_fingerprint(existing[0]) == content_fingerprint(record):' ingest.py)
# REPLACE the three lines of that branch (verified: ingest.py:263-265 — the `if`, `result.unchanged += 1`, `return`) with:
    if existing is not None and content_fingerprint(existing[0]) == content_fingerprint(record):
        # Same content — but an envelope written by an older codec must still be re-encoded,
        # or the page keeps a hash no current reader can reproduce (issue:42977fa3aaeb).
        stored_record, stored_hash = existing
        try:
            canonical_hash = decision_to_page(stored_record).content_hash
            if stored_hash == canonical_hash:
                result.unchanged += 1
                return
            await repo.save(stored_record, stored_hash)
        except DecisionError as exc:
            result.diagnostics.append(DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id))
            return
        result.updated += 1
        return
```
**Why this shape**: the stored record is what gets saved, so revision, review history and links survive;
the CAS uses the hash read a few lines above, so a concurrent writer wins and shows up as a diagnostic.
Leave the rest of the function (the `try: await repo.save(record, expected_hash)` path) untouched, and
update the function's one-line docstring to mention the re-encode.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from pathlib import Path' test_ingest.py → line 5)
# BEFORE — insert above `from pathlib import Path` (verified: test_ingest.py:5):
import hashlib
import json

# occurrences: 1 (verified: grep -cF 'from parrot.knowledge.wiki.decisions.codec import documented_decision_id' test_ingest.py)
# REPLACE that import line (verified: test_ingest.py:9) with:
from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page, documented_decision_id

# occurrences: 1 (verified: grep -cF 'from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord' test_ingest.py)
# REPLACE that import line (verified: test_ingest.py:11) with:
from parrot.knowledge.wiki.decisions.models import ADR_REVISION_CONFLICT, DecisionConfig, DecisionError, DecisionRecord

# occurrences: 1 (verified: grep -cF 'from parrot.knowledge.wiki.store import BaseWikiStore' test_ingest.py)
# REPLACE that import line (verified: test_ingest.py:13) with:
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord

# occurrences: 1 (verified: grep -cF 'class TestRefresh:' test_ingest.py → line 27)
# AFTER — append at the END of the file, at module level (a new class, not inside TestRefresh):
_SCHEMA_2_KEYS = (
    "about", "batch_id", "contradicts", "document_id", "entry_id", "lifecycle",
    "normative", "rationale", "rejected_alternatives", "supersedes_refs", "targets",
)
_LEGACY_SOURCE = "docs/adr/0001-use-pgvector.md"


async def _make_legacy(store: BaseWikiStore, decision_id: str) -> str:
    """Rewrite one stored ADR page the way an older codec wrote it; return its legacy hash."""
    page = await store.get_page(decision_id, include_body=True)
    marker, envelope, rest = page["body"].split("\n", 2)
    payload = json.loads(envelope)
    for key in _SCHEMA_2_KEYS:
        payload.pop(key, None)
    legacy = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    legacy_hash = hashlib.sha1(legacy.encode("utf-8")).hexdigest()  # noqa: S324 — identity, not security
    await store.upsert_pages(
        [
            WikiPageRecord(
                concept_id=page["concept_id"],
                node_id=page["node_id"],
                title=page["title"],
                category=page["category"],
                summary=page["summary"],
                body=f"{marker}\n{legacy}\n{rest}",
                source_id=page.get("source_id"),
                token_count=page.get("token_count") or 0,
                origin=page.get("origin") or "ingest",
                asserted_by=page.get("asserted_by"),
                content_hash=legacy_hash,
            )
        ]
    )
    return legacy_hash


def _canonical_hash(page: dict) -> str:
    """The hash the current codec gives the record stored in ``page``."""
    return decision_to_page(decision_from_page(page)).content_hash


class TestCanonicalEnvelope:
    """issue:42977fa3aaeb — a refresh re-encodes a stored envelope that is not canonical."""

    async def test_refresh_rewrites_legacy_envelope(self, adr_repo, adr_config, adr_store):
        await refresh_decisions(adr_store, adr_repo, adr_config)
        decision_id = documented_decision_id(_LEGACY_SOURCE)
        legacy_hash = await _make_legacy(adr_store, decision_id)
        assert legacy_hash != _canonical_hash(await adr_store.get_page(decision_id))  # precondition

        result = await refresh_decisions(adr_store, adr_repo, adr_config)

        page = await adr_store.get_page(decision_id)
        assert result.updated == 1 and result.created == 0
        assert page["content_hash"] == _canonical_hash(page) != legacy_hash

    async def test_refresh_rewrite_keeps_stored_record(self, adr_repo, adr_config, adr_store):
        await refresh_decisions(adr_store, adr_repo, adr_config)
        decision_id = documented_decision_id(_LEGACY_SOURCE)
        await _make_legacy(adr_store, decision_id)
        before = decision_from_page(await adr_store.get_page(decision_id))

        await refresh_decisions(adr_store, adr_repo, adr_config)

        assert decision_from_page(await adr_store.get_page(decision_id)) == before

    async def test_refresh_rewrite_is_idempotent(self, adr_repo, adr_config, adr_store):
        await refresh_decisions(adr_store, adr_repo, adr_config)
        await _make_legacy(adr_store, documented_decision_id(_LEGACY_SOURCE))
        await refresh_decisions(adr_store, adr_repo, adr_config)

        result = await refresh_decisions(adr_store, adr_repo, adr_config)

        assert result.updated == 0 and result.created == 0 and result.unchanged > 0

    async def test_refresh_canonical_pages_stay_unchanged(self, adr_repo, adr_config, adr_store):
        await refresh_decisions(adr_store, adr_repo, adr_config)

        result = await refresh_decisions(adr_store, adr_repo, adr_config)

        assert result.updated == 0 and result.created == 0 and result.unchanged > 0
        assert result.diagnostics == [] or all(d.code != ADR_REVISION_CONFLICT for d in result.diagnostics)

    async def test_refresh_rewrite_conflict_is_a_diagnostic(self, adr_repo, adr_config, adr_store, monkeypatch):
        await refresh_decisions(adr_store, adr_repo, adr_config)
        decision_id = documented_decision_id(_LEGACY_SOURCE)
        await _make_legacy(adr_store, decision_id)

        # FILL IN: monkeypatch DecisionRepository.save to raise
        # DecisionError(ADR_REVISION_CONFLICT, "conflict", decision_id=decision_id) for this id only,
        # run refresh_decisions, then assert result.updated == 0 and that result.diagnostics holds one
        # entry with code == ADR_REVISION_CONFLICT and decision_id == decision_id — bounded by spec AC-1/§2.
```
**Why**: the tests rebuild a legacy page from a real ingested one, so they exercise the same decode path
as production. `_make_legacy` constructs the record from named fields because a `get_page` row carries
read-only keys.

### FILL IN checklist
- [ ] `test_ingest.py::TestCanonicalEnvelope::test_refresh_rewrite_conflict_is_a_diagnostic` — the
  monkeypatch and the two assertions; bounded by spec §2 Overview (a `DecisionError` becomes a
  diagnostic and nothing is counted as updated).
- [ ] Confirm `documented_decision_id("docs/adr/0001-use-pgvector.md")` is stored after the first
  refresh (it is the accepted ADR of the `adr_repo` fixture, conftest.py:161); if the fixture file name
  differs, use the first id of `DecisionRepository(adr_store).inventory()` instead.
- [ ] `ingest.py::_persist_if_changed` docstring — one sentence naming the re-encode.

---

## Acceptance Criteria

- [ ] A refresh over a plane holding a legacy envelope rewrites that page and reports `updated == 1`.
- [ ] After the rewrite the stored hash equals `decision_to_page(decision_from_page(page)).content_hash`.
- [ ] The rewritten record equals the record decoded before the rewrite.
- [ ] A further refresh reports the page as unchanged.
- [ ] `test_second_sync_is_a_no_op` and the rest of `test_ingest.py` still pass.
- [ ] `ruff check` reports nothing on the two files.
- [ ] `test_refresh_rewrites_legacy_envelope` fails on the base commit and passes on this branch.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py -q`

---

## Test Specification

The five tests are given in the Implementation Blueprint above; the only open part is the FILL IN in
`test_refresh_rewrite_conflict_is_a_diagnostic`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug decisions-ingest-fixes --feature-id FEAT-808`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in `sdd/tasks/index/decisions-ingest-fixes.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** with the Validation Commands, using `PYTHONPATH=packages/ai-parrot/src` inside the worktree
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with `parrot sdd task close TASK-5205 decisions-ingest-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
