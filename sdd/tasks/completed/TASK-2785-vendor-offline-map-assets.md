# TASK-2785: Vendor offline map assets (Leaflet/jQuery/Bootstrap/MarkerCluster) + license manifest

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview / §6 "Verified Live Behavior": `folium.Map()` (installed
`folium==0.20.0`) unconditionally emits external `<script src=`/`<link href=`
references to Leaflet, jQuery, Bootstrap, Font Awesome, and Leaflet.awesome-markers
— even for a Map with zero plugins — via its `JSCSSMixin.default_js`/`default_css`
class attributes. `folium.plugins.MarkerCluster` (which this feature requires,
spec §8 resolved decision: threshold 500) adds one more JS + two more CSS
resources. This task provides the local, static copies of every one of those
files so a later task (TASK-2787) can swap the CDN URLs for inlined `data:` URIs
— the mechanism spec §2 chose after discovering that HTML-escaping inside an
`iframe srcdoc` hides the CDN fetch from the existing guardrail test
(`test_document_shell.py:44-46`) without actually eliminating it.

This task is a pure asset-addition task: no renderer code changes.

## Scope

- Download and vendor the exact pinned versions `folium==0.20.0` currently
  references as its own defaults (verified live, spec §6 "Verified Live Behavior"):
  - `leaflet@1.9.3`: `leaflet.js`, `leaflet.css`
  - `jquery-3.7.1`: `jquery.min.js`
  - `bootstrap@5.2.2`: `bootstrap.bundle.min.js`, `bootstrap.min.css`
  - `bootstrap-glyphicons` (folium's own pinned URL, version `3.0.0`):
    `bootstrap-glyphicons.css`
  - `@fortawesome/fontawesome-free@6.2.0`: `fontawesome.all.min.css`
  - `Leaflet.awesome-markers@2.0.2`: `leaflet.awesome-markers.js`,
    `leaflet.awesome-markers.css`
  - folium's own `leaflet.awesome.rotate.min.css` template asset
  - `leaflet.markercluster@1.1.0`: `leaflet.markercluster.js`,
    `MarkerCluster.css`, `MarkerCluster.Default.css`
  - Total: 13 files (5 JS-or-equivalent, 8 CSS).
- Place all 13 files flat inside
  `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/` — the
  SAME directory as the existing `chart.umd.min.js`/`echarts.min.js` (matches the
  documented placement convention at `interactive_html.py:140-141`: "Shares the
  `formats/assets/` placement convention with the vendored ECharts bundle").
  Use exactly the filenames a later task will reference — pick clear, unambiguous
  names, e.g. `leaflet-1.9.3.js`, `leaflet-1.9.3.css`, `jquery-3.7.1.min.js`,
  `bootstrap-5.2.2.bundle.min.js`, `bootstrap-5.2.2.min.css`,
  `bootstrap-glyphicons-3.0.0.css`, `fontawesome-free-6.2.0.min.css`,
  `leaflet-awesome-markers-2.0.2.js`, `leaflet-awesome-markers-2.0.2.css`,
  `leaflet-awesome-rotate.min.css`, `leaflet-markercluster-1.1.0.js`,
  `MarkerCluster-1.1.0.css`, `MarkerCluster.Default-1.1.0.css`.
- Update `packages/ai-parrot-visualizations/pyproject.toml`'s
  `[tool.setuptools.package-data]` entry for
  `"parrot.outputs.formats.assets"` from `["*.js"]` to `["*.js", "*.css"]` (the
  existing `design_system` sub-entry already covers `*.css` for ITS own
  subdirectory — this is a separate, sibling entry for the flat `formats/assets/`
  directory, which today only globs `*.js`).
- Add a lightweight license manifest,
  `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/VENDORED_LICENSES.md`,
  listing each vendored file, its upstream project, pinned version, and license
  (all permissive — Leaflet BSD-2-Clause, jQuery MIT, Bootstrap MIT, Font Awesome
  Free MIT/OFL-1.1/CC-BY-4.0, Leaflet.awesome-markers MIT, Leaflet.markercluster
  MIT) — resolves spec §8's remaining open question ("pick the lightest
  convention that satisfies a license audit").
- Build a single Python mapping module, `_map_vendor.py`, in the same
  `a2ui_renderers/` package as `folium_map.py`, that maps each folium
  `(name, cdn_url)` pair to its locally vendored file path — this is the lookup
  table TASK-2787 will consume. Do NOT implement the actual data-URI swap logic
  here (that's TASK-2787) — this task only provides the static files and the
  name→local-path mapping.

**NOT in scope**:
- Reading/inlining the vendored files into `data:` URIs (TASK-2787).
- Any change to `folium_map.py`'s `render()` or the new `build_map_document()`
  (TASK-2786/2787).
- Any change to `interactive_html.py` (TASK-2788).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/leaflet-1.9.3.js` | CREATE | Vendored Leaflet JS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/leaflet-1.9.3.css` | CREATE | Vendored Leaflet CSS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/jquery-3.7.1.min.js` | CREATE | Vendored jQuery |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/bootstrap-5.2.2.bundle.min.js` | CREATE | Vendored Bootstrap JS bundle |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/bootstrap-5.2.2.min.css` | CREATE | Vendored Bootstrap CSS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/bootstrap-glyphicons-3.0.0.css` | CREATE | Vendored Bootstrap Glyphicons CSS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/fontawesome-free-6.2.0.min.css` | CREATE | Vendored Font Awesome CSS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/leaflet-awesome-markers-2.0.2.js` | CREATE | Vendored awesome-markers JS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/leaflet-awesome-markers-2.0.2.css` | CREATE | Vendored awesome-markers CSS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/leaflet-awesome-rotate.min.css` | CREATE | Vendored folium template asset |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/leaflet-markercluster-1.1.0.js` | CREATE | Vendored MarkerCluster JS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/MarkerCluster-1.1.0.css` | CREATE | Vendored MarkerCluster CSS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/MarkerCluster.Default-1.1.0.css` | CREATE | Vendored MarkerCluster default-theme CSS |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/VENDORED_LICENSES.md` | CREATE | License manifest |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_map_vendor.py` | CREATE | `(name, cdn_url) -> local file path` mapping table |
| `packages/ai-parrot-visualizations/pyproject.toml` | MODIFY | `package-data` glob `["*.js"]` → `["*.js", "*.css"]` for `parrot.outputs.formats.assets` |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing precedent to mirror — packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:140-148
from pathlib import Path
_CHART_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "chart.umd.min.js"
_CHART_JS_SOURCE = _CHART_JS_PATH.read_text(encoding="utf-8")  # read ONCE at import time
```

### Existing Signatures to Use
```python
# folium==0.20.0 (installed) — verified live at spec time via:
#   python -c "import folium; m = folium.Map(); print(m.default_js); print(m.default_css)"
#   python -c "import folium.plugins as fp; mc = fp.MarkerCluster(); print(mc.default_js); print(mc.default_css)"
#
# folium.Map().default_js  (name, url):
#   ("leaflet", "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js")
#   ("jquery", "https://code.jquery.com/jquery-3.7.1.min.js")
#   ("bootstrap", "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js")
#   ("awesome_markers", "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js")
#
# folium.Map().default_css  (name, url):
#   ("leaflet_css", "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css")
#   ("bootstrap_css", "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/css/bootstrap.min.css")
#   ("glyphicons_css", "https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css")
#   ("awesome_markers_font_css", "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css")
#   ("awesome_markers_css", "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css")
#   ("awesome_rotate_css", "https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/leaflet.awesome.rotate.min.css")
#
# folium.plugins.MarkerCluster().default_js:
#   ("markerclusterjs", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/leaflet.markercluster.js")
#
# folium.plugins.MarkerCluster().default_css:
#   ("markerclustercss", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.css")
#   ("markerclusterdefaultcss", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.Default.css")

# packages/ai-parrot-visualizations/pyproject.toml (existing, line ~78-80)
# [tool.setuptools.package-data]
# "parrot.outputs.formats.assets" = ["*.js"]
# "parrot.outputs.formats.assets.design_system" = ["*.css"]
```

### Does NOT Exist
- ~~`folium.Map(offline=True)` or any built-in vendoring mode~~ — does not exist;
  this task's manual vendoring is the only path (spec §6 "Does NOT Exist").
- ~~An existing `formats/assets/` subdirectory for map/Leaflet vendor files~~ — the
  directory today only holds `chart.umd.min.js`, `echarts.min.js`, `__init__.py`,
  and the `design_system/` subpackage. This task adds the new files flat into
  that same directory, not a new subdirectory.

---

## Implementation Notes

### Pattern to Follow
Match `_CHART_JS_PATH`/`_CHART_JS_SOURCE`'s "read once at import time" shape for
`_map_vendor.py`'s mapping table — a plain module-level `dict[str, Path]` or
similar, resolved relative to `Path(__file__).parent.parent / "formats" / "assets"`.
Do NOT read file contents in this task's module (that belongs to TASK-2787's
data-URI construction) — just the name→path mapping.

### Key Constraints
- Do not introduce a new pip dependency to fetch these files at install or
  build time — vendor them as static, committed files (same as
  `chart.umd.min.js` today), not downloaded during CI/build.
- Keep exact upstream file content (minified where the upstream project ships
  minified — e.g. `.min.js`/`.min.css`) — do not hand-edit vendored files.
- `VENDORED_LICENSES.md` must name each file, its upstream project + exact
  pinned version + license + source URL it was fetched from.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:140-148` — vendoring/read-once pattern to mirror.
- `packages/ai-parrot-visualizations/pyproject.toml` — package-data glob to extend.

---

## Acceptance Criteria

- [ ] All 13 vendored files exist at the paths listed above, each matching its
  pinned upstream version's content exactly.
- [ ] `VENDORED_LICENSES.md` lists all 13 files with upstream project, version,
  license, and source URL.
- [ ] `packages/ai-parrot-visualizations/pyproject.toml`'s package-data entry
  for `parrot.outputs.formats.assets` includes `"*.css"`.
- [ ] `_map_vendor.py` exposes a mapping from each of the 8 verified
  `(name, cdn_url)` pairs (5 JS-track, wait — verify exact count: 4 Map JS + 1
  MarkerCluster JS = 5 JS names; 6 Map CSS + 2 MarkerCluster CSS = 8 CSS names;
  13 total) to its local vendored file path.
- [ ] `uv build` (or `python -m build`) for `ai-parrot-visualizations` includes
  all 13 new files in the built wheel (verify via `unzip -l` on the built wheel
  or `python -c "import parrot.outputs.formats.assets"` package inspection).
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_map_vendor.py`

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_map_vendor.py
import pytest
from parrot.outputs.a2ui_renderers._map_vendor import VENDORED_ASSET_PATHS


class TestMapVendor:
    def test_all_folium_default_resources_have_a_vendored_path(self):
        """Every (name, url) pair folium.Map()/MarkerCluster() declare by
        default has a corresponding local vendored file path."""
        import folium
        import folium.plugins as fp

        m = folium.Map()
        mc = fp.MarkerCluster()
        all_names = {n for n, _ in m.default_js} | {n for n, _ in m.default_css}
        all_names |= {n for n, _ in mc.default_js} | {n for n, _ in mc.default_css}
        assert all_names <= set(VENDORED_ASSET_PATHS)

    def test_vendored_files_exist_on_disk(self):
        for path in VENDORED_ASSET_PATHS.values():
            assert path.exists(), f"missing vendored asset: {path}"
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` for full
   context (§1 Motivation, §2 Overview, §6 "Verified Live Behavior", §7 Known
   Risks "folium version drift").
2. No dependencies — start immediately.
3. Verify the Codebase Contract's `(name, url)` pairs are still accurate by
   re-running the `python -c "import folium; ..."` inspection commands listed
   above against the currently-installed `folium` version before vendoring —
   if the installed version has drifted from `0.20.0`, use the CURRENTLY
   installed version's actual pins, not the ones recorded here.
4. Update status in the per-spec index → `"in-progress"`.
5. Implement per scope.
6. Verify all acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update the per-spec index → `"done"`.
9. Fill in the Completion Note below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-09-03
**Notes**: Re-verified the installed `folium==0.20.0` `default_js`/`default_css`
pairs live (matched the Codebase Contract exactly). Downloaded all 13 vendored
files from their exact upstream CDN URLs into `formats/assets/`, added
`VENDORED_LICENSES.md`, added `_map_vendor.py`'s `VENDORED_ASSET_PATHS`
name→path mapping, and extended `pyproject.toml`'s package-data glob from
`["*.js"]` to `["*.js", "*.css"]` for `parrot.outputs.formats.assets`.
Verified via `python -m build --wheel` that all 13 files land in the built
wheel. `ruff check` clean; both tests in `test_map_vendor.py` pass.

**Deviations from spec**: none
