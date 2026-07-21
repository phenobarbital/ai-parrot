---
type: Wiki Summary
title: parrot_tools.o365.oauth_toolkit
id: mod:parrot_tools.o365.oauth_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Office 365 toolkit with per-user OAuth 2.0 (delegated / 3LO) auth.
relates_to:
- concept: class:parrot_tools.o365.oauth_toolkit.Office365Toolkit
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.auth.o365_oauth
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot_tools.o365.oauth_toolkit`

Office 365 toolkit with per-user OAuth 2.0 (delegated / 3LO) auth.

Concrete :class:`parrot.tools.toolkit.AbstractToolkit` that resolves
per-user Microsoft Graph access tokens through a
:class:`parrot.auth.credentials.CredentialResolver` at tool-call time —
the same pattern used by :class:`parrot_tools.jiratoolkit.JiraToolkit`
for ``oauth2_3lo`` mode.

Each public async method becomes an LLM-visible tool. ``_pre_execute``
extracts ``_permission_context`` from kwargs, resolves the token, and
caches an ``aiohttp.ClientSession`` keyed by ``channel:user_id``. The
session sends ``Authorization: Bearer <access_token>`` headers; on a
401 from Graph the cache entry is evicted so the next call re-fetches
from the manager (which may transparently refresh the token).

## Classes

- **`Office365Toolkit(AbstractToolkit)`** — Microsoft Graph toolkit with delegated per-user OAuth tokens.
