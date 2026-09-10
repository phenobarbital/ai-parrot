---
id: F017
query_id: Q017
type: grep
intent: Catalog registration and validation
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F017 — catalog/__init__.py — register_component, resolve_catalog, validate_envelope; export.py

## Summary

`register_component(..., requires_actions=False)` registers Parrot/viz-core components; `resolve_catalog()` prefers component `catalogId`, else the surface default; `validate_envelope(envelope, origin, surface_catalog_id)` enforces exactly-one-root, known components and the D10b action gate (`ProducerOrigin.LLM` may not carry `action`/`requires_actions`); `validate_message` runs jsonschema. `export_catalog_definition()` emits a catalog document with Basic `$ref`s.

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py`
  lines: 111-180
  symbol: `register_component`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py`
  lines: 342
  symbol: `resolve_catalog`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py`
  lines: 455-520
  symbol: `validate_message / validate_envelope`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py`
  lines: 89-95
  symbol: `ProducerOrigin`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py`
  lines: 215-250
  symbol: `export_catalog_definition`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/producer.py`
  lines: 255
