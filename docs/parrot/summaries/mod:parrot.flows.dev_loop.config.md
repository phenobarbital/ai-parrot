---
type: Wiki Summary
title: parrot.flows.dev_loop.config
id: mod:parrot.flows.dev_loop.config
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dev-loop configuration helpers (FEAT-253).
relates_to:
- concept: func:parrot.flows.dev_loop.config.parse_repo_specs
  rel: defines
- concept: mod:parrot.flows.dev_loop.models
  rel: references
---

# `parrot.flows.dev_loop.config`

Dev-loop configuration helpers (FEAT-253).

Provides :func:`parse_repo_specs` — a pure, synchronous helper that
converts raw ``DEV_LOOP_REPOS`` env entries into
:class:`~parrot.flows.dev_loop.models.RepoSpec` objects.

``conf.py`` must never import ``dev_loop``, so this parser lives here
and is called by the demo server (``examples/dev_loop/server.py``) and
any other consumer that needs to turn string env-var entries into
``RepoSpec`` instances.

## Functions

- `def parse_repo_specs(raw: list[str]) -> list[RepoSpec]` — Parse ``DEV_LOOP_REPOS`` entries into :class:`RepoSpec` objects.
