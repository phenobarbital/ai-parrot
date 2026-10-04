---
id: F003
query_id: Q003
type: read
intent: runtime environment facts
executed_at: 2026-09-28T20:32:00Z
parent_id: null
depth: 0
---
# F003 — Env facts that contradict FEAT-610 findings

## Summary
Installed querysource is 4.5.11 (no tenants, no /api/v1/{tenant}/queries, no JSONB @>). QS_PBAC_ENABLED absent from env files (defaults False). env/.env points DB at production RDS (navigator_production, ENV=production); staging exists at env/staging/.env. Any slug seed = production write unless targeted at staging.

## Citations
- path: `venv:querysource-4.5.11.dist-info`
- path: `venv:querysource/queries/qs.py`
  lines: 42-56
- path: `venv:querysource/conf.py`
  lines: 429
- path: `env/.env`
  lines: 20-22, 124, 394-395
- path: `env/staging/.env`
  lines: 20-23
- path: `packages/ai-parrot/pyproject.toml`
  lines: 225, 688
- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 77
