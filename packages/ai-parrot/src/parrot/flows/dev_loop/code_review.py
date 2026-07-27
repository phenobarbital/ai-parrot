"""AbstractCodeReviewDispatcher ABC + factory (FEAT-270).

Decouples the QA node's code-review gate from any specific development
dispatcher. Concrete review dispatchers wrap the existing Claude/Codex/Gemini
development dispatchers with a write-enabled review profile, allowing the
reviewer to fix issues it discovers and commit fixes to the worktree branch.

See ``sdd/specs/new-codereviewers.spec.md`` for the full design.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError

from parrot import conf
from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,
    CodexCodeDispatcher,
    GeminiCodeDispatcher,
)
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    ClaudeCodeDispatchProfile,
    ClaudeCodeReviewProfile,
    CodeReviewFinding,
    CodeReviewVerdict,
    CodexAdversarialReviewProfile,
    CodexCodeReviewProfile,
    GeminiCodeReviewProfile,
    JudgePanelConfig,
    JudgeSpec,
    default_judge_panel,
)
from parrot.flows.dev_loop.session_state import JudgeVerdictRecorded, SessionHost

# Signature: ``(key, fallback) -> Any`` (mirrors ``agent_builder.ConfigGetter``)
# — kept local rather than imported to avoid a module-level dependency on
# ``agent_builder`` (see the lazy import inside
# ``JudgePanelReviewDispatcher._build_judge`` for why: this module is on the
# transitive import path of the package's own ``__init__.py``).
ConfigGetter = Callable[..., Any]


def _default_config_getter(key: str, fallback: Any = None) -> Any:
    """Default ``config_getter``: ``conf.config.get`` with fallback as kwarg.

    ``conf.config.get``'s own signature is
    ``get(key, section=None, fallback=None)`` — a positional 2nd argument
    binds to ``section``, not ``fallback``. Every ``ConfigGetter`` call
    site in this package (here and in ``agent_builder.py``) calls
    ``config_getter(key, fallback)`` positionally, so the default must
    thread ``fallback`` through by keyword to match.
    """
    return conf.config.get(key, fallback=fallback)


class _JudgeSynthesisBrief(BaseModel):
    """Brief for the optional LLM-judge synthesis pass (FEAT-375 G7).

    Carries the already-computed deterministic merge (agreements/
    disagreements) — the judge's only job is a short narrative over that
    merge, not re-deriving it.
    """

    agreements: list[AdversarialFinding]
    disagreements: list[AdversarialFinding]
    primary_passed: bool
    adversary_passed: bool


class _JudgeSynthesisOutput(BaseModel):
    """Structured output of the optional LLM-judge synthesis pass (FEAT-375 G7)."""

    judge_summary: str = ""


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
        round: str = "",
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
            round: FEAT-378 — the QA round identifier (e.g. ``"qa-1"``),
                threaded through so :class:`JudgePanelReviewDispatcher` can
                stamp ``JudgeVerdictRecorded.round``. Unused by this base
                implementation and every non-panel dispatcher.
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
        self._model = model or conf.DEV_LOOP_ADVERSARIAL_MODEL
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
        round: str = "",
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
            round=round,
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
        round: str = "",
    ) -> CodeReviewVerdict:
        primary_result, adversary_result = await asyncio.gather(
            self._primary.review(
                brief=brief, run_id=run_id, node_id=node_id, cwd=cwd,
                session_host=session_host, round=round,
            ),
            self._adversary.review(
                brief=brief, run_id=run_id, node_id=node_id, cwd=cwd,
                session_host=session_host, round=round,
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
                agreements = [f for f in merged.findings if "," in f.source]
                disagreements = [f for f in merged.findings if "," not in f.source]
                judge_summary = await self._run_judge(
                    agreements=agreements,
                    disagreements=disagreements,
                    primary_passed=primary_verdict.passed,
                    adversary_passed=adversary_verdict.passed,
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
            # FEAT-375 code-review fix: preserve BOTH summaries when present
            # instead of discarding the adversary's whenever the primary's is
            # non-empty.
            summary="; ".join(s for s in (primary.summary, adversary.summary) if s),
            files_modified=list(primary.files_modified),
        )

    async def _run_judge(
        self,
        *,
        agreements: list[AdversarialFinding],
        disagreements: list[AdversarialFinding],
        primary_passed: bool,
        adversary_passed: bool,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost],
    ) -> str:
        """Best-effort optional LLM-judge dispatch (spec §2 G7, gated by conf).

        FEAT-375 code-review fix: the judge dispatcher's concrete type is
        intentionally left generic (``Any``, per spec §2's ``judge_dispatcher:
        Optional[Any]``), but it MUST implement the same
        ``dispatch(brief=, profile=, output_model=, run_id=, node_id=, cwd=,
        session_host=)`` contract every other dev-loop dispatcher does — the
        previous version called it with an ad hoc
        ``primary_verdict=``/``adversary_verdict=`` shape that no real
        dispatcher accepts, so an enabled judge always raised ``TypeError``
        (silently degraded by the caller's ``except Exception``, but never
        actually ran). The judge's job is a short narrative over the
        ALREADY-COMPUTED deterministic merge (``agreements``/
        ``disagreements``) — it does not re-derive the merge itself.

        The read-only ``sdd-worker`` profile assumes a Claude-compatible
        dispatcher (matching the default server wiring, which reuses the
        primary ``ClaudeCodeDispatcher``); a non-Claude judge dispatcher
        would need a different profile shape.
        """
        judge_brief = _JudgeSynthesisBrief(
            agreements=agreements,
            disagreements=disagreements,
            primary_passed=primary_passed,
            adversary_passed=adversary_passed,
        )
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            permission_mode="plan",
            allowed_tools=["Read"],
            setting_sources=["project"],
        )
        result = await self._judge_dispatcher.dispatch(
            brief=judge_brief,
            profile=profile,
            output_model=_JudgeSynthesisOutput,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
        )
        if isinstance(result, str):
            return result
        return getattr(result, "judge_summary", "") or ""


def _judges_from_conf(config_getter: ConfigGetter) -> List[JudgeSpec]:
    """Resolve the judge panel from ``DEV_LOOP_JUDGE_PANEL`` (FEAT-378).

    Mirrors ``agent_builder.parse_pool_env``'s degrade-on-malformed-JSON
    contract: an unset/empty/malformed value is never an exception — it
    silently falls back to :func:`default_judge_panel`.

    Args:
        config_getter: ``(key, fallback) -> Any`` callable.

    Returns:
        The resolved list of :class:`JudgeSpec`.
    """
    raw = config_getter("DEV_LOOP_JUDGE_PANEL", "")
    if not raw:
        return default_judge_panel().judges
    try:
        data = json.loads(raw)
        return JudgePanelConfig(**data).judges
    except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
        logging.getLogger(__name__).warning(
            "DEV_LOOP_JUDGE_PANEL is malformed (%s); using default panel.", exc
        )
        return default_judge_panel().judges


@CodeReviewDispatcherFactory.register("judge-panel")
class JudgePanelReviewDispatcher(AbstractCodeReviewDispatcher):
    """N-judge QA panel: configurable majority-decision code review (FEAT-378).

    Generalizes :class:`ParallelPerspectiveReviewDispatcher`'s single
    hardcoded Claude-shaped judge (``_run_judge``, :460) into a
    configurable panel: each judge in ``judges`` independently reviews the
    SAME neutral ``brief`` via a dispatcher materialized by
    ``agent_builder.build_dispatcher()`` (mapping ``JudgeSpec`` →
    ``DevAgentSpec``), then verdicts are combined by simple majority.

    Judge → review-dispatcher mapping: ``"claude-code"`` uses the
    write-enabled :class:`ClaudeCodeReviewDispatcher`, ``"gemini"`` uses
    :class:`GeminiCodeReviewDispatcher`, and ``"codex"`` uses
    :class:`CodexAdversarialReviewDispatcher` — the adversarial,
    ``sdd-secondopinion``-profiled reviewer (spec §2: "adversarial =
    sdd-secondopinion as a judge"), preserving the existing advisory/
    read-only conventions for the Codex seat. Other ``DevAgentBackend``
    values have no review profile defined yet and raise ``ValueError``.

    Decision rule (spec §2, fail-closed): ``passed`` = strict majority of
    the NON-errored judges. A tie among active judges, OR an
    abstention/infra-error that breaks majority (i.e. errored judges are
    themselves a majority of the panel), escalates — ``passed=False`` —
    rather than passing by default. All findings are tagged
    ``source=<judge backend>`` (``AdversarialFinding.source``, reusing the
    ``ParallelPerspectiveReviewDispatcher`` convention) so QANode's
    existing CONFIRM/REJECT/ESCALATE triage path can attribute them.
    ``files_modified`` on the merged verdict is the deduplicated union of
    every judge's own reported edits.

    Concurrency note: unlike ``ParallelPerspectiveReviewDispatcher`` (at
    most one write-enabled side), this panel may run MULTIPLE
    write-enabled judges (claude-code + gemini) concurrently against the
    SAME ``cwd`` via ``asyncio.gather`` — each dispatch is independent and
    none is synchronized against the others' edits. This mirrors the
    scope this task generalizes (single hardcoded judge → N judges) and is
    flagged, not solved, here; callers wanting a fix-free panel should
    configure judges via a future read-only profile once one exists for
    claude-code/gemini (only "codex" has one today: the adversarial
    profile used for its seat).
    """

    agent_name = "judge-panel"
    advisory = True

    def __init__(
        self,
        *,
        judges: Optional[List[JudgeSpec]] = None,
        decision: str = "majority",
        redis_url: str,
        max_concurrent: int = 4,
        stream_ttl_seconds: int = 3600,
        config_getter: ConfigGetter = _default_config_getter,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self._judge_specs = judges if judges is not None else _judges_from_conf(config_getter)
        self._decision = decision
        self._redis_url = redis_url
        self._max_concurrent = max_concurrent
        self._stream_ttl_seconds = stream_ttl_seconds
        self._config_getter = config_getter

    def build_review_profile(self) -> BaseModel:
        """Not applicable — :meth:`review` fans out to per-judge dispatchers."""
        raise NotImplementedError(
            "JudgePanelReviewDispatcher overrides review() directly and does "
            "not delegate to a single dispatch profile."
        )

    def _build_judge(self, spec: JudgeSpec) -> Tuple[str, AbstractCodeReviewDispatcher]:
        """Materialize one ``JudgeSpec`` into ``(judge_id, review_dispatcher)``.

        Lazily imports ``agent_builder``/``DevAgentSpec`` (rather than at
        module scope) because ``code_review.py`` sits on the transitive
        import path of ``parrot.flows.dev_loop``'s own ``__init__.py``
        (via ``flow.py`` → ``nodes/qa.py``) — ``agent_builder`` itself
        imports dispatch-profile names back from the package, which would
        deadlock on a partially-initialized module if done eagerly here.

        Args:
            spec: The judge's backend + optional model override.

        Returns:
            A ``(judge_id, review_dispatcher)`` pair; ``judge_id`` is the
            backend name, used both for logging and as the
            ``AdversarialFinding.source`` tag.

        Raises:
            ValueError: If ``spec.agent`` has no review-dispatcher mapping.
        """
        from parrot.flows.dev_loop.agent_builder import build_dispatcher
        from parrot.flows.dev_loop.models import DevAgentSpec

        dev_agent_spec = DevAgentSpec(agent=spec.agent, model=spec.model)
        dispatcher, _profile = build_dispatcher(
            dev_agent_spec,
            redis_url=self._redis_url,
            max_concurrent=self._max_concurrent,
            stream_ttl_seconds=self._stream_ttl_seconds,
            config_getter=self._config_getter,
        )
        judge_id = spec.agent
        model = spec.model or None

        if spec.agent == "claude-code":
            return judge_id, ClaudeCodeReviewDispatcher(dispatcher=dispatcher, model=model)
        if spec.agent == "codex":
            return judge_id, CodexAdversarialReviewDispatcher(dispatcher=dispatcher, model=model)
        if spec.agent == "gemini":
            return judge_id, GeminiCodeReviewDispatcher(dispatcher=dispatcher, model=model)

        raise ValueError(
            f"JudgePanelReviewDispatcher does not support judge backend "
            f"{spec.agent!r} — no review profile exists for it yet "
            f"(supported: claude-code, codex, gemini)."
        )

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
        round: str = "",
    ) -> CodeReviewVerdict:
        judges = [self._build_judge(spec) for spec in self._judge_specs]

        results = await asyncio.gather(
            *(
                judge.review(
                    brief=brief,
                    run_id=run_id,
                    node_id=node_id,
                    cwd=cwd,
                    session_host=session_host,
                    round=round,
                )
                for _judge_id, judge in judges
            ),
            return_exceptions=True,
        )

        verdicts: List[Tuple[str, Optional[CodeReviewVerdict]]] = []
        for (judge_id, _judge), result in zip(judges, results):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "judge %s errored during panel review: %s", judge_id, result
                )
                verdicts.append((judge_id, None))
            else:
                verdicts.append((judge_id, result))

        # FEAT-378 (code-review finding): record each judge's verdict as a
        # JudgeVerdictRecorded action so `session_host.state.judge_verdicts`
        # — and downstream readers like FeedbackRouterNode's judge-verdict
        # summary — actually see the panel's individual votes, not just the
        # merged CodeReviewVerdict this method returns. One action per judge
        # per QA round (spec §2 item 5); a round-less caller (round="")
        # still records, just without per-attempt partitioning.
        if session_host is not None:
            for (judge_id, _judge), spec, (_jid, verdict) in zip(
                judges, self._judge_specs, verdicts
            ):
                if verdict is None:
                    session_host.apply(JudgeVerdictRecorded(
                        round=round, judge_id=judge_id, backend=judge_id,
                        model=spec.model, passed=False, findings_count=0,
                        summary="judge review could not run (infra error)",
                    ))
                else:
                    session_host.apply(JudgeVerdictRecorded(
                        round=round, judge_id=judge_id, backend=judge_id,
                        model=spec.model, passed=verdict.passed,
                        findings_count=len(verdict.findings),
                        summary=verdict.summary,
                    ))

        panel_size = len(verdicts)
        errored_count = sum(1 for _judge_id, v in verdicts if v is None)
        active_count = panel_size - errored_count
        passed_count = sum(1 for _judge_id, v in verdicts if v is not None and v.passed)

        # Fail-closed: no active judges, or errored judges alone already
        # form a majority of the panel — the panel itself is down.
        if active_count == 0 or errored_count * 2 >= panel_size:
            passed = False
        elif passed_count * 2 > active_count:
            # Strict majority of the active judges passed.
            passed = True
        else:
            # Tie among active judges (or a minority pass) — escalate,
            # never pass by default.
            passed = False

        findings: List[AdversarialFinding] = []
        for judge_id, verdict in verdicts:
            if verdict is None:
                findings.append(
                    AdversarialFinding(
                        message="judge review could not run (infra error)",
                        severity="nit",
                        source=judge_id,
                    )
                )
                continue
            for finding in verdict.findings:
                findings.append(
                    AdversarialFinding(
                        message=finding.message,
                        severity=finding.severity,
                        file=finding.file,
                        line=finding.line,
                        source=judge_id,
                    )
                )

        summary = "; ".join(
            f"{judge_id}: {'pass' if v.passed else 'fail'}" if v is not None else f"{judge_id}: error"
            for judge_id, v in verdicts
        )
        # Union (order-preserving, deduplicated) of every judge's reported
        # edits. Only "claude-code"/"gemini" judges are write-enabled (the
        # "codex" judge is always the read-only adversarial reviewer, so it
        # never contributes here) — see the concurrency caveat in the class
        # docstring / this task's Completion Note.
        files_modified: List[str] = []
        for _judge_id, verdict in verdicts:
            if verdict is None:
                continue
            for path in verdict.files_modified:
                if path not in files_modified:
                    files_modified.append(path)

        return CodeReviewVerdict(
            passed=passed,
            findings=findings,
            summary=summary,
            files_modified=files_modified,
        )


__all__ = [
    "AbstractCodeReviewDispatcher",
    "CodeReviewDispatcherFactory",
    "ClaudeCodeReviewDispatcher",
    "CodexAdversarialReviewDispatcher",
    "CodexCodeReviewDispatcher",
    "GeminiCodeReviewDispatcher",
    "JudgePanelReviewDispatcher",
    "ParallelPerspectiveReviewDispatcher",
]
