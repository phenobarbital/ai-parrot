"""End-to-end Q&A reference benchmark + public export check (TASK-4243)."""

from pathlib import Path
from typing import Any

from parrot.eval import (
    CompositeEvaluator,
    ContainsMatch,
    EvalRunConfig,
    EvalRunner,
    ExactMatch,
    GroundednessMetric,
    InMemoryBaselineStore,
    InMemoryJudgeCache,
    JSONLDatasetLoader,
    JudgeCriterion,
    LLMJudgeMetric,
    NoopSandboxProvider,
    Rubric,
    SingleTurnRollout,
    TokenF1,
    check_regression,
)
from parrot.eval.judge import JudgeVerdict
from parrot.models.basic import CompletionUsage

DATASET = Path(__file__).parent / "benchmarks" / "qa_reference.jsonl"
ANSWERS = {
    "capital of France": "Paris.",
    "25 * 47": "1175",
    "largest planet": "Jupiter",
    "formula for water": "H2O",
    "capital of Germany": "Munich",
}


class _QABot:
    """Deterministic, answer-only bot for the hermetic reference benchmark."""

    async def ask(self, question: str) -> Any:
        """Return the fixture answer corresponding to ``question``."""
        text = next((answer for key, answer in ANSWERS.items() if key in question), "I don't know")
        return type(
            "Msg",
            (),
            {
                "content": text,
                "model": "mock:qa",
                "usage": CompletionUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
                "tool_calls": [],
                "metadata": {},
            },
        )()


class _AlwaysCorrectJudge:
    """Fake judge client that exercises structured-output handling without an LLM."""

    async def ask(self, prompt: str, model: str, **kwargs: Any) -> Any:
        """Return a deterministic positive verdict for every prompt."""
        return type("Response", (), {"content": "", "structured_output": JudgeVerdict(criteria={"correct": True})})()


def test_public_exports() -> None:
    """All FEAT-652 interfaces are exported from ``parrot.eval``."""
    import parrot.eval as evaluation

    names = (
        "normalize_text",
        "ExactMatch",
        "ContainsMatch",
        "TokenF1",
        "CompositeEvaluator",
        "GroundednessMetric",
        "LLMJudgeMetric",
        "JudgeCriterion",
        "Rubric",
        "JudgeVerdict",
        "judge_cache_key",
        "JudgeCache",
        "InMemoryJudgeCache",
        "PostgresJudgeCache",
        "BaselineStore",
        "InMemoryBaselineStore",
        "PostgresBaselineStore",
        "RegressionVerdict",
        "check_regression",
    )
    for name in names:
        assert name in evaluation.__all__
        assert hasattr(evaluation, name)


async def test_qa_benchmark_e2e():
    """Run reference metrics, judging, and regression checks without external services."""
    dataset = await JSONLDatasetLoader().load(str(DATASET))
    rubric = Rubric(
        name="qa",
        version="1",
        criteria=[JudgeCriterion(name="correct", question="Is the answer correct?")],
    )
    evaluator = CompositeEvaluator(
        [
            ExactMatch(),
            ContainsMatch(),
            TokenF1(threshold=0.5),
            GroundednessMetric(),
            LLMJudgeMetric(
                _AlwaysCorrectJudge(),
                judge_model="fake:judge",
                rubric=rubric,
                cache=InMemoryJudgeCache(),
                model_under_test="mock:qa",
            ),
        ],
        required=("exact_match",),
        threshold=0.5,
    )

    async def factory(sandbox: Any) -> _QABot:
        """Build a fresh deterministic bot for each runner attempt."""
        return _QABot()

    report = await EvalRunner(
        dataset=dataset,
        agent_factory=factory,
        rollout=SingleTurnRollout(),
        evaluator=evaluator,
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=2),
    ).run()

    assert report.pass_k is not None
    assert 0 < report.pass_k < 1
    assert "qa" in report.per_tag
    assert "numeric" in report.per_tag
    assert all(result.trajectory.tokens.total == 8 for result in report.results)

    store = InMemoryBaselineStore()
    await store.record(report)
    assert (await check_regression(report, store)).passed

    degraded = report.model_copy(update={"per_tag": {**report.per_tag, "qa": report.per_tag["qa"] - 0.5}})
    verdict = await check_regression(degraded, store)
    assert not verdict.passed
    assert "qa" in verdict.regressed_tags
