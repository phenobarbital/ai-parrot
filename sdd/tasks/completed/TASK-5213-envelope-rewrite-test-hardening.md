# TASK-5213: Envelope-rewrite tests pin the stored record, the CAS hash and the encode failure

**Feature**: FEAT-809 — Envelope-rewrite tests pin the stored record, the CAS hash and the encode failure
**Spec**: `sdd/specs/decisions-test-ingest-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:d251f4df988b`

---

## Context

Implements spec §3 Module 1. The code review of TASK-5205 (FEAT-808) found `_persist_if_changed`
correct and three gaps in `TestCanonicalEnvelope` (ledger `issue:d251f4df988b`): the "keeps stored
record" test starts from a record with no review history, so saving the parsed record instead of the
stored one would pass; the conflict test raises without looking at the arguments `save` receives; and
no test covers `decision_to_page` raising inside the rewrite branch.

---

## Scope

- Add the test helper `_seed_review_state`.
- Tighten `test_refresh_rewrite_keeps_stored_record` and `test_refresh_rewrite_conflict_is_a_diagnostic`.
- Add `test_refresh_rewrite_encode_failure_is_a_diagnostic`.
- Show each of the three tests failing against its mutation of `ingest.py` (Acceptance Criteria), with
  `ingest.py` restored before committing.

**NOT in scope**: any production file (`decisions/ingest.py` included), the other tests of
`test_ingest.py`, `issue:84c5f270394d` (read-only plane), `issue:c7f16ecf903e` and `issue:d219d0707031`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | MODIFY | helper `_seed_review_state`, two tightened tests, one new test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page, documented_decision_id   # verified: test_ingest.py:11 (already imported)
from parrot.knowledge.wiki.decisions.ingest import discover_adr_sources, refresh_decisions                     # verified: test_ingest.py:12 (already imported)
from parrot.knowledge.wiki.decisions.models import ADR_REVISION_CONFLICT, DecisionConfig, DecisionError, DecisionRecord   # verified: test_ingest.py:13 (already imported)
from parrot.knowledge.wiki.decisions.models import ADR_RECORD_TOO_LARGE, ReviewEvent                           # verified: decisions/models.py:23, :174 (NOT yet imported in test_ingest.py)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository                                      # verified: test_ingest.py:14 (already imported)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord                                          # verified: test_ingest.py:15 (already imported)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
from parrot.knowledge.wiki.decisions.codec import content_fingerprint, decision_to_page   # line 16 — the binding the new test patches
async def _persist_if_changed(repo: DecisionRepository, record: DecisionRecord, result: SyncResult) -> None   # line 259
#     existing = await repo.get(record.decision_id)                              # line 265
#     stored_record, stored_hash = existing                                      # line 270
#     try:                                                                       # line 271
#         canonical_hash = decision_to_page(stored_record).content_hash          # line 272
#         if stored_hash == canonical_hash: result.unchanged += 1; return        # lines 273-275
#         await repo.save(stored_record, stored_hash)                            # line 276
#     except DecisionError as exc: result.diagnostics.append(DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id)); return
#     result.updated += 1
async def refresh_decisions(store: BaseWikiStore, root: Path, config: DecisionConfig, paths: list[str] | None = None) -> SyncResult   # line 293

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None
async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord   # line 107 — returns the record as written

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class ReviewEvent(_Strict):                       # line 174
#   revision: int (ge=1); action: Literal["accept", "reject", "revise", "link"]; actor: str (min_length=1);
#   timestamp: str (min_length=1); reason: str = ""; before_sha1: str = ""; after_sha1: str = ""
class DecisionRecord(_Strict):                    # line 224 — revision: int = 1 (line 229); review_history: list[ReviewEvent] = [] (line 244)
class SyncResult(_Strict)                         # created, updated, unchanged, missing, unresolved, diagnostics

# packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py
_LEGACY_SOURCE = "docs/adr/0001-use-pgvector.md"                       # line 426
async def _make_legacy(store: BaseWikiStore, decision_id: str) -> str  # line 429 — returns the legacy hash
def _canonical_hash(page: dict) -> str                                 # line 458
class TestCanonicalEnvelope                                            # line 463
# fixtures: adr_repo (conftest.py:149), adr_config (:185), adr_store (:191)
```

### Does NOT Exist
- ~~a fixture that yields a reviewed documented record~~ — seed it with `_seed_review_state`.
- ~~`DecisionRepository.review` / `.set_revision`~~ — write the seeded record with `DecisionRepository.save`.
- ~~a `MAX_RECORD_BYTES` override hook or an oversized-record fixture~~ — patch
  `parrot.knowledge.wiki.decisions.ingest.decision_to_page`.
- ~~an `ingest_module` name in `test_ingest.py`~~ — patch by dotted string; the original encoder is the
  `decision_to_page` the test file already imports from `codec`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#_persist_if_changed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#refresh_decisions",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.get",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.save",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#decision_to_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#ReviewEvent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Seed with a `ReviewEvent(...)` object, not a dict: `model_copy(update=...)` does not validate.
- Seed **before** `_make_legacy`; `_make_legacy` keeps the revision and review history of the envelope.
- Do not touch `review_status` when seeding: it is inside `content_fingerprint`, and changing it sends
  the next refresh down the changed-content path instead of the rewrite branch.
- `ingest.py` must not appear in the feature diff. Mutations are applied and reverted in the worktree only.
- Tests are plain `async def` methods (pytest-asyncio auto mode, as the rest of the file).

### References in Codebase
- `tests/knowledge/wiki/decisions/test_ingest.py:163-178` — an existing record built with review history.
- `tests/knowledge/wiki/decisions/test_ingest.py:466-477` — the first test of the class, for the shape.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the `models` import — *why*: the helper needs `ReviewEvent` and the new test needs
   `ADR_RECORD_TOO_LARGE`; the line is already 119 columns, so it becomes a parenthesised import.
2. Add `_seed_review_state` after `_canonical_hash` — *why*: two tests need a stored record whose
   revision and review history differ from what a fresh parse produces.
3. Replace the body of `test_refresh_rewrite_keeps_stored_record` — *why*: with seeded review state the
   parsed record and the stored record differ, so saving the wrong one fails the test.
4. Replace the body of `test_refresh_rewrite_conflict_is_a_diagnostic` — *why*: recording the arguments
   pins both the record and the hash the compare-and-swap uses.
5. Add `test_refresh_rewrite_encode_failure_is_a_diagnostic` at the end of the class — *why*: the
   `decision_to_page` call sits inside the `try`; nothing proves it today.
6. Run the Validation Commands, then the three mutation checks of the Acceptance Criteria.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` — MODIFY (import)
```python
# REPLACE the line `from parrot.knowledge.wiki.decisions.models import ADR_REVISION_CONFLICT, DecisionConfig, DecisionError, DecisionRecord` (verified: test_ingest.py:13)
# occurrences: 1 (verified: grep -cF '<anchor>' test_ingest.py)
from parrot.knowledge.wiki.decisions.models import (
    ADR_RECORD_TOO_LARGE,
    ADR_REVISION_CONFLICT,
    DecisionConfig,
    DecisionError,
    DecisionRecord,
    ReviewEvent,
)
```
**Why**: black's layout for an import over 120 columns.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` — MODIFY (helper)
```python
# AFTER — insert below the body of `def _canonical_hash(page: dict) -> str:` (verified: test_ingest.py:458), before `class TestCanonicalEnvelope:`
# occurrences: 1 (verified: grep -c 'def _canonical_hash' test_ingest.py)
async def _seed_review_state(store: BaseWikiStore, decision_id: str) -> DecisionRecord:
    """Give one stored ADR record revision 2 and one review event; return the record as saved."""
    repo = DecisionRepository(store)
    record, stored_hash = await repo.get(decision_id)
    reviewed = record.model_copy(
        update={
            "revision": 2,
            "review_history": [
                ReviewEvent(
                    revision=2,
                    action="accept",
                    actor="human:reviewer",
                    timestamp="2026-01-01T00:00:00+00:00",
                    reason="seeded by test",
                    before_sha1="a",
                    after_sha1="b",
                )
            ],
        }
    )
    return await repo.save(reviewed, stored_hash)
```
**Why**: `revision` and `review_history` are outside `content_fingerprint`, so the next refresh still
reaches the fingerprint-equal branch — which is the branch under test.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` — MODIFY (keeps stored record)
```python
# REPLACE the body of `    async def test_refresh_rewrite_keeps_stored_record(self, adr_repo, adr_config, adr_store):` (verified: test_ingest.py:479)
# occurrences: 1
    async def test_refresh_rewrite_keeps_stored_record(self, adr_repo, adr_config, adr_store):
        await refresh_decisions(adr_store, adr_repo, adr_config)
        decision_id = documented_decision_id(_LEGACY_SOURCE)
        await _seed_review_state(adr_store, decision_id)
        await _make_legacy(adr_store, decision_id)
        before = decision_from_page(await adr_store.get_page(decision_id))
        assert before.revision == 2 and len(before.review_history) == 1  # the precondition

        result = await refresh_decisions(adr_store, adr_repo, adr_config)

        after = decision_from_page(await adr_store.get_page(decision_id))
        assert result.updated == 1
        assert after == before
        assert after.revision == 2
        assert [event.action for event in after.review_history] == ["accept"]
```
**Why**: the explicit `revision` / `review_history` assertions name what is being protected; `after ==
before` alone would not say why it failed.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` — MODIFY (conflict)
```python
# REPLACE the body of `    async def test_refresh_rewrite_conflict_is_a_diagnostic(self, adr_repo, adr_config, adr_store, monkeypatch):` (verified: test_ingest.py:506)
# occurrences: 1
    async def test_refresh_rewrite_conflict_is_a_diagnostic(self, adr_repo, adr_config, adr_store, monkeypatch):
        await refresh_decisions(adr_store, adr_repo, adr_config)
        decision_id = documented_decision_id(_LEGACY_SOURCE)
        await _seed_review_state(adr_store, decision_id)
        legacy_hash = await _make_legacy(adr_store, decision_id)
        stored = decision_from_page(await adr_store.get_page(decision_id))
        original_save = DecisionRepository.save
        calls: list[tuple[DecisionRecord, str | None]] = []

        async def conflicting_save(self, record, expected_content_hash):
            if record.decision_id == decision_id:
                calls.append((record, expected_content_hash))
                raise DecisionError(ADR_REVISION_CONFLICT, "conflict", decision_id=decision_id)
            return await original_save(self, record, expected_content_hash)

        monkeypatch.setattr(DecisionRepository, "save", conflicting_save)

        result = await refresh_decisions(adr_store, adr_repo, adr_config)

        conflicts = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == ADR_REVISION_CONFLICT]
        assert result.updated == 0
        assert [diagnostic.decision_id for diagnostic in conflicts] == [decision_id]
        assert calls == [(stored, legacy_hash)]
        # FILL IN: assert the page is untouched — bounded by spec §4: its stored hash is still `legacy_hash`.
```
**Why**: `calls == [(stored, legacy_hash)]` fails for a wrong record and for a wrong expected hash, and
also for a second `save` attempt.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` — MODIFY (encode failure)
```python
# AFTER — append at the end of `class TestCanonicalEnvelope:` (verified: test_ingest.py:463), which is the end of the file
# occurrences: 1 (verified: grep -c '^class TestCanonicalEnvelope' test_ingest.py)
    async def test_refresh_rewrite_encode_failure_is_a_diagnostic(self, adr_repo, adr_config, adr_store, monkeypatch):
        await refresh_decisions(adr_store, adr_repo, adr_config)
        clean = await refresh_decisions(adr_store, adr_repo, adr_config)
        decision_id = documented_decision_id(_LEGACY_SOURCE)
        legacy_hash = await _make_legacy(adr_store, decision_id)

        def failing_encode(record):
            if record.decision_id == decision_id:
                raise DecisionError(ADR_RECORD_TOO_LARGE, "too large", decision_id=decision_id)
            return decision_to_page(record)

        monkeypatch.setattr("parrot.knowledge.wiki.decisions.ingest.decision_to_page", failing_encode)

        result = await refresh_decisions(adr_store, adr_repo, adr_config)

        failures = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == ADR_RECORD_TOO_LARGE]
        assert [diagnostic.decision_id for diagnostic in failures] == [decision_id]
        assert result.updated == 0 and result.created == 0
        assert (await adr_store.get_page(decision_id))["content_hash"] == legacy_hash
        # FILL IN: assert the refresh went on — bounded by spec G3: `result.unchanged == clean.unchanged - 1`,
        # and `clean.unchanged > 1` so the assertion means something (check the fixture holds several ADRs).
```
**Why**: only the name bound in `ingest.py` is patched; `DecisionRepository.save` keeps the real encoder,
so a failure can only come from the call inside the rewrite branch.

### FILL IN checklist
- [ ] Conflict test: the page still holds `legacy_hash` after the refresh.
- [ ] Encode-failure test: `result.unchanged == clean.unchanged - 1` with `clean.unchanged > 1`.

---

## Acceptance Criteria

- [ ] `test_refresh_rewrite_keeps_stored_record` fails when line 276 of `ingest.py` is
  `await repo.save(record, stored_hash)`, and passes on the unmodified code.
- [ ] `test_refresh_rewrite_conflict_is_a_diagnostic` fails when line 276 is
  `await repo.save(stored_record, None)`, and passes on the unmodified code.
- [ ] `test_refresh_rewrite_encode_failure_is_a_diagnostic` fails when the `canonical_hash = ...` line is
  moved above `try:`, and passes on the unmodified code.
- [ ] The Validation Commands pass with `ingest.py` unmodified.
- [ ] `git diff --name-only origin/dev...HEAD` lists no file under `packages/*/src/`.
- [ ] `ruff check` reports nothing on `test_ingest.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py -q`

---

## Test Specification

The three tests are given in the Implementation Blueprint above; the open parts are the two FILL IN markers.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug decisions-test-ingest-tech-debt --feature-id FEAT-809`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in `sdd/tasks/index/decisions-test-ingest-tech-debt.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** with the Validation Commands, using `PYTHONPATH=packages/ai-parrot/src` inside the worktree
8. **Run the three mutation checks**, restoring `ingest.py` after each (`git checkout -- <path>`)
9. **Commit the code** — stage only `test_ingest.py`
10. **Close the task** with `parrot sdd task close TASK-5213 decisions-test-ingest-tech-debt verified`
11. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude (session /sdd-fix, actor agent:sdd-fix:8f950552)
**Date**: 2026-11-05
**Notes**: `test_ingest.py` only (commit `013a2ca917`). Added `_seed_review_state`; tightened
`test_refresh_rewrite_keeps_stored_record` (seeded revision 2 + one review event must survive) and
`test_refresh_rewrite_conflict_is_a_diagnostic` (`save` must receive the stored record and the legacy
hash; the page keeps the legacy hash); added `test_refresh_rewrite_encode_failure_is_a_diagnostic`.
Evidence, run in the feature worktree with `PYTHONPATH=packages/ai-parrot/src`: unmodified code gives
31 passed on `test_ingest.py`; `ruff check` and `black --check -l 120` are clean. Mutations of
`ingest.py`, each reverted with `git checkout --`:
`repo.save(record, stored_hash)` → the keeps-stored-record test fails (the conflict test fails too);
`repo.save(stored_record, None)` → the conflict test fails;
`decision_to_page` moved above `try:` → the encode-failure test fails.
`ingest.py` is not in the diff.

**Deviations from spec**: none. Both FILL IN markers were completed as bounded: the conflict test asserts
the page still holds the legacy hash; the encode-failure test asserts `clean.unchanged > 1` and
`result.unchanged == clean.unchanged - 1`.
