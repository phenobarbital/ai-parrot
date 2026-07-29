---
id: F006
query_id: Q007
type: grep
intent: Toolkit conventions across parrot
executed_at: 2026-07-13T22:42:00Z
parent_id: null
depth: 0
---

# F006 — Existing AbstractToolkit subclasses (conventions)

## Summary

16 `AbstractToolkit` subclasses exist. Single-file toolkits live directly in
parrot/tools/ (e.g. `openapitoolkit.py`, `excel_intelligence.py`,
`reminder.py`, `infographic_toolkit.py`); multi-file ones get a package dir
(`databasequery/toolkit.py`, `working_memory/tool.py`, `dataset_manager/`).
Naming: `<Thing>Toolkit`. A grep for "company" (case-insensitive) across
parrot/tools/ returned **zero files** — no existing company-research
capability; this is greenfield inside parrot.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py`
  lines: 45
  symbol: `OpenAPIToolkit`
- path: `packages/ai-parrot/src/parrot/tools/excel_intelligence.py`
  lines: 18
  symbol: `ExcelIntelligenceToolkit`
- path: `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py`
  lines: 115
  symbol: `DatabaseQueryToolkit`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 44
  symbol: `WorkingMemoryToolkit`
- path: `packages/ai-parrot/src/parrot/tools/reminder.py`
  lines: 158
  symbol: `ReminderToolkit`

## Notes

Absence evidence: `grep -rlin 'company' packages/ai-parrot/src/parrot/tools/`
→ no matches.
