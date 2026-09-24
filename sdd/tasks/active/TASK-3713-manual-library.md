# TASK-3713: ManualLibrary staged ingest, video, refresh, verify (M8)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-3706, TASK-3708, TASK-3709, TASK-3712
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8** (library half) and §2 Overview "Ingest", "Video", "Re-ingest".
`ManualLibrary` copies the `ContractLibrary` flow — sha256 dedup → markdown → staged PageIndex
tree (`create_tree` → `insert_markdown` → `get_tree` → `derive_toc`) → carding → figure
extraction/captioning/callouts/upload → `assemble_card` → evidence snapshot →
`catalog.upsert(card, version=…)` → graph publication → tip relink report → verification-queue
entries — inserting the M5/M6/M7 hooks built by earlier tasks. PDF markdown comes from
`extract_markdown_per_page(images_dir=…)` (NOT contracts' raw `page.get_text()`, F013) so figure
references survive. Image-only PDFs are refused (v1 Non-Goal: no OCR).

Parallelism: orchestrates draft_manual/assemble_card from TASK-3708 (manuals/carding.py),
extract/caption/upload/map_callouts from TASK-3706 (manuals/figures.py), align_video from
TASK-3709 (manuals/video.py) and ManualGraphLoader from TASK-3712 (manuals/graph_loader.py).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/manuals/library.py` with `TreeIndexer`
  (4-method protocol, identical to contracts), `IngestResult`, `ImageOnlyManual`,
  `ManualLibrary` per the spec §3 M8 skeleton (signatures fixed).
- `add_manual(source, *, equipment, revision, source_uri=None, force=False)`:
  read bytes → sha256 → `catalog.find_by_sha` / `find_by_source_uri` (unchanged ⇒
  `status="unchanged"` unless `force`) → `_to_markdown` → PageIndex staged tree
  (`tree_name == manual_id`) → `derive_toc` → `draft_manual` → `extract_figures` →
  `caption_figures` (only when a captioner resolves; `CaptioningUnavailable` ⇒ warning, not
  failure) → `map_callouts` (only when `settings.callouts_enabled`, see TASK-3706) →
  `upload_figures` → `assemble_card` → write the evidence snapshot → `catalog.upsert(card,
  version=ManualVersion(...))` → `graph_loader.publish(card)` when a loader is configured →
  `IngestResult` with counts and queue entries.
- `manual_id` = `unique_slug(slugify(f"{equipment[0]} {revision}"), taken)`; an empty slug (non-Latin
  titles collapse, Known Risk) ⇒ `ValueError` asking for an explicit slug. Keep a
  `slug: str | None = None` kwarg **only if** you can add it without changing the fixed
  signature order — otherwise raise and document.
- `add_folder`, `add_video` (delegates to `align_video`; for each `(media_ref, media_link)` pair
  attach the link to the step whose `identity.step_id == media_ref.label`; refs with `label is None`
  are procedure-level overview media; persist on the card via `upsert(expected_revision=…)`), `refresh` (new `ManualVersion` appended: previous
  `valid_to = today`, new `valid_from = today`; passes `SourceInfo(previous_card=<current card>)` so `assemble_card` carries forward `StepIdentity` for steps matched by
  `source_identity`/`content_hash` so tips relink without a graph round-trip — Known Risk
  "positional step identity"), `verify_procedure` (flip `verification="verified"`, stamp
  `verified_by/at` in `field_provenance`, freeze the current version).
- `_to_markdown`: PDF ⇒ `extract_markdown_per_page(path, images_dir=images_dir)` joined as
  `## Page N` sections + page hints; zero text on every page but images present ⇒
  `ImageOnlyManual`; DOCX ⇒ `bookstore.library.docx_to_markdown`; md/txt ⇒ read text.
- Evidence snapshot (manuals must not import `contracts.evidence`): write
  `<evidence_root>/<tenant_id>/<manual_id>/v<version_n>/sections.json` (`node_id → body`) +
  `source.<ext>`; expose `async def load_section(manual_id, node_id, *, version_n) -> str | None`
  for the verifier (TASK-3722).
- Write `packages/ai-parrot/tests/knowledge/manuals/test_library.py`.

**NOT in scope**: carding/figure/video internals (TASK-3705–3709), the graph loader (TASK-3712),
the CLI (TASK-3727), Postgres (TASK-3703), OCR.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/library.py` | CREATE | ingest/refresh/verify orchestration |
| `packages/ai-parrot/tests/knowledge/manuals/test_library.py` | CREATE | fake-indexer pipeline, refresh, image-only refusal |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.carding import derive_toc, slugify, unique_slug  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:88, 49, 73
from parrot.knowledge.bookstore.library import docx_to_markdown  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:104 (async, Path -> str)
from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page  # verified: pdf_to_markdown.py:35 — `images_dir` kwarg added by TASK-3704
# PageIndexToolkit is lazy-imported in the default indexer factory, as contracts/library.py:1222-1226:
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
# Created by earlier FEAT-601 tasks (spec §3 skeletons):
from parrot.knowledge.manuals.catalog import ManualCatalogStore                  # TASK-3702
from parrot.knowledge.manuals.models import ManualCard, ManualVersion, SourceFormat  # TASK-3699
from parrot.knowledge.manuals.carding import draft_manual, assemble_card, SourceInfo  # TASK-3707/3708 — SourceInfo(figure_candidates=..., previous_card=...) is defined by TASK-3708 (manuals/carding.py); refresh() passes previous_card
from parrot.knowledge.manuals.figures import (extract_figures, caption_figures, upload_figures, resolve_captioner,
    CaptioningUnavailable, resolve_callout_mapper, map_callouts)                  # TASK-3705/3706
from parrot.knowledge.manuals.video import align_video, AlignmentReport, JudgementLog  # created by TASK-3709 (manuals/video.py) — align_video returns (media_refs, media_links, report); media_links[i] pairs with media_refs[i]; the target step id is carried in MediaRef.label (MediaLink has no step field); overview refs have label None
from parrot.knowledge.manuals.graph_loader import ManualGraphLoader               # TASK-3712
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/contracts/library.py (template — copy, never import)
class TreeIndexer(Protocol):                                                              # :96-115
    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]
    async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None, doc_name: Optional[str] = None) -> dict[str, Any]
    async def get_tree(self, tree_name: str) -> dict[str, Any]
    async def delete_tree(self, tree_name: str) -> dict[str, Any]
def pdf_markdown(pages: Sequence[str]) -> str                                            # :205-220 — "## Page N" sections, empty pages skipped
class ContractLibrary: __init__(*, catalog, storage_root, evidence_root, adapter=None, indexer_factory=None, …, now=_utcnow)  # :481-514
    async def add_contract(self, source, *, source_uri=None, force=False) -> IngestResult   # :516-607 (sha dedup :540-575)
    async def _to_markdown(self, path, source_format) -> tuple[str, dict[int, int]]        # :910-947 — page hints map section index → page
def _default_indexer_factory(storage_dir: Path, adapter: Any) -> TreeIndexer             # :1222-1226 — PageIndexToolkit(adapter=adapter, storage_dir=storage_dir)

# packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py
def derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str]   # :88
def slugify(text: str) -> str                                                             # :49 — non-Latin titles collapse (Known Risk)
def unique_slug(base: str, taken: set[str]) -> str                                        # :73

# packages/ai-parrot-loaders/src/parrot_loaders/pdf.py:54-61 — is_image_only semantics to mirror (no text AND page.get_images())
```

### Does NOT Exist
- ~~`extract_markdown_per_page` used by `ContractLibrary`~~ — contracts uses raw `page.get_text()` (F013); we use the markdown path.
- ~~Importing `parrot.knowledge.contracts.library` / `.evidence` (`StagingArea`, `EvidenceArchive`)~~ — manuals must not import contracts (M1 goal); the evidence snapshot is this module's own file layout.
- ~~OCR for scanned PDFs~~ — refused with `ImageOnlyManual` (v1).
- ~~`ManualLibrary.relate_*`~~ — no relation stage in v1.
- ~~Timecoded Gemini scenes / `VideoUnderstandingLoader`~~ — not used (F025).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/library.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_library.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#derive_toc",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#slugify",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#unique_slug",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#docx_to_markdown",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py#extract_markdown_per_page"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- Ontology imports (if any) from submodules only (AC17). No new dependency. Google docstrings, strict hints, Pydantic v2, `self.logger`.
- Blocking work (`read_bytes`, pymupdf) runs in `asyncio.to_thread` — never block the loop.
- `tree_name == manual_id` (spec M2). On any failure after `create_tree`, delete the staged tree before returning `status="refused"` with the reason in `warnings`.
- Queue entries: `figures_unpaired` (cited-but-missing figure refs), unresolved callouts, low-confidence steps, unparseable serial qualifiers — list their ids in `IngestResult.queue_entries`.
- Tests use `FakeIndexer`/`FakeAdapter` from `packages/ai-parrot/tests/knowledge/_support/adapter.py`, `FakeFileManager` from `_support/files.py`, synthetic PDFs from `_support/pdfs.py` (TASK-3698), `InMemoryManualCatalog` from `_support/catalog.py` (TASK-3702); fixtures `manual_pdf`, `manual_pdf_rev_b`, `image_only_pdf`, `fake_adapter`, `fake_file_manager` from `tests/knowledge/manuals/conftest.py`.
- If a helper name from TASK-3705–3709 differs from the spec skeleton when you start, follow the landed code and record it in the Completion Note — the spec skeleton is the default.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/contracts/library.py:481-1226` — flow template.

---

## Implementation Blueprint

### Steps (in order)
1. Declare `TreeIndexer`, `IngestResult`, `ImageOnlyManual`, `_utcnow`, `_default_indexer_factory` — *why*: tests inject a fake indexer through `indexer_factory`.
2. Implement `_to_markdown` over `extract_markdown_per_page(images_dir=…)` + image-only detection — *why*: AC12/F013 — figure refs must survive and scanned manuals are refused.
3. Implement the private `_ingest(path, manual_id, …)` pipeline used by both `add_manual` and `refresh` — *why*: one code path keeps dedup, staging and versioning consistent.
4. Implement `add_manual`, `add_folder`, `add_video`, `refresh`, `verify_procedure`, `load_section` — *why*: the CLI (TASK-3727) and spikes (TASK-3726) call exactly these.
   - `add_video`: `media_refs, media_links, report = await align_video(...)`; pair by index and route each link to the step with `identity.step_id == media_ref.label` (label `None` ⇒ procedure overview media) — *why*: `MediaLink` has no step field; the label is the only step pointer TASK-3709 carries.
   - `refresh`: build `SourceInfo(figure_candidates=…, previous_card=<stored card>)` — *why*: `assemble_card` (TASK-3708) does the step-id carry-forward from `previous_card`; without it every step is re-minted and tips orphan.
5. Write tests — *why*: `test_add_manual_pipeline_fake_indexer` and `test_refresh_appends_version_and_relinks` are spec §4 M8.

### `packages/ai-parrot/src/parrot/knowledge/manuals/library.py` (CREATE) — part 1: types + markdown
```python
"""ManualLibrary: staged ingest of assembly manuals into cards (FEAT-601 M8)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from ..bookstore.carding import derive_toc, slugify, unique_slug
from ..pageindex.pdf_to_markdown import extract_markdown_per_page
from .carding import SourceInfo, assemble_card, draft_manual
from .catalog import ManualCatalogStore
from .figures import (CaptioningUnavailable, caption_figures, extract_figures, map_callouts,
                      resolve_callout_mapper, resolve_captioner, upload_figures)
from .graph_loader import ManualGraphLoader
from .models import ManualCard, ManualVersion, SourceFormat
from .video import AlignmentReport, JudgementLog, align_video

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImageOnlyManual(ValueError):
    """The PDF has no extractable text (scanned); OCR is out of scope in v1."""


class TreeIndexer(Protocol):
    """The PageIndex surface the library depends on (PageIndexToolkit or a test double)."""

    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]: ...
    async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None,
                              doc_name: Optional[str] = None) -> dict[str, Any]: ...
    async def get_tree(self, tree_name: str) -> dict[str, Any]: ...
    async def delete_tree(self, tree_name: str) -> dict[str, Any]: ...


def _default_indexer_factory(storage_dir: Path, adapter: Any) -> TreeIndexer:
    """Build a real PageIndexToolkit over ``storage_dir`` (heavy import kept lazy)."""
    from ..pageindex.toolkit import PageIndexToolkit  # noqa: PLC0415

    return PageIndexToolkit(adapter=adapter, storage_dir=storage_dir)


class IngestResult(BaseModel):
    """Outcome of one ingest/refresh; counts feed the CLI summary and spikes."""

    card: Optional[ManualCard] = None
    status: Literal["created", "updated", "unchanged", "refused"]
    procedures: int = 0
    steps: int = 0
    figures_paired: int = 0
    figures_unpaired: int = 0
    hazards: int = 0
    tips_relinked: int = 0
    tips_orphaned: int = 0
    queue_entries: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _source_format(path: Path) -> SourceFormat:
    """Map the suffix to SourceFormat; unsupported ⇒ ValueError."""
    # FILL IN: .pdf/.docx/.md/.markdown/.txt — bounded by SourceFormat literal (TASK-3699)
    raise NotImplementedError
```
**Why**: the spec skeleton types `IngestResult.card` as required; a `"refused"` result has no
card, so it is `Optional` here — record this in the Completion Note as the one deliberate
relaxation (the alternative, a fake card, would violate G2).

### `library.py` — part 2: `ManualLibrary` (append below part 1)
```python
class ManualLibrary:
    """Ingest manuals into the tenant catalog, then publish to the graph."""

    def __init__(self, *, catalog: ManualCatalogStore, storage_root: str | Path, evidence_root: str | Path,
                 adapter: Any = None, file_manager: Any, vision_client: Any | None = None,
                 indexer_factory: Optional[Callable[[Path, Any], TreeIndexer]] = None,
                 graph_loader: Optional[ManualGraphLoader] = None, max_procedure_sections: int = 20,
                 now: Callable[[], datetime] = _utcnow) -> None:
        self.catalog = catalog
        self.storage_root = Path(storage_root)
        self.evidence_root = Path(evidence_root)
        self.adapter = adapter
        self.file_manager = file_manager
        self.vision_client = vision_client
        self.graph_loader = graph_loader
        self.max_procedure_sections = max_procedure_sections
        self._indexer_factory = indexer_factory or _default_indexer_factory
        self._now = now
        self.logger = logging.getLogger(__name__)

    async def add_manual(self, source: str | Path, *, equipment: Sequence[str], revision: str,
                         source_uri: Optional[str] = None, force: bool = False) -> IngestResult:
        """sha dedup → markdown → staged tree → carding → figures → assemble → upsert → publish."""
        # FILL IN: dedup (find_by_sha/find_by_source_uri) ⇒ "unchanged" unless force; allocate manual_id; call self._ingest
        raise NotImplementedError

    async def add_folder(self, folder: str | Path, *, recursive: bool = False, force: bool = False) -> list[IngestResult]:
        """Ingest every supported file; equipment/revision come from a sidecar `<file>.manual.json` — FILL IN or refuse per file."""
        raise NotImplementedError

    async def add_video(self, manual_id: str, *, uri: str, transcript: Mapping[str, Any] | None = None,
                        local_path: Optional[Path] = None, force: bool = False) -> AlignmentReport:
        """align_video over the stored card; persist segments with expected_revision; judgement log under storage_root."""
        # FILL IN: transcript None ⇒ build via parrot_loaders (optional import, RuntimeError hint) from uri/local_path
        # media_refs, media_links, report = await align_video(card, uri=uri, transcript=..., adapter=self.adapter, judgement_log=..., force=force)
        # for ref, link in zip(media_refs, media_links):
        #     step = next(s for p in card.procedures for s in p.steps if s.identity.step_id == ref.label) if ref.label else None
        #     FILL IN: step is None ⇒ append ref to procedure-level overview media; else step.media.append(link); card.figures.append(ref)
        raise NotImplementedError

    async def refresh(self, manual_id: str, source: str | Path, *, revision: str) -> IngestResult:
        """New revision: append ManualVersion (prev valid_to = new valid_from = today), carry forward step identities, publish, relink."""
        # FILL IN: previous = await self.catalog.get(manual_id); self._ingest(..., previous=previous) must build
        #          SourceInfo(figure_candidates=..., previous_card=previous) for assemble_card (TASK-3708) — bounded by R1
        raise NotImplementedError

    async def verify_procedure(self, manual_id: str, procedure_id: str, *, user: str,
                               expected_revision: Optional[int] = None) -> ManualCard:
        """Flip verification → verified (verified_by/at) and freeze the current ManualVersion."""
        raise NotImplementedError

    async def load_section(self, manual_id: str, node_id: str, *, version_n: int) -> Optional[str]:
        """Body of ``node_id`` in the archived snapshot of ``version_n`` (read by ProcedureVerifier)."""
        raise NotImplementedError

    async def _ingest(self, path: Path, *, manual_id: str, equipment: Sequence[str], revision: str,
                      source_uri: Optional[str], sha256: str, previous: Optional[ManualCard]) -> IngestResult:
        """Shared pipeline; deletes the staged tree and returns 'refused' on any failure."""
        # FILL IN: order fixed by spec §2 Ingest; captioning optional (CaptioningUnavailable ⇒ warning);
        #          callouts only when figures' callouts_enabled setting is on (AC21);
        #          assemble_card(draft, manual_id=..., source=SourceInfo(figure_candidates=figures, previous_card=previous), ...)
        raise NotImplementedError

    async def _to_markdown(self, path: Path, source_format: SourceFormat, *, images_dir: Path) -> tuple[str, dict[int, int]]:
        """PDF via extract_markdown_per_page(images_dir=…) as '## Page N'; DOCX via docx_to_markdown; image-only ⇒ ImageOnlyManual."""
        raise NotImplementedError

    def _write_evidence(self, manual_id: str, version_n: int, bodies: Mapping[str, str], source: Path) -> str:
        """Write <evidence_root>/<tenant>/<manual_id>/v<n>/sections.json + source copy; return the evidence_ref path."""
        raise NotImplementedError
```
**Why**: signatures are fixed by spec §3 M8. `add_video` pairs `media_refs[i]` with `media_links[i]`
and finds the step through `MediaRef.label == step.identity.step_id` because TASK-3709's `MediaLink`
carries no step field — a `None` label marks a procedure-level overview segment. `refresh` passes
`SourceInfo(previous_card=…)` because TASK-3708's `assemble_card` owns the step-id carry-forward (R1).
`load_section`/`_write_evidence` are the minimal additions required because the spec keeps `EvidenceArchive` in contracts (U2 narrowed) while M1
forbids manuals importing contracts.

### `packages/ai-parrot/tests/knowledge/manuals/test_library.py` (CREATE)
```python
"""ManualLibrary pipeline with fake indexer/adapter/file manager (FEAT-601 M8)."""
from __future__ import annotations

import pytest

from parrot.knowledge.manuals.library import ImageOnlyManual, IngestResult, ManualLibrary

from .._support.catalog import InMemoryManualCatalog  # TASK-3702


@pytest.mark.asyncio
async def test_add_manual_pipeline_fake_indexer(manual_pdf, fake_adapter, fake_file_manager, tmp_path) -> None:
    """Card with 1 procedure / 5 ordered steps, 2 paired figures uploaded (storage keys, no URLs), queue entries listed."""


@pytest.mark.asyncio
async def test_add_manual_refuses_image_only(image_only_pdf, fake_adapter, fake_file_manager, tmp_path) -> None:
    """status='refused' with an OCR-not-supported warning; no catalog write."""


@pytest.mark.asyncio
async def test_add_manual_unchanged_on_same_sha(manual_pdf, fake_adapter, fake_file_manager, tmp_path) -> None:
    """Second add ⇒ 'unchanged'; force=True re-cards."""


@pytest.mark.asyncio
async def test_refresh_appends_version_and_relinks(manual_pdf, manual_pdf_rev_b, fake_adapter, fake_file_manager, tmp_path) -> None:
    """rev B ⇒ versions[] appended with valid_from/valid_to; carried-forward step ids; relink counts populated."""


@pytest.mark.asyncio
async def test_verify_procedure_freezes_version(manual_pdf, fake_adapter, fake_file_manager, tmp_path) -> None:
    """verification == 'verified', verified_by stamped."""
```

### FILL IN checklist
- [ ] `_source_format`
- [ ] `add_manual` dedup + slug allocation (empty slug ⇒ ValueError)
- [ ] `add_folder` sidecar policy
- [ ] `add_video` transcript acquisition (optional loaders import)
- [ ] `refresh` version append + identity carry-forward; bounded by R1
- [ ] `verify_procedure`
- [ ] `load_section` / `_write_evidence` layout
- [ ] `_ingest` fixed order + tree cleanup on failure
- [ ] `_to_markdown` + image-only detection; bounded by AC12
- [ ] five tests

---

## Acceptance Criteria

- [ ] `test_add_manual_pipeline_fake_indexer` and `test_refresh_appends_version_and_relinks` pass (spec §4 M8).
- [ ] Image-only PDFs are refused with a clear message; no OCR attempted.
- [ ] No URL is stored on any `MediaRef` (storage keys only — AC13).
- [ ] `library.py` imports nothing from `parrot.knowledge.contracts`.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/manuals/library.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_library.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_library.py
async def test_add_manual_pipeline_fake_indexer(): ...      # spec §4 M8
async def test_add_manual_refuses_image_only(): ...
async def test_add_manual_unchanged_on_same_sha(): ...
async def test_refresh_appends_version_and_relinks(): ...   # spec §4 M8
async def test_verify_procedure_freezes_version(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3713-manual-library.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
