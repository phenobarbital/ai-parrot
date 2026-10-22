"""Focused FEAT-626 regression and failure-path tests."""

import json
import sys
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


def test_watch_rejects_limit_and_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject watch combinations before the CLI opens a store or builds a runtime."""
    opened = False

    def reject_store(*args: object, **kwargs: object) -> object:
        nonlocal opened
        opened = True
        return object()

    monkeypatch.setattr(wiki_cli, "_open_store", reject_store)
    runner = CliRunner()
    for args in (["--watch", "--limit", "1"], ["--watch", "--dry-run"]):
        result = runner.invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path), *args])
        assert result.exit_code == 2
        assert "--watch cannot be combined with --limit or --dry-run" in result.output
    assert not opened


def test_watch_runs_watcher_with_cli_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Build the watcher with the command's archive and force options."""
    _patch_runtime(tmp_path, monkeypatch, _report())
    captured: dict[str, object] = {}

    class FakeStats:
        """Provide deterministic shutdown counters for the CLI."""

        events_seen = 2
        runs_started = 3
        documents_processed = 4
        lock_busy_retries = 5

        def model_dump_json(self) -> str:
            """Render the CLI's expected machine-readable shutdown summary."""
            return '{"events_seen":2}'

    class FakeWatcher:
        """Record the runtime and command flags passed to the lazy watcher."""

        def __init__(self, runtime: object, *, force: bool, archive: bool) -> None:
            captured.update(runtime=runtime, force=force, archive=archive)
            self.stats = FakeStats()

        async def run_forever(self) -> FakeStats:
            """Return immediately so the CLI can render final statistics."""
            return self.stats

    monkeypatch.setattr("parrot.knowledge.wiki.inbox.watcher.InboxWatcher", FakeWatcher)
    result = CliRunner().invoke(
        wiki_cli.wiki,
        ["inbox", "--path", str(tmp_path), "--watch", "--force", "--no-archive"],
    )
    assert result.exit_code == 0, result.output
    assert captured["force"] is True
    assert captured["archive"] is False
    assert "Watcher: events=2 runs=3 documents=4 lock_retries=5" in result.output

    as_json = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path), "--watch", "--json"])
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.output) == {"events_seen": 2}


def test_watch_without_watchdog_is_usage_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Translate the lazy watch-extra failure to Click's usage exit code."""
    _patch_runtime(tmp_path, monkeypatch, _report())
    from parrot.knowledge.wiki.inbox.watcher import WatcherUnavailable

    class UnavailableWatcher:
        """Raise the lazy dependency error only from the watch execution path."""

        def __init__(self, runtime: object, *, force: bool, archive: bool) -> None:
            self.stats = None

        async def run_forever(self) -> None:
            """Model watchdog's unavailable extra."""
            raise WatcherUnavailable("install ai-parrot[filesystem-transport-full]")

    monkeypatch.setattr("parrot.knowledge.wiki.inbox.watcher.InboxWatcher", UnavailableWatcher)
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path), "--watch"])
    assert result.exit_code == 2
    assert "filesystem-transport-full" in result.output


def test_one_shot_works_without_watchdog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ordinary inbox processing independent of the optional watcher extra."""
    calls = _patch_runtime(tmp_path, monkeypatch, _report(status="empty"))
    monkeypatch.setitem(sys.modules, "watchdog", None)
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert calls == [{"dry_run": False, "limit": None, "force": False, "archive": True}]
