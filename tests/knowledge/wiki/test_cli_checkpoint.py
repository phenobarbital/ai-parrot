"""FEAT-557 — which CLI commands checkpoint, and busy soft-skip in upsert."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki import cli as cli_module
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiStoreBusy

PY_STORE = '"""A tiny key-value store module."""\n\n\nclass Store:\n    """In-memory key-value store."""\n\n    def get(self, key):\n        """Fetch a value."""\n        return key\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake repository."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _build(runner: CliRunner, repo: Path, *extra: str):
    result = runner.invoke(wiki, ["build", "--path", str(repo), "--no-git", *extra])
    assert result.exit_code == 0, result.output
    return result


class TestCheckpointCallSites:
    def test_build_checkpoints(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A successful build folds the WAL back (AC-7)."""
        calls: list[str] = []
        monkeypatch.setattr(cli_module, "_checkpoint_if_sqlite", lambda store, label: calls.append(label))
        _build(runner, repo)
        assert calls == ["build"]

    def test_ingest_checkpoints(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A successful ingest folds the WAL back (AC-7)."""
        from parrot.knowledge.wiki.review import ManifestReader

        calls: list[str] = []
        monkeypatch.setattr(cli_module, "_checkpoint_if_sqlite", lambda store, label: calls.append(label))

        # Reuse the project's existing stub-ingest wiring machinery from
        # test_cli.py rather than duplicating it: the fake triage adapters,
        # novelty scorer and PageIndexToolkit stub live there.
        import tests.knowledge.wiki.test_cli as cli_tests

        light = cli_tests._FakeTriageAdapter()
        heavy = cli_tests._FakeTriageAdapter()
        monkeypatch.setattr(
            cli_module, "_build_triage_adapters", lambda lightweight_model, model: (light, heavy, "fake-light", True)
        )
        monkeypatch.setattr(
            cli_module, "_build_novelty_scorer", lambda root, config, store: cli_tests._FakeNoveltyScorer()
        )
        monkeypatch.setattr(cli_tests._pageindex_toolkit, "PageIndexToolkit", cli_tests._FakePageIndexToolkit)
        monkeypatch.setenv("WIKI_LIGHTWEIGHT_MODEL", "stub:light")
        monkeypatch.setenv("WIKI_MODEL", "stub:heavy")

        charter_dir = repo / ".parrot"
        charter_dir.mkdir(parents=True, exist_ok=True)
        charter_path = charter_dir / "charter.yaml"
        charter_path.write_text(cli_tests._CHARTER_YAML, encoding="utf-8")

        docs = repo.parent / "docs"
        docs.mkdir()
        (docs / "decision.md").write_text(
            "# Migration decision\n\nWe decided to migrate the graph store.",
            encoding="utf-8",
        )

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs),
                "--path",
                str(repo),
                "--charter",
                str(charter_path),
                "--auto",
            ],
        )
        assert result.exit_code == 0, result.output
        assert calls == ["ingest"]
        # Sanity: it really did apply (not skip everything as dry-run would).
        _header, entries = ManifestReader(repo / ".parrot" / "wiki" / "ingest-manifest.jsonl").read()
        assert all(e.decision == e.proposed_action for e in entries)

    def test_upsert_does_not_checkpoint(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`upsert --changed` must NOT checkpoint (spec §1 non-goal)."""
        calls: list[str] = []
        _build(runner, repo)
        monkeypatch.setattr(cli_module, "_checkpoint_if_sqlite", lambda store, label: calls.append(label))
        (repo / "pkg" / "store.py").write_text(PY_STORE + "\n# v2\n", encoding="utf-8")
        result = runner.invoke(wiki, ["upsert", "pkg/store.py", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert calls == []

    def test_checkpoint_call_site_policy_end_to_end(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The three-way contract in one place (AC-7 / TASK-3226): `build` and
        `ingest` checkpoint, `upsert --changed` does not (spec §1 non-goal)."""
        from parrot.knowledge.wiki.review import ManifestReader

        import tests.knowledge.wiki.test_cli as cli_tests

        calls: list[str] = []
        monkeypatch.setattr(cli_module, "_checkpoint_if_sqlite", lambda store, label: calls.append(label))

        # 1. `build` checkpoints.
        _build(runner, repo)
        assert calls == ["build"]

        # 2. `ingest` checkpoints.
        light = cli_tests._FakeTriageAdapter()
        heavy = cli_tests._FakeTriageAdapter()
        monkeypatch.setattr(
            cli_module, "_build_triage_adapters", lambda lightweight_model, model: (light, heavy, "fake-light", True)
        )
        monkeypatch.setattr(
            cli_module, "_build_novelty_scorer", lambda root, config, store: cli_tests._FakeNoveltyScorer()
        )
        monkeypatch.setattr(cli_tests._pageindex_toolkit, "PageIndexToolkit", cli_tests._FakePageIndexToolkit)
        monkeypatch.setenv("WIKI_LIGHTWEIGHT_MODEL", "stub:light")
        monkeypatch.setenv("WIKI_MODEL", "stub:heavy")

        charter_dir = repo / ".parrot"
        charter_dir.mkdir(parents=True, exist_ok=True)
        charter_path = charter_dir / "charter.yaml"
        charter_path.write_text(cli_tests._CHARTER_YAML, encoding="utf-8")

        # A distinct dirname (not "docs") — `repo.parent` is the shared pytest
        # session tmp base, and `test_ingest_checkpoints` already claims "docs"
        # there; colliding on the same name breaks whichever test runs second.
        docs = repo.parent / "docs-combined"
        docs.mkdir()
        (docs / "decision.md").write_text(
            "# Migration decision\n\nWe decided to migrate the graph store.",
            encoding="utf-8",
        )

        result = runner.invoke(
            wiki,
            ["ingest", str(docs), "--path", str(repo), "--charter", str(charter_path), "--auto"],
        )
        assert result.exit_code == 0, result.output
        assert calls == ["build", "ingest"]
        _header, entries = ManifestReader(repo / ".parrot" / "wiki" / "ingest-manifest.jsonl").read()
        assert all(e.decision == e.proposed_action for e in entries)

        # 3. `upsert --changed` does NOT checkpoint.
        (repo / "pkg" / "store.py").write_text(PY_STORE + "\n# v2\n", encoding="utf-8")
        result = runner.invoke(wiki, ["upsert", "pkg/store.py", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert calls == ["build", "ingest"]

    def test_checkpoint_failure_does_not_fail_build(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raising checkpoint still leaves exit code 0 (AC-7).

        Exercises the REAL `_checkpoint_if_sqlite` (not a stub for it) by
        making the underlying `SQLiteWikiStore.checkpoint()` itself raise
        — proving the helper's own swallow-and-log behaviour, not just
        that it was bypassed.
        """

        async def _boom(self: SQLiteWikiStore, truncate: bool = True) -> dict:
            raise RuntimeError("disk exploded")

        monkeypatch.setattr(SQLiteWikiStore, "checkpoint", _boom)
        result = runner.invoke(wiki, ["build", "--path", str(repo), "--no-git"])
        assert result.exit_code == 0, result.output


class TestCheckpointHelper:
    """Unit tests for `_checkpoint_if_sqlite` itself (the belt-and-braces layer)."""

    def test_swallows_a_raising_checkpoint(self) -> None:
        """A raising checkpoint() call is caught and logged, never re-raised (AC-7)."""

        class _BoomStore(SQLiteWikiStore):
            async def checkpoint(self, truncate: bool = True) -> dict:
                raise RuntimeError("disk exploded")

        store = _BoomStore.__new__(_BoomStore)
        cli_module._checkpoint_if_sqlite(store, "test")  # must not raise

    def test_non_sqlite_backend_is_skipped(self) -> None:
        """A memory/arango store has no checkpoint(); the guard handles it."""

        class _NotSqlite:
            pass

        cli_module._checkpoint_if_sqlite(_NotSqlite(), "test")  # must not raise AttributeError


class TestUpsertBusySoftSkip:
    def test_busy_upsert_is_not_an_error(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """WikiStoreBusy yields exit 0 and an actionable message (AC-8)."""
        _build(runner, repo)

        def _boom(coro: object) -> None:
            coro.close()  # avoid a "coroutine was never awaited" warning
            raise WikiStoreBusy(repo / ".parrot" / "wiki" / "wiki.db", "upsert", 15.0)

        monkeypatch.setattr(cli_module, "_run", _boom)
        result = runner.invoke(wiki, ["upsert", "pkg/store.py", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "busy" in result.output.lower()

    def test_busy_upsert_is_silent_when_quiet(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--quiet` keeps the git hook's output clean."""
        _build(runner, repo)

        def _boom(coro: object) -> None:
            coro.close()  # avoid a "coroutine was never awaited" warning
            raise WikiStoreBusy(repo / ".parrot" / "wiki" / "wiki.db", "upsert", 15.0)

        monkeypatch.setattr(cli_module, "_run", _boom)
        result = runner.invoke(wiki, ["upsert", "pkg/store.py", "--path", str(repo), "--quiet"])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == ""
