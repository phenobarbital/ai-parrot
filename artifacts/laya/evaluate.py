"""CLI entry point for the Laya CPU evaluation: ``python -m artifacts.laya.evaluate``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from artifacts.laya.models import (
    SCENARIOS,
    EvaluationCase,
    EvaluationConfig,
    EvaluationReport,
    SampleResult,
    load_cases,
    manifest_sha256,
)

logger = logging.getLogger("artifacts.laya.evaluate")
DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXIT_OK, EXIT_CONFIG, EXIT_INCOMPLETE = 0, 2, 3


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without importing optional Laya or Parrot dependencies."""
    parser = argparse.ArgumentParser(
        prog="python -m artifacts.laya.evaluate",
        description="FEAT-589 exploratory Laya CPU evaluation (no adoption gate).",
    )
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--checkpoint-path", type=Path, required=True)
    parser.add_argument("--checkpoint-revision", required=True)
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--primary-label", default="anthropic:opus-5")
    parser.add_argument("--primary-api-model", default=None)
    parser.add_argument("--cheap-api-model", default=None)
    parser.add_argument("--max-live-calls", type=int, default=0)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--injection-threshold", type=float, default=0.5)
    parser.add_argument("--routing-threshold", type=float, default=0.8)
    parser.add_argument("--startup-timeout-s", type=float, default=300.0)
    parser.add_argument("--prediction-timeout-s", type=float, default=30.0)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--price-file", type=Path, default=None)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    return parser


def parse_args_to_config(argv: Sequence[str] | None) -> tuple[EvaluationConfig, Path]:
    """Parse and preflight configuration before starting an evaluation worker.

    Args:
        argv: Command-line arguments excluding the program name.

    Returns:
        Validated configuration and the fixture directory.

    Raises:
        ValueError: If configuration, fixtures, prices, or live settings are invalid.
    """
    namespace = build_parser().parse_args(argv)
    fixtures = namespace.fixtures
    kwargs = {key: value for key, value in vars(namespace).items() if key != "fixtures"}
    try:
        config = EvaluationConfig(**kwargs)
    except ValidationError as exc:
        raise ValueError(f"invalid configuration: {exc}") from None
    if config.output_dir.exists() and any(config.output_dir.iterdir()):
        raise ValueError(f"--output-dir {config.output_dir} is not empty; choose a new directory")

    from artifacts.laya.live import preflight_live
    from artifacts.laya.reporting import load_prices

    preflight_live(config)
    wanted = list(SCENARIOS) if config.scenario == "all" else [config.scenario]
    for scenario in wanted:
        fixture = fixtures / f"{scenario}.jsonl"
        if not fixture.is_file():
            raise ValueError(f"missing fixture file: {fixture}")
    if "routing" in wanted and not (fixtures / "routing_rubrics.json").is_file():
        raise ValueError(f"missing routing rubric file: {fixtures / 'routing_rubrics.json'}")
    try:
        load_prices(config.price_file)
    except OSError as exc:
        raise ValueError(f"invalid --price-file: {exc}") from None
    return config, fixtures


def collect_environment(worker: Any | None) -> dict[str, Any]:
    """Collect reproducibility metadata without loading optional dependencies."""
    environment: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "worker": None,
    }
    if worker is not None and worker.ready is not None:
        environment["worker"] = worker.ready.model_dump()
        environment["startup_ms"] = worker.startup_ms
        environment["peak_rss_kb"] = worker.peak_rss_kb
        environment["peak_rss_unit"] = "kB" if worker.peak_rss_kb is not None else None
        environment["peak_rss_reason"] = (
            None if worker.peak_rss_kb is not None else "ru_maxrss unit not kB on this platform or never reported"
        )
    return environment


def build_live_agent(config: EvaluationConfig) -> Any:
    """Build the one direct Anthropic client and routing agent for a live run."""
    from parrot.clients.anthropic import AnthropicClient

    from artifacts.laya.routing import LayaEvaluationAgent

    client = AnthropicClient(backend="direct", model=config.primary_api_model)
    return LayaEvaluationAgent(
        name="laya-routing-eval",
        llm=client,
        use_tools=False,
        system_prompt="Answer concisely in English.",
    )


async def run_evaluation(config: EvaluationConfig, cases: list[EvaluationCase]) -> EvaluationReport:
    """Run local scenarios and optional paired live routing calls.

    Args:
        config: Validated evaluation configuration.
        cases: Validated cases for every requested scenario.

    Returns:
        An evaluation report, including incomplete operational evidence.
    """
    from artifacts.laya.runtime import LayaWorker, WorkerStartupError
    from artifacts.laya.scenarios import QUESTION_SCHEMAS, route_decisions_for, run_local_scenario, run_regex_baseline

    wanted = list(SCENARIOS) if config.scenario == "all" else [config.scenario]
    by_scenario = {scenario: [case for case in cases if case.scenario == scenario] for scenario in wanted}
    samples: list[SampleResult] = []
    limitations = ["smoke datasets: not representative production accuracy estimates (spec §4)"]
    metrics: dict[str, Any] = {}
    status = "complete"
    worker = LayaWorker(config)
    try:
        async with worker:
            for scenario in wanted:
                local, first = await run_local_scenario(worker, by_scenario[scenario], config)
                samples.extend(local)
                if any(sample.error_code in ("inference_timeout", "worker_failed") for sample in local):
                    status = "incomplete"
                if scenario == "injection":
                    metrics["regex_baseline"] = run_regex_baseline(by_scenario[scenario])
                if scenario == "routing":
                    decisions = route_decisions_for(first, config)
                    metrics["route_decisions"] = {key: value.model_dump() for key, value in decisions.items()}
                    if config.live:
                        from artifacts.laya.live import LiveCallBudget, load_rubrics, run_live_routing_pairs

                        agent = build_live_agent(config)
                        await agent.configure()
                        live_samples = await run_live_routing_pairs(
                            agent,
                            by_scenario[scenario],
                            decisions,
                            config,
                            LiveCallBudget(config.max_live_calls),
                            load_rubrics(DEFAULT_FIXTURES / "routing_rubrics.json"),
                        )
                        samples.extend(live_samples)
                        if any(
                            sample.error_code in ("call_cap_reached", "provider_error", "model_unverified")
                            for sample in live_samples
                        ):
                            status = "incomplete"
                            limitations.append("live routing incomplete: call, provider, or model-verification failure")
                    else:
                        status = "incomplete"
                        limitations.append(
                            "live routing not executed: --live not requested (local routing inference did run)"
                        )
    except WorkerStartupError as exc:
        status = "incomplete"
        limitations.extend(
            [
                f"{exc.error_code}: {exc}",
                "worker prerequisites missing — follow artifacts/laya/README.md 'Isolated environment' and 'Checkpoint snapshot'",
            ]
        )

    from artifacts.laya.reporting import load_prices, summarize

    metrics.update(summarize(samples, load_prices(config.price_file)))
    return EvaluationReport(
        status=status,
        config=config,
        environment=collect_environment(worker),
        question_schemas=QUESTION_SCHEMAS,
        samples=samples,
        metrics=metrics,
        limitations=limitations,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its documented exit code."""
    logging.basicConfig(level=os.environ.get("LAYA_EVAL_LOGLEVEL", "INFO"), stream=sys.stderr)
    try:
        config, fixtures = parse_args_to_config(argv)
        wanted = list(SCENARIOS) if config.scenario == "all" else [config.scenario]
        cases = [case for scenario in wanted for case in load_cases(fixtures / f"{scenario}.jsonl", scenario)]
        hashes = {scenario: manifest_sha256(fixtures / f"{scenario}.jsonl") for scenario in wanted}
    except ValueError as exc:
        logger.error("%s", exc)
        return EXIT_CONFIG

    from artifacts.laya.reporting import write_report

    try:
        report = asyncio.run(run_evaluation(config, cases))
    except Exception as exc:
        logger.exception("evaluation failed")
        report = EvaluationReport(
            status="error", config=config, limitations=[f"unexpected failure: {type(exc).__name__}: {exc}"]
        )
    report.fixture_sha256 = hashes
    json_path, markdown_path = write_report(report, config.output_dir)
    logger.info("wrote %s and %s (status=%s)", json_path, markdown_path, report.status)
    return EXIT_OK if report.status == "complete" else EXIT_INCOMPLETE


if __name__ == "__main__":
    sys.exit(main())
