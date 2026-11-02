"""ChannelNotifier adapters for Jira connection events (FEAT-773 M8)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping

from parrot.auth.oauth2.events import ConnectionEvent

logger = logging.getLogger(__name__)


class _JiraAdapterBase:
    """Shared state-payload helpers for the Jira channel adapters."""

    channel: str = ""

    def __init__(self, app: Mapping[str, Any]) -> None:
        self._app = app

    @staticmethod
    def _extra(state_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return the channel-specific OAuth state fields."""
        return dict(state_payload.get("extra") or {})

    @staticmethod
    def _site_url(state_payload: Dict[str, Any]) -> str:
        """Return the public Jira site URL carried with the event."""
        return str((state_payload.get("connection_meta") or {}).get("site_url") or "")

    @staticmethod
    def _reason(event: ConnectionEvent) -> str:
        """Return a useful failure message without exposing credential material."""
        return event.reason or "Jira connection failed."
