"""Swarm request context propagated via ``contextvars`` (FEAT-463).

Carries per-request routing state — hop count, originating collaborative
session id, and the channel/trigger-event a request originated from — from
``MatrixCrewAgentWrapper.handle_message`` / ``handle_task`` down to
``AgentSwarmToolkit`` tool calls (e.g. ``ask_agent``), without threading
extra parameters through every intermediate layer.
"""
import contextvars
from typing import Optional

#: Number of tunnel hops already taken in the current request chain.
#: Defaults to ``0`` for top-level (human-triggered) requests.
current_hops: contextvars.ContextVar[int] = contextvars.ContextVar(
    "current_hops", default=0
)

#: The originating collaborative session id, when the current request was
#: triggered from a ``MatrixCollaborativeSession`` cross-pollination round.
current_session: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_session", default=None
)

#: The room id of the channel the current request originated from, when
#: applicable — used to post the optional tunnel-question echo line.
current_channel_room: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_channel_room", default=None
)

#: The event id of the human message that triggered the current request
#: chain — used as the ``reply_to`` target for the echo line.
current_trigger_event: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_trigger_event", default=None
)
