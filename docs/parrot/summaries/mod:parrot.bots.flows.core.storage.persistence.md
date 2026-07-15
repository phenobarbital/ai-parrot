---
type: Wiki Summary
title: parrot.bots.flows.core.storage.persistence
id: mod:parrot.bots.flows.core.storage.persistence
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PersistenceMixin — pluggable persistence for crew/flow execution results
  (FEAT-147).
relates_to:
- concept: class:parrot.bots.flows.core.storage.persistence.PersistenceMixin
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: references
---

# `parrot.bots.flows.core.storage.persistence`

PersistenceMixin — pluggable persistence for crew/flow execution results (FEAT-147).

Replaces the former hard-wired DocumentDB persistence with a delegating
mixin that respects ``self._persist_results`` (opt-out) and lazily resolves
a ``ResultStorage`` backend on first write.

The host class is responsible for initialising four attributes in its
``__init__``:

    self._persist_results: bool                        # default True
    self._result_storage_arg: str | ResultStorage | None
    self._result_storage: Optional[ResultStorage]      # populated lazily
    self._persist_tasks: set[asyncio.Task]             # initialised to set()

All four are accessed via ``getattr`` with safe defaults so the mixin
remains backwards-compatible with host classes that have not yet been wired.

A host may additionally opt out of per-agent persistence only (FEAT-306)
via a fifth, optional attribute:

    self._persist_agent_results: bool                  # default True

Also accessed via ``getattr`` with a safe default of ``True``, so hosts
that have not been wired for per-agent persistence keep working unchanged.

## Classes

- **`PersistenceMixin`** — Pluggable persistence for crew/flow execution results.
