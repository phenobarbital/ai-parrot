# TASK-2716: Interactive multiselect UI + client-side dataModel filtering

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2715, TASK-2711
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (second half). This is the last task in the graph and the
spec's **designated cut line**: it is the only non-presentational module —
it carries state, interaction and data semantics rather than styling — and
nothing else depends on it. If scope has to shrink, this is what goes, and
the design system, rich table and KPI cards still deliver the bulk of the
visual improvement (spec §3 Module 8 note, §7 Known Risks).

Interactivity here means filtering the **already-embedded** `dataModel`
client-side. It is not a data fetch and not a server round-trip; the
`refresh_dashboard` server-side replay lane is FEAT-491's concern and is
unrelated to this.

---

## Scope

- `interactive-html` intercepts the `filter-bar` variant and emits the
  reference control: a searchable multiselect per filter — button, dropdown
  panel with a text search, per-option checkboxes, select-all/clear actions,
  selection chips, and a global reset — matching
  `docs/flex_program_report (39).html` lines 60-105.
- Filtering JS in `_BEHAVIOR_JS` over the `report-data` JSON:
  - A filter applies **only** to charts/tables whose dataset declares that
    filter's `parrot_filter_column`. A section without the column is left
    untouched — never blanked, never zeroed.
  - Re-render affected Chart.js instances and re-emit affected table bodies
    from the filtered rows, reusing TASK-2711's formatting so filtered cells
    look identical to unfiltered ones.
  - A filter state summary line reflects the current selection.
- Empty result handling: a section whose rows all filter out shows an
  explicit "no rows match" state, not an empty chart canvas.
- All vanilla ES2017, no dependency, consistent with the existing hooks.

**NOT in scope**: the composite and its degradation (TASK-2715); server-side
refresh or recipe params (FEAT-491 owns that lane); URL/state persistence;
cross-artifact filter state.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../a2ui_renderers/interactive_html.py` | MODIFY | Intercept `filter-bar`; emit the multiselect markup |
| `.../a2ui_renderers/interactive_html.py` (`_BEHAVIOR_JS`) | MODIFY | Filtering, re-render, chips, reset, empty state |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_interactive.py` | CREATE | Markup + hook tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot-visualizations/.../interactive_html.py
_INTERCEPTED = {"Chart", "DataTable", "Infographic"}   # line 86 — add the FilterBar handling here
_BEHAVIOR_JS = r"""..."""                              # line 142 — vanilla ES2017, no deps
class InteractiveHTMLRenderer(AbstractA2UIRenderer):   # line 295
    async def render(self, envelope, *, bake=True) -> RenderedArtifact: ...   # line 298
    def _render_top(self, comp, by_id, degradations) -> str: ...               # line 393
    def _render_prim_Row(self, node, degradations) -> str: ...                 # line 517
    def _render_chart(self, props) -> str: ...                                # line 600
    def _render_datatable(self, props) -> str: ...                            # line 653
```

### How the data model reaches the page (already working)

```python
# interactive_html.py:331, 339
data_model_json = _safe_json(envelope.data_model)
f'<script type="application/json" id="report-data">{data_model_json}</script>'
```

```javascript
// _BEHAVIOR_JS, interactive_html.py:145-150 — the existing accessor
function reportData() {
  var el = document.getElementById("report-data");
  if (!el) return {};
  try { return JSON.parse(el.textContent); } catch (e) { return {}; }
}
```

### The documented behaviour-hook conventions to extend (docstring, `interactive_html.py:28-51`)

```
[data-chart-config] on a <canvas>          — JSON chart config, Chart.js instantiated on load
[data-tabs-for="<chart-id>"] + [data-tab-index]        — day-tab switching
[data-metric-toggle-for="<chart-id>"] + [data-metric-index]  — series visibility
[data-sort-table] + [data-sort-key]        — client-side column sort
[data-tabs="<id>"] + [data-tabs-panes="<id>"] + [data-pane-index]  — generic Tabs
```

Follow the same `data-*` attribute-driven style: "All hooks are driven purely
by component properties / the embedded data — never hardcoded to any specific
dashboard."

### The vocabulary this task consumes (from TASK-2715)

```
Row     metadata.extensions.parrot_variant = "filter-bar"
child   metadata.extensions.parrot_role = "filter"
child   metadata.extensions.parrot_filter_column = "<column>"
```

Access shape: `node.metadata.extensions.root.get("parrot_filter_column")` —
`Extensions` is a RootModel.

### The self-contained invariant, enforced by test

```
packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py:64-67
    assert externals == [] ; "@import" not in doc ; "<script src=" not in doc ; "<link " not in doc
```

### Does NOT Exist

- ~~a client-side filtering runtime today~~ — `_BEHAVIOR_JS` has sort, tabs and metric toggles only; nothing filters
- ~~a Chart.js data-update helper in `_BEHAVIOR_JS`~~ — the tab switching swaps `config.tabs[index].data`; there is no generic re-render-from-rows path yet
- ~~`window.a2ui` / a global runtime object~~ — `_BEHAVIOR_JS` is a self-executing IIFE (`(function () { "use strict"; ...`), not a namespaced API
- ~~a filter-state persistence mechanism~~ — no localStorage/URL state anywhere in this renderer
- ~~any relationship to `refresh_dashboard`~~ — that is FEAT-491's server-side replay tool; this task must not call or assume it

---

## Implementation Notes

### Which sections a filter touches

Derive it from the data, never from a hardcoded map: a chart or table is
affected iff its bound rows contain the filter's column. A section that does
not carry the column is untouched — the spec's "a filter applies only to
sections whose dataset carries the column" rule. Blanking an unrelated
section is the most likely wrong behaviour here, so test it explicitly.

### Key Constraints

- Reuse TASK-2711's cell formatting for re-rendered rows; a filtered table
  that formats differently from its initial render is a visible defect.
- Keep the IIFE structure and the `data-*` hook style; no global namespace.
- No dependency, no CDN, no build step — the invariant test above is
  unforgiving.
- Empty result is an explicit state, not an empty canvas.

### References in Codebase

- `docs/flex_program_report (39).html` lines 60-105 (`.msf`, `.msf-btn`, `.msf-panel`, `.msf-search`, `.msf-actions`, `.reset-btn`, `.filter-summary`) — the reference control and the class names `components.css` already styles
- `.../interactive_html.py:142-290` — `_BEHAVIOR_JS`, where the filtering runtime goes
- `.../interactive_html.py:28-51` — the hook-convention docstring to extend

---

## Acceptance Criteria

- [ ] A `FilterBar` renders a searchable multiselect per filter, with chips and a reset control
- [ ] Selecting a value filters the charts and tables whose data carries that column
- [ ] A section whose data does NOT carry the filtered column is left completely unchanged
- [ ] A filter that excludes every row shows an explicit "no rows match" state, not an empty canvas
- [ ] Re-rendered table cells use the same formatting as the initial render
- [ ] The filter summary line reflects the current selection
- [ ] Reset restores the unfiltered view exactly
- [ ] `_BEHAVIOR_JS` remains a single dependency-free IIFE; the self-contained test at `test_interactive_html.py:64-67` passes unmodified
- [ ] `ssr-html`/`pdf` degradation from TASK-2715 is unaffected
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/ -v`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_interactive.py
import pytest


class TestFilterBarMarkup:
    async def test_multiselect_rendered(self):
        """Button, panel, search input, options, actions and reset all present."""
    async def test_filter_column_reaches_the_dom(self):
        """Each control carries its parrot_filter_column as a data attribute."""
    async def test_chips_and_summary_present(self): ...


class TestFilteringRuntime:
    async def test_behaviour_js_references_filter_hooks(self):
        """The runtime is wired by data-* hook names, not by dashboard-specific ids."""
    async def test_no_external_references(self):
        """test_interactive_html.py:64-67's invariant, re-asserted with a FilterBar present."""
    async def test_empty_state_markup_present(self): ...


class TestSectionScoping:
    async def test_unrelated_section_untouched(self):
        """A chart whose rows lack the filtered column must not be blanked."""
```

Behavioural assertions over the runtime are markup/hook-level here: there is
no JS test harness in this repo, so verify the emitted hooks and the runtime's
reference to them, and record any manual browser verification in the
completion note.

---

## Agent Instructions

1. **Read the spec** (§3 Module 8 including its cut-line note, §7 Known
   Risks) and `docs/flex_program_report (39).html` lines 60-105.
2. **Check dependencies** — TASK-2715 and TASK-2711 must both be completed.
3. **Verify the Codebase Contract**, especially that `_BEHAVIOR_JS` is still
   an IIFE and that no filtering runtime has appeared in the meantime.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope. If the work turns out materially larger than the
   estimate, say so rather than half-landing it — this task is explicitly
   cuttable and a partial filter runtime is worse than none.
6. **Verify** every acceptance criterion; note any manual browser check.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: The bulk of the FilterBar interactive multiselect + filtering
runtime was already implemented (uncommitted) in the worktree when this
session resumed FEAT-493; this session verified it against the Codebase
Contract and the FilterBar catalog component (`catalog/parrot/filterbar.py`,
TASK-2715), wrote the missing test module
(`test_filterbar_interactive.py`), and fixed one regression it caused: the
runtime's empty-result notice literally embedded the string
`"a2ui-table-notice"` (TASK-2711's truncation-notice class) inside
`_BEHAVIOR_JS`, which is inlined into every rendered page — that broke
`test_rich_datatable.py::test_no_truncation_notice_when_not_truncated`,
which asserts that class's *absence* means "not truncated". Fixed by giving
the empty-result notice its own class (`a2ui-filter-empty` only, no shared
class), since neither class carries any CSS styling today.

**Manual verification performed**: Read-through of the full markup +
`_BEHAVIOR_JS` diff against the task's Codebase Contract and Implementation
Notes; confirmed `node_extensions`, `_esc`, `buildDatasets`, `data-table`/
`data-chart`/`data-chart-config` hook names, and the FilterBar → Row →
ChoicePicker lowering shape (`parrot_role`/`parrot_filter_column`) all match
existing code exactly. No browser/Chart.js manual run performed (out of
scope for this environment) — coverage is via markup/hook-presence
assertions per the task's own Test Specification.

**Deviations from spec**: none. (One in-scope bugfix, described above, to
the file this task already modifies — not a scope change.)

**Test results**: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/ -v`
→ 150 passed. Full `ai-parrot-visualizations` suite → 217 passed.
`ruff check` on both changed files → all checks passed.
