"""Name -> locally-vendored-file mapping for folium's default CDN resources
(FEAT-522, TASK-2785).

``folium.Map()`` and ``folium.plugins.MarkerCluster()`` both declare their
own default external JS/CSS resources via ``JSCSSMixin.default_js`` /
``default_css`` (class-level ``list[tuple[name, url]]`` attributes — see
``folium_map.py``'s module docstring / spec §2 "Why not
`folium.Map.add_js_link()`/`.add_css_link()`" for why this feature does not
mutate those lists directly).

This module provides the static, read-once-at-import-time lookup table from
each ``(name, cdn_url)`` pair's ``name`` to the local vendored copy of that
exact file, living flat in ``formats/assets/`` (same placement convention as
``chart.umd.min.js`` / ``echarts.min.js`` — see ``interactive_html.py:140-148``
for the precedent this mirrors).

This module intentionally does NOT read file *contents* or build any
``data:`` URIs — that is TASK-2787's job
(``folium_map.build_map_document()``'s offline data-URI swap). This module
only maps ``name -> Path``.
"""
from __future__ import annotations

from pathlib import Path

#: Same directory `_CHART_JS_PATH` resolves into
#: (`interactive_html.py:140-141`) — flat `formats/assets/`, shared by all
#: vendored JS/CSS bundles in this package.
_ASSETS_DIR = Path(__file__).parent.parent / "formats" / "assets"

#: Maps every `name` folium.Map()`/`folium.plugins.MarkerCluster()` declare
#: in their `default_js`/`default_css` class attributes (verified live
#: against the installed `folium==0.20.0`, spec §6 "Verified Live
#: Behavior") to its locally vendored file path.
#:
#: 5 JS-track names (4 `folium.Map` + 1 `MarkerCluster`) + 8 CSS-track names
#: (6 `folium.Map` + 2 `MarkerCluster`) = 13 total, matching the 13 vendored
#: files this task adds to `formats/assets/`.
VENDORED_ASSET_PATHS: dict[str, Path] = {
    # folium.Map().default_js
    "leaflet": _ASSETS_DIR / "leaflet-1.9.3.js",
    "jquery": _ASSETS_DIR / "jquery-3.7.1.min.js",
    "bootstrap": _ASSETS_DIR / "bootstrap-5.2.2.bundle.min.js",
    "awesome_markers": _ASSETS_DIR / "leaflet-awesome-markers-2.0.2.js",
    # folium.Map().default_css
    "leaflet_css": _ASSETS_DIR / "leaflet-1.9.3.css",
    "bootstrap_css": _ASSETS_DIR / "bootstrap-5.2.2.min.css",
    "glyphicons_css": _ASSETS_DIR / "bootstrap-glyphicons-3.0.0.css",
    "awesome_markers_font_css": _ASSETS_DIR / "fontawesome-free-6.2.0.min.css",
    "awesome_markers_css": _ASSETS_DIR / "leaflet-awesome-markers-2.0.2.css",
    "awesome_rotate_css": _ASSETS_DIR / "leaflet-awesome-rotate.min.css",
    # folium.plugins.MarkerCluster().default_js
    "markerclusterjs": _ASSETS_DIR / "leaflet-markercluster-1.1.0.js",
    # folium.plugins.MarkerCluster().default_css
    "markerclustercss": _ASSETS_DIR / "MarkerCluster-1.1.0.css",
    "markerclusterdefaultcss": _ASSETS_DIR / "MarkerCluster.Default-1.1.0.css",
}
