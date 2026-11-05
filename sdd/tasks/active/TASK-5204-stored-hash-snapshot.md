# TASK-5204: Decision snapshot compares stored page hashes

**Feature**: FEAT-807 — Decision snapshot compares stored hashes, so a legacy ADR envelope no longer blocks the gate
**Spec**: `sdd/specs/decisions-inventory-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:5918ff019737`

---

## Context

Implements spec §3 Module 1. `InventorySnapshot.take` compares `record_hash(record)` — the record
re-encoded with today's model — with the page hash the store holds. A page written by an older codec
re-encodes differently, so the check reports `SNAPSHOT_UNSTABLE` for every spec although nothing changed
(ledger `issue:5918ff019737`). The fix pairs each record with the hash of the page it was decoded from
and compares stored with stored.

---

## Scope

- Add `DecisionRepository.inventory_with_hashes()` returning `(record, stored content_hash)` pairs.
- Make `DecisionRepository.inventory()` delegate to it, with the same result as today.
- In `InventorySnapshot.take`, build the phase-one hash map from the stored hashes and keep the manifest
  equal to today's for canonical pages.
- Write the four new tests listed in the Test Specification.

**NOT in scope**: `decisions/ingest.py` (TASK-5205 / FEAT-808), the `SNAPSHOT_UNSTABLE` message, the
codec, `DecisionRecord`, and the return type of `inventory()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py` | MODIFY | add `inventory_with_hashes`; `inventory` delegates |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | MODIFY | `take()` uses stored hashes |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` | MODIFY | two tests in `TestInventory` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` | MODIFY | legacy-envelope and manifest tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.repository import DecisionRepository   # verified: decisions/repository.py:26
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, batch_marker_id, is_eligible, record_hash  # verified: decisions/inventory.py:64, :32, :53, :37
from parrot.knowledge.wiki.decisions.codec import decision_to_page          # verified: decisions/codec.py:180 (already imported at tests/.../test_repository.py:7)
from parrot.knowledge.wiki.decisions.models import DecisionRecord           # verified: tests/.../test_inventory.py:20
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord       # verified: tests/.../test_inventory.py:25
import hashlib                                                              # stdlib; not yet imported in test_inventory.py
import json                                                                 # already imported: tests/.../test_inventory.py:5
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
class DecisionRepository:                                                   # line 26
    self._store, self._max_records, self.logger                             # lines 39-41
    self.last_diagnostics: list[DecisionDiagnostic] = []                    # line 43
    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None   # line 45 — returns (decision_from_page(page), page.get("content_hash"))
    async def inventory(self) -> list[DecisionRecord]:                      # line 63, body to line 94
    #   self.last_diagnostics = []                                          # line 73
    #   stubs = await self._store.list_pages(category=ADR_CATEGORY, limit=self._max_records + 1)   # line 74
    #   raise DecisionError(ADR_INVENTORY_LIMIT, …) when len(stubs) > self._max_records            # lines 75-79
    #   page = await self._store.get_page(concept_id, include_body=True)    # line 83; None → continue
    #   records.append(decision_from_page(page)); DecisionError → self.last_diagnostics.append(DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id or concept_id))   # lines 88-93

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py
def record_hash(record: DecisionRecord) -> str                              # line 37
class SnapshotManifest(_Strict): inventory: dict[str, str]                  # lines 42-45
class InventorySnapshot:                                                    # line 64
    async def take(cls, repo, taxonomy, approvals, adapter, structural_revision, *, store, root, config_digest)   # line 80
    #   records = await repo.inventory()                                    # line 95
    #   diagnostics.extend(repo.last_diagnostics)                           # line 96
    #   hashes = {record.decision_id: record_hash(record) for record in records}   # line 97
    #   if await store.page_hashes(sorted(hashes)) != hashes:               # line 101
    #       raise DecisionError(SNAPSHOT_UNSTABLE, "decision inventory changed while reading")   # line 102
    #   inventory=hashes,                                                   # line 107 (SnapshotManifest argument)

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py
def decision_to_page(record: DecisionRecord) -> WikiPageRecord              # line 180 — body = f"{marker}\n{envelope}\n\n{markdown}", content_hash = sha1(envelope)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel)                                             # line 601 — pydantic: use .model_copy(update={...})
async def upsert_pages(self, pages: list[WikiPageRecord]) -> int            # BaseWikiStore, line 912 — keeps a supplied content_hash
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]   # BaseWikiStore, line 1242

# packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py
def _record(decision_id: str, **updates: object) -> DecisionRecord          # line 36
async def _snapshot(adr_store, tmp_path, repo: DecisionRepository | None = None) -> InventorySnapshot   # line 55
# fixture adr_store → InMemoryWikiStore (tests/knowledge/wiki/decisions/conftest.py:191)

# packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py
# fixtures: record (line 14), store (line 20); class TestInventory (line 116) is the last class in the file
```

### Does NOT Exist
- ~~`DecisionRepository.inventory_with_hashes`~~ — this task creates it.
- ~~`DecisionRecord.content_hash`~~ — the hash lives on the page row, not on the record.
- ~~`DecisionRepository.page_hashes`~~ — `page_hashes` is a store method.
- ~~a `legacy` fixture or helper in `conftest.py`~~ — the test builds the legacy page itself.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.inventory",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.get",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py#InventorySnapshot.take",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py#record_hash",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#decision_to_page"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `inventory()` keeps its signature and result; nine call sites depend on it.
- The `SNAPSHOT_UNSTABLE` message string does not change.
- For a page saved through `repo.save`, the manifest entry must equal `record_hash(record)` as today,
  or every rendered spec turns stale.
- Tests are plain `async def` (pytest-asyncio auto mode, as the rest of both test files).

### References in Codebase
- `decisions/repository.py:45-61` — `get()` already pairs a record with its page hash.
- `tests/knowledge/wiki/decisions/test_inventory.py:119-130` — the existing unstable-snapshot test.

---

## Implementation Blueprint

### Steps (in order)
1. Add `inventory_with_hashes()` to `DecisionRepository` by moving today's `inventory()` loop into it and
   appending `(record, page.get("content_hash"))` — *why*: the stability check needs the hash the store
   holds, and `get()` already returns it this way.
2. Reduce `inventory()` to a delegate — *why*: its callers must see no change.
3. In `take()`, read the pairs, derive `records` and the stored-hash map, compare that map with
   `store.page_hashes()` — *why*: comparing stored with stored is what "changed while reading" means.
4. Build the manifest inventory with `content_hash or record_hash(record)` — *why*: `SnapshotManifest.inventory`
   is `dict[str, str]`, and for canonical pages the stored hash already equals `record_hash`.
5. Add the tests and run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def inventory(self) -> list[DecisionRecord]:' repository.py)
# REPLACE the method `inventory` (verified: repository.py:63-94) with the two methods below.
    async def inventory_with_hashes(self) -> list[tuple[DecisionRecord, str | None]]:
        """Load the complete bounded ADR inventory with each page's stored ``content_hash``.

        Reads ``limit=max_records + 1`` so an overflow is detectable rather
        than silently truncated into a wrong "no decisions" answer. The hash
        is the one the store holds for the page the record was decoded from —
        compare against it, never against a re-encoded record.

        Raises:
            DecisionError: ``ADR_INVENTORY_LIMIT`` when the plane holds more
                than ``max_records`` ADR pages.
        """
        self.last_diagnostics = []
        stubs = await self._store.list_pages(category=ADR_CATEGORY, limit=self._max_records + 1)
        if len(stubs) > self._max_records:
            raise DecisionError(
                ADR_INVENTORY_LIMIT,
                f"ADR inventory exceeds max_records={self._max_records}; raise the bound or prune records",
            )
        pairs: list[tuple[DecisionRecord, str | None]] = []
        for stub in stubs:
            concept_id = stub.get("concept_id")
            page = await self._store.get_page(concept_id, include_body=True)
            if page is None:
                # Deleted between list_pages() and get_page() — not an
                # inventory-level error, just skip it.
                continue
            try:
                pairs.append((decision_from_page(page), page.get("content_hash")))
            except DecisionError as exc:
                self.last_diagnostics.append(
                    DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id or concept_id)
                )
        return pairs

    async def inventory(self) -> list[DecisionRecord]:
        """Load the complete bounded ADR inventory.

        Raises:
            DecisionError: ``ADR_INVENTORY_LIMIT`` when the plane holds more
                than ``max_records`` ADR pages.
        """
        return [record for record, _content_hash in await self.inventory_with_hashes()]
```
**Why this shape**: the loop is today's, moved unchanged apart from what it appends, so bounds, the
deleted-page skip and `last_diagnostics` behave exactly as before. Do not change `get()` or `save()`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        records = await repo.inventory()' inventory.py)
# REPLACE `        records = await repo.inventory()` (verified: inventory.py:95) with:
        pairs = await repo.inventory_with_hashes()
        records = [record for record, _content_hash in pairs]

# occurrences: 1 (verified: grep -cF '        hashes = {record.decision_id: record_hash(record) for record in records}' inventory.py)
# REPLACE that line (verified: inventory.py:97) with:
        # Stored hashes, not re-encoded ones: a page written by an older codec re-encodes
        # differently although it did not change (issue:5918ff019737).
        stored = {record.decision_id: content_hash for record, content_hash in pairs}

# occurrences: 1 (verified: grep -cF '        if await store.page_hashes(sorted(hashes)) != hashes:' inventory.py)
# REPLACE that line (verified: inventory.py:101) with:
        if await store.page_hashes(sorted(stored)) != stored:

# occurrences: 1 (verified: grep -cF '            inventory=hashes,' inventory.py)
# REPLACE that line (verified: inventory.py:107) with:
            inventory={record.decision_id: content_hash or record_hash(record) for record, content_hash in pairs},
```
**Why**: the raised error and its message on the next line stay as they are. `record_hash` remains in use
for the manifest fallback, so its definition and import stay.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'class TestInventory:' test_repository.py)
# AFTER — append these methods at the END of `class TestInventory:` (verified: test_repository.py:116;
# it is the last class, so this is the end of the file). Keep the 4-space method indentation.
    async def test_inventory_with_hashes_pairs_stored_hash(self, store):
        """Each record comes with the hash the store holds for its page."""
        repo = DecisionRepository(store)
        for i in range(2):
            await repo.save(DecisionRecord(decision_id=f"adr:doc:{i}", decision=f"d{i}", origin="documented"), None)
        pairs = await repo.inventory_with_hashes()
        assert {record.decision_id for record, _ in pairs} == {"adr:doc:0", "adr:doc:1"}
        stored = await store.page_hashes([record.decision_id for record, _ in pairs])
        assert all(content_hash == stored[record.decision_id] for record, content_hash in pairs)
        assert all(content_hash for _, content_hash in pairs)

    async def test_inventory_delegates_to_inventory_with_hashes(self, store, record):
        """``inventory()`` returns exactly the records of ``inventory_with_hashes()``."""
        repo = DecisionRepository(store)
        await repo.save(record, None)
        pairs = await repo.inventory_with_hashes()
        assert await repo.inventory() == [paired for paired, _ in pairs]
        assert repo.last_diagnostics == []
```
**Why**: the first test pins the pairing against the store's own view; the second pins the delegate.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'import json' test_inventory.py → line 5)
# BEFORE — insert above `import json` (verified: test_inventory.py:5):
import hashlib

# occurrences: 1 (verified: grep -cF 'from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, batch_marker_id, is_eligible' test_inventory.py)
# REPLACE that import line (verified: test_inventory.py:12) with:
from parrot.knowledge.wiki.decisions.codec import decision_to_page
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, batch_marker_id, is_eligible, record_hash

# occurrences: 1 (verified: grep -cF 'async def test_inventory_overflow_raises(adr_store, tmp_path) -> None:' test_inventory.py)
# BEFORE — insert above the function `test_inventory_overflow_raises` (verified: test_inventory.py:133),
# i.e. right after `test_snapshot_unstable_is_incomplete`:
_SCHEMA_2_KEYS = (
    "about", "batch_id", "contradicts", "document_id", "entry_id", "lifecycle",
    "normative", "rationale", "rejected_alternatives", "supersedes_refs", "targets",
)


def _legacy_page(record: DecisionRecord) -> WikiPageRecord:
    """The page an older codec wrote: no schema-2 keys in the envelope, hash of that envelope."""
    page = decision_to_page(record)
    marker, envelope, rest = page.body.split("\n", 2)
    payload = json.loads(envelope)
    for key in _SCHEMA_2_KEYS:
        payload.pop(key, None)
    legacy = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    content_hash = hashlib.sha1(legacy.encode("utf-8")).hexdigest()  # noqa: S324 — identity, not security
    return page.model_copy(update={"body": f"{marker}\n{legacy}\n{rest}", "content_hash": content_hash})


async def test_snapshot_stable_with_legacy_envelope(adr_store, tmp_path) -> None:
    """An unchanged page written by an older codec is not reported as changed (issue:5918ff019737)."""
    record = _record("adr:doc:legacy")
    legacy = _legacy_page(record)
    assert legacy.content_hash != record_hash(record)  # the precondition this bug needs
    await adr_store.upsert_pages([legacy])

    snapshot = await _snapshot(adr_store, tmp_path)

    # FILL IN: assert the record is in the snapshot's eligible set and that
    # snapshot.manifest.inventory["adr:doc:legacy"] == legacy.content_hash — bounded by spec AC-1.


async def test_snapshot_manifest_unchanged_for_canonical_pages(adr_store, tmp_path) -> None:
    """For pages saved by the current codec the manifest is byte-identical to before (spec G3)."""
    repo = DecisionRepository(adr_store)
    records = [_record("adr:doc:one"), _record("adr:doc:two")]
    for record in records:
        await repo.save(record, None)

    snapshot = await _snapshot(adr_store, tmp_path, repo)

    assert snapshot.manifest.inventory == {record.decision_id: record_hash(record) for record in records}
```
**Why**: the legacy test fails on today's code with `SNAPSHOT_UNSTABLE` and passes after the change; the
manifest test guards G3. `_legacy_page` drops only keys whose value is the model default, so the page
still decodes to an equal record.

### FILL IN checklist
- [ ] `test_inventory.py::test_snapshot_stable_with_legacy_envelope` — the two assertions on the
  snapshot; bounded by spec Acceptance Criterion 1 (use `snapshot.eligible` and `snapshot.manifest`,
  both set in `InventorySnapshot.__init__`, inventory.py:67-77).
- [ ] If `ruff` reports an unused name after the `inventory.py` edit, remove only that name.

---

## Acceptance Criteria

- [ ] A plane holding an ADR page written without the schema-2 fields produces a snapshot.
- [ ] `test_snapshot_unstable_is_incomplete` still passes: a changed phase-two hash raises `SNAPSHOT_UNSTABLE`.
- [ ] For canonical pages `manifest.inventory` equals `{id: record_hash(record)}`.
- [ ] `DecisionRepository.inventory()` returns the same list as before.
- [ ] `ruff check` reports nothing on the four files.
- [ ] `test_snapshot_stable_with_legacy_envelope` fails on the base commit and passes on this branch.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py -q`

---

## Test Specification

The four tests are given in full in the Implementation Blueprint above (two in `test_repository.py`,
two in `test_inventory.py`); the only open part is the FILL IN in
`test_snapshot_stable_with_legacy_envelope`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug decisions-inventory-fixes --feature-id FEAT-807`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in `sdd/tasks/index/decisions-inventory-fixes.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** with the Validation Commands, using `PYTHONPATH=packages/ai-parrot/src` inside the worktree
8. **Commit the code** — stage only the four files this task lists
9. **Close the task** with `parrot sdd task close TASK-5204 decisions-inventory-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
