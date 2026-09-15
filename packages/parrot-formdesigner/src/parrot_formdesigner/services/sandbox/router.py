"""Tier router: selects the cheapest executor and applies on_failure (FEAT-459 / M12).

Converges Track 2: given a SnippetBundle and a live FormEventContext (via
the injected ContextProjector), routes to SubprocessWorkerPool (tiers
1-2) or GVisorWorkerPool (tiers 3-4), validates the returned
EventResolution, rehydrates an AbortSignal into FormEventAbort, and
applies the on_failure policy (TASK-3162's FormEventBinding.on_failure).

MUST NOT import or reference the FEAT-188 dispatch entry point module —
this class is called FROM a TASK-3163 resolver closure, which that
module's dispatch() (unmodified, G10) sees as an ordinary registered
handler.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

from parrot.eval.sandbox.base import SandboxProvider, SandboxSpec
from parrot_formdesigner.core.events import EventResolution, FormEventAbort
from parrot_formdesigner.core.snippets import (
    AbortSignal,
    CapabilityTier,
    SandboxContext,
    SandboxOutcome,
    SnippetBundle,
)

logger = logging.getLogger(__name__)


class TierRouter:
    """Routes a SnippetBundle to its cheapest satisfying executor.

    Post-review correction (code review of this feature's first pass —
    both an independent Claude subagent and an adversarial `codex`
    cross-check, 2026-09-11): `execute()` originally took the LIVE
    `FormEventContext` and performed its own projection via an owned
    `ContextProjector`. That contradicted the spec's own declared
    `TierRouter.execute(bundle, ctx: SandboxContext)` interface AND
    `services/snippets/base.py`'s actual resolver closure (TASK-3163),
    which already projects the live context via the INJECTED
    `project_context` callable before calling `execute(bundle,
    sandbox_ctx)`. Passing an already-projected `SandboxContext` into a
    parameter that then tried to re-project it raised `AttributeError`
    at tier >= 2 (`SandboxContext` has no `auth_context`). Fixed by
    accepting the pre-projected `SandboxContext` directly and dropping
    the internal projection entirely — projection now has exactly ONE
    owner (the resolver closure), matching both the spec text and
    `base.py`'s tested behavior.
    """

    def __init__(
        self,
        subprocess_pool: SandboxProvider,
        gvisor_pool: SandboxProvider | None,
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
        """
        self._subprocess_pool = subprocess_pool
        self._gvisor_pool = gvisor_pool
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

    async def _run_on_sandbox(self, sandbox: Any, bundle: SnippetBundle, sandbox_ctx: Any) -> SandboxOutcome:
        """Call the acquired Sandbox's forms-specific run method.

        Kept as its own method (rather than inlined in execute()) so
        tests can monkeypatch this single seam instead of needing a real
        pool/worker. Both SubprocessWorkerPool's and GVisorWorkerPool's
        Sandbox implementations are expected to expose `run_snippet()`
        (see TASK-3169's `_SubprocessSandbox.run_snippet`); this is
        called by name (duck-typed against the Sandbox ABC extension)
        rather than importing either concrete pool module here.
        """
        return await sandbox.run_snippet(sandbox_ctx)

    async def execute(self, bundle: SnippetBundle, ctx: SandboxContext) -> SandboxOutcome:
        """Run `bundle` against an already-projected `ctx`, returning the raw outcome.

        Args:
            bundle: The snippet to run.
            ctx: An ALREADY-PROJECTED SandboxContext — the caller (a
                TASK-3163 resolver closure) owns projection via its own
                injected ContextProjector before calling this method.
                This method does NOT project; passing a live
                FormEventContext here would fail at the pool boundary
                (SandboxContext and FormEventContext are distinct,
                unrelated Pydantic models).

        Returns:
            SandboxOutcome with exactly one of resolution/abort set, even
            on a worker-side failure — a raised exception (including a
            timeout, or a downstream Sandbox not yet exposing
            run_snippet) is caught and converted into
            SandboxOutcome(abort=AbortSignal(...)), so execute() itself
            never raises for an ordinary snippet failure; only
            execute_with_policy() decides whether that becomes a raised
            FormEventAbort or a logged continue.
        """
        pool = self._pool_for_tier(bundle.manifest.tier)
        started = time.monotonic()
        try:
            sandbox = await pool.acquire(SandboxSpec())
        except Exception:
            # Post-review fix: acquisition failure (PoolExhaustedError,
            # ColdStartTimeoutError, ...) used to escape execute()
            # uncaught, breaking the "execute() never raises" invariant
            # even for on_failure="continue". Nothing was acquired, so
            # there is nothing to release.
            self.logger.exception("snippet %s failed to acquire a sandbox worker", bundle.handler_ref)
            duration_ms = (time.monotonic() - started) * 1000
            return SandboxOutcome(
                abort=AbortSignal(
                    reason=f"sandbox acquisition failed for {bundle.handler_ref!r}",
                    user_message="An internal error occurred.",
                    status_code=500,
                ),
                duration_ms=duration_ms,
            )
        try:
            timeout_s = bundle.manifest.timeout_ms / 1000.0
            try:
                raw_outcome = await asyncio.wait_for(self._run_on_sandbox(sandbox, bundle, ctx), timeout=timeout_s)
            except Exception:
                # Any failure — timeout, worker crash, or a Sandbox
                # implementation not (yet) exposing run_snippet — is
                # logged internally with its traceback and NEVER
                # surfaced to the end user (spec §7 risk table).
                self.logger.exception("snippet %s failed during sandbox execution", bundle.handler_ref)
                duration_ms = (time.monotonic() - started) * 1000
                return SandboxOutcome(
                    abort=AbortSignal(
                        reason=f"sandbox execution failed for {bundle.handler_ref!r}",
                        user_message="An internal error occurred.",
                        status_code=500,
                    ),
                    duration_ms=duration_ms,
                )
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
            self.logger.error(
                "malformed SandboxOutcome (resolution_set=%s, abort_set=%s) — "
                "treating as failure, never partially applied",
                has_resolution,
                has_abort,
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
        ctx: SandboxContext,
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
            bundle.handler_ref,
            outcome.abort.reason if outcome.abort else None,
        )
        return EventResolution()
