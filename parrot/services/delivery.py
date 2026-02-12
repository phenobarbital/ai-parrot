"""Delivery routing for task results."""
import json
from typing import Any, Optional

import aiohttp
from navconfig.logging import logging

from .models import AgentTask, DeliveryChannel, DeliveryConfig, TaskResult


class DeliveryRouter:
    """Routes task results to the appropriate delivery channel."""

    def __init__(self) -> None:
        self._http_session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger("parrot.services.delivery")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazy-create a shared HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._http_session

    async def deliver(self, task: AgentTask, result: TaskResult) -> bool:
        """Deliver a task result via the configured channel.

        Args:
            task: Original task with delivery configuration.
            result: Execution result to deliver.

        Returns:
            True if delivery succeeded.
        """
        channel = task.delivery.channel
        try:
            handler = self._get_handler(channel)
            await handler(task, result)
            self.logger.debug(
                f"Delivered result for task {task.task_id} via {channel}"
            )
            return True
        except Exception as exc:
            self.logger.error(
                f"Delivery failed for task {task.task_id} via {channel}: {exc}"
            )
            return False

    def _get_handler(self, channel: str):
        """Resolve the delivery handler for a channel."""
        handlers = {
            DeliveryChannel.LOG: self._deliver_log,
            DeliveryChannel.WEBHOOK: self._deliver_webhook,
            DeliveryChannel.TELEGRAM: self._deliver_telegram,
            DeliveryChannel.TEAMS: self._deliver_teams,
            DeliveryChannel.EMAIL: self._deliver_email,
            DeliveryChannel.REDIS_STREAM: self._deliver_redis_stream,
        }
        handler = handlers.get(channel)
        if not handler:
            raise ValueError(f"Unknown delivery channel: {channel}")
        return handler

    async def _deliver_log(self, task: AgentTask, result: TaskResult) -> None:
        """Log the result (default for heartbeats)."""
        status = "✅" if result.success else "❌"
        output_preview = (result.output or "")[:200]
        self.logger.info(
            f"{status} Task {task.task_id} ({task.agent_name}): {output_preview}"
        )

    async def _deliver_webhook(self, task: AgentTask, result: TaskResult) -> None:
        """POST result to a webhook URL."""
        url = task.delivery.webhook_url
        if not url:
            raise ValueError("No webhook_url configured for WEBHOOK delivery")

        session = await self._get_session()
        payload = {
            "task_id": result.task_id,
            "agent_name": result.agent_name,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "execution_time_ms": result.execution_time_ms,
            "metadata": result.metadata,
        }

        async with session.post(url, json=payload) as resp:
            if resp.status >= 400:
                body = await resp.text()
                self.logger.warning(
                    f"Webhook {url} returned {resp.status}: {body[:200]}"
                )

    async def _deliver_telegram(self, task: AgentTask, result: TaskResult) -> None:
        """Send result to Telegram via bot API."""
        token = task.delivery.telegram_bot_token
        chat_id = task.delivery.telegram_chat_id
        if not token or not chat_id:
            raise ValueError(
                "telegram_bot_token and telegram_chat_id required for TELEGRAM delivery"
            )

        text = result.output or result.error or "No output"
        # Truncate to Telegram's 4096 char limit
        if len(text) > 4000:
            text = text[:4000] + "\n... (truncated)"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        session = await self._get_session()
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        async with session.post(url, json=payload) as resp:
            if resp.status >= 400:
                body = await resp.text()
                self.logger.warning(
                    f"Telegram API returned {resp.status}: {body[:200]}"
                )

    async def _deliver_teams(self, task: AgentTask, result: TaskResult) -> None:
        """Send result to MS Teams via incoming webhook."""
        webhook_url = task.delivery.teams_webhook_url
        if not webhook_url:
            raise ValueError("teams_webhook_url required for TEAMS delivery")

        text = result.output or result.error or "No output"
        session = await self._get_session()

        # Teams incoming webhook expects Adaptive Card or simple text
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": f"Agent: {result.agent_name}",
                                "weight": "Bolder",
                                "size": "Medium",
                            },
                            {
                                "type": "TextBlock",
                                "text": text[:2000],
                                "wrap": True,
                            },
                        ],
                    },
                }
            ],
        }

        async with session.post(webhook_url, json=payload) as resp:
            if resp.status >= 400:
                body = await resp.text()
                self.logger.warning(
                    f"Teams webhook returned {resp.status}: {body[:200]}"
                )

    async def _deliver_email(self, task: AgentTask, result: TaskResult) -> None:
        """Send result via email using async-notify."""
        recipients = task.delivery.email_recipients
        if not recipients:
            raise ValueError("email_recipients required for EMAIL delivery")

        try:
            from notify import Notify
            from notify.models import Actor

            actors = [Actor(name=r, account=r) for r in recipients]
            subject = (
                task.delivery.email_subject
                or f"Agent Result: {result.agent_name}"
            )
            body = result.output or result.error or "No output"

            async with Notify("email") as notify:
                await notify.send(
                    recipient=actors,
                    subject=subject,
                    body=body,
                )
        except ImportError:
            self.logger.error(
                "async-notify not installed. Cannot deliver via EMAIL."
            )

    async def _deliver_redis_stream(
        self, task: AgentTask, result: TaskResult
    ) -> None:
        """Publish result to a Redis response stream.

        Requires the redis_listener to be available on the service.
        This is a no-op placeholder; actual publishing is handled by
        ``AgentService._process_task`` via ``RedisTaskListener.publish_result``.
        """
        self.logger.debug(
            f"Redis stream delivery for task {task.task_id} handled by service"
        )

    async def close(self) -> None:
        """Close the shared HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
