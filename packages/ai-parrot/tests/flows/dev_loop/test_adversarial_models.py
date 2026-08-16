"""Unit tests for FEAT-375 adversarial review models + `review_escalation` GateKind.

Covers TASK-1899 (Module 1: Models & GateKind).
"""

from __future__ import annotations

from typing import get_args

from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodexAdversarialReviewProfile,
    CodexCodeDispatchProfile,
    PerspectiveSynthesis,
    TriageBrief,
    TriageReport,
)


def test_adversarial_profile_defaults():
    p = CodexAdversarialReviewProfile()
    assert p.sandbox == "read-only"
    assert p.subagent == "sdd-secondopinion"
    assert p.approval_policy == "never"
    assert p.review_scope == "uncommitted"
    assert p.resume_last is False


def test_worker_profile_default_unchanged():
    assert CodexCodeDispatchProfile().subagent == "sdd-worker"


def test_worker_profile_accepts_secondopinion_subagent():
    assert CodexCodeDispatchProfile(subagent="sdd-secondopinion").subagent == "sdd-secondopinion"


def test_triage_brief_has_no_reasoning_field():
    assert "reasoning" not in TriageBrief.model_fields


def test_finding_disposition_literal():
    f = AdversarialFinding(message="x", severity="major", disposition="escalate")
    assert f.disposition == "escalate"


def test_finding_defaults():
    f = AdversarialFinding(message="x", severity="minor")
    assert f.source == "codex-adversarial"
    assert f.disposition is None
    assert f.triage_reason == ""


def test_triage_report_defaults():
    report = TriageReport(findings=[])
    assert report.files_modified == []
    assert report.summary == ""


def test_perspective_synthesis_defaults():
    synth = PerspectiveSynthesis(agreements=[], disagreements=[])
    assert synth.judge_summary == ""


def test_gatekind_review_escalation():
    from parrot.flows.dev_loop.session_state import GateKind

    assert "review_escalation" in get_args(GateKind)


def test_new_models_importable_from_package_init():
    from parrot.flows.dev_loop import (
        AdversarialFinding as PkgAdversarialFinding,
        CodexAdversarialReviewProfile as PkgCodexAdversarialReviewProfile,
        PerspectiveSynthesis as PkgPerspectiveSynthesis,
        TriageBrief as PkgTriageBrief,
        TriageReport as PkgTriageReport,
    )

    assert PkgAdversarialFinding is AdversarialFinding
    assert PkgCodexAdversarialReviewProfile is CodexAdversarialReviewProfile
    assert PkgPerspectiveSynthesis is PerspectiveSynthesis
    assert PkgTriageBrief is TriageBrief
    assert PkgTriageReport is TriageReport
