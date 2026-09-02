"""Shared exceptions, protocol, and session-host dual-publish shim for the
dev-loop code-agent dispatchers (FEAT-129/322).

Split out of the former monolithic ``dispatcher.py`` so each LLM client's
dispatcher lives in its own module; every per-provider module in this
package imports ``_SESSION_HOST_CTX`` / ``_apply_to_session_host`` from
here to fold ``DispatchEvent``s into the run's ``SessionHost``.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from typing import Any, Dict, Optional, Protocol, Type, TypeVar

from pydantic import BaseModel

from parrot.flows.dev_loop.models import DispatchEvent, DispatchLabels
from parrot.flows.dev_loop.session_state import SessionHost, action_from_dispatch_event

T = TypeVar("T", bound=BaseModel)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Display-contract clamp constants (FEAT-496) — the AHP lazy-loading rule:
# session state and event payloads carry display-ready projections; heavy
# content stays by reference on the terminal channel. Every backend task
# (TASK-2724..2728) uses these same numbers so the console clamps identically
# across dispatchers.
# ---------------------------------------------------------------------------

SUMMARY_MAX_CHARS = 160
TEXT_MAX_CHARS = 400
TOOL_INPUT_MAX_CHARS = 120

_LIFECYCLE_KINDS_FOR_TASK_FILE = frozenset({"dispatch.queued", "dispatch.started"})


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
# Dispatch labels (FEAT-496) — identity of the work in flight, stamped once
# per dispatch() call and read back at the single _publish_event() choke
# point in each dispatcher.
#
# Mirrors _SESSION_HOST_CTX exactly, for the same reason: every dispatcher
# already funnels ALL of its publishing through one _publish_event method,
# so a ContextVar read there stamps every event without threading a new
# parameter through ~40 internal call sites across 5 dispatcher classes.
# ContextVar values are copied per asyncio.Task, so concurrent seats on a
# shared dispatcher instance never observe each other's labels.
# ---------------------------------------------------------------------------

_DISPATCH_LABELS_CTX: "contextvars.ContextVar[Optional[DispatchLabels]]" = (
    contextvars.ContextVar("dev_loop_dispatch_labels", default=None)
)


def bind_labels(labels: Optional[DispatchLabels]) -> "contextvars.Token":
    """Bind labels for the duration of one ``dispatch()`` call.

    Callers MUST reset the returned token in a ``finally:`` block, mirroring
    the ``_SESSION_HOST_CTX.set(...)`` / ``.reset(token)`` discipline already
    used for the session host.

    Args:
        labels: The identity of the work this dispatch is doing, or ``None``.

    Returns:
        A ``contextvars.Token`` to pass to ``_DISPATCH_LABELS_CTX.reset()``.
    """
    return _DISPATCH_LABELS_CTX.set(labels)


def current_labels() -> Optional[DispatchLabels]:
    """Return the labels bound by the active ``dispatch()`` call, if any.

    Returns:
        The bound :class:`DispatchLabels`, or ``None`` when no dispatch has
        bound one (legacy callers, or callers that omit ``labels=``).
    """
    return _DISPATCH_LABELS_CTX.get()


# ---------------------------------------------------------------------------
# Display contract (FEAT-496 Layer 2) — normalize_payload() guarantees a
# human-legible `summary` on every published event and stamps the active
# dispatch's DispatchLabels, without any dispatcher having to think about
# it. Called from the single _publish_event() choke point each dispatcher
# already has.
# ---------------------------------------------------------------------------


def _clamp(value: str, max_chars: int, *, head: bool = True) -> str:
    """Clamp ``value`` to ``max_chars``, adding an ellipsis when truncated.

    Args:
        value: The string to clamp.
        max_chars: The maximum length of the result.
        head: When ``True`` (default) keep the beginning of the string
            (used for commands); when ``False`` keep the end (used for
            paths, so the file name stays visible).

    Returns:
        ``value`` unchanged if it already fits, otherwise a truncated
        version with a trailing/leading ellipsis.
    """
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars == 1:
        return value[:1]
    if head:
        return value[: max_chars - 1] + "…"
    return "…" + value[-(max_chars - 1):]


def summarize_tool_input(
    tool_name: str, tool_input: Any, *, max_chars: int = TOOL_INPUT_MAX_CHARS
) -> str:
    """Compact one-line digest of a tool's arguments.

    Recognises the common shapes (a Grep-style ``pattern``[+``path``], a
    shell ``command``/``cmd``, a file ``file_path``/``path``/
    ``notebook_path``, a ``url``, a ``prompt``/``description``) and falls
    back to ``"<first key>=<value>"``. Never raises.

    Args:
        tool_name: The tool's name. Unused today beyond documenting intent;
            kept so a future per-tool digesting strategy has a hook.
        tool_input: A dict of tool arguments, a JSON-encoded string, or
            anything else.
        max_chars: Maximum length of the returned digest.

    Returns:
        A compact digest string, or ``""`` when the shape is not
        recognised.
    """
    del tool_name  # reserved for a future per-tool digesting strategy
    try:
        data: Any = tool_input
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return ""
        if not isinstance(data, dict):
            return ""

        pattern = data.get("pattern")
        if pattern:
            path = data.get("path")
            digest = f"{pattern} in {path}" if path else str(pattern)
            return _clamp(digest, max_chars)

        for key in ("command", "cmd"):
            value = data.get(key)
            if value:
                return _clamp(str(value), max_chars)

        for key in ("file_path", "path", "notebook_path"):
            value = data.get(key)
            if value:
                return _clamp(str(value), max_chars, head=False)

        url = data.get("url")
        if url:
            return _clamp(str(url), max_chars)

        for key in ("prompt", "description"):
            value = data.get(key)
            if value:
                first_line = str(value).splitlines()[0] if value else ""
                return _clamp(first_line, max_chars)

        if data:
            first_key = next(iter(data))
            return _clamp(f"{first_key}={data[first_key]}", max_chars)
        return ""
    except Exception:  # noqa: BLE001 - telemetry helper must never raise
        return ""


def _fmt_duration_ms(duration_ms: Any) -> str:
    """Best-effort ``"1m03s"``-style rendering of a millisecond duration."""
    try:
        total_seconds = int(float(duration_ms) / 1000)
    except Exception:  # noqa: BLE001
        return ""
    minutes, seconds = divmod(max(total_seconds, 0), 60)
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _labels_prefix(payload: Dict[str, Any]) -> str:
    """Build a ``"[TASK-1857 · w1]"``-style prefix from stamped labels."""
    task_id = payload.get("task_id")
    seat = payload.get("seat")
    parts = []
    if task_id:
        parts.append(str(task_id))
    if seat:
        short_seat = str(seat).split(".")[-1]
        if short_seat:
            parts.append(short_seat)
    if not parts:
        return ""
    return "[" + " · ".join(parts) + "]"


def _kind_fallback(kind: str, payload: Dict[str, Any]) -> str:
    """Kind-specific fallback summary when no richer field is available."""
    if kind == "dispatch.queued":
        dispatcher = payload.get("dispatcher") or payload.get("agent") or ""
        return f"queued ({dispatcher})" if dispatcher else "queued"
    if kind == "dispatch.started":
        cwd = payload.get("cwd") or ""
        base = os.path.basename(str(cwd).rstrip("/")) if cwd else ""
        return f"started in {base}" if base else "started"
    if kind == "dispatch.completed":
        bits = []
        num_turns = payload.get("num_turns")
        if num_turns:
            bits.append(f"{num_turns} turns")
        duration = _fmt_duration_ms(payload.get("duration_ms"))
        if duration:
            bits.append(duration)
        return "completed — " + ", ".join(bits) if bits else "completed"
    return kind.split(".", 1)[-1] if "." in kind else str(kind)


def _build_summary(kind: str, payload: Dict[str, Any]) -> str:
    """Compose a human-legible summary from whatever the payload carries.

    Precedence: an explicit ``tool_name``/``tool_input`` pair for tool
    events, message ``text``, an ``error``/``error_message``, then a
    kind-specific fallback, then the bare event kind.
    """
    body = ""
    if kind == "dispatch.tool_use":
        tool_name = str(payload.get("tool_name") or "").strip()
        tool_input = str(payload.get("tool_input") or "").strip()
        if tool_name:
            body = f"{tool_name} {tool_input}".strip() if tool_input else tool_name
    elif kind == "dispatch.tool_result":
        tool_name = str(payload.get("tool_name") or "").strip()
        if tool_name:
            outcome = "error" if payload.get("is_error") else "ok"
            body = f"{tool_name} → {outcome}"
    elif kind == "dispatch.message":
        text = str(payload.get("text") or "").strip()
        if text:
            body = " ".join(text.split())
    elif kind in ("dispatch.failed", "dispatch.output_invalid"):
        err = str(payload.get("error") or payload.get("error_message") or "").strip()
        if err:
            body = err

    if not body:
        body = _kind_fallback(kind, payload)

    prefix = _labels_prefix(payload)
    if prefix and body and not body.startswith("["):
        body = f"{prefix} {body}"

    return _clamp(body or "event", SUMMARY_MAX_CHARS)


def normalize_payload(kind: str, payload: Any) -> Dict[str, Any]:
    """Return ``payload`` plus the guaranteed display keys and active labels.

    Guarantees:
      * the result always contains a non-empty ``summary`` (<= 160 chars);
      * every key already present in ``payload`` survives unchanged;
      * :meth:`DispatchLabels.as_payload` keys are merged in, but NEVER
        overwrite a key the backend already set;
      * ``task_file`` is stamped only on ``dispatch.queued`` /
        ``dispatch.started`` (spec §7 payload-growth constraint);
      * it never raises — on any internal error it returns the input
        payload (best-effort coerced to a dict) plus a generic summary.

    Args:
        kind: The ``DispatchEvent.kind`` this payload belongs to.
        payload: The backend-specific payload dict (or any malformed value —
            this function is total).

    Returns:
        A new dict; the input is never mutated.
    """
    try:
        out: Dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}

        labels = current_labels()
        if labels is not None:
            for key, value in labels.as_payload().items():
                if key == "task_file" and kind not in _LIFECYCLE_KINDS_FOR_TASK_FILE:
                    continue
                out.setdefault(key, value)

        existing_summary = out.get("summary")
        if existing_summary:
            out["summary"] = _clamp(str(existing_summary), SUMMARY_MAX_CHARS)
        else:
            out["summary"] = _build_summary(kind, out)

        return out
    except Exception:  # noqa: BLE001 - telemetry must never break a dispatch
        try:
            fallback: Dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
        except Exception:  # noqa: BLE001
            fallback = {}
        fallback["summary"] = _clamp(
            (kind.split(".", 1)[-1] if isinstance(kind, str) and "." in kind else str(kind))
            or "event",
            SUMMARY_MAX_CHARS,
        )
        return fallback


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
        labels: Optional[DispatchLabels] = None,
    ) -> T:
        """Dispatch a code-agent run and return validated structured output."""
