---
id: F001
query: "RequestBot class definition"
type: read
file: packages/ai-parrot/src/parrot/utils/helpers.py
lines: 43-78
---

RequestBot is a dynamic proxy using `__getattr__` to intercept all method calls on
the delegate (AbstractBot) and inject `ctx` into kwargs. Handles both async and sync
methods. Only injects if `ctx` not already present. Non-callable attributes pass through.

Key: this is a **runtime proxy**, not a subclass. It creates wrapper closures on every
attribute access, which has performance and introspection implications (__doc__, __name__,
type hints are lost on wrapped methods).
