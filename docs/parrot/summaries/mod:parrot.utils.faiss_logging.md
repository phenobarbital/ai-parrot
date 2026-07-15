---
type: Wiki Summary
title: parrot.utils.faiss_logging
id: mod:parrot.utils.faiss_logging
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Quiet FAISS's own import-time boot chatter.
relates_to:
- concept: func:parrot.utils.faiss_logging.quiet_faiss_loader
  rel: defines
---

# `parrot.utils.faiss_logging`

Quiet FAISS's own import-time boot chatter.

FAISS logs through its ``faiss.loader`` logger the first time ``import faiss``
runs in a process — probing the CPU instruction set and reporting which shared
library it loaded::

    [DEBUG] faiss.loader :: Environment variable FAISS_OPT_LEVEL is not set ...
    [INFO]  faiss.loader :: Loading faiss with AVX2 support.
    [INFO]  faiss.loader :: Could not load library with AVX2 support due to: ...
    [INFO]  faiss.loader :: Loading faiss.
    [INFO]  faiss.loader :: Successfully loaded faiss.

These are emitted once at first import and carry no actionable information for
AI-Parrot users. ``quiet_faiss_loader`` raises the ``faiss`` logger family to
WARNING so only genuine problems surface. Because Python loggers are singletons
by name, setting the level here persists even though FAISS creates the logger at
import time — call this BEFORE the first ``import faiss`` and the boot lines are
suppressed for the whole process.

Override via the ``FAISS_LOG_LEVEL`` environment variable (e.g. ``INFO`` to
restore the full boot chatter, ``DEBUG``, or a numeric level).

## Functions

- `def quiet_faiss_loader() -> None` — Raise the ``faiss`` logger to WARNING (or ``FAISS_LOG_LEVEL``). Idempotent.
