---
id: F016
query_id: Q016
type: wiki_query
intent: FEAT-578 stores ADRs in the main wiki.db by category (DecisionRepository) — the Option A precedent
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F016 — FEAT-578 stores ADRs in the main wiki.db by category (DecisionRepository) — the Option A precedent

## Summary

decisions/repository.py DecisionRepository.inventory 'Load the complete bounded ADR inventory' (score 1.00); module doc 'Store-facing persistence for ADR records (FEAT-578 Module 2)'. Confirms both precedents exist: same-store category (decisions) vs own-db overlay (ledger).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py`
  lines: -
  symbol: `DecisionRepository.inventory`
  excerpt: |
    Store-facing persistence for ADR records (FEAT-578 Module 2).
