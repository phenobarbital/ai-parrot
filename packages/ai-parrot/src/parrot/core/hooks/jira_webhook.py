"""Jira webhook hook — receives and parses Jira issue events."""
import hashlib
import hmac
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from .base import BaseHook
from .models import HookType, JiraWebhookConfig


class JiraWebhookHook(BaseHook):
    """Receives Jira webhook POST requests via an aiohttp route.

    Validates HMAC signatures when a secret token is configured.
    Parses issue events (created, updated, closed, deleted) and
    emits HookEvents.
    """

    hook_type = HookType.JIRA_WEBHOOK

    def __init__(self, config: JiraWebhookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config

    async def start(self) -> None:
        self.logger.info(
            f"JiraWebhookHook '{self.name}' ready (routes via setup_routes)"
        )

    async def stop(self) -> None:
        self.logger.info(f"JiraWebhookHook '{self.name}' stopped")

    def setup_routes(self, app: Any) -> None:
        app.router.add_post(self._config.url, self._handle_post)
        self.logger.info(f"Jira webhook route registered: POST {self._config.url}")

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    async def _handle_post(self, request: web.Request) -> web.Response:
        try:
            body = await request.read()

            # HMAC signature validation
            if self._config.secret_token:
                if not self._verify_signature(request, body):
                    return web.Response(status=401, text="Unauthorized")

            payload = await request.json()
            event_type = self._classify_event(payload)
            if event_type is None:
                return web.Response(status=200, text="Event ignored")

            issue = payload.get("issue", {})
            fields = issue.get("fields", {})
            assignee_field = fields.get("assignee") or {}
            event_payload: Dict[str, Any] = {
                "webhook_event": payload.get("webhookEvent"),
                "event_type": event_type,
                "issue_key": issue.get("key"),
                "issue_id": issue.get("id"),
                "summary": fields.get("summary", ""),
                "description": fields.get("description"),
                "status": (fields.get("status") or {}).get("name"),
                "priority": (fields.get("priority") or {}).get("name"),
                "project_key": (fields.get("project") or {}).get("key"),
                "reporter": (fields.get("reporter") or {}).get("displayName"),
                "assignee": {
                    "account_id": assignee_field.get("accountId"),
                    "email": assignee_field.get("emailAddress"),
                    "display_name": assignee_field.get("displayName"),
                    "name": assignee_field.get("name"),
                },
                "changelog": payload.get("changelog"),
                "user": payload.get("user", {}),
                "timestamp": payload.get("timestamp"),
            }

            if event_type == "assigned":
                prev, curr = self._extract_assignee_change(payload)
                event_payload["previous_assignee"] = prev
                event_payload["new_assignee"] = curr

            event = self._make_event(
                event_type=f"jira.{event_type}",
                payload=event_payload,
                task=f"Jira issue {event_type}: {issue.get('key')} — {fields.get('summary', '')}",
            )
            await self.on_event(event)
            return web.json_response({"status": "accepted"}, status=202)

        except Exception as exc:
            self.logger.error(f"Jira webhook error: {exc}")
            return web.Response(status=500, text="Internal Server Error")

    def _verify_signature(self, request: web.Request, body: bytes) -> bool:
        signature = request.headers.get("X-Hub-Signature")
        if not signature:
            return False
        computed = "sha256=" + hmac.new(
            self._config.secret_token.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, computed)

    @staticmethod
    def _classify_event(payload: Dict[str, Any]) -> Optional[str]:
        webhook_event = payload.get("webhookEvent", "")
        if webhook_event == "jira:issue_created":
            fields = (payload.get("issue") or {}).get("fields") or {}
            if (fields.get("assignee") or {}).get("accountId"):
                return "assigned"
            return "created"
        if webhook_event == "jira:issue_deleted":
            return "deleted"
        if webhook_event == "jira:issue_updated":
            changelog = payload.get("changelog", {})
            items = changelog.get("items", [])
            for item in items:
                if item.get("field") == "assignee":
                    if item.get("to"):
                        return "assigned"
                    return "unassigned"
            for item in items:
                if item.get("field") == "status":
                    if (item.get("toString") or "").lower() == "closed":
                        return "closed"
                    return "updated"
            return "updated"
        return None

    @staticmethod
    def _extract_assignee_change(
        payload: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Optional[str]]], Optional[Dict[str, Optional[str]]]]:
        """Extract previous/current assignee from a Jira changelog payload.

        Returns a tuple of ``(previous, current)`` dicts (or ``None`` when a
        side is empty). Each dict carries ``account_id`` and ``display_name``.

        On ``jira:issue_created`` no changelog exists, so the previous side
        is ``None`` and the current side is sourced from the issue fields.
        """
        items = (payload.get("changelog") or {}).get("items") or []
        for item in items:
            if item.get("field") == "assignee":
                prev = None
                curr = None
                if item.get("from"):
                    prev = {
                        "account_id": item.get("from"),
                        "display_name": item.get("fromString"),
                    }
                if item.get("to"):
                    curr = {
                        "account_id": item.get("to"),
                        "display_name": item.get("toString"),
                    }
                return prev, curr

        assignee = (
            ((payload.get("issue") or {}).get("fields") or {}).get("assignee") or {}
        )
        if assignee:
            return None, {
                "account_id": assignee.get("accountId"),
                "display_name": assignee.get("displayName"),
            }
        return None, None
