"""Dev-loop orchestration flow (FEAT-129).

An eight-node ``AgentsFlow`` (IntentClassifier → [BugIntake] → Research →
Development → QA → DeploymentHandoff → Close, with FailureHandler as the
failure/on-error terminal path) that takes a work brief and produces a PR
plus a Jira ticket transitioned to "Ready to
Deploy". See ``sdd/specs/dev-loop-orchestration.spec.md`` for the full
spec. Runs are hosted by :class:`DevLoopRunner`, which enforces the
``FLOW_MAX_CONCURRENT_RUNS`` cap.
"""

from parrot.flows.dev_loop.commands import register_command_routes
from parrot.flows.dev_loop.config import parse_repo_specs
from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,
    CodexCodeDispatcher,
    GeminiCodeDispatcher,
    LLMCodeDispatcher,
    GrokCodeDispatcher,
    MoonshotCodeDispatcher,
    ZaiCodeDispatcher,
    DevLoopCodeDispatcher,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.flow import FlowEventPublisher, build_dev_loop_flow
from parrot.flows.dev_loop.runner import DevLoopRunner, gate_ttl_for
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
    BugBrief,
    ClaudeCodeDispatchProfile,
    CodexCodeDispatchProfile,
    GeminiCodeDispatchProfile,
    LLMCodeDispatchProfile,
    GrokCodeDispatchProfile,
    MoonshotCodeDispatchProfile,
    ZaiCodeDispatchProfile,
    CriterionResult,
    DevelopmentOutput,
    DispatchEvent,
    FlowtaskCriterion,
    LogSource,
    ManualCriterion,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    WorkBrief,
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

__all__ = [
    "AcceptanceCriterion",
    "ActionEnvelope",
    "ActionOrigin",
    "ApprovalGate",
    "BugBrief",
    "ClaudeCodeDispatcher",
    "ClaudeCodeDispatchProfile",
    "CodexCodeDispatcher",
    "CodexCodeDispatchProfile",
    "DevLoopAction",
    "DevLoopSessionState",
    "GeminiCodeDispatcher",
    "GeminiCodeDispatchProfile",
    "LLMCodeDispatcher",
    "LLMCodeDispatchProfile",
    "GrokCodeDispatcher",
    "GrokCodeDispatchProfile",
    "MoonshotCodeDispatcher",
    "MoonshotCodeDispatchProfile",
    "ZaiCodeDispatcher",
    "ZaiCodeDispatchProfile",
    "CriterionResult",
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
    "QAReport",
    "ResearchOutput",
    "RootAction",
    "RunRegistryState",
    "RunSummary",
    "SessionHost",
    "ShellCriterion",
    "Snapshot",
    "WorkBrief",
    "build_dev_loop_flow",
    "cleanup_worktree",
    "flow_stream_ws",
    "gate_ttl_for",
    "parse_repo_specs",
    "register_command_routes",
    "register_pull_request_webhook",
    "sweep_finished_worktrees",
]
