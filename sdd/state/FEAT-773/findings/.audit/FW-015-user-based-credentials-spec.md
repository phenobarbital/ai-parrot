---
id: FW-015
query_id: Q015
type: wiki_page
intent: "Read spec: user-based-credentials — the 'session vault' / per-user credential store the brainstorm asks about (spike S1)."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-015 — FEAT-063 user-based-credentials (approved 2026-03-25): per-user asyncdb DB credentials via `CredentialsHandler` at `/api/v1/users/credentials`, session-vault keys `_credentials:{name}` + DocumentDB `user_credentials` encrypted with navigator-session `encrypt_for_db`; OAuth tokens explicitly OUT of scope

## Summary

The "session vault" referenced in the Dec-2025 per-session design is navigator-session's `SessionData` vault: FEAT-063 stores DB credential dicts there under `_credentials:{name}` for immediate availability and persists them to DocumentDB `user_credentials` (unique `(user_id, name)`), encrypted with `navigator_session.vault.crypto.encrypt_for_db/decrypt_for_db` (helpers now `parrot/security/credentials_utils.py`, FEAT-099 envelope v2). Non-goals: OAuth/token credential types, sharing, rotation. So this is the *ephemeral+durable DB-credential* scope; it is unrelated to OAuth connections and does not define a principal-keyed OAuth vault. Together with FW-004 this closes Spike S1: there is no single "vault" to extend; there are navigator-session user vault (`vault_utils`/`VaultTokenSync`), navigator-auth Identity Vault (`IdentityStore`), Postgres `ai_user_credentials` (FEAT-621), and DocumentDB (`user_credentials`, `users_integrations`).

## Citations

- path: `sdd/specs/user-based-credentials.spec.md`
  lines: n/a
  symbol: FEAT-063 §2 (`CredentialsHandler(BaseView)`, `@is_authenticated` `@user_session`, `DocumentDb.save_background`), §6 session key convention `_credentials:{name}`
  wiki_page_id: file:sdd/specs/user-based-credentials.spec.md
- path: `packages/ai-parrot-server/src/parrot/handlers/credentials.py`
  lines: n/a
  symbol: `CredentialsHandler` CRUD view for user database credentials
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/handlers/credentials.py (score=0.78)
- path: `packages/ai-parrot/src/parrot/security/credentials_utils.py`
  lines: n/a
  symbol: envelope v2 encryption helpers (FEAT-099)
  wiki_page_id: file:packages/ai-parrot/src/parrot/security/credentials_utils.py (score=0.52)

## Notes

None.
