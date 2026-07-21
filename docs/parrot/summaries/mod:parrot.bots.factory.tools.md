---
type: Wiki Summary
title: parrot.bots.factory.tools
id: mod:parrot.bots.factory.tools
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic tools the Agent Factory builders invoke.
relates_to:
- concept: mod:parrot.bots.factory.tools.finalize
  rel: references
- concept: mod:parrot.bots.factory.tools.introspection
  rel: references
- concept: mod:parrot.bots.factory.tools.openapi_register
  rel: references
- concept: mod:parrot.bots.factory.tools.vector_store
  rel: references
---

# `parrot.bots.factory.tools`

Deterministic tools the Agent Factory builders invoke.

These are plain async helpers. They are also exposed as ``@tool``-decorated
callables so the orchestrator/specialist LLMs can invoke them directly when
that is more natural than calling them from Python.
