---
id: F003
query: "AbstractBot.retrieval() context manager"
type: read
file: packages/ai-parrot/src/parrot/bots/abstract.py
lines: 3103-3205
---

The SOLE creation point for RequestBot. Creates RequestContext from params, wraps
delegate in RequestBot, enforces PBAC policies, and yields under a semaphore.

Critical responsibilities bundled here:
1. RequestContext instantiation
2. RequestBot wrapping
3. PBAC policy enforcement (lines ~3141-3197)
4. Concurrency limiting via self._semaphore

The session() replacement must account for all four responsibilities.
