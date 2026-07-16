---
type: Wiki Summary
title: parrot.handlers.agents.factory
id: mod:parrot.handlers.agents.factory
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for the AgentFactoryOrchestrator.
relates_to:
- concept: class:parrot.handlers.agents.factory.AgentFactoryHandler
  rel: defines
- concept: func:parrot.handlers.agents.factory.build_auto_approve_manager
  rel: defines
- concept: mod:parrot.bots.factory
  rel: references
- concept: mod:parrot.human.channels
  rel: references
- concept: mod:parrot.human.manager
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.handlers.agents.factory`

HTTP handler for the AgentFactoryOrchestrator.

Endpoint shape:

    POST /api/v1/agents/factory
        body: {description, clone_from?, hints?, category?, auto_approve?}
        returns: FactoryResult-as-JSON

The handler picks up the ``HumanInteractionManager`` from
``request.app["human_manager"]``. If absent, a stub manager that
auto-approves every gate is used — handy for scripted / CI runs.

For real interactive flows, the host application must register the manager
beforehand (typically wiring a ``WebHumanChannel`` or telegram channel).

IMPORTANT: auto_approve=true is restricted to authenticated users with
factory:admin role to prevent registry tampering via unvalidated API calls.

## Classes

- **`AgentFactoryHandler(BaseView)`** — POST /api/v1/agents/factory — create a new agent via the factory.

## Functions

- `def build_auto_approve_manager() -> HumanInteractionManager` — Construct a manager whose only channel auto-approves every gate.
