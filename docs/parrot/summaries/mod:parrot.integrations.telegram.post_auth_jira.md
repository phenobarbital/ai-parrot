---
type: Wiki Summary
title: parrot.integrations.telegram.post_auth_jira
id: mod:parrot.integrations.telegram.post_auth_jira
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Jira implementation of the ``PostAuthProvider`` protocol.
relates_to:
- concept: class:parrot.integrations.telegram.post_auth_jira.JiraPostAuthProvider
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.integrations.telegram.auth
  rel: references
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: references
- concept: mod:parrot.integrations.telegram.models
  rel: references
- concept: mod:parrot.services.identity_mapping
  rel: references
- concept: mod:parrot.services.vault_token_sync
  rel: references
---

# `parrot.integrations.telegram.post_auth_jira`

Jira implementation of the ``PostAuthProvider`` protocol.

Wraps :class:`parrot.auth.jira_oauth.JiraOAuthManager` to participate in
the combined Telegram auth flow:

1. ``build_auth_url`` asks the manager for an Atlassian consent URL and
   stashes the primary BasicAuth payload inside the CSRF nonce's
   ``extra_state`` so it can be reunited with the Jira code at the
   combined callback.
2. ``handle_result`` exchanges the Jira code for tokens (via
   :meth:`JiraOAuthManager.handle_callback`, which already writes to
   Redis), then additionally persists the tokens in the user's Vault
   (:class:`VaultTokenSync`) and creates identity-mapping rows in
   ``auth.user_identities`` (:class:`IdentityMappingService`) for both
   the Telegram and Jira providers.

Vault and identity-mapping failures are logged but do NOT fail the auth
— Redis is the primary store and the flow must stay resilient.

## Classes

- **`JiraPostAuthProvider`** — Secondary auth provider for Atlassian Jira (OAuth2 3LO).
