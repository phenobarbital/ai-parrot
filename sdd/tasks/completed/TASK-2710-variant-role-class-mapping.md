# TASK-2710: Honour parrot_variant / parrot_role / unit / trend + KPI grid + (theme, layout) resolution

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2709
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (second half), and the core finding of §1: **the semantic
layer already exists end to end, and the renderers throw it away.** The
catalog's `lower()` methods already emit 8 `parrot_variant` values and 27
`parrot_role` values, plus `parrot_unit` and `parrot_trend` on KPICard. Both
Card renderers drop the variant entirely, so a `KPICard` — which tags itself
`parrot_variant: "kpi"` on purpose — arrives as a generic bordered box with
three loose `<p>` elements.

This task closes that gap and adds the `(theme, layout)` resolution
precedence. **No `lower()` method is modified**: the 8 lowering golden
fixtures in `packages/ai-parrot/tests/outputs/a2ui/golden/` must stay
byte-identical.

---

## Scope

- Add `DesignSystem.resolve(envelope, *, theme_default, layout_default)
  -> tuple[str, str]` implementing the precedence: envelope
  `metadata.extensions["parrot_theme"]`/`["parrot_layout"]` → the
  `Infographic.theme` prop when the top-level component is an `Infographic`
  → the renderer's constructor kwargs → the class defaults. Unknown values
  warn and fall back; nothing raises.
- Both renderers call it in `render()` and pass the result to
  `document_shell()`.
- **Card variant mapping** — `_render_prim_Card` (`interactive_html.py:529`)
  and `_render_Card` (`ssr_html.py:331`): read
  `metadata.extensions["parrot_variant"]` and append a semantic class to the
  existing `a2ui-card`: `kpi` → `kpi-card`, `report` → `report-card`,
  `chart`/`table` → `panel`, others → `a2ui-card-<variant>`.
- **Text role mapping** — `_render_prim_Text` (`interactive_html.py:478`)
  already emits `a2ui-<role>`; ADD the semantic class alongside for the roles
  the design system styles (`label` → `kpi-label`, `value` → `kpi-value`,
  `delta` → `kpi-delta`, `title`/`subtitle`/`heading`/`caption`/`notice` →
  their `ds-*` equivalents). `ssr_html._render_Text` (`:277`) gains the same
  mapping.
- `parrot_unit` renders as `<span class="kpi-unit">`; `parrot_trend` becomes
  `data-trend="up|down|flat"` on the delta element, which
  `components.css` colours.
- **KPI grid** — `_render_prim_Row` (`interactive_html.py:517`) and
  `_render_Row` (`ssr_html.py:319`): when every child Card carries
  `parrot_variant: "kpi"`, emit `class="a2ui-row kpi-grid"`.
- Share this logic through helpers in `_shell.py` (or a sibling
  `_semantics.py`) called by both dispatchers.

**NOT in scope**: the rich DataTable (TASK-2711); `FilterBar` (TASK-2715);
the runner (TASK-2714); modifying ANY `lower()` method or golden fixture.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../a2ui_renderers/_semantics.py` | CREATE | Shared variant/role → class helpers |
| `.../formats/assets/design_system/__init__.py` | MODIFY | Add `DesignSystem.resolve()` |
| `.../a2ui_renderers/interactive_html.py` | MODIFY | Card/Text/Row mapping; call `resolve()` |
| `.../a2ui_renderers/ssr_html.py` | MODIFY | Same |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py` | CREATE | Mapping + precedence tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.outputs.a2ui.catalog.base import BasicNode
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface, SurfaceMetadata
# verified: packages/ai-parrot/src/parrot/outputs/a2ui/models.py:364, 378, 446
```

### The metadata access path — use exactly this shape

```python
# packages/ai-parrot-visualizations/.../interactive_html.py:478-484 (existing, working)
def _render_prim_Text(self, node: BasicNode, degradations) -> str:
    props = node.model_extra or {}
    role = None
    if node.metadata is not None and node.metadata.extensions is not None:
        role = node.metadata.extensions.root.get("parrot_role")     # NOTE: .root — Extensions is a RootModel
    cls = f"a2ui-text a2ui-{_esc(role)}" if role else "a2ui-text"
    return f'<p class="{cls}">{_esc(props.get("text"))}</p>'
```

`node.metadata.extensions.root` is a plain dict. `ComponentMetadata`
(`a2ui/models.py:364`) has `extensions: Extensions | None` (`:373`);
`SurfaceMetadata = ComponentMetadata` (`:378`).

### The sites that currently DROP the variant

```python
# packages/ai-parrot-visualizations/.../interactive_html.py:529-531
def _render_prim_Card(self, node, degradations) -> str:
    inner = self._render_basic(node.child, degradations) if node.child is not None else ""
    return f'<div class="a2ui-card">{inner}</div>'          # metadata ignored

# packages/ai-parrot-visualizations/.../ssr_html.py:331-333
def _render_Card(self, node, degradations) -> str:
    ...
    return f'<div class="a2ui-card">{inner}</div>'          # metadata ignored
```

### What KPICard actually emits (do NOT change this file)

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
class KPICardComponent:                                     # line 50
    def lower(self, component, data_model) -> BasicTree:    # line 56
        # Text(parrot_role="label")
        # Text(parrot_role="value", parrot_unit=props.get("unit"))
        # Text(parrot_role="delta", parrot_trend=trend)      — only when delta or trend is set
        # returns Card(child=Column(children=[...]),
        #              metadata={"extensions": {"parrot_variant": "kpi"}})   # line 94
```

### The complete emitted vocabulary (verified by grep over `catalog/parrot/*.py` + `renderers/degrade.py`)

- **`parrot_variant` (8)**: `card`, `chart`, `infographic`, `kpi`, `map`, `report`, `table`, `timeline`
- **`parrot_role` (27)**: `axis`, `axis-label`, `body`, `caption`, `cell`, `column-header`, `delta`, `description`, `event`, `event-description`, `event-title`, `header`, `heading`, `label`, `layer`, `layer-summary`, `notice`, `row`, `rows`, `series`, `series-list`, `subtitle`, `summary`, `timestamp`, `title`, `trendline`, `value`
- **Extras**: `parrot_unit`, `parrot_trend` (kpicard), `parrot_component_id` (datatable), `parrot_optional` (narrative bindings)

### The theme hint that already exists in the schema

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infographic.py:39
"theme": {"type": "string", "description": "Theme hint (e.g. palette name)."},
# populated by build_infographic(theme=...) — packages/ai-parrot/src/parrot/outputs/a2ui/builders.py:220-221
# fed from RenderSpec.theme at runner.py:616, on the Infographic branch ONLY
# and read by NOTHING: _render_infographic (interactive_html.py:690) ignores it
```

### Does NOT Exist

- ~~`parrot_theme` / `parrot_layout` extension keys~~ — net-new, 0 hits repo-wide; this task defines them
- ~~`node.metadata.extensions["k"]`~~ — `Extensions` is a RootModel; the access is `.extensions.root.get("k")`
- ~~`node.metadata.variant` / `node.variant`~~ — no such attribute; variants live only under `extensions`
- ~~`ssr_html._render_prim_Card` / `_render_prim_Row` / `_render_prim_Text`~~ — SSR dispatch has NO `_prim_` infix: the real names are `_render_Card` (:331), `_render_Row` (:319), `_render_Text` (:277)
- ~~a shared base class or mixin between the two renderers~~ — none; a name-based mixin would silently no-op on one of them, which is why helpers are shared instead
- ~~an HTML golden/snapshot fixture~~ — the 8 goldens under `tests/outputs/a2ui/golden/` are *lowering* JSON only

---

## Implementation Notes

### Why helpers and not a mixin

The two renderers dispatch by different method names
(`_render_prim_<C>` vs `_render_<C>`). A mixin that defines
`_render_prim_Card` attaches to `interactive_html` and is never called by
`ssr_html`, producing a half-applied feature that tests on one surface would
not catch. Put the logic in free functions (`semantic_card_classes(node)`,
`semantic_text_classes(node)`, `is_kpi_row(node)`) and call them from both
dispatchers.

### Key Constraints

- **Additive only.** `a2ui-card` stays; `kpi-card` is appended. Every
  pre-existing class assertion must pass unmodified —
  `test_e2e_ssr_html.py:75` counts an exact class string
  `'class="a2ui-text a2ui-cell"'`, so for the `cell` role either append
  nothing or ensure the appended class comes after and the count assertion
  still holds. Verify this specific test before and after.
- **Do not touch any `lower()`.** If a mapping seems to need a new role,
  that is a signal to handle it in the renderer, not to change the catalog.
- Unknown variants/roles degrade to a generic class, never to an exception.

### References in Codebase

- `.../interactive_html.py:478-484` — the working role-read, the pattern to extend
- `.../kpicard.py:56-95` — what the KPI tree actually looks like
- `.../ssr_html.py:277, 319, 331` — the SSR dispatch names

---

## Acceptance Criteria

- [ ] A `KPICard` envelope renders with `kpi-card`, `kpi-label`, `kpi-value`, and `data-trend` when a trend is set, on BOTH renderers
- [ ] `parrot_unit` renders inside `<span class="kpi-unit">`
- [ ] A `Row` whose children are all `kpi`-variant Cards emits `kpi-grid`; a mixed Row does not
- [ ] `DesignSystem.resolve()` honours the four precedence levels in order, verified individually
- [ ] An unknown theme/layout in envelope metadata warns and falls back without raising
- [ ] The 8 golden fixtures under `packages/ai-parrot/tests/outputs/a2ui/golden/` are unchanged (`git diff --exit-code` on that directory)
- [ ] No file under `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/` is modified
- [ ] Every pre-existing test passes **without modification**, `test_e2e_ssr_html.py:75` included
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/ packages/ai-parrot/tests/outputs/a2ui/ -v`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py
import pytest
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer

RENDERERS = [InteractiveHTMLRenderer, SSRHTMLRenderer]


@pytest.fixture
def kpi_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="kpi",
        components=[Component(id="root", component="KPICard", label="Revenue",
                              value="1234", unit="USD", delta="+4.2%", trend="up")],
    )


@pytest.mark.parametrize("renderer_cls", RENDERERS)
class TestSemanticClasses:
    async def test_kpicard_variant_honoured(self, renderer_cls, kpi_envelope):
        doc = (await renderer_cls().render(kpi_envelope)).content.decode()
        assert "kpi-card" in doc
        assert "kpi-label" in doc
        assert "kpi-value" in doc
        assert 'data-trend="up"' in doc
        assert "kpi-unit" in doc

    async def test_legacy_classes_preserved(self, renderer_cls, kpi_envelope):
        doc = (await renderer_cls().render(kpi_envelope)).content.decode()
        assert "a2ui-card" in doc          # never replaced, only appended to
        assert "a2ui-value" in doc


class TestKpiGrid:
    async def test_kpi_row_becomes_grid(self): ...
    async def test_mixed_row_is_not_a_grid(self): ...


class TestResolutionPrecedence:
    async def test_envelope_extensions_win(self): ...
    async def test_infographic_theme_prop_is_second(self): ...
    async def test_constructor_is_third(self): ...
    async def test_class_default_is_last(self): ...
    async def test_unknown_value_warns_and_falls_back(self, caplog): ...


class TestGoldensUntouched:
    def test_no_catalog_file_modified(self):
        """Guard the spec's hard constraint: this feature never edits a lower()."""
        import subprocess
        changed = subprocess.run(
            ["git", "diff", "--name-only", "origin/dev", "--",
             "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/",
             "packages/ai-parrot/tests/outputs/a2ui/golden/"],
            capture_output=True, text=True, check=True).stdout.split()
        # filterbar.py + its golden are the ONLY permitted additions (TASK-2715)
        assert all("filterbar" in c for c in changed), changed
```

---

## Agent Instructions

1. **Read the spec** (§1 Problem Statement, §3 Module 3) — the "already
   emitted, thrown away" framing is the whole point of this task.
2. **Check dependencies** — TASK-2709 must be completed.
3. **Verify the Codebase Contract**, especially the `.extensions.root`
   access shape and the SSR method names (no `_prim_` infix).
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope. Touch no `lower()`.
6. **Verify** every acceptance criterion, running the pre-existing suites
   first to establish they still pass unmodified.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Added `DesignSystem.resolve(envelope, *, theme_default,
layout_default) -> tuple[str, str]` implementing the 4-level precedence
(envelope `metadata.extensions["parrot_theme"/"parrot_layout"]` -> the
top-level `Infographic.theme` prop (theme axis only) -> the renderer's
constructor kwargs -> `DEFAULT_THEME`/`DEFAULT_LAYOUT`), backed by
`_valid_theme_name`/`_valid_layout_name` helpers that log a warning and
fall through on an unrecognised name — never raises. Created
`a2ui_renderers/_semantics.py` with free functions (`semantic_card_class`,
`semantic_text_class`, `kpi_unit_html`, `trend_attr_html`, `is_kpi_row`) —
free functions rather than a mixin, per the task's own rationale, since
`interactive_html` dispatches via `_render_prim_<Name>` and `ssr_html` via
`_render_<Name>`. Wired both renderers' `_render_prim_Card`/`_render_Card`,
`_render_prim_Text`/`_render_Text`, and `_render_prim_Row`/`_render_Row` to
these helpers (additive only — `a2ui-card`/`a2ui-<role>` classes are never
replaced), and both `render()` methods to `DesignSystem.resolve()`.
`parrot_unit` renders as `<span class="kpi-unit">` appended after a
`value`-role Text's content; `parrot_trend` renders as
`data-trend="up|down|flat"` on a `delta`-role Text's `<p>`. Touched no
`lower()` — verified by a new `TestGoldensUntouched` test that
`git diff`s `catalog/` and `golden/` against `origin/dev` and asserts no
non-filterbar changes.

Tests: this task's new
`packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_semantic_classes.py`
(14 tests, incl. `test_e2e_ssr_html.py:75`'s exact
`class="a2ui-text a2ui-cell"` count-of-6 assertion re-verified unmodified)
passes; the full `packages/ai-parrot-visualizations/tests/` suite (147
tests) passes unmodified; the KPICard/Infographic/Chart-DataTable-Map
catalog test files under `packages/ai-parrot/tests/outputs/a2ui/` (36
tests) pass unmodified. `ruff check` is clean on all changed/created
files. Could not run the FULL `packages/ai-parrot/tests/outputs/a2ui/`
suite in this sandbox — its package-level `conftest.py` bootstraps a
Navigator/DB-backed app that times out with no DB/network reachable here
(pre-existing environment constraint, unrelated to this feature; same
constraint noted in prior sessions for this repo). Ran the golden-adjacent
component test files individually instead, plus the git-diff-based
goldens-untouched guard, as the concrete proof for that acceptance
criterion.

**Deviations from spec**: none.
