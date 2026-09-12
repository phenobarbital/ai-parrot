"""`/devloop` slash-command handler (FEAT-555 M10)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from parrot.integrations.devloop.models import (  # TASK-3200
    CommandSyntaxError,
    NotRunOwnerError,
    Requester,
    RunNotFoundError,
)
from parrot.integrations.devloop.parser import USAGE, parse_command  # TASK-3201

if TYPE_CHECKING:
    from parrot.integrations.devloop.service import DevLoopDispatchService  # TASK-3204
    from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport  # TASK-3207
    from parrot.integrations.slack.wrapper import SlackAgentWrapper  # verified: slack/wrapper.py:72

logger = logging.getLogger(__name__)


def _ephemeral(text: str) -> dict[str, Any]:
    return {"response_type": "ephemeral", "text": text}


def _requester(payload: dict[str, Any]) -> Requester:
    return Requester(transport="slack", tenant_id=payload.get("team_id", ""), user_id=payload.get("user_id", ""))


async def devloop_command_handler(
    payload: dict[str, Any],
    *,
    wrapper: "SlackAgentWrapper",
    service: "DevLoopDispatchService",
    transport: "SlackDevLoopTransport",
) -> dict[str, Any]:
    """Router handler for ``/devloop``.

    Returns the ephemeral ack dict immediately (Slack's 3s window); all
    dispatch/cancel work runs in a background task tracked on the
    wrapper.

    Args:
        payload: keys ``team_id``, ``user_id``, ``channel_id``, ``text``,
            ``response_url`` (wrapper.py:357-363).
        wrapper: The Slack wrapper this command is bound to.
        service: The channel-neutral dispatch service.
        transport: The Slack transport bound to ``wrapper``.

    Returns:
        The immediate ephemeral ack dict.
    """
    channel, user = payload.get("channel_id", ""), payload.get("user_id", "")
    if not channel or not wrapper._is_authorized(channel, user):
        return _ephemeral("Unauthorized.")
    try:
        command = parse_command(payload.get("text", ""))
    except CommandSyntaxError as exc:
        return _ephemeral(f"{exc}\n{USAGE}")
    if command.action == "help":
        return _ephemeral(USAGE)
    requester = _requester(payload)
    if command.action == "status":
        records = await service.status(requester)
        return _ephemeral(transport.render_status(records))
    task = asyncio.create_task(_run_async(command, requester, payload, service=service, transport=transport))
    wrapper._background_tasks.add(task)
    task.add_done_callback(wrapper._background_tasks.discard)
    if command.action == "cancel":
        return _ephemeral(f"Cancelling `{command.run_id}`…")
    return _ephemeral(f"Validating your {command.type} request… a confirm card will appear in this channel.")


async def _run_async(
    command,
    requester: Requester,
    payload: dict[str, Any],
    *,
    service: "DevLoopDispatchService",
    transport: "SlackDevLoopTransport",
) -> None:
    """Background half: dispatch (→ confirm card) or cancel.

    Every error becomes an ephemeral reply via ``response_url``; never
    raises out (the caller is a fire-and-forget background task).
    """
    response_url = payload.get("response_url", "")
    try:
        if command.action == "cancel":
            result = await service.cancel(command.run_id, requester)
            if result.ok:
                await transport.ephemeral(response_url, f"Cancelling `{command.run_id}`…")
            elif result.reason == "not_found":
                await transport.ephemeral(response_url, "Unknown run id.")
            elif result.reason == "unreachable":
                await transport.ephemeral(
                    response_url, f"Run `{command.run_id}` is unreachable; it may have already stopped."
                )
            else:
                await transport.ephemeral(
                    response_url, f"Could not cancel `{command.run_id}`: {result.reason or 'unknown error'}."
                )
            return
        await service.dispatch(
            command, requester, payload.get("channel_id", "")
        )  # posts the confirm card via transport.post_confirm
    except NotRunOwnerError as exc:
        await transport.ephemeral(response_url, f"This run belongs to <@{exc.owner_user_id}>.")
    except RunNotFoundError:
        await transport.ephemeral(response_url, "Unknown run id.")
    except Exception as exc:  # noqa: BLE001 — never leak a traceback into Slack, never crash the bot
        logger.exception("devloop dispatch failed")
        await transport.ephemeral(response_url, f"Could not start: {exc}")
