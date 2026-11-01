---
id: F010
query_id: Q029
type: read
intent: "R1: read VaultTokenSync — key shape, persistence, encryption, per-user vs per-session."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-010]
---

# F010 — VaultTokenSync persists OAuth tokens into navigator-session's encrypted SessionVault under a deterministic per-user session_uuid; flat `{provider}:{field}` keys; Jira retired from it (FEAT-735)

## Summary

`parrot/services/vault_token_sync.py` (343 lines, ai-parrot-server). Uses `navigator_session.vault.SessionVault.load_for_session(session_uuid=_synth_session_uuid(nav_user_id), user_id=int(nav_user_id), session_ttl=3600)`; `_synth_session_uuid` = `f"{session_scheme}:{nav_user_id}"` (deterministic → persistent across sessions despite being a 'session' vault). Keys are flat `{provider}:{key}` (e.g. `fireflies:api_key`). `store_tokens(nav_user_id, provider, tokens)` writes field-by-field (no transactional write; FEAT-267 partial-write warning). Docstring: 'Jira no longer stores credentials in this vault' — owner is Identity Vault (`auth.user_identities`). Returns `VaultTokenRead` with `needs_reconnect`. Failures are logged, never raised.

## Citations

- path: `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`
  lines: 3-16
  symbol: `module docstring`
  excerpt: |
    Vault using a flat {provider}:{field} key scheme ... fireflies:api_key
    **Jira no longer stores credentials in this vault.** Its durable owner is navigator-auth's Identity Vault (auth.user_identities)
- path: `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`
  lines: 69-88
  symbol: `_synth_session_uuid`
  excerpt: |
    def _synth_session_uuid(nav_user_id: str, session_scheme: str = _DEFAULT_SESSION_SCHEME) -> str:
        return f"{session_scheme}:{nav_user_id}"
- path: `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`
  lines: 107-150
  symbol: `VaultTokenSync`
  excerpt: |
    class VaultTokenSync:
        def __init__(self, db_pool, redis, session_ttl: int = 3600, session_scheme: str = _DEFAULT_SESSION_SCHEME)
- path: `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`
  lines: 157-181
  symbol: `VaultTokenSync._load_vault`
  excerpt: |
    vault = await SessionVault.load_for_session(session_uuid=_synth_session_uuid(nav_user_id, self._session_scheme), user_id=_coerce_user_id(nav_user_id), session_ttl=self._session_ttl)
- path: `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`
  lines: 189-239
  symbol: `VaultTokenSync.store_tokens`
  excerpt: |
    for key, value in ordered_items:
        vault_key = f"{provider}:{key}"
        await vault.set(vault_key, value)

## Notes

Spike S1 answer (part 1): the 'session vault' is navigator-session `SessionVault` (`auth.user_vault_secrets`), encrypted; made per-user by a synthetic deterministic session_uuid. It is keyed by nav_user_id (principal), NOT channel. Still serves fireflies/workiq/entra/o365 per docs (FC-032).
