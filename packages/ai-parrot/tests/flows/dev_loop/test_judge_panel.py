"""Unit tests for FEAT-378 ``JudgePanelReviewDispatcher`` (TASK-1920).

Judges are stubbed by monkeypatching ``_build_judge`` on the instance —
this decouples the majority-decision logic under test from
``agent_builder.build_dispatcher()``'s real dispatcher construction.
"""

from __future__ import annotations

from typing import get_args

import pytest
from parrot.flows.dev_loop.code_review import (
    CodeReviewDispatcherFactory,
    JudgePanelReviewDispatcher,
    ParallelPerspectiveReviewDispatcher,
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
        "mantle": _StubJudge(_v(False)),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert verdict.passed is True


async def test_majority_fail():
    panel = _panel({
        "claude-code": _StubJudge(_v(False)),
        "codex": _StubJudge(_v(True)),
        "mantle": _StubJudge(_v(False)),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert verdict.passed is False


async def test_tie_escalates():
    specs = [JudgeSpec(agent="claude-code"), JudgeSpec(agent="mantle")]
    panel = _panel(
        {
            "claude-code": _StubJudge(_v(True)),
            "mantle": _StubJudge(_v(False)),
        },
        judges=specs,
    )
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    assert verdict.passed is False  # 1/2 tie -> escalate, never pass


async def test_judge_down_degrades_to_remaining():
    panel = _panel({
        "claude-code": _StubJudge(_v(True)),
        "codex": _StubJudge(None, raises=RuntimeError("infra boom")),
        "mantle": _StubJudge(_v(True)),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    # Both active (non-errored) judges passed -> majority pass.
    assert verdict.passed is True
    assert any(f.source == "codex" and "infra error" in f.message for f in verdict.findings)


async def test_majority_down_escalates():
    specs = [JudgeSpec(agent="claude-code"), JudgeSpec(agent="codex"), JudgeSpec(agent="mantle")]
    panel = _panel(
        {
            "claude-code": _StubJudge(None, raises=RuntimeError("boom 1")),
            "codex": _StubJudge(None, raises=RuntimeError("boom 2")),
            "mantle": _StubJudge(_v(True)),
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
        "mantle": _StubJudge(
            _v(True, findings=[CodeReviewFinding(message="another nit", severity="nit", file="b.py")])
        ),
    })
    verdict = await panel.review(brief=None, run_id="r", node_id="n", cwd="/wt")
    sources = {f.source for f in verdict.findings}
    assert sources == {"claude-code", "mantle"}


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
        '{"agent": "mantle"}], "decision": "majority"}'
    )

    def fake_getter(key, fallback=None):
        return raw if key == "DEV_LOOP_JUDGE_PANEL" else fallback

    dispatcher = JudgePanelReviewDispatcher(redis_url="redis://fake", config_getter=fake_getter)
    assert [j.agent for j in dispatcher._judge_specs] == ["claude-code", "mantle"]
    assert dispatcher._judge_specs[0].model == "x"


def test_panel_from_conf_malformed_json_falls_back(monkeypatch):
    def fake_getter(key, fallback=None):
        return "{not valid json" if key == "DEV_LOOP_JUDGE_PANEL" else fallback

    dispatcher = JudgePanelReviewDispatcher(redis_url="redis://fake", config_getter=fake_getter)
    expected = default_judge_panel().judges
    assert [j.agent for j in dispatcher._judge_specs] == [j.agent for j in expected]


def test_unsupported_judge_backend_rejected_at_construction():
    """Code-review finding: JudgeSpec.agent is typed as the full 7-value
    DevAgentBackend Literal, but only 3 backends have a review profile —
    JudgeSpec now validates eagerly at construction time (config-load
    time) instead of failing silently inside asyncio.gather at dispatch
    time (JudgePanelReviewDispatcher._build_judge, still exercised below
    for a backend that somehow bypassed validation)."""
    with pytest.raises(ValueError, match="grok"):
        JudgeSpec(agent="grok")


def test_build_judge_raises_for_unsupported_backend():
    """Belt-and-suspenders: _build_judge itself still rejects an
    unsupported backend even if a JudgeSpec is constructed via
    model_construct() (bypassing validation)."""
    dispatcher = JudgePanelReviewDispatcher(
        judges=[JudgeSpec(agent="claude-code")], redis_url="redis://fake"
    )
    bypassed_spec = JudgeSpec.model_construct(agent="grok", model="")
    with pytest.raises(ValueError, match="grok"):
        dispatcher._build_judge(bypassed_spec)


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


class TestJudgeBackendPinning:
    """The judge backend set has three copies; they must not drift.

    ``JudgeBackend`` (the model) is authoritative. ``catalog.JUDGE_BACKENDS``
    and ``console._JUDGE_REVIEW_CAPABLE_BACKENDS`` restate it — the console
    one deliberately, because that module keeps the dev-loop models behind
    ``TYPE_CHECKING`` to avoid a heavy runtime import. Drift is not
    hypothetical: the console constant previously offered "google_coding"
    (and later "gemini") rows that ``JudgeSpec`` rejects outright with a
    ``ValidationError``, i.e. a guaranteed dead-end choice in the wizard.
    """

    def test_catalog_matches_the_model(self):
        from parrot.flows.dev_loop import catalog
        from parrot.flows.dev_loop.models.base import JudgeBackend

        assert catalog.JUDGE_BACKENDS == get_args(JudgeBackend)

    def test_console_constant_matches_the_model(self):
        from parrot.cli.devloop.console import _JUDGE_REVIEW_CAPABLE_BACKENDS
        from parrot.flows.dev_loop.models.base import JudgeBackend

        assert _JUDGE_REVIEW_CAPABLE_BACKENDS == get_args(JudgeBackend)

    def test_every_judge_backend_builds_a_reviewer(self):
        """``_build_judge`` must map every declared backend, or it raises.

        Guards the split introduced when "mantle" joined the panel: it is
        the one judge with no ``build_dispatcher`` branch, so it has to be
        handled BEFORE the ``DevAgentSpec`` round-trip.
        """
        from parrot.flows.dev_loop.models.base import JudgeBackend

        dispatcher = JudgePanelReviewDispatcher(redis_url="redis://fake")
        for backend in get_args(JudgeBackend):
            judge_id, reviewer = dispatcher._build_judge(JudgeSpec(agent=backend))
            assert judge_id == backend
            assert hasattr(reviewer, "review")


class TestPerRunPanelOverride:
    """``with_judges`` — the seam that makes the console's judge rows real."""

    def test_returns_a_new_instance_leaving_the_original_alone(self):
        original = JudgePanelReviewDispatcher(redis_url="redis://fake")
        before = [j.agent for j in original._judge_specs]

        override = original.with_judges([JudgeSpec(agent="claude-code")])

        assert override is not original
        assert [j.agent for j in original._judge_specs] == before

    def test_carries_transport_settings_across(self):
        original = JudgePanelReviewDispatcher(
            redis_url="redis://fake", max_concurrent=7, stream_ttl_seconds=99
        )
        override = original.with_judges([JudgeSpec(agent="claude-code")])

        assert override._redis_url == "redis://fake"
        assert override._max_concurrent == 7
        assert override._stream_ttl_seconds == 99

    def test_appends_the_adversarial_seat_when_missing(self):
        """Adversarial review is not optional — not even via a form."""
        override = JudgePanelReviewDispatcher(redis_url="redis://fake").with_judges(
            [JudgeSpec(agent="claude-code")]
        )
        assert [j.agent for j in override._judge_specs] == ["claude-code", "codex"]

    @pytest.mark.parametrize("adversary", ["codex", "mantle"])
    def test_keeps_a_panel_that_already_has_an_adversary(self, adversary):
        judges = [JudgeSpec(agent="claude-code"), JudgeSpec(agent=adversary)]
        override = JudgePanelReviewDispatcher(redis_url="redis://fake").with_judges(judges)
        assert [j.agent for j in override._judge_specs] == ["claude-code", adversary]

    def test_rejects_an_empty_panel(self):
        with pytest.raises(ValueError, match="at least one judge"):
            JudgePanelReviewDispatcher(redis_url="redis://fake").with_judges([])


# ---------------------------------------------------------------------------
# FEAT-496 TASK-2731 — per-judge DispatchLabels attribution
# ---------------------------------------------------------------------------


class _RecordingStubJudge:
    """Duck-typed judge that records every kwarg its review() receives."""

    def __init__(self, verdict=None, *, advisory=False):
        self._verdict = verdict or _v(True)
        self.advisory = advisory
        self.calls = []

    async def review(self, **kw):
        self.calls.append(kw)
        return self._verdict


class TestJudgePanelLabels:
    async def test_each_judge_gets_a_distinct_judge_id(self):
        judges = {
            "claude-code": _RecordingStubJudge(),
            "codex": _RecordingStubJudge(),
            "mantle": _RecordingStubJudge(),
        }
        panel = _panel(judges)
        await panel.review(brief=None, run_id="r", node_id="qa", cwd="/wt")

        ids = {name: j.calls[-1]["labels"].judge_id for name, j in judges.items()}
        assert set(ids.values()) == {"claude-code", "codex", "mantle"}

    async def test_judge_labels_carry_backend_and_model(self):
        judges = {"claude-code": _RecordingStubJudge(), "codex": _RecordingStubJudge()}
        specs = [
            JudgeSpec(agent="claude-code", model="claude-opus-4-6"),
            JudgeSpec(agent="codex", model="gpt-5.5"),
        ]
        panel = _panel(judges, judges=specs)
        await panel.review(brief=None, run_id="r", node_id="qa", cwd="/wt")

        claude_labels = judges["claude-code"].calls[-1]["labels"]
        assert claude_labels.agent == "claude-code"
        assert claude_labels.model == "claude-opus-4-6"

    async def test_node_id_is_still_qa(self):
        """NodeId is a closed Literal — identity must ride in labels."""
        judges = {"claude-code": _RecordingStubJudge(), "codex": _RecordingStubJudge()}
        panel = _panel(judges)
        await panel.review(brief=None, run_id="r", node_id="qa", cwd="/wt")

        for j in judges.values():
            assert j.calls[-1]["node_id"] == "qa"

    async def test_judge_ids_match_verdict_records(self):
        """Live labels and the terminal JudgeVerdictRecorded must agree."""
        judges = {"claude-code": _RecordingStubJudge(_v(True)), "codex": _RecordingStubJudge(_v(True))}
        panel = _panel(judges)
        host = SessionHost("run-labels")

        await panel.review(brief=None, run_id="r", node_id="qa", cwd="/wt", session_host=host)

        recorded_ids = {v.judge_id for verdicts in host.state.judge_verdicts.values() for v in verdicts}
        live_ids = {j.calls[-1]["labels"].judge_id for j in judges.values()}
        assert recorded_ids == live_ids

    async def test_decision_rule_unchanged(self):
        """Majority + fail-closed escalation still behave exactly as before."""
        judges = {
            "claude-code": _RecordingStubJudge(_v(True)),
            "codex": _RecordingStubJudge(_v(True)),
            "mantle": _RecordingStubJudge(_v(False)),
        }
        panel = _panel(judges)
        verdict = await panel.review(brief=None, run_id="r", node_id="qa", cwd="/wt")
        assert verdict.passed is True

    async def test_judge_without_labels_kwarg_still_runs(self):
        """Labels are best-effort — a duck-typed double must not break."""

        class _NoKwargsJudge:
            def __init__(self):
                self.called = False

            async def review(self, *, brief, run_id, node_id, cwd, session_host=None, round=""):
                self.called = True
                return _v(True)

        judge = _NoKwargsJudge()
        specs = [JudgeSpec(agent="claude-code")]
        panel = JudgePanelReviewDispatcher(judges=specs, redis_url="redis://fake")
        panel._build_judge = lambda spec: (spec.agent, judge)

        verdict = await panel.review(brief=None, run_id="r", node_id="qa", cwd="/wt")

        # The panel retries once without labels when a judge's review()
        # does not declare labels= — the review genuinely still runs.
        assert judge.called is True
        assert verdict.passed is True


class TestParallelPerspectiveLabels:
    async def test_sides_are_labelled(self):
        primary = _RecordingStubJudge(_v(True))
        adversary = _RecordingStubJudge(_v(True))
        dispatcher = ParallelPerspectiveReviewDispatcher(primary=primary, adversary=adversary)

        await dispatcher.review(brief=None, run_id="r", node_id="qa", cwd="/wt")

        assert primary.calls[-1]["labels"].judge_id == "primary"
        assert adversary.calls[-1]["labels"].judge_id == "codex-adversarial"
