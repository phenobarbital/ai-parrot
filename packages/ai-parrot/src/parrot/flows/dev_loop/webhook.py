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
from typing import Any, Dict, Optional

from parrot import conf

logger = logging.getLogger(__name__)


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


__all__ = [
    "cleanup_worktree",
    "register_pull_request_webhook",
]
