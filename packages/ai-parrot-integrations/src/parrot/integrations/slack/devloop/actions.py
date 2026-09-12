"""Block actions, modal submissions, thread-reply interceptor and identity resolver (FEAT-555 M11).

FEAT-555 NOTE (written by TASK-3206): TASK-3207 had not landed yet when
this file was created, so this is a **minimal stub** — just enough for
``register_devloop()`` to wire the action registry and the message
interceptor without error. ``devloop_confirm``/``devloop_discard`` are
fully functional (the confirm-card flow this task ships); gate
answer/approve/reject, the answers/edit modals and the thread-reply
interceptor are stubbed until TASK-3207 replaces this file with the full
implementation — see spec §3 Module 11.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from parrot.integrations.devloop.models import NotRunOwnerError, Requester, RunNotFoundError  # TASK-3200
from parrot.integrations.devloop.service import DevLoopDispatchService  # TASK-3204
from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport

logger = logging.getLogger(__name__)
THREAD_ANSWER_RE = re.compile(r"^\s*(\d+)\s*[:)\.-]\s*(.+)$", re.M)


def _requester(payload: dict[str, Any]) -> Requester:
    return Requester(
        transport="slack",
        tenant_id=payload.get("team", {}).get("id", ""),
        user_id=payload.get("user", {}).get("id", ""),
    )


async def handle_block_action(
    payload: dict[str, Any],
    action: dict[str, Any],
    *,
    service: DevLoopDispatchService,
    transport: SlackDevLoopTransport,
) -> None:
    """Route ``devloop_<verb>:<suffix>`` actions; ownership errors become ephemeral notices via response_url."""
    verb, _, suffix = action.get("action_id", "").partition(":")
    requester, response_url = _requester(payload), payload.get("response_url", "")
    try:
        if verb == "devloop_confirm":
            await service.confirm(suffix, requester)
        elif verb == "devloop_discard":
            await service.discard(suffix, requester)
        else:
            logger.info("devloop action %r not yet implemented (TASK-3207 pending)", verb)
    except NotRunOwnerError as exc:
        await transport.ephemeral(response_url, f"This run belongs to <@{exc.owner_user_id}>.")
    except RunNotFoundError:
        await transport.ephemeral(response_url, "Unknown run.")


async def handle_answers_submission(
    payload: dict[str, Any], *, service: DevLoopDispatchService, transport: SlackDevLoopTransport
) -> dict[str, Any] | None:
    """FEAT-555 stub: TASK-3207 implements the open_questions answers modal submission."""
    logger.info("handle_answers_submission not yet implemented (TASK-3207 pending)")
    return None


async def handle_edit_submission(
    payload: dict[str, Any], *, service: DevLoopDispatchService, transport: SlackDevLoopTransport
) -> dict[str, Any] | None:
    """FEAT-555 stub: TASK-3207 implements the Edit modal submission."""
    logger.info("handle_edit_submission not yet implemented (TASK-3207 pending)")
    return None


async def thread_answer_interceptor(
    event: dict[str, Any], *, service: DevLoopDispatchService, transport: SlackDevLoopTransport
) -> bool:
    """FEAT-555 stub: TASK-3207 implements the ``N:`` thread-reply fallback."""
    return False
