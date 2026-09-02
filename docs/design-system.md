# Backend HTML Design System (FEAT-493)

`parrot.outputs.formats.assets.design_system.DesignSystem` is the single CSS
composer shared by every backend-rendered HTML surface —
`interactive-html`, `ssr-html`, `pdf` (via `PDFRenderer`, which forces
`layout="print"`), and `formats/infographic_html.py`. Before FEAT-493, each
renderer hand-rolled its own `_STYLE`/`BASE_CSS` constant; now they all call
`DesignSystem.stylesheet(theme, layout)` and get back one composed,
self-contained stylesheet (no `<link>`, no `@import`, no external fetch).

> **⚠️ Visual change on upgrade.** `analytics` is the default `layout`
> everywhere (`DesignSystem.DEFAULT_LAYOUT`), including for existing
> `infographic_html` consumers who never passed a `layout` argument before
> this feature existed. Their output looks different starting with this
> release — denser KPI grid, sticky table headers, tabular-numeric columns.
> If you need the *previous* look, pass `layout="report"` explicitly: it
> reproduces the pre-FEAT-493 `infographic_html` appearance. Any stored
> screenshot or visual baseline kept outside this repo will no longer match.

## The two axes

`DesignSystem.stylesheet()` takes two **orthogonal** arguments — mixing any
theme with any layout is a supported `(theme, layout)` pair (15 combinations
today: 5 themes × 3 layouts), and every pair is exercised by
`test_design_system.py::test_all_theme_layout_pairs_compose`.

| Axis | Values | Controls | Resolved by |
|---|---|---|---|
| `theme` | `light`, `dark`, `corporate`, `midnight`, `petrol` | Palette — colors, fonts, `ThemeConfig.to_css_variables()`'s `:root { --token: value; }` block | `parrot.models.infographic.theme_registry` |
| `layout` | `report`, `analytics` (default), `print` | Density/structure — page width, table chrome, sticky headers, KPI grid density, print page rules | `DesignSystem.LAYOUTS` / `DesignSystem.DEFAULT_LAYOUT` |

Neither axis ever raises. An unknown name is a cosmetic failure only: it is
logged as a `logger.warning(...)` and silently resolved to the default
(`DesignSystem.DEFAULT_THEME` / `DesignSystem.DEFAULT_LAYOUT`) —
`DesignSystem._resolve_theme` / `_resolve_layout`, plus each renderer's own
call site (e.g. `InfographicHTMLRenderer.render_to_html`), all follow this
same warn-and-fall-back rule.

A composed sheet is cached per `(theme_key, layout_key)` pair
(`DesignSystem._cache`) — resolving the same pair twice returns the
identical cached string.

## Rendered output shape

Every HTML document produced through the design system wraps its body in:

```html
<div class="ds-page" data-layout="<layout>" data-theme="<theme>">
```

so layout-specific CSS can scope itself with `.ds-page[data-layout="..."]`
(see `layout-analytics.css`'s sticky-header/KPI-grid rules) without leaking
into the other two layouts, and the resolved pair is inspectable straight
from the rendered markup — no need to re-derive it from renderer arguments.

## The CSS assets

Composition order (`DesignSystem.stylesheet()`, `__init__.py`):

```
theme_config.to_css_variables()   # :root { --token: value; } for this theme
+ base.css                        # reset, typography scale, page shell, table skeleton
+ components.css                  # KPI cards, tables, tabs, FilterBar's .msf-* controls, etc.
+ layout-<layout>.css             # the one selected layout (report | analytics | print)
```

Each file is read **once at import time** (`_read_asset`, matching the
`_CHART_JS_SOURCE` pattern in `interactive_html.py`) — never inside
`stylesheet()`, since that would block the event loop on every async
render for no benefit. A missing asset degrades (logs a warning, composes
without that part) rather than crashing the whole module's import.

Packaging: all five files ship via
`packages/ai-parrot-visualizations/pyproject.toml`'s
`[tool.setuptools.package-data]` entry —
`"parrot.outputs.formats.assets.design_system" = ["*.css"]` — verified by
building a real wheel, not just by reading from the source tree
(`test_design_system.py`'s installed-wheel assertion).

## The layout token list

`ThemeConfig` (`parrot/models/infographic.py`) carries the layout tokens
added by TASK-2706, each **optional** with a documented derivation from an
existing color/font token — every one of the five pre-existing registered
themes keeps working, byte-for-byte, without opting in:

| Field | CSS variable | Derives from, if unset |
|---|---|---|
| `content_width` | `--content-width` | `1200px` |
| `radius` | `--radius` | `8px` |
| `density` (`"comfortable"` \| `"compact"`) | `--density`, `--density-gap`, `--density-padding` | `"comfortable"` (`1rem` gap/padding; `0.5rem` when `"compact"`) |
| `shadow` | `--shadow` | `0 1px 3px rgba(0, 0, 0, 0.1)` (set to `"none"` for print) |
| `mono_family` | `--mono-family` | a system monospace stack (used by numeric table cells, see `.num` in `base.css`) |
| `panel_bg` | `--panel-bg` | `surface_bg`, then `neutral_bg` |
| `panel_border` | `--panel-border` | `neutral_border` |
| `header_bg` | `--header-bg` | `primary` |
| `header_text` | `--header-text` | `on_primary`, then `#ffffff` |

## How to add a new layout

1. Pick a name and add it to `DesignSystem.LAYOUTS` (and, if it should be
   the default, `DesignSystem.DEFAULT_LAYOUT`) in
   `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py`.
2. Add `layout-<name>.css` next to the existing `layout-report.css` /
   `layout-analytics.css` / `layout-print.css`, scoped under
   `.ds-page[data-layout="<name>"] ...` so it never leaks into the other
   layouts. Register it in the module-level `_LAYOUT_CSS` dict.
3. It ships automatically once packaged — no new
   `package-data` entry needed (the existing entry is a glob, `*.css`).
4. Add the new pair to `test_design_system.py`'s
   `test_all_theme_layout_pairs_compose` (all 5 themes × the new layout)
   and to the self-containment / `<meta viewport>` /
   `div.ds-page[data-layout][data-theme]` assertions in
   `test_interactive_html.py` / `test_document_shell.py` if the layout
   introduces new structural markup.
5. If the layout targets print (WeasyPrint), read
   `docs/weasyprint-css-support.md` first — several modern CSS features
   used elsewhere in this design system (`auto-fit` grids, `position:
   sticky`, `box-shadow`) are empirically unsupported by WeasyPrint 69.0
   and must be avoided or explicitly overridden in the new layout's CSS.

## FilterBar (the one net-new catalog component)

`FilterBar` (`parrot/outputs/a2ui/catalog/parrot/filterbar.py`, TASK-2715)
is the only net-new A2UI catalog vocabulary this feature adds. It lowers to
a `Row` tagged `parrot_variant: "filter-bar"` of `ChoicePicker` filters
(`parrot_role: "filter"`, `parrot_filter_column: "<column>"`).
`interactive-html` renders it as a searchable multiselect per filter and
wires a dependency-free client-side runtime that filters the surface's own
already-embedded `dataModel` (never a server round-trip — that is
FEAT-491's `refresh_dashboard` lane, unrelated). `ssr-html`/`pdf` degrade it
to a static filter-state summary line plus a `degradation_record`, never a
non-functional control.

## Related documents

- `docs/weasyprint-css-support.md` — empirical CSS-support findings for the
  `print` layout / PDF surface.
- `sdd/specs/html-renderer-design-system.spec.md` — the full FEAT-493 spec
  (architecture, module breakdown, acceptance criteria, codebase contract).
