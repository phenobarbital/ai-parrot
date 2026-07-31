---
type: Wiki Overview
title: 'TASK-1455: Refactor STRUCTURED_CHART onto the deterministic base'
id: doc:sdd-tasks-completed-task-1455-chart-deterministic-refactor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2**. `STRUCTURED_CHART` (FEAT-215) currently takes the
  LLM-owns-data path that
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats.structured_base
  rel: mentions
---

# TASK-1455: Refactor STRUCTURED_CHART onto the deterministic base

**Feature**: FEAT-223 — Structured Artifact Contract
**Spec**: `sdd/specs/structured-artifact-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1454
**Assigned-to**: unassigned

---

## Context

Implements **Module 2**. `STRUCTURED_CHART` (FEAT-215) currently takes the LLM-owns-data path that
FEAT-218 explicitly rejected: the LLM emits rows, and the renderer reactively heals them with
`_resolve_rows` + `_reconcile_columns`. This produced the production failures the spec documents
(invented columns, `data: [{}]`, orientation flips, "No data"). Rebuild the renderer on the
`StructuredOutputBase` from TASK-1454: **rows come deterministically from the agent's DataFrame**; the
LLM contributes **presentation only** (`type`, `x`, `y[]` chosen from the real column set, plus
palette / colorBySign).

---

## Scope

- Refactor `StructuredChartRenderer` to obtain rows via `StructuredOutputBase._extract_rows`
  (i.e. `TableRenderer._extract_data`), NOT from `cfg.data` nor a tool variable.
- Constrain the LLM to **presentation**: keep `type`, `x`, `y`, `palette`, `color_by_sign`, etc.;
  treat `StructuredChartConfig.data` as **input-only / ignored as a row source**.
- Validate `x` / `y` against the REAL extracted column set. If the LLM picks an absent column, apply a
  **deterministic fallback**: first categorical column → `x`, numeric column(s) → `y`.
- **Remove the reactive patches**: `_resolve_rows` (`structured_chart.py:226`) and
  `_reconcile_columns` (`:256`). Keep only a thin safety guard (e.g. empty-data → graceful "no data").
- Use the shared `_route_envelope` for output (data excluded, rows → `response.data`, explanation
  wrapped). Drop the duplicated `_extract_json_code` copy in favor of the base helper.
- Update `STRUCTURED_CHART_SYSTEM_PROMPT` so the LLM is told it picks presentation from a provided
  real-column list and must NOT emit rows.

**NOT in scope**: chart-config convergence onto ChartBlock / Artifact.definition (TASK-1456); map work
(TASK-1457); writing the cross-renderer parity test (TASK-1458 — but keep existing chart tests green
or update them to reflect deterministic rows).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` | MODIFY | Rebuild on `StructuredOutputBase`; remove reactive patches; deterministic x/y fallback; update system prompt |
| `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` | MODIFY | Update reconciliation-era tests to assert deterministic rows + x/y ∈ real columns |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFY each anchor before coding. TASK-1454 must be in `tasks/completed/` first.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredChartConfig  # outputs.py:37 / :309
# Within ai-parrot-visualizations:
from parrot.outputs.formats.structured_base import StructuredOutputBase  # CREATED by TASK-1454 — verify name
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py
@register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=STRUCTURED_CHART_SYSTEM_PROMPT)  # :75
class StructuredChartRenderer(BaseChart):                 # :76
    async def render(self, response, *, environment="html", **kwargs): ...   # :90 (lines 90-221)
    @staticmethod
    def _resolve_rows(cfg: StructuredChartConfig, existing): ...   # :226  ← REMOVE
    def _reconcile_columns(self, out, cfg, rows): ...              # :256  ← REMOVE
    # out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})  # :180 (data already excluded)

# packages/ai-parrot/src/parrot/models/outputs.py
class StructuredChartConfig(BaseModel):                   # :309
    type: ChartType            # bar|horizontalBar|line|area|scatter|pie|donut|radar|map
    x: str                     # categorical column NAME
    y: List[str]               # value column NAMES
    palette: Optional[List[str]]
    color_by_sign: Optional[bool]   # alias colorBySign
    data: List[dict]                # INPUT-ONLY — already excluded from output; do NOT use as row source
    data_variable: Optional[str]    # alias dataVariable
    # _normalize_data_orientation (:398) and _validate_chart_constraints (:443) — keep; the latter
    # deliberately does NOT validate x/y presence (renderer enforces against real columns now)

# packages/ai-parrot/src/parrot/outputs/formats/table.py
class TableRenderer(BaseRenderer):
    def _extract_data(self, response) -> pd.DataFrame: ...   # :57
```

### Does NOT Exist
- ~~A second LLM "refine" pass on the chart renderer~~ — unlike table/map, chart has none today; do not invent one.
- ~~`StructuredChartConfig` validation of x/y against real columns~~ — that enforcement lives in the renderer.

---

## Implementation Notes

### Pattern to Follow
Mirror `StructuredTableRenderer`'s deterministic flow: `_extract_rows(response)` → derive the real column
set → let the LLM-chosen `x`/`y` pass only if present, else fall back deterministically → `_route_envelope`.

### Known Risks / Gotchas
- After rows become deterministic, verify pie / bar / horizontalBar / radar / line still render with BOTH
  positive AND negative values (the spec calls this out explicitly).
- The LLM still picks x/y — feed it the real column list via the system prompt / extracted schema.

### Key Constraints
- Async; `self.logger` on fallback + degradation paths. Never raise — graceful "no data" fallback.
- No real client data in fixtures/prompts (use `cat`/`val` placeholders).

---

## Acceptance Criteria

- [ ] Chart rows come from `response.data` (the agent DataFrame), never from `cfg.data` / the LLM.
- [ ] Emitted config's `x`/`y` always reference real columns; absent LLM choice → deterministic fallback (first categorical = x, numeric = y).
- [ ] `_resolve_rows` and `_reconcile_columns` removed; only a thin guard remains.
- [ ] Renderer uses the shared `_route_envelope`; output excludes `data`.
- [ ] "No data" / column-mismatch failures cannot occur for valid data.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_chart.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/formats/test_structured_chart.py
class TestDeterministicChart:
    async def test_rows_from_dataframe_not_llm(self):
        """Given a DataFrame in response.data + LLM presentation, rows come from the DataFrame."""
        ...

    async def test_xy_always_real_columns(self):
        """x/y in the emitted config are always members of the real column set."""
        ...

    async def test_absent_xy_falls_back_deterministically(self):
        """LLM picks an absent x/y → first categorical = x, numeric = y."""
        ...

    async def test_negative_values_render(self):
        """bar/line/pie/radar render with negative values after determinism."""
        ...

    async def test_never_raises_on_garbage(self):
        """Unusable input degrades gracefully (None, message), never raises."""
        ...
```

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-03
**Notes**: Rebuilt `StructuredChartRenderer(StructuredOutputBase, BaseChart)`. Rows come exclusively from `_extract_rows(response)` → `canonical_records`. Removed `_resolve_rows`, `_reconcile_columns`, `_extract_json_code` (latter inherited). Added `_safe_x`/`_safe_y` for deterministic column fallback preserving index-like column filtering. Uses `_route_envelope` via `cfg.model_copy(update={"x":x,"y":y,"data":rows})`. Updated system prompt to say LLM must NOT emit rows. 9 reconciliation-era tests updated; 5 new deterministic tests added. 37/37 chart tests + 48/48 table tests pass. Linting clean.
**Deviations from spec**: none
