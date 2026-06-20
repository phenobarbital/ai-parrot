"""RevisionHandoffNode — push to the existing branch + comment the same PR.

Implements the handoff half of **Module 9** (FEAT-250 G6). On the revision
path (a reviewer asked for changes on a draft PR), this terminal-ish node:

1. ``git push`` to the **existing** feature branch (subprocess, mirroring
   ``DeploymentHandoffNode._push_branch``), and
2. ``git_toolkit.add_pr_comment(pr_number, …)`` on the **same** PR.

It MUST NOT call ``create_pull_request`` — the revision loop updates the
existing draft PR, it never opens a new one. Like the other terminal nodes it
never raises: failures degrade to a structured status dict.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Union

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node


@register_dev_loop_node("dev_loop.revision_handoff")
class RevisionHandoffNode(DevLoopNode):
    """Revision-path handoff — push existing branch + comment existing PR."""

    def __init__(
        self,
        git_toolkit: Any,
        name: str = "revision_handoff",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_git", git_toolkit)

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Push the revised branch and comment on the same PR. Never raises.

        Reads ``repo_path``/``branch``/``pr_number``/``repository``/``feedback``
        from the shared state (seeded by ``DevLoopRunner.run_revision``). Marks
        ``shared["mode"] = "revision"`` for the close node.

        Returns:
            ``{"status": "revised", "pr_number": int, "branch": str}`` on
            success, or ``{"status": "blocked"/"comment_failed", "error": ...}``.
        """
        shared = self.shared_state(ctx)
        shared["mode"] = "revision"

        research = shared.get("research_output")
        repo_path = shared.get("repo_path") or (
            getattr(research, "repo_path", "") or getattr(research, "worktree_path", "")
        )
        branch = shared.get("branch") or getattr(research, "branch_name", "")
        pr_number = shared.get("pr_number")
        repository = shared.get("repository")
        feedback = shared.get("feedback", "")

        # 1. Push to the EXISTING branch.
        try:
            await self._push_branch(branch, repo_path)
        except RuntimeError as exc:
            self.logger.error("revision git push failed: %s", exc)
            return {"status": "blocked", "error": f"push: {exc}", "branch": branch}

        # 2. Comment on the SAME PR — never open a new one.
        body = (
            "flow-bot: applied the requested revision and re-ran QA on the "
            f"existing branch `{branch}`.\n\nReviewer feedback addressed:\n"
            f"> {feedback}" if feedback else
            f"flow-bot: applied the requested revision and re-ran QA on `{branch}`."
        )
        try:
            await self._git.add_pr_comment(
                pr_number, body=body, repository=repository
            )
        except Exception as exc:  # noqa: BLE001 - terminal node, never raises
            self.logger.exception("revision add_pr_comment failed: %s", exc)
            return {
                "status": "comment_failed",
                "pr_number": pr_number,
                "branch": branch,
                "error": str(exc),
            }

        return {"status": "revised", "pr_number": pr_number, "branch": branch}

    # ------------------------------------------------------------------
    # Internal — git push (mirrors DeploymentHandoffNode._push_branch)
    # ------------------------------------------------------------------

    async def _push_branch(self, branch: str, cwd: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            cwd,
            "push",
            "origin",
            branch,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"git push failed: {stderr.decode(errors='replace')}"
            )


__all__ = ["RevisionHandoffNode"]
