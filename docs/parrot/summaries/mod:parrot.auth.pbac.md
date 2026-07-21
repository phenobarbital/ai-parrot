---
type: Wiki Summary
title: parrot.auth.pbac
id: mod:parrot.auth.pbac
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PBAC (Policy-Based Access Control) setup and initialization for AI-Parrot.
relates_to:
- concept: func:parrot.auth.pbac.setup_pbac
  rel: defines
---

# `parrot.auth.pbac`

PBAC (Policy-Based Access Control) setup and initialization for AI-Parrot.

This module provides the ``setup_pbac()`` async helper that boots the full
PBAC stack during application startup and wires it into the aiohttp app.

Typical usage in app.py::

    from parrot.auth.pbac import setup_pbac

    pdp, evaluator, guardian = setup_pbac(app, policy_dir="policies")
    if evaluator is not None:
        resolver = PBACPermissionResolver(evaluator=evaluator)
        bot_manager.set_default_resolver(resolver)

Public API:
    - ``setup_pbac``: Initialize PBAC engine from YAML policies directory.

## Functions

- `def setup_pbac(app: web.Application, policy_dir: str='policies', cache_ttl: int=30, default_effect: Optional[object]=None) -> 'tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]'` — Initialize the PBAC engine and register it with the aiohttp application.
