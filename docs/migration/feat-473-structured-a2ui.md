# Migration — FEAT-473: A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP

**Feature**: FEAT-473
**Status**: merged (target version: 0.30.0)
**Affects**: any consumer of `OutputMode.STRUCTURED_CHART` /
`STRUCTURED_TABLE` / `STRUCTURED_MAP` responses — frontends, BFFs, and
anything persisting `response.artifacts[]`.
**Depends on**: FEAT-470 (`a2ui-v1-dialect`).
**Related**: FEAT-215/218/221 (structured chart/table/map), FEAT-224
(structured `artifacts[]` envelope v1), FEAT-273 (A2UI core).

## What changed

STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP responses now
**additionally** carry a spec-conformant [A2UI v1.0](https://a2ui.org/specification/v1_0)
`CreateSurface` envelope, built **deterministically** (zero LLM calls) by a
new core adapter (`parrot.outputs.a2ui.adapters.structured`). This is a
**dual-emit**, not a replacement: the existing `response.output` /
`response.data` contract (FEAT-215/218/221/223) is unchanged except for one
additive key.

This closes the gap the FEAT-273 A2UI rollout left open: `OutputMode.A2UI`
existed with `Chart`/`DataTable`/`Map` catalog components, but the
deterministic structured-output path (the one `PandasAgent`/`DatabaseAgent`
actually use) never produced an A2UI envelope. It does now.

## What did NOT change

- `response.output` — same shape, **plus one additive key**: `surfaceId`.
- `response.data` — unchanged (still full rows / per-layer payloads).
- The three config models (`StructuredChartConfig`, `StructuredTableConfig`,
  `StructuredMapConfig`) — no field changes, no renames.
- Public `render()` signatures on `StructuredChartRenderer` /
  `StructuredTableRenderer` / `StructuredMapRenderer`.
- `Map.lower()` — still a titled layer summary (no GeoJSON-rich lowering).
- No new hard dependencies (`jsonschema`/`jsonpointer`/`folium` were already
  required by FEAT-470).

## v1 → v2 `artifacts[]` diff

```diff
 {
   "type": "chart",
   "artifactId": "structured_chart-a1b2c3d4",
+  "surfaceId": "structured_chart-a1b2c3d4",
+  "schemaVersion": 2,
   "definition": {
-    "type": "bar",
-    "x": "month",
-    "y": ["sales"],
-    "title": "Monthly Sales"
+    "id": "root",
+    "component": "Chart",
+    "catalogId": "https://parrot.dev/catalogs/v1",
+    "type": "bar",
+    "x": "month",
+    "y": ["sales"],
+    "title": "Monthly Sales",
+    "data": { "path": "/rows" }
   }
 }
```

Key differences:

1. **`surfaceId`** (new) — equals `artifactId` and `response.artifact_id`.
2. **`schemaVersion: 2`** (new) — discriminates v2 from v1 (absent, or `1`).
3. **`definition`** changes SHAPE: it is now a v1.0 wire `Component` node
   (`id`, `component`, `catalogId`, config props top-level camelCase, `data`
   as a `{"path": ...}` binding) instead of a bare camelCase config dict. The
   config *values* are identical — only the envelope around them changed.

A new top-level `response.a2ui_envelope` also appears for these three modes:

```json
{"version": "v1.0", "createSurface": {"surfaceId": "...", "components": [...], "dataModel": {...}}}
```

See the [frontend guide §2.6](../frontend/structured-artifacts-frontend-guide.md#26-envelope-a2ui-v10-feat-473--dual-emit)
for the full contract, consumption examples, and validated payload samples.

## Shim window: 0.30 → 0.32

A consumer cushion (G6) is available for anyone not ready to consume v2
immediately:

```python
from parrot.outputs.a2ui.compat import is_legacy_artifact, artifact_definition_to_legacy

for entry in response.artifacts:
    v1_definition = (
        entry["definition"] if is_legacy_artifact(entry)
        else artifact_definition_to_legacy(entry)
    )
```

| Version | Status |
|---|---|
| **0.30** (this feature) | v2 introduced; shim available |
| **0.31** | shim still supported |
| **0.32** | shim **removed** — v2 becomes the only shape |

Migrate any code reading `artifacts[].definition` directly (assuming the v1
bare-dict shape) to either read through the shim, or read the v2 Component
node's top-level props directly (they are the same config values).

## Code changes required

**None**, if you only read `response.output` / `response.data` (unchanged
contract) and ignore `response.a2ui_envelope` / the new `artifacts[]` keys.

**If you persist or re-serve `artifacts[].definition` assuming the v1
shape**: wrap reads with `artifact_definition_to_legacy()` (above) before
0.32, then migrate to the v2 Component-node shape.

**If you want the new capabilities** (external A2UI renderers, PDF/SSR
delivery, Adaptive Cards for Teams, deep-link degradation, richer chart/map
styling): consume `response.a2ui_envelope` directly — see the frontend guide.

## New renderer capabilities (G7)

Satellite `echarts`/`folium_map` A2UI renderers now honour props that were
previously silently ignored when reached via the A2UI path:

- **ECharts**: `stacked`, `splitSeries`, `trendline`, `colorBySign` (+
  `negativeColor`/`positiveColor`), `xAxisLabel`/`yAxisLabel`, `palette`.
- **Folium**: multi-layer maps (`Map.layers[]` with per-layer `data`),
  `markerColor`, `tooltipTemplate`, `labelField`, `geodesic` (rendered as a
  straight polyline — no great-circle curve plugin vendored).

Envelopes without these props render exactly as before (regression-safe
defaults).

## Anti-hallucination guard (G8)

`validate_envelope(origin=LLM)` now rejects an inline `data` (or `datasets`)
row list on `Chart`/`DataTable`/`Map` — LLM-produced envelopes for these
components must use a `{"path": ...}` binding. `origin=TOOL` (this
feature's own deterministic adapter) is exempt and may inline rows/features
directly into the data model.
