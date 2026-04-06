# TASK-587: Grid-Based Detection Orchestrator

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-583, TASK-584, TASK-586
**Assigned-to**: unassigned

---

## Context

This is the core orchestrator that ties the grid system together. It takes a list of grid cells, crops images, builds per-cell prompts with filtered hints and reference images, executes parallel LLM calls via `asyncio.gather()`, and merges results. Implements Spec Module 5.

---

## Scope

- Implement `GridDetector` class with:
  - `__init__(self, llm, reference_images, logger)` — stores LLM client and reference images
  - `async detect_cells(cells: List[GridCell], image: Image.Image, grid_config: DetectionGridConfig) -> List[IdentifiedProduct]`
    1. For each `GridCell`: crop image to cell bbox, downscale to `grid_config.max_image_size`
    2. Build per-cell prompt with only that cell's `expected_products` as hints
    3. Filter `reference_images` to only keys matching `cell.reference_image_keys`
    4. Execute all cell LLM calls in parallel via `asyncio.gather(*tasks, return_exceptions=True)`
    5. Handle per-cell failures: log error, skip failed cell, continue with others
    6. Pass results to `CellResultMerger.merge()` for offset correction + deduplication
    7. Return merged `List[IdentifiedProduct]`
- Support multi-reference images per product: if `reference_images[key]` is a list, pass all images
- Write unit tests with mocked LLM calls

**NOT in scope**: Modifying existing pipeline flow (that's TASK-590).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/detector.py` | CREATE | GridDetector orchestrator |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py` | MODIFY | Add export |
| `tests/pipelines/test_grid_detector.py` | CREATE | Unit tests with mocked LLM |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio  # stdlib
import logging  # stdlib
from typing import Any, Dict, List, Optional, Tuple, Union  # stdlib
from pathlib import Path  # stdlib
from PIL import Image  # pillow

from parrot_pipelines.planogram.grid.models import GridCell, DetectionGridConfig
from parrot_pipelines.planogram.grid.merger import CellResultMerger
from parrot.models.detections import IdentifiedProduct, DetectionBox
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/google/analysis.py:1094
# This is the LLM method we call per cell:
async def detect_objects(
    self,
    image: Union[str, Path, Image.Image],
    prompt: str,
    reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
    output_dir: Optional[Union[str, Path]] = None
) -> List[Dict[str, Any]]:
    # Returns list of dicts with: label, box_2d, confidence, type
    # box_2d: [ymin, xmin, ymax, xmax] normalized 0-1000
    # Image is resized to 1024x1024 internally

# packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py
# Image helpers (available on pipeline instance):
#   _downscale_image(img, max_side=1024, quality=82)
#   _enhance_image(pil_img, brightness=1.10, contrast=1.20)
```

### Does NOT Exist
- ~~`GridDetector`~~ — does not exist; this task creates it
- ~~`AbstractPipeline.detect_per_cell()`~~ — does not exist
- ~~`GoogleAnalysis.detect_objects_batch()`~~ — no batch method; call detect_objects() N times

---

## Implementation Notes

### Pattern to Follow
```python
class GridDetector:
    def __init__(self, llm: Any, reference_images: Dict[str, Any], logger: logging.Logger):
        self.llm = llm
        self.reference_images = reference_images
        self.logger = logger
        self.merger = CellResultMerger()

    async def detect_cells(
        self,
        cells: List[GridCell],
        image: Image.Image,
        grid_config: DetectionGridConfig,
    ) -> List[IdentifiedProduct]:
        tasks = [
            self._detect_single_cell(cell, image, grid_config)
            for cell in cells
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cell_results = []
        for cell, result in zip(cells, results):
            if isinstance(result, Exception):
                self.logger.error("Cell %s detection failed: %s", cell.cell_id, result)
                continue
            cell_results.append((cell, result))

        return self.merger.merge(cell_results)

    async def _detect_single_cell(
        self, cell: GridCell, image: Image.Image, grid_config: DetectionGridConfig
    ) -> List[IdentifiedProduct]:
        # 1. Crop image to cell bbox
        x1, y1, x2, y2 = cell.bbox
        cell_image = image.crop((x1, y1, x2, y2))
        # 2. Downscale
        cell_image.thumbnail([grid_config.max_image_size, grid_config.max_image_size])
        # 3. Build prompt with cell-specific hints
        hints = ", ".join(cell.expected_products) if cell.expected_products else "any products"
        prompt = self._build_cell_prompt(hints)
        # 4. Filter reference images
        refs = self._filter_references(cell.reference_image_keys)
        # 5. Call LLM
        raw = await self.llm.detect_objects(image=cell_image, prompt=prompt, reference_images=refs)
        # 6. Parse raw dicts into IdentifiedProduct (cell-relative coords)
        return self._parse_detections(raw, cell_image.size)
```

### Key Constraints
- All LLM calls must be async and parallel via `asyncio.gather`
- `return_exceptions=True` is critical — one failed cell must not kill others
- Per-cell prompt must instruct LLM to report ALL objects (not just expected ones)
- Reference image filtering: `self.reference_images[key]` may be `str|Path|Image` (single) or `List` (multi-ref per product). Handle both.
- Coordinate parsing: LLM returns `box_2d: [ymin, xmin, ymax, xmax]` normalized 0-1000. Convert to pixel coords relative to cell image size.
- Log cell_id and timing for each cell detection call

---

## Acceptance Criteria

- [ ] `GridDetector.detect_cells()` executes N parallel LLM calls for N cells
- [ ] Per-cell prompts contain only that cell's expected products as hints
- [ ] Reference images filtered per cell
- [ ] Multi-reference per product supported (list of images)
- [ ] Failed cells logged and skipped without affecting other cells
- [ ] Results merged with correct coordinate offsets
- [ ] All tests pass with mocked LLM

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot_pipelines.planogram.grid.detector import GridDetector
from parrot_pipelines.planogram.grid.models import GridCell, DetectionGridConfig, GridType


class TestGridDetector:
    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220", "box_2d": [100, 50, 400, 300], "confidence": 0.9, "type": "product"}
        ])
        return llm

    async def test_parallel_execution(self, mock_llm):
        """N cells produce N LLM calls."""
        detector = GridDetector(llm=mock_llm, reference_images={}, logger=MagicMock())
        cells = [
            GridCell(cell_id="top", bbox=(0, 0, 800, 300), expected_products=["ES-C220"]),
            GridCell(cell_id="mid", bbox=(0, 300, 800, 600), expected_products=["V39-II"]),
        ]
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS)
        await detector.detect_cells(cells, mock_image, config)
        assert mock_llm.detect_objects.call_count == 2

    async def test_cell_failure_isolation(self, mock_llm):
        """One cell failing doesn't block others."""
        mock_llm.detect_objects.side_effect = [Exception("API error"), [{"label": "V39-II", ...}]]
        ...

    async def test_reference_filtering(self, mock_llm):
        """Only relevant reference images sent per cell."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for the full detection flow diagram
2. **Check** TASK-583, TASK-584, TASK-586 are completed
3. **Read** `product_on_shelves.py:102-222` to understand the current detection flow and prompt structure
4. **Read** `analysis.py:1094-1145` to understand the LLM `detect_objects()` interface
5. **Implement** following scope — keep prompts simple and focused
6. **Run tests** with mocked LLM

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-05

Created `grid/detector.py` with `GridDetector`. `detect_cells()` dispatches all cells in
parallel via `asyncio.gather(*tasks, return_exceptions=True)` — failed cells are logged
and skipped without blocking other cells. `_detect_single_cell()` crops, downscales,
builds a focused per-cell prompt with `expected_products` as hints, filters reference images
to `reference_image_keys` (supports single image or list per product key), then calls
`self.llm.detect_objects()`. `_parse_detections()` correctly unpacks `[ymin, xmin, ymax, xmax]`
as `(x1=xmin, y1=ymin, x2=xmax, y2=ymax)` — note this is consistent with spec intent and
differs from the legacy path's pre-existing coordinate swap (see FIXME in `_detect_legacy`).
Results passed to `CellResultMerger.merge()` for offset correction and IoU deduplication.
Unit tests at `tests/pipelines/test_grid_detector.py` — all pass with mocked LLM.
