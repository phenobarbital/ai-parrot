# TASK-3641: Planogram vocabulary + closed-set identification prompt

**Feature**: FEAT-592 — Amazon Nova 2 Lite slot identification for planogram images
**Spec**: `sdd/specs/nova-image-planogram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3639
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3.

The shared pipeline prompt builder is contractually **open-set**: its docstring
states it "Must NOT mention a planogram or expected products"
(`identify.py:125`). FEAT-592 resolved to use a **closed-set** prompt seeded from
the planogram's own SKUs and brands, so that variant must live example-locally —
the pipeline's contract stays untouched (spec §1 Non-Goals, §8 resolved).

There is also no way to inject a builder into the pipeline: `_run_call` calls
`build_identify_prompt` by module-level name (`identify.py:331`). That is why
TASK-3642 owns its own strip loop and consumes this module's builder directly.

---

## Scope

- Implement `PlanogramVocabulary`, `load_planogram_vocabulary()` and
  `build_nova_identify_prompt()`.
- Declare `NOVA_PROMPT_VERSION` and `NOVA_STAGE` as distinct constants.
- Write unit tests for the vocabulary loader — pure, no AWS.

**NOT in scope**: modifying `build_identify_prompt` or anything under
`packages/` (spec G3 / AC6); reading planogram descriptor fields —
`product` + `brand` ONLY (resolved decision); the strip loop (TASK-3642).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/aws/prompt.py` | CREATE | Vocabulary loader + closed-set prompt builder |
| `examples/planogram/tests/test_nova2_prompt.py` | CREATE | Unit tests for the vocabulary loader |

---

## Codebase Contract (Anti-Hallucination)

> **CORRECTION-1 (applied post-merge by the orchestrator):**
> Same defect as TASK-3640 (commit 1928b9af2): the blueprint's
> `test_nova2_prompt.py` import
> (`from examples.planogram.aws.prompt import ...`) never resolves because a
> third-party `examples` distribution installed in the shared `.venv`
> shadows the repo-local `examples/` namespace directory regardless of
> `sys.path` order. `examples/planogram/tests/conftest.py` already inserts
> `examples/planogram/aws/` onto `sys.path` (fixed in 1928b9af2); this task's
> test was switched to the matching bare sibling import
> (`from prompt import ...`).

### Verified Imports
```python
from pydantic import BaseModel   # v2, repo standard
# json / pathlib / typing from the stdlib. No parrot import is required by this module.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py
IDENTIFY_PROMPT_VERSION: str = "identify-v1"   # line 33  ← must NOT be reused
IDENTIFY_STAGE: str = "identify"               # line 34  ← must NOT be reused
def build_identify_prompt(targets: Sequence[Dict[str, Any]],   # line 119
                          vocabulary: Sequence[str]) -> str: ...
#   docstring line 125: "Must NOT mention a planogram or expected products."
#   Its AREAS contract, which this module MUST keep verbatim:
#     each area = {"id", "mark", "box_2d", "ocr_text"}
#     box_2d = [ymin, xmin, ymax, xmax] normalised 0-1000 relative to the image sent
#     rules: report only from inside each box; exactly one entry per area in
#            existing_identifications with shape_id == area id; confirm/correct
#            ocr_text; report occupancy/product/brand/raw_confidence/evidence;
#            "use null when not legible - do not guess"; a product no area covers
#            goes ONLY under added_shapes with box_norm [ymin,xmin,ymax,xmax] 0-1000

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class Identification(BaseModel):               # line 101 — the per-area answer shape
    shape_id: str; product: Optional[str]; brand: Optional[str]; text: Optional[str]
    occupancy: str = "unknown"                 # line 110 — "occupied"|"empty"|"unknown"
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)   # line 111
    evidence: List[str]                        # line 112
class AddedShape(BaseModel):                   # line 117
    box_norm: List[int]                        # line 120 — [ymin,xmin,ymax,xmax] 0-1000

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
def cache_key(backend, max_tokens, stage, prompt_version, prompt, schema, images) -> str: ...  # line 63
#   the cache key mixes BOTH stage and prompt_version — this is why new constants matter
```

```json
// examples/planogram/planogram_page1.json — VERIFIED structure
{
  "planogram": {...},
  "shelves": [
    {
      "shelf": "...", "shelf_number": 1, "product_count": 0, "facing_count": 0,
      "products": {
        "pos 1:1": {
          "position": 1, "segment": "left", "segment_number": 1, "slot": 1,
          "segment_slot": 1, "product": "9C228AN", "brand": "HP", "shelf": 1,
          "facings": 1, "confidence": "high", "read_method": "direct",
          "notes": "HP 31 color ink-bottle multipack.",
          "display_name": null, "family": null, "xl": null, "colors": null,
          "pack": null, "identifiers": null, "aliases": null, "price": null
        }
      }
    }
  ]
}
```

### Does NOT Exist
- ~~`parrot_pipelines...identify.build_closed_set_prompt`~~ — no closed-set builder exists anywhere.
- ~~a prompt-builder hook on `identify_strips` / `_run_call`~~ — `build_identify_prompt` is called by module-level name at `identify.py:331`. There is NO injection point; do not try to add one.
- ~~`examples/planogram/aws/prompt.py`~~ — created by this task.
- ~~a top-level `products` key in the planogram JSON~~ — products live under `shelves[].products{}`, keyed `"pos <row>:<slot>"`.
- ~~descriptor fields as vocabulary~~ — `display_name`, `family`, `xl`, `colors`, `pack`, `identifiers`, `aliases` exist in the JSON but are deliberately NOT read (resolved decision: keeps prompts short).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/aws/prompt.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_nova2_prompt.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#build_identify_prompt",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Identification"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Both functions are **pure and synchronous** — no I/O beyond reading the
  planogram file in the loader, no network, no AWS.
- `NOVA_PROMPT_VERSION` / `NOVA_STAGE` MUST differ from `"identify-v1"` /
  `"identify"`: `cache_key` (`vision.py:63`) mixes both, so reusing them could
  serve a cached open-set answer for a closed-set prompt.
- Keep the AREAS contract byte-for-byte compatible with `build_identify_prompt`
  so `IdentificationResponse` still validates and `validate_response` still
  reconciles ids.
- The closed set is a **hint, not a cage**: tell the model it may answer outside
  the list when the package clearly shows something else — otherwise a product
  genuinely absent from the planogram gets mislabelled as a listed SKU.
- Sorted, de-duplicated output so prompts are deterministic (AC14 depends on a
  stable prompt for cache hits).

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:119-157` —
  the open-set builder whose AREAS contract and rule list this mirrors.
- `examples/planogram/README.md` — documents the planogram descriptor fields
  (and why this task ignores them).

---

## Implementation Blueprint

### Steps (in order)
1. Declare `NOVA_PROMPT_VERSION` and `NOVA_STAGE` first — *why*: they key the response cache alongside the prompt text, and reusing the pipeline's values would cross-contaminate open-set and closed-set answers.
2. Implement `PlanogramVocabulary` and `load_planogram_vocabulary` — *why*: TASK-3642 and TASK-3643 both import them, so their shape is fixed by this task.
3. Implement `build_nova_identify_prompt`, copying the rule list from `build_identify_prompt` and adding only the candidate lists — *why*: any drift in the AREAS contract breaks `validate_response`'s id reconciliation downstream.
4. Write the loader tests — *why*: the `product`+`brand`-only decision is easy to widen by accident and a test pins it.

### `examples/planogram/aws/prompt.py` (CREATE)
```python
"""Closed-set identification prompt for Nova (FEAT-592).

Deliberately example-local: the shared ``build_identify_prompt`` must NOT mention a
planogram or expected products (verified: identify.py:125).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pydantic import BaseModel

#: Distinct from IDENTIFY_PROMPT_VERSION / IDENTIFY_STAGE (verified: identify.py:33-34)
#: so cache entries can never collide — cache_key mixes both (verified: vision.py:63).
NOVA_PROMPT_VERSION: str = "nova-closed-set-v1"
NOVA_STAGE: str = "identify-nova"


class PlanogramVocabulary(BaseModel):
    """Closed-set candidates: ``product`` and ``brand`` ONLY (resolved decision)."""

    products: List[str]
    brands: List[str]


def load_planogram_vocabulary(path: Path) -> PlanogramVocabulary:
    """Distinct product/brand values from ``shelves[].products{}`` of a planogram JSON.

    Returns:
        Sorted, de-duplicated products and brands; empty lists are legal.

    Raises:
        ValueError: the file is not a planogram JSON (no ``shelves`` list).
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload.get("shelves"), list):
        raise ValueError(f"{path}: not a planogram JSON - no 'shelves' list")
    # FILL IN: walk shelves[].products{}.values(), collect non-empty "product" and
    #   "brand" strings into two sets, return them sorted — bounded by: read ONLY
    #   those two keys; descriptor fields are excluded by decision
    raise NotImplementedError


def build_nova_identify_prompt(
    areas: Sequence[Dict[str, Any]],
    vocabulary: PlanogramVocabulary,
    schema_instruction: str,
) -> str:
    """Closed-set counterpart of build_identify_prompt (verified: identify.py:119).

    Keeps that function's AREAS contract verbatim and differs in exactly one way: it
    offers the planogram's products and brands as expected candidates.

    Returns:
        The prompt text.
    """
    areas_json = json.dumps(list(areas), separators=(",", ":"), ensure_ascii=False)
    # FILL IN: compose the prompt — bounded by these NON-NEGOTIABLE rules, copied
    #   from identify.py:137-156 so IdentificationResponse still validates:
    #     - each area has id, mark, box_2d ([ymin,xmin,ymax,xmax] 0-1000 relative to
    #       the image received) and ocr_text
    #     - report on each listed area ONLY from what is visible inside its own box
    #     - exactly one entry per area in existing_identifications, shape_id == area id
    #     - confirm or correct ocr_text in the text field
    #     - report occupancy ('occupied'|'empty'|'unknown'), product, brand,
    #       raw_confidence 0..1 and a one-sentence evidence
    #     - "use null when not legible - do not guess"
    #     - a product no area covers goes ONLY under added_shapes with box_norm
    #   PLUS the closed-set addition: offer vocabulary.products / vocabulary.brands as
    #   the expected candidates AND state the model may answer outside the list when
    #   the package clearly shows something else
    #   PLUS schema_instruction appended last
    raise NotImplementedError
```
**Why this shape**: the AREAS contract and the per-area rule list are reproduced
from `build_identify_prompt` (`identify.py:137-156`) because `validate_response`
downstream reconciles on `shape_id` and accepts extras only under `added_shapes` —
drift there silently drops identifications. The only intended difference is the
candidate lists. `NOVA_PROMPT_VERSION`/`NOVA_STAGE` are separate constants, not
imports of the pipeline's, so a cached open-set answer can never be served here.
`schema_instruction` arrives as a plain string parameter, which is why this module
does **not** import `nova_vision` and can be built in parallel with TASK-3640.

### `examples/planogram/tests/test_nova2_prompt.py` (CREATE)
```python
"""Unit tests for the closed-set vocabulary loader (FEAT-592, TASK-3641).

Pure-function tests: no AWS, no network, no planogram data committed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from examples.planogram.aws.prompt import (
    NOVA_PROMPT_VERSION,
    NOVA_STAGE,
    PlanogramVocabulary,
    load_planogram_vocabulary,
)


@pytest.fixture
def planogram(tmp_path: Path) -> Path:
    """A minimal two-shelf planogram with a duplicate brand and a duplicate SKU."""
    payload = {
        "planogram": {"name": "synthetic"},
        "shelves": [
            {"shelf_number": 1, "products": {
                "pos 1:1": {"product": "9C228AN", "brand": "HP", "display_name": "HP 31"},
                "pos 1:2": {"product": "T502XL", "brand": "Epson", "family": "502"},
            }},
            {"shelf_number": 2, "products": {
                "pos 2:1": {"product": "9C228AN", "brand": "HP", "aliases": ["HP 31 tri"]},
                "pos 2:2": {"product": "PG-245", "brand": "Canon", "colors": ["black"]},
            }},
        ],
    }
    path = tmp_path / "planogram.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_vocabulary_reads_product_and_brand_only(planogram: Path) -> None:
    """Products and brands are collected; descriptor fields are ignored."""
    vocab = load_planogram_vocabulary(planogram)
    assert vocab.products == ["9C228AN", "PG-245", "T502XL"]
    assert vocab.brands == ["Canon", "Epson", "HP"]
    # FILL IN: assert no descriptor value (e.g. "HP 31", "502", "black") leaked into
    #   either list — bounded by the resolved product+brand-only decision


def test_vocabulary_deduplicates_and_sorts(planogram: Path) -> None:
    """A SKU repeated across shelves appears once, and output order is stable."""
    # FILL IN: assert len(set(vocab.products)) == len(vocab.products) and both lists
    #   equal their sorted() form — bounded by AC14 (a stable prompt enables cache hits)
    raise NotImplementedError


def test_vocabulary_rejects_non_planogram_json(tmp_path: Path) -> None:
    """A JSON file without a 'shelves' list is rejected, not silently empty."""
    path = tmp_path / "not_a_planogram.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(ValueError, match="shelves"):
        load_planogram_vocabulary(path)


def test_vocabulary_allows_empty_shelves(tmp_path: Path) -> None:
    """An empty but well-formed planogram yields empty lists, not an error."""
    # FILL IN: {"shelves": []} -> PlanogramVocabulary(products=[], brands=[])
    #   — bounded by the docstring's "empty lists are legal"
    raise NotImplementedError


def test_prompt_versions_differ_from_pipeline() -> None:
    """The cache key constants must not collide with the shared open-set prompt."""
    assert NOVA_PROMPT_VERSION != "identify-v1"
    assert NOVA_STAGE != "identify"
```
**Why**: the first test is the one that pins the resolved `product`+`brand`-only
decision — the fixture deliberately carries `display_name`, `family`, `colors` and
`aliases` so a widened loader fails loudly. The last test guards the cache-collision
risk recorded in spec §7. The fixture builds its own synthetic planogram under
`tmp_path`, so no retailer data is needed or committed.

### FILL IN checklist
- [ ] `prompt.py::load_planogram_vocabulary` — the shelves/products walk; bounded by: read only `product` and `brand`
- [ ] `prompt.py::build_nova_identify_prompt` — the prompt text; bounded by the verbatim AREAS rule list from `identify.py:137-156` plus the candidate lists
- [ ] `test_nova2_prompt.py::test_vocabulary_reads_product_and_brand_only` — the descriptor-leak assertion; bounded by the resolved decision
- [ ] `test_nova2_prompt.py::test_vocabulary_deduplicates_and_sorts` — body; bounded by AC14
- [ ] `test_nova2_prompt.py::test_vocabulary_allows_empty_shelves` — body; bounded by the loader docstring

---

## Acceptance Criteria

- [ ] `load_planogram_vocabulary` returns sorted, de-duplicated `products` and `brands`.
- [ ] Only the `product` and `brand` keys are read; no descriptor field reaches the vocabulary.
- [ ] A JSON file with no `shelves` list raises `ValueError` naming `shelves` — spec AC10.
- [ ] A well-formed planogram with no products yields empty lists without raising.
- [ ] `build_nova_identify_prompt` emits the AREAS JSON with `id`, `mark`, `box_2d`, `ocr_text` per area, and states the one-entry-per-area rule.
- [ ] The prompt offers the planogram candidates AND permits an answer outside the list.
- [ ] `NOVA_PROMPT_VERSION != "identify-v1"` and `NOVA_STAGE != "identify"`.
- [ ] `prompt.py` imports nothing from `nova_vision.py` (the schema instruction is a parameter).
- [ ] No file under `packages/` is modified — spec AC6.
- [ ] `ruff check` and `black --check --line-length 120` pass on the new files — spec AC12.

---

## Validation Commands

- `pytest examples/planogram/tests/test_nova2_prompt.py -q`

---

## Test Specification

See the `test_nova2_prompt.py` blueprint block above — five cases over the pure
loader plus the cache-constant guard, with a synthetic planogram fixture under
`tmp_path`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 3, §7 cache-collision risk).
2. **Check dependencies** — TASK-3639 must be in `sdd/tasks/completed/`: without its `.gitignore` negation block, `git add` of your new files under `examples/planogram/aws/` silently does nothing.
3. **Verify the Codebase Contract** — re-read `identify.py:119-157` and copy its rule
   list faithfully; re-confirm the planogram JSON shape before writing the loader.
4. **Update status** in `sdd/tasks/index/nova-image-planogram.json` → `"in-progress"`.
5. **Implement** — start from the blueprint blocks, complete every `# FILL IN:`, and
   never change a signature, class name or file path the blueprint fixes.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-3641-planogram-vocabulary-closed-set-prompt.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3641
- Feature: nova-image-planogram
- Implementation SHA: 59af55b6dba4d1e50f92f6ccdc14e2896895c6bc
- Closed at (UTC): 2026-09-22T23:59:42+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| deviation | Blueprint's from examples.planogram.aws.prompt import ... test import never resolves (shadowed by a third-party examples distribution in .venv, same defect as TASK-3640). Fixed post-merge in fix(nova-image-planogram): TASK-3641 review fixes commit 59af55b6d using a bare sibling import (repo-level defect, not attributable to the delivering model). |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 1 · Duration: 134.72s · Tokens: n/a |
| test_command | pytest examples/planogram/tests/test_nova2_prompt.py -v |
| test_result | 5 passed (after fix commit 59af55b6d correcting a blueprint import defect) |
| tests_passed | True |
