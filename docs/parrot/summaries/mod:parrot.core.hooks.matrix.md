---
type: Wiki Summary
title: parrot.core.hooks.matrix
id: mod:parrot.core.hooks.matrix
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Matrix protocol hook for AutonomousOrchestrator.
relates_to:
- concept: class:parrot.core.hooks.matrix.MatrixHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.matrix`

Matrix protocol hook for AutonomousOrchestrator.

This module is a thin compatibility shim.  The concrete ``MatrixHook``
implementation lives in the satellite package ``ai-parrot-integrations``
(``parrot.integrations.matrix.hook``) and self-registers with
:class:`~parrot.core.hooks.base.HookRegistry` when that package is
imported.

Usage
-----
Install ``ai-parrot-integrations[matrix]`` and import the hook module
to trigger self-registration::

    import parrot.integrations.matrix.hook  # auto-registers MatrixHook
    from parrot.core.hooks import MatrixHook  # resolved via HookRegistry

.. deprecated::
    Direct use of this module is discouraged.  Use the
    :class:`~parrot.core.hooks.base.HookRegistry` instead.

## Classes

- **`MatrixHook(BaseHook)`** — Compatibility shim for MatrixHook.
