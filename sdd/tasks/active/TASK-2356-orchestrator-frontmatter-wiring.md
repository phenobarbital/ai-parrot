# TASK-2356: Orchestrator wiring — acquirer, metadata persistence, page frontmatter

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2352, TASK-2353, TASK-2355
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec (§3). This is where the three halves meet:
`WikiIngestOrchestrator` stops reading source files with `read_text`, starts
persisting document metadata onto the source manifest, and prefixes the
generated wiki page bodies with the YAML frontmatter block.

`ingest.py` is shared machinery — `build` and `upsert` also call
`WikiIngestOrchestrator.ingest()` with `triage=None`. **Every change here must
be inert on that legacy path**: no frontmatter, no new columns written, same
staleness behavior, byte-identical output.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py`:
  - `_load_source` (line 666-682): delegate to `DocumentAcquirer`. Widen the
    signature to accept the `DocumentRef`/URI the caller holds, and return the
    acquired text. Let `DocumentAcquisitionError` propagate — the caller
    decides whether to skip.
  - `ingest()` (line 161-168): add an optional
    `acquired: AcquiredDocument | None = None` keyword. When given, use it
    instead of re-acquiring (the CLI passes the triage-lane result). When
    `None`, acquire via `DocumentAcquirer` as before.
  - Persist metadata: call `SourceCollectionManager.record_document_metadata()`
    (TASK-2355) with `acquired.metadata.model_dump()`, `content_type`, and
    `loader`, on the admit/archive paths only.
  - Build a `TriageProvenance` from the `triage` entry (`composite`,
    `decision or proposed_action`, `decision_source`) plus the
    `charter_version` argument `ingest()` already receives.
  - Compute `frontmatter = render_frontmatter(acquired.metadata, provenance)`
    and pass it into `_build_page_records` as a new keyword.
  - `_build_page_records` (line 709-800): add `frontmatter: str = ""`; prefix
    it onto **every** record's `body`, in BOTH branches (the resolved-node
    branch and the `node is None` fallback branch). Prefix **before**
    `estimate_tokens(...)` is computed (line 797) so `token_count` reflects
    what is actually stored.
- Extend `tests/knowledge/wiki/test_ingest.py`.

**NOT in scope**: `cli.py` (TASK-2357); the `--review` re-acquisition path's
caching (deferred, spec §8); backfilling frontmatter onto pages ingested
before FEAT-451 (explicit spec Non-Goal); any change to `IngestTriageRouter`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` | MODIFY | `_load_source`, `ingest()`, `_build_page_records` |
| `tests/knowledge/wiki/test_ingest.py` | MODIFY | Frontmatter + legacy-path tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `2026-08-23`. `ingest.py` is shared with FEAT-450 —
> **re-anchor line numbers before editing.**

### Verified Imports

```python
from parrot.knowledge.wiki.documents import (      # TASK-2351/2352/2353
    AcquiredDocument,
    DocumentAcquirer,
    DocumentAcquisitionError,
    DocumentRef,
    TriageProvenance,
    render_frontmatter,
)
from parrot.knowledge.wiki.models import SourceManifestEntry, WikiConfig, WikiPageCategory
from parrot.knowledge.wiki.review import ManifestDocEntry     # review.py:135
from parrot.knowledge.wiki.store import WikiPageRecord        # store.py:215
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py
class WikiIngestOrchestrator:                                          # 107
    def __init__(self, pi_toolkit, graph, sources, bookkeeper, *,
                 store=None, sync_graph=...)                           # 127

    async def ingest(
        self,
        source_path: str,
        wiki_config: WikiConfig,
        *,
        triage: Optional[ManifestDocEntry] = None,
        charter_version: Optional[str] = None,
    ) -> IngestReport:                                                 # 161-168
    #  triage=None  -> LEGACY path, byte-identical to pre-FEAT-402 behavior.
    #  effective_destination = triage.decision or triage.proposed_action
    #  "discard" short-circuits: no PageIndex call, no store sync, manifest only.

    async def _load_source(self, path: Path) -> str:                   # 666
        return await asyncio.to_thread(path.read_text, encoding="utf-8")   # 682

    async def _create_wiki_pages(self, content, tree_name, hint=None) -> dict[str, Any]:  # 684

    async def _build_page_records(
        self, tree_name: str, node_ids: list[str], source_id: str,
        fallback_title: str = "", fallback_summary: str = "",
        category_override: Optional[str] = None,
    ) -> list[WikiPageRecord]:                                         # 709-717
    #  TWO construction branches — BOTH need the frontmatter prefix:
    #    node is None fallback        -> record_kwargs dict, lines ~770-780
    #    resolved node                -> WikiPageRecord(...),  lines ~783-799
    #  token_count=estimate_tokens(body or summary)                    # ~797

    def _load_body(self, loader, concept_id, node_id)                  # 815
    def _update_bookkeeping(self, ...)                                 # 898
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/review.py:135-170
class ManifestDocEntry(BaseModel):
    kind: Literal["doc"] = "doc"
    source_uri: str
    file_hash: str
    briefing: str
    scores: DimensionScores
    composite: float = Field(ge=0.0, le=1.0)          # <-- provenance.composite_score
    proposed_action: Literal["admit", "archive", "discard"]
    claims: list[Claim] = []
    decision: Literal["admit", "archive", "discard"] | None = None
    decision_source: Literal["heuristic", "model", "human", "auto"] | None = None
    audit_sample: bool = False
    audit_stratum: str | None = None
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:215-243
class WikiPageRecord(BaseModel):
    concept_id: str; node_id: Optional[str] = None; title: str = ""
    category: str = "concept"; summary: str = ""; body: str = ""
    source_id: Optional[str] = None; token_count: int = 0
    origin: str = "ingest"; asserted_by: Optional[str] = None
```

### Does NOT Exist

- ~~`WikiPageRecord.metadata` / `.frontmatter` / `.doc_metadata`~~ — no such
  field (store.py:234-243). The frontmatter is a **string prefix on the
  existing `body`**. Do not add a column.
- ~~`ManifestDocEntry.charter_version`~~ — not a field (review.py:135-170).
  The charter version lives once per run on `ManifestRunHeader` (review.py:111)
  and reaches `ingest()` as the separate `charter_version=` argument. That is
  exactly why the argument exists — use it.
- ~~`ManifestDocEntry.composite_score`~~ — the field is named **`composite`**
  (review.py:163). `composite_score` is the name on `SourceManifestEntry`
  (models.py:218) and on `TriageProvenance`. Map, do not assume.
- ~~a single page-record construction site~~ — `_build_page_records` has **two**
  branches. Prefixing only the resolved-node one silently drops frontmatter
  from fallback records.
- ~~`estimate_tokens` living in `ingest.py`~~ — it is imported there; do not
  redefine it.

---

## Implementation Notes

### Pattern to Follow

```python
def _provenance_from(
    triage: ManifestDocEntry | None, charter_version: str | None
) -> TriageProvenance | None:
    if triage is None:
        return None            # legacy build/upsert path -> NO triage block
    return TriageProvenance(
        composite_score=triage.composite,                    # NOTE: .composite
        decision=triage.decision or triage.proposed_action,
        decision_source=triage.decision_source,
        charter_version=charter_version,
    )
```

### Key Constraints

- **The legacy path must stay inert.** With `triage=None` and no `acquired`,
  `build`/`upsert` must produce byte-identical pages. Guard the frontmatter
  emission so it only runs on the supervised path; `test_build_unaffected`
  (TASK-2358) is the regression gate.
- Prefix frontmatter in **both** `_build_page_records` branches, and **before**
  the `estimate_tokens` call.
- Every page derived from one source gets the **identical** frontmatter block
  (resolved spec §8) — compute it once, outside the per-node loop. Do not
  derive a per-page `page_range`.
- `"discard"` short-circuits before any page is created (ingest.py docstring
  §"discard"). Do not acquire, render, or persist metadata on that path beyond
  what the existing code already records.
- Keep `DocumentAcquisitionError` propagating out of `_load_source` — swallowing
  it here would re-create the silent-corruption bug in a new place.
- `ingest.py` is shared with FEAT-450. Rebase on `dev` before starting and
  before committing.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:161-230` — the `ingest()` docstring documents the legacy/triage contract precisely; keep it accurate after your change.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:709-800` — the two record branches.
- `tests/knowledge/wiki/test_ingest.py` — existing test shape and mocked toolkits.

---

## Acceptance Criteria

- [ ] `_load_source` acquires through `DocumentAcquirer`; a PDF yields real
      extracted text, not mojibake.
- [ ] `ingest(..., acquired=<AcquiredDocument>)` does **not** re-acquire.
- [ ] On admit/archive, `record_document_metadata()` is called with the
      document's metadata, content type, and loader.
- [ ] Generated page bodies start with a `---` frontmatter block that
      `yaml.safe_load` parses.
- [ ] That block contains a nested `triage:` mapping with `composite_score`
      (from `ManifestDocEntry.composite`), `decision`, `decision_source`, and
      `charter_version`.
- [ ] All pages from one source carry a **byte-identical** frontmatter block.
- [ ] Frontmatter is applied in the fallback (`node is None`) branch too.
- [ ] `token_count` accounts for the frontmatter.
- [ ] With `triage=None` (the `build`/`upsert` path), **no frontmatter is
      emitted** and page records are byte-identical to pre-FEAT-451 output.
- [ ] `"discard"` still creates no pages and makes no PageIndex call.
- [ ] `DocumentAcquisitionError` propagates out of `_load_source`.
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_ingest.py -v`
- [ ] `ruff check` and `mypy` clean.

---

## Test Specification

```python
# tests/knowledge/wiki/test_ingest.py  (append)
import yaml
import pytest


class TestFrontmatterWiring:
    async def test_pages_carry_frontmatter(self, orchestrator, triage_entry, wiki_config):
        report = await orchestrator.ingest(
            "/tmp/a.pdf", wiki_config, triage=triage_entry, charter_version="1.2.0"
        )
        record = ...   # fetch the created WikiPageRecord
        assert record.body.startswith("---\n")
        block = record.body.split("---\n")[1]
        parsed = yaml.safe_load(block)
        assert parsed["triage"]["charter_version"] == "1.2.0"
        assert parsed["triage"]["composite_score"] == triage_entry.composite
        assert parsed["triage"]["decision"] == (
            triage_entry.decision or triage_entry.proposed_action
        )

    async def test_all_pages_identical_frontmatter(self, orchestrator_multi_node, ...):
        records = ...
        blocks = [r.body.split("---\n")[1] for r in records]
        assert len(set(blocks)) == 1

    async def test_fallback_branch_gets_frontmatter(self, orchestrator_no_tree, ...):
        """node is None branch must also be prefixed."""
        ...

    async def test_token_count_includes_frontmatter(self, ...):
        ...

    async def test_legacy_path_emits_no_frontmatter(self, orchestrator, wiki_config):
        """triage=None -> build/upsert path -> byte-identical, no frontmatter."""
        report = await orchestrator.ingest("/tmp/a.md", wiki_config)
        record = ...
        assert not record.body.startswith("---\n")

    async def test_metadata_persisted(self, orchestrator, triage_entry, wiki_config, sources):
        await orchestrator.ingest(
            "/tmp/a.pdf", wiki_config, triage=triage_entry, charter_version="1.2.0"
        )
        entry = sources.find_by_uri("/tmp/a.pdf")
        assert sources.get_source(entry).doc_metadata is not None

    async def test_acquisition_error_propagates(self, orchestrator, wiki_config):
        from parrot.knowledge.wiki.documents import DocumentAcquisitionError
        with pytest.raises(DocumentAcquisitionError):
            await orchestrator.ingest("/tmp/undecodable.pdf", wiki_config)

    async def test_discard_creates_nothing(self, orchestrator, discard_entry, wiki_config):
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 6, §7).
2. **Check dependencies** — TASK-2352, TASK-2353, TASK-2355 must all be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `ingest.py:161-230` and
   `709-800`, and confirm `ManifestDocEntry.composite` is still the field name
   (NOT `composite_score`). Update this contract first if anything moved.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2356-orchestrator-frontmatter-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
