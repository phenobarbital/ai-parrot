# TASK-2074: Orchestrator triage wiring (hint forwarding + archive routing)

**Feature**: FEAT-402 — Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)
**Spec**: `sdd/specs/supervised-wiki-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2071, TASK-2072, TASK-2073
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec (§3). `WikiIngestOrchestrator.ingest`
today takes only `(source_path, wiki_config)` and drops the `hint` slot
when calling PageIndex. This task threads the triage outcome through the
apply pipeline: briefing → `insert_content(hint=…)` so triage work is
reused (not repeated), archive-routed docs get the `ARCHIVE` category,
rejected docs never create pages, and re-applying a manifest is idempotent.

---

## Scope

- Modify `WikiIngestOrchestrator.ingest` to accept an **optional** triage
  context (keyword-only, e.g. `triage: Optional[ManifestDocEntry] = None`
  — pick the minimal surface; default behavior with `triage=None` must be
  byte-identical to today):
  - Forward `triage.briefing` as the `hint` at the PageIndex call site
    (currently `await self._pi.insert_content(tree_name, content)` at
    `ingest.py:343` — the slot exists upstream, fill it).
  - `proposed/decided destination == "archive"` → pages created with
    `WikiPageCategory.ARCHIVE`.
  - `destination == "discard"` → NO page creation; record via
    `SourceCollectionManager` (`status="rejected"`, TASK-2073 fields) and
    bookkeeper `DISCARD`.
  - Admitted/archived: persist decision fields (TASK-2073 API) and log
    `ADMIT`/`ARCHIVE`.
- Idempotent re-review: re-running apply for an already-processed source
  must replace, not duplicate, its pages (reuse the orchestrator's existing
  replace/upsert semantics — study how `ingest` handles re-ingest of a
  known source before writing code).
- Extend `tests/knowledge/wiki/test_ingest.py` with stubbed toolkits.

**NOT in scope**: triage computation (TASK-2071), CLI (TASK-2075),
manifest file parsing (TASK-2070).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` | MODIFY | optional triage param; hint forwarding; archive/discard routing |
| `tests/knowledge/wiki/test_ingest.py` | MODIFY | wiring tests with stubbed PageIndex/GraphIndex toolkits |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ad6365242` (2026-08-02).

### Verified Imports
```python
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator, IngestReport
from parrot.knowledge.wiki.models import WikiConfig, WikiPageCategory
from parrot.knowledge.wiki.review import ManifestDocEntry        # TASK-2070
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py
class WikiIngestOrchestrator:                            # line 69
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any,
                 source_manager: SourceCollectionManager, bookkeeper: WikiBookkeeper,
                 store: Optional[BaseWikiStore] = None, sync_graph: bool = False) -> None: ...  # 89-95
    async def ingest(self, source_path: str, wiki_config: WikiConfig) -> IngestReport: ...     # 123-306
class IngestReport(BaseModel): ...                       # line 45
# PageIndex call site — the dropped hint slot to fill:
#   ingest.py:343  →  await self._pi.insert_content(tree_name, content)
# Bookkeeper update helper exists: _update_bookkeeping (see ingest.py:523-536, logs "INGEST")

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit:
    async def insert_content(self, tree_name: str, content: str,
                             parent_node_id: Optional[str] = None,
                             hint: Optional[str] = None) -> dict[str, Any]: ...  # 730-736

# packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py — downstream of the hint:
class TwoStepIngester:                                   # line 43
    async def ingest(self, content: str, hint: Optional[str] = None) -> IngestedMarkdown: ...  # 62-69
    # hint interpolated into BOTH prompts (_step1_analyze :71-73, _step2_generate :83-90)

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
    def mark_ingested(self, source_id: str, pages_generated: list[str],
                      status: str = "ingested") -> Optional[SourceManifestEntry]: ...  # 282-287
    # + decision-field persistence added by TASK-2073 — check its actual API when implementing
```

### Does NOT Exist
- ~~`WikiIngestOrchestrator.ingest(hint=…)`~~ / ~~`(triage=…)`~~ — no such parameter today; YOU add the optional triage param.
- ~~`replace_source_slice`~~ — verify the actual replace/upsert mechanism inside `ingest` (123-306) before relying on a name; the spec references the *semantics* (replace, don't duplicate), not a confirmed symbol.
- ~~`WikiPageCategory.ARCHIVE`~~ before TASK-2072 lands — depends on it.

---

## Implementation Notes

### Key Constraints
- **Backward compatibility**: `ingest(source_path, wiki_config)` with no
  triage context must behave exactly as today (the `build`/`upsert` paths
  call it) — spec integration test `test_build_unaffected` enforces this.
- Async throughout; log decisions via `self.logger` + bookkeeper.
- Keep the triage param typed against `ManifestDocEntry` (single source of
  truth for decision fields) rather than inventing a parallel dataclass.

### References in Codebase
- `ingest.py:123-306` — read the FULL method before editing; understand the
  existing source-registration, page-creation, and bookkeeping flow.
- `ingest.py:523-536` — `_update_bookkeeping` pattern for operation logging.

---

## Acceptance Criteria

- [ ] Briefing reaches `insert_content(hint=…)` (asserted via stub capture).
- [ ] Archive-destination docs produce pages with category `archive`.
- [ ] Discard-destination docs produce ZERO pages and a `status="rejected"` manifest row.
- [ ] Re-applying the same source replaces pages (no duplicates) — idempotence test.
- [ ] `ingest` without triage context: existing `test_ingest.py` suite passes unchanged.
- [ ] `pytest tests/knowledge/wiki/test_ingest.py -v` green; `ruff check` clean.

---

## Test Specification

```python
# tests/knowledge/wiki/test_ingest.py (add)
async def test_orchestrator_forwards_hint(...): ...        # stub captures hint kwarg
async def test_orchestrator_archive_category(...): ...
async def test_orchestrator_reject_no_pages(...): ...
async def test_orchestrator_reapply_idempotent(...): ...
async def test_orchestrator_no_triage_unchanged(...): ...  # legacy path regression
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2071, TASK-2072, TASK-2073 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `ingest.py:123-306` in full;
   confirm the TASK-2073 persistence API as actually implemented
4. **Update status** in `sdd/tasks/index/supervised-wiki-ingestion.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and **update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
