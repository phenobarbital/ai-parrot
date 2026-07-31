---
type: Wiki Summary
title: parrot.bots.flows.core.storage.backends
id: mod:parrot.bots.flows.core.storage.backends
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pluggable result-storage backends for AgentCrew and AgentsFlow (FEAT-147).
relates_to:
- concept: mod:parrot.bots.flows.core.storage
  rel: references
---

# `parrot.bots.flows.core.storage.backends`

Pluggable result-storage backends for AgentCrew and AgentsFlow (FEAT-147).

Public API
----------
* ``ResultStorage``           — abstract base class (ABC).
* ``DocumentDbResultStorage`` — default backend (wraps DocumentDb).
* ``RedisResultStorage``      — Redis backend (one key per execution + TTL).
* ``PostgresResultStorage``   — Postgres backend (jsonb row per execution).
* ``get_result_storage``      — factory: resolves a name/instance/env-var.
