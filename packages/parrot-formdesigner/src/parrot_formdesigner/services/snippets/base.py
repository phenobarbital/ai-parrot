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
        RuntimeError: If the source resolves no bundle at all for this key
            (e.g. a DB snippet was revoked with no fallback registered
            under this exact tenant slot — the fallback-to-global case is
            handled by get_form_event()'s own precedence, not here).
    """

    async def _resolver(ctx: FormEventContext) -> EventResolution | None:
        bundle = await source.resolve_current(tenant=tenant, handler_ref=handler_ref)
        if bundle is None:
            # No currently resolvable bundle for this exact (tenant,
            # handler_ref) slot. This closure only ever answers for ONE
            # specific slot; the fallback-to-global case (a revoked
            # tenant snippet falling back to a platform git snippet) is
            # handled entirely by get_form_event()'s own tenant->global
            # precedence (event_registry.py:149), not by this closure.
            # Reaching here with no bundle means the slot itself has
            # nothing to serve, which is a configuration error.
            raise RuntimeError(
                f"snippet resolver for (tenant={tenant!r}, handler_ref={handler_ref!r}) "
                "found no currently resolvable bundle"
            )
        sandbox_ctx = await project_context(ctx, bundle)
        outcome = await execute(bundle, sandbox_ctx)
        # Exactly one of outcome.resolution / outcome.abort is set
        # (SandboxOutcome's documented invariant, TASK-3161). An abort is
        # rehydrated into FormEventAbort and raised unchanged in substance
        # so dispatch() (which already expects to catch FormEventAbort
        # from ordinary handlers) behaves identically to a hand-written
        # handler raising it directly.
        if outcome.abort is not None:
            raise FormEventAbort(
                outcome.abort.reason,
                user_message=outcome.abort.user_message,
                status_code=outcome.abort.status_code,
            )
        return outcome.resolution

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
