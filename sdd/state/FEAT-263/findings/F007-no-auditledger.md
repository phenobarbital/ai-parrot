# F007 — AuditLedger / key_fingerprint do NOT exist (GAP — brainstorm invariant unbacked)

**Query**: Q003 (grep `class AuditLedger`, `key_fingerprint`, `audit_ledger`, `AuditLog`)
**Verdict**: ABSENT — brainstorm §6 invariant #4 and §12 AC have no code backing.

- Zero matches for `AuditLedger`, `key_fingerprint`, `audit_ledger`, `AuditLog` across all `packages/*/src/parrot`.
- The scrubber seam (F008) and PBAC exist, but the append-only KMS-signed `AuditLedger` recording `key_fingerprint` per credentialed invocation is **aspirational vocabulary**, not implemented.

**Implication**: Any spec AC that requires `AuditLedger.key_fingerprint` must either (a) descope it to a thinner audit-log, or (b) build it from scratch — it is NOT a reuse. This is the single largest "claimed-but-absent" item; the proposal must flag it so the spec doesn't assume it.
