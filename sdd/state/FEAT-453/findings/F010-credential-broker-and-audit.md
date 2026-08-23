---
id: F010
query_id: Q012
type: read
intent: Determine how credentials/secrets are supplied to tools — a browser login to Hooba needs them
executed_at: 2026-08-23T09:32:00Z
depth: 1
parent_id: null
---

# F010 — A surface-agnostic CredentialBroker with vault storage and a signed invocation ledger already exists

## Summary

Hooba credentials do not need a bespoke solution. FEAT-264 shipped
`parrot/auth/broker.py` — a `CredentialBroker` + `CredentialResolverFactory`
with pluggable resolvers including `_VaultStaticKeyResolver` and
`_MCPVaultResolver` — sitting on `parrot/auth/credentials.py` ("Credential
resolution abstractions **for toolkits**"). Encrypted storage helpers live in
`parrot/security/vault_utils.py`, and `parrot/security/audit_ledger.py`
(FEAT-260) keeps an append-only, KMS-signed ledger of every credential
invocation. `sdd/specs/unified-credential-broker.spec.md` is the design of record.

A static username/password for `app.hooba.com` is the simplest resolver shape
this machinery already supports — the `Authenticate` action (F001/F002) would
pull from the broker rather than embedding secrets in a plan JSON.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/broker.py`
  lines: 51, 276-326
  symbol: `CredentialBroker`, resolvers
  excerpt: |
    Surface-agnostic CredentialBroker and CredentialResolverFactory (FEAT-264).
    class CredentialBrokerConfigError(Exception):        # 51
    class _VaultStaticKeyResolver(CredentialResolver):   # 276
    class _MCPVaultResolver(CredentialResolver):         # 303
    class CredentialBroker:                              # 326

- path: `packages/ai-parrot/src/parrot/auth/credentials.py`
  lines: 1-1
  symbol: "Credential resolution abstractions for toolkits."

- path: `packages/ai-parrot/src/parrot/security/vault_utils.py`
  lines: 1-1
  symbol: "Vault CRUD helpers — shared encrypted-credential storage for handlers."

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 1-1
  symbol: "Append-only, KMS-signed credential-invocation ledger (FEAT-260 / TASK-1642)."

- path: `sdd/specs/unified-credential-broker.spec.md`
  lines: 1-1
  symbol: "unified credential broker spec"

- path: `packages/ai-parrot/tests/unit/test_credential_broker.py`
  lines: 1-1
  symbol: "TASK-1667 broker tests"

## Notes

The audit ledger is an unexpectedly good fit for a *legally mandated* accounting
system: every automated login and every credential use against `app.hooba.com`
lands in a signed, append-only record. That is the kind of evidence trail worth
having if an automated filing is ever questioned.

Not answered by the codebase, and left as an unknown: whether Hooba enforces
MFA/CAPTCHA on login, which would make unattended `authenticate` impossible and
force the `user_data_dir` persistent-profile route (F004) plus `await_human`.
