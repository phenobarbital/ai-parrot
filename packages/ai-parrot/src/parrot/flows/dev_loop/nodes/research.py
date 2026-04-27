"""ResearchNode — bug triage, Jira ticket, sdd-research dispatch.

Implements **Module 5** of the dev-loop spec. Sequence (per spec §3 M5):

1. Fetch logs via the configured log toolkits (one per ``LogSource.kind``).
2. Create the Jira ticket via ``jira_toolkit.jira_create_issue(...)``.
   The ticket is created **before** the dispatch — the call order is
   pinned by a unit test (spec §4 ``test_research_node_creates_jira_then_dispatches``).
3. Dispatch to the ``sdd-research`` subagent so it runs ``/sdd-spec``,
   ``/sdd-task``, and creates the worktree.
4. Validate the dispatch payload as :class:`ResearchOutput` (delegated
   to the dispatcher's output_model contract).

Spec §7 R5 — duplicate worktree detection: the node checks
``WORKTREE_BASE_PATH/<branch_name>`` after the subagent returns and
fails fast if the directory exists; recovery is the human's job.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from parrot import conf
from parrot.bots.flow.node import Node
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    BugBrief,
    ClaudeCodeDispatchProfile,
    LogSource,
    ResearchOutput,
)


class ResearchNode(Node):
    """Second node — Jira + log fetch + sdd-research dispatch.

    Args:
        dispatcher: A :class:`ClaudeCodeDispatcher` instance shared by
            every node in the flow.
        jira_toolkit: A pre-built ``parrot_tools.jiratoolkit.JiraToolkit``
            wired with service-account credentials.
        log_toolkits: Mapping ``"cloudwatch"|"elasticsearch"`` →
            toolkit instance. Optional kinds may be missing; an unknown
            ``LogSource.kind`` raises ``ValueError`` at dispatch time.
        name: Node id, default ``"research"``.
    """

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        jira_toolkit: Any,
        log_toolkits: Optional[Dict[str, Any]] = None,
        name: str = "research",
    ) -> None:
        super().__init__()
        self._name = name
        self._init_node(name)
        self._dispatcher = dispatcher
        self._jira = jira_toolkit
        self._log_toolkits = log_toolkits or {}
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return self._name

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self, prompt: str, ctx: Dict[str, Any]
    ) -> ResearchOutput:
        """Run the research phase. Returns a validated :class:`ResearchOutput`."""
        brief: BugBrief = ctx["bug_brief"]

        # 1. Fetch logs first — cheap, deterministic, and the excerpts
        # become part of the Jira description.
        excerpts = await self._collect_log_excerpts(brief.log_sources)

        # 2. Create the Jira ticket BEFORE dispatching. Unit tests pin
        # this ordering (spec §4 test_research_node_creates_jira_then_dispatches).
        jira_resp = await self._jira.jira_create_issue(
            summary=brief.summary,
            description=self._build_description(brief, excerpts),
            assignee=conf.FLOW_BOT_JIRA_ACCOUNT_ID or None,
            fields=self._reporter_fields(brief.reporter),
        )
        issue_key = self._extract_issue_key(jira_resp)
        ctx["jira_issue_key"] = issue_key

        # 3. Dispatch the sdd-research subagent.
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-research",
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Grep", "Glob", "Bash"],
            model="claude-sonnet-4-6",
        )
        cwd = os.path.abspath(conf.WORKTREE_BASE_PATH)
        os.makedirs(cwd, exist_ok=True)
        # Stash the excerpts on the brief so the subagent gets them.
        # We pass the brief through as-is since BugBrief already carries
        # log_sources; the prompt builder embeds excerpts separately.
        ctx["log_excerpts"] = excerpts

        research_out: ResearchOutput = await self._dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=ResearchOutput,
            run_id=ctx["run_id"],
            node_id=self.name,
            cwd=cwd,
        )

        # 4. If the subagent left jira_issue_key blank, inject ours.
        if not research_out.jira_issue_key:
            research_out = research_out.model_copy(
                update={"jira_issue_key": issue_key}
            )

        # 5. Spec §7 R5 — fail fast on duplicate worktree.
        self._check_no_existing_worktree(research_out.branch_name)

        ctx["research_output"] = research_out
        return research_out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _collect_log_excerpts(
        self, sources: List[LogSource]
    ) -> List[str]:
        excerpts: List[str] = []
        for src in sources:
            try:
                excerpts.extend(await self._fetch_logs(src))
            except Exception as exc:  # never block the flow on log fetch
                self.logger.warning(
                    "Log fetch failed for %s/%s: %s", src.kind, src.locator, exc
                )
        return excerpts

    async def _fetch_logs(self, source: LogSource) -> List[str]:
        if source.kind == "cloudwatch":
            toolkit = self._log_toolkits.get("cloudwatch")
            if toolkit is None:
                raise ValueError("CloudWatch toolkit not configured")
            result = await toolkit.aws_cloudwatch_query_logs(
                log_group=source.locator,
                start_time=f"-{source.time_window_minutes}m",
            )
            return self._tail_text(result)
        if source.kind == "elasticsearch":
            toolkit = self._log_toolkits.get("elasticsearch")
            if toolkit is None:
                raise ValueError("Elasticsearch toolkit not configured")
            result = await toolkit.search(
                index=source.locator,
                window_minutes=source.time_window_minutes,
            )
            return self._tail_text(result)
        if source.kind == "attached_file":
            with open(source.locator, "r", encoding="utf-8") as fh:
                return [fh.read()[-4000:]]
        raise ValueError(f"Unknown log source kind: {source.kind}")

    @staticmethod
    def _tail_text(result: Any) -> List[str]:
        if isinstance(result, str):
            return [result[-4000:]]
        if isinstance(result, list):
            return [str(x)[-4000:] for x in result[-10:]]
        return [str(result)[-4000:]]

    @staticmethod
    def _build_description(brief: BugBrief, excerpts: List[str]) -> str:
        criteria_lines = "\n".join(
            f"- {c.kind}: {c.name}" for c in brief.acceptance_criteria
        )
        excerpts_block = "\n---\n".join(excerpts) if excerpts else "(none)"
        return (
            f"Affected component: {brief.affected_component}\n\n"
            f"Acceptance criteria:\n{criteria_lines}\n\n"
            f"Log excerpts:\n{excerpts_block}\n\n"
            f"Reporter: {brief.reporter}\n"
            f"Escalation assignee on failure: {brief.escalation_assignee}\n"
        )

    @staticmethod
    def _reporter_fields(reporter: str) -> Optional[Dict[str, Any]]:
        if not reporter:
            return None
        # Jira REST v3 — reporter is a user object: {"accountId": "..."}
        return {"reporter": {"accountId": reporter}}

    @staticmethod
    def _extract_issue_key(resp: Any) -> str:
        if isinstance(resp, dict):
            key = resp.get("key") or resp.get("issue_key")
            if isinstance(key, str):
                return key
        return ""

    @staticmethod
    def _check_no_existing_worktree(branch_name: str) -> None:
        path = os.path.join(conf.WORKTREE_BASE_PATH, branch_name)
        if os.path.exists(path):
            # Duplicate worktree — spec §7 R5 explicitly forbids
            # auto-recovery in v1; the human cleans up.
            raise RuntimeError(
                f"Worktree {path!r} already exists. Run "
                f"`git worktree remove {path}` and retry. "
                f"Auto-recovery is out of scope (spec R5)."
            )


__all__ = ["ResearchNode"]
