"""DeploymentHandoffNode — push, open PR, transition Jira.

Implements **Module 8** of the dev-loop spec. Pure AI-Parrot — does NOT
call the dispatcher. After QA passes, this node:

1. Pushes the branch (``git push -u origin <branch_name>``).
2. Opens a PR. Primary path: ``gh pr create`` (when the CLI is on
   ``$PATH``). Fallback: a direct ``POST /repos/{owner}/{repo}/pulls``
   call via :mod:`aiohttp`. The fallback uses a personal access token
   from the environment (``GITHUB_TOKEN``).
3. Transitions the Jira ticket to *Ready to Deploy* via
   ``jira_transition_issue``.
4. Posts the PR URL as a Jira comment via ``jira_add_comment``.
5. Retries the PR step **once** with a 2 s backoff before falling back
   to the *Deployment Blocked* status.

The node does NOT raise on the *blocked* path — it returns a structured
``dict`` so the orchestrator can record the outcome cleanly.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any, Dict, Optional, Union

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.models import (
    BugBrief,
    DevelopmentOutput,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import (
    DevLoopNode,
    register_dev_loop_node,
    scrub_git_output,
    transition_issue_with_candidates,
)


@register_dev_loop_node("dev_loop.deployment_handoff")
class DeploymentHandoffNode(DevLoopNode):
    """Fifth (success-path) node — handles PR creation and Jira handoff.

    Args:
        jira_toolkit: ``parrot_tools.jiratoolkit.JiraToolkit`` instance
            already wired with bot credentials.
        git_toolkit: Optional Git toolkit used for the HTTP fallback when
            ``gh`` is unavailable. The toolkit's ``create_pull_request``
            shape is file-bundle oriented; in v1 we prefer the bare HTTP
            fallback (``_create_pr_via_rest``) which the test suite
            patches directly.
        gh_cli_path: Override path to the ``gh`` CLI binary.
        target_repo: ``"<owner>/<repo>"`` for the GitHub REST fallback.
            Reads ``GITHUB_REPOSITORY`` env var when not provided.
        base_branch: Default base branch for the PR (default ``"dev"``).
        name: Node id (default ``"deployment_handoff"``).
        require_deployment_approval: FEAT-322 opt-in — when ``True`` AND a
            ``SessionHost`` is present in shared state, opens a blocking
            ``deployment_approval`` HITL gate before the Jira transition.
            Defaults to ``False`` so existing/legacy runs (which now always
            have a host seeded by ``DevLoopRunner.run()``, TASK-1851) are
            NOT unexpectedly gated — mirrors ``ManualCriterion.blocking``'s
            explicit opt-in philosophy (spec §1 G4 zero-regression).
    """

    def __init__(
        self,
        *,
        jira_toolkit: Any,
        git_toolkit: Any = None,
        gh_cli_path: Optional[str] = None,
        target_repo: Optional[str] = None,
        base_branch: str = "dev",
        name: str = "deployment_handoff",
        require_deployment_approval: bool = False,
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_jira", jira_toolkit)
        object.__setattr__(self, "_git", git_toolkit)
        object.__setattr__(self, "_gh_cli_path", gh_cli_path)
        object.__setattr__(
            self,
            "_target_repo",
            target_repo or os.environ.get("GITHUB_REPOSITORY", ""),
        )
        object.__setattr__(self, "_base_branch", base_branch)
        object.__setattr__(
            self, "_require_deployment_approval", require_deployment_approval
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Push, PR, transition Jira, comment.

        Args:
            ctx: Flow context whose shared state carries ``research_output``,
                ``bug_brief``, and optionally ``development_output`` /
                ``qa_report``.
            deps: Dependency results (unused).
            **kwargs: Extra execution context (ignored).

        Returns:
            ``{"status": "ready_to_deploy", "pr_url": "...", "pr_number": int}``
            on success (the PR is opened as a DRAFT; ``pr_number`` enables the
            revision loop to comment on the same PR), or
            ``{"status": "blocked", "error": "..."}`` after the retry
            budget is exhausted.
        """
        shared = self.shared_state(ctx)
        research: ResearchOutput = shared["research_output"]
        brief: BugBrief = shared["bug_brief"]
        dev_out: DevelopmentOutput = shared.get("development_output")
        qa_report: QAReport = shared.get("qa_report")
        issue_key = research.jira_issue_key

        # 1. Push.
        try:
            await self._push_branch(
                research.branch_name, research.worktree_path
            )
        except RuntimeError as exc:
            self.logger.error("git push failed: %s", exc)
            await self._mark_blocked(issue_key, str(exc))
            return {"status": "blocked", "error": f"push: {exc}"}

        # 2. Open PR with retry-once.
        title = self._build_title(brief, research)
        body = self._build_body(research, dev_out, qa_report)
        pr_url: Optional[str] = None
        last_error: Optional[str] = None
        for attempt in range(2):
            try:
                pr_url = await self._create_pr(
                    research.branch_name, title, body
                )
                break
            except Exception as exc:  # noqa: BLE001 - retry boundary
                last_error = str(exc)
                if attempt == 0:
                    self.logger.warning(
                        "PR create failed (attempt %s), retrying: %s",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(2)
                else:
                    self.logger.error(
                        "PR create failed after retry: %s", exc
                    )

        if pr_url is None:
            await self._mark_blocked(
                issue_key, last_error or "unknown PR error"
            )
            return {
                "status": "blocked",
                "error": last_error or "unknown PR error",
            }

        pr_number = self._parse_pr_number(pr_url)

        # FEAT-322: deployment_approval HITL gate — between PR creation and
        # the Jira transition. A human must approve before the ticket moves;
        # reject/expire routes through the existing blocked path (no Jira
        # transition happens). Opt-in via ``require_deployment_approval``
        # (default False): ``DevLoopRunner.run()`` always seeds
        # ``shared["session_host"]`` now (TASK-1851), so gating on host
        # presence ALONE would make every existing/legacy run block forever
        # on an unresolved gate — the explicit flag preserves
        # "zero-regression by default" (spec §1 G4) the same way
        # ``ManualCriterion.blocking`` does for QA. No-host fallback (e.g. a
        # node invoked outside the runner) logs a WARNING and proceeds.
        host = shared.get("session_host")
        if self._require_deployment_approval and host is not None:
            gate_status, gate_error = await self._await_deployment_approval(
                host, shared.get("run_id", ""), issue_key, pr_url,
            )
            if gate_status != "approved":
                await self._mark_blocked(issue_key, gate_error)
                return {"status": "blocked", "error": gate_error}
        elif self._require_deployment_approval and host is None:
            self.logger.warning(
                "DeploymentHandoffNode: require_deployment_approval=True but "
                "no session_host in shared state (legacy DevLoopRunner "
                "construction) — proceeding without a deployment_approval "
                "gate."
            )

        # 3. Transition Jira.
        try:
            await transition_issue_with_candidates(
                self._jira,
                issue_key,
                conf.DEV_LOOP_JIRA_TRANSITIONS_READY,
                logger=self.logger,
            )
        except Exception as exc:  # noqa: BLE001 - degraded path
            self.logger.warning(
                "Jira transition failed (continuing): %s", exc
            )

        # 4. Comment with PR link.
        try:
            await self._jira.jira_add_comment(
                issue=issue_key,
                body=(
                    f"flow-bot: PR opened — {pr_url}\n"
                    f"QA passed all acceptance criteria."
                ),
            )
        except Exception as exc:  # noqa: BLE001 - degraded path
            self.logger.warning("Jira add_comment failed: %s", exc)

        return {
            "status": "ready_to_deploy",
            "pr_url": pr_url,
            "pr_number": pr_number,
        }

    # ------------------------------------------------------------------
    # Internal — deployment_approval HITL gate (FEAT-322)
    # ------------------------------------------------------------------

    async def _await_deployment_approval(
        self, host: Any, run_id: str, issue_key: str, pr_url: str,
    ) -> tuple[str, str]:
        """Open the ``deployment_approval`` gate and await its resolution.

        Args:
            host: The run's ``SessionHost`` (never ``None`` — callers only
                invoke this when a host is present).
            run_id: The run id, used to build the changeset ``payload_ref``.
            issue_key: The Jira issue key (used in the gate title).
            pr_url: The draft PR URL (surfaced in the gate instructions).

        Returns:
            A ``(gate_status, error_message)`` tuple. ``error_message`` is
            ``""`` when ``gate_status == "approved"``; otherwise it is the
            ``"deployment_approval <status> by <resolver>"`` reason used
            for the blocked-path Jira comment.
        """
        # Lazy imports — avoid a runner.py <-> factories.py <-> this module
        # import cycle (runner.py imports factories.py, which imports this
        # module to build the node).
        from parrot.flows.dev_loop.runner import gate_ttl_for
        from parrot.flows.dev_loop.session_state import changeset_channel

        gate_id, _ = host.open_gate(
            kind="deployment_approval",
            node_id="deployment_handoff",
            title=f"Deploy approval: {issue_key}",
            instructions=f"Approve deployment for PR {pr_url}",
            payload_ref=changeset_channel(run_id) if run_id else "",
            ttl_seconds=gate_ttl_for("deployment_approval"),
            on_expiry="fail",
        )
        gate = await host.wait_gate(gate_id)
        if gate.status == "approved":
            return "approved", ""
        reason = (
            f"deployment_approval {gate.status} by "
            f"{gate.resolved_by or 'ttl'}"
        )
        return gate.status, reason

    # ------------------------------------------------------------------
    # Internal — git push
    # ------------------------------------------------------------------

    async def _push_branch(self, branch: str, cwd: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            cwd,
            "push",
            "-u",
            "origin",
            branch,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"git push failed: {scrub_git_output(stderr.decode(errors='replace'))}"
            )

    # ------------------------------------------------------------------
    # Internal — PR creation
    # ------------------------------------------------------------------

    def _gh_available(self) -> bool:
        return shutil.which(self._gh_cli_path or "gh") is not None

    @staticmethod
    def _parse_pr_number(pr_url: str) -> Optional[int]:
        """Extract the trailing PR number from a GitHub PR URL.

        ``https://github.com/owner/repo/pull/42`` → ``42``. Returns ``None``
        when no integer tail is present. Both the ``gh`` and the REST
        (``html_url``) paths surface a ``…/pull/<n>`` URL.
        """
        tail = pr_url.rstrip("/").rsplit("/", 1)[-1] if pr_url else ""
        return int(tail) if tail.isdigit() else None

    async def _create_pr(self, branch: str, title: str, body: str) -> str:
        """Open a DRAFT PR; return the PR URL (number derived by the caller)."""
        if self._gh_available():
            return await self._create_pr_with_gh(branch, title, body)
        return await self._create_pr_via_rest(branch, title, body)

    async def _create_pr_with_gh(
        self, branch: str, title: str, body: str
    ) -> str:
        gh_path = self._gh_cli_path or "gh"
        proc = await asyncio.create_subprocess_exec(
            gh_path,
            "pr",
            "create",
            "--draft",
            "--base",
            self._base_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"gh pr create failed: {err.decode(errors='replace')}"
            )
        text = out.decode().strip()
        # The last line of `gh pr create` output is the PR URL.
        return text.splitlines()[-1] if text else ""

    async def _create_pr_via_rest(
        self, branch: str, title: str, body: str
    ) -> str:
        # Pure HTTP fallback. We import aiohttp lazily so test harnesses
        # can monkeypatch the helper without aiohttp involvement at all.
        import aiohttp  # noqa: WPS433 - intentional lazy import

        token = os.environ.get("GITHUB_TOKEN", "")
        if not self._target_repo or not token:
            raise RuntimeError(
                "GitHub REST fallback requires target_repo + GITHUB_TOKEN"
            )
        url = f"https://api.github.com/repos/{self._target_repo}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": branch,
            "base": self._base_branch,
            "draft": True,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, json=payload, headers=headers
            ) as resp:
                data = await resp.json()
                if resp.status >= 300:
                    raise RuntimeError(
                        f"GitHub REST {resp.status}: {data}"
                    )
                return data.get("html_url", "")

    # ------------------------------------------------------------------
    # Internal — Jira blocked path
    # ------------------------------------------------------------------

    async def _mark_blocked(self, issue_key: str, error: str) -> None:
        try:
            await transition_issue_with_candidates(
                self._jira,
                issue_key,
                conf.DEV_LOOP_JIRA_TRANSITIONS_BLOCKED,
                logger=self.logger,
            )
        except Exception as exc:  # noqa: BLE001 - degraded path
            self.logger.warning("Blocked transition failed: %s", exc)
        try:
            await self._jira.jira_add_comment(
                issue=issue_key,
                body=f"flow-bot: deployment blocked — {error}",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Blocked comment failed: %s", exc)

    # ------------------------------------------------------------------
    # Internal — copy
    # ------------------------------------------------------------------

    @staticmethod
    def _build_title(brief: BugBrief, research: ResearchOutput) -> str:
        first_line = brief.summary.splitlines()[0][:80]
        return f"{research.feat_id}: {first_line}"

    @staticmethod
    def _build_body(
        research: ResearchOutput,
        dev_out: Optional[DevelopmentOutput],
        qa_report: Optional[QAReport],
    ) -> str:
        files = (
            ", ".join(dev_out.files_changed[:10])
            if dev_out
            else "(none)"
        )
        criteria = (
            "\n".join(
                f"- {r.name}: {'PASS' if r.passed else 'FAIL'}"
                for r in (qa_report.criterion_results if qa_report else [])
            )
            or "(none)"
        )
        return (
            f"## Summary\n\n"
            f"Spec: `{research.spec_path}`\n"
            f"Jira: `{research.jira_issue_key}`\n\n"
            f"## Files changed\n\n{files}\n\n"
            f"## QA evidence\n\n{criteria}\n\n"
            f"---\n_Created by flow-bot via the dev-loop._"
        )


__all__ = ["DeploymentHandoffNode"]
