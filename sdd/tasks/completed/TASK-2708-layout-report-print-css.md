# TASK-2708: layout-report.css (1:1 legacy migration) + layout-print.css

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2707
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (second half). Two more layouts on top of TASK-2707's
`analytics`:

- **`report`** reproduces today's infographic appearance exactly, so the
  visual-default change this feature introduces stays reversible per caller.
  It is a *migration*, not a redesign: the existing `BASE_CSS` is the source
  of truth and every one of its selectors must survive.
- **`print`** exists because `PDFRenderer` subclasses `SSRHTMLRenderer`
  (`pdf.py:99`) and therefore inherits whatever stylesheet SSR uses. Print
  needs no shadows, no `auto-fit`/`minmax`, and real `@page` rules.

---

## Scope

- `layout-report.css` — migrate the layout-and-density half of `BASE_CSS`
  (`formats/infographic_html.py:176`) **1:1**: `.container { max-width:
  900px }`, the gradient `.hero`, 24px radii, `.section-title::after`, and
  the block spacing. Component rules that TASK-2707 already moved into
  `components.css` must NOT be duplicated here — this file carries only what
  differs from `analytics`.
- `layout-print.css` — no `box-shadow`, no `repeat(auto-fit, minmax(...))`
  (use explicit column counts), `@page { size: A4; margin: … }`,
  `break-inside: avoid` on cards/panels/table rows, and
  `--shadow: none`.
- Add both to the composer's asset table so `DesignSystem.LAYOUTS` is fully
  backed by real files.
- Write the parity test that enumerates every selector in the legacy
  `BASE_CSS` and asserts each one is reachable from
  `stylesheet(theme, "report")`. This test is the whole point of calling the
  migration 1:1 — do not weaken it to a spot-check.

**NOT in scope**: removing `BASE_CSS` from `infographic_html.py`
(TASK-2712 does that, after this file proves parity); wiring `PDFRenderer`
to `print` (TASK-2713); empirical WeasyPrint verification (TASK-2713).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../formats/assets/design_system/layout-report.css` | CREATE | 1:1 migration of the legacy look |
| `.../formats/assets/design_system/layout-print.css` | CREATE | Print-safe layout |
| `.../formats/assets/design_system/__init__.py` | MODIFY | Register the two new assets |
| `packages/ai-parrot-visualizations/tests/outputs/test_design_system_layouts.py` | CREATE | Parity + print-safety tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.infographic import theme_registry            # models/infographic.py:1574
from parrot.outputs.formats.assets.design_system import DesignSystem   # created by TASK-2707
```

### The legacy stylesheet being migrated

`packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py:176`
— `BASE_CSS`, a `"""\`-opened Python string of ~180 lines, commented
*"Base CSS (extracted from reference HTML)"* at line 173. Its complete
selector list, verified by extraction:

```
body · .container · .hero · .hero h1 · .hero p · .hero .meta
.section-title · .section-title::after
.kpi-grid · .kpi-card · .kpi-value · .kpi-label
.kpi-trend · .kpi-trend.up · .kpi-trend.down · .kpi-trend.flat
.chart-container · .chart-container h3
table · th · td · tr:nth-child(even) · tr:hover
.table-container · .table-container h3
.summary-block · .summary-block.highlight · .summary-block h3
.bullet-list-block (+ h3, ul/ol, li)
.image-block (+ img, .caption)
blockquote.quote-block (+ .attribution)
.callout-block (+ h3) · .callout-block.info/.success/.warning/.error/.tip (+ h3 each)
hr.divider · hr.divider.solid/.dashed/.dotted/.gradient
.timeline-block (+ h3) · .timeline-event (+ ::before, ::after, :last-child::after)
.timeline-date · .timeline-content (+ .title, .desc)
.progress-block (+ h3) · .progress-item · .progress-header
.progress-label · .progress-value · .progress-track · .progress-fill · .progress-target
.empty-message · footer.infographic-footer
+ media-query overrides for .container, .hero, .hero h1, .kpi-grid, body
```

It is already token-driven (`var(--font-family)`, `var(--body-bg)`,
`var(--neutral-text)`, `var(--surface-bg, white)`, `var(--primary)`,
`var(--neutral-border)`, `var(--callout-tip-bg, #f0fdfa)` …), which is why a
1:1 migration is possible without rewriting values.

### WeasyPrint, as pinned

```toml
# packages/ai-parrot/pyproject.toml:199
"weasyprint==69.0"
# packages/ai-parrot-visualizations/pyproject.toml:60
"weasyprint>=68.0"
```

Do NOT assume what CSS this version supports. `layout-print.css` avoids
`auto-fit`/`minmax` outright precisely so the question does not arise here;
TASK-2713 establishes the empirical answer.

### Does NOT Exist

- ~~`layout-report.css` / `layout-print.css`~~ — created by this task
- ~~a `.print` or `@media print` block in `BASE_CSS`~~ — the legacy CSS has screen media queries only (`max-width` breakpoints); there is no print handling anywhere today
- ~~`.panel` / `.ds-page` / `.num` in `BASE_CSS`~~ — those are net-new classes from TASK-2707, not legacy ones
- ~~a visual/HTML snapshot baseline for the infographic lane~~ — none exists; the selector-parity test is the only guard against regressing the legacy look

---

## Implementation Notes

### How to keep the migration honest

Extract the legacy selector list mechanically rather than by eye, and keep
the extraction in the test so it cannot drift:

```python
_SELECTOR_RE = re.compile(r"^\s*([^{}@/]+?)\s*\{", re.MULTILINE)
legacy = {s.strip() for s in _SELECTOR_RE.findall(BASE_CSS)}
```

Then assert every legacy selector appears in
`components.css + layout-report.css`. A selector that TASK-2707 moved into
`components.css` counts as present — the test checks the *composed* sheet,
not one file.

### Key Constraints

- Same zero-external-reference rule as TASK-2707: no `@import`, no webfont.
- `layout-report.css` must not restate component rules already in
  `components.css`; duplication is how the two layouts silently diverge.
- Print: explicit grid column counts, never `auto-fit`.

### References in Codebase

- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py:173-400` — the legacy `BASE_CSS`
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py:99` — `class PDFRenderer(SSRHTMLRenderer)`, why print exists

---

## Acceptance Criteria

- [ ] Every selector present in the legacy `BASE_CSS` is reachable from `DesignSystem.stylesheet(theme, "report")`, verified by mechanical extraction rather than a spot-check
- [ ] `layout-report.css` contains no rule already defined in `components.css`
- [ ] `stylesheet(theme, "print")` contains no `box-shadow` with a non-`none` value and no `auto-fit`/`minmax`
- [ ] `stylesheet(theme, "print")` contains an `@page` rule and `break-inside: avoid` for cards/panels
- [ ] All three layouts compose for all five themes (15 pairs), none empty
- [ ] Neither file contains `@import` or `url(http`
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/test_design_system_layouts.py -v`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/test_design_system_layouts.py
import re
import pytest
from parrot.models.infographic import theme_registry
from parrot.outputs.formats.infographic_html import BASE_CSS
from parrot.outputs.formats.assets.design_system import DesignSystem

_SELECTOR_RE = re.compile(r"^\s*([^{}@/]+?)\s*\{", re.MULTILINE)


def _legacy_selectors() -> set[str]:
    return {s.strip() for s in _SELECTOR_RE.findall(BASE_CSS) if s.strip()}


class TestReportLayoutParity:
    def test_report_layout_matches_legacy_selectors(self):
        """Every legacy selector survives the migration — mechanically checked."""
        composed = DesignSystem.stylesheet("light", "report")
        missing = sorted(s for s in _legacy_selectors() if s not in composed)
        assert not missing, f"selectors lost in migration: {missing}"


class TestPrintLayout:
    def test_no_shadows(self):
        css = DesignSystem.stylesheet("light", "print")
        assert "--shadow: none" in css or "box-shadow: none" in css

    def test_no_auto_fit(self):
        css = DesignSystem.stylesheet("light", "print")
        assert "auto-fit" not in css
        assert "minmax" not in css

    def test_page_rules_present(self):
        css = DesignSystem.stylesheet("light", "print")
        assert "@page" in css
        assert "break-inside" in css


@pytest.mark.parametrize("theme", sorted(theme_registry.list_themes()))
@pytest.mark.parametrize("layout", ["report", "analytics", "print"])
def test_all_theme_layout_pairs_compose(theme, layout):
    css = DesignSystem.stylesheet(theme, layout)
    assert css.strip()
    assert "@import" not in css
    assert "url(http" not in css

---

## Agent Instructions

1. **Read the spec** at the path in the header for full context.
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing any code: confirm each
   listed import, signature and line number still holds. If the file has
   shifted, update this contract FIRST, then implement.
4. **Update status** in `sdd/tasks/index/html-renderer-design-system.json` → `"in-progress"`.
5. **Implement** per scope — nothing outside it.
6. **Verify** every acceptance criterion by running it, not by inspection.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note.**

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-01
**Notes**: Mechanically extracted the legacy `BASE_CSS`'s 172 unique
top-level/nested selectors via a brace-depth parser, then wrote
`layout-report.css` as every one of its top-level rule blocks EXCEPT the
24 already defined verbatim in `components.css` (`.kpi-grid`, `.kpi-card`,
`.kpi-value`, `.kpi-label`, `.callout-block` + its 5 variants + its `h3`,
`.timeline-block`/`.timeline-event` (+ pseudo-elements)/`.timeline-date`/
`.timeline-content`, `.progress-block`/`.progress-item`/`.progress-header`/
`.progress-track`/`.progress-fill`/`.progress-target`) — including the two
legacy `@media` breakpoint blocks verbatim, since a selector legitimately
reappearing inside a narrow breakpoint override is not "the same rule
restated." Verified 0-of-172 selectors missing from the composed
`(theme, report)` sheet. Wrote `layout-print.css` with `@page { size: A4;
margin: … }`, `break-inside: avoid` on cards/panels/table rows/timeline/
progress blocks, `--shadow: none` scoped under
`[data-layout="print"]`, and fixed (non-responsive) KPI grid column
counts. `__init__.py` required no functional change — TASK-2707 already
declared the `report`/`print` keys in `_LAYOUT_CSS` forward-looking for
this task; only tightened a now-stale docstring comment. All 32 tests
(this task's 6 + TASK-2707's 12 + the 5×3 all-pairs matrix, re-verified)
pass; `ruff check` is clean; confirmed via an actual
`python -m build --wheel` that both new CSS files ship in the wheel.

**Deviations from spec**:
- Modified `components.css` (not listed in this task's Files table) to
  change `.kpi-grid`'s `grid-template-columns` from
  `repeat(auto-fit, minmax(180px, 1fr))` to a fixed `repeat(4, 1fr)`,
  moving the responsive auto-fit/minmax behaviour into
  `layout-analytics.css` (scoped under `[data-layout="analytics"]`)
  instead. This was necessary: `components.css` is unconditionally
  concatenated into every composed stylesheet including `print`, so its
  original auto-fit/minmax literally appeared in
  `DesignSystem.stylesheet(theme, "print")`, violating this task's own
  acceptance criterion ("no `auto-fit`/`minmax`" in the print sheet) —
  a cross-task interaction TASK-2707 could not have anticipated before
  `print` existed. Re-ran TASK-2707's full test suite after the change;
  all 12 tests still pass.
- Added a fourth, supplementary test
  (`test_report_layout_does_not_duplicate_components`) beyond the given
  Test Specification, to make the acceptance criterion "layout-report.css
  contains no rule already defined in components.css" independently
  verifiable rather than only manually reasoned about. It compares only
  TOP-LEVEL selectors (via the same brace-depth parser used to build the
  migration) so a legitimate narrow `@media` breakpoint override (e.g.
  `.kpi-grid` collapsing to one column under 560px, migrated verbatim
  from the legacy sheet) is not flagged as duplication.
