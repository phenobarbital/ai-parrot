---
type: Wiki Summary
title: parrot.auth.jira_oauth
id: mod:parrot.auth.jira_oauth
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Jira OAuth 2.0 (3LO) manager for per-user authentication.
relates_to:
- concept: class:parrot.auth.jira_oauth.JiraOAuthManager
  rel: defines
- concept: class:parrot.auth.jira_oauth.JiraTokenSet
  rel: defines
- concept: mod:parrot.auth.routes
  rel: references
---

# `parrot.auth.jira_oauth`

Jira OAuth 2.0 (3LO) manager for per-user authentication.

This module implements the complete Atlassian OAuth 2.0 (3LO) lifecycle
for per-user Jira access:

- Generate authorization URLs with CSRF state nonces.
- Exchange authorization codes for tokens.
- Discover ``cloud_id`` via the ``accessible-resources`` endpoint.
- Resolve user identity via ``/rest/api/3/myself``.
- Store and retrieve tokens from Redis, keyed by ``channel:user_id``.
- Handle Atlassian's rotating refresh tokens with a Redis distributed
  lock to avoid losing tokens when two requests refresh concurrently.

The manager never holds credentials in memory — everything flows through
Redis so the HTTP callback process and the agent session can share state.

## Classes

- **`JiraTokenSet(BaseModel)`** — Per-user Jira OAuth 2.0 token set persisted in Redis.
- **`JiraOAuthManager`** — OAuth 2.0 (3LO) lifecycle manager for Jira Cloud.
