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

import asyncio
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from parrot import conf
from parrot.bots.flow.node import Node
from parrot.clients.factory import LLMFactory
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import (
    BugBrief,
    ClaudeCodeDispatchProfile,
    LogSource,
    ResearchOutput,
)


# Atlassian caps the description field at 32 767 chars; leave a 2K
# headroom for the rest of the JSON body and any unicode-byte expansion.
_MAX_DESCRIPTION_CHARS = 30_000
# Target size for the LLM-summarized excerpts block when the raw body
# would exceed _MAX_DESCRIPTION_CHARS. Keeps the digest compact enough
# that the surrounding sections (criteria, reporter, user description)
# always fit.
_SUMMARIZED_EXCERPTS_CHARS = 8_000


def _summarizer_llm_default() -> str:
    """Resolve the default LLM string for log-excerpt summarization.

    Reads ``DEV_LOOP_SUMMARY_LLM`` from navconfig (env-overridable);
    falls back to Anthropic Haiku 4.5 — small, fast, cheap, perfect
    for compressing a few KB of log into a digest.
    """
    return conf.config.get(
        "DEV_LOOP_SUMMARY_LLM",
        fallback="anthropic:claude-haiku-4-5-20251001",
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
        summarizer_llm: Optional[str] = None,
        name: str = "research",
    ) -> None:
        super().__init__()
        self._name = name
        self._init_node(name)
        self._dispatcher = dispatcher
        self._jira = jira_toolkit
        self._log_toolkits = log_toolkits or {}
        self._summarizer_llm = summarizer_llm or _summarizer_llm_default()
        self._summarizer_client: Any = None  # lazy
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

        # 2. Resolve the Jira ticket BEFORE dispatching. Unit tests pin
        # this ordering (spec §4 test_research_node_creates_jira_then_dispatches).
        # Idempotency: reuse an existing ticket when one already tracks
        # this incident (caller-supplied ``existing_issue_key`` or an
        # open ticket whose summary matches verbatim). Otherwise, fall
        # back to creating a new one. Reporter is resolved to an
        # accountId here (the toolkit auto-resolves the assignee but
        # not the raw fields={"reporter":…} blob, so we do it
        # explicitly so emails work in BugBrief.reporter).
        description = await self._build_description(brief, excerpts)
        existing_key = await self._find_existing_issue(brief)
        if existing_key:
            issue_key = existing_key
            self.logger.info(
                "Re-using existing Jira ticket %s for run_id=%s",
                issue_key, ctx.get("run_id", "?"),
            )
            await self._comment_retriggered(
                issue_key=issue_key,
                run_id=ctx.get("run_id", ""),
                description=description,
            )
        else:
            reporter_fields = await self._reporter_fields(brief.reporter)
            jira_resp = await self._jira.jira_create_issue(
                summary=brief.summary,
                issuetype="Bug",
                description=description,
                assignee=conf.FLOW_BOT_JIRA_ACCOUNT_ID or None,
                fields=reporter_fields,
            )
            issue_key = self._extract_issue_key(jira_resp)
            self.logger.info(
                "Created new Jira ticket %s for run_id=%s",
                issue_key, ctx.get("run_id", "?"),
            )
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

        # 5. Spec §7 R5 (relaxed) — reuse existing worktree if it's
        # already a registered git worktree on the expected branch;
        # fail fast only on the unsafe shapes (untracked directory or
        # mismatched branch).
        self._ensure_worktree_safe(research_out.branch_name)

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
            # Per project policy the log group is configured at toolkit
            # construction time (default_log_group); the per-source
            # locator is informational and only forwarded if a non-empty
            # override is provided.
            kwargs: Dict[str, Any] = {
                "start_time": f"-{source.time_window_minutes}m",
            }
            if source.locator and source.locator != toolkit.default_log_group:
                kwargs["log_group_name"] = source.locator
            result = await toolkit.aws_cloudwatch_query_logs(**kwargs)
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
            # Blocking I/O off the event loop — large attached log files
            # would otherwise stall every concurrent flow run.
            content = await asyncio.to_thread(
                self._read_file_tail, source.locator, 4000
            )
            return [content]
        raise ValueError(f"Unknown log source kind: {source.kind}")

    @staticmethod
    def _read_file_tail(path: str, max_bytes: int) -> str:
        """Synchronous helper run via :func:`asyncio.to_thread`."""
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()[-max_bytes:]

    @staticmethod
    def _tail_text(result: Any) -> List[str]:
        if isinstance(result, str):
            return [result[-4000:]]
        if isinstance(result, list):
            return [str(x)[-4000:] for x in result[-10:]]
        return [str(result)[-4000:]]

    async def _build_description(
        self, brief: BugBrief, excerpts: List[str]
    ) -> str:
        """Render the Jira description, summarizing logs if it overflows.

        Progressive degradation:

        1. Render the full body with raw excerpts.
        2. If the result would exceed Atlassian's 32 767-char cap, send
           the excerpts through an LLM summarizer (Haiku by default) and
           re-render with the digest in place of the raw text.
        3. As a last-resort defense, hard-truncate to
           ``_MAX_DESCRIPTION_CHARS`` with a ``... (truncated)`` marker.

        The user-supplied ``brief.description`` is never summarized — it
        is the human's own words and stays verbatim until the final
        truncation step (which only kicks in if even the digest version
        is too long, and is logged loudly).
        """
        body = self._render_body(brief, excerpts)
        if len(body) > _MAX_DESCRIPTION_CHARS:
            self.logger.info(
                "Description %d chars > %d cap; summarizing log excerpts",
                len(body), _MAX_DESCRIPTION_CHARS,
            )
            digest = await self._summarize_excerpts(excerpts)
            body = self._render_body(
                brief,
                [
                    "(Auto-summarized: the raw log excerpts exceeded "
                    "Jira's 32 767-char limit. The digest below was "
                    f"produced by {self._summarizer_llm}.)\n\n"
                    + digest
                ],
            )
        if len(body) > _MAX_DESCRIPTION_CHARS:
            self.logger.warning(
                "Description still %d chars after summarization; "
                "hard-truncating to %d.",
                len(body), _MAX_DESCRIPTION_CHARS,
            )
            body = (
                body[: _MAX_DESCRIPTION_CHARS - 32].rstrip()
                + "\n\n... (truncated)"
            )
        return body

    @staticmethod
    def _render_body(brief: BugBrief, excerpts: List[str]) -> str:
        # Format each criterion with the salient field for human review:
        # shell command for ShellCriterion, task_path for FlowtaskCriterion,
        # raw text for ManualCriterion.
        def _fmt_criterion(c: Any) -> str:
            kind = getattr(c, "kind", "?")
            name = getattr(c, "name", "?")
            detail = (
                getattr(c, "command", None)
                or getattr(c, "task_path", None)
                or getattr(c, "text", "")
            )
            return f"- [{kind}] {name}: {detail}"

        criteria_lines = "\n".join(
            _fmt_criterion(c) for c in brief.acceptance_criteria
        )
        excerpts_block = "\n---\n".join(excerpts) if excerpts else "(none)"
        details_block = (
            f"Details:\n{brief.description}\n\n" if brief.description else ""
        )
        return (
            f"Affected component: {brief.affected_component}\n\n"
            f"{details_block}"
            f"Acceptance criteria:\n{criteria_lines}\n\n"
            f"Log excerpts:\n{excerpts_block}\n\n"
            f"Reporter: {brief.reporter}\n"
            f"Escalation assignee on failure: {brief.escalation_assignee}\n"
        )

    async def _summarize_excerpts(self, excerpts: List[str]) -> str:
        """Compress raw log excerpts into a concise incident digest.

        Falls back to a deterministic tail-truncation when the LLM call
        fails or no API key is available — the flow never crashes
        because of the summarizer.
        """
        raw = "\n---\n".join(excerpts) if excerpts else ""
        if not raw:
            return "(no log excerpts available)"
        target_chars = _SUMMARIZED_EXCERPTS_CHARS
        try:
            client = self._get_summarizer_client()
            prompt = (
                "You are summarising application log excerpts so a human "
                "engineer can triage an incident from a Jira ticket.\n\n"
                "Produce a concise digest — at most "
                f"{target_chars // 6} words. Highlight: error messages, "
                "stack frames, repeated symptoms, request IDs, "
                "timestamps, and any obvious root-cause hints. Quote "
                "the most damning lines verbatim. Do NOT add prose "
                "beyond the digest itself.\n\n"
                "===LOGS START===\n"
                f"{raw}\n"
                "===LOGS END==="
            )
            response = await client.ask(prompt, max_tokens=2000)
            text = (response.response or "").strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001 - degraded fallback
            self.logger.warning(
                "Log summarization via %s failed (%s); "
                "falling back to deterministic tail",
                self._summarizer_llm, exc,
            )
        # Deterministic fallback: keep the tail of each excerpt up to
        # the target budget.
        budget = max(target_chars // max(1, len(excerpts)), 200)
        tails = [e[-budget:] for e in excerpts]
        return "\n---\n".join(tails)

    def _get_summarizer_client(self) -> Any:
        if self._summarizer_client is None:
            self._summarizer_client = LLMFactory.create(self._summarizer_llm)
        return self._summarizer_client

    async def _find_existing_issue(self, brief: BugBrief) -> Optional[str]:
        """Look up a Jira ticket that already tracks this incident.

        Two-tier lookup:

        1. Caller-provided ``brief.existing_issue_key`` — verified via
           ``jira_get_issue`` so we don't trust a stale value.
        2. JQL search by exact summary in the configured project,
           filtered to tickets that aren't ``Done``. Multiple matches
           pick the most recent (the JQL orders by ``created DESC``).

        Returns:
            The Jira issue key on hit, ``None`` otherwise.
        """
        # 1. Caller override.
        if brief.existing_issue_key:
            try:
                await self._jira.jira_get_issue(brief.existing_issue_key)
                return brief.existing_issue_key
            except Exception as exc:  # noqa: BLE001 - degrade to lookup
                self.logger.warning(
                    "existing_issue_key=%r could not be fetched (%s); "
                    "falling back to summary search",
                    brief.existing_issue_key, exc,
                )

        # 2. Summary search inside the configured project.
        project = conf.config.get("JIRA_PROJECT")
        if not project:
            return None
        # Escape JQL string delimiters in the summary.
        safe_summary = brief.summary.replace("\\", "\\\\").replace('"', '\\"')
        jql = (
            f'project = "{project}" '
            f'AND summary ~ "\\"{safe_summary}\\"" '
            f"AND statusCategory != Done "
            f"ORDER BY created DESC"
        )
        try:
            result = await self._jira.jira_search_issues(
                jql=jql,
                max_results=10,
                fields="key,summary,status",
            )
        except Exception as exc:  # noqa: BLE001 - degrade to create-new
            self.logger.warning(
                "Jira lookup failed (%s); will create a new ticket", exc,
            )
            return None

        issues = (
            result.get("issues")
            or result.get("results")
            or result.get("data")
            or []
        )
        # JQL `~` is fuzzy — verify the exact summary post-fetch so we
        # don't mistakenly merge unrelated tickets that share keywords.
        exact_matches = [
            issue for issue in issues
            if (
                (issue.get("fields") or {}).get("summary") == brief.summary
                or issue.get("summary") == brief.summary
            )
        ]
        if not exact_matches:
            return None
        if len(exact_matches) > 1:
            self.logger.warning(
                "Found %d open Jira tickets with summary=%r; reusing "
                "the most recently created one",
                len(exact_matches), brief.summary,
            )
        chosen = exact_matches[0]
        return chosen.get("key") or chosen.get("issue_key")

    async def _comment_retriggered(
        self,
        *,
        issue_key: str,
        run_id: str,
        description: str,
    ) -> None:
        """Append a re-triggered comment to a reused Jira ticket.

        Keeps the audit trail intact when the dev-loop runs against an
        already-known incident: the original ticket gets a comment with
        the new run_id and the freshly-collected log digest, so the
        human reviewer sees that the agent re-attacked the same issue.
        """
        body = (
            f"Dev-loop re-triggered for this ticket "
            f"(run_id=`{run_id or 'unknown'}`).\n\n"
            f"Refreshed context attached:\n\n{description}"
        )
        try:
            await self._jira.jira_add_comment(issue=issue_key, body=body)
        except Exception as exc:  # noqa: BLE001 - non-fatal
            self.logger.warning(
                "Could not post re-trigger comment on %s: %s",
                issue_key, exc,
            )

    async def _reporter_fields(
        self, reporter: str
    ) -> Optional[Dict[str, Any]]:
        """Build the ``fields={"reporter": {...}}`` blob for create_issue.

        Accepts either an email or an accountId. Emails are resolved via
        the toolkit's user lookup so callers can keep BugBrief.reporter
        in human-readable form (e.g. ``jane@example.com``) rather than
        the Jira-internal ``557058:abc`` accountId.
        """
        if not reporter:
            return None
        try:
            account_id = await self._jira._resolve_account_id(reporter)
        except Exception as exc:  # noqa: BLE001 - degrade to raw value
            self.logger.warning(
                "Could not resolve reporter %r to an accountId (%s); "
                "passing through verbatim",
                reporter, exc,
            )
            account_id = reporter
        return {"reporter": {"accountId": account_id}}

    @staticmethod
    def _extract_issue_key(resp: Any) -> str:
        if isinstance(resp, dict):
            key = resp.get("key") or resp.get("issue_key")
            if isinstance(key, str):
                return key
        return ""

    def _ensure_worktree_safe(self, branch_name: str) -> None:
        """Verify the resolved worktree is safe to reuse, or fail loudly.

        Idempotency relaxation of spec §7 R5: when the dev-loop
        re-runs against an already-known incident, the same FEAT-id —
        and therefore the same worktree path / branch — is expected to
        appear again. Failing fast on every such re-run defeats the
        re-trigger workflow.

        Decision matrix:

        * Path does not exist → nothing to do (subagent created it).
        * Path is a registered git worktree on the *expected* branch →
          log info and reuse silently.
        * Path is a registered git worktree on a *different* branch →
          fail fast (real conflict).
        * Path exists but is NOT a registered git worktree → fail
          fast (stale junk; refuse to assume).
        * ``git worktree list`` itself failed → fail fast (cannot
          decide safely).
        """
        path = os.path.join(conf.WORKTREE_BASE_PATH, branch_name)
        if not os.path.exists(path):
            return

        try:
            proc = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                f"Path {path!r} exists but `git worktree list` "
                f"failed: {exc}. Investigate manually before retrying."
            ) from exc

        info = self._find_worktree_entry(proc.stdout, os.path.abspath(path))
        if info is None:
            raise RuntimeError(
                f"Path {path!r} already exists but is not a registered "
                f"git worktree — likely stale. Remove it (e.g. "
                f"`rm -rf {path}`) and retry."
            )
        actual_branch = info.get("branch")
        if actual_branch and actual_branch != branch_name:
            raise RuntimeError(
                f"Worktree {path!r} is on branch {actual_branch!r}, "
                f"not on the expected {branch_name!r}. Run "
                f"`git worktree remove {path}` and retry."
            )
        self.logger.info(
            "Reusing existing worktree %s on branch %s",
            path, branch_name,
        )

    @staticmethod
    def _find_worktree_entry(
        porcelain: str, abs_path: str
    ) -> Optional[Dict[str, str]]:
        """Parse ``git worktree list --porcelain`` output for a path.

        Returns a dict with the entry's fields (notably ``branch``,
        without the ``refs/heads/`` prefix) or ``None`` if the path is
        not registered.
        """
        current: Dict[str, str] = {}
        for line in porcelain.splitlines():
            if not line:
                # Blank line separates worktree entries.
                if current.get("worktree") == abs_path:
                    return current
                current = {}
                continue
            if " " in line:
                key, _, value = line.partition(" ")
            else:
                key, value = line, ""
            if key == "branch" and value.startswith("refs/heads/"):
                value = value[len("refs/heads/"):]
            current[key] = value
        if current.get("worktree") == abs_path:
            return current
        return None


__all__ = ["ResearchNode"]
