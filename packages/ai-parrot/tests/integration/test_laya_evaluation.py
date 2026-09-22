"""FEAT-589 M5 mocked end-to-end and opt-in Laya evaluation tests."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from artifacts.laya import evaluate  # noqa: E402

LOG = REPO_ROOT / "artifacts" / "logs" / "laya_evaluation_pytest.log"
FAKE_CHILD = textwrap.dedent(
    """
    import json
    import os
    import sys

    sys.stdout.write(json.dumps({"type": "ready", "worker_pid": os.getpid(), "device": "cpu",
        "checkpoint_path": "x", "checkpoint_revision": "fake", "packages": {}, "load_ms": 1.0,
        "python": "3", "platform": "fake"}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        request = json.loads(line)
        answers = {}
        for question_id, question in request["questions"].items():
            if question["type"] == "choice":
                options = question["options"]
                remainder = 0.3 / (len(options) - 1)
                answers[question_id] = {"type": "choice", "choice": options[0], "confidence": 0.85,
                    "probabilities": {option: 0.7 if option == options[0] else remainder for option in options}}
            else:
                noul = 0.9 if "ignore" in request["state"].lower() else 0.1
                answers[question_id] = {"type": "noul", "noul": noul, "confidence": 0.9}
        sys.stdout.write(json.dumps({"type": "result", "request_id": request["request_id"], "status": "ok",
            "answers": answers, "inference_ms": 2.0, "error_code": None, "error_message": None,
            "peak_rss_kb": 1234}) + "\\n")
        sys.stdout.flush()
    """
)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Generator[None, None, None]:
    """Expose the call outcome to the autouse log fixture."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.rep_call = report


@pytest.fixture(autouse=True)
def _log_run(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Append one outcome line per test, including intentionally skipped tests."""
    yield
    LOG.parent.mkdir(parents=True, exist_ok=True)
    outcome = getattr(request.node, "rep_call", None)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{request.node.nodeid}\\t{outcome.outcome if outcome else 'unknown'}\\n")


class _FakeAgent:
    """Offline routed agent that provides verifiable model and usage evidence."""

    async def configure(self) -> None:
        """Match the live agent configuration hook without side effects."""

    async def ask_routed(self, question: str, decision: Any, **kwargs: Any) -> AIMessage:
        """Return a deterministic response with provider model evidence."""
        return AIMessage(
            input=question,
            output="Paris",
            response="Paris",
            model=decision.selected_model,
            provider="claude",
            raw_response={"model": f"{decision.selected_model}-real"},
            usage=CompletionUsage(prompt_tokens=2, completion_tokens=1, total_tokens=3),
        )


def test_mocked_end_to_end_produces_all_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Produce complete local and paired-live reports with no real worker or credentials."""
    (tmp_path / "fake_child.py").write_text(FAKE_CHILD, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(evaluate, "build_live_agent", lambda config: _FakeAgent())
    original_parse = evaluate.parse_args_to_config

    def parse_with_fake_worker(argv: list[str] | None):
        config, fixtures = original_parse(argv)
        return config.model_copy(update={"worker_module": "fake_child"}), fixtures

    monkeypatch.setattr(evaluate, "parse_args_to_config", parse_with_fake_worker)
    output_dir = tmp_path / "out"
    result = evaluate.main(
        [
            "--worker-python",
            sys.executable,
            "--checkpoint-path",
            str(tmp_path),
            "--checkpoint-revision",
            "fake",
            "--output-dir",
            str(output_dir),
            "--repeats",
            "2",
            "--warmup",
            "1",
            "--live",
            "--primary-api-model",
            "P",
            "--cheap-api-model",
            "C",
            "--max-live-calls",
            "40",
        ]
    )
    report = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert result == 0
    assert report["status"] == "complete"
    assert set(report["metrics"]["scenarios"]) == {"injection", "routing", "grounded"}
    assert {sample["arm"] for sample in report["samples"] if sample["scenario"] == "routing"} == {
        "local",
        "primary",
        "routed",
    }
    assert (output_dir / "report.md").is_file()
    assert "regex_baseline" in report["metrics"]


def _real_env() -> dict[str, str] | None:
    """Return real-CPU prerequisites only when all required variables are present."""
    keys = ("LAYA_EVAL_WORKER_PYTHON", "LAYA_EVAL_CHECKPOINT", "LAYA_EVAL_REVISION")
    return {key: os.environ[key] for key in keys} if all(os.environ.get(key) for key in keys) else None


def _required_live_env() -> tuple[dict[str, str] | None, list[str]]:
    """Return all live prerequisites and identify every missing variable."""
    environment = _real_env()
    keys = (
        "LAYA_EVAL_LIVE",
        "LAYA_EVAL_PRIMARY_API_MODEL",
        "LAYA_EVAL_CHEAP_API_MODEL",
        "LAYA_EVAL_MAX_LIVE_CALLS",
        "ANTHROPIC_API_KEY",
    )
    missing = [key for key in keys if not os.environ.get(key)]
    if os.environ.get("LAYA_EVAL_LIVE") != "1" and "LAYA_EVAL_LIVE" not in missing:
        missing.append("LAYA_EVAL_LIVE=1")
    return environment, missing


async def test_real_cpu_scenarios(tmp_path: Path) -> None:
    """Run real CPU inference only with explicit environment-provided prerequisites."""
    environment = _real_env()
    if environment is None:
        pytest.skip("real CPU run not requested: set LAYA_EVAL_WORKER_PYTHON, LAYA_EVAL_CHECKPOINT, LAYA_EVAL_REVISION")
    output_dir = tmp_path / "real"
    result = await asyncio.to_thread(
        evaluate.main,
        [
            "--worker-python",
            environment["LAYA_EVAL_WORKER_PYTHON"],
            "--checkpoint-path",
            environment["LAYA_EVAL_CHECKPOINT"],
            "--checkpoint-revision",
            environment["LAYA_EVAL_REVISION"],
            "--output-dir",
            str(output_dir),
            "--repeats",
            "3",
            "--warmup",
            "1",
        ],
    )
    report = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert result in (0, 3)
    assert report["environment"]["worker"]["device"] == "cpu"
    assert all(metrics["n_cases"] > 0 and metrics["n_error"] == 0 for metrics in report["metrics"]["scenarios"].values())
    assert report["status"] == "incomplete"
    assert any("--live not requested" in limitation for limitation in report["limitations"])


@pytest.mark.live
async def test_live_paired_routing(tmp_path: Path) -> None:
    """Validate opt-in paired routing evidence only with complete live prerequisites."""
    environment, missing = _required_live_env()
    if environment is None:
        missing.extend(("LAYA_EVAL_WORKER_PYTHON", "LAYA_EVAL_CHECKPOINT", "LAYA_EVAL_REVISION"))
    if missing:
        pytest.skip(f"live paired routing not requested: set {', '.join(sorted(set(missing)))}")
    assert environment is not None
    output_dir = tmp_path / "live"
    max_live_calls = os.environ["LAYA_EVAL_MAX_LIVE_CALLS"]
    result = await asyncio.to_thread(
        evaluate.main,
        [
            "--worker-python",
            environment["LAYA_EVAL_WORKER_PYTHON"],
            "--checkpoint-path",
            environment["LAYA_EVAL_CHECKPOINT"],
            "--checkpoint-revision",
            environment["LAYA_EVAL_REVISION"],
            "--scenario",
            "routing",
            "--output-dir",
            str(output_dir),
            "--repeats",
            "3",
            "--warmup",
            "1",
            "--live",
            "--primary-api-model",
            os.environ["LAYA_EVAL_PRIMARY_API_MODEL"],
            "--cheap-api-model",
            os.environ["LAYA_EVAL_CHEAP_API_MODEL"],
            "--max-live-calls",
            max_live_calls,
        ],
    )
    report = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    live_samples = [
        sample
        for sample in report["samples"]
        if sample["scenario"] == "routing" and sample["arm"] in {"primary", "routed"}
    ]
    assert result == 0
    assert {sample["arm"] for sample in live_samples} == {"primary", "routed"}
    assert all(sample["actual_model"] for sample in live_samples if sample["status"] == "ok")
    assert all(report["metrics"]["routing"]["arms"][arm]["usage"] is not None for arm in ("primary", "routed"))
    assert len(live_samples) <= int(max_live_calls)
