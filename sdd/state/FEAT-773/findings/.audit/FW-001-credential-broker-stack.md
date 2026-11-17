---
id: FW-001
query_id: Q001
type: wiki_query
intent: "Orient: broker/credential-resolver stack in core (FEAT-264) — what resolves per-user credentials today."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-001 — FEAT-264 CredentialBroker stack EXISTS in core: broker package, factory, NeedsAuth/CredentialRequired signals, tool-loop ContextVar seam

## Summary

The brainstorm's proposed `ConnectionManager` / `VaultCredentialResolver` / unified needs-auth signal already has a shipped counterpart. `parrot.auth.broker` (package: `core.py`, `factory.py`, `byok.py`) hosts `CredentialBroker` (`register`, `from_config`, `resolve(provider, channel, user_id) -> ResolvedCredential | NeedsAuth`) and `CredentialResolverFactory` mapping `auth` kinds `obo | oauth2 | static_key | mcp | device_code` to resolver strategies. `parrot.auth.credentials` defines `CredentialResolver` ABC (`resolve(channel, user_id)`, `get_auth_url`, `is_connected`), `OAuthCredentialResolver(oauth_manager)`, `StaticCredentialResolver`, `NeedsAuth` and the surface-neutral `CredentialRequired(provider, auth_url, auth_kind)` exception. TASK-1669 inserted the credential seam into `AbstractTool.execute()` with a per-call ContextVar read via `current_credential()`; `AbstractTool.credential_provider` is formalised. All 11 FEAT-264 tasks (TASK-1667..1677) are `done` (per-spec index, completed 2026-06-30). This is a second, parallel "needs auth" protocol next to `AuthorizationRequired` — exactly the duplication the brainstorm wants to collapse, but the two classes are BOTH in core, not one in the Jira package.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: n/a
  symbol: `CredentialBroker` (`__init__`, `from_config`, `register`, `resolve`), `CredentialBrokerConfigError`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/broker/core.py (score=0.82)
- path: `packages/ai-parrot/src/parrot/auth/broker/__init__.py`
  lines: n/a
  symbol: `CredentialResolverFactory`, `_MCPVaultResolver`, `_VaultStaticKeyResolver`, `_UserLLMKeyResolver`, `set_user_llm_key_store`, `byok_store_setting`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/broker/__init__.py (score=0.43)
- path: `packages/ai-parrot/src/parrot/auth/credentials.py`
  lines: n/a
  symbol: `CredentialResolver`, `OAuthCredentialResolver`, `StaticCredentialResolver`, `AuthKind`, `ProviderCredentialConfig`, `ResolvedCredential`, `NeedsAuth`, `CredentialRequired`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/credentials.py (score=0.22)
- path: `packages/ai-parrot/src/parrot/auth/__init__.py`
  lines: n/a
  symbol: `_LAZY_ATTRS` (exports `AuthorizationRequired` from `parrot.auth.exceptions`, `CredentialBroker` from `parrot.auth.broker`, `CredentialRequired`/`NeedsAuth` from `parrot.auth.credentials`)
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/__init__.py (score=0.42)
- path: `sdd/tasks/completed/TASK-1669-tool-loop-seam.md`
  lines: n/a
  symbol: `current_credential()` ContextVar seam in `AbstractTool.execute`
  wiki_page_id: file:sdd/tasks/completed/TASK-1669-tool-loop-seam.md (score=0.14)
- path: `sdd/tasks/index/unified-credential-broker.json`
  lines: n/a
  symbol: FEAT-264 tasks TASK-1667..TASK-1677 all `done`, completed_at 2026-06-30

## Notes

The brainstorm §3 row "`CredentialResolver` generic or Jira-typed?" → generic: signature is `(channel, user_id)` with `Optional[Any]` return; `OAuthCredentialResolver` wraps any manager exposing `get_valid_token(channel, user_id)`. Two needs-auth exceptions coexist in core: `parrot.auth.exceptions.AuthorizationRequired` (FEAT-107, caught by ToolManager + AgentTalk) and `parrot.auth.credentials.CredentialRequired` (FEAT-264, raised by the broker seam). `[cross-lane: type=read, intent=confirm how ToolManager/AbstractTool handle BOTH AuthorizationRequired and CredentialRequired and whether they map to the same ToolResult status]`.
