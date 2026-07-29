"""GitHub webhook hook — receives and parses GitHub pull_request events."""
import hashlib
import hmac
from typing import Any, Dict, Optional

from aiohttp import web

from navigator_eventbus.hooks.base import BaseHook
from navigator_eventbus.hooks.models import GitHubWebhookConfig, HookType


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

            event_payload = self._build_event_payload(
                github_event, event_type, payload, delivery_id
            )

            repo_full = event_payload.get("repository")
            pr_number = event_payload.get("pr_number")
            event = self._make_event(
                event_type=f"github.{event_type}",
                payload=event_payload,
                task=(
                    f"GitHub {event_type}: {repo_full}#{pr_number}"
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
    def _build_event_payload(
        cls,
        github_event: str,
        event_type: str,
        payload: Dict[str, Any],
        delivery_id: str,
    ) -> Dict[str, Any]:
        """Parse the raw GitHub payload into a normalized event dict.

        Three shapes are handled:

        - ``pull_request`` events → parsed from the top-level ``pull_request``
          (unchanged from the original behaviour).
        - ``issue_comment`` on a PR (``pr_comment``) → parsed from ``issue`` +
          ``comment``. The head SHA is **not** present in this payload, so
          ``head_sha``/``branch`` are ``None`` and the consumer must fetch them
          via the PR number.
        - ``pull_request_review`` (``pr_review``) → parsed from
          ``pull_request`` + ``review``; carries ``head_sha``, ``branch`` and
          ``review_state``.
        """
        repo = payload.get("repository") or {}
        base_payload: Dict[str, Any] = {
            "github_event": github_event,
            "action": payload.get("action"),
            "event_type": event_type,
            "delivery_id": delivery_id,
            "repository": repo.get("full_name"),
            "owner": (repo.get("owner") or {}).get("login"),
            "repo_name": repo.get("name"),
            "review_state": None,
        }

        if event_type == "pr_comment":
            issue = payload.get("issue") or {}
            comment = payload.get("comment") or {}
            user = comment.get("user") or {}
            base_payload.update(
                {
                    "pr_number": issue.get("number"),
                    "pr_url": issue.get("html_url"),
                    "pr_title": issue.get("title"),
                    "pr_body": comment.get("body") or "",
                    "body": comment.get("body") or "",
                    # Not available on issue_comment payloads — consumer fetches.
                    "head_sha": None,
                    "head_ref": None,
                    "branch": None,
                    "base_ref": None,
                    "draft": None,
                    "author": user.get("login"),
                    "created_at": comment.get("created_at"),
                    "updated_at": comment.get("updated_at"),
                }
            )
            return base_payload

        if event_type == "pr_review":
            pull_request = payload.get("pull_request") or {}
            review = payload.get("review") or {}
            user = review.get("user") or {}
            head = pull_request.get("head") or {}
            base = pull_request.get("base") or {}
            base_payload.update(
                {
                    "pr_number": pull_request.get("number"),
                    "pr_url": pull_request.get("html_url"),
                    "pr_title": pull_request.get("title"),
                    "pr_body": review.get("body") or "",
                    "body": review.get("body") or "",
                    "head_sha": head.get("sha"),
                    "head_ref": head.get("ref"),
                    "branch": head.get("ref"),
                    "base_ref": base.get("ref"),
                    "draft": pull_request.get("draft", False),
                    "author": user.get("login"),
                    "review_state": (review.get("state") or "").lower() or None,
                    "created_at": review.get("submitted_at"),
                    "updated_at": review.get("submitted_at"),
                }
            )
            return base_payload

        # Default: a ``pull_request`` action (opened / reopened / synchronize).
        pull_request = payload.get("pull_request") or {}
        user = pull_request.get("user") or {}
        head = pull_request.get("head") or {}
        base = pull_request.get("base") or {}
        base_payload.update(
            {
                "pr_number": pull_request.get("number"),
                "pr_url": pull_request.get("html_url"),
                "pr_title": pull_request.get("title"),
                "pr_body": pull_request.get("body") or "",
                "head_sha": head.get("sha"),
                "head_ref": head.get("ref"),
                "branch": head.get("ref"),
                "base_ref": base.get("ref"),
                "draft": pull_request.get("draft", False),
                "author": user.get("login"),
                "created_at": pull_request.get("created_at"),
                "updated_at": pull_request.get("updated_at"),
            }
        )
        return base_payload

    @classmethod
    def _classify_event(
        cls, github_event: str, payload: Dict[str, Any]
    ) -> Optional[str]:
        action = (payload.get("action") or "").lower()

        if github_event == "pull_request":
            if action not in cls._RELEVANT_PR_ACTIONS:
                return None
            return f"pr_{action}"

        # issue_comment fires for BOTH issues and PRs — only treat it as a PR
        # comment when the issue carries a ``pull_request`` sub-object (FEAT-250).
        if github_event == "issue_comment":
            issue = payload.get("issue") or {}
            if action == "created" and issue.get("pull_request"):
                return "pr_comment"
            return None

        # A submitted PR review (approved / changes_requested / commented).
        if github_event == "pull_request_review":
            if action == "submitted":
                return "pr_review"
            return None

        return None
