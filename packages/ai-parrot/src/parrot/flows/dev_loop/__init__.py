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
from parrot.flows.dev_loop.models import (
    AcceptanceCriterion,
    BugBrief,
    ClaudeCodeDispatchProfile,
    CriterionResult,
    DevelopmentOutput,
    DispatchEvent,
    FlowtaskCriterion,
    LogSource,
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
    "FlowtaskCriterion",
    "LogSource",
    "QAReport",
    "ResearchOutput",
    "ShellCriterion",
]
