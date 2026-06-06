"""Unit tests for parrot.eval.models (TASK-1415)."""
import pytest
from pydantic import ValidationError

from parrot.eval import EvalDataset, EvalResult, EvalTask, MetricScore, Trajectory


def test_eval_task_frozen():
    """EvalTask must be immutable (frozen=True)."""
    t = EvalTask(task_id="t1", inputs={"q": "hi"})
    with pytest.raises(ValidationError):
        t.task_id = "x"  # type: ignore[misc]


def test_trajectory_roundtrip():
    """Trajectory survives model_dump / model_validate round-trip."""
    tr = Trajectory(task_id="t1", attempt=1)
    assert Trajectory.model_validate(tr.model_dump()).attempt == 1


def test_eval_result_holds_scores():
    """EvalResult stores scores and passed flag correctly."""
    tr = Trajectory(task_id="t1", attempt=1)
    r = EvalResult(
        task_id="t1",
        attempt=1,
        scores=[MetricScore(name="m", value=1.0)],
        passed=True,
        trajectory=tr,
    )
    assert r.passed and r.scores[0].value == 1.0


def test_eval_task_defaults():
    """EvalTask optional fields default correctly."""
    t = EvalTask(task_id="t2", inputs={})
    assert t.expected is None
    assert t.sandbox_spec is None
    assert t.user_scenario is None
    assert t.tags == []
    assert t.metadata == {}


def test_eval_dataset_holds_tasks():
    """EvalDataset stores named tasks."""
    ds = EvalDataset(
        name="smoke",
        tasks=[EvalTask(task_id="t1", inputs={}), EvalTask(task_id="t2", inputs={})],
    )
    assert len(ds.tasks) == 2
    assert ds.name == "smoke"


def test_trajectory_extra_fields():
    """Trajectory allows extra fields (extra='allow')."""
    tr = Trajectory(task_id="t", attempt=1, custom_field="x")
    assert tr.task_id == "t"
