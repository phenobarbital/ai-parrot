# TASK-3419: Perception spike harness, evaluator, .gitignore negations and spike report

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3418
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (second half) — the *perception spike*. Generic
classical-CV shape detection is the feature's main technical risk: it is proven
only for price tags. The user decided (brainstorm round 5) that the first piece
of work is a time-boxed spike that **measures** the profile-driven proposer of
TASK-3418 on real ProductOnShelves photos, against a small manually annotated
sample, and records which profiles are accepted.

The spike's outcome gates one class default later in the feature:
`ProductOnShelves` stays on `perception_mode="llm_detector"` unless this report
records **passed** gates. *Insufficient photos, untested conditions or any failed
gate ⇒ `inconclusive`/`failed` ⇒ the LLM-detector default stays.*

The repository is **public**: real store photos and manual annotations are
git-ignored and may be entirely absent in the worktree where this task runs. The
harness must therefore work with **no private data at all** — it then produces a
report whose outcome is `inconclusive`, which is a valid, expected result.

---

## Scope

- `evaluate.py`: annotation models, one-to-one IoU matching (threshold 0.5,
  provisional), per-profile / per-photo precision and recall, off-fixture
  proposal counts, gate evaluation, outcome decision.
- `run_spike.py`: CLI (`--photos-dir`, `--annotations-dir`, `--out`,
  `--iou`, `--work-width`, `--membership-module`) that loads photos + annotations
  when present, always runs the built-in **synthetic cases**, calls
  `propose_shapes` with the candidate profiles, and writes the Markdown report.
  Candidate profiles for ProductOnShelves (product body, box, fact/price tag,
  backlit zone) are defined here as data — they are the spike's hypothesis.
- `README.md`: how to annotate, the annotation JSON format, how to run, privacy rules.
- `.gitignore`: negations so the harness code is tracked while anything else
  dropped into that folder stays ignored; plus the negations for the two example
  scripts later tasks add (`descriptor_assistant.py`, `backend_benchmark.py`).
  **This is the only task of the feature that edits `.gitignore`.**
- `docs/pipelines/planogram-perception-spike.md`: the committed report
  (aggregates only). Run the harness once in your worktree and commit what it
  produces — `inconclusive` when no private sample is available.
- Tests for the evaluator (loaded by file path — `examples/` is not a package).

**NOT in scope**: changing `propose_shapes` or `PRICE_TAG_PROFILE` (TASK-3418);
fixture-membership logic (another task — the harness only accepts an *optional*
dotted module name at the CLI and records the membership gate as `untested`
when none is given); flipping any class default; committing any photo,
annotation, crop or per-photo filename; touching `examples/planogram/plancheck/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/perception_spike/run_spike.py` | CREATE | CLI: load sample, synthetic cases, run proposer, write report |
| `examples/planogram/perception_spike/evaluate.py` | CREATE | Annotation models, IoU matching, metrics, gates, outcome |
| `examples/planogram/perception_spike/README.md` | CREATE | Annotation format, usage, privacy rules |
| `.gitignore` | MODIFY | Negations for the harness folder and the two future example scripts |
| `docs/pipelines/planogram-perception-spike.md` | CREATE | Committed aggregate report + accepted profiles + outcome |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_spike_evaluate.py` | CREATE | Offline tests of the evaluator |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
import cv2
import numpy as np
from pydantic import BaseModel, Field
import argparse, importlib, importlib.util, json, logging, sys
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple
```

### Existing Signatures to Use
```python
# Created by TASK-3418 (dependency) — packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/
from parrot_pipelines.planogram.perception import (
    PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile, propose_shapes)

class ShapeProfile(BaseModel):          # profiles.py
    name: str; kind: str
    min_width: float; max_width: float; min_height: float; max_height: float   # fractions of the image
    min_aspect: float; max_aspect: float                                       # w / h
    polarity: Literal["bright", "dark", "edge"]
    min_rectangularity: float = 0.75; min_contrast_std: float = 25.0
    thresholds: Tuple[int, ...] = (130, 150, 170, 190, 210, 230); dedup_overlap: float = 0.5
class ShapeCandidate(BaseModel):        # profiles.py
    profile: str; kind: str; x1: int; y1: int; x2: int; y2: int; score: float
def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *,
                   work_width: int = 2048) -> List[ShapeCandidate]: ...       # shapes.py — BGR ndarray in, source pixels out

# .gitignore — FEAT-565 block (verified 2026-09-18)
#   :20   examples/**/*.py                       (global rule — why every tracked example .py needs a negation)
#   :413  # FEAT-565: planogram compliance example — track code + small inputs only.
#   :416  examples/planogram/*
#   :423  !examples/planogram/white_label_detector/
#   :424  examples/planogram/white_label_detector/*
#   :425  !examples/planogram/white_label_detector/detect_price_labels.py      (last line of the block)
```

Reference photo (git-ignored, may be absent): `examples/planogram/photo_2026-09-18_20-36-30.jpg`,
1280×955 — Epson EcoTank endcap: luminous backlit header; 3 white printers on a
white riser (low contrast); 3 electronic price tags (white, red band); 3×2 box
stack; distractor fixtures on both aisles.

### Does NOT Exist
- ~~`examples/planogram/perception_spike/`~~ — new in this task.
- ~~`docs/pipelines/`~~ — directory does not exist yet; create it with the report.
- ~~any manual annotation file in the repo~~ — none exists and none may be committed.
- ~~labelled ground truth for the example photos~~ — none (README of FEAT-565: "No accuracy claim").
- ~~an importable `examples` package~~ — `examples/` has no `__init__.py`; tests load `evaluate.py` with `importlib.util.spec_from_file_location`.
- ~~a fixture-membership function available to this task~~ — not a dependency. The CLI only accepts an optional dotted module name and resolves it with `importlib.import_module` at run time; absent ⇒ the membership gate is `untested`.
- ~~profiles for products/boxes/backlits in the package~~ — only `PRICE_TAG_PROFILE` ships; candidate profiles live in `run_spike.py` as the spike's hypothesis.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/planogram/perception_spike/run_spike.py", "action": "CREATE"},
    {"path": "examples/planogram/perception_spike/evaluate.py", "action": "CREATE"},
    {"path": "examples/planogram/perception_spike/README.md", "action": "CREATE"},
    {"path": ".gitignore", "action": "MODIFY"},
    {"path": "docs/pipelines/planogram-perception-spike.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_spike_evaluate.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Annotation format (private, one JSON per photo, same stem as the photo)
```json
{
  "image": "photo.jpg",
  "image_size": [1280, 955],
  "conditions": ["full_view", "adjacent_fixture"],
  "objects": [
    {"id": "p1", "kind": "product", "box": [412, 380, 560, 520], "membership": "on_fixture", "slot_target": true},
    {"id": "t1", "kind": "price_tag", "box": [430, 528, 520, 560], "membership": "on_fixture", "slot_target": false},
    {"id": "d1", "kind": "product", "box": [20, 400, 140, 540], "membership": "off_fixture", "slot_target": false}
  ]
}
```
`conditions` vocabulary (the report lists which were exercised): `full_view`,
`partial_view`, `adjacent_fixture`, `absent_anchors`, `repeated_skus`,
`ambiguous_membership`.

### Gates (spec Module 1 — provisional engineering gates, not accuracy claims)
- per evaluable photo: product-slot **recall ≥ 0.90** and **precision ≥ 0.90**
  (`slot_target` objects only; tag-anchored proposals count only if the slot
  derived above the tag covers the intended product — in this task approximate
  with "a `product`/`box` proposal matches the `slot_target` box");
- **zero** off-fixture observations admitted into scoring — measurable only when
  `--membership-module` is given; otherwise `untested`;
- synthetic cases pass: partial shelf, absent anchors, adjacent distractor
  fixture (repeated SKUs are *not applicable* at proposal level — say so in the report).
- Outcome: `passed` only when every gate is `passed`; any `failed` ⇒ `failed`;
  anything `untested`, fewer than 3 evaluable photos, or a required condition
  never exercised ⇒ `inconclusive`.

### Key Constraints
- **Privacy**: the report contains counts and ratios per *anonymous* photo index
  (`photo 1`, `photo 2`), never a filename, path, store name, crop or pixel data.
- No `print` anywhere — repo rule: use `logging` (`logging.basicConfig(level=INFO)` in `main`).
- Blocking file I/O is fine here (a CLI, not an event loop). No `requests`/`httpx`.
- `evaluate.py` imports only stdlib + `pydantic` (no cv2, no parrot) so the test
  can load it by path without side effects. Register the module in `sys.modules`
  **before** `exec_module` — Pydantic resolves postponed annotations through it.
- Synthetic images are drawn with `cv2`/`numpy` inside `run_spike.py`; the
  synthetic annotations are generated from the same draw calls.
- Inside a worktree run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
- Time box: two engineering days (provisional). Do not tune profiles against the
  single reference photo beyond what the README documents — record failures instead.

### References in Codebase
- `examples/planogram/plancheck/detection.py:136-160` — image loading/downscale idea (reference only)
- `.gitignore:413-425` — the block to extend

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its path nearly
> verbatim, then complete every `# FILL IN:`. Never change a signature or path fixed here.

### Steps (in order)
1. Edit `.gitignore` first — *why*: `examples/**/*.py` (`.gitignore:20`) and
   `examples/planogram/*` (`:416`) ignore everything you are about to create;
   without the negations `git add` silently skips the harness.
2. Verify with `git check-ignore -v examples/planogram/perception_spike/evaluate.py`
   (must print nothing / exit 1) and `git check-ignore -v examples/planogram/perception_spike/ann.json`
   (must be ignored) — *why*: proves code is tracked and private data is not.
3. Write `evaluate.py`, then its test, and make the test pass — *why*: metrics
   must be trusted before any number is reported.
4. Write `run_spike.py` and `README.md`.
5. Run `python examples/planogram/perception_spike/run_spike.py --out docs/pipelines/planogram-perception-spike.md`
   (add `--photos-dir/--annotations-dir` only if the private sample exists on
   your machine) and commit the produced report — *why*: the report is a feature deliverable.

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -c '^!examples/planogram/white_label_detector/detect_price_labels.py$' .gitignore)
# AFTER — insert below `!examples/planogram/white_label_detector/detect_price_labels.py` (verified: .gitignore:425)
# FEAT-574: perception spike harness (code only — photos/annotations dropped here stay ignored)
!examples/planogram/perception_spike/
examples/planogram/perception_spike/*
!examples/planogram/perception_spike/*.py
!examples/planogram/perception_spike/README.md
# FEAT-574: example scripts added by later tasks of the same feature
!examples/planogram/descriptor_assistant.py
!examples/planogram/backend_benchmark.py
```
**Why**: same un-ignore / re-ignore / allow-list pattern the block already uses for
`white_label_detector/` (`:423-425`). The harness folder is flat, so `*.py` is
enough. The two script negations are added here so that no other task has to
touch `.gitignore` (single owner ⇒ no merge conflicts).

### `examples/planogram/perception_spike/evaluate.py` (CREATE)
```python
"""Spike evaluator: one-to-one IoU matching, per-profile metrics, gates (FEAT-574). Stdlib + pydantic only."""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

Box = Tuple[int, int, int, int]
GateState = Literal["passed", "failed", "untested"]
Outcome = Literal["passed", "failed", "inconclusive"]
MIN_EVALUABLE_PHOTOS = 3
REQUIRED_CONDITIONS = ("partial_view", "adjacent_fixture", "absent_anchors")


class AnnotatedObject(BaseModel):
    """One manually annotated object."""
    id: str
    kind: str
    box: Box
    membership: Literal["on_fixture", "off_fixture", "uncertain"] = "on_fixture"
    slot_target: bool = False


class PhotoAnnotation(BaseModel):
    """All annotations of one photo."""
    image: str
    image_size: Tuple[int, int]
    conditions: List[str] = Field(default_factory=list)
    objects: List[AnnotatedObject]


class Proposal(BaseModel):
    """Proposer output reduced to what the evaluator needs."""
    profile: str
    kind: str
    box: Box
    admitted: Optional[bool] = None  # None = membership not evaluated


class ProfileMetrics(BaseModel):
    """Precision/recall of one profile on one photo."""
    profile: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: Optional[float]   # None when there are no proposals
    recall: Optional[float]      # None when there is nothing to find


class PhotoResult(BaseModel):
    """Everything measured on one photo (anonymous index, never a filename)."""
    index: int
    conditions: List[str]
    per_profile: List[ProfileMetrics]
    slot_precision: Optional[float]
    slot_recall: Optional[float]
    off_fixture_proposals: int
    off_fixture_admitted: Optional[int]


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two [x1, y1, x2, y2] boxes; 0.0 for degenerate boxes."""
    # FILL IN — bounded by: symmetric, 1.0 for identical boxes, never divides by zero.
    raise NotImplementedError


def match_one_to_one(proposals: Sequence[Box], truths: Sequence[Box], threshold: float = 0.5
                     ) -> List[Tuple[int, int, float]]:
    """Greedy best-IoU-first one-to-one matching. Returns (proposal_idx, truth_idx, iou) triples."""
    # FILL IN — bounded by: each proposal and each truth used at most once; ties broken by
    #           lower proposal index then lower truth index (deterministic).
    raise NotImplementedError


def evaluate_photo(index: int, annotation: PhotoAnnotation, proposals: Sequence[Proposal],
                   kind_of_profile: Dict[str, str], threshold: float = 0.5) -> PhotoResult:
    """Per-profile metrics (truths = on_fixture objects of the profile's kind) + slot metrics."""
    # FILL IN — bounded by: off_fixture_proposals counts proposals matching an off_fixture object;
    #           off_fixture_admitted is None when every Proposal.admitted is None.
    raise NotImplementedError


def decide_outcome(photos: Sequence[PhotoResult], synthetic: Dict[str, bool], *,
                   min_precision: float = 0.90, min_recall: float = 0.90) -> Tuple[Outcome, Dict[str, GateState]]:
    """Apply the gates of the task's Implementation Notes and return (outcome, gate states)."""
    # FILL IN — bounded by: <3 evaluable photos, a REQUIRED_CONDITIONS entry never exercised on a
    #           real photo, or any "untested" gate => "inconclusive"; any failed gate => "failed".
    raise NotImplementedError
```
**Why this shape**: pure functions over small Pydantic models so every number in
the report is unit-testable without OpenCV or photos. `admitted` is tri-state
because membership is optional in this task — `None` must propagate to an
`untested` gate, never to a silent pass.

### `examples/planogram/perception_spike/run_spike.py` (CREATE)
```python
"""Perception spike CLI (FEAT-574): measure propose_shapes on a private sample + synthetic cases."""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile, propose_shapes

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate  # noqa: E402  (sibling module; examples/ is not a package)

logger = logging.getLogger("perception_spike")

CANDIDATE_PROFILES: List[ShapeProfile] = [
    PRICE_TAG_PROFILE,
    # FILL IN: hypothesis profiles "product_body" (polarity="edge"), "product_box" (polarity="edge"),
    #          "backlit_zone" (polarity="bright", very large), "electronic_tag" (polarity="bright") —
    #          bounded by: the reference-photo description in the Codebase Contract; values are the
    #          spike's HYPOTHESIS and must be listed verbatim in the report.
]


def synthetic_cases() -> Dict[str, Tuple[np.ndarray, "evaluate.PhotoAnnotation"]]:
    """Drawn images + generated annotations: full_wall, partial_shelf, absent_anchors, adjacent_fixture."""
    # FILL IN — bounded by: annotations come from the same draw calls (no hand-typed boxes).
    raise NotImplementedError


def load_sample(photos_dir: Optional[Path], annotations_dir: Optional[Path]
                ) -> List[Tuple[np.ndarray, "evaluate.PhotoAnnotation"]]:
    """Pairs (image, annotation) by file stem. Missing dirs or no pairs -> [] (never raises)."""
    # FILL IN — bounded by: log only COUNTS, never a filename.
    raise NotImplementedError


def resolve_membership(dotted: Optional[str]) -> Optional[Callable[..., Sequence[bool]]]:
    """importlib.import_module(dotted).admit when given; None otherwise or on ImportError (logged)."""
    # FILL IN — bounded by: absence is NOT an error; it makes the membership gate "untested".
    raise NotImplementedError


def render_report(photos: Sequence["evaluate.PhotoResult"], synthetic: Dict[str, bool],
                  outcome: str, gates: Dict[str, str], profiles: Sequence[ShapeProfile], args: argparse.Namespace) -> str:
    """Markdown with the fixed sections of docs/pipelines/planogram-perception-spike.md."""
    # FILL IN — bounded by: the section list in the report blueprint below; no filenames/paths of photos.
    raise NotImplementedError


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Exit code 0 for every outcome (the outcome is data, not an error)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos-dir", type=Path, default=None)
    parser.add_argument("--annotations-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--work-width", type=int, default=2048)
    parser.add_argument("--membership-module", type=str, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    # FILL IN: load_sample -> propose_shapes per photo -> evaluate.evaluate_photo -> synthetic_cases ->
    #          evaluate.decide_outcome -> render_report -> args.out.write_text (mkdir parents).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: the CLI must succeed with zero private data (worktrees have
none) and then report `inconclusive`; every loader therefore degrades to empty
instead of raising. Candidate profiles are data in this file — not in the
package — because they are unvalidated hypotheses until the gates pass.

### `docs/pipelines/planogram-perception-spike.md` (CREATE)
````markdown
# Planogram perception spike — FEAT-574

**Outcome**: inconclusive
**Date**: YYYY-MM-DD · **IoU threshold**: 0.5 · **Work width**: 2048 · **Evaluable photos**: 0

> Engineering gates on a small private sample — not population accuracy claims.
> Photos and annotations are private and git-ignored; this file holds aggregates only.

## Gates
| Gate | State | Detail |
|---|---|---|
| product-slot recall ≥ 0.90 on each evaluable photo | untested | — |
| product-slot precision ≥ 0.90 on each evaluable photo | untested | — |
| zero off-fixture observations admitted | untested | no membership module supplied |
| synthetic cases (partial shelf, absent anchors, adjacent fixture) | — | — |

## Conditions exercised
## Per-photo, per-profile precision / recall
## Off-fixture proposals and admissions
## Synthetic cases
## Candidate profiles evaluated
## Accepted profiles
```json
[]
```
## Failures and untested conditions
## Consequence
`ProductOnShelves` keeps `perception_mode="llm_detector"` unless **Outcome** is `passed`.
````
**Why**: this is the *shape* `render_report` must emit; the committed file is the
harness's real output. The first line after the title is parsed by a later task,
so `**Outcome**: <passed|failed|inconclusive>` and the `## Accepted profiles`
JSON block (a list of `ShapeProfile` dicts, `[]` unless passed) are fixed.

### `examples/planogram/perception_spike/README.md` (CREATE)
Sections (prose, no code to copy): *Purpose* · *Privacy rules* (nothing but
`*.py`/`README.md` in this folder is tracked; never commit photos, annotations,
crops or filenames) · *Annotation format* (the JSON above + the `conditions`
vocabulary) · *How to annotate* (enumerate target-fixture objects/anchors **and**
neighbouring distractors, boxes in source pixels) · *Run* (the command of Step 5,
with and without the private sample) · *Reading the report* (gates, outcome,
consequence).

### FILL IN checklist
- [ ] `evaluate.py::iou`, `match_one_to_one`, `evaluate_photo`, `decide_outcome`
- [ ] `run_spike.py::CANDIDATE_PROFILES` hypothesis values
- [ ] `run_spike.py::synthetic_cases`, `load_sample`, `resolve_membership`, `render_report`, `main` body
- [ ] `README.md` prose
- [ ] the committed report = real harness output
- [ ] `test_spike_evaluate.py` bodies

---

## Acceptance Criteria

- [ ] AC-1: `git check-ignore` reports the harness `*.py` and `README.md` as **not** ignored, and any other file in `examples/planogram/perception_spike/` (e.g. `ann.json`, `x.jpg`) as ignored; `examples/planogram/descriptor_assistant.py` and `examples/planogram/backend_benchmark.py` are not ignored.
- [ ] AC-2: one-to-one matching at IoU 0.5 yields the expected precision/recall on a hand-built case (2 truths, 3 proposals of which one duplicates an already matched truth ⇒ TP=2, FP=1, FN=0 ⇒ precision 2/3, recall 1.0).
- [ ] AC-3: `decide_outcome` returns `inconclusive` with no photos, with an `untested` membership gate, or when a required condition was never exercised; `failed` when any photo misses a gate; `passed` only when all gates pass.
- [ ] AC-4: `python examples/planogram/perception_spike/run_spike.py --out <tmp>` succeeds with no private data and writes a report whose second non-empty line is `**Outcome**: inconclusive`.
- [ ] AC-5: the committed `docs/pipelines/planogram-perception-spike.md` has the fixed sections, an `## Accepted profiles` JSON list, and contains no photo filename or path.
- [ ] AC-6: no photo, annotation or crop is added to git (`git status --porcelain` shows only the six declared files).
- [ ] AC-7: `examples/planogram/plancheck/` untouched.
- [ ] No linting errors: `ruff check examples/planogram/perception_spike/`
- [ ] All tests pass (see Validation Commands).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_spike_evaluate.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_spike_evaluate.py
"""Offline tests for the spike evaluator, loaded by path (examples/ is not a package)."""
import importlib.util
import sys
from pathlib import Path

import pytest

_EVALUATE = Path(__file__).resolve().parents[4] / "examples/planogram/perception_spike/evaluate.py"


@pytest.fixture(scope="module")
def ev():
    spec = importlib.util.spec_from_file_location("perception_spike_evaluate", _EVALUATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # pydantic resolves postponed annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def test_iou_identity_disjoint_and_degenerate(ev): ...
def test_spike_evaluator_one_to_one_matching(ev):
    """AC-2: a duplicate proposal over one truth is a false positive, not a second match."""
def test_matching_is_deterministic_on_ties(ev): ...
def test_evaluate_photo_counts_off_fixture_and_tristate_admission(ev): ...
def test_outcome_inconclusive_without_photos(ev):
    outcome, gates = ev.decide_outcome([], {"partial_shelf": True, "absent_anchors": True, "adjacent_fixture": True})
    assert outcome == "inconclusive"
def test_outcome_inconclusive_when_membership_untested(ev): ...
def test_outcome_failed_when_a_photo_misses_recall(ev): ...
def test_outcome_passed_only_when_every_gate_passes(ev): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 1, §7 "repository is public")
2. **Check dependencies** — TASK-3418 merged (the `perception` package imports)
3. **Verify the Codebase Contract** — re-check `.gitignore:413-425` and the
   `grep -c` occurrence count before editing; update the contract FIRST if it moved
4. **Implement** from the blueprint; complete every `# FILL IN:`
5. **Verify** all acceptance criteria, including the `git check-ignore` checks
6. **Commit code + report only** — never touch `sdd/`; never commit private data
7. **Fill in the Completion Note** in your final report (state the outcome and
   which conditions were exercised)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
