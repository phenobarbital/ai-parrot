"""CLI tests for `wikitoolkit sync push|pull` (FEAT-461 TASK-2467).

The engine (`sync_push`/`sync_pull`) is mocked/monkeypatched throughout —
its own logic is covered by `tests/knowledge/wiki/test_sync.py`
(TASK-2466). These tests only verify CLI dispatch, summary rendering, and
clean error handling.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.sync import SyncError, SyncReport


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a base wiki.json (build not required — engine is mocked)."""
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot" / "wiki.json").write_text("{}", encoding="utf-8")
    return tmp_path


class TestSyncCli:
    def test_push_dispatches_with_env_and_dry_run(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        async def _fake_sync_push(root, *, target_env, dry_run, local_identity):
            captured.update(
                root=root,
                target_env=target_env,
                dry_run=dry_run,
                local_identity=local_identity,
            )
            return SyncReport(
                direction="push",
                env=target_env,
                created=1,
                updated=2,
                skipped_older=3,
                dry_run=dry_run,
            )

        monkeypatch.setattr("parrot.knowledge.wiki.sync.sync_push", _fake_sync_push)
        result = runner.invoke(
            wiki,
            ["sync", "push", "--path", str(repo), "--env", "prod", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert captured["target_env"] == "prod"
        assert captured["dry_run"] is True
        assert captured["local_identity"].startswith("human:")
        assert "DRY RUN — nothing applied" in result.output
        assert "created=1" in result.output
        assert "updated=2" in result.output
        assert "skipped-older=3" in result.output

    def test_pull_all_maps_to_include_own(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        async def _fake_sync_pull(root, *, target_env, include_own, dry_run, local_identity):
            captured.update(include_own=include_own, target_env=target_env)
            return SyncReport(direction="pull", env=target_env)

        monkeypatch.setattr("parrot.knowledge.wiki.sync.sync_pull", _fake_sync_pull)
        result = runner.invoke(wiki, ["sync", "pull", "--path", str(repo), "--env", "dev", "--all"])
        assert result.exit_code == 0, result.output
        assert captured["include_own"] is True
        assert captured["target_env"] == "dev"

    def test_pull_default_env_and_no_all(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        async def _fake_sync_pull(root, *, target_env, include_own, dry_run, local_identity):
            captured.update(include_own=include_own, target_env=target_env)
            return SyncReport(direction="pull", env=target_env)

        monkeypatch.setattr("parrot.knowledge.wiki.sync.sync_pull", _fake_sync_pull)
        result = runner.invoke(wiki, ["sync", "pull", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert captured["include_own"] is False
        assert captured["target_env"] == "dev"

    def test_summary_rendering(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_sync_pull(root, *, target_env, include_own, dry_run, local_identity):
            return SyncReport(
                direction="pull",
                env=target_env,
                created=4,
                updated=5,
                skipped_older=6,
                skipped_own=7,
            )

        monkeypatch.setattr("parrot.knowledge.wiki.sync.sync_pull", _fake_sync_pull)
        result = runner.invoke(wiki, ["sync", "pull", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "pulled: created=4 updated=5 skipped-older=6 skipped-own=7" in result.output

    def test_unreachable_remote_clean_exit(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_sync_push(root, *, target_env, dry_run, local_identity):
            raise SyncError(f"Could not reach the remote wiki plane for env {target_env!r}")

        monkeypatch.setattr("parrot.knowledge.wiki.sync.sync_push", _fake_sync_push)
        result = runner.invoke(wiki, ["sync", "push", "--path", str(repo), "--env", "prod"])
        assert result.exit_code != 0
        assert "Could not reach" in result.output
        assert "Traceback" not in result.output

    def test_sync_help_documents_env_default_and_author_filter(self, runner: CliRunner) -> None:
        group_help = runner.invoke(wiki, ["sync", "--help"])
        assert group_help.exit_code == 0
        assert "human:" in group_help.output

        push_help = runner.invoke(wiki, ["sync", "push", "--help"])
        assert push_help.exit_code == 0
        assert "dev" in push_help.output

        pull_help = runner.invoke(wiki, ["sync", "pull", "--help"])
        assert pull_help.exit_code == 0
        assert "dev" in pull_help.output
        assert "--all" in pull_help.output
