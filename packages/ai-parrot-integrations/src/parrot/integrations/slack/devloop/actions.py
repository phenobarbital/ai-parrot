"""Block actions, modal submissions, thread-reply interceptor and identity resolver (FEAT-555 M11)."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, Optional, Tuple

from parrot.integrations.devloop.models import NotRunOwnerError, Requester, RunNotFoundError  # TASK-3200
from parrot.integrations.devloop.service import DevLoopDispatchService  # TASK-3204
from parrot.integrations.slack.devloop import blocks
from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport
from parrot.integrations.slack.wrapper import SlackAgentWrapper  # verified: slack/wrapper.py:72

logger = logging.getLogger(__name__)
THREAD_ANSWER_RE = re.compile(r"^\s*(\d+)\s*[:)\.-]\s*(.+)$", re.M)


def _requester(payload: Dict[str, Any]) -> Requester:
    return Requester(
        transport="slack",
        tenant_id=payload.get("team", {}).get("id", ""),
        user_id=payload.get("user", {}).get("id", ""),
    )


async def handle_block_action(
    payload: Dict[str, Any],
    action: Dict[str, Any],
    *,
    service: DevLoopDispatchService,
    transport: SlackDevLoopTransport,
) -> None:
    """Route ``devloop_<verb>:<suffix>`` actions; ownership errors become ephemeral notices via response_url.

    Args:
        payload: The full ``block_actions`` payload.
        action: The specific action element that was clicked.
        service: The channel-neutral dispatch service.
        transport: The Slack transport bound to the wrapper.
    """
    verb, _, suffix = action.get("action_id", "").partition(":")
    requester, response_url = _requester(payload), payload.get("response_url", "")
    try:
        if verb == "devloop_confirm":
            await service.confirm(suffix, requester)
        elif verb == "devloop_discard":
            await service.discard(suffix, requester)
        elif verb == "devloop_edit":
            pending = service.pending(suffix)
            if pending is None:
                await transport.ephemeral(response_url, "This request is no longer pending.")
                return
            await transport.wrapper._interactive_handler.open_modal(
                payload.get("trigger_id", ""), blocks.edit_modal(pending.pending_id, pending.kind, pending.fields)
            )
        elif verb == "devloop_answer":
            run_id, _, gate_id = suffix.partition(":")
            gate = service.pending_gate(run_id)
            record = service.record(run_id)
            if gate is None or record is None:
                await transport.ephemeral(response_url, "This gate is no longer pending.")
                return
            await transport.wrapper._interactive_handler.open_modal(
                payload.get("trigger_id", ""), blocks.answers_modal(record, gate)
            )
        elif verb in ("devloop_approve", "devloop_reject"):
            run_id, _, gate_id = suffix.partition(":")
            resolution = "approved" if verb == "devloop_approve" else "rejected"
            result = await service.resolve_gate(run_id, gate_id, requester, resolution)
            if result.reason == "already_resolved":
                await transport.ephemeral(response_url, "This gate was already resolved.")
            elif not result.ok and result.reason:
                await transport.ephemeral(response_url, f"Could not resolve the gate: {result.reason}.")
        else:
            logger.warning("unknown devloop action_id verb: %r", verb)
    except NotRunOwnerError as exc:
        await transport.ephemeral(response_url, f"This run belongs to <@{exc.owner_user_id}>.")
    except RunNotFoundError:
        await transport.ephemeral(response_url, "Unknown run.")


async def handle_answers_submission(
    payload: Dict[str, Any], *, service: DevLoopDispatchService, transport: SlackDevLoopTransport
) -> Optional[Dict[str, Any]]:
    """``modal:devloop_answers`` submission.

    Extracts ``{question: answer}`` for non-empty inputs and calls
    ``service.answer_gate``; an empty submission (or a gate the service
    rejects as ``answers_required``) returns a Slack ``errors`` response.

    Args:
        payload: The ``view_submission`` payload.
        service: The channel-neutral dispatch service.
        transport: The Slack transport bound to the wrapper.

    Returns:
        A Slack ``response_action`` dict on validation failure, else ``None``.
    """
    meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    run_id, gate_id = meta.get("run_id", ""), meta.get("gate_id", "")
    gate = service.pending_gate(run_id)
    if gate is None:
        return {"response_action": "errors", "errors": {"q1": "This gate is no longer pending."}}

    values = transport.wrapper._interactive_handler.extract_form_values(payload)  # verified: interactive.py:554
    answers: Dict[str, str] = {}
    for block_id, value in values.items():
        if not value or not block_id.startswith("q"):
            continue
        try:
            idx = int(block_id[1:]) - 1
        except ValueError:
            continue
        if 0 <= idx < len(gate.questions):
            answers[gate.questions[idx]] = value

    if not answers:
        return {"response_action": "errors", "errors": {"q1": "Answer at least one question"}}

    requester = _requester(payload)
    try:
        result = await service.answer_gate(run_id, gate_id, requester, answers)
    except (NotRunOwnerError, RunNotFoundError):
        return {"response_action": "errors", "errors": {"q1": "This gate is no longer available to you."}}
    if not result.ok and result.reason == "answers_required":
        return {"response_action": "errors", "errors": {"q1": "Answer at least one question"}}
    return None


async def handle_edit_submission(
    payload: Dict[str, Any], *, service: DevLoopDispatchService, transport: SlackDevLoopTransport
) -> Optional[Dict[str, Any]]:
    """``modal:devloop_edit`` submission.

    Calls ``service.confirm(pending_id, requester, overrides)``;
    validation errors map to a Slack ``errors`` response keyed by field id.

    Args:
        payload: The ``view_submission`` payload.
        service: The channel-neutral dispatch service.
        transport: The Slack transport bound to the wrapper.

    Returns:
        A Slack ``response_action`` dict on validation failure, else ``None``.
    """
    meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    pending_id = meta.get("pending_id", "")
    overrides = {k: v for k, v in transport.wrapper._interactive_handler.extract_form_values(payload).items() if v}
    requester = _requester(payload)
    try:
        await service.confirm(pending_id, requester, overrides)
    except NotRunOwnerError as exc:
        logger.warning("devloop edit submission rejected: not the owner (%s)", exc.owner_user_id)
        return {
            "response_action": "errors",
            "errors": {next(iter(overrides), "_"): "This run belongs to someone else."},
        }
    except RunNotFoundError:
        return {
            "response_action": "errors",
            "errors": {next(iter(overrides), "_"): "This request is no longer pending."},
        }
    except Exception as exc:  # noqa: BLE001 - pydantic.ValidationError or any brief-construction failure
        errors: Dict[str, str] = {}
        for err in getattr(exc, "errors", lambda: [])():
            loc = err.get("loc") or ("_",)
            errors[str(loc[0])] = err.get("msg", "Invalid value")
        if not errors:
            errors = {next(iter(overrides), "_"): str(exc)}
        return {"response_action": "errors", "errors": errors}
    return None


async def thread_answer_interceptor(
    event: Dict[str, Any], *, service: DevLoopDispatchService, transport: SlackDevLoopTransport
) -> bool:
    """True (consumed) iff ``event`` is a reply in a known run thread.

    Owner + pending ``open_questions`` gate + ≥1 valid ``N:`` line ⇒
    ``answer_gate``; otherwise an ephemeral hint via ``chat.postEphemeral``
    (there is no ``response_url`` for events). A run-thread message is
    *always* consumed, even when it is not a valid answer (spec §7: never
    forwarded to the LLM).

    Args:
        event: The raw Slack message event dict.
        service: The channel-neutral dispatch service.
        transport: The Slack transport bound to the wrapper.

    Returns:
        ``True`` when the event belonged to a known run thread.
    """
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return False
    channel = event.get("channel", "")
    record = service.record_by_thread(channel, thread_ts)
    if record is None:
        return False

    user_id = event.get("user", "")

    async def _hint(text: str) -> None:
        await transport.wrapper._slack_api("chat.postEphemeral", {"channel": channel, "user": user_id, "text": text})

    if user_id != record.requester.user_id:
        await _hint(f"This run belongs to <@{record.requester.user_id}>.")
        return True

    gate = service.pending_gate(record.run_id)
    if gate is None or gate.kind != "open_questions":
        await _hint("No open question is waiting for an answer right now.")
        return True

    text = event.get("text", "")
    answers: Dict[str, str] = {}
    for num_str, answer in THREAD_ANSWER_RE.findall(text):
        idx = int(num_str) - 1
        if 0 <= idx < len(gate.questions):
            answers[gate.questions[idx]] = answer.strip()

    if not answers:
        await _hint("Reply with `1: your answer` (one line per question) to answer the open questions.")
        return True

    # Reuse the stored identity — it already carries the right tenant_id;
    # the raw event dict (unlike block_actions/view_submission payloads)
    # carries no team info to rebuild a Requester from.
    await service.answer_gate(record.run_id, gate.gate_id, record.requester, answers)
    return True


class SlackIdentityResolver:
    """identity_resolver for the service (spec Q3).

    Maps the initiator's Slack email (``users.info``) to a Jira accountId
    via the toolkit; ``("", "")`` when no email is available, letting the
    service fall back to ``bootstrap.default_identities()``.
    """

    def __init__(self, wrapper: SlackAgentWrapper, jira_toolkit: Any = None, *, ttl_seconds: float = 3600.0) -> None:
        self.wrapper = wrapper
        self.jira_toolkit = jira_toolkit
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[float, Tuple[str, str]]] = {}
        self.logger = logging.getLogger(__name__)

    async def __call__(self, requester: Requester) -> Tuple[str, str]:
        cached = self._cache.get(requester.user_id)
        if cached and time.monotonic() - cached[0] < self.ttl_seconds:
            return cached[1]

        data = await self.wrapper._slack_api("users.info", {"user": requester.user_id})
        email = ((data or {}).get("user", {}).get("profile", {}) or {}).get("email", "")

        identity: Tuple[str, str] = ("", "")
        if email:
            resolved = None
            if self.jira_toolkit is not None and hasattr(self.jira_toolkit, "resolve_account_id"):
                try:
                    resolved = await self.jira_toolkit.resolve_account_id(email)
                except Exception:  # noqa: BLE001 - Jira resolution is best-effort
                    self.logger.debug("Jira account resolution failed for %r", email, exc_info=True)
            value = resolved or email
            identity = (value, value)

        self._cache[requester.user_id] = (time.monotonic(), identity)
        return identity
