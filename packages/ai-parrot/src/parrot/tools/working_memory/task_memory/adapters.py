"""Typed result adapters for the invocation observer (FEAT-538).

The observer has to answer one question about every dispatch: *what
actually happened?* This module answers it, and the whole design rests on
a single prohibition from the specification:

    **Never parse free text to infer success.**

A tool that returns the string ``"Error: the database is unreachable"``
returned a *value*. It succeeded. A tool that returns
``ToolResult(status="error")`` failed. The difference is the typed
envelope, never the prose — and a classifier that reads prose will
eventually mark a search result about outages as a failure, or miss a
real failure whose message happens to read cheerfully.

What counts as a typed signal, in precedence order:

1. A :class:`~parrot.tools.abstract.ToolResult`-shaped **model** — its
   ``success``/``status``/``error`` fields.
2. A toolkit **error dictionary**: a mapping whose ``status`` key holds a
   recognised failure status. Business dictionaries are *not* envelopes:
   a mapping with no ``status``, or with a ``status`` this module does
   not recognise as a failure, is an ordinary value and therefore a
   success.
3. A plan **execution manifest**: failed nodes, or a ``partial``/``error``
   artifact reference. A partial manifest is explicitly *not* valid
   completion evidence.
4. A raised **exception** — a failure, except for cancellation.
5. Anything else — an ordinary value, and therefore a success.

Dispatch outcomes that never ran a tool body
--------------------------------------------

``ToolManager.execute_tool`` returns early for an unknown tool
(``not_found``), a guardrail/grant/resolver denial (``forbidden``) and an
authorization requirement (``authorization_required``). Those are
unsuccessful **dispatch** outcomes, not failed tools: they carry
``executed=False`` so nothing downstream can claim a tool body ran.

Both dispatch modes reach the same answer
-----------------------------------------

Verified against the real dispatcher: in default mode the ``AbstractTool``
branch **raises** ``ValueError`` for a ``status == "error"`` envelope,
while ``return_tool_result=True`` **returns** that envelope. This module
classifies both to :data:`CallOutcome.ERROR`, so enabling full-result mode
cannot change a step's recorded history.

Structural typing, deliberately
-------------------------------

Envelopes and manifests are recognised by *shape*, not by ``isinstance``
against imported classes. Importing ``parrot.tools.abstract`` or
``parrot.bots.flows.plan.models`` here would couple the task-memory
package to the tool and flow machinery for nothing — the fields are the
contract. The test module verifies the duck-typing against the **real**
``ToolResult``, ``ArtifactRef`` and ``ExecutionManifest`` classes, so the
shapes cannot drift apart silently.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from parrot.memory.compaction.models import ToolInvocation, ToolStatus

from .models import CallOutcome, Limits

__all__ = (
    "OutcomeSource",
    "DispatchOutcome",
    "FAILURE_STATUSES",
    "NOT_EXECUTED_STATUSES",
    "DENIED_STATUSES",
    "UNRESOLVED_STATUSES",
    "CANCELLED_STATUSES",
    "looks_like_tool_result",
    "looks_like_manifest",
    "looks_like_error_mapping",
    "classify_result",
    "classify_exception",
    "classify",
    "to_tool_invocation",
)


class OutcomeSource(str, Enum):
    """Which rule decided a dispatch's outcome.

    Recorded so an operator can tell *why* an attempt was classified the
    way it was — "the tool returned a typed envelope" and "the value was
    ordinary so we defaulted to success" are very different claims to
    make about a step's history.
    """

    #: A ``ToolResult``-shaped model's typed fields.
    TOOL_RESULT = "tool_result"
    #: A toolkit mapping carrying a recognised failure ``status``.
    ERROR_MAPPING = "error_mapping"
    #: A plan execution manifest or artifact reference.
    PLAN_MANIFEST = "plan_manifest"
    #: An exception propagated out of the dispatch.
    EXCEPTION = "exception"
    #: Cancellation, which is never a failure and never a success.
    CANCELLATION = "cancellation"
    #: An ordinary value with no typed failure signal.
    ORDINARY_VALUE = "ordinary_value"


#: Envelope statuses meaning the dispatch never entered a tool body.
NOT_EXECUTED_STATUSES: frozenset = frozenset({"not_found", "authorization_required"})

#: Envelope statuses meaning the call was refused by a guard or policy.
DENIED_STATUSES: frozenset = frozenset({"forbidden", "denied", "unauthorized"})

#: Envelope statuses whose disposition is genuinely unsettled. A timeout
#: or a pending result may or may not have produced an external effect,
#: so neither may be reported as a failure the agent can safely retry.
UNRESOLVED_STATUSES: frozenset = frozenset({"timeout", "pending"})

#: Envelope statuses meaning the caller cancelled the call.
CANCELLED_STATUSES: frozenset = frozenset({"cancelled", "canceled"})

#: Envelope statuses meaning the tool body ran and failed.
_PLAIN_ERROR_STATUSES: frozenset = frozenset({"error", "failed", "failure"})

#: Every status this module recognises as *not* a success.
FAILURE_STATUSES: frozenset = (
    NOT_EXECUTED_STATUSES | DENIED_STATUSES | UNRESOLVED_STATUSES | CANCELLED_STATUSES | _PLAIN_ERROR_STATUSES
)

#: Statuses that positively mean success.
_SUCCESS_STATUSES: frozenset = frozenset({"success", "ok", "completed"})


@dataclass(frozen=True)
class DispatchOutcome:
    """What one physical dispatch attempt actually did.

    Attributes:
        outcome: The typed outcome.
        executed: Whether a tool body actually ran. ``False`` only for
            the dispatcher's early returns.
        error: Condensed error text taken from a typed field, never
            inferred from prose. Callers must still pass it through the
            redactor before it reaches a journal.
        status: The envelope status observed, when there was one.
        partial: Whether a plan manifest reported partial results. A
            partial manifest is not valid completion evidence.
        source: Which rule decided this outcome.
    """

    outcome: CallOutcome
    executed: bool
    error: Optional[str] = None
    status: Optional[str] = None
    partial: bool = False
    source: OutcomeSource = OutcomeSource.ORDINARY_VALUE

    @property
    def succeeded(self) -> bool:
        """Whether this attempt is a plain success."""
        return self.outcome is CallOutcome.SUCCESS

    @property
    def is_resolved(self) -> bool:
        """Whether this outcome settles the attempt's disposition."""
        return self.outcome.is_resolved

    @property
    def tool_status(self) -> ToolStatus:
        """The compaction status this outcome maps to.

        ``ToolStatus`` has only ``COMPLETED`` and ``ERROR`` and this
        module does not invent new members: the richer vocabulary
        (cancelled, unknown, denied, not-executed) lives on
        ``InvocationRecord`` and in journal events, while
        ``ToolInvocation`` stays the shared normalized payload it
        already is.
        """
        return ToolStatus.COMPLETED if self.succeeded else ToolStatus.ERROR


def _clip(text: Optional[str]) -> Optional[str]:
    """Clip typed error text to the journal's reason bound.

    Args:
        text: The error text, or ``None``.

    Returns:
        The clipped text, or ``None``.
    """
    if text is None:
        return None
    return text[: Limits.MAX_REASON]


def _status_of(value: Any) -> Optional[str]:
    """Return a lower-cased ``status`` attribute or key, when present.

    Args:
        value: The candidate envelope.

    Returns:
        The normalized status, or ``None``.
    """
    status = value.get("status") if isinstance(value, Mapping) else getattr(value, "status", None)
    return status.strip().lower() if isinstance(status, str) else None


def looks_like_tool_result(value: Any) -> bool:
    """Whether ``value`` is a ``ToolResult``-shaped model.

    Deliberately excludes mappings: a plain ``dict`` that happens to hold
    ``success``/``status``/``result`` keys is business data, and treating
    it as an envelope is exactly the "business dicts mistaken for
    envelopes" failure the acceptance criteria forbid.

    Args:
        value: The candidate.

    Returns:
        ``True`` when it carries the envelope's typed fields as
        attributes and is not a mapping.
    """
    if isinstance(value, Mapping):
        return False
    return all(hasattr(value, field) for field in ("success", "status", "result", "error"))


def looks_like_manifest(value: Any) -> bool:
    """Whether ``value`` is a plan execution manifest.

    Args:
        value: The candidate.

    Returns:
        ``True`` when it carries the manifest's aggregate fields.
    """
    if isinstance(value, Mapping):
        return False
    return all(hasattr(value, field) for field in ("artifacts", "nodes_failed", "nodes_total"))


def looks_like_error_mapping(value: Any) -> bool:
    """Whether ``value`` is a toolkit error dictionary.

    A mapping is an error envelope **only** when its ``status`` is one
    this module recognises as a failure. A mapping with no ``status``, or
    with an unrecognised one (``{"status": "shipped"}``), is ordinary
    business data.

    Args:
        value: The candidate.

    Returns:
        ``True`` when it is a mapping carrying a recognised failure status.
    """
    if not isinstance(value, Mapping):
        return False
    return _status_of(value) in FAILURE_STATUSES


def _outcome_for_status(status: str, *, success_flag: Optional[bool]) -> Tuple[CallOutcome, bool]:
    """Map an envelope status to a typed outcome and an executed flag.

    Args:
        status: The normalized envelope status.
        success_flag: The envelope's ``success`` boolean, when it has one.

    Returns:
        A ``(outcome, executed)`` pair.
    """
    if status in NOT_EXECUTED_STATUSES:
        return CallOutcome.NOT_EXECUTED, False
    if status in DENIED_STATUSES:
        return CallOutcome.DENIED, False
    if status in CANCELLED_STATUSES:
        return CallOutcome.CANCELLED, True
    if status in UNRESOLVED_STATUSES:
        # A timeout or a pending result may already have produced an
        # external effect. Reporting it as a failure would invite an
        # automatic retry of an uncertain effect, which the spec forbids.
        return CallOutcome.UNKNOWN, True
    if status in _PLAIN_ERROR_STATUSES:
        return CallOutcome.ERROR, True
    if status in _SUCCESS_STATUSES:
        # An explicit ``success=False`` still wins over a success status.
        return (CallOutcome.SUCCESS, True) if success_flag is not False else (CallOutcome.ERROR, True)
    # An unrecognised status on a typed envelope: fall back to the
    # boolean if there is one, and otherwise treat it as a success —
    # never guess a failure from an unfamiliar label.
    if success_flag is False:
        return CallOutcome.ERROR, True
    return CallOutcome.SUCCESS, True


def _classify_tool_result(value: Any) -> DispatchOutcome:
    """Classify a ``ToolResult``-shaped envelope.

    Args:
        value: The envelope.

    Returns:
        The dispatch outcome.
    """
    status = _status_of(value) or ""
    raw_success = getattr(value, "success", None)
    success_flag = raw_success if isinstance(raw_success, bool) else None
    outcome, executed = _outcome_for_status(status, success_flag=success_flag)

    error = getattr(value, "error", None)
    return DispatchOutcome(
        outcome=outcome,
        executed=executed,
        error=_clip(error) if isinstance(error, str) else None,
        status=status or None,
        source=OutcomeSource.TOOL_RESULT,
    )


def _classify_error_mapping(value: Mapping[str, Any]) -> DispatchOutcome:
    """Classify a toolkit error dictionary.

    Args:
        value: The mapping.

    Returns:
        The dispatch outcome.
    """
    status = _status_of(value) or ""
    raw_success = value.get("success")
    success_flag = raw_success if isinstance(raw_success, bool) else None
    outcome, executed = _outcome_for_status(status, success_flag=success_flag)

    # Toolkits spell the message several ways; take the first typed one.
    error: Optional[str] = None
    for key in ("error", "detail", "message"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            error = candidate
            break
    if error is None and isinstance(value.get("errors"), (list, tuple)) and value["errors"]:
        first = value["errors"][0]
        error = first if isinstance(first, str) else repr(first)

    return DispatchOutcome(
        outcome=outcome,
        executed=executed,
        error=_clip(error),
        status=status or None,
        source=OutcomeSource.ERROR_MAPPING,
    )


def _classify_manifest(value: Any) -> DispatchOutcome:
    """Classify a plan execution manifest.

    A manifest whose nodes all succeeded (or were skipped by a false
    guard) is a success. Any failed node, or any ``error``/``partial``
    artifact reference, is not: a partial manifest is explicitly not
    valid completion evidence.

    Args:
        value: The manifest.

    Returns:
        The dispatch outcome.
    """
    refs = getattr(value, "artifacts", None) or ()
    statuses = {getattr(ref, "status", None) for ref in refs}
    nodes_failed = getattr(value, "nodes_failed", 0) or 0

    errors: list = []
    for ref in refs:
        for message in getattr(ref, "errors", None) or ():
            if isinstance(message, str):
                errors.append(f"{getattr(ref, 'node_id', '?')}: {message}")

    partial = "partial" in statuses
    failed = nodes_failed > 0 or "error" in statuses

    if not failed and not partial:
        return DispatchOutcome(
            outcome=CallOutcome.SUCCESS,
            executed=True,
            status="ok",
            source=OutcomeSource.PLAN_MANIFEST,
        )

    return DispatchOutcome(
        outcome=CallOutcome.ERROR,
        executed=True,
        error=_clip("; ".join(errors)) if errors else None,
        status="partial" if partial and not failed else "error",
        partial=partial,
        source=OutcomeSource.PLAN_MANIFEST,
    )


def classify_result(value: Any) -> DispatchOutcome:
    """Classify a value the dispatcher returned.

    Args:
        value: Whatever ``execute_tool`` returned.

    Returns:
        The dispatch outcome. An ordinary value — including a string that
        reads like an error message — is a success, because it carries no
        typed failure signal.
    """
    if looks_like_tool_result(value):
        return _classify_tool_result(value)
    if looks_like_manifest(value):
        return _classify_manifest(value)
    if looks_like_error_mapping(value):
        return _classify_error_mapping(value)
    return DispatchOutcome(
        outcome=CallOutcome.SUCCESS,
        executed=True,
        source=OutcomeSource.ORDINARY_VALUE,
    )


def classify_exception(exc: BaseException, *, executed: bool = True) -> DispatchOutcome:
    """Classify an exception that propagated out of the dispatch.

    Cancellation is neither a success nor a failure: the call was
    interrupted, so its disposition is unresolved until a later attempt
    or an explicit reconciliation records one.

    Args:
        exc: The exception.
        executed: Whether a tool body had already been entered. Pass
            ``False`` only when the dispatcher failed before execution.

    Returns:
        The dispatch outcome.

    Note:
        When the caller cannot establish *whether* the body ran — a lost
        worker, a crashed pod — the honest record is
        :data:`CallOutcome.UNKNOWN`, which the turn session records
        directly rather than inferring here.
    """
    if isinstance(exc, asyncio.CancelledError):
        return DispatchOutcome(
            outcome=CallOutcome.CANCELLED,
            executed=executed,
            source=OutcomeSource.CANCELLATION,
        )
    message = f"{type(exc).__name__}: {exc}"
    return DispatchOutcome(
        outcome=CallOutcome.ERROR,
        executed=executed,
        error=_clip(message),
        source=OutcomeSource.EXCEPTION,
    )


def classify(*, value: Any = None, exception: Optional[BaseException] = None) -> DispatchOutcome:
    """Classify a dispatch from whichever of value/exception it produced.

    Args:
        value: The returned value, when the dispatch returned.
        exception: The raised exception, when it raised.

    Returns:
        The dispatch outcome.
    """
    if exception is not None:
        return classify_exception(exception)
    return classify_result(value)


def to_tool_invocation(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    outcome: DispatchOutcome,
    output: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
    output_chars: Optional[int] = None,
    wm_key: Optional[str] = None,
) -> ToolInvocation:
    """Build the canonical compaction payload for one attempt.

    The observer produces this **once** and feeds both the journal
    derivation and ``ConversationTurn.tool_invocations``, rather than
    letting the turn re-derive its own copy from ``AIMessage.tool_calls``.

    The result is *not* yet safe to persist: run it through
    :func:`~parrot.tools.working_memory.task_memory.redaction.redact_invocation`,
    which normalizes it with Stage 0 and then removes credentials.

    Args:
        tool_name: The dispatched tool.
        arguments: The call's arguments.
        outcome: The classified outcome.
        output: Rendered output text, when there is one.
        elapsed_ms: Wall-clock duration.
        output_chars: Length of the original output, captured before any
            offload so a preview notice can report the true size.
        wm_key: Working-memory tee key, when the result carried one.

    Returns:
        A new :class:`ToolInvocation`.
    """
    return ToolInvocation(
        tool_name=tool_name,
        input=dict(arguments),
        output=output,
        status=outcome.tool_status,
        error=outcome.error,
        elapsed_ms=elapsed_ms,
        output_chars=output_chars if output_chars is not None else (len(output) if output is not None else None),
        wm_key=wm_key,
    )
