---
id: F005
query_id: Q005
type: wiki_query
intent: Orient: AutoFinanceToolkit spec (Spec A) and the deferred Spec B.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — Spec A (FEAT-478) is approved on paper but never decomposed; it defines the DeductibilityVerdict/AeatRule contracts Spec B was meant to consume

## Summary

`sdd/specs/auto-finance-toolkit.spec.md` is **FEAT-478** with goals G2 (BBVA Excel layout first + Norma 43), G6 (AEAT deductibility as a data-driven rule table producing drafts only; "filing to Hooba is Spec B / hooba-service-toolkit"). `sdd/tasks/index/` has **no** auto-finance index (Q033 glob: only finance-reporter-tier2-narrative, web-automation-fixture-site-tests, web-automation-infra) → nothing of Spec A is implemented; `parrot_tools/finance/` parse_bank_excel / AeatRule / taxonomy_es_autonomo_v1.yaml do not exist. The spec explicitly plans Module 2 `parse_bank_excel` to locate the transaction table in BBVA workbooks (preamble rows).

## Citations


- path: `sdd/specs/auto-finance-toolkit.spec.md`
  lines: 11, 41-62
  symbol: `FEAT-478 goals`
  excerpt: |
    **Feature ID**: FEAT-478 ... G2. Idempotent statement ingestion for **Excel (BBVA layout first)** ... G6. AEAT deductibility as a data-driven rule table producing **drafts only** (human approves; filing to Hooba is Spec B / `hooba-service-toolkit`).

- path: `sdd/specs/auto-finance-toolkit.spec.md`
  lines: 196-209
  symbol: `DeductibilityVerdict, AeatRule`
  excerpt: |
    class DeductibilityVerdict(BaseModel):   # drafts consumed by Spec B
        draft_id: str; txn_id: str; rule_id: str
        deductible_pct: Decimal; capped_amount: Decimal | None
        legal_basis: str; invoice_required: bool
        status: Literal["draft", "approved", "rejected", "registered"]
    class AeatRule(BaseModel): rule_id; matcher: RuleMatcher; deductible_pct; annual_cap; requires_exclusive_use; invoice_required; legal_basis

- path: `sdd/specs/auto-finance-toolkit.spec.md`
  lines: 265, 298-303
  symbol: `parse_bank_excel / Module 2`
  excerpt: |
    async def parse_bank_excel(self, path: str, bank: str = "bbva") -> dict: ...   # → {statement_id, rows, skipped, digest}
    ### Module 2: Ingestion (Excel BBVA + Norma 43) — Path: parrot_tools/finance/ingest.py

- path: `sdd/specs/auto-finance-toolkit.spec.md`
  lines: 647-651
  symbol: `Worktree strategy`
  excerpt: |
    Spec B (`hooba-service-toolkit`) depends on this spec's `DeductibilityVerdict` and must be decomposed AFTER this spec merges

- path: `sdd/tasks/index/`
  lines: listing
  symbol: `no auto-finance index`
  excerpt: |
    finance-reporter-tier2-narrative.json, web-automation-fixture-site-tests.json, web-automation-infra.json
