"""AbstractCodeReviewDispatcher ABC + factory (FEAT-270).

Decouples the QA node's code-review gate from any specific development
dispatcher. Concrete review dispatchers wrap the existing Claude/Codex/Gemini
development dispatchers with a write-enabled review profile, allowing the
reviewer to fix issues it discovers and commit fixes to the worktree branch.

See ``sdd/specs/new-codereviewers.spec.md`` for the full design.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel

from parrot import conf
from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,
    CodexCodeDispatcher,
    GeminiCodeDispatcher,
)
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    ClaudeCodeReviewProfile,
    CodeReviewFinding,
    CodeReviewVerdict,
    CodexAdversarialReviewProfile,
    CodexCodeReviewProfile,
    GeminiCodeReviewProfile,
)
from parrot.flows.dev_loop.session_state import SessionHost


class AbstractCodeReviewDispatcher(ABC):
    """ABC for all code review dispatchers.

    Wraps an underlying development dispatcher (Claude/Codex/Gemini) and
    adds review-specific behavior: building the review prompt/profile,
    enforcing the ``CodeReviewVerdict`` output contract (see
    ``parrot.flows.dev_loop.models``), and allowing the reviewer to fix +
    commit issues it finds.

    Concrete subclasses only need to implement ``build_review_profile()``
    and set ``agent_name``; the ``review()`` dispatch + degrade loop is
    handled by the ABC.
    """

    agent_name: str
    advisory: bool = False
    """FEAT-375: True for reviewers that never modify files and whose
    findings must be triaged (CONFIRM/REJECT/ESCALATE) by the primary
    worker rather than trusted at face value. False (default) for the
    existing write-enabled reviewers (unchanged)."""

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> CodeReviewVerdict:
        """Run code review, optionally fix issues, return a verdict.

        Delegates to the underlying development dispatcher's ``dispatch()``
        with the review profile. On any infrastructure error, degrades to a
        passing verdict with a nit-level finding noting the failure.

        Args:
            brief: The review brief (acceptance criteria + worktree path).
            run_id: The flow run id, used for the Redis stream key.
            node_id: The flow node id, used for the Redis stream key.
            cwd: Working directory for the review session.
            session_host: FEAT-322 — the run's ``SessionHost``, if any
                (threaded through to the underlying dispatcher so
                dispatch-level events fold into session state).
        """
        try:
            return await self._dispatcher.dispatch(
                brief=brief,
                profile=self.build_review_profile(),
                output_model=CodeReviewVerdict,
                run_id=run_id,
                node_id=node_id,
                cwd=cwd,
                session_host=session_host,
            )
        except Exception as exc:  # noqa: BLE001 - degrade-on-infra-error (FEAT-250 G4)
            self.logger.warning(
                "%s code-review dispatch failed: %s", self.agent_name, exc
            )
            return CodeReviewVerdict(
                passed=True,
                findings=[
                    CodeReviewFinding(
                        message=f"code-review could not run: {exc}",
                        severity="nit",
                    )
                ],
            )

    @abstractmethod
    def build_review_profile(self) -> BaseModel:
        """Return the dispatcher-specific review profile."""


class CodeReviewDispatcherFactory:
    """Factory for creating code review dispatchers."""

    _registry: Dict[str, Type[AbstractCodeReviewDispatcher]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a code review dispatcher."""

        def decorator(klass):
            cls._registry[name] = klass
            return klass

        return decorator

    @classmethod
    def create(cls, name: str, **kwargs) -> AbstractCodeReviewDispatcher:
        """Create a code review dispatcher by name."""
        if name not in cls._registry:
            raise ValueError(
                f"Unknown code review dispatcher: {name!r}. "
                f"Available: {sorted(cls._registry)}"
            )
        return cls._registry[name](**kwargs)


@CodeReviewDispatcherFactory.register("claude-code")
class ClaudeCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    """Wraps :class:`ClaudeCodeDispatcher` with a write-enabled review profile.

    Delegates to the ``sdd-codereview`` subagent (via the shared
    ``ClaudeCodeDispatcher``) with ``permission_mode="default"`` and the full
    read/write tool set, allowing the reviewer to fix issues it finds and
    commit the fixes to the worktree branch.
    """

    agent_name = "claude-code"

    def __init__(self, *, dispatcher: ClaudeCodeDispatcher, model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or conf.DEV_LOOP_CODEREVIEW_MODEL
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> ClaudeCodeReviewProfile:
        return ClaudeCodeReviewProfile(model=self._model)


@CodeReviewDispatcherFactory.register("codex")
class CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    """Wraps :class:`CodexCodeDispatcher` with a write-enabled sandbox profile.

    Uses ``sandbox="workspace-write"`` and ``approval_policy="on-request"`` so
    the reviewer can fix issues it finds and commit the fixes to the
    worktree branch, mirroring the Claude reviewer's write-enabled behavior.
    """

    agent_name = "codex"

    def __init__(self, *, dispatcher: CodexCodeDispatcher, model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or "gpt-5.5"
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> CodexCodeReviewProfile:
        return CodexCodeReviewProfile(model=self._model)


@CodeReviewDispatcherFactory.register("gemini")
class GeminiCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    """Wraps :class:`GeminiCodeDispatcher` with sandbox disabled + auto-edit.

    Uses ``sandbox=False`` and ``approval_mode="auto_edit"`` so the reviewer
    can fix issues it finds and commit the fixes to the worktree branch,
    mirroring the Claude and Codex reviewers' write-enabled behavior.
    """

    agent_name = "gemini"

    def __init__(self, *, dispatcher: GeminiCodeDispatcher, model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or "auto"
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> GeminiCodeReviewProfile:
        return GeminiCodeReviewProfile(model=self._model)


@CodeReviewDispatcherFactory.register("codex-adversarial")
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):
    """Read-only adversarial second-opinion reviewer (FEAT-375 G1).

    Wraps :class:`CodexCodeDispatcher` with the read-only, neutral-brief
    ``CodexAdversarialReviewProfile``: unlike ``CodexCodeReviewDispatcher``,
    this reviewer NEVER modifies files. Its findings are advisory only and
    must be triaged (CONFIRM/REJECT/ESCALATE) by the primary worker
    downstream (QANode, TASK-1903) rather than trusted or auto-applied.
    """

    agent_name = "codex-adversarial"
    advisory = True

    def __init__(
        self,
        *,
        dispatcher: CodexCodeDispatcher,
        model: str | None = None,
        review_scope: str = "uncommitted",
        review_base: str = "",
        review_commit: str = "",
    ) -> None:
        self._dispatcher = dispatcher
        self._model = model or getattr(conf, "DEV_LOOP_ADVERSARIAL_MODEL", "gpt-5.5")
        self._review_scope = review_scope
        self._review_base = review_base
        self._review_commit = review_commit
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> CodexAdversarialReviewProfile:
        return CodexAdversarialReviewProfile(
            model=self._model,
            review_scope=self._review_scope,
            review_base=self._review_base,
            review_commit=self._review_commit,
        )

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> CodeReviewVerdict:
        """Run the advisory review, then enforce the no-writes contract.

        Post-dispatch hardening (spec §2/§3 Module 4): ``files_modified`` is
        forced to ``[]`` regardless of what the underlying dispatch reports
        (the adversarial reviewer must never be trusted to have modified
        anything — it runs in a read-only sandbox by profile, but this is
        belt-and-suspenders), and every finding is tagged with this
        reviewer's ``source`` so downstream triage can attribute it.
        """
        verdict = await super().review(
            brief=brief,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
        )
        tagged_findings = [
            finding
            if isinstance(finding, AdversarialFinding)
            else AdversarialFinding(**finding.model_dump(), source=self.agent_name)
            for finding in verdict.findings
        ]
        return verdict.model_copy(update={"files_modified": [], "findings": tagged_findings})


@CodeReviewDispatcherFactory.register("parallel")
class ParallelPerspectiveReviewDispatcher(AbstractCodeReviewDispatcher):
    """Composite reviewer: primary (write-enabled) + adversary, merged (FEAT-375 G7).

    Runs the primary write-enabled reviewer and the codex-adversarial
    reviewer concurrently on the same brief, then deterministically merges
    their verdicts: findings that name the same file with a
    whitespace/case-normalized-identical message are agreements (tagged
    with both sources); everything else is a disagreement (tagged with its
    single source). ``passed`` is the AND of both sides; ``files_modified``
    is always the primary's (the adversary never modifies files).

    An optional LLM-judge dispatch may append a synthesis narrative to the
    merged verdict's ``summary`` — but only when explicitly enabled via
    ``judge_enabled=True`` with a ``judge_dispatcher`` provided. A failing
    judge dispatch degrades silently (logged) to the deterministic merge.
    """

    agent_name = "parallel"
    advisory = True

    def __init__(
        self,
        *,
        primary: AbstractCodeReviewDispatcher,
        adversary: AbstractCodeReviewDispatcher,
        judge_dispatcher: Optional[Any] = None,
        judge_enabled: bool = False,
    ) -> None:
        self._primary = primary
        self._adversary = adversary
        self._judge_dispatcher = judge_dispatcher
        self._judge_enabled = judge_enabled
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> BaseModel:
        """Not applicable — :meth:`review` composes two reviewers directly."""
        raise NotImplementedError(
            "ParallelPerspectiveReviewDispatcher overrides review() directly "
            "and does not delegate to a single dispatch profile."
        )

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> CodeReviewVerdict:
        primary_result, adversary_result = await asyncio.gather(
            self._primary.review(
                brief=brief, run_id=run_id, node_id=node_id, cwd=cwd, session_host=session_host
            ),
            self._adversary.review(
                brief=brief, run_id=run_id, node_id=node_id, cwd=cwd, session_host=session_host
            ),
            return_exceptions=True,
        )
        # NOTE: sides may be duck-typed reviewers (e.g. in tests) without an
        # `agent_name` attribute — use fixed labels, decoupled from the
        # concrete dispatcher identity, matching `_merge_verdicts`' tags.
        primary_verdict = self._resolve_side(primary_result, "primary")
        adversary_verdict = self._resolve_side(adversary_result, "codex-adversarial")

        merged = self._merge_verdicts(primary_verdict, adversary_verdict)

        if self._judge_enabled and self._judge_dispatcher is not None:
            try:
                judge_summary = await self._run_judge(
                    primary=primary_verdict,
                    adversary=adversary_verdict,
                    brief=brief,
                    run_id=run_id,
                    node_id=node_id,
                    cwd=cwd,
                    session_host=session_host,
                )
            except Exception as exc:  # noqa: BLE001 - judge is best-effort, never blocking
                self.logger.warning(
                    "parallel judge dispatch failed, degrading to deterministic merge: %s", exc
                )
                judge_summary = ""
            if judge_summary:
                combined_summary = f"{merged.summary}\n\n{judge_summary}".strip()
                merged = merged.model_copy(update={"summary": combined_summary})

        return merged

    def _resolve_side(self, result: Any, source: str) -> CodeReviewVerdict:
        """Turn a `gather(..., return_exceptions=True)` result into a verdict.

        Mirrors the ABC's degrade-on-infra-error contract (FEAT-250 G4) for
        the case where a side's own ``review()`` raised instead of
        internally degrading (e.g. a duck-typed reviewer with no built-in
        degrade wrapper).
        """
        if isinstance(result, BaseException):
            self.logger.warning("%s review failed during parallel dispatch: %s", source, result)
            return CodeReviewVerdict(
                passed=True,
                findings=[
                    CodeReviewFinding(
                        message=f"code-review could not run: {result}",
                        severity="nit",
                    )
                ],
            )
        return result

    @staticmethod
    def _normalize_message(message: str) -> str:
        """Casefold + collapse whitespace for agreement-key comparison."""
        return " ".join(message.casefold().split())

    def _merge_verdicts(
        self, primary: CodeReviewVerdict, adversary: CodeReviewVerdict
    ) -> CodeReviewVerdict:
        """Deterministically merge two verdicts (spec §2 `PerspectiveSynthesis`).

        Agreement key: ``(file, normalized message)``. Agreements are
        tagged with both sources (comma-joined); disagreements keep their
        single source. Never mutates the input verdicts.
        """
        merged_by_key: Dict[Tuple[str, str], AdversarialFinding] = {}

        def _key(finding: CodeReviewFinding) -> Tuple[str, str]:
            return (finding.file, self._normalize_message(finding.message))

        for finding in primary.findings:
            merged_by_key[_key(finding)] = AdversarialFinding(
                message=finding.message,
                severity=finding.severity,
                file=finding.file,
                line=finding.line,
                source="primary",
            )

        for finding in adversary.findings:
            key = _key(finding)
            if key in merged_by_key:
                existing = merged_by_key[key]
                merged_by_key[key] = existing.model_copy(
                    update={"source": f"{existing.source},codex-adversarial"}
                )
            else:
                merged_by_key[key] = AdversarialFinding(
                    message=finding.message,
                    severity=finding.severity,
                    file=finding.file,
                    line=finding.line,
                    source="codex-adversarial",
                )

        return CodeReviewVerdict(
            passed=primary.passed and adversary.passed,
            findings=list(merged_by_key.values()),
            summary=primary.summary or adversary.summary,
            files_modified=list(primary.files_modified),
        )

    async def _run_judge(
        self,
        *,
        primary: CodeReviewVerdict,
        adversary: CodeReviewVerdict,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost],
    ) -> str:
        """Best-effort optional LLM-judge dispatch (spec §2 G7, gated by conf).

        The judge dispatcher's concrete type is intentionally left generic
        (``Any``, per spec §2's ``judge_dispatcher: Optional[Any]``) — this
        method calls its ``dispatch(...)`` coroutine with both verdicts and
        the original brief, and accepts either a plain string or an object
        exposing ``judge_summary`` (e.g. a ``PerspectiveSynthesis``-shaped
        result) as the narrative to append.
        """
        result = await self._judge_dispatcher.dispatch(
            brief=brief,
            primary_verdict=primary,
            adversary_verdict=adversary,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
        )
        if isinstance(result, str):
            return result
        return getattr(result, "judge_summary", "") or ""


__all__ = [
    "AbstractCodeReviewDispatcher",
    "CodeReviewDispatcherFactory",
    "ClaudeCodeReviewDispatcher",
    "CodexAdversarialReviewDispatcher",
    "CodexCodeReviewDispatcher",
    "GeminiCodeReviewDispatcher",
    "ParallelPerspectiveReviewDispatcher",
]
