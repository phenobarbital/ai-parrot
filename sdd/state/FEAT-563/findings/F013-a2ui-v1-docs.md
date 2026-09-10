---
id: F013
query_id: Q013
type: read
intent: A2UI v1.0 docs
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F013 — docs/outputs/a2ui-v1.md — catalogs, extensions, validation, renderers

## Summary

Three catalogs: Basic (official, `https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json`), Parrot (`https://parrot.dev/catalogs/v1`: InfoCard, Chart, DataTable, Map, KPICard, Timeline, Infographic, Report, +HtmlDocument), viz-core. Parrot components implement `lower()` to Basic primitives. Presentation semantics go in `metadata.extensions.parrot_*` (e.g. `parrot_role`, `parrot_variant`, `parrot_component_id`) — never bare top-level props. `validate_envelope(origin=LLM)` rejects any `action`; TOOL origin allows it. Six visualization renderers declare `RendererCapabilities.supported_components` and degrade unknown components to a `Text` placeholder with a `degraded` record.

## Citations

- path: `docs/outputs/a2ui-v1.md`
  lines: 73-99
- path: `docs/outputs/a2ui-v1.md`
  lines: 140-158
  excerpt: |
    | `parrot_role` | Presentation role of a lowered `Text` ...
    | `parrot_variant` | Which Parrot component a lowered `Card` stands in for ...
- path: `docs/outputs/a2ui-v1.md`
  lines: 170-192
- path: `docs/outputs/a2ui-v1.md`
  lines: 206-218
