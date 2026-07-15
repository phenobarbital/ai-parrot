---
type: Wiki Summary
title: parrot.tools.database
id: mod:parrot.tools.database
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deprecated alias — use ``parrot.tools.databasequery`` instead.
relates_to:
- concept: mod:parrot.tools.databasequery
  rel: references
---

# `parrot.tools.database`

Deprecated alias — use ``parrot.tools.databasequery`` instead.

This module exists for backwards compatibility only.  The ``DatabaseToolkit``
class was renamed to ``DatabaseQueryToolkit`` and moved to
``parrot.tools.databasequery`` in FEAT-105 (databasetoolkit-clash) to resolve
a name clash with ``parrot.bots.database.toolkits.base.DatabaseToolkit``.

Migration:

    # Before (deprecated):
    from parrot.tools.database import DatabaseToolkit

    # After:
    from parrot.tools.databasequery import DatabaseQueryToolkit

This shim will be removed in a future major release.
