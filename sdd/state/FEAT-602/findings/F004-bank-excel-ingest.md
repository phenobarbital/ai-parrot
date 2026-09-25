---
id: F004
query_id: Q004
type: wiki_query
intent: Orient: existing bank-statement Excel ingestion machinery.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — FEAT-453 ingest.py builds a per-row ExecutionPlan but only maps two columns (client, amount) — not a BBVA layout parser

## Summary

`business_automation/ingest.py` (TASK-2392): `compute_statement_digest` (sha256 of bytes), `_load_expense_rows(xlsx_path, client_column, amount_column)` via `ExcelLoader`, `build_import_plan(xlsx_path, *, period, operation="register_expense", client_column="client", amount_column="amount")` → one `PlanNode(tool="run_operation")` per row, sequential; permission-hardened manifest under `$PARROT_STATE_DIR/business_automation/checkpoints/<operation>/`, `make_import_progress_listener` for resume-without-duplicates, `reconcile()`. It assumes a flat two-column sheet and a browser `register_expense` operation; a BBVA export (preamble rows, date/concept/amount columns) needs its own parser (Spec A Module 2, F005). No `ExcelStructureAnalyzer` class exists in ai-parrot-loaders (grep empty).

## Citations


- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py`
  lines: 111-151
  symbol: `_load_expense_rows`
  excerpt: |
    async def _load_expense_rows(xlsx_path, client_column, amount_column):
        missing_columns = {client_column, amount_column} - {str(c) for c in df.columns}
        return df[[client_column, amount_column]].astype(str).to_dict(orient="records")

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py`
  lines: 222-280
  symbol: `build_import_plan`
  excerpt: |
    async def build_import_plan(xlsx_path, *, period, operation="register_expense", client_column="client", amount_column="amount") -> ImportPlanBundle:
        digest = compute_statement_digest(xlsx_path)
        import_run = ImportRun(statement_digest=digest, period=period, ...)
        PlanNode(... tool="run_operation", args={... client_column: row[client_column], amount_column: row[amount_column]})

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py`
  lines: API outline
  symbol: `checkpoint_dir_for, compute_statement_digest, ImportPlanBundle, make_import_progress_listener, reconcile`

- path: `packages/ai-parrot-loaders/src/parrot_loaders/excel.py`
  lines: 1-1
  symbol: `ExcelLoader`
  excerpt: |
    imported by ingest.py: from parrot_loaders.excel import ExcelLoader
