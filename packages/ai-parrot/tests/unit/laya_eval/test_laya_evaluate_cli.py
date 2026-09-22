"""FEAT-589 M4 — CLI configuration, incomplete reports, and no-live defaults."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from artifacts.laya import evaluate
from artifacts.laya.models import EvaluationConfig


FAKE_CHILD = textwrap.dedent(
    """
    import json
    import os
    import sys

    sys.stdout.write(json.dumps({"type": "ready", "worker_pid": os.getpid(), "device": "cpu",
        "checkpoint_path": "x", "checkpoint_revision": "r", "packages": {}, "load_ms": 1.0,
        "python": "3", "platform": "fake"}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        request = json.loads(line)
        answers = {}
        for question_id, question in request["questions"].items():
            if question["type"] == "choice":
                answers[question_id] = {"type": "choice", "choice": "cheap", "confidence": 0.9,
                    "probabilities": {"primary": 0.05, "cheap": 0.9, "abstain": 0.05}}
            else:
                answers[question_id] = {"type": "noul", "noul": 0.1, "confidence": 0.9}
        sys.stdout.write(json.dumps({"type": "result", "request_id": request["request_id"], "status": "ok",
            "answers": answers, "inference_ms": 2.0, "error_code": None, "error_message": None,
            "peak_rss_kb": 1234}) + "\\n")
        sys.stdout.flush()
    """
)


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--worker-python",
        sys.executable,
        "--checkpoint-path",
        str(tmp_path),
        "--checkpoint-revision",
        "r",
        "--output-dir",
        str(tmp_path / "out"),
        "--repeats",
        "1",
        "--warmup",
        "0",
        *extra,
    ]


def test_help_works_without_laya(capsys: pytest.CaptureFixture[str]) -> None:
    """The parser help path does not require an isolated Laya environment."""
    with pytest.raises(SystemExit) as exit_info:
        evaluate.main(["--help"])
    assert exit_info.value.code == 0
    assert "--primary-api-model" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        ["--injection-threshold", "1.5"],
        ["--live"],
        ["--fixtures", "/nonexistent/dir"],
    ],
)
def test_configuration_errors_exit_2_before_any_process(
    tmp_path: Path, extra: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid settings fail before a worker or a provider call is started."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert evaluate.main(_argv(tmp_path, *extra)) == 2


def test_non_empty_output_dir_exits_2(tmp_path: Path) -> None:
    """A report directory is never implicitly overwritten."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "existing").write_text("x", encoding="utf-8")
    assert evaluate.main(_argv(tmp_path)) == 2


def test_missing_worker_module_yields_incomplete_report_exit_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A startup failure is represented in both report formats rather than raised."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert evaluate.main(_argv(tmp_path, "--scenario", "injection")) == 3
    report = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert report["status"] == "incomplete"
    assert any("dependency_missing" in limitation for limitation in report["limitations"])
    assert "README" in " ".join(report["limitations"])
    assert set(report["fixture_sha256"]) == {"injection"}
    assert (tmp_path / "out" / "report.md").is_file()


def test_no_live_calls_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Routing runs locally without constructing a live Anthropic agent by default."""
    (tmp_path / "fake_laya_child.py").write_text(FAKE_CHILD, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    def no_live_agent(config: EvaluationConfig) -> None:
        raise AssertionError(f"live agent must not be built for {config}")

    original_parse = evaluate.parse_args_to_config

    def parse_with_fake_worker(argv: list[str] | None) -> tuple[EvaluationConfig, Path]:
        config, fixtures = original_parse(argv)
        return config.model_copy(update={"worker_module": "fake_laya_child"}), fixtures

    monkeypatch.setattr(evaluate, "build_live_agent", no_live_agent)
    monkeypatch.setattr(evaluate, "parse_args_to_config", parse_with_fake_worker)
    assert evaluate.main(_argv(tmp_path, "--scenario", "routing")) == 3
    report = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert report["status"] == "incomplete"
    assert any("--live not requested" in limitation for limitation in report["limitations"])
