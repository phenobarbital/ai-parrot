"""ChannelNotifier adapters for Jira connection events (FEAT-773 M8)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
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


class TelegramJiraNotifierAdapter(_JiraAdapterBase):
    """Deliver Jira connection lifecycle events to Telegram."""

    channel = "telegram"

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Stamp the Telegram session and send the Jira status message."""
        if event.provider != "jira":
            return

        extra = self._extra(state_payload)
        chat_id = extra.get("chat_id")
        if not chat_id:
            logger.info("Skipping Telegram Jira notification without chat_id")
            return

        try:
            telegram_user_id = str(state_payload.get("user_id") or "")
            if event.kind == "connection.completed":
                stamper = self._app.get("telegram_jira_session_stamper")
                if stamper is not None and telegram_user_id:
                    stamper(
                        telegram_user_id,
                        SimpleNamespace(
                            display_name=event.display_name,
                            site_url=self._site_url(state_payload),
                            account_id=event.account_id,
                            cloud_id=(state_payload.get("connection_meta") or {}).get("cloud_id", ""),
                        ),
                    )

                notifier = self._app.get("jira_oauth_notifier")
                if notifier is not None:
                    await notifier.notify_connected(int(chat_id), event.display_name, self._site_url(state_payload))
                else:
                    logger.warning("No Telegram Jira notifier registered")
            elif event.kind in {"connection.refresh_failed", "connection.revoked"}:
                notifier = self._app.get("jira_oauth_notifier")
                if notifier is not None:
                    await notifier.notify_failure(int(chat_id), self._reason(event))
                else:
                    logger.warning("No Telegram Jira notifier registered")
        except (TypeError, ValueError):
            logger.warning("Skipping Telegram Jira notification with invalid chat_id=%r", chat_id)


class SlackJiraNotifierAdapter(_JiraAdapterBase):
    """Deliver Jira connection lifecycle events to Slack."""

    channel = "slack"

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Persist the Slack identity when bound and send the Jira status message."""
        if event.provider != "jira":
            return

        extra = self._extra(state_payload)
        team_id = str(extra.get("team_id") or state_payload.get("team_id") or "")
        slack_user_id = str(extra.get("slack_user_id") or state_payload.get("slack_user_id") or "")
        if event.kind == "connection.completed":
            identity_service = self._app.get("identity_mapping_service")
            nav_user_id = str(extra.get("nav_user_id") or state_payload.get("nav_user_id") or "")
            if identity_service is not None and slack_user_id and nav_user_id:
                await identity_service.upsert_identity(
                    nav_user_id=nav_user_id,
                    auth_provider="slack",
                    provider_user_id=slack_user_id,
                    auth_data={"team_id": team_id, "slack_user_id": slack_user_id},
                    display_name=event.display_name or None,
                    email=(state_payload.get("connection_meta") or {}).get("email") or None,
                )
            elif identity_service is not None and slack_user_id:
                logger.warning(
                    "Skipping auth.user_identities write for Slack user=%s team=%s: "
                    "OAuth state carries no Navigator nav_user_id",
                    slack_user_id,
                    team_id,
                )

            notifier = self._app.get("slack_jira_oauth_notifier")
            if notifier is not None and slack_user_id:
                await notifier.notify_connected(
                    team_id=team_id,
                    slack_user_id=slack_user_id,
                    display_name=event.display_name,
                    site_url=self._site_url(state_payload),
                )
            elif notifier is None:
                logger.warning("No Slack Jira notifier registered")
        elif event.kind in {"connection.refresh_failed", "connection.revoked"}:
            notifier = self._app.get("slack_jira_oauth_notifier")
            if notifier is not None and slack_user_id:
                await notifier.notify_failure(
                    team_id=team_id,
                    slack_user_id=slack_user_id,
                    reason=self._reason(event),
                )
            elif notifier is None:
                logger.warning("No Slack Jira notifier registered")
