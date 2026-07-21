---
type: Wiki Summary
title: parrot.security.vault_utils
id: mod:parrot.security.vault_utils
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Vault CRUD helpers — shared encrypted-credential storage for handlers.
relates_to:
- concept: func:parrot.security.vault_utils.delete_vault_credential
  rel: defines
- concept: func:parrot.security.vault_utils.load_vault_keys
  rel: defines
- concept: func:parrot.security.vault_utils.oauth2_vault_name
  rel: defines
- concept: func:parrot.security.vault_utils.retrieve_vault_credential
  rel: defines
- concept: func:parrot.security.vault_utils.store_vault_credential
  rel: defines
- concept: mod:parrot.interfaces.documentdb
  rel: references
- concept: mod:parrot.security.credentials_utils
  rel: references
---

# `parrot.security.vault_utils`

Vault CRUD helpers — shared encrypted-credential storage for handlers.

Provides ``store``, ``retrieve``, and ``delete`` operations on the
``user_credentials`` DocumentDB collection using the same AES-GCM encryption
scheme as :class:`~parrot.handlers.credentials.CredentialsHandler`.

Any handler that needs to persist secrets in the Vault should import from here
rather than duplicating this logic.

Usage::

    from parrot.security.vault_utils import (
        store_vault_credential,
        retrieve_vault_credential,
        delete_vault_credential,
    )

    await store_vault_credential(user_id, "mcp_perplexity_agent-1", {"api_key": "sk-..."})

## Functions

- `def load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]` — Load vault master keys from the environment.
- `async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None` — Encrypt and upsert secret parameters in the Vault.
- `async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]` — Decrypt and return a secret credential from the Vault.
- `async def delete_vault_credential(user_id: str, vault_name: str) -> None` — Hard-delete a Vault credential from DocumentDB.
- `def oauth2_vault_name(provider_id: str, channel: str, user_id: str) -> str` — Build the deterministic Vault credential name for an OAuth2 token.
