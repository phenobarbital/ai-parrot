"""FEAT-758 M6 — end-to-end CLI acceptance for the durable ledger outbox."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.claude_code.installer import _install_ledger_hooks
from parrot.knowledge.wiki.cli import ledger
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.service import LedgerService


def _git(cwd: Path, *args: str) -> str:
    """Run one bounded test-only Git command and return standard output."""
    result = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def _cli(*args: str) -> object:
    """Invoke the ledger CLI exactly as an operator would."""
    return CliRunner().invoke(ledger, list(args))


def _open_issue(ledger_dir: Path, title: str) -> str:
    """Append one shareable event to an explicit private journal."""
    return asyncio.run(
        LedgerService.from_dir(ledger_dir).open_issue(
            title, "acceptance fixture", discovered_from="spec:FEAT-758", actor="agent:acceptance"
        )
    )


def _result_json(result: object) -> dict[str, object]:
    """Decode a successful JSON CLI result."""
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _prepare(repo_root: Path, ledger_dir: Path) -> dict[str, object]:
    """Seal the current private journal through the public CLI."""
    return _result_json(
        _cli("outbox", "prepare", "--repo-root", str(repo_root), "--ledger-dir", str(ledger_dir), "--json")
    )


def _integrate(repo_root: Path, ledger_dir: Path) -> list[dict[str, object]]:
    """Deliver every pending batch through the public CLI."""
    result = _cli("outbox", "integrate", "--repo-root", str(repo_root), "--ledger-dir", str(ledger_dir), "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _remote_events(repo_root: Path) -> list[dict[str, object]]:
    """Read the canonical event log from the fetched private origin."""
    content = _git(repo_root, "show", "origin/dev:sdd/ledger/events.jsonl")
    return [json.loads(line) for line in content.splitlines() if line]


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every CLI invocation local to the test's private repositories."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))


@pytest.fixture
def origin_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    """Create a private bare origin with synchronized ``dev`` and ``main`` branches."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=dev", str(origin)], check=True, capture_output=True, timeout=30
    )
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", str(origin), str(seed))
    _git(seed, "config", "user.name", "Ledger Acceptance")
    _git(seed, "config", "user.email", "ledger@example.test")
    (seed / "sdd" / "ledger").mkdir(parents=True)
    (seed / "sdd" / "ledger" / "events.jsonl").write_text("", encoding="utf-8")
    (seed / "sdd" / "ledger" / "issues.jsonl").write_text("", encoding="utf-8")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md", "sdd/ledger/events.jsonl", "sdd/ledger/issues.jsonl")
    _git(seed, "commit", "-m", "seed ledger")
    _git(seed, "push", "origin", "dev")
    _git(seed, "branch", "main")
    _git(seed, "push", "origin", "main")
    primary = tmp_path / "primary"
    _git(tmp_path, "clone", str(origin), str(primary))
    _git(primary, "config", "user.name", "Ledger Acceptance")
    _git(primary, "config", "user.email", "ledger@example.test")
    _git(primary, "fetch", "origin")
    return origin, primary


def test_two_linked_worktrees_findings_never_enter_feature_diffs(
    origin_and_clone: tuple[Path, Path], tmp_path: Path
) -> None:
    """Two feature worktrees share private findings without canonical ledger diffs."""
    _, primary = origin_and_clone
    ledger_dir = tmp_path / "private-ledger"
    first = tmp_path / "feature-one"
    second = tmp_path / "feature-two"
    _git(primary, "worktree", "add", "-b", "feature-one", str(first), "dev")
    _git(primary, "worktree", "add", "-b", "feature-two", str(second), "dev")
    first_issue = _open_issue(ledger_dir, "first linked finding")
    second_issue = _open_issue(ledger_dir, "second linked finding")
    for worktree, filename in ((first, "one.txt"), (second, "two.txt")):
        (worktree / filename).write_text(filename, encoding="utf-8")
        _git(worktree, "add", filename)
        _git(worktree, "commit", "-m", f"add {filename}")
        assert not any(path.startswith("sdd/ledger/") for path in _git(worktree, "diff", "--name-only", "origin/dev...HEAD").splitlines())
    _prepare(primary, ledger_dir)
    reports = _integrate(primary, ledger_dir)
    assert reports[0]["status"] == "delivered"
    assert {event["subject"] for event in _remote_events(primary)} >= {first_issue, second_issue}


def test_new_event_after_seal_waits_for_next_pass(origin_and_clone: tuple[Path, Path], tmp_path: Path) -> None:
    """An event appended after preparation stays unsealed until the next pass."""
    _, primary = origin_and_clone
    ledger_dir = tmp_path / "private-ledger"
    first_issue = _open_issue(ledger_dir, "sealed finding")
    first_batch = _prepare(primary, ledger_dir)["batch"]
    second_issue = _open_issue(ledger_dir, "later finding")
    first_reports = _integrate(primary, ledger_dir)
    status = _result_json(_cli("outbox", "status", "--repo-root", str(primary), "--ledger-dir", str(ledger_dir), "--json"))
    assert first_reports[0]["batch_id"] == first_batch["batch_id"]
    assert status["unsealed_events"] == 1
    assert {event["subject"] for event in _remote_events(primary)} >= {first_issue}
    assert second_issue not in {event["subject"] for event in _remote_events(primary)}
    _prepare(primary, ledger_dir)
    _integrate(primary, ledger_dir)
    assert {event["subject"] for event in _remote_events(primary)} >= {first_issue, second_issue}


def test_feature_worktree_removed_externally_batch_still_deliverable(
    origin_and_clone: tuple[Path, Path], tmp_path: Path
) -> None:
    """A batch sealed from a linked worktree remains deliverable after removal."""
    _, primary = origin_and_clone
    ledger_dir = tmp_path / "private-ledger"
    worktree = tmp_path / "removed-feature"
    _git(primary, "worktree", "add", "-b", "removed-feature", str(worktree), "dev")
    issue_id = _open_issue(ledger_dir, "removed worktree finding")
    _prepare(worktree, ledger_dir)
    _git(primary, "worktree", "remove", "--force", str(worktree))
    reports = _integrate(primary, ledger_dir)
    assert reports[0]["status"] == "delivered"
    assert issue_id in {event["subject"] for event in _remote_events(primary)}


def test_hotfix_on_main_delivers_only_to_dev(origin_and_clone: tuple[Path, Path], tmp_path: Path) -> None:
    """A hotfix source branch leaves ``origin/main`` unchanged while delivery targets dev."""
    _, primary = origin_and_clone
    ledger_dir = tmp_path / "private-ledger"
    main_before = _git(primary, "rev-parse", "origin/main")
    _git(primary, "checkout", "-b", "hotfix", "origin/main")
    issue_id = _open_issue(ledger_dir, "hotfix finding")
    _prepare(primary, ledger_dir)
    reports = _integrate(primary, ledger_dir)
    assert reports[0]["status"] == "delivered"
    assert _git(primary, "rev-parse", "origin/main") == main_before
    assert issue_id in {event["subject"] for event in _remote_events(primary)}


def test_foreign_remote_event_survives_snapshot_regeneration(
    origin_and_clone: tuple[Path, Path], tmp_path: Path
) -> None:
    """A foreign canonical event is retained when a local batch rebuilds the snapshot."""
    origin, primary = origin_and_clone
    foreign = tmp_path / "foreign"
    _git(tmp_path, "clone", str(origin), str(foreign))
    _git(foreign, "config", "user.name", "Foreign Ledger")
    _git(foreign, "config", "user.email", "foreign@example.test")
    foreign_ledger = tmp_path / "foreign-ledger"
    foreign_issue = _open_issue(foreign_ledger, "foreign finding")
    (foreign / "sdd" / "ledger" / "events.jsonl").write_bytes((foreign_ledger / "events.jsonl").read_bytes())
    _git(foreign, "add", "sdd/ledger/events.jsonl")
    _git(foreign, "commit", "-m", "publish foreign event")
    _git(foreign, "push", "origin", "dev")
    ledger_dir = tmp_path / "private-ledger"
    _open_issue(ledger_dir, "local finding")
    _prepare(primary, ledger_dir)
    _integrate(primary, ledger_dir)
    snapshot = _git(primary, "show", "origin/dev:sdd/ledger/issues.jsonl")
    assert foreign_issue in {json.loads(line)["issue_id"] for line in snapshot.splitlines() if line}


def test_mixed_archive_and_current_log_no_rotation(origin_and_clone: tuple[Path, Path], tmp_path: Path) -> None:
    """Archive bytes survive delivery when its event is duplicated in the current log."""
    _, primary = origin_and_clone
    archive_event = LedgerEvent(
        kind="insight.recorded", subject="spec:archive", actor="agent:acceptance", ts="2026-10-27T00:00:01+00:00",
        payload={"fact": "archive", "title": "archive", "derived_from": "spec:FEAT-758"},
    )
    line = json.dumps(archive_event.model_dump(), sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    archive = primary / "sdd" / "ledger" / "archive" / "events-2026_09.jsonl"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(line)
    (primary / "sdd" / "ledger" / "events.jsonl").write_bytes(line)
    _git(primary, "add", "sdd/ledger/archive/events-2026_09.jsonl", "sdd/ledger/events.jsonl")
    _git(primary, "commit", "-m", "add historical archive")
    _git(primary, "push", "origin", "dev")
    archive_before = _git(primary, "show", "origin/dev:sdd/ledger/archive/events-2026_09.jsonl").encode("utf-8") + b"\n"
    ledger_dir = tmp_path / "private-ledger"
    _open_issue(ledger_dir, "current finding")
    _prepare(primary, ledger_dir)
    reports = _integrate(primary, ledger_dir)
    assert reports[0]["status"] == "delivered"
    archive_after = _git(primary, "show", "origin/dev:sdd/ledger/archive/events-2026_09.jsonl").encode("utf-8") + b"\n"
    assert archive_after == archive_before


def test_stale_hook_cannot_stage_events(origin_and_clone: tuple[Path, Path]) -> None:
    """The obsolete staging CLI fails, then installation upgrades the managed hook block."""
    _, primary = origin_and_clone
    hook = primary / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n# >>> parrot-ledger >>>\nwikitoolkit ledger export-log --stage --quiet\n# <<< parrot-ledger <<<\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    result = _cli("export-log", "--repo-root", str(primary), "--stage", "--quiet")
    assert result.exit_code == 4
    assert _git(primary, "diff", "--cached", "--name-only") == ""
    _install_ledger_hooks(primary)
    upgraded = hook.read_text(encoding="utf-8")
    assert "Intentionally a no-op" in upgraded
    assert "export-log --stage" not in upgraded
