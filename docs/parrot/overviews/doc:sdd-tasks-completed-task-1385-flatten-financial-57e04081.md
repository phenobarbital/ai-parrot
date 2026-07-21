---
type: Wiki Overview
title: 'TASK-1385: Flatten `financial_variance` template to 9 positional slots (+
  tests)'
id: doc:sdd-tasks-completed-task-1385-flatten-financial-variance-template-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: one rendered block, and it keeps only `.blocks[0]` per slot. The current
relates_to:
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1385: Flatten `financial_variance` template to 9 positional slots (+ tests)

**Feature**: FEAT-206 — Align `financial_variance` template with the positional block validator
**Spec**: `sdd/specs/FEAT-206-financial-variance-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`InfographicToolkit._validate_blocks()` is strictly positional: one `BlockSpec` ↔
one rendered block, and it keeps only `.blocks[0]` per slot. The current
`TEMPLATE_FINANCIAL_VARIANCE` declares 5 *grouped* specs (a `HERO_CARD` with
`min/max_items=4`, a `CHART` with `min/max_items=2`) to describe a 9-block layout.
Under the positional validator this silently drops 3 hero cards and misreads
`min_items` on charts as a series count. This task flattens the template to 9
explicit positional specs so the existing validator is already correct — no
validator code changes. Implements spec §2 (Module 1) and §4 (Test Specification).

---

## Scope

- Replace `TEMPLATE_FINANCIAL_VARIANCE.block_specs` (currently 5 grouped specs) with
  the **9 flat positional specs** from spec §2: `TITLE`, `HERO_CARD`×4, `CHART`(bar/half),
  `CHART`(bar/half), `CHART`(line/full), `SUMMARY`.
- Each hero-card spec describes exactly **one** card (no `min_items`/`max_items`).
- The two bar-chart specs carry `constraints={"chart_type": "bar", "layout": "half"}`;
  the line-chart spec carries `constraints={"chart_type": "line", "layout": "full"}`.
- Update the template `description` to match spec §2 (keep concise).
- Leave `_register_builtins()` untouched — it already lists `TEMPLATE_FINANCIAL_VARIANCE`.
- Add the unit + integration tests from spec §4 (see Test Specification below).

**NOT in scope**:
- ANY edit to `infographic_toolkit.py` (`_validate_blocks` / `_check_item_count`) —
  they must remain byte-for-byte unchanged.
- ANY edit to `infographic.py` block models or the HTML renderer.
- The downstream `compute.py` payload — that is TASK-1386.
- Fixing the `.blocks[0]` truncation in `basic`/`executive`/`dashboard` (spec §8, out of scope).
- Adding constraint *enforcement* — `constraints` are LLM hints only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic_templates.py` | MODIFY | Replace `TEMPLATE_FINANCIAL_VARIANCE.block_specs` with 9 flat specs |
| `packages/ai-parrot/tests/tools/test_infographic_financial_variance.py` | CREATE | Unit tests (contract, constraints, flat-payload validation, 9-block coercion, layout preservation, legacy-rejection) |
| `packages/ai-parrot/tests/integration/test_infographic_e2e.py` | MODIFY | Add `test_render_financial_variance_end_to_end` (4 hero cards + 3 charts in HTML) |

---

## Codebase Contract (Anti-Hallucination)

> All anchors verified 2026-05-29 against the working tree. Confirm line numbers
> with `grep` before editing — they may have shifted.

### Verified Imports
```python
# Top of infographic_templates.py — reuse verbatim (already present):
from .infographic import BlockType, JSBundle      # parrot/models/infographic.py

# In the new test module:
from parrot.models.infographic_templates import (
    InfographicTemplate, BlockSpec, infographic_registry,
)
from parrot.tools.infographic_toolkit import (
    InfographicToolkit, InfographicValidationError,
)
```

### Existing Signatures to Use
```python
# parrot/models/infographic_templates.py:21
class BlockSpec(BaseModel):
    block_type: BlockType                                  # line 27
    required: bool = True                                  # line 28
    description: Optional[str] = None                      # line 29
    min_items: Optional[int] = None                        # line 33
    max_items: Optional[int] = None                        # line 37
    constraints: Optional[Dict[str, str]] = Field(default_factory=dict)  # line 41 — values are str→str

# parrot/models/infographic_templates.py:374
TEMPLATE_FINANCIAL_VARIANCE = InfographicTemplate(  # currently 5 grouped specs — REPLACE block_specs
    name="financial_variance", ...
)
# parrot/models/infographic_templates.py:473
def _register_builtins(self) -> None:   # tuple at lines 475-484 ALREADY lists TEMPLATE_FINANCIAL_VARIANCE (line 483)

# parrot/models/infographic.py:71
class BlockType(str, Enum):   # TITLE="title", HERO_CARD="hero_card", SUMMARY="summary", CHART="chart" (+others)

# parrot/models/infographic.py:223
class HeroCardBlock(BaseModel):
    type: Literal["hero_card"] = "hero_card"
    label: str = ""           # line 226
    value: str = ""           # line 230
    icon / trend / trend_value / comparison_period / color   # all Optional

# parrot/models/infographic.py:404
class ChartBlock(BaseModel):
    type: Literal["chart"] = "chart"
    chart_type: ChartType                       # required enum: "bar","line",... (line 407)
    labels: List[str]                           # required (line 410)
    series: List[ChartDataSeries]               # required (line 414)
    layout: Optional[Literal["full", "half"]] = None   # line 422

# parrot/models/infographic.py:757  (read-only — explains current bug)
@model_validator(mode="before")
def _normalise_payload(cls, values):   # expands hero_card with "items" → N cards,
                                       # GUARDED by `"label" not in block` (line 790):
                                       # flat hero_cards carrying `label` are NOT expanded.

# parrot/tools/infographic_toolkit.py  (READ ONLY — DO NOT MODIFY)
def _validate_blocks(self, template, blocks_raw):   # line 437; positional loop line 451
    if len(blocks_raw) > len(specs): raise ...("EXTRA_BLOCKS", ...)   # line 444
    block_model = InfographicResponse.model_validate({"blocks":[block_raw]}).blocks[0]  # line 476
def _check_item_count(self, idx, spec, block_raw):  # line 481
    for key in ("items","cards","rows","series","entries","tabs"): ...   # line 490 (first list-like key wins)
async def get_template_contract(self, template_name):  # line 284; returns {"block_specs":[{position,block_type,...,constraints}]}
```

### Does NOT Exist
- ~~A `group`/`repeat`/`count` field on `BlockSpec`~~ — multiplicity = repeated specs.
- ~~Constraint *enforcement* in `_validate_blocks`~~ — `constraints` are LLM hints only; validator checks type + item-count, NOT `chart_type`/`layout`.
- ~~`BlockSpec(min_items=N)` meaning "N separate blocks"~~ — it measures a list *inside one block*.
- ~~A `subtitle` field on `HeroCardBlock`~~ — use `comparison_period` / `trend_value`.

---

## Implementation Notes

### Pattern to Follow
Mirror the formatting/style of sibling builtin templates already in
`infographic_templates.py` (e.g. `TEMPLATE_MULTI_TAB` at line 430). Data-only edit;
keep `constraints` values as strings.

### Key Constraints
- The two `layout="half"` bar specs MUST be adjacent (positions 5,6) for the 2-column grid.
- Do NOT touch the toolkit — acceptance criterion requires its diff to be empty.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/infographic_templates.py:374` — symbol to replace
- `packages/ai-parrot/tests/integration/test_infographic_e2e.py:244` — existing `test_e2e_financial_variance_template_registered` (style reference for the new e2e test)

---

## Acceptance Criteria

- [ ] `TEMPLATE_FINANCIAL_VARIANCE.block_specs` has 9 entries matching spec §2 exactly.
- [ ] `_validate_blocks` / `_check_item_count` source is unchanged (no diff in `infographic_toolkit.py`).
- [ ] All new unit tests pass: `pytest packages/ai-parrot/tests/ -k financial_variance -v`
- [ ] Integration render test passes; HTML contains 4 hero cards + 3 chart containers.
- [ ] Every other builtin template (`basic`, `executive`, `dashboard`, `comparison`, `timeline`, `minimal`, `multi_tab`) still validates/renders (no regressions).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/infographic_templates.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_infographic_financial_variance.py
import pytest
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicValidationError
from parrot.models.infographic_templates import infographic_registry


@pytest.fixture
def fv_blocks():
    """Minimal valid 9-block financial_variance payload."""
    bar = lambda t: {"type": "chart", "chart_type": "bar", "layout": "half",
                     "title": t, "labels": ["D1", "D2"],
                     "series": [{"name": "x", "values": [1.0, 2.0]}]}
    card = lambda l, v: {"type": "hero_card", "label": l, "value": v}
    return [
        {"type": "title", "title": "T", "date": "May 14 – 27, 2026"},
        card("Revenue", "$3.7M"), card("Change", "$1.4M"),
        card("EBITDA", "$31K"), card("DoD", "$107K"),
        bar("Revenue DoD"), bar("EBITDA DoD"),
        {"type": "chart", "chart_type": "line", "layout": "full", "title": "Cumulative",
         "labels": ["D1", "D2"], "series": [{"name": "rev", "values": [2.3, 3.7]}]},
        {"type": "summary", "content": "Summary text."},
    ]


def test_financial_variance_contract_is_flat():
    """get_template_contract returns 9 specs: title, hero_card×4, chart×3, summary."""
    tk = InfographicToolkit()
    contract = await_or_sync(tk.get_template_contract, "financial_variance")
    types = [s["block_type"] for s in contract["block_specs"]]
    assert types == ["title", "hero_card", "hero_card", "hero_card", "hero_card",
                     "chart", "chart", "chart", "summary"]


def test_financial_variance_chart_constraints():
    """Positions 5,6 are bar/half; position 7 is line/full."""
    tpl = infographic_registry.get("financial_variance")
    specs = tpl.block_specs
    assert specs[5].constraints == {"chart_type": "bar", "layout": "half"}
    assert specs[6].constraints == {"chart_type": "bar", "layout": "half"}
    assert specs[7].constraints == {"chart_type": "line", "layout": "full"}


def test_validate_coerces_all_nine_blocks(fv_blocks):
    """_validate_blocks returns a list of length 9 (regression for .blocks[0] drop)."""
    tk = InfographicToolkit()
    tpl = infographic_registry.get("financial_variance")
    coerced = tk._validate_blocks(tpl, fv_blocks)
    assert len(coerced) == 9


def test_two_half_charts_preserve_layout(fv_blocks):
    """Both coerced bar ChartBlocks keep layout == 'half'."""
    tk = InfographicToolkit()
    tpl = infographic_registry.get("financial_variance")
    coerced = tk._validate_blocks(tpl, fv_blocks)
    assert coerced[5].layout == "half" and coerced[6].layout == "half"


def test_legacy_items_payload_now_rejected():
    """Old shape (1 hero_card w/ items=[4] + 2 charts) no longer validates."""
    tk = InfographicToolkit()
    tpl = infographic_registry.get("financial_variance")
    legacy = [
        {"type": "title", "title": "T"},
        {"type": "hero_card", "items": [{"label": f"c{i}", "value": "1"} for i in range(4)]},
        {"type": "chart", "chart_type": "bar", "labels": ["a"], "series": [{"name": "s", "values": [1]}]},
        {"type": "chart", "chart_type": "line", "labels": ["a"], "series": [{"name": "s", "values": [1]}]},
    ]
    with pytest.raises(InfographicValidationError):
        tk._validate_blocks(tpl, legacy)
```

> NOTE for the implementing agent: confirm whether `get_template_contract` /
> `infographic_validate_blocks` are async (they are defined `async def`) and adapt the
> test harness to the project's existing pytest/anyio/asyncio convention used in the
> sibling toolkit tests (`await_or_sync` above is a placeholder — replace with the real
> async test pattern). Also add `test_validate_flat_payload_ok` (validate_blocks returns
> `{"ok": True}`) per spec §4.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (esp. §2, §4, §6).
2. **Verify the Codebase Contract** — grep each anchor before editing.
3. **Update status** in the per-spec index → `"in-progress"`.
4. **Implement** the data-only template edit + tests.
5. **Verify** all acceptance criteria, including the unchanged-toolkit diff.
6. **Move this file** to `sdd/tasks/completed/` and update the index → `"done"`.
7. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-29
**Notes**:
- Replaced 5-grouped-spec `block_specs` with 9 flat positional specs exactly as specified in §2.
- All 7 unit tests pass: contract shape, chart constraints, 9-block coercion, layout preservation, legacy rejection, validate_blocks ok, get_template_contract.
- Integration render test passes: 1MB HTML produced with all 4 hero cards and 3 charts present.
- `infographic_toolkit.py` not touched (diff is empty for that file).
- `InfographicToolkit(artifact_store=...)` requires a store argument; unit tests use a MagicMock fixture.
- E2E test uses `fake_store.save_artifact.call_args` to extract rendered HTML since `html_inline` is None for large (>50KB) payloads.

**Deviations from spec**: none
