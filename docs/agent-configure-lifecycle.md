# Agent Configure Lifecycle

> **Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
> **Spec**: [sdd/specs/double-configure-agents.spec.md](../sdd/specs/double-configure-agents.spec.md)
>
> **Feature**: FEAT-726 — Configure-Override Idempotency (§6, §8)
> **Spec**: [sdd/specs/bots-agent-tech-debt.spec.md](../sdd/specs/bots-agent-tech-debt.spec.md)

This document describes what `AbstractBot.configure()` guarantees and the contract
`configure()` / `post_configure()` overrides must follow so an agent can be configured
more than once in one process.

---

## 1. `configure()` is idempotent per instance

A second call to `configure()` on the same bot instance is a logged no-op when the
resolved app is the same object as the one already bound (including both being `None`).
The idempotency is enforced by an entry counter (`self._configure_count`) that is
incremented on each call: when at least one entry has already happened and the app is
unchanged, the method returns immediately with an INFO log. The condition itself lives
in exactly one place, `configure_is_noop()` (§8), which `configure()` calls.

A genuine reconfiguration occurs when a new app arrives where none was bound before
(e.g., CLI first, server later). In that case the full pipeline runs again, and
`post_configure()` is called a second time.

**Subclass overrides do not re-derive this condition.** They read the decision the
base publishes: `configure_skipped` after the `super()` call (§6), or
`configure_is_noop(app)` before it (§8). The counter is not the guard.

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

## 6. Work after `super().configure()`: `configure_skipped`

A subclass override that does its own work AFTER `await super().configure(app)` must
skip that work when the base call was an idempotent no-op. Read `configure_skipped`:

```python
async def configure(self, app=None) -> None:
    await super().configure(app)
    if self.configure_skipped:
        return
    ...  # own setup
```

`configure_skipped` is `True` only when the entry that just returned skipped the
pipeline. It is `False` before the first `configure()`, after any entry that ran the
pipeline, and after `reconfigure()`.

> **Do not use `if self.configure_count > 1: return`.** Earlier revisions of this
> document and of the `configure()` docstring prescribed exactly that, and it is
> wrong. On the CLI-then-server path — an app arriving where none was bound before —
> the base runs its **full pipeline** with `configure_count == 2`. An override guarded
> on the counter would skip its own setup on a configure that genuinely ran, trading a
> double-run bug for a silent missing-setup bug. `configure_count` is still public and
> fine to read for diagnostics; it is just not the guard.

The nine overrides on this path are `BasicAgent`, `FirefliesInsightsAgent`,
`FirefliesObsidianAgent`, `WebAgent`, `DocumentAgent`, `OrchestratorAgent`,
`A2AOrchestratorAgent`, `A2AAgent` and `ComputerAgent`.

---

## 7. Not a concurrency guarantee

Two coroutines calling `configure()` on the same instance at the same time can both
pass the counter guard. Keep-first keeps that from raising. Concurrent configure of
different instances is fine.

The idempotency contract is per-instance, not per-process. If you need true
concurrency safety, gate the configure call with your own lock or use a fresh
instance for each concurrent path.

---

## 8. Work before `super().configure()`: `configure_is_noop()`

An override that does its own work BEFORE `await super().configure(app)` cannot use
`configure_skipped` — by the time the base returns, the work has already run. It asks
in advance instead:

```python
async def configure(self, app=None) -> None:
    if self.configure_is_noop(app):
        await super().configure(app)   # keeps the counter and the INFO log truthful
        return
    ...  # own setup
    await super().configure(app)
```

`configure_is_noop(app)` is `True` when a `configure(app)` call made right now would
early-return. It is deliberately a plain `def`, not a coroutine, so it can be consulted
before the override's first `await`. The question is **prospective** — "would a call
made now be a no-op?" — so it tests `configure_count >= 1`, not `> 1`, and
`configure()` itself calls it before incrementing. A caller outside `configure()` and
`configure()` itself therefore get the same answer.

Note the `super().configure(app)` call on the no-op path: it looks redundant and is
not. Returning without it would skip the entry-counter increment and the INFO log, and
leave `configure_count` under-counting — which `configure_is_noop` itself reads.

The three overrides on this path are `Chatbot`, `VoiceBot` and `DatabaseAgent`. Match
each site's existing call convention: `DatabaseAgent` calls
`await super().configure(app=app)`.

### Sites deliberately left unguarded

These need no guard. They are listed with their reasons so the inventory reads as
complete rather than unfinished — `tests/bots/test_configure_override_guards.py`
asserts they stay unguarded, so "completing" the fix here fails a test.

| Site | Why no guard |
|---|---|
| `bots/data.py` (`PandasAgent`) | its pre-super work self-gates on `if self._queries and not self.dataframes`, and `_sync_dataframes_from_dm()` is a pure re-sync |
| `bots/mixins/narrative.py` (`NarrativeMixin`) | pure cooperative passthrough — it awaits `super().configure()` and does nothing else |
| `bots/mixins/infographic_authoring.py` (`InfographicAuthoringMixin`) | its pre-super `set_bot()` is idempotent: `_inject_prompt_guidance` returns early on the sentinel `"## Infographic Generation Mode"` header already present in the prompt |

`bots/mixins/identity.py` also appears in a `grep` for `async def configure`, but that
match is inside the `IdentityMixin` class docstring's usage example, not code.

---

## 9. Full override inventory

To re-derive the lists above:

```bash
git grep -n 'async def configure' -- packages/ai-parrot/src packages/ai-parrot-tools/src
```

Filter the result to `AbstractBot` descendants (the MRO is `AbstractBot` → `BaseBot` →
`Chatbot` → `BasicAgent` → `Agent`; neither `BaseBot` nor `Agent` overrides
`configure`). Every hit must be one of: a guarded post-super site (§6), a guarded
pre-super site (§8), or a recorded exemption (§8). Anything else is an unclassified
site and a defect.
