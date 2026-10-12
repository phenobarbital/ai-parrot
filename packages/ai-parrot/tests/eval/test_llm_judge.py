"""Unit tests for LLMJudgeMetric with a fake client (TASK-4241)."""

import pytest

from parrot.eval.evaluators.llm_judge import LLMJudgeMetric
from parrot.eval.judge import InMemoryJudgeCache, JudgeCriterion, JudgeVerdict, Rubric
from parrot.eval.models import EvalTask, Trajectory
from parrot.eval.registry import get_metric


class FakeJudgeClient:
    """Return scripted verdicts; optionally serialize them as response text."""

    def __init__(self, verdicts, text_mode=False):
        self.verdicts = list(verdicts)
        self.text_mode = text_mode
        self.calls = 0

    async def ask(self, prompt, model, **kwargs):
        del prompt, model, kwargs
        self.calls += 1
        verdict = self.verdicts[(self.calls - 1) % len(self.verdicts)]
        if self.text_mode:
            return type("Response", (), {"content": verdict.model_dump_json()})()
        return type("Response", (), {"content": "", "structured_output": verdict})()


RUBRIC = Rubric(
    name="qa",
    version="1",
    criteria=[JudgeCriterion(name="correct", question="Correct?"), JudgeCriterion(name="concise", question="Concise?")],
)
TASK = EvalTask(task_id="t", inputs={"query": "capital of France?"}, expected={"answer": "Paris"})
TRAJECTORY = Trajectory(task_id="t", attempt=1, final_output="Paris", model="under-test")


def verdict(correct: bool, concise: bool = True) -> JudgeVerdict:
    return JudgeVerdict(criteria={"correct": correct, "concise": concise}, rationale="Looks good.")


@pytest.mark.asyncio
async def test_registered():
    assert get_metric("llm_judge") is LLMJudgeMetric


@pytest.mark.asyncio
async def test_calls_client_once_then_cached():
    client = FakeJudgeClient([verdict(True)])
    metric = LLMJudgeMetric(client, judge_model="judge", rubric=RUBRIC, cache=InMemoryJudgeCache())

    first = await metric.score(TASK, TRAJECTORY)
    second = await metric.score(TASK, TRAJECTORY)

    assert client.calls == 1
    assert first.value == 1.0
    assert second.detail["cached"] is True


@pytest.mark.asyncio
async def test_majority_vote():
    client = FakeJudgeClient([verdict(True), verdict(True), verdict(False)])
    metric = LLMJudgeMetric(client, judge_model="judge", rubric=RUBRIC, n_samples=3)

    score = await metric.score(TASK, TRAJECTORY)

    assert score.value == 1.0
    assert score.passed is True
    assert score.detail["verdict"]["criteria"] == {"correct": True, "concise": True}


@pytest.mark.asyncio
async def test_tie_is_false():
    client = FakeJudgeClient([verdict(True), verdict(False)])
    metric = LLMJudgeMetric(client, judge_model="judge", rubric=RUBRIC, n_samples=2, max_tokens=100)

    score = await metric.score(TASK, TRAJECTORY)

    assert score.detail["verdict"]["criteria"]["correct"] is False


def test_rejects_same_model():
    with pytest.raises(ValueError, match="must differ"):
        LLMJudgeMetric(FakeJudgeClient([verdict(True)]), judge_model="same", model_under_test="same", rubric=RUBRIC)


@pytest.mark.asyncio
async def test_unparseable_output():
    class GarbageClient:
        async def ask(self, prompt, model, **kwargs):
            del prompt, model, kwargs
            return type("Response", (), {"content": "garbage"})()

    metric = LLMJudgeMetric(GarbageClient(), judge_model="judge", rubric=RUBRIC)

    score = await metric.score(TASK, TRAJECTORY)

    assert score.value == 0.0
    assert score.passed is False
    assert score.detail["error"] == "judge output unparseable"


@pytest.mark.asyncio
async def test_parses_text_json_fallback():
    client = FakeJudgeClient([verdict(True)], text_mode=True)
    metric = LLMJudgeMetric(client, judge_model="judge", rubric=RUBRIC)

    score = await metric.score(TASK, TRAJECTORY)

    assert score.value == 1.0
    assert score.passed is True


@pytest.mark.asyncio
async def test_concurrent_same_key_calls_judge_once():
    import asyncio

    client = FakeJudgeClient([verdict(True)])
    original = client.ask

    async def slow_ask(prompt, model, **kwargs):
        await asyncio.sleep(0.01)
        return await original(prompt, model, **kwargs)

    client.ask = slow_ask
    metric = LLMJudgeMetric(client, judge_model="judge", rubric=RUBRIC)

    scores = await asyncio.gather(*(metric.score(TASK, TRAJECTORY) for _ in range(4)))

    assert client.calls == 1
    assert all(score.value == 1.0 for score in scores)


@pytest.mark.asyncio
async def test_cache_key_depends_on_prompt_version():
    from parrot.eval.judge import judge_cache_key

    base = dict(judge_model="j", rubric=RUBRIC, question="q", expected=None, answer="a")
    assert judge_cache_key(**base, prompt_version="1") != judge_cache_key(**base, prompt_version="2")


@pytest.mark.asyncio
async def test_self_judging_at_score_time_fails_closed():
    client = FakeJudgeClient([verdict(True)])
    metric = LLMJudgeMetric(client, judge_model="under-test", rubric=RUBRIC)

    score = await metric.score(TASK, TRAJECTORY)

    assert score.passed is False and score.value == 0.0
    assert client.calls == 0
