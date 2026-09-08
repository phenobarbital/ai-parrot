# Vendored Third-Party Assets — License Manifest

These files are static, committed copies of the exact default external
resources `folium==0.20.0` (and `folium.plugins.MarkerCluster`) reference by
default, vendored offline so the `interactive-html`/`folium-map` A2UI
renderers can produce a genuinely self-contained document with zero runtime
CDN fetches (FEAT-522). They are **not** pip dependencies — they ship as
static `package-data` in `ai-parrot-visualizations`'s wheel, the same
mechanism already used for `chart.umd.min.js` / `echarts.min.js`.

None of these files were hand-edited; each is byte-identical to the upstream
CDN resource it was fetched from at vendoring time (2026-09-03).

| File | Project | Version | License | Source URL |
|---|---|---|---|---|
| `leaflet-1.9.3.js` | [Leaflet](https://leafletjs.com/) | 1.9.3 | BSD-2-Clause | https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js |
| `leaflet-1.9.3.css` | [Leaflet](https://leafletjs.com/) | 1.9.3 | BSD-2-Clause | https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css |
| `jquery-3.7.1.min.js` | [jQuery](https://jquery.com/) | 3.7.1 | MIT | https://code.jquery.com/jquery-3.7.1.min.js |
| `bootstrap-5.2.2.bundle.min.js` | [Bootstrap](https://getbootstrap.com/) | 5.2.2 | MIT | https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js |
| `bootstrap-5.2.2.min.css` | [Bootstrap](https://getbootstrap.com/) | 5.2.2 | MIT | https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/css/bootstrap.min.css |
| `bootstrap-glyphicons-3.0.0.css` | Bootstrap Glyphicons (folium's own pinned URL) | 3.0.0 | MIT | https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css |
| `fontawesome-free-6.2.0.min.css` | [Font Awesome Free](https://fontawesome.com/) | 6.2.0 | MIT (icons: CC-BY-4.0, fonts: SIL-OFL-1.1) | https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css |
| `leaflet-awesome-markers-2.0.2.js` | [Leaflet.awesome-markers](https://github.com/lennardv2/Leaflet.awesome-markers) | 2.0.2 | MIT | https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js |
| `leaflet-awesome-markers-2.0.2.css` | [Leaflet.awesome-markers](https://github.com/lennardv2/Leaflet.awesome-markers) | 2.0.2 | MIT | https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css |
| `leaflet-awesome-rotate.min.css` | [folium](https://python-visualization.github.io/folium/) template asset (`leaflet.awesome.rotate.css`) | matches folium 0.20.0 | MIT (folium's own license) | https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/leaflet.awesome.rotate.min.css |
| `leaflet-markercluster-1.1.0.js` | [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) | 1.1.0 | MIT | https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/leaflet.markercluster.js |
| `MarkerCluster-1.1.0.css` | [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) | 1.1.0 | MIT | https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.css |
| `MarkerCluster.Default-1.1.0.css` | [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) | 1.1.0 | MIT | https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.Default.css |

## Provenance / drift note

These are the exact pins `folium==0.20.0` references by default via its
`JSCSSMixin.default_js` / `default_css` class attributes (`folium.Map()`)
and `folium.plugins.MarkerCluster()`'s own defaults. If a future `folium`
upgrade changes these names/URLs/versions, `scripts/generate_a2ui_css.py
--check` (FEAT-522, Module 6) introspects the *installed* `folium` package
live and fails CI if the vendored asset set has fallen out of sync — see
`_map_vendor.py`'s `VENDORED_ASSET_PATHS` mapping.
