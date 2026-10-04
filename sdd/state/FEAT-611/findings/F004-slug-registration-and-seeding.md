---
id: F004
query_id: Q003
type: read
intent: slug registration and idempotent seeding
executed_at: 2026-09-28T20:32:00Z
parent_id: null
depth: 0
---
# F004 — Slugs only via QueryModel (public.queries); 3 seeding paths

## Summary
Lookup is always QueryModel.get(query_slug=) on Postgres; SLUG_CACHE never read. Seed options: SQL upsert on public.queries; PUT /api/v1/management/queries/{slug}; SlugCatalog.upsert via QuerysourceToolkit.save_multiquery(allow_write=True) (multiquery rows only).

## Citations
- path: `venv:querysource/interfaces/connections.py`
  lines: 47, 444-466
- path: `venv:querysource/models.py`
  lines: 48-104
  symbol: QueryModel
- path: `venv:querysource/handlers/manager.py`
  lines: 397-441
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py`
  lines: 275-308
  symbol: `SlugCatalog.upsert`
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 605-620
  symbol: save_multiquery
