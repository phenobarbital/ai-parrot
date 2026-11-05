# TASK-5215: Derive the snapshot manifest from the decoded records, not the stored envelope

**Feature**: FEAT-810 — A hashless ADR page fails the snapshot closed, and the manifest no longer depends on the stored envelope shape
**Spec**: `sdd/specs/decisions-inventory-fixes-2.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5214
**Assigned-to**: unassigned

**Discovered-from**: `issue:d219d0707031`

---

## Context

Implements spec §3 Module 2 (goals **G2**, **G3**).

`SnapshotManifest.inventory` is built as `content_hash or record_hash(record)` (`inventory.py:110`), so
for a page with a legacy envelope it holds the stored **legacy** hash. When the FEAT-808 ingest (merged
in PR #1960) later rewrites that page to its canonical envelope the stored hash changes, the manifest
changes, the `input_digest` that `ConsequenceService.evaluate` derives from it changes, and every spec
rendered in between reports stale generated sections (exit 3) and must be re-rendered and re-committed.
The same manifest also differs between a clone holding legacy pages and one holding canonical pages
until the first clone runs a full ingest.

`record_hash` is the sha1 of `canonical_json(record)` — a function of the decoded record, so it is the
same whichever envelope the record came out of. Using it for every decision makes the manifest describe
the decisions rather than their storage encoding, and costs nothing: for a canonical page the stored
hash already equals `record_hash(record)` (`decision_to_page` stores exactly `sha1(canonical envelope)`),
which is why **G3** holds and the existing
`test_snapshot_manifest_unchanged_for_canonical_pages` keeps passing unmodified.

Depends on TASK-5214: both tasks edit `InventorySnapshot.take` and `test_inventory.py`, within a few
lines of each other.

---

## Scope

- Change the `SnapshotManifest.inventory` comprehension in `InventorySnapshot.take` to use
  `record_hash(record)` for every decision, ignoring the stored `content_hash`.
- Update the existing `test_snapshot_stable_with_legacy_envelope` assertion: the snapshot still
  succeeds (that is the point of FEAT-807), but the manifest value is now `record_hash(record)`.
- Add a test that a legacy page and a canonical page of the same record yield the same
  `manifest.inventory` value.

**NOT in scope**:
- The hashless precondition and the `test_repository.py` delegation test — those are TASK-5214.
- The stability comparison at `inventory.py:104-105`, which must keep comparing **stored** hashes.
- `ConsequenceService`, the `input_digest` computation, `consequences.py`, or any rendered spec.
- Re-rendering specs whose `input_digest` changes because of this task — none should, since no ADR page
  on `dev` is legacy after FEAT-808.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | MODIFY | Manifest comprehension uses `record_hash` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` | MODIFY | Update one assertion; add one test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `b3a10aafa1`. TASK-5214 lands first and inserts lines into
> `InventorySnapshot.take` **above** line 104, so the manifest block will have moved down by roughly
> seven lines. Locate it by its verbatim anchor text, not by line number.

### Verified Imports

```python
# already imported in inventory.py — add nothing
from parrot.knowledge.wiki.decisions.codec import canonical_json             # verified: inventory.py:11
from parrot.knowledge.wiki.decisions.models import DecisionRecord            # verified: inventory.py:18

# already imported in test_inventory.py — add nothing
from parrot.knowledge.wiki.decisions.codec import decision_to_page           # verified: test_inventory.py:13
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, record_hash  # verified: test_inventory.py:14
from parrot.knowledge.wiki.decisions.repository import DecisionRepository    # verified: test_inventory.py:25
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord        # verified: test_inventory.py:27
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py
def record_hash(record: DecisionRecord) -> str                               # line 37 — sha1(canonical_json(record))
class SnapshotManifest(_Strict):                                             # line 42
    inventory: dict[str, str]                                                # line 45 — type UNCHANGED by this task
    taxonomy_digest: str                                                     # line 46
    approvals_digest: str                                                    # line 47
    structural_revision: str                                                 # line 48
    rules_version: int                                                       # line 49
    config_digest: str                                                       # line 50
#   manifest = SnapshotManifest(inventory={... content_hash or record_hash(record) ...}, …)  # lines 109-116

# packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py — reuse, do not redefine
def _record(decision_id: str, **updates: object) -> DecisionRecord           # line 38
async def _snapshot(adr_store, tmp_path, repo: DecisionRepository | None = None) -> InventorySnapshot  # line 57
def _legacy_page(record: DecisionRecord) -> WikiPageRecord                   # line 150 — envelope stripped, content_hash = sha1(that envelope)
async def test_snapshot_stable_with_legacy_envelope(adr_store, tmp_path) -> None   # line 162 — MODIFY its assertion
async def test_snapshot_manifest_unchanged_for_canonical_pages(adr_store, tmp_path) -> None  # line 175 — MUST stay unmodified

# packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py
async def adr_store(tmp_path)                                                # line 191 — InMemoryWikiStore
```

### Does NOT Exist

- ~~`SnapshotManifest.envelope_hashes`~~ / ~~`SnapshotManifest.stored_hashes`~~ — the model has exactly
  the six fields listed above; this task adds none.
- ~~`record_hash(page)`~~ — `record_hash` takes a `DecisionRecord`, never a page or a dict.
- ~~`canonical_json(page)`~~ — same, it takes a `DecisionRecord` (`inventory.py:39`).
- ~~`DecisionRecord.content_hash`~~ — the hash lives on the page row only.

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
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py#InventorySnapshot.take",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py#SnapshotManifest",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py#record_hash"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Keep the two hash sources distinct and say so: the **stability check** reads stored hashes (FEAT-807,
`issue:5918ff019737`); the **manifest** reads records. They are deliberately different and a future
change must not collapse them.

### Key Constraints

- `SnapshotManifest.inventory` stays typed `dict[str, str]` — `record_hash` always returns a `str`, so
  the `or` fallback that existed for `None` is no longer needed and must be removed, not kept.
- `test_snapshot_manifest_unchanged_for_canonical_pages` (`test_inventory.py:175`) must pass
  **unmodified**. If it needs editing, G3 is broken and the change is wrong — stop and report.
- The loop variable for the discarded hash is `_content_hash` (leading underscore), matching the style
  already used at `inventory.py:96` and `repository.py:105`.
- Line length 120, Google-style docstrings, `ruff check --fix` on the changed files.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py:343` —
  `ConsequenceService.evaluate`, the consumer whose `input_digest` this manifest feeds.
- `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py:175` —
  `test_snapshot_manifest_unchanged_for_canonical_pages`, the G3 guard.

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-5214 is `done` in the per-spec index and present in the worktree — *why*: it edits the
   same function, and its insertion shifts every line number below `inventory.py:100`.
2. Replace the manifest comprehension — *why*: AC-1; a hash derived from the record is invariant under
   the FEAT-808 envelope rewrite, which is the whole point of `issue:d219d0707031`.
3. Update the assertion in `test_snapshot_stable_with_legacy_envelope` — *why*: it currently asserts the
   legacy stored hash; it must now assert `record_hash(record)` while still proving the snapshot succeeded.
4. Add `test_snapshot_manifest_is_independent_of_the_stored_envelope` — *why*: AC-2, the property the
   issue actually asks for, which neither existing test covers.
5. Run the Validation Commands and confirm `test_snapshot_manifest_unchanged_for_canonical_pages` passed
   without being edited — *why*: AC-3 (G3).

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'inventory={record.decision_id: content_hash or record_hash(record) for record, content_hash in pairs},' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py)
# REPLACE the line `            inventory={record.decision_id: content_hash or record_hash(record) for record, content_hash in pairs},` (verified: inventory.py:110 at b3a10aafa1; shifted down by TASK-5214 — match on the text)
            # The manifest describes the decisions, not the envelope they are stored in: a legacy and a
            # canonical page of the same record hash alike, so the FEAT-808 rewrite does not stale a
            # rendered spec (issue:d219d0707031). The stability check above still uses stored hashes.
            inventory={record.decision_id: record_hash(record) for record, _content_hash in pairs},
```

**Why**: `record_hash` is `sha1(canonical_json(record))`, computed from the decoded model, so it is
invariant under a change of stored envelope shape. For a canonical page it already equals the stored
hash (`decision_to_page` stores `sha1(canonical envelope)`), so manifests on canonical planes do not
move — that invariance is G3 and is what lets this change ship without re-rendering any spec. Do not
keep the `or` fallback: with `record_hash` there is nothing to fall back from.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def test_snapshot_stable_with_legacy_envelope(adr_store, tmp_path) -> None:' packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py)
# REPLACE the last line of `async def test_snapshot_stable_with_legacy_envelope` (verified: test_inventory.py:172),
# namely `    assert snapshot.manifest.inventory == {"adr:doc:legacy": legacy.content_hash}`
    assert snapshot.manifest.inventory == {"adr:doc:legacy": record_hash(record)}
    assert snapshot.manifest.inventory["adr:doc:legacy"] != legacy.content_hash  # issue:d219d0707031
```

**Why**: the test's purpose — an unchanged legacy envelope still produces a snapshot — is unchanged and
the two assertions above it stay as they are. Only the manifest value moves, from the stored legacy hash
to the record hash. The second line pins the new property explicitly; it holds because the test already
asserts `legacy.content_hash != record_hash(record)` as its precondition (test_inventory.py:166).

```python
# occurrences: 1 (verified: grep -c 'async def test_snapshot_manifest_unchanged_for_canonical_pages(adr_store, tmp_path) -> None:' packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py)
# AFTER — append below the body of `async def test_snapshot_manifest_unchanged_for_canonical_pages` (verified: test_inventory.py:175-184; leave that test UNMODIFIED)


async def test_snapshot_manifest_is_independent_of_the_stored_envelope(adr_store, tmp_path) -> None:
    """The same decision hashes alike whether its page is legacy or canonical (issue:d219d0707031)."""
    record = _record("adr:doc:same")

    await adr_store.upsert_pages([_legacy_page(record)])
    legacy_manifest = (await _snapshot(adr_store, tmp_path)).manifest.inventory

    await DecisionRepository(adr_store).save(record, None)
    # FILL IN: assert the page is now canonical before re-reading — bounded by AC-2; a save that
    # silently no-opped would make the two manifests match for the wrong reason
    canonical_manifest = (await _snapshot(adr_store, tmp_path)).manifest.inventory

    assert legacy_manifest == canonical_manifest == {"adr:doc:same": record_hash(record)}
```

**Why this shape**: the same `DecisionRecord` is read twice from two different stored encodings of it,
which is exactly the before/after of the FEAT-808 ingest rewrite that `issue:d219d0707031` describes.
Asserting both manifests equal `record_hash(record)` proves the value is the record's, not the page's.
`_legacy_page` and `_record` already exist — do not redefine them.

### FILL IN checklist

- [ ] `test_inventory.py::test_snapshot_manifest_is_independent_of_the_stored_envelope` — the assertion
  that the second read really sees a canonical page; bounded by AC-2 (compare the page's stored
  `content_hash` against `record_hash(record)`, or against the legacy page's hash, so a no-op `save`
  cannot make the test pass vacuously).

---

## Acceptance Criteria

- [ ] AC-1 — `SnapshotManifest.inventory[decision_id] == record_hash(record)` for every decision,
  whatever envelope its page holds; the `content_hash or …` fallback is gone.
- [ ] AC-2 — A legacy page and a canonical page of the same record produce the same
  `manifest.inventory`.
- [ ] AC-3 — `test_snapshot_manifest_unchanged_for_canonical_pages` passes **unmodified** (G3).
- [ ] AC-4 — `test_snapshot_stable_with_legacy_envelope` still proves the snapshot succeeds for an
  unchanged legacy envelope (FEAT-807 does not regress).
- [ ] AC-5 — `SnapshotManifest.inventory` is still typed `dict[str, str]`; no field added or removed.
- [ ] AC-6 — All Validation Commands pass.
- [ ] AC-7 — No change to any public signature in `parrot.knowledge.wiki.decisions`.
- [ ] AC-8 — No linting errors: `ruff check` on the two changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequence_digests.py -q`

---

## Test Specification

One assertion updated and one test added, both in the existing
`packages/ai-parrot/tests/knowledge/wiki/decisions/test_inventory.py` (module-level async functions —
the file has no test class). No new test file, no new imports.

| Test | Asserts |
|---|---|
| `test_snapshot_stable_with_legacy_envelope` (updated) | snapshot still succeeds; manifest value is `record_hash(record)`, not the legacy stored hash |
| `test_snapshot_manifest_is_independent_of_the_stored_envelope` (new) | legacy and canonical pages of one record give one manifest |
| `test_snapshot_manifest_unchanged_for_canonical_pages` (untouched) | G3 — canonical manifests do not move |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug decisions-inventory-fixes-2 --feature-id FEAT-810`)
2. **Read the spec** at `sdd/specs/decisions-inventory-fixes-2.spec.md`
3. **Check dependencies** — TASK-5214 must be `"done"` in
   `sdd/tasks/index/decisions-inventory-fixes-2.json`
4. **Verify the Codebase Contract** before writing ANY code — TASK-5214 shifted the line numbers in
   `InventorySnapshot.take`, so match the anchors by text
5. **Update status** in `sdd/tasks/index/decisions-inventory-fixes-2.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete the `FILL IN` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists (never `git add .` / `-A`)
9. **Close the task** with
   `parrot sdd task close TASK-5215 decisions-inventory-fixes-2 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
