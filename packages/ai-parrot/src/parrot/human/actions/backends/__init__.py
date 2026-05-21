"""Concrete action backends for the HITL escalation system.

FEAT-194 — TASK-1275

Each backend implements :class:`~parrot.human.actions.backends.base.ActionBackend`
and is dispatched by :class:`~parrot.human.actions.notify.NotifyAction` or
:class:`~parrot.human.actions.ticket.TicketAction` based on
``tier.action_metadata["kind"]``.
"""
from .base import (
    ActionBackend,
    ActionBackendError,
    EmailBackendError,
    ZammadBackendError,
    WebhookBackendError,
)
from .email import EmailBackend
from .webhook import WebhookBackend
from .zammad import ZammadBackend

__all__ = [
    "ActionBackend",
    "ActionBackendError",
    "EmailBackendError",
    "ZammadBackendError",
    "WebhookBackendError",
    "EmailBackend",
    "WebhookBackend",
    "ZammadBackend",
]
