---
id: F076
query_id: Q001
type: wiki_page
intent: "Follow-up: FEAT-263 Copilot/A2A per-credential — the suspend/resume + AuditLedger surfaces the broker serves."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: FW-001
depth: 1
merged_from: [FW-023]
---

# F076 — FEAT-263 (approved 2026-06-26): A2A credential gate with suspend (`SuspendedExecutionStore`) + consent link + OAuth-callback nonce resume (`register_a2a_resume_hook`), greenfield KMS-signed `parrot.security.audit_ledger.AuditLedger`; Fireflies = static API key via `VaultTokenSync fireflies:api_key`; work.iq = MCP + Entra OBO

## Summary

FEAT-263 established the "deterministic contract, probabilistic consumer" pattern the brainstorm wants, for the A2A surface: `A2AServer.process_message` extracts identity, calls `CredentialResolver.resolve(channel, user_id)`, on `None` saves a `SuspendedExecution` (Redis key `hitl:suspended:{interaction_id}`) and returns a TEXT artifact with the consent link from `IntegrationsService.start_connect`; the OAuth callback (via `oauth2_routes.register_a2a_resume_hook`, TASK-1645) correlates nonce ↔ interaction_id and calls `AbstractBot.resume(session_id, user_input, state)`. `AuditLedger` (`parrot/security/audit_ledger.py`: `AuditLedgerEntry{entry_id,user_id,channel,tool,provider,key_fingerprint,signature,created_at}`, `AbstractKMSSigner`, `LocalHMACSigner`, later `AzureKeyVaultSigner`) records `key_fingerprint` never the secret. Resolved OQs: Fireflies accepts only a static API key (OOB capture, `fireflies:api_key`); work.iq is an MCP server with delegated-only OBO scope `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask`. FEAT-264 then replaced the A2A embedded gate with broker calls (TASK-1672) and gave MSAgentSDK Adaptive/OAuth cards + `ConversationReference` proactive resume (TASK-1673/1674).

## Citations

- path: `sdd/specs/copilot-a2a-percredential.spec.md`
  lines: n/a
  symbol: FEAT-263 §2 overview, §6 contract (`a2a/server.py:245 process_message`; `human/suspended_store.py:33 SuspendedExecution`, `:64 SuspendedExecutionStore` (`save/load/delete`); `bots/abstract.py:3462 resume`; `oauth2_routes.py:151 make_oauth2_callback`, `:202 setup_oauth2_routes`, `:216` auth exclusion)
  wiki_page_id: ledger::spec:copilot-a2a-percredential.spec (score=0.50)
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: n/a
  symbol: `AuditLedger` (`append`, `verify`), `AuditLedgerEntry`, `AbstractKMSSigner`, `LocalHMACSigner` (FEAT-264 §6 anchors `:203/:79/:134/:165`)
  wiki_page_id: ledger::spec:unified-credential-broker.spec
- path: `packages/ai-parrot-server/src/parrot/human/suspended_store.py`
  lines: n/a
  symbol: `SuspendedExecution`, `SuspendedExecutionStore`
  wiki_page_id: ledger::spec:copilot-a2a-percredential.spec
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: n/a
  symbol: `A2AServer` (`_extract_identity`, `_on_missing_credential`, `resume_from_oauth_callback`)
  wiki_page_id: ledger::spec:unified-credential-broker.spec
- path: `packages/ai-parrot/src/parrot/integrations/mcp/fireflies_a2a.py`
  lines: n/a
  symbol: `FirefliesCredentialResolver` (static key, `fireflies:api_key`, `store_key`)
  wiki_page_id: ledger::spec:unified-credential-broker.spec
- path: `packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py`
  lines: n/a
  symbol: `WorkIQOBOCredentialResolver`, `WorkIQOAuth2Provider`, `WORKIQ_SCOPE`
  wiki_page_id: ledger::spec:unified-credential-broker.spec

## Notes

Audit requirement of the brainstorm ("each event appended to the AuditLedger") maps onto the existing canonical ledger. The suspend/auto-resume pattern (A2A + MSAgentSDK) is the existing answer to "agent retries on completion" — the web/Telegram channels still require a manual re-prompt (FEAT-144 Q-D).

[citation-check: stale] packages/ai-parrot/src/parrot/integrations/mcp/fireflies_a2a.py — file does not exist in core; it lives at packages/ai-parrot-integrations/src/parrot/integrations/mcp/fireflies_a2a.py (6.4K).
