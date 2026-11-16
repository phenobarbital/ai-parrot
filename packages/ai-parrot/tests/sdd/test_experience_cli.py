"""Deterministic experience-memory CLI regression tests."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.sdd.scripts import experience_cli
from parrot.sdd.scripts.experience_cli import main


def _checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, name: str = "primary") -> Path:
    """Create an isolated checkout and select it as the CLI working directory."""
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    return root


def test_cli_missing_plane_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep an ordinary read against an absent plane silent and non-creating."""
    root = _checkout(tmp_path, monkeypatch)
    task = root / "TASK-1.md"
    task.write_text("# TASK-1: Keep reads quiet\n\n## Files to Create / Modify\n", encoding="utf-8")

    assert main(["brief", "--task-file", str(task)]) == 0
    assert capsys.readouterr().out == ""
    assert not (root / ".parrot" / "experience").exists()


def test_cli_export_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Refresh, graduate, and export in order without invoking global sync."""
    root = _checkout(tmp_path, monkeypatch)
    plane = root / ".parrot" / "experience"
    plane.mkdir(parents=True)
    calls: list[str] = []

    class Service:
        """Minimal service double for the cross-component ordering contract."""

        def __init__(self) -> None:
            self.config = SimpleNamespace(enabled=True)
            self.index = object()
            self.plane_dir = plane
            self.root = root

        async def refresh(self) -> None:
            calls.append("refresh")

    ledger = object()
    monkeypatch.setattr(experience_cli.ExperienceService, "from_root", lambda: Service())
    monkeypatch.setattr(experience_cli.LedgerService, "from_root", lambda path: ledger)

    async def graduate(service: Service, target: object, *, ledger_name: str) -> list[str]:
        assert target is ledger
        assert ledger_name == root.name
        calls.append("graduate")
        return []

    def export_shared(repo_plane: Path, checkout: Path) -> None:
        assert repo_plane == plane
        assert checkout == root
        calls.append("export")

    monkeypatch.setattr(experience_cli, "graduate", graduate)
    monkeypatch.setattr(experience_cli, "export_shared", export_shared)
    monkeypatch.setattr(experience_cli, "sync_global", lambda path: pytest.fail(f"unexpected sync of {path}"))

    assert main(["export"]) == 0
    assert calls == ["refresh", "graduate", "export"]


def test_cli_mutating_verb_warns_when_plane_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep absent-plane mutations successful but make their no-op visible on stderr."""
    _checkout(tmp_path, monkeypatch)

    with caplog.at_level(logging.WARNING, logger=experience_cli.logger.name):
        assert main(["record", "--executable", "gh", "--solution", "use api"]) == 0

    assert capsys.readouterr().out == ""
    assert "experience plane unavailable; record skipped" in caplog.text


def test_cli_export_writes_under_checkout_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass the service checkout root to export even when invoked from a subdirectory."""
    root = _checkout(tmp_path, monkeypatch)
    plane = root / ".parrot" / "experience"
    plane.mkdir(parents=True)
    nested = root / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)

    class Service:
        """Minimal export service rooted at the checkout rather than the current directory."""

        def __init__(self) -> None:
            self.config = SimpleNamespace(enabled=True)
            self.index = object()
            self.plane_dir = plane
            self.root = root

        async def refresh(self) -> None:
            return None

    monkeypatch.setattr(experience_cli.ExperienceService, "from_root", lambda: Service())
    monkeypatch.setattr(experience_cli.LedgerService, "from_root", lambda path: object())

    async def graduate(*args: object, **kwargs: object) -> list[str]:
        return []

    def export_shared(repo_plane: Path, checkout: Path) -> None:
        assert repo_plane == plane
        assert checkout == root

    monkeypatch.setattr(experience_cli, "graduate", graduate)
    monkeypatch.setattr(experience_cli, "export_shared", export_shared)

    assert main(["export"]) == 0


def test_cli_brief_missing_task_file_is_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Return argparse's usage status when a requested briefing file does not exist."""
    root = _checkout(tmp_path, monkeypatch)

    with caplog.at_level(logging.ERROR, logger=experience_cli.logger.name):
        assert main(["brief", "--task-file", str(root / "missing.md")]) == 2

    assert "task file does not exist" in caplog.text


def test_cli_record_list_show_and_retire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise real text/JSON output and the authored lesson lifecycle."""
    _checkout(tmp_path, monkeypatch)
    assert main(["init"]) == 0
    assert (
        main(
            [
                "record",
                "--executable",
                "gh",
                "--subcommand",
                "pr edit",
                "--error",
                "Projects classic",
                "--symptom",
                "GraphQL rejects the request",
                "--solution",
                "Use gh api",
                "--path",
                "src/release.py",
            ]
        )
        == 0
    )
    lesson_id = capsys.readouterr().out.strip()
    assert lesson_id.startswith("pit-")

    assert main(["list", "--json"]) == 0
    lessons = json.loads(capsys.readouterr().out)
    assert [lesson["lesson_id"] for lesson in lessons] == [lesson_id]

    assert main(["show", lesson_id]) == 0
    assert lesson_id in capsys.readouterr().out
    assert main(["retire", lesson_id, "--reason", "obsolete"]) == 0
    assert main(["list", "--state", "retired", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["state"] == "retired"


def test_cli_brief_extracts_task_title_and_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pass only the semantic task title and declared file paths to briefing."""
    root = _checkout(tmp_path, monkeypatch)
    plane = root / ".parrot" / "experience"
    plane.mkdir(parents=True)
    task = root / "TASK-1.md"
    task.write_text(
        "# TASK-1: Repair release command\n\n"
        "## Files to Create / Modify\n\n"
        "| File | Action |\n|---|---|\n"
        "| `src/release.py` | MODIFY |\n| `tests/test_release.py` | MODIFY |\n\n"
        "## Acceptance Criteria\n",
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    class Service:
        """Briefing service double which records parsed task context."""

        def __init__(self) -> None:
            self.config = SimpleNamespace(enabled=True)
            self.index = object()
            self.plane_dir = plane
            self.root = root

        async def refresh(self) -> None:
            return None

        async def brief(self, title: str, files: list[str], *, max_entries: int | None = None) -> str:
            seen.update(title=title, files=files, max_entries=max_entries)
            return "- known pitfall"

    monkeypatch.setattr(experience_cli.ExperienceService, "from_root", lambda: Service())

    assert main(["brief", "--task-file", str(task), "--max", "3"]) == 0
    assert seen == {
        "title": "Repair release command",
        "files": ["src/release.py", "tests/test_release.py"],
        "max_entries": 3,
    }
    assert capsys.readouterr().out == "- known pitfall\n"


def test_cli_disabled_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Honor the configuration kill switch without creating the plane."""
    root = _checkout(tmp_path, monkeypatch, name="disabled")
    (root / ".parrot").mkdir()
    (root / ".parrot" / "wiki.json").write_text('{"experience":{"enabled":false}}', encoding="utf-8")

    assert main(["init"]) == 0
    assert main(["record", "--executable", "gh", "--solution", "use api"]) == 0
    assert not (root / ".parrot" / "experience").exists()
