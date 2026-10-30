---
id: F034
query_id: Q054
type: grep
intent: "Audit: canonical AuditLedger location (security/audit_ledger) and remaining auth/audit callers."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-035]
---

# F034 — Two AuditLedger classes still exist: canonical parrot/security/audit_ledger.py (KMS-signed, used by broker, roost, msagentsdk/auth) and legacy parrot/auth/audit.py (still imported by msagentsdk/wrapper.py)

## Summary

`security/audit_ledger.py:80 AuditLedgerEntry`, `:296 class AuditLedger`; imported by `auth/broker/core.py`, `tools/stub_credentialed_tool.py`, `roost/audit.py` (signers), `integrations/msagentsdk/auth.py`. Legacy `auth/audit.py:65 class AuditLedger` (3.9K) still exists and is imported by `integrations/msagentsdk/wrapper.py:135`.

## Citations

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 80,296
  symbol: `AuditLedgerEntry / AuditLedger`
  excerpt: |
    class AuditLedgerEntry(BaseModel)  # :80
    class AuditLedger:  # :296
- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  lines: 65
  symbol: `AuditLedger (legacy)`
  excerpt: |
    class AuditLedger:
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py`
  lines: 135
  symbol: `legacy import`
  excerpt: |
    from parrot.auth.audit import AuditLedger

## Notes

FEAT-264 M8 'one canonical ledger' is not fully done (legacy still imported once). `connection.*` audit entries should target `parrot.security.audit_ledger`.
