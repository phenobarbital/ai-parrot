---
id: F058
query_id: Q005
type: wiki_page
intent: "Read spec: unified credential broker (FEAT-264) — scope landed vs planned."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FW-005]
---

# F058 — FEAT-264 Unified Credential Broker spec (approved 2026-06-29, all 11 tasks done): declarative per-user auth for tools & MCP, canonical identity = Entra OID/email, one `CredentialRequired` signal, MCP token via `header_provider`

## Summary

FEAT-264 delivered: `CredentialBroker` + `CredentialResolverFactory` (`auth: obo|oauth2|static_key|mcp`) built from `ProviderCredentialConfig` on the AgentDefinition (`AbstractBot.configure()` → `ToolManager.set_broker()`) plus an in-package YAML manifest loader (`parrot/auth/manifest.py`); the core tool-loop seam between arg validation and `_execute` (`AbstractTool.credential_provider`, per-call ContextVar, `current_credential()`); `CanonicalIdentityMapper` (`parrot/auth/identity.py`); replacement of the A2AServer gate; MSAgentSDK Adaptive/OAuth cards + suspend/auto-resume; canonical `parrot.security.audit_ledger.AuditLedger` (+ `AzureKeyVaultSigner`; `parrot/auth/audit.py` deprecated); MCP per-user token injection into `MCPClientConfig.header_provider` (TASK-1676); Fireflies + work.iq example. Non-goals explicitly kept the OAuth2 `IntegrationsService` / provider registry / persistence schema as-is. Resolution keys are `(provider, channel, user_id)` where `user_id` is the *canonical* identity (OID/email), and `channel` is audit-only — i.e. the broker already treats connections as user-scoped, not channel-scoped, for the surfaces it covers (A2A, MSAgentSDK, CLI). The brainstorm's "`NeedsAuthorizationError` / `WebOAuthManager` / `StateStore` / `TokenStore`" are NOT in this design; the actual names are `NeedsAuth` (model) and `CredentialRequired` (exception).

## Citations

- path: `sdd/specs/unified-credential-broker.spec.md`
  lines: n/a
  symbol: FEAT-264 §2 Overview, §3 M1–M10, §6 Codebase Contract
  wiki_page_id: ledger::spec:unified-credential-broker.spec (score=0.50)
- path: `packages/ai-parrot/src/parrot/auth/manifest.py`
  lines: n/a
  symbol: in-package YAML manifest loader for per-agent credential configuration
  wiki_page_id: dir:packages/ai-parrot/src/parrot/auth
- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  lines: n/a
  symbol: DEPRECATED shim → `parrot.security.audit_ledger`
  wiki_page_id: dir:packages/ai-parrot/src/parrot/auth
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: n/a
  symbol: `credential_provider`, `current_credential()` (per spec §6: `abstract.py:36`, `:123/:147`)
  wiki_page_id: ledger::spec:o365-auth-homologation.spec
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: n/a
  symbol: `ToolManager.set_broker()`, `_broker` / `_cred_channel` / `_cred_user_id` injection from `permission_context.channel/.user_id` (spec §2: `manager.py:1305-1316`)
  wiki_page_id: ledger::spec:o365-auth-homologation.spec

## Notes

Verified-at-spec-time line numbers (June/July 2026) may have drifted; the codebase lane should re-anchor `tools/abstract.py` and `tools/manager.py`. `[cross-lane: type=grep, intent=re-anchor set_broker/_cred_channel/_cred_user_id/current_credential in tools/manager.py and tools/abstract.py]`.
