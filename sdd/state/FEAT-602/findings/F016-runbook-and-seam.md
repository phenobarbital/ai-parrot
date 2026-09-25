---
id: F016
query_id: Q013
type: read
intent: FEAT-453 spec goals/non-goals and runbook for the plans-directory contract.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F016 — The public/private seam and the D2 submit-gate policy are documented operator contracts, not just code comments

## Summary

`docs/business-automation-runbook.md` (tracked) §1 Plans-directory contract, §2 Submit-gate policy (Decision D2), §2a Broker-backed login and mid-plan human pauses, §3 Checkpoints and retention (D3), §4 WhatsApp channel as financial control, §5 gestoria wiki plane, §7 SmokeCheck (D4). `sdd/specs/web-automation-infra.spec.md` §1 Goals line 71 "the reusable engine is public and site-specific plans stay private"; line 90 "Site plans are an out-of-repo deliverable (§3, Deliverable X)"; §2 line 156 `TemplatePlanStore ← external plans dir (private, configurable)`; line 170 `GestoriaAgent + hooba/*.template.json (private plans, 5 operations)`.

## Citations


- path: `docs/business-automation-runbook.md`
  lines: 10, 36, 58, 87, 126, 225
  symbol: `sections`
  excerpt: |
    ## 1. Plans-directory contract / ## 2. Submit-gate policy (Decision D2) / ## 2a. Broker-backed login / ## 3. Checkpoints and retention (Decision D3) / ## 7. Scheduled canary (SmokeCheck, Decision D4)

- path: `sdd/specs/web-automation-infra.spec.md`
  lines: 71, 90, 138, 156, 170
  symbol: `public/private seam`
  excerpt: |
    so the reusable engine is public and site-specific plans stay private. ... Site plans are an out-of-repo deliverable ... GestoriaAgent + hooba/*.template.json (private plans, 5 operations)
