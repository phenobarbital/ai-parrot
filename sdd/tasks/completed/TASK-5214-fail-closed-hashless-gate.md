# TASK-5214: Fail the snapshot closed when a decision page has no stored content hash

**Feature**: FEAT-810 — A hashless ADR page fails the snapshot closed, and the manifest no longer depends on the stored envelope shape
**Spec**: `sdd/specs/decisions-inventory-fixes-2.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:c7f16ecf903e`

---

## Context

Implements spec §3 Module 1 (goal **G1**).

FEAT-807 (PR #1959) changed `InventorySnapshot.take` to compare the hash the store held at the first
read with the hash it holds at the second read. `DecisionRepository.inventory_with_hashes()` returns
`page.get("content_hash")`, which is `None` for a page row that stores no hash, and
`BaseWikiStore.page_hashes` / `SQLiteWikiStore.page_hashes` also return `None` for an **absent** row.
So for a hashless ADR page phase one yields `None` and phase two yields `None` whether that page was
rewritten or deleted outright between the two reads: `stored == await store.page_hashes(...)` holds and
the snapshot silently includes a record that may no longer exist.

Before FEAT-807 the phase-one value was `record_hash(record)`, which is never `None`, so a hashless page
always raised `SNAPSHOT_UNSTABLE` — the gate failed closed. This task restores that property without
touching the stored-hash comparison FEAT-807 introduced.

---

## Scope

- Add a precondition to `InventorySnapshot.take`: when any decision's phase-one stored hash is `None`,
  raise `DecisionError(SNAPSHOT_UNSTABLE, ...)` naming the offending decision ids, before the phase-two
  comparison runs.
- Add a test that a page upserted with `content_hash=None` raises `SNAPSHOT_UNSTABLE` and that the
  message names the decision id.
- Add the regression test the ledger issue asks for: a hashless page deleted between the two reads
  raises instead of being included in `snapshot.eligible`.
- Strengthen the existing `test_inventory_delegates_to_inventory_with_hashes` to use several records
  **plus one malformed page**, asserting ordering parity and that `last_diagnostics` is the same through
  both `inventory()` and `inventory_with_hashes()`.

**NOT in scope**:
- The `SnapshotManifest.inventory` comprehension at `inventory.py:110` — that is TASK-5215.
- Changing `DecisionRepository.inventory_with_hashes()`, the codec, `DecisionRecord`, or the
  `SNAPSHOT_UNSTABLE` code string.
- Making `page_hashes` distinguish an absent row from a row with a NULL hash (spec Non-Goals).
- Backfilling `content_hash` on existing pages.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | MODIFY | Hashless precondition in `InventorySnapshot.take` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` | MODIFY | `_hashless_page` helper + two new tests |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` | MODIFY | Strengthen the delegation test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `b3a10aafa1`. Use these exact imports, names and signatures.
> If anything has changed, update this contract FIRST, then implement.

### Verified Imports

```python
# already imported in inventory.py — add nothing
from parrot.knowledge.wiki.decisions.models import SNAPSHOT_UNSTABLE, DecisionError  # verified: inventory.py:14, :17

# already imported in test_inventory.py — add nothing
from parrot.knowledge.wiki.decisions.codec import decision_to_page            # verified: test_inventory.py:13
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, record_hash  # verified: test_inventory.py:14
from parrot.knowledge.wiki.decisions.models import SNAPSHOT_UNSTABLE, DecisionError, DecisionRecord  # verified: test_inventory.py:15-23
from parrot.knowledge.wiki.decisions.repository import DecisionRepository     # verified: test_inventory.py:25
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord         # verified: test_inventory.py:27
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py
def record_hash(record: DecisionRecord) -> str                                 # line 37
class InventorySnapshot:                                                       # line 64
    @classmethod
    async def take(cls, repo, taxonomy, approvals, adapter, structural_revision, *,
                   store, root, config_digest) -> "InventorySnapshot"          # line 80
    #   pairs = await repo.inventory_with_hashes()                             # line 95
    #   stored = {record.decision_id: content_hash for record, content_hash in pairs}  # line 100
    #   if await store.page_hashes(sorted(stored)) != stored:                  # line 104

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
async def inventory_with_hashes(self) -> list[tuple[DecisionRecord, str | None]]  # line 63; hash = page.get("content_hash") (line 90)
async def inventory(self) -> list[DecisionRecord]                                 # line 98 — delegates (line 105)
self.last_diagnostics: list[DecisionDiagnostic]                                   # line 43, reset at line 75

# packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py — reuse, do not redefine
def _record(decision_id: str, **updates: object) -> DecisionRecord             # line 38
async def _snapshot(adr_store, tmp_path, repo: DecisionRepository | None = None) -> InventorySnapshot  # line 57
def _legacy_page(record: DecisionRecord) -> WikiPageRecord                     # line 150 — keeps content_hash SET

# packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py
async def adr_store(tmp_path)                                                  # line 191 — InMemoryWikiStore
# test_repository.py uses the `store` and `record` fixtures; ADR_CATEGORY and WikiPageRecord
# are already imported there (see test_one_corrupt_page_becomes_a_diagnostic, line 145).
```

### Does NOT Exist

- ~~`SNAPSHOT_HASHLESS`, `ADR_HASH_MISSING`~~ — no such code anywhere under
  `packages/ai-parrot/src/parrot/knowledge/wiki/` (verified: 0 files match). Reuse `SNAPSHOT_UNSTABLE`.
- ~~`store.page_exists`~~ / ~~a `page_hashes` variant distinguishing absent from NULL~~ — not in `store.py`.
- ~~`DecisionRecord.content_hash`~~ — the hash lives on the page row only.
- ~~`_hashless_page` in `test_inventory.py`~~ — created by this task (verified: 0 occurrences).
- ~~`DecisionRepository.page_hashes`~~ — `page_hashes` is a **store** method.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py#InventorySnapshot.take",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py#record_hash",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.inventory_with_hashes",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.page_hashes"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Fail closed: a gate that cannot verify its input refuses, it does not assume. The existing
phase-two comparison right below is the model for the raise — same error class, same code,
a message that says what could not be verified.

### Key Constraints

- The new check runs **before** `store.page_hashes(...)` so the error names the real cause
  ("no stored content hash") instead of a mismatch that would never occur.
- Do **not** change the existing comparison at `inventory.py:104-105` — FEAT-807 (`issue:5918ff019737`)
  depends on it comparing stored hashes, and `test_snapshot_stable_with_legacy_envelope` proves it.
- `_legacy_page` keeps `content_hash` set, so it is unaffected by this task.
- `repo.save` always sets a hash; `adr_store.upsert_pages` is what writes a page out-of-band.
- Line length 120, Google-style docstrings, `ruff check --fix` on the changed files.

### References in Codebase

- `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py:121` —
  `test_snapshot_unstable_is_incomplete`, the pattern for asserting `exc.value.code == SNAPSHOT_UNSTABLE`.
- `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py:145` —
  `test_one_corrupt_page_becomes_a_diagnostic`, the pattern for upserting a malformed ADR page.

---

## Implementation Blueprint

### Steps (in order)

1. Insert the hashless precondition in `InventorySnapshot.take`, directly above the existing
   `store.page_hashes` comparison — *why*: the comparison below cannot distinguish "unchanged" from
   "gone" when both sides are `None`, so the read must be refused before it is trusted.
2. Extend the comment at `inventory.py:98-99` to say the stored hashes are the stability check's input
   and that a missing one is unverifiable — *why*: the next reader must not re-introduce a `None`-tolerant
   comparison.
3. Add `_hashless_page` to `test_inventory.py` next to `_legacy_page` — *why*: `repo.save` cannot produce
   a hashless page, so the test must write one out-of-band.
4. Add the two new tests — *why*: AC-1 and AC-2; the deletion case is the regression the ledger issue names.
5. Strengthen `test_inventory_delegates_to_inventory_with_hashes` — *why*: one valid record establishes
   neither ordering nor diagnostics parity (the companion test gap in `issue:c7f16ecf903e`).
6. Run the Validation Commands — *why*: AC-7, and `test_snapshot_stable_with_legacy_envelope` must still
   pass, proving FEAT-807 did not regress.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'if await store.page_hashes(sorted(stored)) != stored:' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py)
# BEFORE — insert above `        if await store.page_hashes(sorted(stored)) != stored:` (verified: inventory.py:104)
        unverifiable = sorted(decision_id for decision_id, content_hash in stored.items() if content_hash is None)
        if unverifiable:
            raise DecisionError(
                SNAPSHOT_UNSTABLE,
                "decision pages have no stored content hash, so a mid-read change cannot be detected: "
                + ", ".join(unverifiable),
            )
```

**Why**: `page_hashes` returns `None` both for a row that is gone and for a row whose hash is NULL, so a
`None` on the phase-one side makes the two-phase comparison vacuous. Refusing here restores the
pre-FEAT-807 fail-closed behaviour. Keep it above the existing comparison — the existing comparison, its
message and `SNAPSHOT_UNSTABLE` itself must not change.

```python
# occurrences: 1 (verified: grep -c 'stored = {record.decision_id: content_hash for record, content_hash in pairs}' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py)
# REPLACE the comment above `        stored = {record.decision_id: content_hash for record, content_hash in pairs}` (verified: inventory.py:98-100)
        # Stored hashes, not re-encoded ones: a page written by an older codec re-encodes
        # differently although it did not change (issue:5918ff019737). A page with no stored
        # hash cannot be compared at all, so the snapshot refuses it below (issue:c7f16ecf903e).
```

**Why**: documents both halves of the invariant at the one place a future change would break it.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def _legacy_page(record: DecisionRecord) -> WikiPageRecord:' packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py)
# AFTER — append below the body of `def _legacy_page(record: DecisionRecord) -> WikiPageRecord:` (verified: test_inventory.py:150-159)


def _hashless_page(record: DecisionRecord) -> WikiPageRecord:
    """The out-of-band page B1 needs: a canonical envelope whose row stores no content hash."""
    return decision_to_page(record).model_copy(update={"content_hash": None})


async def test_snapshot_unstable_when_a_page_has_no_stored_hash(adr_store, tmp_path) -> None:
    """A page the store holds no hash for cannot be verified, so the snapshot refuses it."""
    record = _record("adr:doc:hashless")
    await adr_store.upsert_pages([_hashless_page(record)])

    with pytest.raises(DecisionError) as exc:
        await _snapshot(adr_store, tmp_path)

    assert exc.value.code == SNAPSHOT_UNSTABLE
    assert "adr:doc:hashless" in str(exc.value)


async def test_snapshot_unstable_when_a_hashless_page_disappears_mid_read(
    adr_store, tmp_path, monkeypatch
) -> None:
    """The regression of issue:c7f16ecf903e: None == None must not read as 'unchanged'."""
    record = _record("adr:doc:hashless")
    await adr_store.upsert_pages([_hashless_page(record)])

    async def gone(ids: list[str]) -> dict[str, str | None]:
        """Phase two for a page deleted between the reads: None, exactly as for a null hash."""
        return dict.fromkeys(ids)

    monkeypatch.setattr(adr_store, "page_hashes", gone)
    with pytest.raises(DecisionError) as exc:
        await _snapshot(adr_store, tmp_path)

    assert exc.value.code == SNAPSHOT_UNSTABLE
```

**Why this shape**: `_hashless_page` mirrors `_legacy_page` (same `decision_to_page` starting point,
one field altered) so the two out-of-band page shapes read alike. The second test monkeypatches
`page_hashes` the way `test_snapshot_unstable_is_incomplete` (test_inventory.py:121) does, but returns
`None` rather than `"changed"` — that is precisely the value a deleted page produces, and the value the
old code accepted. Do not assert on the exact message wording beyond the decision id.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    async def test_inventory_delegates_to_inventory_with_hashes(self, store, record):' packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py)
# REPLACE the whole method `    async def test_inventory_delegates_to_inventory_with_hashes(self, store, record):` (verified: test_repository.py:188-194)
    async def test_inventory_delegates_to_inventory_with_hashes(self, store):
        """``inventory()`` returns the records of ``inventory_with_hashes()``, in order, with the same diagnostics."""
        repo = DecisionRepository(store)
        for i in range(3):
            await repo.save(
                DecisionRecord(decision_id=f"adr:doc:{i}", decision=f"decision {i}", origin="documented"), None
            )
        await store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id="adr:doc:garbage",
                    title="garbage",
                    category=ADR_CATEGORY,
                    body="not a valid envelope at all",
                )
            ]
        )

        pairs = await repo.inventory_with_hashes()
        paired_diagnostics = list(repo.last_diagnostics)
        records = await repo.inventory()

        assert records == [paired for paired, _ in pairs]
        # FILL IN: assert the ordering is the concrete one both methods produce — bounded by AC-6
        # (list_pages order; assert the explicit [ "adr:doc:0", "adr:doc:1", "adr:doc:2" ] list if it is
        # deterministic for InMemoryWikiStore, else assert sorted() equality AND len(records) == 3)
        assert [diagnostic.code for diagnostic in repo.last_diagnostics] == [
            diagnostic.code for diagnostic in paired_diagnostics
        ]
        assert [diagnostic.code for diagnostic in repo.last_diagnostics] == ["ADR_SCHEMA_UNSUPPORTED"]
```

**Why**: the old body used a single valid record, so it proved only that two one-element lists matched —
it could not detect a reordering or a diagnostics path that differs between the two methods. Three
records plus one undecodable page exercise both. The `record` fixture is dropped from the signature
because the test now builds its own records; `WikiPageRecord` and `ADR_CATEGORY` are already imported in
this module (used at test_repository.py:145-155).

### FILL IN checklist

- [ ] `test_repository.py::test_inventory_delegates_to_inventory_with_hashes` — the concrete ordering
  assertion; bounded by AC-6 (must fail if either method reorders, so a bare `set()` comparison is not
  acceptable).

---

## Acceptance Criteria

- [ ] AC-1 — An ADR page stored without a `content_hash` makes `InventorySnapshot.take` raise
  `DecisionError` with code `SNAPSHOT_UNSTABLE`, and the message names the offending decision id.
- [ ] AC-2 — A hashless page deleted between the two reads raises instead of appearing in
  `snapshot.eligible`.
- [ ] AC-3 — `test_snapshot_stable_with_legacy_envelope` still passes unmodified: an unchanged legacy
  envelope still yields a snapshot (FEAT-807 does not regress).
- [ ] AC-4 — `test_snapshot_unstable_is_incomplete` still passes unmodified.
- [ ] AC-5 — `test_snapshot_manifest_unchanged_for_canonical_pages` still passes unmodified.
- [ ] AC-6 — `test_inventory_delegates_to_inventory_with_hashes` establishes ordering and diagnostics
  parity over several records including a malformed page.
- [ ] AC-7 — All Validation Commands pass.
- [ ] AC-8 — No change to any public signature in `parrot.knowledge.wiki.decisions`.
- [ ] AC-9 — No linting errors: `ruff check` on the three changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences.py -q`

---

## Test Specification

New tests land in the existing `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py`
(module-level async functions, matching the file's existing style — it has no test class) and in the
existing `TestInventory` class of `test_repository.py`. No new test file is created. Reuse `adr_store`,
`_record`, `_snapshot`, `store` and the module's existing imports; add no new imports.

| Test | Asserts |
|---|---|
| `test_snapshot_unstable_when_a_page_has_no_stored_hash` | `SNAPSHOT_UNSTABLE` + decision id in the message |
| `test_snapshot_unstable_when_a_hashless_page_disappears_mid_read` | `SNAPSHOT_UNSTABLE` when phase two returns `None` |
| `test_inventory_delegates_to_inventory_with_hashes` | record ordering parity + `last_diagnostics` parity |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug decisions-inventory-fixes-2 --feature-id FEAT-810`)
2. **Read the spec** at `sdd/specs/decisions-inventory-fixes-2.spec.md`
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code; if anything moved, fix the contract first
5. **Update status** in `sdd/tasks/index/decisions-inventory-fixes-2.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete the `FILL IN` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the three files this task lists (never `git add .` / `-A`)
9. **Close the task** with
   `parrot sdd task close TASK-5214 decisions-inventory-fixes-2 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 244.5s · Tokens: n/a

**Completed by**: sdd-worker orchestrator (coder seat gpt-5.6-terra, attempt d7e52284019a4e71b5c03f5135e6af3e)
**Date**: 2026-11-05
**Notes**: Hashless-page gate added to `InventorySnapshot` (inventory.py) before the `page_hashes` compare; raises `SNAPSHOT_UNSTABLE` naming the unverifiable ids. Tests added in test_inventory.py / test_repository.py. Merge-tier validation green (54 passed, handle 560c78fa-...:TASK-5214:merge). Orchestrator reviewed the diff against the blueprint: no deviations, fidelity_ok. `coder_record_review` failed server-side (`CoderReview() argument after ** must be a mapping`), so review was NOT recorded in the feedback plane and no feedback was filed (no defects found).

**Deviations from spec**: none
