# TASK-2707: Design-system package — composer, base CSS, analytics layout, packaging

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2706
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. This task creates the design system itself: the packaged
CSS assets, the Python composer that stitches them together with the
`ThemeConfig` tokens from TASK-2706, and the packaging entry without which
an installed wheel would render unstyled HTML.

The quality bar is `docs/flex_program_report (39).html` — hand-authored CSS
custom properties, native grid, `tabular-nums` numerics, flat panels, solid
sticky table headers. Read it before writing `layout-analytics.css`; it is
the reference artifact, and it deliberately uses no framework.

---

## Scope

- Create the package
  `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/`
  with an `__init__.py` (required so setuptools treats it as a package and
  `package-data` can reach it).
- `base.css` — reset (`box-sizing`), typography scale, the `.ds-page` shell,
  and the table skeleton. System font stacks only; NO `@import`, NO webfont.
- `components.css` — card variants (`.a2ui-card`, `.kpi-card`, `.panel`,
  `.report-card`), `.kpi-grid` / `.kpi-label` / `.kpi-value` / `.kpi-unit` /
  `.kpi-delta[data-trend]`, tabs, callouts, timeline, progress, and the
  filter-bar classes (styles only — TASK-2715/2716 emit the markup).
- `layout-analytics.css` — the dense aesthetic: wide `--content-width`, flat
  panels, `font-variant-numeric: tabular-nums` on `.num`, solid sticky table
  headers, responsive breakpoints.
- `DesignSystem` in `__init__.py` per the spec's New Public Interfaces:
  `LAYOUTS`, `DEFAULT_THEME`, `DEFAULT_LAYOUT`, and
  `stylesheet(theme, layout) -> str`.
- Read every `.css` **once at import**, never inside a call — copy the
  documented rationale at `interactive_html.py:92-97`.
- Cache the composed sheet per `(theme_name, layout)`.
- An unknown theme or layout logs a warning via `logging.getLogger(__name__)`
  and falls back to the default. It MUST NOT raise: a missing theme is a
  cosmetic failure, not a render failure.
- Extend `[tool.setuptools.package-data]`
  (`packages/ai-parrot-visualizations/pyproject.toml:78-79`) with
  `"parrot.outputs.formats.assets.design_system" = ["*.css"]`.

**NOT in scope**: `layout-report.css` and `layout-print.css` (TASK-2708);
wiring any renderer to the composer (TASK-2709); `DesignSystem.resolve()`,
which needs envelope access and belongs to TASK-2710.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../formats/assets/design_system/__init__.py` | CREATE | `DesignSystem` composer |
| `.../formats/assets/design_system/base.css` | CREATE | Reset, typography, `.ds-page` shell, table skeleton |
| `.../formats/assets/design_system/components.css` | CREATE | Card/KPI/panel/tabs/callout/timeline/progress/filter-bar styles |
| `.../formats/assets/design_system/layout-analytics.css` | CREATE | Dense dashboard layout (the new default) |
| `packages/ai-parrot-visualizations/pyproject.toml` | MODIFY | `package-data` entry for `*.css` |
| `packages/ai-parrot-visualizations/tests/outputs/test_design_system.py` | CREATE | Unit tests |

Paths above are relative to
`packages/ai-parrot-visualizations/src/parrot/outputs/`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.infographic import ThemeConfig, theme_registry
# verified: packages/ai-parrot/src/parrot/models/infographic.py:1375, 1574
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/infographic.py
class ThemeConfig(BaseModel):                      # line 1375
    name: str                                      # line 1382
    def to_css_variables(self) -> str: ...         # line 1457
    # + the nine layout tokens added by TASK-2706

class ThemeRegistry:                               # line 1510
    def get(self, name: str) -> ThemeConfig: ...   # line 1528 — raises KeyError listing available themes
    def list_themes(self) -> List[str]: ...        # line 1548

theme_registry = ThemeRegistry()                   # line 1574
# themes: light, dark, corporate, midnight, petrol
```

### The import-time asset-read pattern to copy VERBATIM in spirit

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:89-97
_CHART_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "chart.umd.min.js"

#: Read ONCE at import time (not per-render) — this is a 200KB+ file and
#: `render()` is an async method; re-reading it synchronously on every call
#: would block the event loop repeatedly for no benefit, since the bundle
#: never changes at runtime.
_CHART_JS_SOURCE = _CHART_JS_PATH.read_text(encoding="utf-8")
```

### Existing CSS to mine for `components.css`

`packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py:176`
defines `BASE_CSS` (~180 lines, commented *"extracted from reference
HTML"*). Its component rules are the starting point — `.kpi-grid`
(`grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))`),
`.kpi-card`, `.kpi-value`, `.kpi-label`, `.kpi-trend.up/.down/.flat`,
`.chart-container`, zebra + hover tables, `.callout-block.info/.success/
.warning/.error/.tip`, `.timeline-block`, `.progress-block`, `hr.divider`.
Do NOT delete it in this task — TASK-2708 migrates it and TASK-2712 removes
the original.

### Packaging, as it stands today

```toml
# packages/ai-parrot-visualizations/pyproject.toml:78-79
[tool.setuptools.package-data]
"parrot.outputs.formats.assets" = ["*.js"]
```

Only `*.js`. A `.css` file added without a new entry ships in the source
tree, passes every source-tree test, and is ABSENT from the wheel.

### Does NOT Exist

- ~~`parrot.outputs.formats.assets.design_system`~~ — this task creates it (0 hits repo-wide)
- ~~`DesignSystem`~~ — no such class anywhere (0 hits)
- ~~any `.css` file under `packages/ai-parrot-visualizations/src`~~ — none exists today
- ~~`parrot.outputs.design`~~ / ~~`parrot.outputs.styles`~~ — wrong modules, do not invent them
- ~~a Tailwind/PostCSS/Node build step~~ — explicitly rejected in spec §1 Non-Goals; write plain CSS
- ~~`importlib.resources` helpers already present for CSS~~ — the existing precedent uses `Path(__file__).parent`, follow it

---

## Implementation Notes

### Composer shape

```python
class DesignSystem:
    LAYOUTS: ClassVar[frozenset[str]] = frozenset({"report", "analytics", "print"})
    DEFAULT_THEME: ClassVar[str] = "light"
    DEFAULT_LAYOUT: ClassVar[str] = "analytics"

    @classmethod
    def stylesheet(cls, theme=None, layout=None) -> str:
        """Compose the CSS for a (theme, layout) pair; never raises on a bad name."""
```

`LAYOUTS` declares `report` and `print` even though TASK-2708 authors their
files — guard the missing-file case with the same warn-and-fall-back
behaviour so this task's tests can pass standalone, and so a partially
applied feature degrades instead of exploding.

### Key Constraints

- **Zero external references.** No `@import`, no `url(https://…)`, no
  webfont. Spec §1 Non-Goals; enforced by `test_interactive_html.py:64-67`.
- Style exclusively through the custom properties emitted by
  `to_css_variables()`. A hardcoded hex in a renderer or in
  `layout-*.css` defeats the theme axis.
- `LAYOUTS` must not intersect `theme_registry.list_themes()` — `corporate`
  is already a theme name (`models/infographic.py:1609`); there is a test
  for this.
- Async-safety: no file I/O inside any method that a `render()` awaits.

### References in Codebase

- `docs/flex_program_report (39).html` lines 25-198 — the reference stylesheet; read it first
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py:176` — `BASE_CSS`, the component rules to mine
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:89-97` — the import-time asset pattern

---

## Acceptance Criteria

- [ ] `DesignSystem.stylesheet()` returns non-empty CSS for `("light", "analytics")`
- [ ] Every `.css` asset loads and is non-empty **when imported from an installed wheel**, not only from the source tree
- [ ] Assets are read once at import: two `stylesheet()` calls with the same pair return the identical cached object
- [ ] An unknown theme name and an unknown layout name each log a warning and return the default sheet, raising nothing
- [ ] `DesignSystem.LAYOUTS` does not intersect `theme_registry.list_themes()`
- [ ] The composed sheet contains no `@import` and no `url(http`
- [ ] `pyproject.toml` declares `*.css` for the new package
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/test_design_system.py -v`
- [ ] `ruff check` and `mypy` clean on the new `__init__.py`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/test_design_system.py
import pytest
from parrot.models.infographic import theme_registry
from parrot.outputs.formats.assets.design_system import DesignSystem


class TestDesignSystem:
    def test_composes_default_pair(self):
        css = DesignSystem.stylesheet("light", "analytics")
        assert css.strip()
        assert "--content-width" in css      # tokens present
        assert ".kpi-card" in css            # components present
        assert ".ds-page" in css             # shell present

    def test_assets_packaged_and_non_empty(self):
        """Catches a package-data regression: every asset must load with content."""
        for layout in ("analytics",):
            assert len(DesignSystem.stylesheet("light", layout)) > 500

    def test_stylesheet_cached_per_pair(self):
        a = DesignSystem.stylesheet("light", "analytics")
        b = DesignSystem.stylesheet("light", "analytics")
        assert a is b

    def test_unknown_theme_falls_back_with_warning(self, caplog):
        css = DesignSystem.stylesheet("no-such-theme", "analytics")
        assert css.strip()
        assert any("no-such-theme" in r.message for r in caplog.records)

    def test_unknown_layout_falls_back_with_warning(self, caplog):
        assert DesignSystem.stylesheet("light", "no-such-layout").strip()
        assert caplog.records

    def test_layouts_disjoint_from_theme_names(self):
        """'corporate' is a THEME; layout names must never collide with themes."""
        assert not DesignSystem.LAYOUTS & set(theme_registry.list_themes())

    def test_no_external_references(self):
        css = DesignSystem.stylesheet("light", "analytics")
        assert "@import" not in css
        assert "url(http" not in css

    @pytest.mark.parametrize("theme", sorted(theme_registry.list_themes()))
    def test_every_theme_composes(self, theme):
        assert DesignSystem.stylesheet(theme, "analytics").strip()
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview, §3 Module 2) and then
   `docs/flex_program_report (39).html` lines 25-198 — that stylesheet is
   the quality target.
2. **Check dependencies** — TASK-2706 must be in `sdd/tasks/completed/`; the
   composer emits its tokens.
3. **Verify the Codebase Contract**, especially the `pyproject.toml`
   `package-data` block, before writing code.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** every acceptance criterion — including the wheel check, which
   is the one that source-tree testing cannot catch.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
