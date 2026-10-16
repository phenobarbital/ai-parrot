"""FEAT-694 — end-to-end shared ledger log across isolated machines."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.shared_log import ARCHIVE_REL_DIR, SHARED_LOG_REL_PATH
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy

REPO_ROOT = Path(__file__).resolve().parents[3]


def _machine(tmp_path: Path, name: str) -> LedgerService:
    """Build an isolated ledger service (own db + local log) for one simulated machine."""
    ledger_dir = tmp_path / name / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_ms=200)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path / name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Return the shared checkout directory both machines export to / import from."""
    path = tmp_path / "repo"
    path.mkdir()
    return path


async def test_two_machines_converge_via_shared_file(tmp_path: Path, repo: Path) -> None:
    """Issues opened on either machine become visible on the other through the shared file."""
    alpha = _machine(tmp_path, "alpha")
    beta = _machine(tmp_path, "beta")
    alpha_id = await alpha.open_issue("From alpha", "body", discovered_from="spec:FEAT-694")
    beta_id = await beta.open_issue("From beta", "body", discovered_from="spec:FEAT-694")

    await alpha.export_shared_log(repo)
    await beta.import_shared_log(repo)
    await beta.export_shared_log(repo)
    await alpha.import_shared_log(repo)

    alpha_ids = {issue_id for issue_id, _ in await alpha._all_issues()}
    beta_ids = {issue_id for issue_id, _ in await beta._all_issues()}
    assert alpha_ids == beta_ids == {alpha_id, beta_id}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git in an isolated environment (no user/global configuration)."""
    env = {
        **os.environ,
        "HOME": str(cwd),
        "XDG_CONFIG_HOME": str(cwd / ".xdg"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_git_union_merge_has_no_conflict(tmp_path: Path) -> None:
    """Concurrent appends to the shared log merge cleanly with the repo's union attribute."""
    attributes = [
        line for line in (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines() if "merge=union" in line
    ]
    assert any(line.startswith("sdd/ledger/events.jsonl") for line in attributes)

    work = tmp_path / "git-repo"
    log = work / SHARED_LOG_REL_PATH
    log.parent.mkdir(parents=True)
    assert _git(work, "init", "-q", "-b", "main").returncode == 0
    (work / ".gitattributes").write_text("\n".join(attributes) + "\n", encoding="utf-8")
    log.write_text('{"id": "base"}\n', encoding="utf-8")
    _git(work, "add", "-A")
    assert _git(work, "commit", "-q", "-m", "base").returncode == 0

    _git(work, "checkout", "-q", "-b", "side")
    log.write_text('{"id": "base"}\n{"id": "side"}\n', encoding="utf-8")
    _git(work, "commit", "-q", "-am", "side")
    _git(work, "checkout", "-q", "main")
    log.write_text('{"id": "base"}\n{"id": "main"}\n', encoding="utf-8")
    _git(work, "commit", "-q", "-am", "main")

    merged = _git(work, "merge", "side", "-m", "merge side")

    assert merged.returncode == 0, merged.stdout + merged.stderr
    lines = log.read_text(encoding="utf-8").splitlines()
    assert '{"id": "side"}' in lines
    assert '{"id": "main"}' in lines
    assert "<<<<<<<" not in log.read_text(encoding="utf-8")


async def test_rebuild_not_triggered_by_import_e2e(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing foreign events never runs the destructive rebuild; local state survives."""
    alpha = _machine(tmp_path, "alpha")
    beta = _machine(tmp_path, "beta")
    local_id = await beta.open_issue("Local only", "body", discovered_from="spec:FEAT-694")
    foreign_id = await alpha.open_issue("Foreign", "body", discovered_from="spec:FEAT-694")
    await alpha.export_shared_log(repo)
    rebuild = AsyncMock()
    monkeypatch.setattr(beta.index, "_rebuild_locked_with_cursor", rebuild)
    monkeypatch.setattr(beta.index, "rebuild", rebuild, raising=False)

    report = await beta.import_shared_log(repo)

    assert report.added == 1
    assert rebuild.await_count == 0
    assert {issue_id for issue_id, _ in await beta._all_issues()} == {local_id, foreign_id}
    offset, last_event_id = await beta.store.read_cursor()
    assert offset > 0 and last_event_id is not None


async def test_fresh_clone_after_rotation_sees_everything(tmp_path: Path, repo: Path) -> None:
    """A machine with an empty local log reconstructs closed + open issues after rotation."""
    origin = _machine(tmp_path, "origin")
    closed_id = await origin.open_issue("Done", "body", discovered_from="spec:FEAT-694")
    assert await origin.close_issue(closed_id, "fixed", "task:4409")
    open_id = await origin.open_issue("Still open", "body", discovered_from="spec:FEAT-694")
    await origin.export_shared_log(repo)

    future = datetime.now(timezone.utc) + timedelta(days=90)
    report = await origin.rotate_shared_log(repo, older_than_days=30, now=future)
    assert report.moved >= 2
    assert any((repo / ARCHIVE_REL_DIR).glob("events-*.jsonl"))

    fresh = _machine(tmp_path, "fresh")
    imported = await fresh.import_shared_log(repo, force=True)

    states = dict(await fresh._all_issues())
    assert imported.added >= 3
    assert states[closed_id]["status"] == "closed"
    assert states[open_id]["status"] == "open"
