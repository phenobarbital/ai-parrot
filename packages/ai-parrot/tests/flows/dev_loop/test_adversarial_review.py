"""Unit tests for FEAT-375 `codex-adversarial` + `parallel` review dispatchers.

Covers TASK-1902 (Module 4: Advisory + parallel review dispatchers).
"""

from __future__ import annotations

from parrot.flows.dev_loop.code_review import (
    CodeReviewDispatcherFactory,
    CodexAdversarialReviewDispatcher,
    ParallelPerspectiveReviewDispatcher,
    _JudgeSynthesisOutput,
)
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodeReviewFinding,
    CodeReviewVerdict,
)


class _StubReviewer:
    advisory = False

    def __init__(self, verdict):
        self._v = verdict

    async def review(self, **kw):
        return self._v


class _StubDispatcher:
    """Duck-typed stand-in for CodexCodeDispatcher.dispatch()."""

    def __init__(self, verdict):
        self._verdict = verdict

    async def dispatch(self, **kw):
        return self._verdict


def test_adversarial_registered():
    assert "codex-adversarial" in CodeReviewDispatcherFactory._registry
    assert CodeReviewDispatcherFactory._registry["codex-adversarial"].advisory is True


def test_parallel_registered():
    assert "parallel" in CodeReviewDispatcherFactory._registry
    assert CodeReviewDispatcherFactory._registry["parallel"].advisory is True


def test_codex_untouched():
    assert "codex" in CodeReviewDispatcherFactory._registry
    assert CodeReviewDispatcherFactory._registry["codex"].advisory is False


async def test_parallel_merge_agreement():
    def f(m):
        return CodeReviewFinding(message=m, severity="major", file="a.py")

    primary = _StubReviewer(CodeReviewVerdict(passed=False, findings=[f("Off by one")]))
    adversary = _StubReviewer(CodeReviewVerdict(passed=False, findings=[f("off  by one")]))
    d = ParallelPerspectiveReviewDispatcher(primary=primary, adversary=adversary)
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert len(v.findings) == 1  # merged as agreement
    assert v.passed is False
    assert v.findings[0].source == "primary,codex-adversarial"


async def test_parallel_merge_disagreement_keeps_single_source():
    primary = _StubReviewer(
        CodeReviewVerdict(
            passed=True, findings=[CodeReviewFinding(message="only primary", severity="minor", file="a.py")]
        )
    )
    adversary = _StubReviewer(
        CodeReviewVerdict(
            passed=True,
            findings=[CodeReviewFinding(message="only adversary", severity="minor", file="b.py")],
        )
    )
    d = ParallelPerspectiveReviewDispatcher(primary=primary, adversary=adversary)
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    sources = {f.source for f in v.findings}
    assert sources == {"primary", "codex-adversarial"}


async def test_parallel_one_side_fails():
    class _Boom:
        advisory = False

        async def review(self, **kw):
            raise RuntimeError("down")

    ok = _StubReviewer(CodeReviewVerdict(passed=True))
    d = ParallelPerspectiveReviewDispatcher(primary=ok, adversary=_Boom())
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert v.passed is True and any("could not run" in fi.message for fi in v.findings)


async def test_parallel_files_modified_is_primary_only():
    primary = _StubReviewer(CodeReviewVerdict(passed=True, files_modified=["fixed.py"]))
    adversary = _StubReviewer(CodeReviewVerdict(passed=True))
    d = ParallelPerspectiveReviewDispatcher(primary=primary, adversary=adversary)
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert v.files_modified == ["fixed.py"]


async def test_judge_not_called_when_disabled():
    called = []

    class _Judge:
        async def dispatch(self, **kw):
            called.append(1)

    ok = _StubReviewer(CodeReviewVerdict(passed=True))
    d = ParallelPerspectiveReviewDispatcher(
        primary=ok, adversary=ok, judge_dispatcher=_Judge(), judge_enabled=False
    )
    await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert not called


async def test_judge_called_when_enabled_appends_summary():
    class _Judge:
        async def dispatch(self, **kw):
            return "judge says: looks fine"

    ok = _StubReviewer(CodeReviewVerdict(passed=True, summary="base summary"))
    d = ParallelPerspectiveReviewDispatcher(
        primary=ok, adversary=ok, judge_dispatcher=_Judge(), judge_enabled=True
    )
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert "judge says: looks fine" in v.summary


async def test_judge_dispatch_uses_real_dispatcher_contract():
    """FEAT-375 code-review fix: the judge call must match the real
    `dispatch(brief=, profile=, output_model=, run_id=, node_id=, cwd=,
    session_host=)` contract every other dev-loop dispatcher implements —
    the previous ad hoc `primary_verdict=`/`adversary_verdict=` shape always
    raised `TypeError` against a real ``ClaudeCodeDispatcher``."""

    class _RealisticJudgeDispatcher:
        async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
            assert output_model is _JudgeSynthesisOutput
            assert profile.subagent == "sdd-worker"
            assert profile.permission_mode == "plan"
            assert profile.allowed_tools == ["Read"]
            assert brief.primary_passed is True
            assert brief.adversary_passed is True
            return output_model(judge_summary="both reviewers agree the fix is safe")

    ok = _StubReviewer(CodeReviewVerdict(passed=True, summary="base summary"))
    d = ParallelPerspectiveReviewDispatcher(
        primary=ok, adversary=ok, judge_dispatcher=_RealisticJudgeDispatcher(), judge_enabled=True
    )
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert "both reviewers agree the fix is safe" in v.summary


async def test_judge_failure_degrades_silently():
    class _BrokenJudge:
        async def dispatch(self, **kw):
            raise RuntimeError("judge unavailable")

    ok = _StubReviewer(CodeReviewVerdict(passed=True, summary="base summary"))
    d = ParallelPerspectiveReviewDispatcher(
        primary=ok, adversary=ok, judge_dispatcher=_BrokenJudge(), judge_enabled=True
    )
    v = await d.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert v.passed is True
    # FEAT-375 code-review fix: both sides' summaries are preserved
    # (semicolon-joined) rather than only the primary's surviving — `ok` is
    # reused for both sides here, so the same text appears twice.
    assert v.summary == "base summary; base summary"


async def test_adversarial_never_carries_files_modified_lying_stub():
    lying_verdict = CodeReviewVerdict(
        passed=True,
        findings=[CodeReviewFinding(message="x", severity="minor", file="a.py")],
        files_modified=["should_not_appear.py"],
    )
    dispatcher = CodexAdversarialReviewDispatcher(dispatcher=_StubDispatcher(lying_verdict))
    v = await dispatcher.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert v.files_modified == []


async def test_adversarial_tags_findings_source():
    verdict = CodeReviewVerdict(
        passed=False,
        findings=[CodeReviewFinding(message="x", severity="major", file="a.py", line=1)],
    )
    dispatcher = CodexAdversarialReviewDispatcher(dispatcher=_StubDispatcher(verdict))
    v = await dispatcher.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert len(v.findings) == 1
    assert isinstance(v.findings[0], AdversarialFinding)
    assert v.findings[0].source == "codex-adversarial"


def test_adversarial_build_review_profile_defaults():
    dispatcher = CodexAdversarialReviewDispatcher(dispatcher=_StubDispatcher(CodeReviewVerdict()))
    profile = dispatcher.build_review_profile()
    assert profile.sandbox == "read-only"
    assert profile.subagent == "sdd-secondopinion"
    assert profile.review_scope == "uncommitted"
