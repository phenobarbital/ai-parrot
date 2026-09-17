# TASK-3348: Report writer — compliance.json, annotated images, crops, run snapshot

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3338
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11 (report)** and §2 "Artefacts in `--output`". This is stage 8's
output half: it turns an already-computed `ComplianceReport` into files on disk. It
owns the *never overwrite* guarantee (`--output` must not exist) that spec §5 turns
into an acceptance criterion, and the annotated overlay a human uses to audit the
automatic registration.

It computes nothing: statuses, credits and metrics arrive ready-made from
`plancheck/scoring.py` (TASK-3347) through the pipeline (TASK-3349).

---

## Scope

- Implement `STATUS_COLORS`: one BGR tuple per `PositionStatus` literal (all ten,
  including `not_assessed`) plus the extra key `"unregistered"`.
- Implement `annotate(image, observations, positions)`: cv2-only overlay, returns a
  **copy** (never mutates the input).
- Implement `write_report(report, images, settings, prompt_versions)`:
  creates `settings.output` (raises `FileExistsError` if it exists), writes
  `compliance.json`, `annotated_<image_id>.jpg`, `slots/<slot_id>.png`,
  `tags/<tag_id>.png`, `run.snapshot.json`; returns the `compliance.json` path.
- All three are **synchronous** — the pipeline (TASK-3349) wraps `write_report`
  in `asyncio.to_thread`.
- Write `examples/planogram/tests/test_plancheck_report.py`.

**NOT in scope**: computing any status/metric (TASK-3347); orchestration and the
early "output exists" pre-check (TASK-3349); CLI exit-code mapping (TASK-3350);
the models themselves (TASK-3337 / TASK-3338); any LLM/OCR call.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/report.py` | CREATE | `STATUS_COLORS`, `annotate`, `write_report` |
| `examples/planogram/tests/test_plancheck_report.py` | CREATE | Unit tests for the three public names |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: use these exact imports and signatures. Do not invent anything not listed.

### Verified Imports
```python
import hashlib                      # stdlib
import json                         # stdlib
import logging                      # stdlib
from pathlib import Path            # stdlib
from typing import Any, get_args    # stdlib

import cv2                          # installed: opencv-python 4.10.0.84
import numpy as np                  # installed: numpy 2.4.6
import pytest                       # tests only
```

### Existing Signatures to Use
```python
# examples/planogram/white_label_detector/detect_price_labels.py  (adopted into git by TASK-3336;
# REFERENCE for the drawing idiom only — never import it, it is a script, not a package)
#   :159  cv2.rectangle(overlay,(x1,y1),(x2,y2),color,max(2,round(ow/800)))
#   :160-161  cv2.putText(overlay,f"{row_number}:{position}",(x1,max(18,y1-5)),
#                         cv2.FONT_HERSHEY_SIMPLEX,ow/3000,color,max(1,round(ow/1000)))
#   :178-179  if not cv2.imwrite(str(output/"annotated.jpg"),overlay): raise IOError("Cannot write annotation")
# → line thickness and font scale are proportional to the ORIGINAL image width; imwrite's
#   boolean result must be checked.
```

#### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py — part 1 by TASK-3337, part 2 by TASK-3338
Box = tuple[int, int, int, int]                       # x1, y1, x2, y2 — ORIGINAL image pixels
PositionStatus = Literal["match", "misplaced", "variant_unresolved", "mismatch", "empty",
                         "inferred_present", "occupied_unassigned", "conflict", "not_assessed", "not_visible"]
class Slot(StrictModel):            # slot_id, image_id, row, index, box: Box, tag_id: str | None, tag_box: Box | None, origin
class PriceReading(StrictModel):    # raw, amount: Decimal | None, currency, source, status
class SlotObservation(StrictModel): # slot: Slot, reading, resolved_sku, candidate_skus, resolution, price, facing_id: str | None, registration_grade, issues
class PlanogramFacing(StrictModel): # facing_id, position, shelf, segment, slot, segment_slot, facing, sku, brand, ...
class PositionResult(StrictModel):  # facing: PlanogramFacing, status: PositionStatus, resolution, strict_credit, lenient_credit, observed_sku, ..., slot_ids: list[str]
class ImageInfo(StrictModel):       # image_id, path, sha256, width, height, tag_rows, tags, slots, registration
class RunInfo(StrictModel):         # visit_id, planogram_id, llm, ocr_llm, verify_pass, started_at, finished_at, errors, catalog_missing_skus, ...
class ComplianceReport(StrictModel):# run, images: list[ImageInfo], slots: list[SlotObservation], positions, shelves, brands, compliance, notes
class Settings(StrictModel):        # images: list[str], planogram: str, catalog: str, output: str, prices: str | None, llm, ocr_llm, base_url, roi, verify_pass, marks, concurrency, cache_dir: str, visit_id, work_width, weights
```
Inside the package import them relatively: `from .models import …`. In tests:
`from plancheck.models import …` (conftest from TASK-3337 puts `examples/planogram/` on `sys.path`).

Shared fixtures (TASK-3337, `examples/planogram/tests/conftest.py` — use, never redefine):
`shelf_image`, `mini_planogram`, `mini_catalog`.

### Does NOT Exist
- ~~`matplotlib` / `seaborn` / `PIL.ImageDraw` drawing~~ — banned or unnecessary; **cv2 only**.
- ~~`from detect_price_labels import …`~~ / ~~`import inkcheck`~~ — not packages; never import.
- ~~`print(...)`~~ — use `logger = logging.getLogger(__name__)`.
- ~~`Settings.output_dir`~~ / ~~`Settings.out`~~ — the field is `Settings.output` (a `str`).
- ~~`SlotObservation.image_id`~~ — the image id lives at `observation.slot.image_id`.
- ~~`PositionResult.facing_id`~~ — it is `position.facing.facing_id`.
- ~~`ComplianceReport.model_dump_json(indent=…)` as the *only* path~~ — allowed, but the spec fixes
  the semantics as `model_dump(mode="json")` (Decimals → strings); either spelling must round-trip
  through `ComplianceReport.model_validate_json`.
- ~~an async `write_report`~~ — it is synchronous by decision; TASK-3349 calls it via `asyncio.to_thread`.
- ~~overwriting / `exist_ok=True`~~ — an existing output directory is an error, always.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/report.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_report.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:examples/planogram/white_label_detector/detect_price_labels.py#detect"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure I/O module: imports `cv2`, `numpy`, stdlib and `.models` only — **never `parrot`**, never a network library.
- Coordinates in every model are ORIGINAL-image pixels — draw and crop with them directly; clip to the image.
- `cv2.imwrite` returns `False` on failure instead of raising → check it and raise `OSError`.
- Create the output directory **first** with `mkdir(parents=True, exist_ok=False)`; nothing may be
  written before that call succeeds (spec §5: "`--output` that already exists … writes nothing").
- Hash input files with sha256 in binary mode; a missing optional file (`settings.prices is None`) → `None`.
- black line length 120; Google-style docstrings; strict type hints.
- Nothing in the test file may copy real SKUs or layout from `planogram_page1.json` (public repo) —
  use the synthetic fixtures only.

### Decided details (do not re-decide)
- Overlay colour = `STATUS_COLORS[status]` of the `PositionResult` whose `facing.facing_id` equals the
  observation's `facing_id`; observations with `facing_id is None` use `STATUS_COLORS["unregistered"]`.
- Slot label text: `"<shelf>:<slot> <status>"` for registered slots, `"unregistered"` otherwise, drawn
  just above the slot box; the tag box gets a 1-step thinner outline in the same colour.
- Crops: `slots/<slot_id>.png` for every observation; `tags/<tag_id>.png` only when `slot.tag_box` and
  `slot.tag_id` are set (gap-filled / untagged-row slots have neither).
- `run.snapshot.json` keys: `settings`, `prompt_versions`, `llm`, `ocr_llm`, `inputs`
  (`{"images": {<image_id>: sha256}, "planogram": sha256, "catalog": sha256, "prices": sha256 | null}`).

### References in Codebase
- `examples/planogram/white_label_detector/detect_price_labels.py:158-161,177-179` — drawing + imwrite idiom.

---

## Implementation Blueprint

> Write each block to its path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path fixed here (they come from spec §3 Module 11).

### Steps (in order)
1. Create `report.py` with the imports, logger and `STATUS_COLORS` — *why*: the colour table is pure data and the test for it needs nothing else.
2. Implement `_sha256_file` and `_clip` helpers — *why*: both `annotate` and `write_report` need clipped boxes, and the snapshot needs file hashes; keeping them private avoids widening the public surface fixed by the spec.
3. Implement `annotate` on a **copy** of the image — *why*: the pipeline reuses the decoded array for crops after annotating; mutating it would burn the overlay into the crops.
4. Implement `write_report`, calling `mkdir(exist_ok=False)` before any write — *why*: spec §5 requires that an existing `--output` writes nothing.
5. Write the tests, building one tiny `ComplianceReport` by hand from the models — *why*: this module must be testable without scoring/pipeline (they are sibling tasks that may not have landed).
6. Run the validation command and `ruff check` on both files — *why*: ruff (TID251) is the merge gate.

### `examples/planogram/plancheck/report.py` (CREATE) — part 1/2
```python
"""Report artefacts for the planogram compliance check (FEAT-565, spec §3 Module 11).

Synchronous, cv2-only. The pipeline calls :func:`write_report` through ``asyncio.to_thread``.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .models import Box, ComplianceReport, PositionResult, Settings, SlotObservation

logger = logging.getLogger(__name__)

# BGR. One entry per PositionStatus literal + "unregistered" (slot with no planogram facing).
STATUS_COLORS: dict[str, tuple[int, int, int]] = {
    "match": (0, 170, 0),
    "misplaced": (0, 200, 255),
    "variant_unresolved": (0, 140, 255),
    "mismatch": (0, 0, 220),
    "empty": (200, 0, 200),
    "inferred_present": (220, 160, 0),
    "occupied_unassigned": (160, 160, 0),
    "conflict": (0, 0, 120),
    "not_assessed": (128, 128, 128),
    "not_visible": (80, 80, 80),
    "unregistered": (200, 200, 200),
}


def _sha256_file(path: Path) -> str:
    """Return the hex sha256 of a file read in binary mode."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clip(box: Box, width: int, height: int) -> Box | None:
    """Clip ``box`` to the image; return ``None`` when nothing is left."""
    x1, y1, x2, y2 = box
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    return (x1, y1, x2, y2) if x1 < x2 and y1 < y2 else None


def annotate(image: np.ndarray, observations: list[SlotObservation], positions: list[PositionResult]) -> np.ndarray:
    """Draw slot/tag boxes coloured by position status on a COPY of ``image``.

    Args:
        image: BGR image in original resolution.
        observations: Observations of THIS image only (caller filters by ``slot.image_id``).
        positions: All position results (looked up by ``facing.facing_id``).

    Returns:
        A new annotated BGR array with the same shape as ``image``.
    """
    overlay = image.copy()
    height, width = overlay.shape[:2]
    thickness = max(2, round(width / 800))  # idiom verified: detect_price_labels.py:159
    font_scale = width / 3000  # idiom verified: detect_price_labels.py:161
    by_facing = {p.facing.facing_id: p for p in positions}
    for obs in observations:
        position = by_facing.get(obs.facing_id) if obs.facing_id else None
        status = position.status if position else "unregistered"
        color = STATUS_COLORS[status]
        # FILL IN: draw the clipped slot box (thickness), the clipped tag box when present
        #   (thickness - 1, min 1) and the label text above the slot box with cv2.putText —
        #   bounded by "Decided details" (label "<shelf>:<slot> <status>" | "unregistered";
        #   skip any box that _clip() returns None for; y of the text = max(18, y1 - 5)).
        raise NotImplementedError
    return overlay
```
**Why this shape**: `STATUS_COLORS` is complete because `test_status_colors_cover_all_statuses`
compares its keys against `get_args(PositionStatus)` + `"unregistered"` — adding a status later
without a colour must fail loudly. `annotate` copies first so the pipeline can still crop clean
pixels. Thickness/scale follow the verified detector idiom so overlays stay legible on 4032-px photos.

### `examples/planogram/plancheck/report.py` (CREATE) — part 2/2
```python
def _write_image(path: Path, image: np.ndarray) -> None:
    """``cv2.imwrite`` with its boolean result checked (it does not raise on failure)."""
    if not cv2.imwrite(str(path), image):
        raise OSError(f"Cannot write image: {path}")


def _snapshot(report: ComplianceReport, settings: Settings, prompt_versions: dict[str, str]) -> dict[str, Any]:
    """Build the ``run.snapshot.json`` payload (settings, models, prompt versions, input hashes)."""
    # FILL IN: return the dict fixed in "Decided details": keys settings
    #   (settings.model_dump(mode="json")), prompt_versions, llm / ocr_llm (from report.run),
    #   inputs = {"images": {info.image_id: info.sha256 for info in report.images},
    #             "planogram": _sha256_file(...), "catalog": _sha256_file(...),
    #             "prices": _sha256_file(...) if settings.prices else None}.
    raise NotImplementedError


def write_report(
    report: ComplianceReport,
    images: dict[str, np.ndarray],
    settings: Settings,
    prompt_versions: dict[str, str],
) -> Path:
    """Write every artefact of one run into a NEW directory.

    Args:
        report: The finished report.
        images: ``image_id`` → decoded BGR image (original resolution).
        settings: Run settings; ``settings.output`` is the directory to create.
        prompt_versions: Stage name → prompt version string, recorded in the snapshot.

    Returns:
        Path of the written ``compliance.json``.

    Raises:
        FileExistsError: ``settings.output`` already exists (nothing is written).
        OSError: An image could not be encoded/written.
    """
    output = Path(settings.output)
    output.mkdir(parents=True, exist_ok=False)  # FileExistsError BEFORE any write — spec §5
    (output / "slots").mkdir()
    (output / "tags").mkdir()
    compliance_path = output / "compliance.json"
    compliance_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
    for image_id, image in images.items():
        own = [obs for obs in report.slots if obs.slot.image_id == image_id]
        _write_image(output / f"annotated_{image_id}.jpg", annotate(image, own, report.positions))
        # FILL IN: for every observation in ``own`` write slots/<slot_id>.png from the clipped
        #   slot.box, and tags/<tag_id>.png from the clipped slot.tag_box when BOTH tag_box and
        #   tag_id are set — bounded by "Decided details" + _clip() (skip None, log at debug).
        raise NotImplementedError
    (output / "run.snapshot.json").write_text(
        json.dumps(_snapshot(report, settings, prompt_versions), indent=2), encoding="utf-8"
    )
    logger.info("Report written to %s", output)
    return compliance_path
```
**Why this shape**: `mkdir(exist_ok=False)` is the single guard that makes "existing output writes
nothing" true — do not replace it with an `exists()` check followed by `mkdir(exist_ok=True)` (race +
weaker guarantee). `model_dump(mode="json")` is fixed by spec §2 (Decimals become strings and the file
round-trips through `ComplianceReport.model_validate_json`). Crops come from the ORIGINAL image, never
from the annotated copy.

### `examples/planogram/tests/test_plancheck_report.py` (CREATE)
```python
"""Unit tests for plancheck.report (FEAT-565, TASK-3348)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import numpy as np
import pytest

from plancheck.models import (
    BrandShare,
    ComplianceReport,
    ComplianceSummary,
    ImageInfo,
    PositionResult,
    PositionStatus,
    RunInfo,
    Settings,
    ShelfScore,
    Slot,
    SlotObservation,
)
from plancheck.report import STATUS_COLORS, annotate, write_report


def _mini_report(mini_planogram, tmp_path: Path) -> tuple[ComplianceReport, Settings]:
    """One image, two observations (one registered + matched, one unregistered), hand-built."""
    # FILL IN: build Slot/SlotObservation/PositionResult/ShelfScore/BrandShare/ComplianceSummary/
    #   ImageInfo/RunInfo from the models; write tiny planogram.json / catalog.json files into
    #   tmp_path so _sha256_file has real inputs; Settings(output=str(tmp_path / "out"),
    #   cache_dir=str(tmp_path / "cache"), images=[...], planogram=..., catalog=...).
    #   Bounded by the model field lists in the Codebase Contract; slot boxes must lie inside
    #   the 1600x1200 shelf_image; the first slot has tag_id + tag_box, the second has neither.
    raise NotImplementedError


def test_status_colors_cover_all_statuses() -> None:
    assert set(STATUS_COLORS) == set(get_args(PositionStatus)) | {"unregistered"}
    assert all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in STATUS_COLORS.values())


def test_annotate_returns_copy_same_shape(shelf_image, mini_planogram, tmp_path) -> None:
    # FILL IN: annotate(...) → result.shape == shelf_image.shape, result is not shelf_image,
    #   shelf_image unchanged (compare with a .copy() taken before), result differs from input.
    raise NotImplementedError


def test_write_report_refuses_existing_dir(shelf_image, mini_planogram, tmp_path) -> None:
    # FILL IN: pre-create settings.output with one sentinel file → pytest.raises(FileExistsError);
    #   afterwards the directory contains ONLY the sentinel (nothing was written).
    raise NotImplementedError


def test_write_report_artifacts(shelf_image, mini_planogram, tmp_path) -> None:
    # FILL IN: returned path == <out>/compliance.json; annotated_<image_id>.jpg exists;
    #   slots/ has one png per observation; tags/ has exactly the observations with a tag_box;
    #   run.snapshot.json has keys settings/prompt_versions/llm/ocr_llm/inputs and
    #   inputs["prices"] is None when settings.prices is None.
    raise NotImplementedError


def test_compliance_json_roundtrip(shelf_image, mini_planogram, tmp_path) -> None:
    # FILL IN: ComplianceReport.model_validate_json(path.read_text()) == original report
    #   (include one PriceReading with a Decimal amount so the Decimal → str → Decimal path is exercised).
    raise NotImplementedError
```
**Why this shape**: the report is built by hand from models so this task does not wait for scoring or
the pipeline. `test_write_report_refuses_existing_dir` is the spec §4 test for M11; the other four pin
the artefact list of spec §2 and the JSON round-trip the acceptance criteria rely on.

### FILL IN checklist
- [ ] `report.py::annotate` — box/tag/label drawing; bounded by "Decided details" and `_clip`
- [ ] `report.py::_snapshot` — payload keys fixed in "Decided details"
- [ ] `report.py::write_report` — slot + tag crops; bounded by "Decided details"
- [ ] `test_plancheck_report.py::_mini_report` — hand-built report within the model field lists
- [ ] `test_plancheck_report.py` — four test bodies, each bounded by its comment

---

## Acceptance Criteria

- [ ] `STATUS_COLORS` has exactly the ten `PositionStatus` keys + `"unregistered"`.
- [ ] `annotate` returns a new array; the input image is byte-identical afterwards.
- [ ] `write_report` on an existing directory raises `FileExistsError` and writes nothing.
- [ ] `write_report` produces `compliance.json`, `annotated_<image_id>.jpg`, `slots/`, `tags/`, `run.snapshot.json`.
- [ ] `compliance.json` round-trips through `ComplianceReport.model_validate_json`.
- [ ] No `print(`, no `matplotlib`/`seaborn`, no `parrot` import in `report.py`.
- [ ] `ruff check examples/planogram/plancheck/report.py examples/planogram/tests/test_plancheck_report.py` is clean.
- [ ] All tests pass: `pytest examples/planogram/tests/test_plancheck_report.py -q`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_report.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint — function names are fixed:
`test_status_colors_cover_all_statuses`, `test_annotate_returns_copy_same_shape`,
`test_write_report_refuses_existing_dir` (spec §4, M11), `test_write_report_artifacts`,
`test_compliance_json_roundtrip`. No network, no real photos, synthetic SKUs only.

---

## Agent Instructions

1. **Read the spec** (§2 artefacts, §3 Module 11, §5) for context.
2. **Check dependencies** — TASK-3338 (and, transitively, TASK-3337) must be in `sdd/tasks/completed/`;
   confirm `examples/planogram/plancheck/models.py` exports every name listed above.
3. **Verify the Codebase Contract** before writing code; if a model field differs, update the contract first.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
6. **Verify** all acceptance criteria and run the validation command.
7. **Move this file** to `sdd/tasks/completed/TASK-3348-report.md` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
