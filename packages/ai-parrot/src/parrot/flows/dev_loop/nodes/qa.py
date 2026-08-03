"""QANode — sdd-qa dispatch in plan mode + pluggable code-review gate.

Implements **Module 7** (FEAT-129/132) and its FEAT-270 extension. Dispatches
the ``sdd-qa`` subagent under ``permission_mode="plan"`` with no edit/write
tools so the deterministic QA pass is strictly read-only. The subagent runs
each acceptance criterion as a subprocess (deterministic — exit code is the
source of truth, not LLM judgement; spec G6) and runs lint, then returns a
:class:`QAReport`.

The code-review gate (FEAT-250, extended by FEAT-270) is additive and
pluggable: it delegates to an :class:`AbstractCodeReviewDispatcher` (Claude,
Codex, or Gemini) which is allowed to fix issues it finds and commit the
fixes to the worktree branch. When the reviewer reports modified files, the
deterministic QA pass re-runs to confirm the fix didn't regress anything.

The node returns the report regardless of ``passed`` — the flow factory
(TASK-886) decides routing via a :class:`FlowTransition`.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from parrot import conf
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    ClaudeCodeReviewDispatcher,
)
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory
from parrot.flows.dev_loop.models import (
    AcceptanceCriterion,
    AdversarialFinding,
    BugBrief,
    ClaudeCodeDispatchProfile,
    CriterionResult,
    ManualCriterion,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    TriageBrief,
    TriageReport,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, condense_qa_failure, register_dev_loop_node
from parrot.flows.dev_loop.session_state import QaAttemptRecorded


_DEFAULT_LINT_COMMAND = "ruff check . && mypy --no-incremental"

# Prefix of the synthetic finding emitted when the code-review gate could not
# run (infra error). Used to detect a *skipped* (vs. genuinely passed) review
# so the skip is surfaced loudly instead of masquerading as a clean review.
_CODE_REVIEW_SKIP_PREFIX = "code-review could not run:"

# Matches a positional ``.`` target in lint commands (e.g. ``ruff check .``).
# Preceded by whitespace, followed by whitespace, chain operator, or EOL.
_LINT_TARGET_RE = re.compile(
    r"(?<=\s)\."
    r"(?=\s|&&|;|$)"
)


class _QABrief(BaseModel):
    """Internal brief shape passed to the ``sdd-qa`` subagent.

    Bundles the upstream ``BugBrief.acceptance_criteria`` together with
    the configurable lint command so the subagent has everything it
    needs in a single JSON payload (the dispatcher's ``_build_prompt``
    serializes the brief as the prompt body).
    """

    acceptance_criteria: List[AcceptanceCriterion] = Field(..., min_length=1)
    lint_command: str
    worktree_path: str
    summary: str = ""


class _CodeReviewBrief(BaseModel):
    """Brief passed to the code-review dispatcher (FEAT-250 / FEAT-270).

    Bundles the acceptance criteria the change must satisfy with the path to
    review and the issue summary, so the reviewer can judge the diff against
    the criteria + the project's standards in a single JSON payload.
    """

    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str
    summary: str = ""
    jira_issue_key: str = ""
    qa_criterion_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Deterministic QA gate results, one entry per executed "
            "acceptance criterion (name/kind/exit_code/passed). Already "
            "executed by the sdd-qa gate — reviewers must judge from these "
            "recorded results and NEVER re-run the criteria themselves "
            "(read-only reviewers cannot execute anything that writes)."
        ),
    )
    qa_lint_passed: Optional[bool] = Field(
        default=None,
        description="Deterministic QA gate lint outcome (None if unknown).",
    )


@register_dev_loop_node("dev_loop.qa")
class QANode(DevLoopNode):
    """Fourth node — runs deterministic acceptance verification."""

    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        lint_command: Optional[str] = None,
        codereview_dispatcher: Optional[AbstractCodeReviewDispatcher] = None,
        graph_memory: Optional[DevLoopGraphMemory] = None,
        skip_qa: bool = False,
        name: str = "qa",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_lint_command", lint_command or _DEFAULT_LINT_COMMAND)
        # Backward compat: if no reviewer dispatcher is supplied, wrap the
        # existing development dispatcher in a ClaudeCodeReviewDispatcher so
        # zero-config callers keep working unchanged (FEAT-270).
        if codereview_dispatcher is None:
            codereview_dispatcher = ClaudeCodeReviewDispatcher(dispatcher=dispatcher)
        object.__setattr__(self, "_codereview_dispatcher", codereview_dispatcher)
        # FEAT-377 TASK-1915 (G2 seam 4): opt-in finding grounding. None
        # (default) is a strict no-op.
        object.__setattr__(self, "_graph_memory", graph_memory)
        object.__setattr__(self, "_skip_qa", skip_qa)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        ctx: Union[FlowContext, Dict[str, Any]],
        deps: Optional[DependencyResults] = None,
        **kwargs: Any,
    ) -> QAReport:
        """Dispatch ``sdd-qa`` and return the :class:`QAReport`.

        Manual criteria (``kind="manual"``) are filtered out before
        dispatch — the deterministic subagent only sees executable
        criteria — and re-appended afterwards as ``passed=True`` results
        with their text in ``QAReport.notes`` for the human reviewer.

        The node returns the report whether ``passed`` is ``True`` or
        ``False``. The flow factory routes the failure path elsewhere;
        the *node* never raises on ``passed=False``.
        """
        shared = self.shared_state(ctx)
        research: ResearchOutput = shared["research_output"]
        brief: BugBrief = shared["bug_brief"]

        runtime_skip = shared.get("skip_qa", False)
        if self._skip_qa or runtime_skip:
            self.logger.info(
                "QA bypass enabled (skip_qa=True, runtime=%s) for %s — returning synthetic pass.",
                runtime_skip, research.jira_issue_key or research.feat_id,
            )
            report = QAReport(
                passed=True,
                criterion_results=[],
                lint_passed=True,
                lint_output="(skipped: skip_qa=True)",
                notes="QA bypassed (skip_qa=True).",
                code_review_passed=True,
                code_review_findings=[],
                attempt=shared.get("qa_attempt", 1),
            )
            shared["qa_report"] = report
            return report

        manual: List[ManualCriterion] = [
            c for c in brief.acceptance_criteria
            if isinstance(c, ManualCriterion)
        ]
        # FEAT-322: per-criterion opt-in HITL gating. Default ``blocking=False``
        # preserves today's behavior byte-identically via
        # ``_merge_manual_results`` below; only ``blocking=True`` criteria open
        # a gate and await resolution before this method returns.
        blocking_manual: List[ManualCriterion] = [c for c in manual if c.blocking]
        non_blocking_manual: List[ManualCriterion] = [
            c for c in manual if not c.blocking
        ]
        executable: List[AcceptanceCriterion] = [
            c for c in brief.acceptance_criteria
            if not isinstance(c, ManualCriterion)
        ]

        is_advisory = getattr(self._codereview_dispatcher, "advisory", False)

        # FEAT-250 G4 / FEAT-270, optimised pipeline:
        #
        # - Advisory reviewers (read-only): run deterministic QA and code
        #   review CONCURRENTLY — the reviewer never modifies files, so
        #   there is no race with the QA subagent reading the worktree.
        #
        # - Write-enabled reviewers: run code review FIRST so its fixes
        #   are committed before the single deterministic QA pass. This
        #   replaces the old QA → review → re-run-QA three-step with a
        #   two-step (review → QA), eliminating the redundant re-run.
        if is_advisory:
            self.logger.info(
                "Advisory reviewer — running deterministic QA and code review concurrently"
            )
            qa_coro = self._run_deterministic_qa(
                shared, research, brief, executable
            )
            cr_coro = self._run_code_review(shared, research, brief)
            report, (cr_passed, cr_findings, files_modified) = (
                await asyncio.gather(qa_coro, cr_coro)
            )
            deterministic_passed = report.passed
        else:
            cr_passed, cr_findings, files_modified = await self._run_code_review(
                shared, research, brief
            )

        cr_skipped = any(
            f.startswith(_CODE_REVIEW_SKIP_PREFIX) for f in cr_findings
        )

        # FEAT-377 TASK-1915 (G2 seam 4): ground code-review findings — an
        # infra-degrade skip marker is never a real finding, so it is never
        # sent through grounding. Findings the graph cannot ground are
        # demoted to notes (never counted as gate-failing); if grounding
        # drops EVERY finding, the review gate must not fail on
        # hallucinated findings alone.
        ungrounded_notes: List[str] = []
        if self._graph_memory is not None and cr_findings and not cr_skipped:
            grounded = await self._graph_memory.ground_findings(cr_findings)
            dropped = [f for f in cr_findings if f not in grounded]
            if dropped:
                ungrounded_notes = [f"[ungrounded] {f}" for f in dropped]
                if not grounded:
                    cr_passed = True
                cr_findings = grounded

        # FEAT-375 (Module 5): an advisory reviewer (`advisory=True`, e.g.
        # "codex-adversarial"/"parallel") never modifies files itself — its
        # findings must be routed to the primary worker for explicit triage
        # (CONFIRM/REJECT/ESCALATE) instead of being trusted at face value.
        triage_notes: List[str] = []
        if not cr_skipped and is_advisory:
            triage_findings = self._collect_triage_findings(shared)
            if triage_findings:
                triage_notes, triage_files_modified, escalation_passed = (
                    await self._run_finding_triage(shared, research, brief, triage_findings)
                )
                for path in triage_files_modified:
                    if path not in files_modified:
                        files_modified.append(path)
                # CONFIRM-and-fixed / REJECT do not fail QA by themselves —
                # only an unresolved/rejected ESCALATE gate does (spec §3
                # Module 5 QA pass/fail semantics).
                cr_passed = escalation_passed

        # Deterministic QA — deferred for write-enabled reviewers, or
        # re-run for advisory reviewers when triage committed fixes.
        if not is_advisory:
            if files_modified:
                self.logger.info(
                    "Code review modified %s — running deterministic QA on fixed code",
                    files_modified,
                )
            report = await self._run_deterministic_qa(
                shared, research, brief, executable,
                cwd_override=research.worktree_path,
            )
            deterministic_passed = report.passed
        elif files_modified:
            self.logger.info(
                "Code review modified %s — re-running deterministic QA",
                files_modified,
            )
            report = await self._run_deterministic_qa(
                shared, research, brief, executable,
                cwd_override=research.worktree_path,
            )
            deterministic_passed = report.passed

        if non_blocking_manual:
            report = self._merge_manual_results(report, non_blocking_manual)

        blocking_passed = True
        if blocking_manual:
            report, blocking_passed = await self._resolve_blocking_manual_criteria(
                shared, blocking_manual, report
            )

        update: Dict[str, Any] = {
            "passed": deterministic_passed and cr_passed and blocking_passed,
            "code_review_passed": cr_passed,
            "code_review_findings": cr_findings,
        }
        extra_notes: List[str] = []
        if cr_skipped:
            # Degrade-to-pass (FEAT-250 G4) keeps the deterministic gate as the
            # hard guarantee, but a skipped review must NOT read as green: here
            # ``code_review_passed=True`` means "not reviewed", not "reviewed
            # clean". Make that loud in the log AND in the report's notes.
            self.logger.warning(
                "Code-review gate did NOT run for %s — QA is passing on the "
                "DETERMINISTIC gate only; code_review_passed=True means "
                "'not reviewed', not 'reviewed clean'. Detail: %s",
                research.jira_issue_key or research.feat_id,
                "; ".join(cr_findings),
            )
            extra_notes.append("⚠ Code-review gate SKIPPED (infra) — change NOT reviewed.")
        # FEAT-375: REJECT/ESCALATE triage notes are always PR-visible, even
        # when the deterministic + code-review gates otherwise pass.
        extra_notes.extend(triage_notes)
        # FEAT-377 TASK-1915: ungrounded findings are demoted to notes, not
        # gate-failing (see the grounding block above).
        extra_notes.extend(ungrounded_notes)
        if extra_notes:
            existing_notes = report.notes or ""
            sep = "\n\n" if existing_notes else ""
            update["notes"] = f"{existing_notes}{sep}{chr(10).join(extra_notes)}"
        report = report.model_copy(update=update)

        # FEAT-377 TASK-1911 (Module 3 repair loop): stamp the attempt
        # number the development node owns in shared state (1 on the very
        # first pass, before development ever bumps it). Lives ON the
        # report — not merely in shared state — because the engine's
        # `cel_evaluator` coerces the node result via `model_dump()`, so
        # the qa->development retry / qa->failure_handler exhaustion CEL
        # predicates can only reference fields on `QAReport` itself.
        attempt = shared.get("qa_attempt", 1)
        report = report.model_copy(update={"attempt": attempt})
        session_host = shared.get("session_host")
        if not report.passed and session_host is not None:
            will_retry = attempt < int(conf.DEV_LOOP_QA_MAX_RETRIES)
            if will_retry:
                session_host.apply(
                    QaAttemptRecorded(
                        attempt=attempt,
                        qa_notes=condense_qa_failure(report),
                    )
                )

        self.logger.info(
            "QA report: passed=%s, deterministic=%s, code_review=%s, "
            "code_review_ran=%s, lint_passed=%s, n_executable=%s, n_manual=%s, "
            "files_modified=%s",
            report.passed,
            deterministic_passed,
            cr_passed,
            not cr_skipped,
            report.lint_passed,
            len(executable),
            len(manual),
            files_modified,
        )
        shared["qa_report"] = report
        return report

    # ------------------------------------------------------------------
    # Deterministic QA dispatch
    # ------------------------------------------------------------------

    async def _run_deterministic_qa(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
        executable: List[AcceptanceCriterion],
        *,
        cwd_override: Optional[str] = None,
    ) -> QAReport:
        """Dispatch the read-only ``sdd-qa`` gate (or synthesize a report).

        Used both for the initial deterministic pass and for the
        review-fix-rerun loop (FEAT-270) — same subagent, same profile, same
        brief shape; only the worktree contents may have changed between
        calls (the reviewer's fix commit).
        """
        if not executable:
            # All criteria are manual — skip the dispatch entirely.
            return QAReport(
                passed=True,
                criterion_results=[],
                lint_passed=True,
                lint_output="(skipped: no executable criteria)",
                notes="No executable acceptance criteria; manual review only.",
            )
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-qa",
            permission_mode="plan",
            allowed_tools=["Read", "Bash"],  # NEVER Edit/Write
            setting_sources=["project"],
        )
        effective_cwd = cwd_override or research.worktree_path

        # Scope lint/ruff/mypy commands to changed files so pre-existing
        # repo-wide errors don't fail the QA gate for unrelated code.
        changed = await self._get_changed_files(effective_cwd)
        lint_cmd = self._scope_lint_to_files(self._lint_command, changed)
        scoped_criteria = self._scope_criteria(executable, changed)

        qa_brief = _QABrief(
            acceptance_criteria=scoped_criteria,
            lint_command=lint_cmd,
            worktree_path=effective_cwd,
            summary=brief.summary,
        )
        return await self._dispatcher.dispatch(
            brief=qa_brief,
            profile=profile,
            output_model=QAReport,
            run_id=shared["run_id"],
            node_id=self.name,
            cwd=effective_cwd,
            # FEAT-322: fold dispatch-level events into the run's
            # SessionHost when one is present (see development.py's
            # dispatch() call for the same pattern/rationale).
            session_host=shared.get("session_host"),
        )

    # ------------------------------------------------------------------
    # Lint scoping helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_changed_files(worktree_path: str) -> List[str]:
        """Return Python files changed in the worktree vs its merge base.

        Tries ``origin/dev`` first (standard base branch), then falls
        back to ``origin/main``. Returns an empty list on any error so
        the caller degrades to the unscoped lint command.
        """
        for upstream in ("origin/dev", "origin/main"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "diff", "--name-only", "--diff-filter=d",
                    f"{upstream}...HEAD", "--", "*.py",
                    cwd=worktree_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and stdout:
                    return [
                        f.strip()
                        for f in stdout.decode().strip().splitlines()
                        if f.strip()
                    ]
            except Exception:
                continue
        return []

    @staticmethod
    def _scope_lint_to_files(command: str, files: List[str]) -> str:
        """Replace whole-repo targets (``.``) with explicit file paths.

        Processes each ``&&``/``;``-separated sub-command independently
        so compound commands like ``ruff check . && mypy --no-incremental``
        scope both halves. Also appends file paths to bare ``mypy``
        invocations that have no positional target.
        """
        if not files:
            return command
        file_args = " ".join(shlex.quote(f) for f in files)

        def _scope_part(part: str) -> str:
            scoped = _LINT_TARGET_RE.sub(file_args, part)
            if scoped == part and re.search(r"\bmypy\b", part):
                scoped = f"{part.rstrip()} {file_args}"
            return scoped

        parts = re.split(r"(&&|;)", command)
        return "".join(
            _scope_part(p) if i % 2 == 0 else p
            for i, p in enumerate(parts)
        )

    @classmethod
    def _scope_criteria(
        cls,
        criteria: List[AcceptanceCriterion],
        files: List[str],
    ) -> List[AcceptanceCriterion]:
        """Rewrite shell criteria that lint the whole repo to target changed files."""
        if not files:
            return criteria
        scoped: List[AcceptanceCriterion] = []
        for c in criteria:
            if (
                isinstance(c, ShellCriterion)
                and _LINT_TARGET_RE.search(c.command)
                and re.search(r"\b(ruff|mypy|flake8|pylint)\b", c.command)
            ):
                scoped.append(
                    c.model_copy(
                        update={
                            "command": cls._scope_lint_to_files(
                                c.command, files
                            )
                        }
                    )
                )
            else:
                scoped.append(c)
        return scoped

    # ------------------------------------------------------------------
    # Code-review gate (FEAT-250, pluggable dispatcher since FEAT-270)
    # ------------------------------------------------------------------

    async def _run_code_review(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
        *,
        qa_report: Optional[QAReport] = None,
    ) -> tuple[bool, List[str], List[str]]:
        """Delegate to the configured code-review dispatcher.

        Returns ``(passed, findings, files_modified)``. A dispatch error
        never raises and never blocks the flow on infra grounds — the
        dispatcher itself degrades to
        ``CodeReviewVerdict(passed=True, findings=["code-review could not
        run: …"])`` so the deterministic gate remains the hard guarantee
        (FEAT-250 G4).

        FEAT-375: also stashes the raw, structured ``CodeReviewVerdict`` on
        ``shared["_code_review_verdict"]`` (``None`` when the dispatch
        degraded) so :meth:`_collect_triage_findings` can read the
        structured findings for triage without widening this method's
        public 3-tuple contract (existing callers/tests assert on it).

        Args:
            qa_report: The deterministic gate's report, folded into the
                brief as ``qa_criterion_results`` so reviewers judge from
                the recorded exit codes instead of re-running criteria —
                a read-only reviewer (codex adversarial) that attempts to
                run pytest dies on tempdir creation and retry-spirals.
        """
        review_cwd = research.worktree_path
        qa_results: List[Dict[str, Any]] = [
            {
                "name": r.name,
                "kind": r.kind,
                "exit_code": r.exit_code,
                "passed": r.passed,
            }
            for r in (qa_report.criterion_results if qa_report else [])
        ]
        review_brief = _CodeReviewBrief(
            acceptance_criteria=list(brief.acceptance_criteria),
            worktree_path=review_cwd,
            summary=brief.summary,
            jira_issue_key=research.jira_issue_key,
            qa_criterion_results=qa_results,
            qa_lint_passed=qa_report.lint_passed if qa_report else None,
        )
        try:
            verdict = await self._codereview_dispatcher.review(
                brief=review_brief,
                run_id=shared["run_id"],
                node_id=self.name,
                cwd=review_cwd,
                # FEAT-322: fold dispatch-level events into the run's
                # SessionHost when one is present.
                session_host=shared.get("session_host"),
                # FEAT-378 (code-review finding): the QA-attempt-scoped round
                # identifier JudgePanelReviewDispatcher stamps onto each
                # JudgeVerdictRecorded action ("qa-1", "qa-2", ... — same
                # convention as QaAttemptRecorded's attempt number above).
                # Ignored by every non-panel dispatcher.
                round=f"qa-{shared.get('qa_attempt', 1)}",
            )
        except Exception as exc:  # noqa: BLE001 - degrade-on-infra-error (FEAT-250 G4)
            self.logger.warning("Code-review dispatcher raised: %s", exc)
            shared["_code_review_verdict"] = None
            return True, [f"{_CODE_REVIEW_SKIP_PREFIX} {exc}"], []
        shared["_code_review_verdict"] = verdict
        findings = [f.message for f in getattr(verdict, "findings", [])]
        files_modified = list(getattr(verdict, "files_modified", []))
        passed = getattr(verdict, "passed", True)
        return passed, findings, files_modified

    # ------------------------------------------------------------------
    # Advisory-finding triage loop (FEAT-375 Module 5)
    # ------------------------------------------------------------------

    def _collect_triage_findings(self, shared: Dict[str, Any]) -> List[AdversarialFinding]:
        """Return the structured findings from the last review verdict, triage-ready.

        Skip-prefixed findings (infra degrade) are excluded — they never
        enter triage, matching the loud-skip convention. Plain
        ``CodeReviewFinding`` items (should not normally occur for an
        advisory dispatcher, which already tags its own findings) are
        coerced into ``AdversarialFinding`` defensively.

        FEAT-375 code-review fix: assigns a stable, positional ``finding_id``
        (``"finding-<n>"``) to every collected finding here — the triage
        worker echoes it back on each disposition, so matching a returned
        disposition to its originating finding no longer depends on the
        worker preserving the exact ``file``/``message`` text (an LLM may
        paraphrase even while faithfully triaging).
        """
        verdict = shared.get("_code_review_verdict")
        if verdict is None:
            return []
        raw_findings = list(getattr(verdict, "findings", []))
        collected: List[AdversarialFinding] = []
        for idx, finding in enumerate(raw_findings):
            if finding.message.startswith(_CODE_REVIEW_SKIP_PREFIX):
                continue
            finding_id = f"finding-{idx}"
            if isinstance(finding, AdversarialFinding):
                collected.append(finding.model_copy(update={"finding_id": finding_id}))
            else:
                collected.append(AdversarialFinding(**finding.model_dump(), finding_id=finding_id))
        return collected

    async def _run_finding_triage(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
        findings: List[AdversarialFinding],
    ) -> Tuple[List[str], List[str], bool]:
        """Dispatch the primary worker to triage advisory findings.

        Every input finding MUST come back with a disposition
        (CONFIRM/REJECT/ESCALATE). Missing dispositions are retried once;
        anything still missing after the retry fails closed to ESCALATE
        (never silently dropped, never silently conceded).

        Returns:
            A ``(notes, files_modified, escalation_passed)`` tuple:
            ``notes`` are PR-visible lines for ``QAReport.notes`` (REJECT
            reasons + ESCALATE notices), ``files_modified`` collects
            CONFIRM fixes for the deterministic-QA rerun, and
            ``escalation_passed`` is ``True`` unless an ESCALATE gate
            resolved to something other than ``"approved"`` (or is still
            pending when a ``SessionHost`` degrade path applies).
        """
        worktree_path = research.worktree_path
        triage_brief = TriageBrief(
            findings=findings,
            acceptance_criteria=list(brief.acceptance_criteria),
            worktree_path=worktree_path,
            summary=brief.summary,
        )
        # Write-enabled `sdd-worker` profile (mirrors development.py's
        # single-agent profile) — CONFIRMed findings may be fixed and
        # committed by this same dispatch.
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Edit", "Write", "Bash", "Grep", "Glob"],
            setting_sources=["project"],
        )

        async def _dispatch_once() -> TriageReport:
            return await self._dispatcher.dispatch(
                brief=triage_brief,
                profile=profile,
                output_model=TriageReport,
                run_id=shared["run_id"],
                node_id=self.name,
                cwd=worktree_path,
                session_host=shared.get("session_host"),
            )

        def _index(report: TriageReport) -> Dict[str, AdversarialFinding]:
            # FEAT-375 code-review fix: match on the stable `finding_id`
            # assigned by `_collect_triage_findings`, not on exact
            # `(file, message)` text — robust against an LLM paraphrasing a
            # finding's message while still faithfully dispositioning it.
            return {f.finding_id: f for f in report.findings if f.finding_id}

        def _missing(indexed: Dict[str, AdversarialFinding]) -> List[AdversarialFinding]:
            return [
                f for f in findings
                if indexed.get(f.finding_id) is None
                or indexed[f.finding_id].disposition is None
            ]

        report = await _dispatch_once()
        indexed = _index(report)
        if _missing(indexed):
            self.logger.warning(
                "One or more advisory findings came back without a "
                "disposition after triage dispatch — retrying once."
            )
            report = await _dispatch_once()
            indexed = _index(report)

        notes: List[str] = []
        session_host = shared.get("session_host")
        ttl_seconds = conf.DEV_LOOP_GATE_TTL_REVIEW_ESCALATION
        escalated_gate_ids: List[str] = []

        files_modified_set = set(report.files_modified)
        for finding in findings:
            resolved = indexed.get(finding.finding_id)
            if resolved is None or resolved.disposition is None:
                # Fail-closed: still undispositioned after the retry.
                resolved = finding.model_copy(update={
                    "disposition": "escalate",
                    "triage_reason": (
                        "no disposition returned by the triage worker after one retry"
                    ),
                })
            elif resolved.disposition == "confirm" and not self._confirm_has_evidence(
                resolved, files_modified_set
            ):
                # FEAT-375 code-review fix: a CONFIRM MUST be backed by an
                # actual file change — otherwise "confirmed" is
                # indistinguishable from "silently dropped" (nothing else
                # would have surfaced this in QAReport.notes, and the
                # deterministic rerun never triggers). Fail closed to
                # ESCALATE rather than let an agreed-upon defect disappear.
                resolved = resolved.model_copy(update={
                    "disposition": "escalate",
                    "triage_reason": (
                        f"disposed as 'confirm' but no corresponding fix was found "
                        f"in files_modified (worker's stated reason: "
                        f"{resolved.triage_reason or '(none)'}) — escalating fail-closed"
                    ),
                })

            if resolved.disposition == "reject":
                notes.append(f"rejected: {resolved.message} — {resolved.triage_reason}")
            elif resolved.disposition == "escalate":
                notes.append(f"⚠ Escalated for human review: {resolved.message}")
                if session_host is not None:
                    gate_id, _ = session_host.open_gate(
                        kind="review_escalation",
                        node_id=self.name,
                        title=f"Adversarial review finding: {resolved.file or 'unspecified file'}",
                        instructions=resolved.message,
                        ttl_seconds=ttl_seconds,
                        on_expiry="fail",
                    )
                    escalated_gate_ids.append(gate_id)
            # CONFIRM (with verified evidence): no note of its own — its fix
            # surfaces via `report.files_modified`, which triggers the
            # existing deterministic-QA rerun.

        escalation_passed = True
        if escalated_gate_ids and session_host is not None:
            resolved_gates = await asyncio.gather(
                *(session_host.wait_gate(gate_id) for gate_id in escalated_gate_ids)
            )
            escalation_passed = all(gate.status == "approved" for gate in resolved_gates)

        return notes, list(report.files_modified), escalation_passed

    @staticmethod
    def _confirm_has_evidence(resolved: AdversarialFinding, files_modified: set) -> bool:
        """Whether a CONFIRM disposition is backed by an actual file change.

        FEAT-375 code-review fix: when the finding names a specific file,
        that file must appear in the triage dispatch's ``files_modified``.
        When the finding isn't file-specific (``file == ""``), fall back to
        requiring SOME fix happened this round — imprecise, but still far
        better than accepting a bare, unverified claim.
        """
        if resolved.file:
            return resolved.file in files_modified
        return bool(files_modified)

    @staticmethod
    def _merge_manual_results(
        report: QAReport, manual: List[ManualCriterion]
    ) -> QAReport:
        """Append synthesized ``passed=True`` results for each manual criterion.

        Manual criteria don't gate the flow; they surface in the Jira
        ticket description (via ``ResearchNode._build_description``) and
        in the QA report's ``notes`` block so the human reviewer signs
        off as part of the PR review.
        """
        synthesized = [
            CriterionResult(
                name=m.name,
                kind="manual",
                exit_code=0,
                duration_seconds=0.0,
                stdout_tail="",
                stderr_tail="",
                passed=True,
            )
            for m in manual
        ]
        merged_results = list(report.criterion_results) + synthesized
        manual_block = "\n".join(f"- {m.name}: {m.text}" for m in manual)
        existing_notes = report.notes or ""
        sep = "\n\n" if existing_notes else ""
        new_notes = (
            f"{existing_notes}{sep}Manual verification required:\n{manual_block}"
        )
        return report.model_copy(
            update={
                "criterion_results": merged_results,
                "notes": new_notes,
            }
        )

    async def _resolve_blocking_manual_criteria(
        self,
        shared: Dict[str, Any],
        blocking: List[ManualCriterion],
        report: QAReport,
    ) -> tuple[QAReport, bool]:
        """Open one HITL gate per blocking criterion and await all resolutions.

        FEAT-322 (dev-loop-approval-gates, spec §3 M5). Folds one
        ``CriterionResult`` per criterion into ``report`` before this method
        returns (CEL routes on ``result.passed``, so gate resolution MUST
        complete inside ``execute``). Multiple gates are opened first, then
        awaited concurrently — one human can review several criteria in any
        order.

        No-host fallback (legacy ``DevLoopRunner`` construction, no AHP
        host seeded): logs a WARNING and degrades to the same
        ``passed=True`` synthesis as non-blocking criteria — a legacy run
        must never deadlock waiting for a gate that can never resolve.

        Args:
            shared: The run's shared state (``shared["session_host"]``).
            blocking: The ``blocking=True`` manual criteria to gate.
            report: The report to fold the gate outcomes into.

        Returns:
            A ``(report, all_passed)`` tuple — ``all_passed`` is ``False``
            if any gate resolved ``rejected``/``expired``.
        """
        host = shared.get("session_host")
        if host is None:
            self.logger.warning(
                "QANode: %d blocking manual criteria requested but no "
                "session_host in shared state (legacy DevLoopRunner "
                "construction) — falling back to non-blocking synthesis.",
                len(blocking),
            )
            return self._merge_manual_results(report, blocking), True

        # Lazy import — avoids a runner.py <-> factories.py <-> qa.py import
        # cycle (runner.py imports factories.py, which imports this module).
        from parrot.flows.dev_loop.runner import gate_ttl_for

        ttl_seconds = gate_ttl_for("manual_criterion")
        opened: List[tuple] = []
        for criterion in blocking:
            gate_id, _ = host.open_gate(
                kind="manual_criterion",
                node_id="qa",
                title=criterion.name,
                instructions=criterion.text,
                ttl_seconds=ttl_seconds,
                on_expiry="fail",
            )
            opened.append((criterion, gate_id))

        resolved_gates = await asyncio.gather(
            *[host.wait_gate(gate_id) for _, gate_id in opened]
        )

        synthesized: List[CriterionResult] = []
        audit_lines: List[str] = []
        all_passed = True
        for (criterion, _gate_id), gate in zip(opened, resolved_gates):
            passed = gate.status == "approved"
            all_passed = all_passed and passed
            synthesized.append(CriterionResult(
                name=criterion.name,
                kind="manual",
                exit_code=0 if passed else 1,
                duration_seconds=0.0,
                stdout_tail="",
                stderr_tail="",
                passed=passed,
            ))
            audit_lines.append(
                f"{criterion.name}: {gate.status} by "
                f"{gate.resolved_by or 'system'} — {gate.comment}"
            )

        merged_results = list(report.criterion_results) + synthesized
        existing_notes = report.notes or ""
        sep = "\n\n" if existing_notes else ""
        audit_block = "\n".join(audit_lines)
        new_notes = (
            f"{existing_notes}{sep}Blocking manual criteria (HITL):\n{audit_block}"
        )
        report = report.model_copy(update={
            "criterion_results": merged_results,
            "notes": new_notes,
        })
        return report, all_passed


__all__ = ["QANode"]
