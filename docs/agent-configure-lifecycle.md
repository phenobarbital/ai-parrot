# Agent Configure Lifecycle

> **Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
> **Spec**: [sdd/specs/double-configure-agents.spec.md](../sdd/specs/double-configure-agents.spec.md)

This document describes what `AbstractBot.configure()` guarantees and the contract
`configure()` / `post_configure()` overrides must follow so an agent can be configured
more than once in one process.

---

## 1. `configure()` is idempotent per instance

A second call to `configure()` on the same bot instance is a logged no-op when the
resolved app is the same object as the one already bound (including both being `None`).
The idempotency is enforced by an entry counter (`self._configure_count`) that is
incremented on each call. When `configure_count > 1` and the app is unchanged, the
method returns immediately with an INFO log.

A genuine reconfiguration occurs when a new app arrives where none was bound before
(e.g., CLI first, server later). In that case the full pipeline runs again, and
`post_configure()` is called a second time.

The `finally` contract is unchanged: `_configured` is always flipped to `True`,
so a failed configure is not retried blindly.

---

## 2. Forcing a re-run: `reconfigure()`

`reconfigure(app=None)` is the only supported way to force a re-run of the configure
pipeline on a live instance. It resets the idempotency counter to 0 and then awaits
`configure(app)` (or the bound app if `app` is not provided). This is the explicit
escape hatch for deliberate reconfiguration.

---

## 3. `post_configure()` must be re-entrant

`post_configure()` is called once per `configure()` that actually runs its pipeline,
and again by `reconfigure()`. An override MUST be safe to run more than once per
instance. The recommended pattern is to **adopt** an already-registered toolkit
instead of building a fresh one.

```python
async def post_configure(self) -> None:
    await super().post_configure()
    working_memory = self.tool_manager.find_registered_toolkit(WorkingMemoryToolkit)
    if working_memory is None:
        working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-wm")
        self.tool_manager.register_toolkit(working_memory)
    self.working_memory = working_memory
```

This ensures `self.working_memory` always names the toolkit the `ToolManager` serves,
and prevents building a second authenticated client.

---

## 4. Adopting a toolkit: `find_registered_toolkit()`

`ToolManager.find_registered_toolkit(toolkit_cls, *, tool_prefix=None)` returns the
registered instance of `toolkit_cls`, or `None` if none is registered. It matches on
the exact class (never a subclass) and, when `tool_prefix` is given, on an equal
`tool_prefix`. This is the recommended way to adopt a toolkit in `post_configure()`.

---

## 5. Keep-first: the manager wins

`ToolManager.register_toolkit()` implements a keep-first policy: when a toolkit of
the same exact class and the same `tool_prefix` is already registered, the already
registered tools are returned and nothing is mutated. The candidate is not even
constructed when it was passed as a name or a class, so no second pool/session is
opened.

A name claimed by a different owner still raises `ToolNameCollisionError`. Two
instances of the same class under different prefixes both register (no keep-first).

If you extend a list with the returned tools, de-duplicate by name to avoid
duplicates in `self.tools`.

---

## 6. Work after `super().configure()`

Subclass overrides that do their own work AFTER `await super().configure(app)` should
guard it with `if self.configure_count > 1: return`. This prevents the work from
running on a second configure() call that is a no-op.

---

## 7. Not a concurrency guarantee

Two coroutines calling `configure()` on the same instance at the same time can both
pass the counter guard. Keep-first keeps that from raising. Concurrent configure of
different instances is fine.

The idempotency contract is per-instance, not per-process. If you need true
concurrency safety, gate the configure call with your own lock or use a fresh
instance for each concurrent path.
