---
id: F012
query_id: Q029
type: grep
intent: Existing Spanish tax knowledge (AEAT/IVA/IRPF/deducible) and BBVA parsing in the repo.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F012 — No AEAT deductibility logic or BBVA parser exists in code; both live only in the unimplemented Spec A and its brainstorm

## Summary

grep `AEAT|deducib|IRPF` over `packages/**/*.py`: 2 hits, both `parrot/scheduler/inprocess.py` (tax-calendar reminder strings from FEAT-453 Module 8) — no rule table, no taxonomy. grep `BBVA` repo-wide: only `sdd/specs/auto-finance-toolkit.spec.md` (G2, Module 2, `parse_bank_excel(path, bank="bbva")`, fixture `tests/finance/anonymize_bbva.py`) and the brainstorm (user confirmed fixtures come from BBVA Excel + Norma 43; anonymization required before committing). Therefore the "normativa vigente ... para autónomos" mapping must be designed fresh or lifted from Spec A's `AeatRule` table (F005).

## Citations


- path: `packages/ai-parrot/src/parrot/scheduler/inprocess.py`
  lines: 1-1
  symbol: `tax-calendar strings`
  excerpt: |
    (only AEAT mention in packages/*.py)

- path: `sdd/specs/auto-finance-toolkit.spec.md`
  lines: 44, 88, 265, 368, 402
  symbol: `BBVA references`
  excerpt: |
    G2 Excel (BBVA layout first); locate the transaction table in BBVA workbooks (preamble rows); test_parse_bbva_excel_layout; bbva_xlsx fixture (script: tests/finance/anonymize_bbva.py)

- path: `sdd/proposals/auto-finance-agent.brainstorm.md`
  lines: 592
  symbol: `resolved question`
  excerpt: |
    Which bank(s) produce the real Excel/N43 fixtures? — BBVA (Excel + Norma 43). Anonymization script required before committing fixtures.
