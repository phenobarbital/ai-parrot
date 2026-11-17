"""Dev-loop orchestration flow (FEAT-129).

An eight-node ``AgentsFlow`` (IntentClassifier → [BugIntake] → Research →
Development → QA → DeploymentHandoff → Close, with FailureHandler as the
failure/on-error terminal path) that takes a work brief and produces a PR
plus a Jira ticket transitioned to "Ready to
Deploy". See ``sdd/specs/dev-loop-orchestration.spec.md`` for the full
spec. Runs are hosted by :class:`DevLoopRunner`, which enforces the
``FLOW_MAX_CONCURRENT_RUNS`` cap.

The public names below are resolved lazily (PEP 562): importing a submodule such as
``parrot.flows.dev_loop.sdd_coder`` must not load the runner, the dispatchers or navconfig
(FEAT-633 R9 — the shipped SDD helpers run in repositories without navconfig's ``env/`` tree).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parrot.flows.dev_loop.commands import register_command_routes
    from parrot.flows.dev_loop.config import parse_repo_specs
    from parrot.flows.dev_loop.dispatchers import (
        GoogleCodingDispatcher,
        GoogleCompatCodeDispatcher,
        ClaudeCodeDispatcher,
        CodexCodeDispatcher,
        GeminiCodeDispatcher,
        LLMCodeDispatcher,
        GrokCodeDispatcher,
        MoonshotCodeDispatcher,
        NovaCodeDispatcher,
        ZaiCodeDispatcher,
        DevLoopCodeDispatcher,
        DispatchExecutionError,
        DispatchOutputValidationError,
    )
    from parrot.flows.dev_loop.flow import FlowEventPublisher, build_dev_loop_flow
    from parrot.flows.dev_loop.runner import DevLoopRunner, gate_ttl_for
    from parrot.flows.dev_loop.run_bundle import RunBundle, build_run_bundle, render_markdown
    from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
    from parrot.flows.dev_loop.streaming import (
        FlowStreamMultiplexer,
        flow_stream_ws,
    )
    from parrot.flows.dev_loop.webhook import (
        cleanup_worktree,
        register_pull_request_webhook,
        sweep_finished_worktrees,
    )
    from parrot.flows.dev_loop.models import (
        AcceptanceCriterion,
        AdversarialFinding,
        GoogleCodingDispatchProfile,
        GoogleCompatCodeDispatchProfile,
        BugBrief,
        ClaudeCodeDispatchProfile,
        CodexAdversarialReviewProfile,
        CodexCodeDispatchProfile,
        GeminiCodeDispatchProfile,
        LLMCodeDispatchProfile,
        GrokCodeDispatchProfile,
        MoonshotCodeDispatchProfile,
        NovaCodeDispatchProfile,
        PerspectiveSynthesis,
        TriageBrief,
        TriageReport,
        ZaiCodeDispatchProfile,
        CriterionResult,
        DevAgentBackend,
        DevAgentPoolConfig,
        DevAgentSpec,
        DevelopmentOutput,
        DispatchEvent,
        FlowtaskCriterion,
        LogSource,
        ManualCriterion,
        QAReport,
        ResearchOutput,
        ShellCriterion,
        TaskScopedBrief,
        WorkBrief,
        WorkerSummary,
    )
    from parrot.flows.dev_loop.session_state import (
        ActionEnvelope,
        ActionOrigin,
        ApprovalGate,
        DevLoopAction,
        DevLoopSessionState,
        GateAlreadyResolvedError,
        GateNotFoundError,
        RootAction,
        RunRegistryState,
        RunSummary,
        SessionHost,
        Snapshot,
    )

#: Public name -> defining submodule (relative to this package).
_LAZY_EXPORTS: dict[str, str] = {
    "AcceptanceCriterion": "models",
    "ActionEnvelope": "session_state",
    "ActionOrigin": "session_state",
    "AdversarialFinding": "models",
    "GoogleCodingDispatcher": "dispatchers",
    "GoogleCodingDispatchProfile": "models",
    "ApprovalGate": "session_state",
    "BugBrief": "models",
    "ClaudeCodeDispatcher": "dispatchers",
    "ClaudeCodeDispatchProfile": "models",
    "CodexAdversarialReviewProfile": "models",
    "CodexCodeDispatcher": "dispatchers",
    "CodexCodeDispatchProfile": "models",
    "DevLoopAction": "session_state",
    "DevLoopSessionState": "session_state",
    "GeminiCodeDispatcher": "dispatchers",
    "GeminiCodeDispatchProfile": "models",
    "GoogleCompatCodeDispatcher": "dispatchers",
    "GoogleCompatCodeDispatchProfile": "models",
    "LLMCodeDispatcher": "dispatchers",
    "LLMCodeDispatchProfile": "models",
    "GrokCodeDispatcher": "dispatchers",
    "GrokCodeDispatchProfile": "models",
    "MoonshotCodeDispatcher": "dispatchers",
    "MoonshotCodeDispatchProfile": "models",
    "NovaCodeDispatcher": "dispatchers",
    "NovaCodeDispatchProfile": "models",
    "ZaiCodeDispatcher": "dispatchers",
    "ZaiCodeDispatchProfile": "models",
    "CriterionResult": "models",
    "DevAgentBackend": "models",
    "DevAgentPoolConfig": "models",
    "DevAgentSpec": "models",
    "DevelopmentOutput": "models",
    "DevLoopRunner": "runner",
    "DevLoopCodeDispatcher": "dispatchers",
    "DispatchEvent": "models",
    "DispatchExecutionError": "dispatchers",
    "DispatchOutputValidationError": "dispatchers",
    "FlowEventPublisher": "flow",
    "FlowStreamMultiplexer": "streaming",
    "FlowtaskCriterion": "models",
    "GateAlreadyResolvedError": "session_state",
    "GateNotFoundError": "session_state",
    "IntentClassifierNode": "nodes.intent_classifier",
    "LogSource": "models",
    "ManualCriterion": "models",
    "PerspectiveSynthesis": "models",
    "QAReport": "models",
    "ResearchOutput": "models",
    "RootAction": "session_state",
    "RunBundle": "run_bundle",
    "RunRegistryState": "session_state",
    "RunSummary": "session_state",
    "SessionHost": "session_state",
    "ShellCriterion": "models",
    "Snapshot": "session_state",
    "TaskScopedBrief": "models",
    "TriageBrief": "models",
    "TriageReport": "models",
    "WorkBrief": "models",
    "WorkerSummary": "models",
    "build_dev_loop_flow": "flow",
    "build_run_bundle": "run_bundle",
    "cleanup_worktree": "webhook",
    "flow_stream_ws": "streaming",
    "gate_ttl_for": "runner",
    "parse_repo_specs": "config",
    "register_command_routes": "commands",
    "register_pull_request_webhook": "webhook",
    "render_markdown": "run_bundle",
    "sweep_finished_worktrees": "webhook",
}

__all__ = [
    "AcceptanceCriterion",
    "ActionEnvelope",
    "ActionOrigin",
    "AdversarialFinding",
    "GoogleCodingDispatcher",
    "GoogleCodingDispatchProfile",
    "ApprovalGate",
    "BugBrief",
    "ClaudeCodeDispatcher",
    "ClaudeCodeDispatchProfile",
    "CodexAdversarialReviewProfile",
    "CodexCodeDispatcher",
    "CodexCodeDispatchProfile",
    "DevLoopAction",
    "DevLoopSessionState",
    "GeminiCodeDispatcher",
    "GeminiCodeDispatchProfile",
    "GoogleCompatCodeDispatcher",
    "GoogleCompatCodeDispatchProfile",
    "LLMCodeDispatcher",
    "LLMCodeDispatchProfile",
    "GrokCodeDispatcher",
    "GrokCodeDispatchProfile",
    "MoonshotCodeDispatcher",
    "MoonshotCodeDispatchProfile",
    "NovaCodeDispatcher",
    "NovaCodeDispatchProfile",
    "ZaiCodeDispatcher",
    "ZaiCodeDispatchProfile",
    "CriterionResult",
    "DevAgentBackend",
    "DevAgentPoolConfig",
    "DevAgentSpec",
    "DevelopmentOutput",
    "DevLoopRunner",
    "DevLoopCodeDispatcher",
    "DispatchEvent",
    "DispatchExecutionError",
    "DispatchOutputValidationError",
    "FlowEventPublisher",
    "FlowStreamMultiplexer",
    "FlowtaskCriterion",
    "GateAlreadyResolvedError",
    "GateNotFoundError",
    "IntentClassifierNode",
    "LogSource",
    "ManualCriterion",
    "PerspectiveSynthesis",
    "QAReport",
    "ResearchOutput",
    "RootAction",
    "RunBundle",
    "RunRegistryState",
    "RunSummary",
    "SessionHost",
    "ShellCriterion",
    "Snapshot",
    "TaskScopedBrief",
    "TriageBrief",
    "TriageReport",
    "WorkBrief",
    "WorkerSummary",
    "build_dev_loop_flow",
    "build_run_bundle",
    "cleanup_worktree",
    "flow_stream_ws",
    "gate_ttl_for",
    "parse_repo_specs",
    "register_command_routes",
    "register_pull_request_webhook",
    "render_markdown",
    "sweep_finished_worktrees",
]


def __getattr__(name: str) -> Any:
    """Import the submodule defining ``name`` on first access and cache the attribute (PEP 562)."""
    submodule = _LAZY_EXPORTS.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{submodule}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports alongside the module globals."""
    return sorted({*globals(), *__all__})
