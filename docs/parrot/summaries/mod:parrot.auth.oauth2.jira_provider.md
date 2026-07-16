---
type: Wiki Summary
title: parrot.auth.oauth2.jira_provider
id: mod:parrot.auth.oauth2.jira_provider
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Jira OAuth2 provider for the AI-Parrot integrations registry.
relates_to:
- concept: class:parrot.auth.oauth2.jira_provider.JiraOAuth2Provider
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.auth.oauth2.registry
  rel: references
- concept: mod:parrot_tools.jiratoolkit
  rel: references
---

# `parrot.auth.oauth2.jira_provider`

Jira OAuth2 provider for the AI-Parrot integrations registry.

``JiraOAuth2Provider`` wraps the existing ``JiraOAuthManager`` (thin wrapper —
no Jira-specific business logic lives here) and the ``JiraToolkit`` factory.

## Classes

- **`JiraOAuth2Provider(OAuth2Provider)`** — OAuth2 provider for Atlassian Jira Cloud (3LO flow).
