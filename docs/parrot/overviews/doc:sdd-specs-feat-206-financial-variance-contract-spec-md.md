---
type: Wiki Overview
title: 'Feature Specification: Align `financial_variance` template with the positional
  block validator'
id: doc:sdd-specs-feat-206-financial-variance-contract-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: when `len(blocks_raw) > len(specs)`, and coerces each slot with
relates_to:
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Align `financial_variance` template with the positional block validator

**Feature ID**: FEAT-206 *(FEAT-198 was already taken by `move-pageindex-kb`; reassigned 2026-05-29)*
**Date**: 2026-05-29
**Author**: Jesus
**Status**: approved
**Target version**: <x.y.z>

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement
`InfographicToolkit._validate_blocks()` is **strictly positional**: it iterates
`template.block_specs`, indexes `blocks_raw[idx]` one-to-one, raises `EXTRA_BLOCKS`
when `len(blocks_raw) > len(specs)`, and coerces each slot with
`InfographicResponse.model_validate({"blocks": [block_raw]}).blocks[0]` — i.e. it
keeps **exactly one** rendered block per spec.

`TEMPLATE_FINANCIAL_VARIANCE`, however, was authored against a different (implicit)
"grouped slot" model. It declares only **5** specs to represent a **9-block** layout:

| Pos | Spec (current) | Intended visual |
|---|---|---|
| 0 | `TITLE` | title + date range |
| 1 | `HERO_CARD` `min/max_items=4` | **4** KPI cards |
| 2 | `CHART` `min/max_items=2` | **2** half-width bar charts |
| 3 | `CHART` `min/max_items=1` | 1 full-width line chart |
| 4 | `SUMMARY` | exec summary |

This is internally contradictory under the positional validator:

1. **Cards are silently dropped.** A single `hero_card` block carrying
   `items=[4 cards]` is expanded by `InfographicResponse._normalise_payload` into 4
   blocks, but `_validate_blocks` keeps only `.blocks[0]` — 3 cards vanish from the
   rendered artifact.
2. **`min_items=2` on a CHART slot is a category error.** `_check_item_count`
   measures the first list-like key it finds, and for a chart that key is `series`.
   So `min_items=2` demands a chart with **2 data series**, not 2 side-by-side
   chart blocks — the opposite of the intent.
3. **The only "valid" 9-block input explodes.** Passing 4 flat `hero_card` blocks +
   2 chart blocks (the real layout) is 9 blocks vs 5 specs → `EXTRA_BLOCKS`.

Net effect: the `financial_variance` template cannot render the dashboard it
describes through the documented `infographic_render` path. Callers (e.g. the
`financial_projection_report` skill) only get a usable result by accident.

### Goals
- Make `financial_variance` render the full 9-block dashboard (1 title, 4 hero
  cards, 2 half-width bar charts, 1 full-width line chart, 1 summary) through the
  unmodified positional validator.
- Keep the fix surgical and behavior-preserving for every other template.
- Pin the positional contract returned by `infographic_get_template_contract`
  so LLM callers can build a deterministic, validatable block list.

### Non-Goals (explicitly out of scope)
- Refactoring `_validate_blocks` / `_check_item_count` to support "grouped" or
  "expandable" slots in general (would change semantics for all templates).
- Fixing the latent `.blocks[0]` truncation in the *other* item-bearing templates
  (`basic`, `executive`, `dashboard`) — tracked separately (see §8).
- Any change to the HTML renderer or the half-width grid CSS.

---

## 2. Architectural Design

### Overview
Flatten `TEMPLATE_FINANCIAL_VARIANCE.block_specs` from 5 grouped specs to **9
explicit positional specs**, one per rendered block. With a flat contract, the
existing positional validator is already correct: each slot maps to exactly one
block, `_normalise_payload` does not expand (flat hero cards carry `label`, not
`items`), and `.blocks[0]` is the right single block. No validator code changes.

### Component Diagram
```
infographic_get_template_contract ──→ TEMPLATE_FINANCIAL_VARIANCE (9 flat specs)
                                                │
infographic_validate_blocks ──→ _validate_blocks (positional, unchanged)
                                                │
infographic_render ──────────→ _validate_blocks → renderer (9 blocks)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `infographic_registry` (`InfographicTemplateRegistry`) | replaces builtin | Re-register the flattened `financial_variance` in `_register_builtins` |
| `InfographicToolkit._validate_blocks` | unchanged | Must keep passing; add regression test asserting `len(coerced) == 9` |
| `daily_financial_projection` skill (`agents/troc_finance/skills/daily_financial_projection/compute.py`) | downstream caller | Must emit **flat** hero_card blocks, not one block with `items=[...]` (see §7) |

### Data Models
No new models. The change is data-only within the existing `InfographicTemplate`
/ `BlockSpec` Pydantic models. Target shape:

```python
TEMPLATE_FINANCIAL_VARIANCE = InfographicTemplate(
    name="financial_variance",
    description=(
        "Financial projection variance dashboard: 4 KPI hero cards, 2 day-over-day "
        "bar charts side-by-side, 1 cumulative trend line chart full-width, and an "
        "executive summary."
    ),
    default_theme="light",
    block_specs=[
        BlockSpec(block_type=BlockType.TITLE,
                  description="Report title and the date range covered (e.g. 'May 14 – 27, 2026')"),
        BlockSpec(block_type=BlockType.HERO_CARD,
                  description="Card 1 — headline metric current value (e.g. total revenue)"),
        BlockSpec(block_type=BlockType.HERO_CARD,
                  description="Card 2 — period variance vs. baseline, with trend + trend_value"),
        BlockSpec(block_type=BlockType.HERO_CARD,
                  description="Card 3 — secondary metric current value (e.g. EBITDA)"),
        BlockSpec(block_type=BlockType.HERO_CARD,
                  description="Card 4 — day-over-day delta, with trend + trend_value"),
        BlockSpec(block_type=BlockType.CHART,
                  description="Bar chart — day-over-day change of the headline metric. MUST set layout='half'.",
                  constraints={"chart_type": "bar", "layout": "half"}),
        BlockSpec(block_type=BlockType.CHART,
                  description="Bar chart — day-over-day change of the secondary metric. MUST set layout='half'.",
                  constraints={"chart_type": "bar", "layout": "half"}),
        BlockSpec(block_type=BlockType.CHART,
                  description="Line chart — cumulative/daily total of the headline metric, full width. layout='full'.",
                  constraints={"chart_type": "line", "layout": "full"}),
        BlockSpec(block_type=BlockType.SUMMARY,
                  description="Executive summary (2–4 sentences) tying the 4 KPIs and the trend together."),
    ],
)
```

### New Public Interfaces
None. Public surface (`infographic_render`, `infographic_get_template_contract`,
`infographic_validate_blocks`, `infographic_list_templates`) is unchanged; only the
positional contract that `get_template_contract("financial_variance")` reports changes.

---

## 3. Module Breakdown

> These map to Phase-2 Task Artifacts.

### Module 1: Template redefinition
- **Path**: `packages/ai-parrot/src/parrot/models/infographic_templates.py`
- **Responsibility**: Replace the `TEMPLATE_FINANCIAL_VARIANCE` definition with the
  9-slot flat `block_specs` from §2. Leave `_register_builtins()` registration
  intact (it already lists `TEMPLATE_FINANCIAL_VARIANCE`).
- **Depends on**: existing `InfographicTemplate`, `BlockSpec`, `BlockType` (no changes).

### Module 2: Downstream skill asset alignment
- **Path**: `agents/troc_finance/skills/daily_financial_projection/compute.py`
  *(verified 2026-05-29 — the skill is present under this name, NOT
  `financial_projection_report`; that earlier name was a placeholder)*
- **Responsibility**: Emit the hero cards as **four separate** `{"type": "hero_card", ...}`
  blocks in `BLOCKS_JSON` instead of one `hero_card` block with an `items` list, so the
  payload matches the flattened positional contract (9 blocks).
  - **Current shape** (`compute.py:114-145`): `title` + **1** `hero_card` w/ `items=[4]`
    + 2 bar charts + 1 line chart + 1 summary = **6** emitted blocks. After
    `_normalise_payload` the hero_card expands to 4, but `_validate_blocks` keeps only
    `.blocks[0]` → 3 cards dropped.
  - **Target shape**: flatten that single `hero_card` into 4 flat
    `{"type": "hero_card", "label": ..., "value": ..., ...}` blocks → **9** blocks
    total, one per positional slot.
- **Depends on**: Module 1. *(This skill IS present in the repo — see Module 2 path —
  so this is in-scope work, not a follow-up. See also the doc asset
  `agents/troc_finance/skills/financial_projection_variance.md`.)*

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_financial_variance_contract_is_flat` | 1 | `infographic_get_template_contract("financial_variance")` returns 9 specs in order: `title, hero_card×4, chart, chart, chart, summary` |
| `test_financial_variance_chart_constraints` | 1 | Positions 5,6 carry `{chart_type:"bar", layout:"half"}`; position 7 carries `{chart_type:"line", layout:"full"}` |
| `test_validate_flat_payload_ok` | 1 | A flat 9-block payload returns `{"ok": True}` from `infographic_validate_blocks` |
| `test_validate_coerces_all_nine_blocks` | 1 | `_validate_blocks(...)` returns a list of length 9 (regression for the `.blocks[0]` drop) |
| `test_two_half_charts_preserve_layout` | 1 | Both coerced bar `ChartBlock`s keep `layout == "half"` |
| `test_legacy_items_payload_now_rejected` | 1 | Old shape (1 hero_card w/ `items=[4]` + 2 charts) fails validation (documents the intended breaking change) |

### Integration Tests
| Test | Description |
|---|---|
| `test_render_financial_variance_end_to_end` | `InfographicToolkit.render(template_name="financial_variance", ...)` with 9 blocks + non-empty `data_variables` returns an `InfographicRenderResult` whose HTML contains 4 hero cards and 3 chart containers |

### Test Data / Fixtures
```python
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

@pytest.fixture
def fv_data_locals():
    """REPL locals with non-empty frames for data_variables validation."""
    import pandas as pd
    return {"fp_daily": pd.DataFrame({"date": [1, 2], "rev_total": [2.3, 3.7]})}
```

---

## 5. Acceptance Criteria

> Complete when ALL of the following are true:

- [ ] `TEMPLATE_FINANCIAL_VARIANCE.block_specs` has 9 entries matching §2 exactly.
- [ ] All new unit tests pass (`pytest packages/ai-parrot/tests/ -k financial_variance -v`).
- [ ] Integration render test passes and the HTML contains 4 hero cards + 3 charts.
- [ ] `_validate_blocks` / `_check_item_count` source is **unchanged** (diff touches only the template file + tests + the downstream `compute.py`).
- [ ] Every other builtin template (`basic`, `executive`, `dashboard`, `comparison`, `timeline`, `minimal`, `multi_tab`) still validates and renders (no regressions).
- [ ] **Intended breaking change documented**: the legacy single-`hero_card`-with-`items` payload for `financial_variance` no longer validates; downstream `compute.py` updated (Module 2) or follow-up filed.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Line numbers are intentionally omitted;
> the implementing agent MUST confirm each symbol by `grep`/read before editing and
> record the resolved `path:line` in the Revision History.

### Verified Imports
```python
# All already present at the top of infographic_templates.py — reuse verbatim.
from .infographic import BlockType, JSBundle          # parrot/models/infographic.py
# In tests:
from parrot.models.infographic_templates import (
    InfographicTemplate, BlockSpec, infographic_registry,
)
from parrot.tools.infographic_toolkit import (
    InfographicToolkit, InfographicValidationError,
)
```

### Existing Symbols (confirm via grep anchors, not line numbers)
```python
# parrot/models/infographic_templates.py
#   grep anchor: "TEMPLATE_FINANCIAL_VARIANCE = InfographicTemplate("
#   grep anchor: "name=\"financial_variance\""
#   grep anchor: "def _register_builtins"      # TEMPLATE_FINANCIAL_VARIANCE is in its tuple
class BlockSpec(BaseModel):
    block_type: BlockType
    required: bool = True
    description: Optional[str] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    constraints: Optional[Dict[str, str]] = Field(default_factory=dict)  # NOTE: values are str→str

# parrot/models/infographic.py
#   grep anchor: "class BlockType(str, Enum)"   # has TITLE, HERO_CARD, CHART, SUMMARY
#   grep anchor: "class HeroCardBlock"           # fields: label, value, icon, trend, trend_value, comparison_period, color
#   grep anchor: "class ChartBlock"              # fields: chart_type, title, labels, series, layout('full'|'half'), x_axis_label, y_axis_label

# parrot/tools/infographic_toolkit.py  (DO NOT MODIFY — read only to confirm behavior)
#   grep anchor: "def _validate_blocks"          # positional loop over template.block_specs
#   grep anchor: ".model_validate({\"blocks\": [block_raw]}).blocks[0]"   # the per-slot single-block coercion
#   grep anchor: "def _check_item_count"          # keys: ("items","cards","rows","series","entries","tabs")
#   grep anchor: "EXTRA_BLOCKS"                   # raised when len(blocks_raw) > len(specs)
```

### Integration Points
| New/Changed | Connects To | Via | Verify At (grep anchor) |
|---|---|---|---|
| Flattened `block_specs` | `_register_builtins` tuple | already lists the symbol | `infographic_templates.py` → `def _register_builtins` |
| Flattened `block_specs` | `_validate_blocks` positional loop | 1 spec ↔ 1 block | `infographic_toolkit.py` → `for idx, spec in enumerate(specs)` |
| `constraints` dict | `BlockSpec.constraints` | must be `Dict[str,str]` | `infographic_templates.py` → `class BlockSpec` |

### Does NOT Exist (Anti-Hallucination)
- ~~A "group"/"repeat"/"count" field on `BlockSpec`~~ — slots are positional; multiplicity is expressed by repeating specs.
- ~~Constraint *enforcement* in `_validate_blocks`~~ — `constraints` are LLM hints only; the validator checks type + item count, **not** `chart_type`/`layout`. Do not add enforcement in this feature.
- ~~`BlockSpec(min_items=...)` meaning "N separate blocks"~~ — `_check_item_count` measures a list **inside one block** (`series` for charts, `items`/`cards` for hero cards).
- ~~A `subtitle` field on `HeroCardBlock`~~ — use `comparison_period` / `trend_value` for the secondary line.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Data-only edit to the template module; mirror the formatting/style of the
  sibling builtin templates already in the file.
- Keep `constraints` values as strings (`{"chart_type": "bar", "layout": "half"}`),
  matching `BlockSpec.constraints: Optional[Dict[str, str]]`.
- Tests under the existing `packages/ai-parrot/tests/` tree; async tests use the
  project's `pytest`/`anyio`/`asyncio` convention already in use for the toolkit.

### Known Risks / Gotchas
- **Breaking change (intended).** Any caller currently sending a single
  `hero_card` block with `items=[...]` for `financial_variance` will break.
  Mitigation: update Module 2 (`compute.py`) in the same change. The repo-wide
  caller audit (`grep -rln "financial_variance" agents/`) found exactly one code
  emitter — `agents/troc_finance/skills/daily_financial_projection/compute.py` —
  plus its doc asset `financial_projection_variance.md`. No other callers.
- **Latent twin bug.** `basic`/`executive`/`dashboard` keep the grouped
  `hero_card` + `min_items` convention and therefore retain the `.blocks[0]`
  truncation. Out of scope here; see §8.
- **Renderer assumption.** Two consecutive `layout="half"` chart blocks must be
  adjacent for the 2-column grid. The flat order (positions 5,6) guarantees this;
  do not insert a divider between them.

### External Dependencies
None.

---

## 8. Open Questions

- [ ] Should the grouped-slot bug be fixed centrally instead — i.e. change
  `_validate_blocks` to keep *all* expanded blocks for an item-bearing slot
  (replacing `.blocks[0]`) — and then leave `basic`/`executive`/`dashboard` as-is?
  That fixes the twin bug but changes validation semantics for every template.
  *Owner: Jesus* — this spec deliberately takes the low-risk per-template path; the
  central fix is a separate FEAT if desired.
- [x] ~~Confirm the suggested **FEAT-198** id is free on `dev`.~~ **Resolved 2026-05-29:**
  FEAT-198 was NOT free (owned by `move-pageindex-kb`). Reassigned to **FEAT-206**
  (next free id) and renamed the spec file accordingly. *Owner: Jesus*
- [x] ~~Is the `financial_projection_report` skill present in the target worktree, or
  does Module 2 become a follow-up task?~~ **Resolved 2026-05-29:** the skill IS
  present, but named `daily_financial_projection`
  (`agents/troc_finance/skills/daily_financial_projection/compute.py`), and it emits the
  legacy `hero_card`-with-`items` shape at `compute.py:117`. Module 2 is therefore
  **in-scope** (not a follow-up). *Owner: Jesus*

> **Note — unrelated template with a confusable name:** a separate, **unregistered**
> `InfographicTemplate(name="financial_projection_variance")` exists at
> `infographic_templates.py:545` (not in `_register_builtins`). This feature does NOT
> touch it; do not confuse it with `financial_variance`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-29 | Jesus | Initial draft — flatten `financial_variance` to 9 positional slots; validator unchanged |
| 0.2 | 2026-05-29 | Jesus | Codebase verification pass. Corrected Module 2 path to `agents/troc_finance/skills/daily_financial_projection/compute.py` (was placeholder `financial_projection_report`); resolved §8 skill-presence question (in-scope); flagged unregistered confusable template `financial_projection_variance`; fixed `BlockSpec.constraints` to `default_factory=dict`. All §6 contract anchors confirmed against source. |
