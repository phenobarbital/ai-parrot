# TASK-5385: Idempotent same-source re-import on every PageIndex import path

**Feature**: FEAT-849 — PageIndex Toolkit Tech Debt
**Spec**: `sdd/specs/pageindex-toolkit-tech-debt.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:d34c567792ef`

---

## Context

Implements spec §4 FR-1 and §3 decision D-1. Closes `issue:d34c567792ef`.

`derive_doc_id` (`segments.py:254`) deliberately returns the *same* slug when
`taken[slug]` already holds the *same* `source_sha256` — that is how a re-import keeps its
identity. But the three import paths then go on to mint a revision and call
`splice_subtree` anyway, so re-importing byte-identical content appends a **second set of
structure nodes** pointing at the same `doc_id@revision`. `_documents_of`
(`toolkit.py:847`) resolves first-wins, so `list_documents` and `outline` hide the
duplicate, while BM25 ranks both copies and the bodies are stored twice.

The revision *id* is already content-addressed (`_new_revision` sets
`revision=revision_id(segments)`, `toolkit.py:2351`), and
`test_insert_markdown_section_addresses` already asserts a re-import returns the same
`(doc_id, revision)` pair. **This task changes tree/structure state only** — the returned
`doc_id` and `revision` stay exactly what they are today.

The product decision (spec D-1) is **idempotent skip**, not replace: splice nothing, mint
nothing, mark the transaction `txn.noop = True`, and tell the caller `reused: True`.

---

## Scope

- Add one private helper to `PageIndexToolkit` that answers "is this exact source already
  imported under the slug it would derive?" and returns the existing document's `doc_id`,
  `revision` and root node ids.
- Call it inside the `apply(txn)` body of `insert_markdown`, `insert_ebook` and
  `import_pdf`, before `splice_subtree`, and short-circuit on a hit.
- Add `reused` to the return dict of all three paths (`False` on a normal import).
- Write tests in `packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py`.

**NOT in scope**:
- `segments.py` / `derive_doc_id` — its contract does not change.
- The `agentic.py` fixes (TASK-5386), the `agentic_retrieve` snapshot (TASK-5387), the
  wiki page (TASK-5388).
- Any "replace the previous subtree" behaviour — explicitly rejected in spec §3 D-1.
- `import_file`, `insert_content`, `import_folder` — they delegate and inherit the
  behaviour; do not add a second check to them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `_reused_document` helper + short-circuit in the three `apply` bodies + `reused` key |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py` | MODIFY | Tests for AC-1…AC-5 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase at `dev`.
> Do NOT invent any import, attribute, or method not listed here.

### Verified Imports

Everything this task needs is **already imported** at the top of `toolkit.py` — add no new
import to the source file:

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:60-78 (verified)
from .segments import (
    DocumentRevision,
    SourceInfo,
    derive_doc_id,
    revision_id,
)
# toolkit.py:41 (verified)
from .generation import StaleGenerationError, WriteTransaction, generation_of
# toolkit.py:22 (verified)
import copy
```

For the test file (`test_segment_import.py`) these are already imported at its top
(verified `test_segment_import.py:7-11`):

```python
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.segments import validate_ownership
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:2206
async def _doc_ids_in(self, tree_name: str, tree: dict[str, Any]) -> dict[str, Optional[str]]:
    """``doc_id`` -> source sha256 (or None) for every imported document already in ``tree``."""

# toolkit.py:2213
def _doc_ids_in_sync(self, tree_name: str, tree: dict[str, Any]) -> dict[str, Optional[str]]:

# toolkit.py:847
def _documents_of(self, tree: dict[str, Any]) -> dict[str, dict[str, Any]]:

# toolkit.py:2346 — @staticmethod
def _new_revision(doc_id: str, segments: list, source: SourceInfo, report: Optional[ScanReport]) -> DocumentRevision:
    # sets revision=revision_id(segments) at line 2351 — content-addressed

# toolkit.py:400
async def _mutate(self, tree_name: str, apply: Callable[[WriteTransaction], Awaitable[T]], *, attempts: int = 3) -> T:
    # line 414: a JOINED transaction is forced `txn.noop = False` — see Key Constraints

# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:254
def derive_doc_id(name: str, *, taken: Mapping[str, Optional[str]], source_sha256: Optional[str]) -> str:
    """Slug of ``name``; suffixed with 6 hex only when ``taken[slug]`` holds a different source hash."""
    # body (lines 256-261):
    #   base = _KNOWN_EXT_RE.sub("", (name or "").strip())
    #   slug = _SLUG_STRIP_RE.sub("-", base.lower()).strip("-")[:48].strip("-") or "doc"
    #   if slug in taken and taken[slug] != source_sha256:  -> suffix
    #   return slug

# segments.py:20-21
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_KNOWN_EXT_RE = re.compile(r"\.(pdf|md|markdown|epub|txt|html?)$", re.IGNORECASE)

# segments.py:49
class SourceInfo(BaseModel):
    name: str
    kind: Literal["pdf", "markdown", "ebook", "legacy"]
    path: Optional[str] = None
    sha256: Optional[str] = None
    pages: Optional[int] = None

# packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py:116, attribute at :147
class WriteTransaction:
    tree: dict[str, Any]          # line 134
    noop: bool                    # line 147 — "Set by a mutator that changed nothing"

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:301
def structure_to_list(structure: Any) -> list[dict]:
```

### Does NOT Exist

- ~~`derive_doc_id(..., reuse=True)`~~ — `derive_doc_id` has exactly three parameters
  (`name`, `taken`, `source_sha256`); it takes no reuse/replace flag.
- ~~`PageIndexToolkit._reused_document`~~ — this task CREATES it; it is not there now.
- ~~`PageIndexToolkit._remove_subtree` / `._delete_document` / `._replace_document`~~ —
  no delete-subtree helper exists, and this task must not add one (D-1 rejects replace).
- ~~`WriteTransaction.skip()` / `.abort()` / `.rollback()`~~ — the only "nothing changed"
  signal is the `noop` attribute.
- ~~`SourceInfo.doc_id`~~ — `SourceInfo` carries no `doc_id`; the id is derived.
- ~~`DocumentRevision.node_ids` / `.root_node_id`~~ — a revision does not know its nodes;
  the mapping lives on the tree's structure nodes (`doc_id` / `revision` keys).
- ~~`toolkit.import_file(..., doc_id=...)`~~ — `import_file` (`toolkit.py:2061`) takes only
  `tree_name`, `file_path`, `parent_node_id`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._doc_ids_in",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._documents_of",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._new_revision",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.insert_markdown",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.insert_ebook",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#derive_doc_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py#WriteTransaction"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Derive the slug exactly once, in one place.** The helper must not re-implement the
  slug rules; it calls `derive_doc_id(source.name, taken=taken, source_sha256=source.sha256)`
  and then asks whether `taken.get(that_slug) == source.sha256`. If the two ever disagreed
  the short-circuit would fire on the wrong document.
- **`taken` is awaited inside the transaction.** `_doc_ids_in` reads revision files off the
  event loop; call it with `txn.tree`, never with a cached tree.
- **A joined transaction must not rely on `noop`.** `_mutate` forces `txn.noop = False`
  when the import is one step of a larger write (`toolkit.py:414`). That is fine: the
  short-circuit splices nothing either way, so the only consequence is that the owner's
  publication proceeds, which is correct.
- **An explicit `doc_id=` disables the short-circuit** (FR-1.4). Each `apply` body already
  reads `doc_id or derive_doc_id(...)`; keep that precedence.
- **`reused` is always present** (FR-1.3) — `False` on a normal import, so callers need no
  `.get` default. Seed it in the `imported` dict that each path already builds.
- Async throughout; `self.logger` / module `logger` for the skip line; 120-col lines;
  Google-style docstrings.

### References in Codebase

- `toolkit.py:1423`, `1589`, `1893`, `2480` — the established
  `txn.noop = True  # nothing changed: do not mint an empty generation` pattern.
- `toolkit.py:2206-2228` — `_doc_ids_in` / `_doc_ids_in_sync`, the `doc_id -> sha256` map
  the helper reuses.

---

## Implementation Blueprint

### Steps (in order)

1. Add the `_reused_document` helper next to `_doc_ids_in` (after `_doc_ids_in_sync`,
   `toolkit.py:2228`) — *why*: it belongs with the other `doc_id`-identity helpers and must
   share their `taken` map.
2. In each of the three `apply(txn)` bodies, compute `taken` once, pass it to both the
   helper and `derive_doc_id`, and return early on a hit — *why*: calling `_doc_ids_in`
   twice would read every revision file twice inside the write lock.
3. Seed `reused: False` in each path's `imported` dict and set it `True` on the
   short-circuit — *why*: FR-1.3 requires the key on every return, not only reuse.
4. Write the five tests — *why*: AC-1…AC-5 are the two-key evidence that closes
   `issue:d34c567792ef`.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — new helper)

```python
# occurrences: 1 (verified: grep -c 'def _doc_ids_in_sync' toolkit.py)
# AFTER — insert below the body of `def _doc_ids_in_sync` (verified: toolkit.py:2213-2228,
# the method ends with `        return taken`)

    def _reused_document(
        self,
        tree: dict[str, Any],
        source: SourceInfo,
        taken: dict[str, Optional[str]],
    ) -> Optional[dict[str, Any]]:
        """The already-imported document ``source`` would re-create, or ``None``.

        A hit means the slug ``derive_doc_id`` picks for ``source`` is already held by a
        document whose ``source.sha256`` is identical, i.e. byte-identical content is being
        re-imported. Callers splice nothing in that case (spec FEAT-849 §3 D-1).

        Args:
            tree: The open transaction's tree (``txn.tree``), never a cached snapshot.
            source: Source info of the incoming import.
            taken: ``doc_id -> source sha256`` map from :meth:`_doc_ids_in` for ``tree``.

        Returns:
            ``{"doc_id": str, "revision": Optional[str], "node_ids": list[str]}`` on a hit,
            ``None`` otherwise.
        """
        if source.sha256 is None:
            return None
        slug = derive_doc_id(source.name, taken=taken, source_sha256=source.sha256)
        if slug not in taken or taken[slug] != source.sha256:
            return None
        # FILL IN: collect the existing document's revision id and its root node ids by
        # walking `structure_to_list(tree.get("structure", []))` for nodes whose
        # `doc_id == slug`. "Root" means a node with no ancestor carrying the same doc_id —
        # bounded by AC-1 (`new_node_ids == []` is acceptable, so an empty list is a valid
        # result here) and by the Does-NOT-Exist note that DocumentRevision carries no
        # node ids. Do NOT load revision files; the id is already on the nodes.
        raise NotImplementedError
```

**Why this shape**: the helper is the single place that decides "same source, same slug",
so `derive_doc_id` and the short-circuit can never disagree (Key Constraints). It takes
`taken` as a parameter rather than awaiting `_doc_ids_in` itself so each `apply` body reads
the revision files exactly once inside the write lock. It is sync because every input is
already in memory. The `source.sha256 is None` guard matters: the no-segments import paths
build no `SourceInfo` at all, and a `None` hash must never match another `None`.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — `insert_markdown`)

```python
# occurrences: 3 (verified: grep -c 'source.name, taken=await self._doc_ids_in(tree_name, txn.tree), source_sha256=source.sha256' toolkit.py)
# FILL IN: disambiguate — this anchor appears 3 times (insert_markdown toolkit.py:1948,
# insert_ebook toolkit.py:2007, import_pdf toolkit.py:2153). For EACH of the three, quote
# the 2-3 surrounding lines that make it unique before editing. In insert_markdown the
# enclosing block is:
#
#     async def apply(txn: WriteTransaction) -> list[str]:
#         fresh = copy.deepcopy(subtree)
#         original_id_to_node = _capture_node_id_object_map(fresh)
#         revision = None
#         if segments:
#             revision = self._new_revision(
#                 doc_id
#                 or derive_doc_id(
#                     source.name, taken=await self._doc_ids_in(tree_name, txn.tree), source_sha256=source.sha256
#                 ),
#
# Rewrite that head as (the same transformation applies to all three sites):

        async def apply(txn: WriteTransaction) -> list[str]:
            taken = await self._doc_ids_in(tree_name, txn.tree)
            if doc_id is None and segments:
                hit = self._reused_document(txn.tree, source, taken)
                if hit is not None:
                    txn.noop = True  # nothing changed: do not mint an empty generation
                    logger.info(
                        "same-source re-import of %r into %r: reusing %s@%s",
                        source.name,
                        tree_name,
                        hit["doc_id"],
                        hit["revision"],
                    )
                    imported.update(doc_id=hit["doc_id"], revision=hit["revision"], reused=True)
                    return []
            fresh = copy.deepcopy(subtree)
            original_id_to_node = _capture_node_id_object_map(fresh)
            revision = None
            if segments:
                revision = self._new_revision(
                    doc_id or derive_doc_id(source.name, taken=taken, source_sha256=source.sha256),
                    segments,
                    source,
                    report,
                )
                # FILL IN: keep the rest of this apply body byte-for-byte as it is today
                # (attach_*_document, splice_subtree, _stage_document, optimizer, T3) —
                # bounded by "NOT in scope"; only the head above changes.
```

**Why**: `taken` is hoisted so the map is read once and shared by the helper and
`derive_doc_id` — both must see the same snapshot. The guard is `doc_id is None and
segments`: an explicit `doc_id` keeps today's behaviour (FR-1.4), and a no-segments import
has no `SourceInfo` to compare. `txn.noop = True` uses the module's existing comment
verbatim so the pattern stays greppable. Returning `[]` is what makes `new_node_ids` empty
per AC-1.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY — `reused` key)

```python
# occurrences: 3 (verified: grep -c 'imported: dict\[str, Optional\[str\]\] = {"doc_id": None, "revision": None}' toolkit.py)
# FILL IN: disambiguate — 3 sites (insert_markdown, insert_ebook, import_pdf). In each,
# widen the annotation and seed `reused` (the dict now holds a bool as well as strings):

        imported: dict[str, Any] = {"doc_id": None, "revision": None, "reused": False}
```

**Why**: FR-1.3 requires `reused` on every import return, not only on a reuse, so callers
need no `.get` default. The annotation must widen from `dict[str, Optional[str]]` to
`dict[str, Any]` because the dict now carries a `bool`; leaving it would be a type lie that
`mypy` flags.

### `packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def test_import_flags_injection_segment' test_segment_import.py)
# AFTER — append below the end of `test_import_flags_injection_segment`
# (verified: test_segment_import.py:160-174, the file's last test)


@pytest.mark.asyncio
async def test_reimport_same_markdown_is_reused(toolkit, tmp_path):
    """AC-1/AC-2: a byte-identical re-import splices nothing and mints no generation."""
    await toolkit.create_tree("kb")
    first = await toolkit.insert_markdown("kb", MD, doc_name="Tutorial.md")
    before = toolkit._store.load("kb")
    # FILL IN: assert `first["reused"] is False`; capture the node count via
    # `structure_to_list(before["structure"])` and the generation via
    # `generation_of(before)`; re-import the same MD/doc_name; then assert the second
    # result has `reused is True`, the same `doc_id`/`revision` as `first`,
    # `new_node_ids == []`, an unchanged node count and an unchanged generation —
    # bounded by AC-1 and AC-2. Import `generation_of` from
    # parrot.knowledge.pageindex.generation at the top of this file.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_reimport_same_pdf_is_reused(toolkit, tmp_path, monkeypatch):
    """AC-3: the same PDF bytes twice reuse the first import."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", _pdf_fake())
    await toolkit.create_tree("t")
    first = await toolkit.import_pdf("t", str(pdf))
    # FILL IN: re-import the same path and assert reuse exactly as above — bounded by AC-3.
    # Note `_pdf_fake()` returns a fresh subtree each call, so the *structure* is identical
    # and the sha256 comes from the file bytes, which do not change.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_reimport_same_ebook_is_reused(toolkit, tmp_path):
    """AC-3: the same ebook sections twice reuse the first import."""
    # FILL IN: reuse the `sections` list from test_insert_ebook_section_addresses
    # (test_segment_import.py:150-156), call insert_ebook twice, assert reuse —
    # bounded by AC-3.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_reimport_changed_content_gets_new_doc_id(toolkit, tmp_path):
    """AC-4: changed bytes under the same name still get a suffixed doc_id."""
    await toolkit.create_tree("kb")
    first = await toolkit.insert_markdown("kb", MD, doc_name="Tutorial.md")
    changed = await toolkit.insert_markdown("kb", MD + "\n## Extra\nMore text here.\n", doc_name="Tutorial.md")
    # FILL IN: assert `changed["reused"] is False`, `changed["doc_id"] != first["doc_id"]`,
    # and that it matches `tutorial-<6 hex>` — bounded by AC-4 and by derive_doc_id's
    # documented suffix rule (segments.py:258-260).
    raise NotImplementedError


@pytest.mark.asyncio
async def test_explicit_doc_id_skips_reuse_shortcircuit(toolkit, tmp_path):
    """AC-5: an explicit doc_id= keeps today's splicing behaviour."""
    await toolkit.create_tree("kb")
    await toolkit.insert_markdown("kb", MD, doc_name="Tutorial.md", doc_id="pinned")
    second = await toolkit.insert_markdown("kb", MD, doc_name="Tutorial.md", doc_id="pinned")
    # FILL IN: assert `second["reused"] is False` and that `second["new_node_ids"]` is
    # non-empty — the caller asked for a specific identity, so no short-circuit fires.
    # Bounded by AC-5 and FR-1.4.
    raise NotImplementedError
```

**Why**: `test_segment_import.py` already owns the import paths and ships the `toolkit`
fixture, the `MD` constant and `_pdf_fake()`, so the tests attach there rather than in a new
module. Each test names its AC so the closing evidence for `issue:d34c567792ef` is
traceable. The existing `test_insert_markdown_section_addresses` assertion that a re-import
returns the same `(doc_id, revision)` must keep passing — it is the regression guard that
this task did not change identity, only structure.

### FILL IN checklist

- [ ] `toolkit.py::PageIndexToolkit._reused_document` — walk the structure for the existing
      `doc_id`'s revision and root node ids; bounded by AC-1 and the Does-NOT-Exist note
      that `DocumentRevision` carries no node ids.
- [ ] `toolkit.py::insert_markdown.apply` — disambiguate the 3-occurrence anchor, then keep
      the post-head body byte-for-byte; bounded by "NOT in scope".
- [ ] `toolkit.py::insert_ebook.apply` — same transformation as `insert_markdown`.
- [ ] `toolkit.py::import_pdf.apply` — same transformation as `insert_markdown`.
- [ ] `toolkit.py` ×3 — widen `imported` to `dict[str, Any]` and seed `reused: False`.
- [ ] `test_segment_import.py` — five test bodies; bounded by AC-1…AC-5.

---

## Acceptance Criteria

- [ ] AC-1 — a second `insert_markdown` of identical content returns `reused: True`, the
      first call's `doc_id`/`revision`, and `new_node_ids == []`; `list_documents` has one entry.
- [ ] AC-2 — after that second import the generation and the structure node count are unchanged.
- [ ] AC-3 — the same holds for `import_pdf` (same bytes) and `insert_ebook` (same sections).
- [ ] AC-4 — changed content under the same name still yields a `-<6 hex>` doc_id and `reused: False`.
- [ ] AC-5 — an explicit `doc_id=` on a same-source re-import still splices.
- [ ] Existing `test_insert_markdown_section_addresses` still passes.
- [ ] `ruff check` clean on both changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation.py -q`

---

## Test Specification

See the blueprint's test block — five tests appended to
`packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py`:
`test_reimport_same_markdown_is_reused`, `test_reimport_same_pdf_is_reused`,
`test_reimport_same_ebook_is_reused`, `test_reimport_changed_content_gets_new_doc_id`,
`test_explicit_doc_id_skips_reuse_shortcircuit`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-toolkit-tech-debt --feature-id FEAT-849`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-grep every anchor's occurrence count before
   editing; a count of 0 means the anchor moved: stop and report the drift
5. **Update status** in `sdd/tasks/index/pageindex-toolkit-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:` marker
7. **Verify** by running the Validation Commands with
   `PYTHONPATH=<wt>/packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists
9. **Close the task**: `parrot sdd task close TASK-5385 pageindex-toolkit-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Code session ai-parrot-b5 (/sdd-fix d34c567792ef)
**Date**: 2026-11-09
**Notes**: Added `PageIndexToolkit._reused_document` after `_doc_ids_in_sync`: it derives the
slug through `derive_doc_id` (so the two can never disagree), confirms `taken[slug]` holds the
same `source.sha256`, and walks the nested structure for that doc_id's root nodes and revision.
The three `apply(txn)` bodies (`insert_markdown`, `insert_ebook`, `import_pdf`) now hoist
`taken = await self._doc_ids_in(...)` once, short-circuit on a hit with
`txn.noop = True` + `return []`, and reuse the hoisted map for `derive_doc_id`. All three
`imported` dicts widened to `dict[str, Any]` and seeded with `reused: False`.

Five tests added to `test_segment_import.py` (AC-1…AC-5), plus a shared `_tree_shape` helper
asserting node count and generation id are unchanged. 10/10 pass in that module; 95/95 across
`test_toolkit.py`, `test_folder_import.py`, `test_generation.py`.

The pre-existing `test_insert_markdown_section_addresses` assertion that a re-import returns the
same `(doc_id, revision)` still passes — identity was already content-addressed; only the
duplicate structure splice changed.

**Deviations from spec**: none. Two notes:
- `ruff check` reports one B905 (`zip()` without `strict=`) at `toolkit.py:2390`; verified
  pre-existing on `origin/dev` and outside this task's scope, so left alone.
- `black --check` wants to reflow `test_segment_import.py`, but every reflow is in
  pre-existing lines (the file predates black here); the appended tests are already
  black-clean, so the file was not reformatted.
