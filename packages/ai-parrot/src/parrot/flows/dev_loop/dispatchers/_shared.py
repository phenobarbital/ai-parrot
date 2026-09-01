"""Shared exceptions, protocol, and session-host dual-publish shim for the
dev-loop code-agent dispatchers (FEAT-129/322).

Split out of the former monolithic ``dispatcher.py`` so each LLM client's
dispatcher lives in its own module; every per-provider module in this
package imports ``_SESSION_HOST_CTX`` / ``_apply_to_session_host`` from
here to fold ``DispatchEvent``s into the run's ``SessionHost``.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Optional, Protocol, Type, TypeVar

from pydantic import BaseModel

from parrot.flows.dev_loop.models import DispatchEvent
from parrot.flows.dev_loop.session_state import SessionHost, action_from_dispatch_event

T = TypeVar("T", bound=BaseModel)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dual-publish shim (FEAT-322 TASK-1852) — fold DispatchEvents into the run's
# SessionHost alongside the legacy XADD, with zero call-site fan-out.
#
# ``dispatch()`` gains an explicit ``session_host: Optional[SessionHost] =
# None`` kwarg (the per-dispatch value the spec requires — never dispatcher-
# instance state, since one dispatcher instance is shared across concurrent
# runs). Internally, threading that value positionally through every one of
# the ~40 ``self._publish_event(...)``/``_publish_*_event(...)`` call sites
# spread across 4 dispatcher classes' streaming helpers would be a large,
# error-prone rewrite of this hot, actively-churning file (FEAT-270/Moonshot
# work landed here in the last weeks — see spec §7 "Known Risks"). Instead,
# ``dispatch()`` binds the value into a ``ContextVar`` for the duration of
# its own call; ``_publish_event`` (the ONE choke point every dispatch kind
# already funnels through) reads it back. ``ContextVar`` values are copied
# per ``asyncio.Task`` at task-creation time, so concurrent dispatches on the
# SAME shared dispatcher instance (separate Tasks) never observe each
# other's host — the identical safety property explicit per-call-site
# threading would have given, with a 3-line touch per dispatch() method
# instead of a rewrite of every internal helper.
# ---------------------------------------------------------------------------

_SESSION_HOST_CTX: "contextvars.ContextVar[Optional[SessionHost]]" = contextvars.ContextVar(
    "dev_loop_session_host", default=None
)


def _owning_node_id(node_id: str) -> str:
    """Map a dispatch seat onto the flow node that owns it.

    Pool dispatches carry a worker seat (``"development.w1"``, and the
    merge-conflict ``"development.resolver"``), but ``session_state``'s
    ``NodeId`` is a closed ``Literal`` of flow node ids — a seat-keyed
    action fails validation and is swallowed, which is why a pooled
    ``development`` node reported 0 messages and 0 tool uses in the run
    bundle while its workers did all the work. Rolling the seat up to its
    node aggregates every worker's dispatch into the node they belong to
    — the same ``seat.split(".", 1)[0]`` convention the FEAT-479 usage
    ledger already uses. Node ids never contain a dot, so this is a no-op
    for every single-agent dispatch.

    Args:
        node_id: The dispatch seat as passed to ``dispatch()``.

    Returns:
        The owning flow node id.
    """
    return node_id.split(".", 1)[0]


def _apply_to_session_host(event: DispatchEvent) -> None:
    """Fold one dispatch event into the current dispatch's SessionHost, if any.

    Reads the per-dispatch host from :data:`_SESSION_HOST_CTX` (bound by the
    active ``dispatch()`` call). No-op when no host is bound (legacy
    callers). Every failure is swallowed and logged at DEBUG — the shim must
    never affect the legacy publish path or the dispatch itself.
    """
    host = _SESSION_HOST_CTX.get()
    if host is None:
        return
    try:
        action = action_from_dispatch_event(
            event.kind, _owning_node_id(event.node_id), event.ts, event.payload
        )
        if action is not None:
            host.apply(action)
    except Exception:  # noqa: BLE001 - shim must never break a dispatch
        _logger.debug(
            "dev-loop session-state shim failed for dispatch event %s (node=%s)",
            event.kind, event.node_id, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DispatchExecutionError(Exception):
    """Raised when the Claude Code session fails before producing a result.

    Wraps any exception raised by ``ClaudeAgentClient.ask_stream`` plus
    misconfiguration errors caught before SDK invocation (e.g.
    ``cwd`` outside ``WORKTREE_BASE_PATH``).
    """


class DispatchOutputValidationError(Exception):
    """Raised when the final ResultMessage payload fails to validate.

    Attributes:
        raw_payload: The concatenated assistant text that failed
            ``output_model.model_validate_json``. Surfaced so the
            audit log / failure handler can capture it verbatim.
    """

    def __init__(self, message: str, *, raw_payload: str = "") -> None:
        super().__init__(message)
        self.raw_payload = raw_payload


class DevLoopCodeDispatcher(Protocol):
    """Shared dispatch contract consumed by dev-loop code-agent nodes."""

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: BaseModel,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        """Dispatch a code-agent run and return validated structured output."""
