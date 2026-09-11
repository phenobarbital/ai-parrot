# TASK-3163: Snippet source protocol & stable resolver closure — `services/snippets/base.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. This is the module that makes the hybrid dual-source
design (OQ-1) work at all. The registry has **no unregister API** —
`register_form_event()` raises `ValueError` on a duplicate
`(tenant, handler_ref)` (`event_registry.py:135-139`), and the only removal
path is the test-only `_clear_event_registry_for_tests()`. That means a DB
snippet cannot simply re-register itself every time a tenant admin
publishes a new version.

The fix: register **one stable resolver closure** per `(tenant,
handler_ref)`, exactly once, at load time. The closure itself does the
version lookup on every dispatch, through whatever store owns that
`(tenant, handler_ref)`. Re-publishing swaps the underlying data; the
registry entry — and the fact that `register_form_event()` was ever called
for that key — never changes again.

This module exists specifically so OQ-1 (storage model) can be revisited
later at the cost of reimplementing `SnippetSourceProtocol`, not the whole
architecture (spec §3 M3 note).

---

## Scope

- Define `SnippetSourceProtocol` (a `typing.Protocol`) that both the git
  loader (TASK-3164) and the DB store (TASK-3165) implement: a single
  async method that resolves the *currently published* `SnippetBundle` for
  a `(tenant, handler_ref)` key, or `None`.
- Implement `make_resolver_adapter(source, tenant, handler_ref)` — builds
  the async closure that: (a) looks up the current bundle via the source,
  (b) converts the live `FormEventContext` to a `SandboxContext` (calling
  a `Callable` hook, since the real `ContextProjector` is TASK-3167 and
  does not exist yet — inject it as a parameter, do not import it here),
  (c) executes it (also injected as a `Callable`, since `TierRouter` is
  TASK-3172), (d) returns an `EventResolution | None` or raises
  `FormEventAbort`, matching `FormEventHandler`'s exact signature so
  `register_form_event()` accepts it unmodified.
- Implement `register_resolver(handler_ref, *, tenant, source, ...)` — the
  function the loaders call exactly once per key; wraps
  `register_form_event()` and re-raises its `ValueError` unchanged (the
  duplicate-ref guard IS the two-snippets-one-ref guard, per spec §3 M4).
- Write `packages/parrot-formdesigner/tests/unit/test_snippet_resolver.py`.

**NOT in scope**: any concrete `SnippetSourceProtocol` implementation (git
loader is TASK-3164, DB store is TASK-3165); the real `ContextProjector`
and `TierRouter` (TASK-3167, TASK-3172) — this task takes them as injected
callables/parameters, never imports `services/sandbox/*`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/__init__.py` | CREATE | Empty package marker |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/base.py` | CREATE | `SnippetSourceProtocol`, resolver closure factory, `register_resolver()` |
| `packages/parrot-formdesigner/tests/unit/test_snippet_resolver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Protocol
from parrot_formdesigner.core.snippets import SnippetBundle, SnippetStatus  # TASK-3161
from parrot_formdesigner.core.events import FormEventContext, EventResolution, FormEventAbort
from parrot_formdesigner.services.event_registry import (
    register_form_event,   # verified: services/event_registry.py:73
    FormEventHandler,       # verified: services/event_registry.py:57
)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py
FormEventHandler = Callable[..., Awaitable[EventResolution | None]]   # line 57
_EVENT_REGISTRY: dict[tuple[str | None, str], FormEventHandler] = {}  # line 65

def register_form_event(                                    # line 73
    handler_ref: str, *, tenant: str | None = None,
) -> Callable[[FormEventHandler], FormEventHandler]: ...
    # Raises ValueError on duplicate (tenant, handler_ref) — line 136.
    # Raises TypeError if the decorated function is not a coroutine
    #   function (asyncio.iscoroutinefunction check) — line 129.
    # The decorator wraps a plain async def and returns it unchanged —
    #   there is no way to "register a lambda", the target must be
    #   `asyncio.iscoroutinefunction(fn)` True.

def get_form_event(handler_ref: str, *, tenant: str | None = None) -> FormEventHandler: ...  # line 149
    # Resolution: (tenant, ref) -> (None, ref) -> KeyError

# packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
class FormEventContext(BaseModel):                          # line 106
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    event: FormEventName
    form_id: str
    tenant: str | None
    auth_context: Any                              # line 128 — LIVE object, never serialise
    payload: Mapping[str, Any] | None = None
    schema_dump: Mapping[str, Any] | None = None
    error: BaseException | None = None
    user_message: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

class FormEventAbort(Exception):                            # line 201
    def __init__(self, reason: str, *, user_message: str, status_code: int = 403) -> None: ...
```

### Does NOT Exist
- ~~`unregister_form_event` / `override_form_event`~~ — do not exist. The
  registry exposes only `register_form_event`, `get_form_event`,
  `list_form_events`, and the test-only `_clear_event_registry_for_tests()`
  (`event_registry.py:206`). **Never** attempt to mutate `_EVENT_REGISTRY`
  directly from this module — that would bypass the duplicate-ref guard
  this whole design relies on.
- ~~`services/sandbox/`~~ — does not exist yet (TASK-3167+ create it). This
  module must not import from it; `ContextProjector`/`TierRouter` are
  received as constructor/factory parameters (dependency injection), not
  imports, to avoid a forward dependency on unwritten modules.
- ~~`services/snippets/git_loader.py`~~, ~~`db_store.py`~~ — created by
  TASK-3164/TASK-3165, which import FROM this module, not the reverse.

---

## Implementation Notes

### Key Constraints
- Register **exactly once** per `(tenant, handler_ref)` — the resolver
  closure must not be re-registered on republish. This is the single most
  important invariant in the whole feature; get the test for it
  (`test_resolver_registers_once_per_key`) passing before anything else.
- The closure returned to `register_form_event()` must match
  `FormEventHandler`'s signature exactly: `async def(ctx: FormEventContext)
  -> EventResolution | None`, so `dispatch()` (unmodified, per G10) can
  call it like any hand-written handler.
- A `FormEventAbort` raised inside the closure must propagate unchanged —
  do not catch and wrap it; `dispatch()` already expects to catch
  `FormEventAbort` from ordinary handlers (spec §2 "the closure resolves
  the currently-published bundle... From the dispatcher's perspective,
  git-backed snippets are ordinary registered handlers").
- No knowledge of tiers, pools, or the broker belongs here — this module's
  job ends at "resolve the current bundle, hand it and a projected context
  to injected callables, translate the outcome back to
  `EventResolution`/`FormEventAbort`".

### References in Codebase
- `services/event_registry.py:73-146` — the decorator and duplicate guard
  this module wraps, shown in full above.
- `services/callback_registry.py` — cited by `event_registry.py`'s own
  docstring as the sibling pattern this registry mirrors; consult if the
  resolver-closure shape is unclear.

---

## Implementation Blueprint

### Steps (in order)
1. Define `SnippetSourceProtocol` — *why*: TASK-3164 and TASK-3165 both
   need a shared shape to implement before either can be reviewed against
   this module.
2. Define `SandboxExecutor` and `ContextProjectorFn` as `Protocol`/`Callable`
   type aliases for the two injected dependencies — *why*: keeps this
   module's public API decoupled from TASK-3167/TASK-3172's concrete
   classes, which do not exist yet.
3. Implement `make_resolver_adapter()` — *why*: the core closure factory.
4. Implement `register_resolver()` — *why*: the one call site loaders use;
   wrapping it (rather than calling `register_form_event` directly from
   each loader) keeps "register exactly once" enforceable in one place.
5. Write and run the tests, focusing first on
   `test_resolver_registers_once_per_key` and `test_resolver_survives_republish`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/base.py` (CREATE)
```python
"""Snippet source protocol and the stable resolver closure (FEAT-459 / M3).

The event registry (services/event_registry.py) has no unregister API —
register_form_event() raises ValueError on a duplicate (tenant,
handler_ref). This module is why a DB-backed snippet can be re-published
without hitting that guard: exactly ONE resolver closure is registered per
key, and the closure looks up the CURRENT bundle on every dispatch through
whatever SnippetSourceProtocol implementation owns that key.

See spec sdd/specs/formbuilder-custom-code.spec.md §2 "Dual-source
storage" and §3 Module 3.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventContext,
)
from parrot_formdesigner.core.snippets import SandboxContext, SandboxOutcome, SnippetBundle
from parrot_formdesigner.services.event_registry import register_form_event

logger = logging.getLogger(__name__)


class SnippetSourceProtocol(Protocol):
    """What both the git loader (TASK-3164) and DB store (TASK-3165) implement."""

    async def resolve_current(
        self, *, tenant: str | None, handler_ref: str
    ) -> SnippetBundle | None:
        """Return the currently published bundle for this key, or None.

        Called on EVERY dispatch by the resolver closure — implementations
        must be cheap (a read-through cache for DB; an in-memory dict for
        git, since git bundles never change without a redeploy).
        """
        ...


# Injected dependency type aliases — kept as Callable/Protocol so this
# module has no import-time dependency on services/sandbox/* (TASK-3167,
# TASK-3172), which do not exist when this task is implemented.
ContextProjectorFn = Callable[[FormEventContext, SnippetBundle], Awaitable[SandboxContext]]
SandboxExecutorFn = Callable[[SnippetBundle, SandboxContext], Awaitable[SandboxOutcome]]


def make_resolver_adapter(
    source: SnippetSourceProtocol,
    *,
    tenant: str | None,
    handler_ref: str,
    project_context: ContextProjectorFn,
    execute: SandboxExecutorFn,
) -> Callable[[FormEventContext], Awaitable[EventResolution | None]]:
    """Build the FormEventHandler-shaped closure registered exactly once.

    Args:
        source: Resolves the current SnippetBundle for (tenant, handler_ref)
            on every call — see SnippetSourceProtocol.
        tenant: The tenant this closure is registered under (None = global).
        handler_ref: The handler_ref this closure answers for.
        project_context: Converts the live FormEventContext + resolved
            bundle into a serialisable SandboxContext (TASK-3167's
            ContextProjector.project, injected — never imported here).
        execute: Runs the bundle against the projected context and returns
            a SandboxOutcome (TASK-3172's TierRouter.execute, injected).

    Returns:
        An async callable matching FormEventHandler's signature, suitable
        for register_form_event().

    Raises:
        SnippetNotApprovedError: via `source.resolve_current` returning a
            non-PUBLISHED bundle — FILL IN: decide whether this closure
            checks status itself or trusts the source to only return
            PUBLISHED bundles (bounded by test_draft_never_executes, M6).
    """

    async def _resolver(ctx: FormEventContext) -> EventResolution | None:
        bundle = await source.resolve_current(tenant=tenant, handler_ref=handler_ref)
        if bundle is None:
            # FILL IN: decide the correct failure mode when the resolver
            #   fires but no bundle currently resolves (e.g. a DB snippet
            #   was revoked with no git fallback) — bounded by spec §7
            #   "revoked snippet falls back to git" (only applies when a
            #   fallback actually exists; this closure only ever answers
            #   for ONE specific tenant slot, the fallback-to-global case
            #   is handled by get_form_event()'s own precedence, not here).
            raise RuntimeError(
                f"snippet resolver for (tenant={tenant!r}, handler_ref={handler_ref!r}) "
                "found no currently resolvable bundle"
            )
        sandbox_ctx = await project_context(ctx, bundle)
        outcome = await execute(bundle, sandbox_ctx)
        # FILL IN: translate `outcome` (SandboxOutcome) into either a
        #   returned EventResolution or a raised FormEventAbort —
        #   bounded by: exactly one of outcome.resolution/outcome.abort is
        #   set (SandboxOutcome's documented invariant, TASK-3161); an
        #   abort must raise FormEventAbort(reason=..., user_message=...,
        #   status_code=...) built from outcome.abort, unchanged in
        #   substance (test_router_abort_rehydrates_exception, M12 — but
        #   this closure is the actual rehydration site since it is what
        #   dispatch() calls).
        raise NotImplementedError

    return _resolver


def register_resolver(
    handler_ref: str,
    *,
    tenant: str | None,
    source: SnippetSourceProtocol,
    project_context: ContextProjectorFn,
    execute: SandboxExecutorFn,
) -> None:
    """Register the stable resolver closure for (tenant, handler_ref).

    Call this EXACTLY ONCE per key at loader startup — never on republish.
    Re-raises register_form_event()'s ValueError unchanged on a duplicate
    key; that guard IS the two-snippets-one-ref safety check (spec §3 M4).

    Args:
        handler_ref: Logical handler reference, e.g. "survey_v1.onBeforeSubmit".
        tenant: None for a git-backed platform snippet; a tenant slug for
            a DB-backed tenant snippet.
        source: The SnippetSourceProtocol owning this key.
        project_context: See make_resolver_adapter.
        execute: See make_resolver_adapter.

    Raises:
        ValueError: Propagated from register_form_event() on a duplicate
            (tenant, handler_ref) — do not catch it here.
    """
    adapter = make_resolver_adapter(
        source,
        tenant=tenant,
        handler_ref=handler_ref,
        project_context=project_context,
        execute=execute,
    )
    register_form_event(handler_ref, tenant=tenant)(adapter)
    logger.info(
        "registered snippet resolver for (tenant=%r, handler_ref=%r)", tenant, handler_ref
    )
```
**Why this shape**: `project_context`/`execute` are injected callables
rather than imports specifically to let this module be implemented,
reviewed, and tested (with fakes) *before* TASK-3167 and TASK-3172 exist —
this is what the spec's Worktree Strategy Phase 1 relies on. The
`_resolver` closure's `FormEventContext -> EventResolution | None` shape
is fixed by `FormEventHandler` and must not change: `register_form_event`
type-checks via `asyncio.iscoroutinefunction`, and `dispatch()` expects
exactly this signature.

### `packages/parrot-formdesigner/tests/unit/test_snippet_resolver.py` (CREATE)
```python
"""Unit tests for services/snippets/base.py — FEAT-459 / TASK-3163."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.events import EventResolution, FormEventContext
from parrot_formdesigner.core.snippets import (
    CapabilityManifest,
    CapabilityTier,
    SandboxContext,
    SandboxOutcome,
    SnippetBundle,
    SnippetSource,
)
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    get_form_event,
)
from parrot_formdesigner.services.snippets.base import register_resolver


@pytest.fixture(autouse=True)
def _clear_registry():
    _clear_event_registry_for_tests()
    yield
    _clear_event_registry_for_tests()


class _FakeSource:
    def __init__(self, bundle: SnippetBundle | None) -> None:
        self.bundle = bundle
        self.resolve_calls = 0

    async def resolve_current(self, *, tenant, handler_ref) -> SnippetBundle | None:
        self.resolve_calls += 1
        return self.bundle


def _bundle() -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT,
        handler_ref="survey_v1.onBeforeSubmit",
        event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=CapabilityTier.PURE),
        python_source="def run(): ...",
        python_sha256="a" * 64,
    )


async def _fake_project(ctx: FormEventContext, bundle: SnippetBundle) -> SandboxContext:
    return SandboxContext(event=ctx.event, form_id=ctx.form_id, tenant=ctx.tenant, claims={})


async def _fake_execute(bundle: SnippetBundle, ctx: SandboxContext) -> SandboxOutcome:
    return SandboxOutcome(resolution=EventResolution(), duration_ms=1.0)


def test_resolver_registers_once_per_key() -> None:
    source = _FakeSource(_bundle())
    register_resolver(
        "survey_v1.onBeforeSubmit",
        tenant=None,
        source=source,
        project_context=_fake_project,
        execute=_fake_execute,
    )
    with pytest.raises(ValueError):
        register_resolver(
            "survey_v1.onBeforeSubmit",
            tenant=None,
            source=source,
            project_context=_fake_project,
            execute=_fake_execute,
        )


async def test_resolver_survives_republish() -> None:
    """Swapping `source.bundle` changes behaviour with NO re-registration."""
    # FILL IN: register_resolver once, call get_form_event(...)(ctx) twice
    #   with source.bundle mutated between calls (e.g. bump version), assert
    #   no ValueError on the second dispatch and no second register call —
    #   bounded by spec's "resolver survives republish" invariant.
    pass


async def test_resolver_calls_injected_project_and_execute() -> None:
    source = _FakeSource(_bundle())
    register_resolver(
        "survey_v1.onBeforeSubmit",
        tenant=None,
        source=source,
        project_context=_fake_project,
        execute=_fake_execute,
    )
    handler = get_form_event("survey_v1.onBeforeSubmit")
    ctx = FormEventContext(
        event="onBeforeSubmit", form_id="f1", tenant=None, auth_context=None
    )
    result = await handler(ctx)
    assert isinstance(result, EventResolution)
    assert source.resolve_calls == 1
```
**Why**: the registration-once and injected-callable tests are written in
full since they are what makes the whole dual-source design work; the
republish test is stubbed because it depends on `_resolver`'s FILL IN
translation logic being complete first.

### FILL IN checklist
- [ ] `base.py::make_resolver_adapter._resolver` — the "no bundle resolves" branch and the outcome→`EventResolution`/`FormEventAbort` translation; bounded by `SandboxOutcome`'s documented invariant and `test_router_abort_rehydrates_exception`
- [ ] `test_resolver_survives_republish` — full test body; bounded by the resolver-closure design itself

---

## Acceptance Criteria

- [ ] `register_resolver()` calls `register_form_event()` exactly once per `(tenant, handler_ref)`; a second call for the same key raises `ValueError`
- [ ] The registered closure's signature matches `FormEventHandler` exactly and is accepted by `register_form_event()` without a `TypeError`
- [ ] Mutating the fake source's bundle between two dispatches changes the outcome without a second registration call (`test_resolver_survives_republish`)
- [ ] A `FormEventAbort`-equivalent outcome (`SandboxOutcome.abort` set) is rehydrated and raised, not swallowed
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_snippet_resolver.py -v`
- [ ] `ruff check` and `mypy` clean on `services/snippets/base.py`

---

## Test Specification

See the blueprint's test file above — 3 test functions, 1 fully stubbed plus one FILL IN inside a written test.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "Dual-source storage" — the resolver-closure paragraph, §3 Module 3)
2. **Check dependencies** — TASK-3161 must be `done` (imports `core/snippets.py`)
3. **Verify the Codebase Contract** — confirm `register_form_event` still raises `ValueError` on duplicate keys at `event_registry.py:135-139`
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3163-snippet-source-protocol-resolver.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
