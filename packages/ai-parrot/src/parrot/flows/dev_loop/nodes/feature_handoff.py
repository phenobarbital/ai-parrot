"""FeatureHandoffNode — draft PR, docs artifact, wiki page, graph write-back.

Implements **Module 6** of the FEAT-378 spec: the automated "sdd-done that
documents" for feature-mode. After push + PR (mirroring
:class:`DeploymentHandoffNode`'s pattern — this is deliberately the SECOND
and ONLY other PR-creating node in the dev-loop; the "never merge"
invariant from ``revision_handoff.py`` applies here too), it:

1. Generates and commits ``docs/features/feat-<id>-<slug>.md`` to the PR
   branch (directory configurable via ``DEV_LOOP_DOCS_ARTIFACT_DIR``).
2. Ingests that page into the LLM wiki via ``LLMWikiToolkit.create_page``
   when ``DEV_LOOP_WIKI_PAGE_INGEST`` is on — degrades with a warning if
   unavailable. No code ``wikitoolkit upsert`` here (deferred to the
   post-merge hook — spec's resolved decision).
3. Publishes the run outcome to the knowledge graph via
   ``DevLoopGraphMemory.publish_run_outcome()`` — a strict no-op when no
   facade was injected (the default).
4. Transitions Jira + comments ONLY when a ticket key is present
   (feature-mode Jira is optional and link-only — this node never
   creates a ticket).

**Never merges** — no ``git merge`` / ``gh pr merge`` anywhere in this
module, mirroring ``revision_handoff.py``'s explicit invariant.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatchers.nova import summarize_pr_changes
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    FeedbackDecision,
    PlannerOutput,
    QAReport,
    SynthesisReport,
)
from parrot.flows.dev_loop.nodes.base import (
    BaseBranchMismatch,
    DevLoopNode,
    assert_base_is_clean,
    register_dev_loop_node,
    scrub_git_output,
    transition_issue_with_candidates,
)
from parrot.flows.dev_loop.session_state import DocsArtifactLinked, SessionHost

_BRANCH_RE = re.compile(r"^feat-(\d+)-(.+)$")


def _slugify(text: str) -> str:
    """Lowercase, hyphen-separated fallback slug (no external deps)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "feature"


def _parse_flow_frontmatter(spec_path: Path) -> Optional[str]:
    """Read the ``base_branch`` declared in a spec's YAML frontmatter.

    FEAT-466 TASK-2505: local duplicate of
    ``nodes.research._parse_flow_frontmatter`` (not a shared import —
    ``research.py`` is not in this task's file list, and ``scripts.sdd`` is
    not importable from this package's context; see TASK-2504's Completion
    Note). Feature-mode always resolves ``type: feature`` (``FeatureBrief.
    kind`` is a fixed literal), so unlike ``ResearchNode`` there is no
    ``kind``-derived hotfix path here — the only question is which base a
    pre-existing spec (``document_kind == "spec"``) already declares (e.g.
    ``staging`` during a release freeze). Returns ``None`` — never raises —
    when the file is missing, has no frontmatter, or is malformed; the
    caller falls back to ``"dev"``.
    """
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        block = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(block, dict):
        return None
    base = block.get("base_branch")
    return base if isinstance(base, str) and base else None


@register_dev_loop_node("dev_loop.feature_handoff")
class FeatureHandoffNode(DevLoopNode):
    """Sixth (feature-mode terminal) node — draft PR + docs + wiki + graph.

    Args:
        jira_toolkit: Optional ``JiraToolkit`` instance. Feature-mode Jira
            is link-only — when ``None`` (or when the run has no ticket
            key), zero Jira calls are made.
        git_toolkit: Optional Git toolkit (parity with
            ``DeploymentHandoffNode`` — unused by the bare HTTP PR
            fallback, kept for interface symmetry / future use).
        wiki_toolkit: Optional pre-wired ``LLMWikiToolkit`` instance. Wiki
            ingest is skipped with a warning when ``None``, even if
            ``DEV_LOOP_WIKI_PAGE_INGEST`` is on.
        wiki_name: Wiki name passed to ``LLMWikiToolkit.create_page``.
        gh_cli_path: Override path to the ``gh`` CLI binary.
        target_repo: ``"<owner>/<repo>"`` for the GitHub REST fallback.
            Reads ``GITHUB_REPOSITORY`` env var when not provided.
        base_branch: Base branch for the draft PR (default ``"dev"``).
        docs_artifact_dir: Directory (relative to the worktree root) for
            the generated docs artifact. Defaults to
            ``conf.DEV_LOOP_DOCS_ARTIFACT_DIR``.
        wiki_page_ingest: Overrides ``conf.DEV_LOOP_WIKI_PAGE_INGEST`` when
            not ``None``.
        graph_memory: Optional :class:`DevLoopGraphMemory` used to record
            this run's outcome in the graph plane. ``None`` (the default)
            disables the seam entirely.
        name: Node id, default ``"feature_handoff"``.
    """

    def __init__(
        self,
        *,
        jira_toolkit: Optional[Any] = None,
        git_toolkit: Any = None,
        wiki_toolkit: Optional[Any] = None,
        wiki_name: str = "ai-parrot",
        gh_cli_path: Optional[str] = None,
        target_repo: Optional[str] = None,
        base_branch: str = "dev",
        docs_artifact_dir: Optional[str] = None,
        wiki_page_ingest: Optional[bool] = None,
        graph_memory: Optional[DevLoopGraphMemory] = None,
        name: str = "feature_handoff",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_jira", jira_toolkit)
        object.__setattr__(self, "_git", git_toolkit)
        object.__setattr__(self, "_wiki", wiki_toolkit)
        object.__setattr__(self, "_wiki_name", wiki_name)
        object.__setattr__(self, "_gh_cli_path", gh_cli_path)
        object.__setattr__(self, "_target_repo", target_repo or os.environ.get("GITHUB_REPOSITORY", ""))
        object.__setattr__(self, "_base_branch", base_branch)
        object.__setattr__(
            self,
            "_docs_artifact_dir",
            docs_artifact_dir or conf.DEV_LOOP_DOCS_ARTIFACT_DIR,
        )
        object.__setattr__(
            self,
            "_wiki_page_ingest",
            conf.DEV_LOOP_WIKI_PAGE_INGEST if wiki_page_ingest is None else wiki_page_ingest,
        )
        # FEAT-377 TASK-1915 (G2 seam 3): opt-in graph write-back, built
        # once by the caller via ``DevLoopGraphMemory.from_config()``.
        # None (default) is a strict no-op — same contract as
        # DevLoopCloseNode/FailureHandlerNode.
        object.__setattr__(self, "_graph_memory", graph_memory)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Push, open a draft PR, generate docs, ingest wiki, write graph.

        Reads ``planner_output`` (required), and optionally
        ``development_output`` / ``synthesis_report`` / ``qa_report`` /
        ``feedback_decision`` from shared state.

        Returns:
            ``{"status": "ready_to_deploy", "pr_url", "pr_number",
            "docs_path", "wiki_page_id"}`` on success, or
            ``{"status": "blocked", "error": "..."}`` after the PR
            creation retry budget is exhausted (mirrors
            ``DeploymentHandoffNode`` — never raises).
        """
        shared = self.shared_state(ctx)
        planner: PlannerOutput = shared["planner_output"]
        development: Optional[DevelopmentOutput] = shared.get("development_output")
        synthesis: Optional[SynthesisReport] = shared.get("synthesis_report")
        qa_report: Optional[QAReport] = shared.get("qa_report")
        feedback: Optional[FeedbackDecision] = shared.get("feedback_decision")
        issue_key = planner.jira_issue_key or ""

        accept_notes = ""
        if feedback is not None and feedback.decision == "accept_with_notes":
            accept_notes = feedback.notes

        # FEAT-466: source the base from the committed spec's frontmatter —
        # the same "resolve once, record it, read the record" principle as
        # DeploymentHandoffNode, never the hardcoded "dev" constructor
        # default (never overridden by factories.py:244 today).
        #
        # NOTE (code-review follow-up, mirrors DeploymentHandoffNode's
        # equivalent note): _resolve_base_branch below always falls back to
        # "dev" when the spec is unreadable, so this never actually
        # produces "" in normal operation today — the block below is
        # defensive-only (exercised directly by
        # test_base_branch_guard.py::TestFeatureHandoffWiring via a
        # hand-constructed empty base), kept for symmetry with
        # DeploymentHandoffNode and as the correct behavior should a future
        # resolver genuinely leave the base unresolved.
        base = self._resolve_base_branch(planner)
        if not base:
            error = (
                "Could not resolve a base branch for this feature run — " "refusing to guess a PR target (FEAT-466)."
            )
            self.logger.error(error)
            await self._mark_blocked(issue_key, error)
            return {"status": "blocked", "error": error}
        object.__setattr__(self, "_base_branch", base)

        # 1. Push.
        try:
            await self._run_git(planner.worktree_path, "push", "-u", "origin", planner.branch_name)
        except RuntimeError as exc:
            self.logger.error("git push failed: %s", exc)
            await self._mark_blocked(issue_key, str(exc))
            return {"status": "blocked", "error": f"push: {exc}"}

        # FEAT-466: sibling-overlap guard — the backstop. Same shared
        # implementation DeploymentHandoffNode calls.
        try:
            await assert_base_is_clean(
                planner.branch_name,
                self._base_branch,
                planner.worktree_path,
                logger=self.logger,
            )
        except BaseBranchMismatch as exc:
            self.logger.error("base-branch guard blocked the PR: %s", exc)
            await self._mark_blocked(issue_key, str(exc))
            return {"status": "blocked", "error": str(exc)}

        # 2. Open draft PR with retry-once (mirrors DeploymentHandoffNode).
        title = self._build_title(planner)
        body = await self._build_body_async(planner, development, synthesis, qa_report, accept_notes)
        pr_url: Optional[str] = None
        last_error: Optional[str] = None
        for attempt in range(2):
            try:
                pr_url = await self._create_pr(planner.branch_name, title, body)
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
                    self.logger.error("PR create failed after retry: %s", exc)

        if pr_url is None:
            await self._mark_blocked(issue_key, last_error or "unknown PR error")
            return {"status": "blocked", "error": last_error or "unknown PR error"}

        pr_number = self._parse_pr_number(pr_url)

        # 3. Docs artifact — generate, commit, push to the PR branch.
        docs_path = self._docs_rel_path(planner)
        docs_content = self._build_docs_content(
            planner,
            development,
            synthesis,
            qa_report,
            accept_notes,
            pr_url,
        )
        try:
            await self._write_and_push_docs(planner.worktree_path, docs_path, docs_content)
        except RuntimeError as exc:
            # Docs commit/push is best-effort — the PR itself already
            # exists; log loudly but do not block the handoff on it.
            self.logger.warning("Docs artifact commit/push failed (continuing): %s", exc)

        # 4. Wiki page ingest (optional, degrades independently).
        wiki_page_id = await self._ingest_wiki_page(planner, docs_content)

        # 5. Graph write-back (no-op when no facade was injected).
        await self._publish_graph_outcome(
            run_id=shared.get("run_id", ""),
            qa_report=qa_report,
            summary=f"{planner.feat_id} handed off: {pr_url}",
        )

        # Record DocsArtifactLinked (TASK-1919).
        session_host: Optional[SessionHost] = shared.get("session_host")
        if session_host is not None:
            session_host.apply(
                DocsArtifactLinked(
                    docs_path=docs_path,
                    wiki_page_id=wiki_page_id,
                    pr_url=pr_url,
                )
            )

        # 6. Jira transition + comment — ONLY when a ticket key exists.
        if issue_key and self._jira is not None:
            try:
                await transition_issue_with_candidates(
                    self._jira,
                    issue_key,
                    conf.DEV_LOOP_JIRA_TRANSITIONS_READY,
                    logger=self.logger,
                )
            except Exception as exc:  # noqa: BLE001 - degraded path
                self.logger.warning("Jira transition failed (continuing): %s", exc)
            try:
                await self._jira.jira_add_comment(
                    issue=issue_key,
                    body=f"flow-bot: PR opened — {pr_url}\nDocs: {docs_path}",
                )
            except Exception as exc:  # noqa: BLE001 - degraded path
                self.logger.warning("Jira add_comment failed: %s", exc)

        return {
            "status": "ready_to_deploy",
            "pr_url": pr_url,
            "pr_number": pr_number,
            "docs_path": docs_path,
            "wiki_page_id": wiki_page_id,
        }

    # ------------------------------------------------------------------
    # Internal — base-branch resolution (FEAT-466 TASK-2505)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_base_branch(planner: PlannerOutput) -> str:
        """Resolve this feature run's base branch from the committed spec.

        The spec on disk is authoritative — same principle as
        ``ResearchNode._resolve_base_branch`` (TASK-2504). Feature-mode
        always resolves ``type: feature`` (no ``kind``-derived hotfix path
        exists here), so an unreadable/absent spec falls back to ``"dev"``
        rather than a kind mapping — this never returns ``""``.

        Args:
            planner: The upstream planner output (for ``spec_path`` and
                ``worktree_path``).

        Returns:
            The resolved base branch name; never ``""``.
        """
        spec_path = Path(planner.spec_path)
        if not spec_path.is_absolute():
            spec_path = Path(planner.worktree_path) / spec_path
        return _parse_flow_frontmatter(spec_path) or "dev"

    # ------------------------------------------------------------------
    # Internal — git plumbing (mirrors DeploymentHandoffNode's subprocess pattern)
    # ------------------------------------------------------------------

    async def _run_git(self, cwd: str, *args: str) -> str:
        """Run one git subcommand in ``cwd``; raise ``RuntimeError`` on failure.

        Never calls ``git merge`` / ``gh pr merge`` — the only git verbs
        this node ever issues are ``push``, ``add``, and ``commit``.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            cwd,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: " f"{scrub_git_output(err.decode(errors='replace'))}")
        return out.decode(errors="replace")

    # ------------------------------------------------------------------
    # Internal — PR creation (mirrors DeploymentHandoffNode verbatim)
    # ------------------------------------------------------------------

    def _gh_available(self) -> bool:
        import shutil

        return shutil.which(self._gh_cli_path or "gh") is not None

    @staticmethod
    def _parse_pr_number(pr_url: str) -> Optional[int]:
        tail = pr_url.rstrip("/").rsplit("/", 1)[-1] if pr_url else ""
        return int(tail) if tail.isdigit() else None

    async def _create_pr(self, branch: str, title: str, body: str) -> str:
        """Open a DRAFT PR; return the PR URL. NEVER merges."""
        if self._gh_available():
            return await self._create_pr_with_gh(branch, title, body)
        return await self._create_pr_via_rest(branch, title, body)

    async def _create_pr_with_gh(self, branch: str, title: str, body: str) -> str:
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
            raise RuntimeError(f"gh pr create failed: " f"{scrub_git_output(err.decode(errors='replace'))}")
        text = out.decode().strip()
        return text.splitlines()[-1] if text else ""

    async def _create_pr_via_rest(self, branch: str, title: str, body: str) -> str:
        import aiohttp  # noqa: WPS433 - intentional lazy import

        token = os.environ.get("GITHUB_TOKEN", "")
        if not self._target_repo or not token:
            raise RuntimeError("GitHub REST fallback requires target_repo + GITHUB_TOKEN")
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
            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                if resp.status >= 300:
                    raise RuntimeError(f"GitHub REST {resp.status}: {scrub_git_output(str(data))}")
                return data.get("html_url", "")

    # ------------------------------------------------------------------
    # Internal — Jira blocked path (no-op without a ticket key)
    # ------------------------------------------------------------------

    async def _mark_blocked(self, issue_key: str, error: str) -> None:
        if not issue_key or self._jira is None:
            return
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
                body=f"flow-bot: handoff blocked — {error}",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Blocked comment failed: %s", exc)

    # ------------------------------------------------------------------
    # Internal — docs artifact
    # ------------------------------------------------------------------

    def _docs_rel_path(self, planner: PlannerOutput) -> str:
        """``<DEV_LOOP_DOCS_ARTIFACT_DIR>/feat-<id>-<slug>.md``, worktree-relative."""
        match = _BRANCH_RE.match(planner.branch_name)
        if match:
            filename = f"feat-{match.group(1)}-{match.group(2)}.md"
        else:
            feat_num = re.sub(r"\D", "", planner.feat_id) or "0"
            filename = f"feat-{feat_num}-{_slugify(planner.branch_name)}.md"
        return f"{self._docs_artifact_dir}/{filename}"

    @staticmethod
    def _build_docs_content(
        planner: PlannerOutput,
        development: Optional[DevelopmentOutput],
        synthesis: Optional[SynthesisReport],
        qa_report: Optional[QAReport],
        accept_notes: str,
        pr_url: str,
    ) -> str:
        files_block = (
            "\n".join(f"- `{f}`" for f in development.files_changed)
            if development and development.files_changed
            else "(none recorded)"
        )
        decisions_block = (
            "\n".join(f"- {a}" for a in synthesis.adjustments)
            if synthesis and synthesis.adjustments
            else "(no reconciliation adjustments)"
        )
        findings_block = (
            "\n".join(f"- {f}" for f in qa_report.code_review_findings)
            if qa_report and qa_report.code_review_findings
            else "(none)"
        )
        notes_block = accept_notes or "(none)"
        test_block = (
            "\n".join(f"- {r.name}: {'PASS' if r.passed else 'FAIL'}" for r in qa_report.criterion_results)
            if qa_report and qa_report.criterion_results
            else "(no acceptance-criteria evidence recorded)"
        )
        return (
            f"# {planner.feat_id}\n\n"
            f"**Branch**: `{planner.branch_name}`\n"
            f"**PR**: {pr_url}\n"
            f"**Spec**: `{planner.spec_path}`\n\n"
            f"## What was implemented\n\n{files_block}\n\n"
            f"## Key decisions\n\n{decisions_block}\n\n"
            f"## Accepted findings\n\n{findings_block}\n\n"
            f"## Accept-with-notes\n\n{notes_block}\n\n"
            f"## How to test\n\n{test_block}\n\n"
            f"---\n_Generated by flow-bot via the dev-loop (feature-mode)._\n"
        )

    async def _write_and_push_docs(self, worktree_path: str, docs_rel_path: str, content: str) -> None:
        """Write, commit, and push the docs artifact to the feature branch.

        Args:
            worktree_path: Absolute path to the feature worktree.
            docs_rel_path: Worktree-relative path, e.g.
                ``"docs/features/feat-999-x.md"``.
            content: Rendered Markdown content.

        Raises:
            RuntimeError: On any ``git`` step failure.
        """
        abs_path = os.path.join(worktree_path, docs_rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        # Synchronous file write of a small Markdown doc — negligible cost,
        # kept simple rather than threading through asyncio.to_thread for a
        # write this small (matches the write-size class of other dev-loop
        # helpers that write small local files inline).
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        await self._run_git(worktree_path, "add", docs_rel_path)
        await self._run_git(worktree_path, "commit", "-m", f"docs: add feature handoff artifact ({docs_rel_path})")
        await self._run_git(worktree_path, "push", "origin", "HEAD")

    # ------------------------------------------------------------------
    # Internal — wiki ingest (optional, degrades independently)
    # ------------------------------------------------------------------

    async def _ingest_wiki_page(self, planner: PlannerOutput, content: str) -> Optional[str]:
        """Ingest the docs artifact as a wiki page, when enabled and available.

        Returns:
            The created page id, or ``None`` when ingest is disabled,
            unconfigured, or fails (all degrade with a warning — this
            never blocks the handoff).
        """
        if not self._wiki_page_ingest:
            return None
        if self._wiki is None:
            self.logger.warning(
                "DEV_LOOP_WIKI_PAGE_INGEST is on but no wiki_toolkit is "
                "configured; skipping wiki page ingest for %s.",
                planner.feat_id,
            )
            return None
        try:
            result = await self._wiki.create_page(
                self._wiki_name,
                title=f"{planner.feat_id}: feature handoff",
                content=content,
                category="concept",
            )
            return result.get("page_id") if isinstance(result, dict) else None
        except Exception as exc:  # noqa: BLE001 - wiki ingest is best-effort
            self.logger.warning(
                "Wiki page ingest failed for %s (degrading): %s",
                planner.feat_id,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Internal — graph write-back (FEAT-377/B, optional)
    # ------------------------------------------------------------------

    async def _publish_graph_outcome(
        self,
        *,
        run_id: str,
        qa_report: Optional[QAReport],
        summary: str,
    ) -> None:
        """Best-effort ``DevLoopGraphMemory.publish_run_outcome()`` (FEAT-377 G2).

        Mirrors ``DevLoopCloseNode``'s seam: the facade is injected (built
        once by the caller via ``DevLoopGraphMemory.from_config()``), never
        constructed here, and ``publish_run_outcome`` already degrades to a
        logged warning on any failure — it never raises into this terminal
        node.

        Args:
            run_id: This run's id, from shared state.
            qa_report: The run's :class:`QAReport`, when QA produced one.
            summary: Human-readable outcome summary stored on the RUN node.
        """
        if self._graph_memory is None:
            return
        await self._graph_memory.publish_run_outcome(
            run_id,
            qa_report,
            "succeeded",
            summary,
        )

    # ------------------------------------------------------------------
    # Internal — PR copy
    # ------------------------------------------------------------------

    async def _build_body_async(
        self,
        planner: PlannerOutput,
        development: Optional[DevelopmentOutput],
        synthesis: Optional[SynthesisReport],
        qa_report: Optional[QAReport],
        accept_notes: str,
    ) -> str:
        """``_build_body()`` plus an optional Haiku "Summary of changes"
        section (FEAT-405 Module 8, [R2] "enrich, never replace").

        The deterministic template is always computed first and is the
        exact fallback: any enrichment failure, timeout, or empty
        response returns it byte-identical to the pre-FEAT-405 output.
        Belt-and-suspenders: ``summarize_pr_changes`` itself never raises,
        but this call site also swallows — PR creation must never break
        because of the mechanical seat.
        """
        body = self._build_body(planner, development, synthesis, qa_report, accept_notes)
        try:
            summary = await summarize_pr_changes(body, logger=self.logger)
        except Exception:  # noqa: BLE001 - enrichment must never break handoff
            self.logger.warning("PR summary enrichment failed; using template only.", exc_info=True)
            summary = ""
        if not summary:
            return body
        return f"{body}\n\n## Summary of changes\n\n{summary}\n"

    @staticmethod
    def _build_title(planner: PlannerOutput) -> str:
        return f"{planner.feat_id}: {planner.branch_name}"

    @staticmethod
    def _build_body(
        planner: PlannerOutput,
        development: Optional[DevelopmentOutput],
        synthesis: Optional[SynthesisReport],
        qa_report: Optional[QAReport],
        accept_notes: str,
    ) -> str:
        files = ", ".join(development.files_changed[:10]) if development else "(none)"
        criteria = (
            "\n".join(
                f"- {r.name}: {'PASS' if r.passed else 'FAIL'}"
                for r in (qa_report.criterion_results if qa_report else [])
            )
            or "(none)"
        )
        notes_section = f"\n\n## Notes\n\n{accept_notes}" if accept_notes else ""
        reconciliation = f"\n\n## Synthesis\n\n{synthesis.summary}" if synthesis else ""
        return (
            f"## Summary\n\n"
            f"Spec: `{planner.spec_path}`\n"
            f"Jira: `{planner.jira_issue_key or '(none)'}`\n\n"
            f"## Files changed\n\n{files}\n\n"
            f"## QA evidence\n\n{criteria}"
            f"{reconciliation}"
            f"{notes_section}\n\n"
            f"---\n_Created by flow-bot via the dev-loop (feature-mode). "
            f"Never auto-merged — human review required._"
        )


__all__ = ["FeatureHandoffNode"]
