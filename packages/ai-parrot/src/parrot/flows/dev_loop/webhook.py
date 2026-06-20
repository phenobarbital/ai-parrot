"""GitHub ``pull_request.closed`` webhook for worktree cleanup.

Implements **Module 11** of the dev-loop spec. Worktree cleanup is
external to the flow itself (spec G8). Two paths trigger it:

1. A human running ``/sdd-done`` manually after a merge.
2. **This module**: a webhook listener registered on the existing
   :class:`parrot.autonomous.AutonomousOrchestrator.WebhookListener`
   via ``orchestrator.register_webhook(...)``. The listener handles
   HMAC validation — this module only adds the GitHub-specific
   transform and cleanup helper.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import OrderedDict
from typing import Any, Dict, Optional

from parrot import conf
from parrot.flows.dev_loop.models import RevisionBrief

logger = logging.getLogger(__name__)

# Cap on the revision dedup cache so a long-lived handler cannot grow without
# bound. Head SHAs evict oldest-first (LRU-ish) once the cap is reached.
_MAX_SEEN_HEAD_SHAS = 10_000


# ---------------------------------------------------------------------------
# Branch matcher
# ---------------------------------------------------------------------------


_DEV_LOOP_BRANCH_RE = re.compile(r"^feat-\d+(?:-[\w-]+)?$")


def _is_dev_loop_branch(name: str) -> bool:
    """Return ``True`` for branches matching ``feat-<id>[-<slug>]``."""
    return bool(_DEV_LOOP_BRANCH_RE.match(name))


# ---------------------------------------------------------------------------
# Payload transform
# ---------------------------------------------------------------------------


def _transform_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Transform a GitHub webhook payload into a cleanup command.

    Returns ``None`` when the event is irrelevant (the listener will
    drop it). Returns ``"cleanup_worktree:<branch>"`` when the event
    is a ``pull_request.closed`` whose head branch matches the
    dev-loop convention.
    """
    if payload.get("action") != "closed":
        return None
    pr = payload.get("pull_request") or {}
    head = pr.get("head") or {}
    head_ref = head.get("ref") or ""
    if not _is_dev_loop_branch(head_ref):
        return None
    return f"cleanup_worktree:{head_ref}"


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------


async def cleanup_worktree(branch: str) -> None:
    """Run ``git worktree remove`` then ``git worktree prune``.

    Best-effort: a missing worktree (already cleaned) is *not* an error.
    All subprocess failures are logged and swallowed.
    """
    path = os.path.join(conf.WORKTREE_BASE_PATH, branch)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "remove",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.info(
                "git worktree remove %s exited %s (likely already cleaned): %s",
                path,
                proc.returncode,
                stderr.decode(errors="replace").strip(),
            )
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("worktree remove for %s raised: %s", path, exc)

    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "prune",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("worktree prune raised: %s", exc)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_pull_request_webhook(
    orchestrator: Any,
    *,
    secret: str,
    path: str = "/github/dev-loop",
    target_id: str = "dev-loop-cleanup",
) -> None:
    """Register the GitHub ``pull_request.closed`` webhook handler.

    Args:
        orchestrator: A :class:`parrot.autonomous.AutonomousOrchestrator`.
        secret: HMAC secret configured on the GitHub webhook.
        path: HTTP path for the listener (default ``/github/dev-loop``).
        target_id: Logical target id used by the orchestrator's
            WebhookListener to dispatch to the cleanup helper.
    """
    orchestrator.register_webhook(
        path=path,
        target_type="agent",
        target_id=target_id,
        secret=secret,
        transform_fn=_transform_payload,
    )


# ---------------------------------------------------------------------------
# Revision trigger (FEAT-250 G6)
# ---------------------------------------------------------------------------


class RevisionWebhookHandler:
    """React to ``github.pr_comment`` / ``github.pr_review`` events.

    Filters reviewer feedback by ``DEV_LOOP_REVISION_TRIGGER``, drops
    bot-authored comments, dedups by ``head_sha`` (mirroring
    ``GitHubReviewer``), builds a :class:`RevisionBrief`, and calls
    ``DevLoopRunner.run_revision(...)``. A single handler instance keeps the
    seen-``head_sha`` set so a chatty PR cannot spawn a revision storm (R3).

    Args:
        runner: A ``DevLoopRunner`` constructed with the revision deps.
        trigger: Override for ``conf.DEV_LOOP_REVISION_TRIGGER`` —
            ``"changes_requested"`` (default), ``"any_comment"`` or
            ``"command"`` (``/revise`` prefix).
        bot_login: GitHub login of the flow-bot; comments authored by it are
            ignored. When ``None``, no author is treated as a bot.
        repo_base_path: Base dir under which the existing clone lives; the
            revision reuses ``<repo_base_path>/<branch>``. Defaults to
            ``conf.WORKTREE_BASE_PATH``.
    """

    def __init__(
        self,
        runner: Any,
        *,
        trigger: Optional[str] = None,
        bot_login: Optional[str] = None,
        repo_base_path: Optional[str] = None,
    ) -> None:
        self._runner = runner
        self._trigger = trigger or conf.DEV_LOOP_REVISION_TRIGGER
        self._bot_login = bot_login
        self._repo_base = repo_base_path or conf.WORKTREE_BASE_PATH
        # Bounded dedup cache (insertion-ordered → oldest evicted first).
        self._seen_head_shas: "OrderedDict[str, None]" = OrderedDict()
        self.logger = logging.getLogger("parrot.dev_loop.revision_webhook")

    def _mark_seen(self, head_sha: str) -> None:
        """Record ``head_sha`` in the bounded dedup cache."""
        self._seen_head_shas[head_sha] = None
        while len(self._seen_head_shas) > _MAX_SEEN_HEAD_SHAS:
            self._seen_head_shas.popitem(last=False)

    def _is_bot(self, author: Optional[str]) -> bool:
        return bool(self._bot_login) and author == self._bot_login

    def _passes_trigger(self, event_type: str, payload: Dict[str, Any]) -> bool:
        body = (payload.get("body") or "").strip()
        state = payload.get("review_state") or ""
        if self._trigger == "command":
            return body.startswith("/revise")
        if self._trigger == "any_comment":
            return True
        # Default: only PR reviews that explicitly request changes.
        return event_type.endswith("pr_review") and state == "changes_requested"

    def _build_brief(self, payload: Dict[str, Any]) -> Optional[RevisionBrief]:
        pr_number = payload.get("pr_number")
        branch = payload.get("branch") or payload.get("head_ref")
        if pr_number is None or not branch:
            # issue_comment payloads carry no branch/head_sha — cannot revise.
            return None
        repo_path = os.path.join(self._repo_base, branch)
        return RevisionBrief(
            repo_path=repo_path,
            branch=branch,
            pr_number=int(pr_number),
            repository=payload.get("repository") or "",
            jira_issue_key=payload.get("jira_issue_key") or "",
            feedback=payload.get("body") or "",
            head_sha=payload.get("head_sha") or "",
        )

    async def handle_event(
        self, event_type: str, payload: Dict[str, Any]
    ) -> Optional[Any]:
        """Maybe trigger a revision run. Returns the ``FlowResult`` or ``None``.

        ``None`` is returned (no run) when the comment is bot-authored, fails
        the trigger filter, is a duplicate ``head_sha`` delivery, or lacks the
        fields needed to build a :class:`RevisionBrief`.
        """
        author = payload.get("author")
        if self._is_bot(author):
            self.logger.debug("Ignoring bot-authored comment from %s", author)
            return None
        if not self._passes_trigger(event_type, payload):
            return None
        head_sha = payload.get("head_sha") or ""
        if head_sha and head_sha in self._seen_head_shas:
            self.logger.info("Deduped revision for head_sha=%s", head_sha)
            return None
        brief = self._build_brief(payload)
        if brief is None:
            return None
        if head_sha:
            self._mark_seen(head_sha)
        self.logger.info(
            "Triggering revision run for PR #%s (branch %s)",
            brief.pr_number, brief.branch,
        )
        return await self._runner.run_revision(brief)


__all__ = [
    "RevisionWebhookHandler",
    "cleanup_worktree",
    "register_pull_request_webhook",
]
