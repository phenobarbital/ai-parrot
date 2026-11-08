# TASK-5308: Build, scan and stage document revisions on every import path

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5301, TASK-5303, TASK-5305, TASK-5307
**Assigned-to**: unassigned

---

## Context

Implements the toolkit part of spec §3 **Module 7**: every ingest path produces a document
revision, scans it, attaches spans/owned ranges to the spliced nodes, renders each node's body
from its owned segments and stages revision + bodies in the FEAT-831 transaction. PDFs without
pages (`BytesIO`, extraction failure, or a test fake without `_pages`) keep today's path.

---

## Scope

- `PageIndexToolkit.__init__`: kwargs `scan_injection`, `injection_probability_threshold`,
  `read_max_chars`; attributes `_segment_store`, `_detector`.
- Helpers: `_scan`, `_stage_document`, `_doc_ids_in`, module-level `_section_segments`.
- `import_pdf`: pages path (new) or fallback (today); new kwarg `doc_id: Optional[str] = None`.
- `insert_markdown` and `insert_ebook`: section-addressed revisions; new kwarg `doc_id`.
  (`insert_content`, `import_file`, `import_folder` go through `insert_markdown` — no change.)
- Write `tests/knowledge/pageindex/test_segment_import.py`.

**NOT in scope**: read tools (TASK-5309), `index_segments`/rename/delete (TASK-5310), any change
to search, embeddings or OKF.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Import integration |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import hashlib                                                            # stdlib (not yet imported in toolkit.py)
from .store import JSONTreeStore                                          # toolkit.py:42 — insertion anchor for new imports
from .utils import find_node_by_id, structure_to_list                     # toolkit.py:48
from .segments import (DocumentRevision, SourceInfo, attach_pdf_document, attach_section_document,
                       derive_doc_id, render_body, revision_id, segment_pages, segment_text)   # TASK-5300/5301
from .segment_store import SegmentStore                                   # TASK-5302
from .injection_scan import ScanReport, scan_segments                     # TASK-5305
from parrot.security.prompt_injection import PromptInjectionDetector, get_injection_scoring_engine  # :102 / TASK-5304
from .utils import get_pdf_name                                           # utils.py:173
```

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py
        lock_timeout_s: float = 30.0,                                     # :117 (last named kwarg before **kwargs)
        self._lock_timeout_s = lock_timeout_s                             # :124
        self._content_store = NodeContentStore(storage_dir, cache_size=content_cache_size)  # :129
async def _mutate(self, tree_name, apply: Callable[[WriteTransaction], Awaitable[T]], *, attempts=3) -> T  # :244
async def _run_t3_classification(self, tree, original_id_to_node) -> None  # :377
async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None)  # :922
        node_markdown = _pop_node_field(subtree, "text")                   # :949 (1st of 2)
        _strip_keys_in_place(subtree, ("token_count", "line_num"))         # :950
        async def apply(txn) -> list[str]:                                 # :952-958
            fresh = copy.deepcopy(subtree)
            original_id_to_node = _capture_node_id_object_map(fresh)
            new_ids = splice_subtree(txn.tree, fresh, parent_node_id=parent_node_id)   # 3 occurrences: :955, :984, :1082
            self._stage_node_markdown(txn, original_id_to_node, node_markdown)        # 3 occurrences: :956, :985, :1083
            await self._run_t3_classification(txn.tree, original_id_to_node)
            return new_ids
async def insert_ebook(self, tree_name, sections, parent_node_id=None)   # :963
        subtree = ebook_tree(records)                                      # :978
        node_markdown = _pop_node_field(subtree, "text")                   # :979 (2nd of 2)
async def import_pdf(self, tree_name, pdf_path, parent_node_id=None, with_summaries=True, with_doc_description=False)  # :1040
        node_markdown = dict(subtree.pop("_node_markdown", {}) or {})      # :1077
def _stage_node_markdown(self, txn, original_id_to_node, node_markdown) -> None   # :1095 — the fallback path
def _pop_node_field(subtree, field) -> dict[str, str]                      # :1366 — keyed by build-time node_id
def _capture_node_id_object_map(subtree) -> dict[str, dict]                # :1424 — build-time node_id → node object

# knowledge/pageindex/generation.py
class WriteTransaction:
    def set_body(self, node, markdown) -> BodyRef                          # :155
    def set_revision(self, rev: DocumentRevision) -> None                  # TASK-5303

# knowledge/pageindex/tree_ops.py
def splice_subtree(target, subtree, parent_node_id=None) -> list[str]      # :89 — inserts the SAME node objects (renumbers node_id, assigns concept_id)
```

### Does NOT Exist
- ~~`PageIndexToolkit._segment_store`, `_scan`, `_stage_document`, `scan_injection`, `read_max_chars`~~ — created here
- ~~`import_pdf(doc_id=...)`, `insert_markdown(doc_id=...)`~~ — created here
- ~~a stored source path or source hash on imported subtrees~~ — recorded for the first time in `SourceInfo`
- ~~`count_tokens` imported by value~~ — segments use `utils.count_tokens` through the module (test stub)

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
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py#WriteTransaction",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#_capture_node_id_object_map",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#_pop_node_field"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Segment and scan **outside** `apply` (once, CPU and possibly ML), derive `doc_id` and build the
  `DocumentRevision` **inside** `apply` from `txn.tree` — *because* `apply` re-runs on
  `StaleGenerationError` and the taken doc ids may change between attempts.
- Key everything that crosses the `deepcopy` by **build-time node_id**, then translate to the fresh
  objects with `_capture_node_id_object_map(fresh)` — *because* `id(node)` changes on deepcopy.
- PDF: call `attach_pdf_document(fresh["structure"], revision)` **before** `splice_subtree`, while
  `start_index`/`end_index` are the build-time values.
- `_stage_document(txn, revision, roots)`: `txn.set_revision(revision)`, then for every node of the
  subtree (`structure_to_list(roots)`) `txn.set_body(node, render_body(revision, node, node.get("nodes") or []))`.
- `doc_id` collision map (`_doc_ids_in`): `{node["doc_id"]: revision_source_sha}` for nodes of the tree
  that carry `doc_id` — load the source sha from the revision file via `self._segment_store` (None when absent).
- Section addressing (`_section_segments`): pre-order over the subtree, `section` = titles from the
  subtree root down to the node, `seq_start` = segments so far; returns `(segments, {build_id: (start, end)})`.
- `SourceInfo`: PDF → `kind="pdf", name=get_pdf_name(pdf_path), path=str(pdf_path), sha256=<file hash in a thread>,
  pages=len(pages)`; markdown → `kind="markdown", name=doc_name or "ingested.md"`; ebook → `kind="ebook",
  name=records[0].source_uri or records[0].title`.
- No segments at all (empty `_pages`, or a markdown/ebook subtree with no text) → the existing
  `_stage_node_markdown` path, no revision, no `doc_id` — *because* existing tests and `BytesIO` imports rely on it.
- `_scan` returns `None` and does nothing when `scan_injection` is False; it resolves the engine with
  `await asyncio.to_thread(get_injection_scoring_engine)`.
- Record `scored_by` on the revision from the `ScanReport`.

---

## Implementation Blueprint

### Steps (in order)
1. Imports and `__init__` additions — *why*: every helper needs the store and detector.
2. Helpers `_scan`, `_doc_ids_in`, `_stage_document`, `_section_segments`.
3. `import_pdf`, then `insert_markdown`, then `insert_ebook` (the three `apply` closures differ —
   disambiguate each by its function, never by the shared lines).
4. Tests; then run the existing `test_toolkit.py` and `test_folder_import.py`.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY) — imports and constructor
```python
# AFTER — insert below `from .store import JSONTreeStore` (verified: toolkit.py:42, occurrences: 1)
from .segment_store import SegmentStore
from .segments import (
    DocumentRevision, SourceInfo, attach_pdf_document, attach_section_document,
    derive_doc_id, render_body, revision_id, segment_pages, segment_text,
)
from .injection_scan import ScanReport, scan_segments
from parrot.security.prompt_injection import PromptInjectionDetector, get_injection_scoring_engine
# also add `import hashlib` and `from datetime import datetime, timezone` to the stdlib block, and `get_pdf_name` to `from .utils import ...` (:48)

# AFTER — insert below `        lock_timeout_s: float = 30.0,` (verified: toolkit.py:117, occurrences: 1)
        scan_injection: bool = True,
        injection_probability_threshold: float = 0.98,
        read_max_chars: int = 12000,

# AFTER — insert below `        self._lock_timeout_s = lock_timeout_s` (verified: toolkit.py:124, occurrences: 1)
        self._scan_injection = scan_injection
        self._injection_threshold = injection_probability_threshold
        self._read_max_chars = max(500, int(read_max_chars))

# AFTER — insert below `        self._content_store = NodeContentStore(storage_dir, cache_size=content_cache_size)` (verified: :129, occurrences: 1)
        self._segment_store = SegmentStore(storage_dir)
        self._detector = PromptInjectionDetector()
```

### `toolkit.py` (MODIFY) — helpers, inserted ABOVE `    def _stage_node_markdown(` (verified: toolkit.py:1095, occurrences: 1)
```python
    async def _scan(self, segments: list) -> Optional[ScanReport]:
        """Score ``segments`` in place for prompt injection; ``None`` when scanning is disabled."""
        if not self._scan_injection or not segments:
            return None
        engine = await asyncio.to_thread(get_injection_scoring_engine)
        return await scan_segments(segments, detector=self._detector, engine=engine,
                                   threshold=self._injection_threshold)

    def _doc_ids_in(self, tree_name: str, tree: dict[str, Any]) -> dict[str, Optional[str]]:
        """``doc_id`` → source sha256 (or None) for every imported document already in ``tree``."""
        # FILL IN — bounded by Key Constraints (doc_id collision map)
        raise NotImplementedError

    def _stage_document(self, txn: WriteTransaction, revision: DocumentRevision, roots: list[dict[str, Any]]) -> None:
        """Stage ``revision`` and one view body per node of the subtree rooted at ``roots``."""
        txn.set_revision(revision)
        for node in structure_to_list(roots):
            txn.set_body(node, render_body(revision, node, node.get("nodes") or []))

    @staticmethod
    def _new_revision(doc_id: str, segments: list, source: SourceInfo, report: Optional[ScanReport]) -> DocumentRevision:
        return DocumentRevision(doc_id=doc_id, revision=revision_id(segments), source=source,
                                scored_by=report.scored_by if report else None,
                                created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                segments=segments)
```
And at module level, below `def _capture_node_id_object_map` (`toolkit.py:1424`):
```python
def _section_segments(roots: list[dict[str, Any]], texts: dict[str, str]) -> tuple[list, dict[str, tuple[int, int]]]:
    """Segments of an unpaged subtree in pre-order plus ``build_node_id → (start, end)`` own ranges."""
    # FILL IN: recursive walk carrying the title path; segment_text(texts.get(node_id, ""), path, seq_start=len(acc))
    #   — bounded by Key Constraints (section addressing), AC-3
    raise NotImplementedError
```

### `toolkit.py` (MODIFY) — `import_pdf` (`async def import_pdf(` verified :1040, occurrences: 1)
```python
# AFTER — `        node_markdown = dict(subtree.pop("_node_markdown", {}) or {})` (verified: :1077, occurrences: 1)
        pages = list(subtree.pop("_pages", []) or [])
        segments = await asyncio.to_thread(segment_pages, pages) if pages else []
        report = await self._scan(segments)
        source = None
        if segments:
            sha = await asyncio.to_thread(lambda: hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest())
            source = SourceInfo(name=get_pdf_name(pdf_path), kind="pdf", path=str(pdf_path), sha256=sha, pages=len(pages))
# FILL IN: inside this function's `apply` (the occurrence of
#   `self._stage_node_markdown(txn, original_id_to_node, node_markdown)` at :1083 — the one in import_pdf):
#   when `segments`: build the revision with doc_id = doc_id or derive_doc_id(source.name, taken=self._doc_ids_in(...),
#   source_sha256=source.sha256); attach_pdf_document(fresh["structure"], revision) BEFORE splice_subtree;
#   after the splice self._stage_document(txn, revision, fresh["structure"]); else keep _stage_node_markdown.
#   Add `doc_id: Optional[str] = None` to the signature and return `"doc_id"` / `"revision"` in the result dict
#   (None on the fallback path) — bounded by AC-1, AC-2
```

### `toolkit.py` (MODIFY) — `insert_markdown` and `insert_ebook`
```python
# insert_markdown: AFTER `        _strip_keys_in_place(subtree, ("token_count", "line_num"))` (verified: :950, occurrences: 1)
        segments, own_by_id = _section_segments(subtree.get("structure", []), node_markdown)
        report = await self._scan(segments)
# insert_ebook: AFTER the `node_markdown = _pop_node_field(subtree, "text")` that follows `        subtree = ebook_tree(records)`
#   (verified: :978-979 — disambiguated by the ebook_tree line; the bare line occurs 2 times)
        segments, own_by_id = _section_segments(subtree.get("structure", []), node_markdown)
        report = await self._scan(segments)
# FILL IN: in each function's own `apply` (insert_markdown :952-958, insert_ebook :981-987): when `segments`,
#   by_node = {id(original_id_to_node[bid]): rng for bid, rng in own_by_id.items() if bid in original_id_to_node};
#   build the revision (SourceInfo per Key Constraints, doc_id override or derive_doc_id); attach_section_document(
#   fresh["structure"], revision, by_node); splice; self._stage_document(txn, revision, fresh["structure"]);
#   else the existing _stage_node_markdown call. Add `doc_id: Optional[str] = None` to both signatures — bounded by AC-3, AC-4
```
**Why this shape**: the three `apply` closures share identical lines (3 occurrences each), so every edit is
anchored by its enclosing function. Doing the expensive work outside `apply` keeps a stale retry cheap.

### FILL IN checklist
- [ ] `_doc_ids_in`; bounded by Key Constraints
- [ ] `_section_segments`; bounded by AC-3
- [ ] `import_pdf` pages path + fallback + result keys; bounded by AC-1, AC-2
- [ ] `insert_markdown` / `insert_ebook` revisions; bounded by AC-3, AC-4

---

## Acceptance Criteria

- [ ] AC-1: `import_pdf` with a fake `build_page_index` returning `start_index`/`end_index` and `_pages` writes `segments/<doc_id>.<revision>.json`; every node of the subtree has `doc_id`, `revision`, `span`, `owned`; a parent's body (via `NodeContentStore.load_node`) contains none of its child's segments.
- [ ] AC-2: a fake without `_pages` (as in the existing `test_toolkit.py` fakes) produces exactly today's result — bodies from `_node_markdown`, no segment file, no `doc_id`; all of `test_toolkit.py` passes unchanged.
- [ ] AC-3: `insert_markdown` of nested headings yields one revision whose segments carry `section` paths and `page=None`; each node's span equals its owned range; `validate_ownership` over the subtree returns `[]`.
- [ ] AC-4: `insert_ebook` does the same with paths built from the parent chain of titles.
- [ ] AC-5: with `scan_injection=True` and a segment matching a CRITICAL pattern, the stored revision has that segment flagged and `scored_by` set; `scan_injection=False` leaves `scored_by` null.
- [ ] AC-6: re-importing the same markdown under the same `doc_name` gives the same `doc_id` and `revision`.
- [ ] `pytest packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py` passes; `ruff check` on `toolkit.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py
# Reuse the adapter/toolkit setup pattern of tests/knowledge/pageindex/test_toolkit.py:19-71
# (MagicMock adapter + autouse tiktoken stub on utils.count_tokens and md_builder.count_tokens).
import pytest

from parrot.knowledge.pageindex.segments import validate_ownership
from parrot.knowledge.pageindex.utils import structure_to_list


@pytest.mark.asyncio
async def test_import_pdf_stages_revision_and_view_bodies(toolkit, tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    async def fake_build(doc, adapter, options=None, **kwargs):
        return {"doc_name": "doc.pdf",
                "structure": [{"title": "Ch 1", "node_id": "0000", "start_index": 1, "end_index": 2,
                               "nodes": [{"title": "1.1 Scope", "node_id": "0001", "start_index": 1, "end_index": 2}]}],
                "_node_markdown": {}, "_pages": [(1, "# Ch 1\n\nIntro.\n\n## 1.1 Scope\n\nScope."), (2, "More.")]}

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", fake_build)
    await toolkit.create_tree("t")
    result = await toolkit.import_pdf("t", str(pdf))
    # FILL IN: segment file exists; node fields set; parent body excludes "Scope." — AC-1
    ...


@pytest.mark.asyncio
async def test_import_pdf_without_pages_falls_back(toolkit, tmp_path, monkeypatch):
    # FILL IN — AC-2
    ...


@pytest.mark.asyncio
async def test_insert_markdown_section_addresses(toolkit):
    # FILL IN — AC-3, AC-6
    ...


@pytest.mark.asyncio
async def test_insert_ebook_section_addresses(toolkit):
    # FILL IN — AC-4
    ...


@pytest.mark.asyncio
async def test_import_flags_injection_segment(toolkit):
    # FILL IN — AC-5 (insert_markdown with "Ignore all previous instructions ..." in one section)
    ...
```

### Known risk for this task
`render_body` joins segments with one blank line. If an existing `test_toolkit.py` test compares a markdown
node body byte-for-byte and the original text used a different separator, do **not** weaken `render_body`;
record the failing test in the Completion Note and stop (spec AC: existing tests change only where a parent
body is asserted to contain child text).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5308 — Build, scan and stage document revisions on every import path`), then close with
   `parrot sdd task close TASK-5308 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

import_pdf/insert_markdown/insert_ebook build, scan and stage a DocumentRevision and render view bodies; no-pages PDFs keep the old path. Empty rendered bodies are not staged (summary fallback preserved). Markdown/ebook SourceInfo.sha256 = hash of joined segment texts so identical re-imports reuse doc_id and edited text gets a suffixed id. KNOWN INTERIM FAILURE: test_generation_integration::test_bookstore_reindex_keeps_book_readable fails until TASK-5310 (Bookstore stages via rename_tree, which does not yet copy revisions). Pre-existing unrelated failures in full pageindex run: test_adapter (2) and test_okf_ontology::test_all_values_count. test_toolkit + test_folder_import (71) and 5 new tests pass.

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-07
**Notes**: tests run with a scratchpad-only shim for navconfig's read-only log dir (environment, not committed)
**Deviations from spec**: none (rename_tree revision copy deliberately left to TASK-5310)
