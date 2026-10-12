"""Unit tests for GroundednessMetric (TASK-4239)."""
from parrot.eval.evaluators.groundedness import GroundednessMetric
from parrot.eval.models import EvalTask, ToolCallRecord, Trajectory, TurnRecord
from parrot.eval.registry import get_metric
from parrot.models.basic import ToolCall
from parrot.security.groundedness import EvidenceIndex, GroundednessPolicy, GroundednessScorer


def _trajectory(answer: str, result: object) -> Trajectory:
    """Build a one-tool-call trajectory for groundedness scoring tests."""
    record = ToolCallRecord(name="get_revenue", arguments={}, result=result, latency_ms=20.0)
    return Trajectory(
        task_id="t",
        attempt=1,
        final_output=answer,
        turns=[TurnRecord(role="agent", content=answer, tool_calls=[record], timestamp=0.0)],
    )


async def test_metric_matches_direct_scorer():
    """Metric evidence reconstruction produces the direct scorer's score."""
    task = EvalTask(task_id="t", inputs={"query": "revenue?"})
    trajectory = _trajectory("Revenue was $1,243,500 in Q3.", {"summary": "Revenue was $1,243,500."})
    policy = GroundednessPolicy()
    direct = GroundednessScorer(policy).score(
        trajectory.final_output,
        EvidenceIndex.from_tool_calls(
            [
                ToolCall(
                    id="0-0",
                    name="get_revenue",
                    arguments={},
                    result={"summary": "Revenue was $1,243,500."},
                )
            ],
            policy,
            user_prompt="revenue?",
        ),
    )

    got = await GroundednessMetric(policy).score(task, trajectory)

    assert got.value == direct.score
    assert got.detail["score"] == direct.score


def test_registered():
    """The metric decorator exposes the fixed registry name."""
    assert get_metric("groundedness") is GroundednessMetric


async def test_no_evidence_neutral():
    """A trajectory with no tool calls produces a neutral passed score."""
    task = EvalTask(task_id="t", inputs={"query": "revenue?"})
    trajectory = Trajectory(task_id="t", attempt=1, final_output="Revenue was $1,243,500.")

    got = await GroundednessMetric().score(task, trajectory)

    assert got.value == 1.0
    assert got.passed is True
    assert got.detail["no_evidence"] is True


async def test_contradicted_fails():
    """A transposed-digit answer is failed when contradictions are enforced."""
    task = EvalTask(task_id="t", inputs={"query": "revenue?"})
    trajectory = _trajectory("Revenue was $1,234,500.", {"summary": "Revenue was $1,243,500."})

    got = await GroundednessMetric().score(task, trajectory)

    assert got.passed is False
    assert got.detail["contradicted"]


async def test_fail_on_contradicted_false_uses_threshold_only():
    """Disabling contradiction failure makes the configured threshold decisive."""
    task = EvalTask(task_id="t", inputs={"query": "revenue?"})
    trajectory = _trajectory("Revenue was $1,234,500.", {"summary": "Revenue was $1,243,500."})

    got = await GroundednessMetric(min_score=0.0, fail_on_contradicted=False).score(task, trajectory)

    assert got.passed is True
    assert got.detail["contradicted"]
