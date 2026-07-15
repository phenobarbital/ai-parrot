---
type: Wiki Summary
title: parrot.auth.oauth2.service
id: mod:parrot.auth.oauth2.service
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: IntegrationsService — orchestration layer for the OAuth2 integration flows.
relates_to:
- concept: class:parrot.auth.oauth2.service.IntegrationsService
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.auth.oauth2
  rel: references
- concept: mod:parrot.auth.oauth2.models
  rel: references
- concept: mod:parrot.auth.oauth2.persistence
  rel: references
- concept: mod:parrot.auth.oauth2.registry
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.auth.oauth2.service`

IntegrationsService — orchestration layer for the OAuth2 integration flows.

Provides four operations (list, start_connect, confirm_enable, disconnect) plus
``persist_credential()`` which is called from the web-channel OAuth2 callback
handler after a successful code exchange.

All origin validation is performed here (not in the handler) so that it is
covered by service-level unit tests.

PBAC convention
---------------
When the ``abac`` PDP is absent from the request (or when this service is called
without a request), the service fails **closed** for the integrations surface
(overrides the general fail-open convention in ``AgentTalk._check_pbac_agent_access``).
This was resolved as the correct behaviour for FEAT-144 Q-B.

## Classes

- **`IntegrationsService`** — Orchestrates OAuth2 provider registry, persistence, and PBAC checks.
