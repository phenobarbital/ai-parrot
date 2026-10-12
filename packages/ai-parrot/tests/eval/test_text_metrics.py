"""Unit tests for exact_match / contains / token_f1 (TASK-4238)."""

from parrot.eval.evaluators.text import ContainsMatch, ExactMatch, TokenF1, normalize_text
from parrot.eval.models import EvalTask, Trajectory
from parrot.eval.registry import get_metric


def _tr(text):
    return Trajectory(task_id="t", attempt=1, final_output=text)


def test_registered_names():
    assert get_metric("exact_match") is ExactMatch
    assert get_metric("contains") is ContainsMatch
    assert get_metric("token_f1") is TokenF1


def test_normalize_text():
    assert normalize_text("  Hello, World!  ") == "hello world"


async def test_exact_match_normalizes_and_accepts_list():
    task = EvalTask(task_id="t", inputs={}, expected={"answer": ["Paris", "París"]})
    matched = await ExactMatch().score(task, _tr("PARIS."))
    unmatched = await ExactMatch().score(task, _tr("Lyon"))
    assert matched.value == 1.0 and matched.passed is True
    assert unmatched.value == 0.0 and unmatched.passed is False
    assert matched.detail["matched"] == "Paris"


async def test_contains_all_any_and_regex():
    task = EvalTask(task_id="t", inputs={}, expected={"must_contain": ["Paris", "France"]})
    all_score = await ContainsMatch(mode="all").score(task, _tr("Paris is in France"))
    any_score = await ContainsMatch(mode="any").score(task, _tr("Paris is elsewhere"))
    regex_score = await ContainsMatch(regex=True).score(
        EvalTask(task_id="t", inputs={}, expected={"must_contain": [r"par\w+"]}), _tr("PARIS")
    )
    assert all_score.value == 1.0 and all_score.passed is True
    assert any_score.value == 0.5 and any_score.passed is True
    assert regex_score.value == 1.0 and regex_score.passed is True


async def test_token_f1_threshold():
    task = EvalTask(task_id="t", inputs={}, expected={"answer": "a b d"})
    score = await TokenF1(threshold=2 / 3).score(task, _tr("a b c"))
    assert score.value == 2 / 3
    assert score.passed is True


async def test_text_metrics_missing_expected():
    task = EvalTask(task_id="t", inputs={}, expected={})
    for metric, key in ((ExactMatch(), "answer"), (ContainsMatch(), "must_contain"), (TokenF1(), "answer")):
        score = await metric.score(task, _tr("anything"))
        assert score.value == 0.0
        assert score.passed is False
        assert score.detail["reason"] == f"expected.{key} missing"


async def test_contains_invalid_regex_is_scored_failure():
    from parrot.eval.evaluators.text import ContainsMatch
    from parrot.eval.models import EvalTask, Trajectory

    task = EvalTask(task_id="t", inputs={}, expected={"must_contain": ["("]})
    traj = Trajectory(task_id="t", attempt=1, final_output="anything")
    score = await ContainsMatch(regex=True).score(task, traj)
    assert score.value == 0.0 and score.passed is False
    assert "invalid regex" in score.detail["error"]


async def test_contains_punctuation_only_needle_not_found():
    from parrot.eval.evaluators.text import ContainsMatch
    from parrot.eval.models import EvalTask, Trajectory

    task = EvalTask(task_id="t", inputs={}, expected={"must_contain": ["?"]})
    traj = Trajectory(task_id="t", attempt=1, final_output="hello")
    score = await ContainsMatch().score(task, traj)
    assert score.value == 0.0 and score.detail["missing"] == ["?"]


async def test_contains_ignore_case_flag():
    from parrot.eval.evaluators.text import ContainsMatch
    from parrot.eval.models import EvalTask, Trajectory

    task = EvalTask(task_id="t", inputs={}, expected={"must_contain": ["PARIS"]})
    traj = Trajectory(task_id="t", attempt=1, final_output="paris")
    assert (await ContainsMatch(regex=True).score(task, traj)).value == 1.0
    assert (await ContainsMatch(regex=True, ignore_case=False).score(task, traj)).value == 0.0
