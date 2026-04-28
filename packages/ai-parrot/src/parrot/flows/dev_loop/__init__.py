"""Dev-loop orchestration flow (FEAT-129).

A 5-node ``AgentsFlow`` (BugIntake → Research → Development → QA →
DeploymentHandoff) that takes a bug brief and produces a PR plus a
Jira ticket transitioned to "Ready to Deploy". See
``sdd/specs/dev-loop-orchestration.spec.md`` for the full spec.
"""

from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.streaming import (
    FlowStreamMultiplexer,
    flow_stream_ws,
)
from parrot.flows.dev_loop.webhook import (
    cleanup_worktree,
    register_pull_request_webhook,
)
from parrot.flows.dev_loop.models import (
    AcceptanceCriterion,
    BugBrief,
    ClaudeCodeDispatchProfile,
    CriterionResult,
    DevelopmentOutput,
    DispatchEvent,
    FlowtaskCriterion,
    LogSource,
    ManualCriterion,
    QAReport,
    ResearchOutput,
    ShellCriterion,
)

__all__ = [
    "AcceptanceCriterion",
    "BugBrief",
    "ClaudeCodeDispatcher",
    "ClaudeCodeDispatchProfile",
    "CriterionResult",
    "DevelopmentOutput",
    "DispatchEvent",
    "DispatchExecutionError",
    "DispatchOutputValidationError",
    "FlowStreamMultiplexer",
    "FlowtaskCriterion",
    "LogSource",
    "ManualCriterion",
    "QAReport",
    "ResearchOutput",
    "ShellCriterion",
    "build_dev_loop_flow",
    "cleanup_worktree",
    "flow_stream_ws",
    "register_pull_request_webhook",
]
