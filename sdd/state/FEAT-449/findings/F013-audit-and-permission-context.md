---
id: F013
query_id: Q013
type: grep
intent: Verify AuditLedger / permission_context referenced by the CENDOJ attributability requirement
executed_at: 2026-08-23T00:22:57Z
depth: 0
parent_id: null
---

# F013 — Both AuditLedger and permission_context are real and already flow into ToolManager.execute_tool

## Summary

The source's requirement that every CENDOJ request be attributable to a named lawyer is
supported by existing machinery. `permission_context` is pervasive (553 matches across
packages) and the documented path is explicit: `ask()` forwards `permission_context` to the
LLM client's `_permission_context`, "which is where ToolManager.execute_tool" reads it — and
the seam is documented as failing **closed** without it. `AuditLedger` exists in two places:
`parrot/auth/audit.py` and `parrot/security/audit_ledger.py`, the latter with an
`AuditLedgerEntry` model.

## Citations

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 80, 296
  symbol: `AuditLedgerEntry`, `AuditLedger`

- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  lines: 65
  symbol: `AuditLedger`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`
  lines: 156, 385-396
  excerpt: |
    audit_ledger: Optional :class:`AuditLedger` for recording
    # client: ``ask()`` forwards ``permission_context`` to
    # ``client._permission_context``, which is where ToolManager.execute_tool

- path: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/resume.py`
  lines: 291-292
  excerpt: |
    # from the LLM client's ``_permission_context``, which ``ask()`` populates
    # from its ``permission_context`` argument. Without it the seam fails closed

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  lines: 20-21
  excerpt: |
    from parrot.auth.permission import PermissionContext, to_eval_context
    from parrot.auth.userinfo import UserInfoService

## Notes

Two `AuditLedger` classes with the same name is a disambiguation the spec must resolve
explicitly before wiring CENDOJ attribution.
