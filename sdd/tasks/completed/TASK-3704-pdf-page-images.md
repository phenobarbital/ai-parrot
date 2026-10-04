# TASK-3704: extract_markdown_per_page images_dir + extract_page_images (M6)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

> Parallelism: `parallel: true` — no dependency — additive edit to pageindex/pdf_to_markdown.py, the only task touching that file.

---

## Context

Spec §3 **Module 6 (Figures)**, first half. Nothing in the ingestion path keeps figures today
(proposal F013/F015/F031): `extract_markdown_per_page` calls `pymupdf4llm.to_markdown(path, page_chunks=True)`
without image output. This task adds an **additive** `images_dir` keyword (so the per-page markdown carries
`![](…)` refs) and a sibling `extract_page_images()` that returns every page image with its bbox and sha256.
The `(page, text)` return contract and the "never pass `pages=`" rule are preserved byte-for-byte (**AC12**).
`TASK-3705` (figures.py) consumes `PageImage` / `extract_page_images`.

---

## Scope

- Add keyword-only params `images_dir`, `image_format="png"`, `dpi=150`, `image_size_limit=0.05` to
  `extract_markdown_per_page`; forward `write_images=True, image_path=…, image_format=…, dpi=…, image_size_limit=…`
  to `pymupdf4llm.to_markdown` **only when `images_dir` is not None**.
- Add `PageImage` (Pydantic v2) and `extract_page_images(pdf_path, images_dir, *, dpi=150, min_area_ratio=0.05)`.
- Write tests `test_extract_markdown_per_page_unchanged_without_images_dir` and `test_extract_page_images_bbox`.

**NOT in scope**: caption pairing, upload, vision (TASK-3705); any change to `build_node_markdown_map` or to
`builder.py` callers; OCR of image-only pages (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` | MODIFY | additive `images_dir` kwargs + `PageImage` + `extract_page_images` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py` | CREATE | unit tests (mocked `to_markdown`, synthetic PDF) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pymupdf        # verified: pageindex/pdf_to_markdown.py:21-24 (guarded try/except, None on ImportError); pymupdf 1.27.1 in venv
import pymupdf4llm    # verified: pageindex/pdf_to_markdown.py:26-29 (guarded); pymupdf4llm 0.0.27 in venv
from pydantic import BaseModel, Field   # pydantic v2 (repo-wide)
import hashlib        # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py
logger = logging.getLogger("parrot.knowledge.pageindex.pdf_to_markdown")            # :32
def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]:       # :35
    # NB: NEVER pass ``pages=`` here — ...                                          # :69-70
    chunks = pymupdf4llm.to_markdown(path_str, page_chunks=True)                    # :71
    # page-count mismatch ⇒ ValueError                                              # :78-83
def build_node_markdown_map(structure: object, pages: list[tuple[int, str]]) -> dict[str, str]   # :97

# pymupdf4llm.to_markdown parameters (verified via inspect.signature, 0.0.27):
#   doc, pages, hdr_info, write_images, embed_images, ignore_images, ..., image_path, image_format,
#   image_size_limit, ..., page_chunks, ..., dpi, ...
# pymupdf.Page.get_image_info / pymupdf.Page.get_image_bbox exist (verified: hasattr on 1.27.1)
```

### Does NOT Exist
- ~~Any PDF image extraction in the repo (`write_images`, `Pixmap`, `extract_image`, `get_image_bbox` callers)~~ — none (F015, F031).
- ~~`PageImage`, `extract_page_images`~~ — created by this task.
- ~~A `pages=` argument in this module's `to_markdown` call~~ — forbidden (index-space alignment with `get_page_tokens`).
- ~~`extract_markdown_per_page` used by `ContractLibrary`~~ — contracts uses raw `page.get_text()` (F013).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py#extract_markdown_per_page"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- Behaviour without `images_dir` must be **identical** (same `to_markdown` kwargs: exactly `page_chunks=True`) — AC12.
- `pymupdf` work is synchronous and file-bound; callers in async code wrap it with `asyncio.to_thread` (TASK-3705/3713) — keep these functions sync.
- No new third-party dependency; Google docstrings, strict type hints, Pydantic v2, module `logger` (no `print`).
- Ontology imports rule (AC17) is not relevant here; keep imports local to pymupdf.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py:35-94` — function to extend.
- `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py:54-61` — `is_image_only` semantics (informational only).

---

## Implementation Blueprint

### Steps (in order)
1. Change the signature of `extract_markdown_per_page` to add the keyword-only image params — *why*: additive API keeps every existing caller (`builder._extract_node_markdown`) valid.
2. Build `kwargs = {"page_chunks": True}` and extend it only when `images_dir` is set (mkdir it first) — *why*: AC12 demands byte-identical behaviour when the kwarg is absent.
3. Append `PageImage` + `extract_page_images` after `extract_markdown_per_page` — *why*: a sibling function keeps the `(page, text)` tuple contract untouched while exposing bboxes for caption pairing.
4. Write the two tests — *why*: they are the AC12 evidence.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def extract_markdown_per_page(pdf_path: str | Path) -> list\[tuple\[int, str\]\]:' pdf_to_markdown.py)
# REPLACE the signature line at pdf_to_markdown.py:35 with:
def extract_markdown_per_page(
    pdf_path: str | Path,
    *,
    images_dir: str | Path | None = None,
    image_format: str = "png",
    dpi: int = 150,
    image_size_limit: float = 0.05,
) -> list[tuple[int, str]]:
    # (docstring: add Args for the four new kwargs — "with images_dir the per-page markdown carries ![](…) refs")

# occurrences: 1 (verified: grep -c 'chunks = pymupdf4llm.to_markdown(path_str, page_chunks=True)' pdf_to_markdown.py)
# REPLACE the call at pdf_to_markdown.py:71 with:
    kwargs: dict[str, object] = {"page_chunks": True}
    if images_dir is not None:
        Path(images_dir).mkdir(parents=True, exist_ok=True)
        kwargs.update(
            write_images=True,
            image_path=os.fspath(images_dir),
            image_format=image_format,
            dpi=dpi,
            image_size_limit=image_size_limit,
        )
    chunks = pymupdf4llm.to_markdown(path_str, **kwargs)

# occurrences: 1 (verified: grep -c '^def build_node_markdown_map(' pdf_to_markdown.py)
# BEFORE — insert above `def build_node_markdown_map(` (verified: pdf_to_markdown.py:97)
class PageImage(BaseModel):
    """One raster image placed on a PDF page, with its bbox in page points."""

    page: int = Field(..., ge=1, description="1-based physical page")
    index: int = Field(..., ge=0, description="order of the image on its page")
    path: Path
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    sha256: str


def extract_page_images(
    pdf_path: str | Path,
    images_dir: str | Path,
    *,
    dpi: int = 150,
    min_area_ratio: float = 0.05,
) -> list[PageImage]:
    """Extract every sufficiently large page image with its bbox.

    Uses ``Page.get_image_info(xrefs=True)`` + ``Page.get_image_bbox`` per page (F026 probe). Keeps the
    ``(page, text)`` contract of :func:`extract_markdown_per_page` intact.

    Args:
        pdf_path: Source PDF.
        images_dir: Directory the PNG files are written to (created if missing).
        dpi: Render resolution for the clipped pixmap.
        min_area_ratio: Images whose bbox area is below this fraction of the page area are skipped.

    Returns:
        Images in (page, index) order.

    Raises:
        ImportError: pymupdf missing.  FileNotFoundError: pdf_path missing.
    """
    if pymupdf is None:
        raise ImportError("extract_page_images requires pymupdf; install the [pdf] extra.")
    out_dir = Path(images_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[PageImage] = []
    doc = pymupdf.open(os.fspath(pdf_path))
    try:
        for page in doc:
            # FILL IN: iterate page.get_image_info(xrefs=True); compute bbox (info["bbox"] or page.get_image_bbox);
            #   skip area < min_area_ratio * page.rect area; render page.get_pixmap(clip=bbox, dpi=dpi), save as
            #   f"p{page.number + 1:04d}-{index:02d}.png", sha256 of the written bytes — bounded by AC12 (never mutate
            #   the markdown path) and deterministic file names (stable across runs).
            pass
    finally:
        doc.close()
    logger.debug("extract_page_images: %d image(s) from %s", len(results), pdf_path)
    return results
```
Also add `import hashlib` and `from pydantic import BaseModel, Field` to the import block (top of file, after `from pathlib import Path` at :19).

**Why this shape**: the kwargs dict is the smallest change that guarantees the old call is literally
`to_markdown(path_str, page_chunks=True)`. Rendering a clipped pixmap (rather than `extract_image(xref)`) gives
the figure exactly as laid out, including vector overlays such as callout numbers.

### `packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py` (CREATE)
```python
"""FEAT-601 M6 — additive image extraction in pdf_to_markdown (AC12)."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

pymupdf = pytest.importorskip("pymupdf")

from parrot.knowledge.pageindex import pdf_to_markdown as p2m  # noqa: E402


def _two_image_pdf(path: Path) -> Path:
    """Build a 1-page PDF carrying two raster images at known rects."""
    # FILL IN: pymupdf.open(); new_page(); insert_image(rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0,0,200,200), 0))
    #   twice at non-overlapping rects large enough to pass min_area_ratio; save — bounded by: no external files.
    return path


def test_extract_markdown_per_page_unchanged_without_images_dir(tmp_path: Path) -> None:
    pdf = _two_image_pdf(tmp_path / "a.pdf")
    with mock.patch.object(p2m.pymupdf4llm, "to_markdown", return_value=[{"text": "x"}]) as tm:
        assert p2m.extract_markdown_per_page(pdf) == [(1, "x")]
    tm.assert_called_once_with(str(pdf), page_chunks=True)
    # FILL IN: second call with images_dir=tmp_path/"img" asserts write_images/image_path forwarded and "pages" not in kwargs


def test_extract_page_images_bbox(tmp_path: Path) -> None:
    pdf = _two_image_pdf(tmp_path / "b.pdf")
    images = p2m.extract_page_images(pdf, tmp_path / "img")
    assert len(images) == 2
    # FILL IN: bboxes match the inserted rects (tolerance 1pt), sha256 is 64 hex chars, files exist, order stable
```

### FILL IN checklist
- [ ] `extract_page_images` per-image loop — bbox, area filter, pixmap render, sha256; bounded by AC12 + deterministic names.
- [ ] `_two_image_pdf` synthetic builder — bounded by: no fixtures from other tasks.
- [ ] Test assertions for the `images_dir` branch and bboxes.

---

## Acceptance Criteria

- [ ] `extract_markdown_per_page(path)` calls `to_markdown(path, page_chunks=True)` exactly; `pages=` never passed (AC12).
- [ ] With `images_dir`, `write_images/image_path/image_format/dpi/image_size_limit` are forwarded.
- [ ] `extract_page_images` returns two `PageImage`s with bboxes + sha256 for the synthetic PDF (AC12).
- [ ] Existing pageindex tests still pass; `ruff check` + `black --check -l 120` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_pdf_page_images.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_ingest.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_extract_markdown_per_page_unchanged_without_images_dir` | call signature/return identical; `pages=` never passed (mock `to_markdown`) |
| `test_extract_page_images_bbox` | synthetic PDF with two images ⇒ two `PageImage`s with bboxes and sha256 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/training-agent.spec.md` (module section named in Context).
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/` (or merged in your feature branch).
3. **Verify the Codebase Contract** — before writing ANY code confirm every import, signature and line anchor
   above still holds (`grep -n` / `read`). Symbols marked "created by TASK-<X>" must exist now that the
   dependency landed; if a name differs, follow the landed code and record the deviation.
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes.
6. **Verify** — run every command in *Validation Commands* (with the worktree `PYTHONPATH`), plus `ruff check`
   and `black --check -l 120` on the touched files.
7. **Move this file** to `sdd/tasks/completed/`, set the index entry to `"done"`, fill in the Completion Note.

---

## Completion Note


- Task: TASK-3704
- Feature: training-agent
- Implementation SHA: 4f5e0cc575a567a0104cde4abbe7147e0109d354
- Closed at (UTC): 2026-09-24T23:24:06+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: haiku(native sonnet) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
| supplementary_test_evidence | 460 passed, 56 skipped, 0 failed (scoped direct pytest run over common/pageindex/contracts) |
