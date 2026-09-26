---
id: F008
query_id: Q012
type: read
intent: FEAT-453 status, module boundaries and the out-of-repo Deliverable X.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — FEAT-453 shipped completely (14/14 tasks, 2026-08-24); the five Hooba BusinessOperations were declared an out-of-repo deliverable that never materialized

## Summary

`sdd/tasks/index/web-automation-infra.json`: FEAT-453 `completed_at 2026-08-24`, all 14 tasks done (session_actions, broker-backed authenticate, BusinessAutomationToolkit + SUBMIT gate, external plans dir, bank-Excel ingest, calendar, scheduler, SmokeCheck, gestoria wiki plane, allowlist). Spec §3 "Deliverable X (OUT OF REPO)" lists five Hooba `BusinessOperation`s — `login`, `create_client`, `register_expense`, `draft_invoice`, `download_invoice_pdf` — with TemplatePlans and selectors; §8 resolved "engine public / plans private". F007 shows only navigation actions exist locally, so `register_expense`/`draft_invoice` web plans were never written. git log on business_automation/: last commit 2026-08-24 (stable for 4 weeks).

## Citations


- path: `sdd/tasks/index/web-automation-infra.json`
  lines: header + tasks
  symbol: `FEAT-453 index`
  excerpt: |
    completed_at 2026-08-24T09:54:01+00:00; TASK-2384..TASK-2397 all done

- path: `sdd/specs/web-automation-infra.spec.md`
  lines: 392-403
  symbol: `Module 9`
  excerpt: |
    Build an ExecutionPlan that iterates ExcelLoader row-mode Documents and invokes the register_expense operation per row

- path: `sdd/specs/web-automation-infra.spec.md`
  lines: 420-431
  symbol: `Deliverable X`
  excerpt: |
    five Hooba BusinessOperations — login, create_client, register_expense, draft_invoice, download_invoice_pdf — ... cannot live in this repo (D4). Why out of repo: §8, resolved — the engine is public, site plans are not.

- path: `sdd/specs/web-automation-infra.spec.md`
  lines: 968
  symbol: `§8 resolved question`
  excerpt: |
    Where does the Hooba toolkit live? — Generic engine public in parrot_tools/business_automation/; Hooba plans private, outside the repo

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/`
  lines: git log
  symbol: `Q034`
  excerpt: |
    3466fdcd32 2026-08-24 style: black; f5a5001e4c fix: close remaining critical review findings (AC-5, AC-12); d93dd03756 wire PlanDirectoryStore; ... 1dba612d5a TASK-2390 core + SUBMIT gate
