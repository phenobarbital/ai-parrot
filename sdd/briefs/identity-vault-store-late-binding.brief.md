---
kind: brief
slug: identity-vault-store-late-binding
key: 4137bc2e311f
base_branch: dev
source:
  type: ledger
  ref: issue:4137bc2e311f
  url: null
jira_issue_key: null
ledger_issue: issue:4137bc2e311f
created: "2026-11-02"
---

# Brief: Bind the Identity Vault credential store after navigator-auth startup

## Problem
Ledger issue:4137bc2e311f (major, from FEAT-773): "Identity Vault credential store is never bound:
OAuth2 managers freeze `_store` before `app['authdb']` exists." After startup,
`type(app['oauth2_manager_o365']._store)` is `VaultUtilsCredentialStore`, and the root `app.py`
Jira manager is the same. 3LO grants never reach `auth.user_identities`, so the FEAT-773 M8/S2
"durable owner" claim (`docs/auth/connections.md`) is false for the shipped server.

## Root cause
`AbstractOAuth2Manager.__init__` freezes the store at construction
(`packages/ai-parrot/src/parrot/auth/oauth2_base.py:267`:
`self._store = credential_store or VaultUtilsCredentialStore()`). All managers are built during
`configure()`/`BotManager.setup()`, but navigator-auth publishes `app["authdb"]` only inside its
`on_startup` handler. Hence:
- `packages/ai-parrot-server/src/parrot/manager/manager.py:2932-2939` — O365 reads `app.get("authdb")` → `None` → default store.
- `app.py:147` — `JiraOAuthManager(...)` built with no `credential_store`.
- `packages/ai-parrot-server/src/parrot/manager/manager.py:2950-2987` — `_register_oauth2_providers`
  (on_startup, *does* see `authdb`) sets the principal resolver and O365 `_events` but never
  attaches a store. (Descriptor providers, registered from inside this hook at :2987, already get one.)

## Research findings
- Store consumers in the manager: `_store.save` (:605), `_store.load` (:641), `_store.delete` (:780, :825, :855) — all at request time, never before startup, so late binding is safe.
- `IdentityVaultCredentialStore(db_pool, cipher=None)` — `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py:67-74`.
- Managers live in `app["jira_oauth_manager"]` and `app["oauth2_manager_<provider_id>"]`.
- Existing late-binding precedent in the same hook: `o365_manager._events = connection_event_publisher` only when unset.
- Workaround in the external harness: `parrot-external-auth/vault_store.py::LazyIdentityVaultCredentialStore`.

## Decisions
Assumptions (no Q&A needed — research settled the choice):
- Use fix option (b): late binding at startup, not lazy resolution inside core `AbstractOAuth2Manager`
  (core must not know about `app["authdb"]` / the server-only `IdentityVaultCredentialStore`).
- Only replace a store the caller did not supply explicitly: track `_store_is_default` in the manager.
- When `authdb` is absent (no navigator-auth), keep `VaultUtilsCredentialStore` and log once at INFO.
- Tokens already written to the generic vault are not migrated (out of scope; note in docs).

## Fix plan
- HOTFIX-4137bc2e311f-1 — add `AbstractOAuth2Manager.bind_credential_store()` + `_store_is_default`;
  in `BotManager._register_oauth2_providers` bind `IdentityVaultCredentialStore(authdb)` onto every
  `app["jira_oauth_manager"]` / `app["oauth2_manager_*"]` manager still on the default store; tests.

## Validation commands
- `pytest packages/ai-parrot/tests/auth/test_oauth2_store_binding.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py -q`
