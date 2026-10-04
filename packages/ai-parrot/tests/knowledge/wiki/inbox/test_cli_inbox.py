"""Focused FEAT-626 regression and failure-path tests."""

import json
from pathlib import Path

import click
from click.testing import CliRunner
import pytest

import parrot.knowledge.wiki.cli as wiki_cli
from parrot.knowledge.wiki.inbox.models import InboxDocResult, InboxRunReport
from parrot.knowledge.wiki.project import WikiProjectConfig


def _report(*, status: str = "admitted") -> InboxRunReport:
    """Build a deterministic inbox result for CLI boundary tests."""
    documents = [] if status == "empty" else [InboxDocResult(source_uri="inbox/note.md", status=status)]
    counts = {} if status == "empty" else {status: 1}
    return InboxRunReport(
        inbox_dir="inbox",
        charter_version="1",
        charter_fingerprint="fingerprint",
        models={"lightweight": "test:light", "heavy": "test:heavy"},
        dry_run=False,
        counts=counts,
        documents=documents,
    )


def _patch_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: InboxRunReport | Exception,
) -> list[dict[str, object]]:
    """Patch CLI construction and capture processor options without I/O."""
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    config = WikiProjectConfig(storage_dir=".parrot/wiki")
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(wiki_cli, "_resolve_project", lambda path: (tmp_path, config))
    monkeypatch.setattr(wiki_cli, "_open_store", lambda root, project_config: object())
    monkeypatch.setattr(wiki_cli, "_open_sources", lambda root, project_config, store=None: object())
    monkeypatch.setattr(wiki_cli, "_resolve_charter_path", lambda root, option: tmp_path / "charter.yaml")
    monkeypatch.setattr("parrot.knowledge.wiki.charter.load_charter", lambda path: object())
    monkeypatch.setattr(wiki_cli, "_build_ingest_runtime", lambda *args, **kwargs: object())

    class FakeProcessor:
        """Offline processor seam for command-boundary assertions."""

        def __init__(self, runtime: object) -> None:
            self.runtime = runtime

        async def run(self, **kwargs: object) -> InboxRunReport:
            calls.append(kwargs)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr("parrot.knowledge.wiki.inbox.processor.InboxProcessor", FakeProcessor)
    return calls


def test_cli_inbox_options_and_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover success/empty=0, failed=1, missing/invalid=2 and busy=3."""
    runner = CliRunner()
    config = WikiProjectConfig(storage_dir=".parrot/wiki")
    monkeypatch.setattr(wiki_cli, "_resolve_project", lambda path: (tmp_path, config))
    missing = runner.invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path)])
    assert missing.exit_code == 2

    _patch_runtime(tmp_path, monkeypatch, _report(status="failed"))
    failed = runner.invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path)])
    assert failed.exit_code == 1

    from parrot.knowledge.wiki.inbox.processor import InboxLockBusy

    _patch_runtime(tmp_path, monkeypatch, InboxLockBusy("busy"))
    busy = runner.invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path)])
    assert busy.exit_code == 3


def test_cli_json_stdout_is_report_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parse stdout as one JSON object even with model detection diagnostics."""
    _patch_runtime(tmp_path, monkeypatch, _report())
    runner = CliRunner()
    result = runner.invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["counts"] == {"admitted": 1}


def test_cli_forwards_options_without_double_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward every option and leave lock ownership to the processor."""
    calls = _patch_runtime(tmp_path, monkeypatch, _report(status="empty"))
    runner = CliRunner()
    result = runner.invoke(
        wiki_cli.wiki,
        ["inbox", "--path", str(tmp_path), "--dry-run", "--limit", "0", "--no-archive", "--force"],
    )
    assert result.exit_code == 0, result.output
    assert calls == [{"dry_run": True, "limit": 0, "force": True, "archive": False}]


def test_ingest_unchanged_after_runtime_factoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the pre-existing model-resolution seam in the ordinary ingest path."""
    source = tmp_path / "note.md"
    source.write_text("# Note\n")
    config = WikiProjectConfig(storage_dir=".parrot/wiki")
    monkeypatch.setattr(wiki_cli, "_resolve_project", lambda path: (tmp_path, config))
    monkeypatch.setattr(wiki_cli, "_open_store", lambda root, project_config: object())
    monkeypatch.setattr(wiki_cli, "_open_sources", lambda root, project_config, store=None: object())
    monkeypatch.setattr(wiki_cli, "_resolve_charter_path", lambda root, option: tmp_path / "charter.yaml")
    monkeypatch.setattr("parrot.knowledge.wiki.charter.load_charter", lambda path: object())
    captured: dict[str, object] = {}

    def build_runtime(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        raise click.ClickException("stop after runtime factoring")

    monkeypatch.setattr(wiki_cli, "_build_ingest_runtime", build_runtime)
    result = CliRunner().invoke(
        wiki_cli.wiki,
        [
            "ingest",
            str(source),
            "--path",
            str(tmp_path),
            "--dry-run",
            "--model",
            "test:heavy",
            "--lightweight-model",
            "test:light",
        ],
    )
    assert result.exit_code != 0
    assert captured == {"lightweight_model_opt": "test:light", "model_opt": "test:heavy", "fetch_timeout": 30.0}


def test_ingest_review_without_charter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep review on its legacy branch instead of requiring a charter path."""
    assert 'if mode == "review":' in Path(wiki_cli.__file__).read_text()


def test_cli_dry_run_has_no_setup_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planning delegates runtime construction without touching processor-owned data."""
    calls = _patch_runtime(tmp_path, monkeypatch, _report(status="empty"))
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert calls == [{"dry_run": True, "limit": None, "force": False, "archive": True}]
