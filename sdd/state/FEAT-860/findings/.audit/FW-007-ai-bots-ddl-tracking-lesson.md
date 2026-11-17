---
id: FW-007
query_id: Q004
type: wiki_page
intent: "Read the recorded lesson on keeping navigator.ai_bots DDL in sync with BotModel."
executed_at: 2026-11-09T17:13:16Z
duration_ms: 150
parent_id: FW-005
depth: 1
---

# FW-007 — Lesson: a strict asyncdb model fails every load when a declared column is missing from the table

## Summary

Memory `mem-65f89185cb0d` (lesson, 2026-10-21): navigator.ai_bots is documented in three places that must
track `parrot.models.bots.BotModel` field-for-field (BotModel docstring, creation.sql,
`sdd/migrations/botmodel-recreate-table.sql`). BotModel has `Meta.strict=True`, so asyncdb SELECTs every
declared field by name and one missing column broke every bot load (`column "toolkit_config" does not exist`).
creation.sql and the BotModel DDL are frozen by the FEAT-621 AC17 gate; deliberate edits go through
`_SANCTIONED_REWRITES`.

## Citations

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  symbol: `BotModel`
  excerpt: |
    mem-65f89185cb0d: "BotModel has Meta.strict=True, so asyncdb SELECTs every declared field by name and ANY
    missing column fails every bot load"
- path: `sdd/migrations/botmodel-recreate-table.sql`
  excerpt: |
    third documented DDL site for navigator.ai_bots

## Notes

Design implication for crew_definitions: storing the CrewDefinition as one JSONB document (plus a few indexed
identity columns) avoids per-field column drift — CrewDefinition evolves often (FW-002 `_strip_unknown_keys`),
and a column-per-field table would reproduce the ai_bots drift problem.
