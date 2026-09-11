# TASK-3172: Tier router — `services/sandbox/router.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161, TASK-3162, TASK-3167, TASK-3168, TASK-3169, TASK-3170, TASK-3171
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12. This is where Track 2 (server sandbox) converges: given
a `SnippetBundle`, route to the cheapest executor satisfying its declared
tier (tier 1-2 → `SubprocessWorkerPool`, tier 3-4 → `GVisorWorkerPool`),
project the context (TASK-3167), execute, validate the returned
`EventResolution`, rehydrate an `AbortSignal` into `FormEventAbort`
(preserving FEAT-188 semantics — `onError` is NOT fired for an abort), and
apply the `on_failure` policy (TASK-3162) on any failure.

This is also the class TASK-3163's `make_resolver_adapter()` injects as
its `execute` callable — once this task lands, the resolver closures
built in TASK-3163/3164/3165 can be wired to a real `TierRouter` instance
instead of a test fake.

---

## Scope

- Implement `TierRouter` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/router.py`:
  `__init__(subprocess_pool, gvisor_pool)` and `async def execute(bundle,
  ctx) -> SandboxOutcome` per the spec §2 skeleton — but see the note
  below on layering `on_failure` handling.
- Add a second method, `async def execute_with_policy(bundle, ctx, *,
  on_failure) -> EventResolution | None` (raises `FormEventAbort`) that
  wraps `execute()` and applies the `on_failure` policy — this is what
  TASK-3163's resolver adapter should actually call (the spec's §2
  skeleton names only `execute()`, which returns the raw `SandboxOutcome`;
  the `on_failure` semantics are described in §3 Module 12's
  responsibility text and in §4's test list, but no single named method
  in §2 owns them — this task makes that ownership explicit).
- Validate that a returned `EventResolution` conforms (Pydantic already
  enforces this at construction, but a worker could return a raw dict
  that fails to parse — treat a validation failure as a router-level
  failure subject to `on_failure`, never a partial application).
- Write `packages/parrot-formdesigner/tests/unit/test_tier_router.py`.

**NOT in scope**: modifying `dispatch()` or `event_dispatcher.py` in any
way — `TierRouter` is invoked FROM a resolver closure (TASK-3163), which
`dispatch()` sees as an ordinary handler; this task must not import or
reference `event_dispatcher.py` at all (spec's repeated G10 warning: "Any
task that finds itself editing event_dispatcher.py has misunderstood the
design").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/router.py` | CREATE | `TierRouter` |
| `packages/parrot-formdesigner/tests/unit/test_tier_router.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.sandbox.base import SandboxProvider, SandboxSpec  # verified: parrot/eval/sandbox/base.py
from parrot_formdesigner.core.events import EventResolution, FormEventAbort  # verified: core/events.py:170,201
from parrot_formdesigner.core.snippets import (
    CapabilityTier, SandboxContext, SandboxOutcome, SnippetBundle,
)  # TASK-3161
from parrot_formdesigner.services.sandbox.projector import ContextProjector  # TASK-3167
```

### Existing Signatures to Use
```python
# spec §2 New Public Interfaces — the skeleton this task implements/extends:
class TierRouter:
    def __init__(
        self, subprocess_pool: SandboxProvider, gvisor_pool: SandboxProvider | None,
    ) -> None: ...
    async def execute(
        self, bundle: SnippetBundle, ctx: SandboxContext,
    ) -> SandboxOutcome: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
class EventResolution(BaseModel):                             # line 170
    model_config = ConfigDict(extra="forbid")
    payload: Mapping[str, Any] | None = None
    schema_overrides: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    user_message: str | None = None

class FormEventAbort(Exception):                              # line 201
    def __init__(self, reason: str, *, user_message: str, status_code: int = 403) -> None: ...
    # onError is deliberately NOT fired for FormEventAbort (FEAT-188 §7)

class FormEventBinding(BaseModel):                             # core/events.py:54, extended by TASK-3162
    on_failure: Literal["abort", "continue"] = "continue"      # governs a handler that RAN and FAILED
```

### Does NOT Exist
- ~~`services/sandbox/router.py`~~ — created by this task.
- ~~Any change to `event_dispatcher.dispatch()`~~ — MUST remain
  byte-for-byte unchanged (G10, spec §5 AC). This task never imports it.
- ~~A single spec-named method owning `on_failure`~~ — see Scope's note;
  this task introduces `execute_with_policy()` to make that ownership
  explicit since the spec's §2 skeleton is silent on it.

---

## Implementation Notes

### Key Constraints
- **Cheapest satisfying executor**: tier `PURE`/`HELPERS` → `subprocess_pool`;
  tier `BROKERED`/`TOOLKIT` → `gvisor_pool`. If a bundle requires
  `gvisor_pool` but it is `None` (constructor allows it, per the spec's
  own `gvisor_pool: SandboxProvider | None`), raise clearly — this is a
  configuration error the loader (TASK-3164) should have already
  prevented via `SnippetTierUnavailableError`, but the router must not
  silently downgrade or crash uninformatively if it somehow still
  receives such a bundle (defense in depth, same posture as TASK-3170's
  constructor).
- **Never partial application**: a malformed/unparseable resolution from
  a worker is a *failure*, handled identically to a raised exception or a
  timeout — never apply half of a resolution.
- **`FormEventAbort` rehydration must preserve reason/message/status
  exactly** — the abort came from `AbortSignal` (TASK-3161), a
  serializable mirror of `FormEventAbort`'s three constructor args.
- **`on_failure="continue"` returns an empty `EventResolution()`**, not
  `None` — re-read spec §5 AC: "`on_failure=\"continue\"` logs and
  proceeds with an empty resolution" (not "does nothing"). `dispatch()`
  (unmodified) presumably treats an empty `EventResolution()` the same as
  a handler returning nothing meaningful, which is why this distinction
  matters for a caller comparing return values.
- **`on_failure="abort"` re-raises through `dispatch()`** — meaning
  `execute_with_policy()` must itself *raise* `FormEventAbort` (or a
  synthesized one, message TBD by the implementer, bounded by "reject the
  submission") rather than return a sentinel value.

### References in Codebase
- `core/events.py:170-230` — `EventResolution`, `FormEventAbort`, shown above.

---

## Implementation Blueprint

### Steps (in order)
1. Implement `execute()` — tier-based pool selection, `acquire`/`release`
   via the `SandboxProvider` contract, delegate the actual run to
   whichever pool's forms-specific run method TASK-3169/3170 exposed
   (their own FILL IN — coordinate the exact method name/signature if it
   has not been finalized when this task starts).
2. Implement the `AbortSignal` → `FormEventAbort` rehydration helper.
3. Implement `execute_with_policy()`, wrapping `execute()` with the
   `on_failure` branch.
4. Write and run tests — this module has the largest test surface in the
   spec (7 named tests across `test_router_*`); prioritize
   `test_router_abort_rehydrates_exception` and
   `test_router_on_failure_abort`/`_continue` first since they encode the
   most spec-critical behavior.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/router.py` (CREATE)
```python
"""Tier router: selects the cheapest executor and applies on_failure (FEAT-459 / M12).

Converges Track 2: given a SnippetBundle and a live FormEventContext (via
the injected ContextProjector), routes to SubprocessWorkerPool (tiers
1-2) or GVisorWorkerPool (tiers 3-4), validates the returned
EventResolution, rehydrates an AbortSignal into FormEventAbort, and
applies the on_failure policy (TASK-3162's FormEventBinding.on_failure).

MUST NOT import or reference event_dispatcher.py — this class is called
FROM a TASK-3163 resolver closure, which dispatch() (unmodified, G10)
sees as an ordinary registered handler.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from pydantic import ValidationError

from parrot.eval.sandbox.base import SandboxProvider, SandboxSpec
from parrot_formdesigner.core.events import EventResolution, FormEventAbort, FormEventContext
from parrot_formdesigner.core.snippets import CapabilityTier, SandboxOutcome, SnippetBundle
from parrot_formdesigner.services.sandbox.projector import ContextProjector

logger = logging.getLogger(__name__)


class TierRouter:
    """Routes a SnippetBundle to its cheapest satisfying executor."""

    def __init__(
        self,
        subprocess_pool: SandboxProvider,
        gvisor_pool: SandboxProvider | None,
        *,
        projector: ContextProjector | None = None,
    ) -> None:
        """
        Args:
            subprocess_pool: Serves CapabilityTier.PURE/HELPERS.
            gvisor_pool: Serves CapabilityTier.BROKERED/TOOLKIT. May be
                None (e.g. gVisor unavailable); a bundle requiring it
                then raises RuntimeError rather than silently downgrading
                — the loader (TASK-3164) should already have refused
                such bundles at boot, so reaching this branch indicates a
                configuration bug, not routine unavailability.
            projector: Defaults to a fresh ContextProjector() if omitted.
        """
        self._subprocess_pool = subprocess_pool
        self._gvisor_pool = gvisor_pool
        self._projector = projector or ContextProjector()
        self.logger = logger

    def _pool_for_tier(self, tier: CapabilityTier) -> SandboxProvider:
        if tier in (CapabilityTier.PURE, CapabilityTier.HELPERS):
            return self._subprocess_pool
        if self._gvisor_pool is None:
            raise RuntimeError(
                f"bundle declares tier={tier!r} but no gVisor pool is configured — "
                "this should have been refused at load time (SnippetTierUnavailableError)"
            )
        return self._gvisor_pool

    async def execute(self, bundle: SnippetBundle, ctx: FormEventContext) -> SandboxOutcome:
        """Run `bundle` against the live `ctx`, returning the raw outcome.

        Note: takes the LIVE FormEventContext (not a pre-projected
        SandboxContext) so this method owns the projection step via the
        injected ContextProjector — keeping "when does projection happen"
        in one place rather than split between the resolver closure and
        this router.

        Returns:
            SandboxOutcome with exactly one of resolution/abort set, even
            on a worker-side failure (translate a raised exception or a
            failed EventResolution validation into
            SandboxOutcome(abort=AbortSignal(...)) — see FILL IN below —
            so execute() itself never raises for an ordinary snippet
            failure; only execute_with_policy() decides whether that
            becomes a raised FormEventAbort or a logged continue).
        """
        pool = self._pool_for_tier(bundle.manifest.tier)
        sandbox_ctx = await self._projector.project(ctx, bundle)
        started = time.monotonic()
        sandbox = await pool.acquire(SandboxSpec())
        try:
            # FILL IN: call whichever forms-specific run method
            #   TASK-3169/3170 exposed on the acquired Sandbox (e.g.
            #   `run_snippet(bundle, sandbox_ctx)`) — coordinate the
            #   exact name with those tasks; this call MUST be wrapped in
            #   a timeout derived from bundle.manifest.timeout_ms and
            #   MUST catch any raised exception, converting it to
            #   SandboxOutcome(abort=AbortSignal(reason=..., user_message=
            #   "An internal error occurred.", status_code=500),
            #   duration_ms=...) — the raw traceback is logged internally
            #   and NEVER surfaced to the end user (spec §7 risk table:
            #   "Traceback logged internally, never surfaced").
            raw_outcome: SandboxOutcome = ...  # type: ignore[assignment]
        finally:
            await pool.release(sandbox)
        duration_ms = (time.monotonic() - started) * 1000
        return self._validate_outcome(raw_outcome, duration_ms=duration_ms)

    def _validate_outcome(self, outcome: SandboxOutcome, *, duration_ms: float) -> SandboxOutcome:
        """Enforce SandboxOutcome's documented invariant: exactly one of
        resolution/abort is set. A malformed outcome is treated as a
        failure (never partially applied) — converted to an abort.
        """
        has_resolution = outcome.resolution is not None
        has_abort = outcome.abort is not None
        if has_resolution == has_abort:  # both set, or neither
            from parrot_formdesigner.core.snippets import AbortSignal

            self.logger.error(
                "malformed SandboxOutcome (resolution_set=%s, abort_set=%s) — "
                "treating as failure, never partially applied",
                has_resolution, has_abort,
            )
            return SandboxOutcome(
                abort=AbortSignal(
                    reason="malformed sandbox outcome",
                    user_message="An internal error occurred.",
                    status_code=500,
                ),
                duration_ms=duration_ms,
            )
        return outcome

    def _rehydrate_abort(self, outcome: SandboxOutcome) -> FormEventAbort:
        """AbortSignal -> FormEventAbort, preserving reason/message/status exactly."""
        assert outcome.abort is not None
        return FormEventAbort(
            outcome.abort.reason,
            user_message=outcome.abort.user_message,
            status_code=outcome.abort.status_code,
        )

    async def execute_with_policy(
        self,
        bundle: SnippetBundle,
        ctx: FormEventContext,
        *,
        on_failure: Literal["abort", "continue"],
    ) -> EventResolution | None:
        """Run `bundle`, applying `on_failure` to any failure outcome.

        Args:
            on_failure: From FormEventBinding.on_failure (TASK-3162).

        Returns:
            The EventResolution on success, or an empty EventResolution()
            when on_failure="continue" and execution failed.

        Raises:
            FormEventAbort: execution failed AND on_failure="abort" —
                this propagates up through the resolver closure
                (TASK-3163) and through dispatch() (unmodified) exactly
                as a hand-written handler's FormEventAbort would.
        """
        outcome = await self.execute(bundle, ctx)
        if outcome.resolution is not None:
            return outcome.resolution
        # outcome.abort is set (guaranteed by _validate_outcome's invariant)
        if on_failure == "abort":
            raise self._rehydrate_abort(outcome)
        self.logger.info(
            "snippet %s failed (reason=%r) but on_failure='continue' — proceeding with empty resolution",
            bundle.handler_ref, outcome.abort.reason if outcome.abort else None,
        )
        return EventResolution()
```
**Why this shape**: `execute()` never raises for an ordinary snippet
failure — every failure mode (timeout, exception, malformed resolution)
is normalized into `SandboxOutcome(abort=...)` inside `execute()`/
`_validate_outcome()`, so `execute_with_policy()`'s branch on
`outcome.resolution is not None` is the SINGLE place that decides whether
a failure becomes a raised exception or a logged continuation. This
separation is what makes `test_router_invalid_resolution_is_failure`
(a malformed return is "never partially applied") and
`test_router_on_failure_abort`/`_continue` (the same failure, routed two
different ways by one flag) both provable without duplicating failure-
detection logic in two places.

### `packages/parrot-formdesigner/tests/unit/test_tier_router.py` (CREATE)
```python
"""Unit tests for TierRouter — FEAT-459 / TASK-3172."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.events import EventResolution, FormEventAbort, FormEventContext
from parrot_formdesigner.core.snippets import (
    AbortSignal, CapabilityManifest, CapabilityTier, SandboxOutcome, SnippetBundle, SnippetSource,
)
from parrot_formdesigner.services.sandbox.router import TierRouter


def _bundle(tier: CapabilityTier) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT, handler_ref="f.onBeforeSubmit", event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=tier), python_source="def run(): ...",
        python_sha256="a" * 64,
    )


def _ctx() -> FormEventContext:
    return FormEventContext(event="onBeforeSubmit", form_id="f1", tenant=None, auth_context=None)


class _FakePool:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    async def acquire(self, spec):
        self.acquired += 1
        return object()

    async def release(self, sandbox):
        self.released += 1


async def test_router_selects_cheapest_tier() -> None:
    subprocess_pool, gvisor_pool = _FakePool(), _FakePool()
    router = TierRouter(subprocess_pool, gvisor_pool)
    # FILL IN: monkeypatch router's internal run call (the FILL IN inside
    #   execute()) to return a canned SandboxOutcome, then assert that a
    #   PURE-tier bundle acquires from subprocess_pool and a
    #   BROKERED-tier bundle acquires from gvisor_pool.
    pass


async def test_router_abort_rehydrates_exception() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    outcome = SandboxOutcome(
        abort=AbortSignal(reason="policy violation", user_message="Not allowed", status_code=403),
        duration_ms=1.0,
    )
    with pytest.raises(FormEventAbort) as excinfo:
        router._rehydrate_abort(outcome)
        raise excinfo.value  # re-raise for pytest.raises to catch cleanly in this pattern
    # FILL IN if the pattern above is awkward: call _rehydrate_abort
    #   directly (it's synchronous) inside pytest.raises(FormEventAbort)
    #   without the manual raise, then assert .reason/.user_message/.status_code.


def test_validate_outcome_rejects_both_set() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    malformed = SandboxOutcome(
        resolution=EventResolution(), abort=AbortSignal(reason="x", user_message="y"), duration_ms=1.0,
    )
    result = router._validate_outcome(malformed, duration_ms=1.0)
    assert result.abort is not None
    assert result.resolution is None


def test_validate_outcome_rejects_neither_set() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    malformed = SandboxOutcome(duration_ms=1.0)
    result = router._validate_outcome(malformed, duration_ms=1.0)
    assert result.abort is not None


async def test_router_on_failure_abort() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    # FILL IN: monkeypatch execute() to return a SandboxOutcome with
    #   abort set, call execute_with_policy(..., on_failure="abort"),
    #   assert pytest.raises(FormEventAbort).
    pass


async def test_router_on_failure_continue() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    # FILL IN: same setup as above but on_failure="continue"; assert the
    #   return value equals EventResolution() (empty, not None).
    pass


async def test_router_invalid_resolution_is_failure() -> None:
    # FILL IN: monkeypatch execute()'s internal worker-run step to return
    #   something that fails EventResolution validation (e.g. an extra
    #   field), assert the router treats it as a failure via
    #   _validate_outcome, never returning a partially-populated
    #   resolution.
    pass
```
**Why**: `_validate_outcome`'s two malformed-input tests are complete
since that method is pure and synchronous; the abort-rehydration test is
written with a noted awkwardness in the `pytest.raises` pattern (since
`_rehydrate_abort` is sync but the test file is async-first) — flagged
rather than silently "fixed" with an assumption about the test runner's
sync/async mixing rules. The remaining four are stubbed because they
require monkeypatching `execute()`'s FILL IN internal worker-run call,
which does not have a fixed shape until TASK-3169/3170's pool run-method
is finalized.

### FILL IN checklist
- [ ] `router.py::execute` — the actual pool-run call, coordinated with TASK-3169/3170's chosen method name
- [ ] `test_router_selects_cheapest_tier` — monkeypatch + assert pool selection
- [ ] `test_router_abort_rehydrates_exception` — clean up the `pytest.raises` pattern
- [ ] `test_router_on_failure_abort` / `_continue` — monkeypatch `execute()`, assert branch behavior
- [ ] `test_router_invalid_resolution_is_failure` — monkeypatch a malformed return

---

## Acceptance Criteria

- [ ] `_pool_for_tier` routes `PURE`/`HELPERS` to `subprocess_pool`, `BROKERED`/`TOOLKIT` to `gvisor_pool`
- [ ] A tier requiring `gvisor_pool` when it is `None` raises `RuntimeError`, never silently uses `subprocess_pool`
- [ ] `_validate_outcome` converts a `SandboxOutcome` with both or neither of `resolution`/`abort` set into a failure `abort`, never returning the malformed value unchanged
- [ ] `_rehydrate_abort` preserves `reason`/`user_message`/`status_code` exactly from `AbortSignal` to `FormEventAbort`
- [ ] `execute_with_policy(..., on_failure="abort")` raises `FormEventAbort` on any failure outcome
- [ ] `execute_with_policy(..., on_failure="continue")` returns `EventResolution()` (not `None`) on any failure outcome
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_tier_router.py -v`
- [ ] `ruff check` and `mypy` clean on `services/sandbox/router.py`
- [ ] `grep -c "event_dispatcher" services/sandbox/router.py` returns `0`

---

## Test Specification

See the blueprint's test file above — 7 test functions, 4 fully or partially stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 New Public Interfaces `TierRouter`, §3 Module 12, §7 risk table rows on failure handling, §5 G9/G10 ACs)
2. **Check dependencies** — TASK-3161, TASK-3162, TASK-3167, TASK-3168, TASK-3169, TASK-3170, TASK-3171 must all be `done`; confirm the exact forms-specific "run a snippet" method name/signature each pool ended up exposing before writing the FILL IN in `execute()`
3. **Verify the Codebase Contract** — confirm `FormEventAbort.__init__` and `EventResolution`'s fields are unchanged
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3172-tier-router.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
