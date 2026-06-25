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
import json
import logging
import os
import re
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

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
# Reconcile sweep (webhook-less fallback cleanup)
# ---------------------------------------------------------------------------
#
# The webhook above only fires when a public endpoint receives GitHub's
# ``pull_request.closed`` event. Local / endpoint-less runs therefore never
# clean up, so dev-loop worktrees pile up. ``sweep_finished_worktrees`` is the
# pollable equivalent: it lists the live dev-loop worktrees and removes only
# those whose PR is already merged or closed (and, opt-in, abandoned ones with
# no PR). Worktrees with an *open* PR are always kept, because the revision
# loop (``revision_handoff``) reuses the same worktree/branch to push
# reviewer-requested changes onto the existing PR.


async def _list_dev_loop_worktrees(
    cwd: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Return ``(path, branch)`` for every live dev-loop worktree.

    Parses ``git worktree list --porcelain`` and keeps only entries whose
    branch matches the ``feat-<id>[-<slug>]`` convention. Returns an empty
    list if git fails (best effort — the caller logs and continues).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "list", "--porcelain",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("`git worktree list` raised: %s", exc)
        return []
    if proc.returncode != 0:
        logger.warning(
            "`git worktree list` exited %s: %s",
            proc.returncode, stderr.decode(errors="replace").strip(),
        )
        return []

    entries: List[Tuple[str, str]] = []
    cur_path: Optional[str] = None
    for raw in stdout.decode(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("worktree "):
            cur_path = line[len("worktree "):]
        elif line.startswith("branch ") and cur_path is not None:
            ref = line[len("branch "):]
            branch = ref.rsplit("/", 1)[-1]  # refs/heads/feat-1 -> feat-1
            if _is_dev_loop_branch(branch):
                entries.append((cur_path, branch))
        elif not line:
            cur_path = None
    return entries


async def _gh_pr_state(branch: str, cwd: Optional[str] = None) -> Optional[str]:
    """Return the PR state for *branch* via the ``gh`` CLI.

    One of ``"merged"``, ``"closed"``, ``"open"``, or ``None`` when no PR
    exists or ``gh`` is unavailable/unauthenticated (treated as "unknown" —
    the caller keeps the worktree unless orphan removal is requested).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "list",
            "--head", branch,
            "--state", "all",
            "--json", "state,mergedAt",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError:
        logger.warning("`gh` CLI not found — cannot resolve PR state for %s.", branch)
        return None
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("`gh pr list` for %s raised: %s", branch, exc)
        return None
    if proc.returncode != 0:
        logger.info(
            "`gh pr list` for %s exited %s: %s",
            branch, proc.returncode, stderr.decode(errors="replace").strip(),
        )
        return None
    try:
        prs = json.loads(stdout.decode(errors="replace") or "[]")
    except json.JSONDecodeError:
        return None
    if not prs:
        return None
    # Prefer the most decisive state: merged > open > closed.
    states = {(pr.get("state") or "").lower() for pr in prs}
    if any(pr.get("mergedAt") for pr in prs) or "merged" in states:
        return "merged"
    if "open" in states:
        return "open"
    if "closed" in states:
        return "closed"
    return None


async def sweep_finished_worktrees(
    *,
    pr_state_fn: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
    remove_orphans: bool = False,
    dry_run: bool = False,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Remove dev-loop worktrees whose PR is merged/closed. Best effort.

    The webhook-less fallback for worktree cleanup. Lists every live dev-loop
    worktree and decides per branch:

    * PR **merged** or **closed** → remove the worktree.
    * PR **open** → keep (a reviewer revision may still reuse it).
    * **No PR** (orphan) → kept by default; removed only when
      ``remove_orphans=True`` (e.g. a run that failed before opening a PR).

    Args:
        pr_state_fn: Async ``branch -> state`` resolver returning one of
            ``"merged"``/``"closed"``/``"open"``/``None``. Defaults to the
            ``gh`` CLI (:func:`_gh_pr_state`). Injectable for tests.
        remove_orphans: Also remove worktrees with no PR.
        dry_run: Report what would be removed without touching anything.
        cwd: Working directory for the git/gh subprocesses (defaults to the
            current process dir; pass the repo root when calling out-of-tree).

    Returns:
        A report dict ``{"removed": [...], "kept": [{"branch", "reason"}],
        "errors": [...], "dry_run": bool}``.
    """
    resolve = pr_state_fn or (lambda b: _gh_pr_state(b, cwd=cwd))
    report: Dict[str, Any] = {
        "removed": [], "kept": [], "errors": [], "dry_run": dry_run,
    }

    worktrees = await _list_dev_loop_worktrees(cwd=cwd)
    for _path, branch in worktrees:
        try:
            state = await resolve(branch)
        except Exception as exc:  # noqa: BLE001 - best effort, per-branch
            report["errors"].append({"branch": branch, "error": str(exc)})
            continue

        if state in ("merged", "closed"):
            reason = f"pr_{state}"
        elif state == "open":
            report["kept"].append({"branch": branch, "reason": "pr_open"})
            continue
        else:  # no PR / unknown
            if not remove_orphans:
                report["kept"].append({"branch": branch, "reason": "no_pr"})
                continue
            reason = "orphan_no_pr"

        if dry_run:
            report["removed"].append({"branch": branch, "reason": reason, "dry_run": True})
            continue
        await cleanup_worktree(branch)
        report["removed"].append({"branch": branch, "reason": reason})

    logger.info(
        "sweep_finished_worktrees: removed=%d kept=%d errors=%d (dry_run=%s)",
        len(report["removed"]), len(report["kept"]),
        len(report["errors"]), dry_run,
    )
    return report


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
    "sweep_finished_worktrees",
]
