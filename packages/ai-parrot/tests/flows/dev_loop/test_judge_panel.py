"""Unit tests for FEAT-378 ``JudgePanelReviewDispatcher`` (TASK-1920).

Judges are stubbed by monkeypatching ``_build_judge`` on the instance —
this decouples the majority-decision logic under test from
``agent_builder.build_dispatcher()``'s real dispatcher construction.
"""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop.code_review import (
    CodeReviewDispatcherFactory,
    JudgePanelReviewDispatcher,
)
from parrot.flows.dev_loop.models import (
    CodeReviewFinding,
    CodeReviewVerdict,
    JudgeSpec,
    default_judge_panel,
)
from parrot.flows.dev_loop.session_state import SessionHost


class _StubJudge:
    """Duck-typed stand-in for an ``AbstractCodeReviewDispatcher``."""

    def __init__(self, verdict=None, *, raises: Exception | None = None):
        self._verdict = verdict
        self._raises = raises

    async def review(self, **kw):
        if self._raises is not None:
            raise self._raises
        return self._verdict


def _panel(judge_verdicts: dict[str, _StubJudge], *, judges=None) -> JudgePanelReviewDispatcher:
    """Build a dispatcher whose ``_build_judge`` returns canned stub judges."""
    specs = judges or [JudgeSpec(agent=name) for name in judge_verdicts]
    dispatcher = JudgePanelReviewDispatcher(judges=specs, redis_url="redis://fake")

    def _fake_build_judge(spec):
        return spec.agent, judge_verdicts[spec.agent]

    dispatcher._build_judge = _fake_build_judge  # type: ignore[method-assign]
    return dispatcher


def _v(passed: bool, *, findings=None) -> CodeReviewVerdict:
    return CodeReviewVerdict(passed=passed, findings=findings or [])


async def test_majority_pass():
    panel = _panel({
        "claude-code": _StubJudge(_v(True)),
        "codex": _StubJudge(_v(True)),
        "gemini": _StubJudge(_v(False)),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert verdict.passed is True


async def test_majority_fail():
    panel = _panel({
        "claude-code": _StubJudge(_v(False)),
        "codex": _StubJudge(_v(True)),
        "gemini": _StubJudge(_v(False)),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert verdict.passed is False


async def test_tie_escalates():
    specs = [JudgeSpec(agent="claude-code"), JudgeSpec(agent="gemini")]
    panel = _panel(
        {
            "claude-code": _StubJudge(_v(True)),
            "gemini": _StubJudge(_v(False)),
        },
        judges=specs,
    )
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert verdict.passed is False  # 1/2 tie -> escalate, never pass


async def test_judge_down_degrades_to_remaining():
    panel = _panel({
        "claude-code": _StubJudge(_v(True)),
        "codex": _StubJudge(None, raises=RuntimeError("infra boom")),
        "gemini": _StubJudge(_v(True)),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    # Both active (non-errored) judges passed -> majority pass.
    assert verdict.passed is True
    assert any(f.source == "codex" and "infra error" in f.message for f in verdict.findings)


async def test_majority_down_escalates():
    specs = [JudgeSpec(agent="claude-code"), JudgeSpec(agent="codex"), JudgeSpec(agent="gemini")]
    panel = _panel(
        {
            "claude-code": _StubJudge(None, raises=RuntimeError("boom 1")),
            "codex": _StubJudge(None, raises=RuntimeError("boom 2")),
            "gemini": _StubJudge(_v(True)),
        },
        judges=specs,
    )
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    # 2/3 judges errored -> panel itself is down -> fail-closed escalate,
    # even though the single remaining judge passed.
    assert verdict.passed is False


async def test_findings_source_tagged():
    panel = _panel({
        "claude-code": _StubJudge(
            _v(True, findings=[CodeReviewFinding(message="nit here", severity="nit", file="a.py")])
        ),
        "codex": _StubJudge(_v(True)),
        "gemini": _StubJudge(
            _v(True, findings=[CodeReviewFinding(message="another nit", severity="nit", file="b.py")])
        ),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    sources = {f.source for f in verdict.findings}
    assert sources == {"claude-code", "gemini"}


def test_factory_registration():
    assert "judge-panel" in CodeReviewDispatcherFactory._registry
    assert CodeReviewDispatcherFactory._registry["judge-panel"].advisory is True
    assert CodeReviewDispatcherFactory._registry["judge-panel"] is JudgePanelReviewDispatcher


def test_default_panel_from_conf_unset(monkeypatch):
    """``DEV_LOOP_JUDGE_PANEL`` unset -> ``default_judge_panel()`` is used."""

    def fake_getter(key, fallback=None):
        assert key == "DEV_LOOP_JUDGE_PANEL"
        return fallback

    dispatcher = JudgePanelReviewDispatcher(redis_url="redis://fake", config_getter=fake_getter)
    expected = default_judge_panel().judges
    assert [j.agent for j in dispatcher._judge_specs] == [j.agent for j in expected]
    assert [j.model for j in dispatcher._judge_specs] == [j.model for j in expected]


def test_panel_from_conf_json(monkeypatch):
    raw = (
        '{"judges": [{"agent": "claude-code", "model": "x"}, '
        '{"agent": "gemini"}], "decision": "majority"}'
    )

    def fake_getter(key, fallback=None):
        return raw if key == "DEV_LOOP_JUDGE_PANEL" else fallback

    dispatcher = JudgePanelReviewDispatcher(redis_url="redis://fake", config_getter=fake_getter)
    assert [j.agent for j in dispatcher._judge_specs] == ["claude-code", "gemini"]
    assert dispatcher._judge_specs[0].model == "x"


def test_panel_from_conf_malformed_json_falls_back(monkeypatch):
    def fake_getter(key, fallback=None):
        return "{not valid json" if key == "DEV_LOOP_JUDGE_PANEL" else fallback

    dispatcher = JudgePanelReviewDispatcher(redis_url="redis://fake", config_getter=fake_getter)
    expected = default_judge_panel().judges
    assert [j.agent for j in dispatcher._judge_specs] == [j.agent for j in expected]


def test_unsupported_judge_backend_raises():
    dispatcher = JudgePanelReviewDispatcher(
        judges=[JudgeSpec(agent="grok")], redis_url="redis://fake"
    )
    with pytest.raises(ValueError, match="grok"):
        dispatcher._build_judge(JudgeSpec(agent="grok"))


# ---------------------------------------------------------------------------
# JudgeVerdictRecorded (code-review finding: the action existed but was
# never applied — session_host.state.judge_verdicts was always empty).
# ---------------------------------------------------------------------------


async def test_review_records_judge_verdicts_when_session_host_present():
    panel = _panel({
        "claude-code": _StubJudge(_v(True, findings=[CodeReviewFinding(message="ok", severity="nit")])),
        "codex": _StubJudge(_v(False)),
    })
    host = SessionHost(run_id="r1")

    await panel.review(
        brief=None, run_id="r1", node_id="qa", cwd="/wt",
        session_host=host, round="qa-1",
    )

    recorded = host.state.judge_verdicts["qa-1"]
    assert {v.judge_id for v in recorded} == {"claude-code", "codex"}
    claude_verdict = next(v for v in recorded if v.judge_id == "claude-code")
    assert claude_verdict.passed is True
    assert claude_verdict.findings_count == 1
    codex_verdict = next(v for v in recorded if v.judge_id == "codex")
    assert codex_verdict.passed is False


async def test_review_records_errored_judge_as_failed_verdict():
    panel = _panel({
        "claude-code": _StubJudge(_v(True)),
        "codex": _StubJudge(None, raises=RuntimeError("boom")),
    })
    host = SessionHost(run_id="r1")

    await panel.review(
        brief=None, run_id="r1", node_id="qa", cwd="/wt",
        session_host=host, round="qa-1",
    )

    codex_verdict = next(
        v for v in host.state.judge_verdicts["qa-1"] if v.judge_id == "codex"
    )
    assert codex_verdict.passed is False
    assert "infra error" in codex_verdict.summary


async def test_review_without_session_host_does_not_raise():
    """session_host=None (default) must degrade to a no-op, not raise."""
    panel = _panel({"claude-code": _StubJudge(_v(True))})
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert verdict.passed is True


async def test_review_without_round_still_records():
    """A round-less caller (round="", the default) still records verdicts
    — just without per-QA-attempt partitioning."""
    panel = _panel({"claude-code": _StubJudge(_v(True))})
    host = SessionHost(run_id="r1")

    await panel.review(brief=None, run_id="r1", node_id="qa", cwd="/wt", session_host=host)

    assert "" in host.state.judge_verdicts
    assert host.state.judge_verdicts[""][0].judge_id == "claude-code"
