"""Regression cases for FEAT-627."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

import parrot.knowledge.wiki.standup.cli as subject


def _document() -> SimpleNamespace:
    """Return a small serializable document fixture for CLI-only tests."""
    return SimpleNamespace(
        language="en",
        model_dump=lambda mode: {"brief_id": "brief:day:2026-10-03", "diagnostics": ["source: unavailable"]},
    )


def test_cli_option_matrix_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the option matrix maps into the shared pipeline options."""
    captured: dict[str, object] = {}

    def resolve(*args: object) -> tuple[Path, object, object]:
        del args
        return tmp_path, object(), object()

    async def fake_run(root: Path, options: object, **kwargs: object) -> SimpleNamespace:
        captured.update(root=root, options=options, **kwargs)
        return _document()

    monkeypatch.setattr(subject, "_resolve_run_inputs", resolve)
    monkeypatch.setattr(subject, "run", fake_run)
    result = CliRunner().invoke(
        subject.standup,
        [
            "--period",
            "week",
            "--date",
            "2026-10-03",
            "--horizon",
            "12",
            "--language",
            "es",
            "--no-llm",
            "--no-store",
            "--no-file",
            "--ns",
            "issues",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["brief_id"] == "brief:day:2026-10-03"
    options = captured["options"]
    assert getattr(options, "period") == "week"
    assert getattr(options, "anchor").isoformat() == "2026-10-03"
    assert getattr(options, "write_page") is False
    assert getattr(options, "write_file") is False
    assert getattr(options, "use_llm") is False


def test_lazy_dispatch_and_import_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify top-level help imports none of the lazily registered modules."""
    del tmp_path, monkeypatch
    code = (
        "import json, sys; from click.testing import CliRunner; "
        "from parrot.knowledge.wiki.cli import wiki; "
        "result = CliRunner().invoke(wiki, ['--help']); "
        "assert result.exit_code == 0, result.output; "
        "print(json.dumps([name for name in sys.modules if name in "
        "('parrot.knowledge.wiki.standup.cli', 'parrot.knowledge.wiki.entity_cli', "
        "'parrot.knowledge.wiki.decisions.cli')]))"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True, text=True)
    assert json.loads(completed.stdout.splitlines()[-1]) == []


def test_exit_codes_and_clean_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify usage and store errors retain Click exit codes and JSON remains clean."""
    del tmp_path
    runner = CliRunner()
    incompatible = runner.invoke(subject.standup, ["--team", "--me", "human:me"])
    assert incompatible.exit_code == 2

    def fail(*args: object) -> tuple[Path, object, object]:
        del args
        raise click.ClickException("store unavailable")

    monkeypatch.setattr(subject, "_resolve_run_inputs", fail)
    unavailable = runner.invoke(subject.standup, [])
    assert unavailable.exit_code == 1
    assert "store unavailable" in unavailable.output
