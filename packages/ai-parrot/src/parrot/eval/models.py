"""Pydantic v2 data models for the Generic Agent Evaluation Harness.

FEAT-217 — All evaluation data contracts live here.  No behavior — pure data.
``SandboxSpec`` is defined in ``parrot.eval.sandbox.base`` and referenced
via a forward reference in ``EvalTask``; call ``EvalTask.model_rebuild()``
once ``SandboxSpec`` is importable (done in ``parrot/eval/__init__.py``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from parrot.eval.sandbox.base import SandboxSpec


class EvalTask(BaseModel):
    """A single evaluation task (input + ground-truth expectation).

    Frozen so that dataset records are immutable after construction.
    ``sandbox_spec`` uses a forward reference resolved once
    ``SandboxSpec`` is importable.

    Attributes:
        task_id: Unique identifier for the task.
        inputs: Free-form input dict passed to the agent.
        expected: Gold answer / goal state / test command (eval-type specific).
        sandbox_spec: Optional sandbox configuration for this task.
        user_scenario: Natural language scenario for the LLM user simulator.
        tags: Grouping labels for per-tag aggregation in the report.
        metadata: Arbitrary metadata attached to the task record.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    task_id: str
    inputs: dict[str, Any]
    expected: dict[str, Any] | None = None
    sandbox_spec: "SandboxSpec | None" = None  # forward ref resolved via model_rebuild()
    user_scenario: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    """Record of a single tool invocation during a trajectory turn.

    Attributes:
        name: Tool name called.
        arguments: Arguments passed to the tool.
        result: Return value of the tool, if available.
        error: Error string if the tool raised, otherwise ``None``.
        latency_ms: Wall-clock time for the tool call in milliseconds.
    """

    name: str
    arguments: dict[str, Any]
    result: Any | None = None
    error: str | None = None
    latency_ms: float | None = None


class TurnRecord(BaseModel):
    """A single conversational turn in a trajectory.

    Attributes:
        role: Speaker role — ``"user"``, ``"agent"``, ``"tool"``, or
            ``"system"``.
        content: Text content of the turn (may be ``None`` for tool-only
            turns).
        tool_calls: Tool invocations that occurred during this turn.
        timestamp: Unix epoch timestamp when this turn was recorded.
    """

    role: Literal["user", "agent", "tool", "system"]
    content: str | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    timestamp: float


class TokenUsage(BaseModel):
    """Aggregated token counts for a trajectory attempt.

    Attributes:
        prompt: Total prompt/input tokens consumed.
        completion: Total completion/output tokens consumed.
        total: Sum of prompt and completion tokens.
    """

    prompt: int = 0
    completion: int = 0
    total: int = 0


class Trajectory(BaseModel):
    """Full record of one agent attempt on a task.

    Retained raw in the report so old runs can be re-scored offline
    without re-running the agent (spec D5).

    Attributes:
        task_id: ID of the ``EvalTask`` this trajectory covers.
        attempt: Attempt index (1-based, up to ``k``).
        turns: Ordered list of conversational turns.
        final_output: Final agent response (text or structured output).
        final_state: Snapshot of world state captured after the rollout.
        tokens: Aggregated token usage.
        cost_usd: Estimated cost in US dollars.
        setup_latency_ms: Time to instantiate and bind the agent.
        latency_ms: Rollout-only wall-clock time.
        error: Exception string if the attempt failed, otherwise ``None``.
        trace_context: W3C traceparent/tracestate for distributed tracing.
    """

    model_config = ConfigDict(extra="allow")

    task_id: str
    attempt: int
    turns: list[TurnRecord] = Field(default_factory=list)
    final_output: Any | None = None
    final_state: dict[str, Any] | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    setup_latency_ms: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None
    trace_context: dict[str, str] | None = None


class MetricScore(BaseModel):
    """Score for a single metric on one attempt.

    Attributes:
        name: Metric name (e.g. ``"state_match"``).
        value: Normalized score in ``[0.0, 1.0]``; binary metrics use 0.0
            or 1.0.
        passed: Whether the metric threshold was met, when applicable.
        detail: Additional scoring detail (mismatches, forbidden entities, …).
    """

    name: str
    value: float
    passed: bool | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    """Evaluation outcome for a single (task, attempt) pair.

    Attributes:
        task_id: ID of the evaluated task.
        attempt: Attempt index this result covers.
        scores: Per-metric scores.
        passed: Aggregate pass/fail: ``True`` iff all metrics passed.
        trajectory: The trajectory used to produce this result.
    """

    task_id: str
    attempt: int
    scores: list[MetricScore]
    passed: bool
    trajectory: Trajectory


class EvalDataset(BaseModel):
    """A named collection of evaluation tasks.

    Attributes:
        name: Human-readable dataset name (used in reports and baselines).
        tasks: Ordered list of tasks to evaluate.
    """

    name: str
    tasks: list[EvalTask]
