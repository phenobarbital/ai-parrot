"""Pydantic v2 contracts for the dev-loop orchestration flow (FEAT-129).

This package is the foundation for ``parrot.flows.dev_loop``. Every other
sub-module (dispatchers, nodes, flow factory, streaming multiplexer)
imports its data structures from here.

Originally a single ``models.py`` module; split into a sub-package so each
LLM client's dispatch/review profile lives in its own file
(``claude.py``, ``codex.py``, ``gemini.py``, ``google_coding.py``,
``llm.py``, ``grok.py``, ``zai.py``, ``moonshot.py``), while the
provider-agnostic contracts stay in ``base.py``. This ``__init__`` re-exports
every public name so ``from parrot.flows.dev_loop.models import X`` keeps
working unchanged for existing callers.

See ``sdd/specs/dev-loop-orchestration.spec.md`` §2 "Data Models" for the
authoritative contracts.
"""

from __future__ import annotations

from parrot.flows.dev_loop.models.base import (
    AcceptanceCriterion,
    AdversarialFinding,
    Brief,
    BugBrief,
    CodeReviewFinding,
    CodeReviewVerdict,
    CriterionResult,
    DevAgentBackend,
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    DispatchEvent,
    DispatchLabels,
    FeatureBrief,
    FeedbackDecision,
    FlowtaskCriterion,
    JudgeBackend,
    JudgePanelConfig,
    JudgeSpec,
    LogSource,
    ManualCriterion,
    PerspectiveSynthesis,
    PlannerOutput,
    QAReport,
    RepoSpec,
    ResearchOutput,
    RevisionBrief,
    ShellCriterion,
    SynthesisReport,
    TaskScopedBrief,
    TriageBrief,
    TriageReport,
    WorkBrief,
    WorkerSummary,
    WorkKind,
    default_judge_panel,
    parse_brief,
)
from parrot.flows.dev_loop.models.claude import (
    ClaudeCodeDispatchProfile,
    ClaudeCodeReviewProfile,
)
from parrot.flows.dev_loop.models.codex import (
    CodexAdversarialReviewProfile,
    CodexCodeDispatchProfile,
    CodexCodeReviewProfile,
)
from parrot.flows.dev_loop.models.gemini import (
    GeminiCodeDispatchProfile,
)
from parrot.flows.dev_loop.models.google_coding import (
    GoogleCodingDispatchProfile,
)
from parrot.flows.dev_loop.models.grok import GrokCodeDispatchProfile
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile
from parrot.flows.dev_loop.models.moonshot import MoonshotCodeDispatchProfile
from parrot.flows.dev_loop.models.nova import (
    NovaAdversarialReviewProfile,
    NovaCodeDispatchProfile,
    NovaMechanicalProfile,
)
from parrot.flows.dev_loop.models.zai import ZaiCodeDispatchProfile

__all__ = [
    "AcceptanceCriterion",
    "AdversarialFinding",
    "Brief",
    "BugBrief",
    "ClaudeCodeDispatchProfile",
    "ClaudeCodeReviewProfile",
    "CodeReviewFinding",
    "CodeReviewVerdict",
    "CodexAdversarialReviewProfile",
    "CodexCodeDispatchProfile",
    "CodexCodeReviewProfile",
    "CriterionResult",
    "DevAgentBackend",
    "DevAgentPoolConfig",
    "DevAgentSpec",
    "DevelopmentOutput",
    "DispatchEvent",
    "DispatchLabels",
    "FeatureBrief",
    "FeedbackDecision",
    "FlowtaskCriterion",
    "GeminiCodeDispatchProfile",
    "GoogleCodingDispatchProfile",
    "GrokCodeDispatchProfile",
    "JudgeBackend",
    "JudgePanelConfig",
    "JudgeSpec",
    "LLMCodeDispatchProfile",
    "LogSource",
    "ManualCriterion",
    "MoonshotCodeDispatchProfile",
    "NovaAdversarialReviewProfile",
    "NovaCodeDispatchProfile",
    "NovaMechanicalProfile",
    "PerspectiveSynthesis",
    "PlannerOutput",
    "QAReport",
    "RepoSpec",
    "ResearchOutput",
    "RevisionBrief",
    "ShellCriterion",
    "SynthesisReport",
    "TaskScopedBrief",
    "TriageBrief",
    "TriageReport",
    "WorkBrief",
    "WorkKind",
    "WorkerSummary",
    "ZaiCodeDispatchProfile",
    "default_judge_panel",
    "parse_brief",
]
