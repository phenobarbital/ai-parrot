"""GitHub webhook hook — receives and parses GitHub pull_request events."""
import hashlib
import hmac
from typing import Any, Dict, Optional

from aiohttp import web

from .base import BaseHook
from .models import GitHubWebhookConfig, HookType


class GitHubWebhookHook(BaseHook):
    """Receives GitHub webhook POST requests via an aiohttp route.

    Validates HMAC-SHA256 signatures when a secret token is configured.
    Parses ``pull_request`` events (opened, reopened, synchronize) and
    emits :class:`HookEvent` instances tagged ``github.pr_<action>``.

    Other event types (issues, push, …) and other ``pull_request`` actions
    (closed, edited, labeled, …) are ignored with a 200 response so GitHub
    does not back off the webhook delivery.
    """

    hook_type = HookType.GITHUB_WEBHOOK

    _RELEVANT_PR_ACTIONS = {"opened", "reopened", "synchronize"}

    def __init__(self, config: GitHubWebhookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        # Public mirror of the route path. Operators wiring auth-exclusion
        # lists (e.g. navigator-auth `add_exclude_list`) should read this
        # instead of touching `_config`.
        self.url: str = config.url

    async def start(self) -> None:
        self.logger.info(
            f"GitHubWebhookHook '{self.name}' ready (routes via setup_routes)"
        )

    async def stop(self) -> None:
        self.logger.info(f"GitHubWebhookHook '{self.name}' stopped")

    def setup_routes(self, app: Any) -> None:
        app.router.add_post(self._config.url, self._handle_post)
        self.logger.info(
            f"GitHub webhook route registered: POST {self._config.url}"
        )

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    async def _handle_post(self, request: web.Request) -> web.Response:
        try:
            body = await request.read()

            if self._config.secret_token:
                if not self._verify_signature(request, body):
                    return web.Response(status=401, text="Unauthorized")

            github_event = request.headers.get("X-GitHub-Event", "")
            delivery_id = request.headers.get("X-GitHub-Delivery", "")
            payload = await request.json()
            event_type = self._classify_event(github_event, payload)
            if event_type is None:
                return web.Response(status=200, text="Event ignored")

            pull_request = payload.get("pull_request") or {}
            repo = payload.get("repository") or {}
            user = pull_request.get("user") or {}
            head = pull_request.get("head") or {}
            base = pull_request.get("base") or {}

            event_payload: Dict[str, Any] = {
                "github_event": github_event,
                "action": payload.get("action"),
                "event_type": event_type,
                "delivery_id": delivery_id,
                "repository": repo.get("full_name"),
                "owner": (repo.get("owner") or {}).get("login"),
                "repo_name": repo.get("name"),
                "pr_number": pull_request.get("number"),
                "pr_url": pull_request.get("html_url"),
                "pr_title": pull_request.get("title"),
                "pr_body": pull_request.get("body") or "",
                "head_sha": head.get("sha"),
                "head_ref": head.get("ref"),
                "base_ref": base.get("ref"),
                "draft": pull_request.get("draft", False),
                "author": user.get("login"),
                "created_at": pull_request.get("created_at"),
                "updated_at": pull_request.get("updated_at"),
            }

            event = self._make_event(
                event_type=f"github.{event_type}",
                payload=event_payload,
                task=(
                    f"GitHub PR {event_type}: "
                    f"{repo.get('full_name')}#{pull_request.get('number')} "
                    f"— {pull_request.get('title', '')}"
                ),
            )
            await self.on_event(event)
            return web.json_response({"status": "accepted"}, status=202)

        except Exception as exc:
            self.logger.error(f"GitHub webhook error: {exc}")
            return web.Response(status=500, text="Internal Server Error")

    def _verify_signature(self, request: web.Request, body: bytes) -> bool:
        signature = request.headers.get("X-Hub-Signature-256")
        if not signature:
            return False
        computed = "sha256=" + hmac.new(
            self._config.secret_token.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, computed)

    @classmethod
    def _classify_event(
        cls, github_event: str, payload: Dict[str, Any]
    ) -> Optional[str]:
        if github_event != "pull_request":
            return None
        action = (payload.get("action") or "").lower()
        if action not in cls._RELEVANT_PR_ACTIONS:
            return None
        return f"pr_{action}"
