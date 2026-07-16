---
type: Wiki Summary
title: parrot.integrations.core.auth.post_auth
id: mod:parrot.integrations.core.auth.post_auth
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PostAuthProvider protocol and registry for secondary authentication flows.
relates_to:
- concept: class:parrot.integrations.core.auth.post_auth.PostAuthProvider
  rel: defines
- concept: class:parrot.integrations.core.auth.post_auth.PostAuthRegistry
  rel: defines
---

# `parrot.integrations.core.auth.post_auth`

PostAuthProvider protocol and registry for secondary authentication flows.

Secondary auth providers run AFTER a primary authentication succeeds and
before the auth flow completes on the client side. A provider is responsible
for:

1. Building a provider-specific authorization URL that the login page can
   redirect to after the primary auth completes.
2. Handling the provider-specific result payload received from the combined
   callback — exchanging codes for tokens, persisting them, and creating
   identity mapping records.

This module defines only the **generic framework** (protocol + registry).
Concrete providers (e.g., ``JiraPostAuthProvider``) live in their own
modules (see ``parrot.integrations.telegram.post_auth_jira``).

## Classes

- **`PostAuthProvider(Protocol)`** — Protocol for secondary authentication providers.
- **`PostAuthRegistry`** — Registry mapping provider names to ``PostAuthProvider`` instances.
