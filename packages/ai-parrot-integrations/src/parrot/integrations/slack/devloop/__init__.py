"""Slack adapter for the dev-loop integration (FEAT-555): `/devloop`, confirm/gate cards, run threads."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.integrations.devloop.service import DevLoopDispatchService
    from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport
    from parrot.integrations.slack.wrapper import SlackAgentWrapper

__all__ = ["register_devloop"]


def register_devloop(wrapper: "SlackAgentWrapper", service: "DevLoopDispatchService") -> "SlackDevLoopTransport":
    """Wire the adapter onto an existing wrapper; returns the transport bound to it.

    ``router.register("devloop")`` · ``action_registry.register_prefix("devloop_")`` ·
    ``register("modal:devloop_answers")`` · ``register("modal:devloop_edit")`` ·
    ``wrapper.add_message_interceptor(thread_answer_interceptor)``.

    Args:
        wrapper: The Slack wrapper to bind the adapter to.
        service: The channel-neutral dispatch service.

    Returns:
        The :class:`SlackDevLoopTransport` bound to ``wrapper``.
    """
    from parrot.integrations.slack.devloop import actions  # TASK-3207 (lazy: avoids import cycles)
    from parrot.integrations.slack.devloop.commands import devloop_command_handler
    from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport  # TASK-3207

    transport = SlackDevLoopTransport(wrapper)
    bound = functools.partial(devloop_command_handler, wrapper=wrapper, service=service, transport=transport)
    wrapper._command_router.register(
        "devloop", bound
    )  # verified: SlackCommandRouter.register slack/commands/__init__.py:50
    registry = wrapper._interactive_handler.action_registry  # verified: interactive.py:116
    registry.register_prefix(
        "devloop_", functools.partial(actions.handle_block_action, service=service, transport=transport)
    )
    registry.register(
        "modal:devloop_answers",
        functools.partial(actions.handle_answers_submission, service=service, transport=transport),
    )
    registry.register(
        "modal:devloop_edit", functools.partial(actions.handle_edit_submission, service=service, transport=transport)
    )
    wrapper.add_message_interceptor(
        functools.partial(actions.thread_answer_interceptor, service=service, transport=transport)
    )
    wrapper.logger.info("dev-loop Slack adapter registered for %s", wrapper.config.name)
    return transport
