"""CliRunner tests: env-aware store resolution, build generation, status.

FEAT-461 Module 2 (TASK-2463) — backend precedence (--backend flag >
environment (overlay / WIKI_STORE_BACKEND) > base wiki.json), build's
missing-overlay auto-generation, and the `status` environment header.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import load_project_config

PY_STORE = (
    '"""A tiny key-value store module."""\n\n\n'
    "class Store:\n"
    '    """In-memory key-value store."""\n\n'
    "    def get(self, key):\n"
    '        """Fetch a value."""\n'
    "        return key\n"
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake repository, no .parrot/ yet."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n\nA demo project.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def repo_with_overlays(repo: Path) -> Path:
    """Repo root with a base wiki.json (memory) + wiki.dev.json (sqlite).

    Both backends are local/file-based (no real ArangoDB needed) so
    precedence can be exercised in a fully offline unit test.
    """
    parrot_dir = repo / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "wiki.json").write_text(json.dumps({"backend": "memory"}), encoding="utf-8")
    (parrot_dir / "wiki.dev.json").write_text(json.dumps({"backend": "sqlite"}), encoding="utf-8")
    return repo


def _build(runner: CliRunner, repo: Path, *extra: str):
    result = runner.invoke(wiki, ["build", "--path", str(repo), "--no-git", *extra])
    assert result.exit_code == 0, result.output
    return result


def _wiki_db(repo: Path) -> Path:
    return repo / ".parrot" / "wiki" / "wiki.db"


def _wiki_pages_dir(repo: Path) -> Path:
    return repo / ".parrot" / "wiki" / "pages"


class TestPrecedence:
    def test_flag_beats_overlay(
        self, runner: CliRunner, repo_with_overlays: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        # Overlay says sqlite for dev; an explicit --backend flag must win.
        _build(runner, repo_with_overlays, "--backend", "memory")
        assert _wiki_pages_dir(repo_with_overlays).exists()
        assert not _wiki_db(repo_with_overlays).exists()
        # The base config is untouched by the environment (only the flag).
        assert load_project_config(repo_with_overlays).backend == "memory"

    def test_overlay_beats_base(
        self, runner: CliRunner, repo_with_overlays: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        # No flag: base says memory, dev overlay says sqlite -> overlay wins.
        _build(runner, repo_with_overlays)
        assert _wiki_db(repo_with_overlays).exists()
        # Persisted base config is untouched by the environment/overlay.
        assert load_project_config(repo_with_overlays).backend == "memory"

    def test_wiki_store_backend_env_honoured_in_build(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.setenv("WIKI_STORE_BACKEND", "memory")
        # No overlay yet, no --backend flag: WIKI_STORE_BACKEND now applies
        # to `build` too (previously ignored — cli.py:352 TODO).
        _build(runner, repo)
        assert _wiki_pages_dir(repo).exists()
        assert not _wiki_db(repo).exists()
        # Never persisted to the base config.
        assert load_project_config(repo).backend == "sqlite"

    def test_wiki_store_backend_env_honoured_on_read_path(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`query`'s default project-config path (no `--store`) must also
        honour WIKI_STORE_BACKEND — not just `build` and the `--store`
        branch (review finding: this was previously flag-only)."""
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.setenv("WIKI_STORE_BACKEND", "memory")
        _build(runner, repo)  # builds the memory plane (asserted above)
        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--json"])
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert any("file:pkg/store.py" in r.get("concept_id", "") for r in rows)
        assert load_project_config(repo).backend == "sqlite"  # never persisted


class TestBuildGeneration:
    def test_generates_missing_overlay_for_active_env(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        result = _build(runner, repo)
        overlay_file = repo / ".parrot" / "wiki.prod.json"
        assert overlay_file.exists()
        assert "Generated wiki environment overlay for env 'prod'" in result.output
        data = json.loads(overlay_file.read_text(encoding="utf-8"))
        # Base is untouched (default sqlite) -> mirrored verbatim.
        assert data["backend"] == "sqlite"

    def test_never_clobbers_existing_overlay(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        parrot_dir = repo / ".parrot"
        parrot_dir.mkdir()
        overlay_file = parrot_dir / "wiki.prod.json"
        sentinel = {"backend": "memory"}
        overlay_file.write_text(json.dumps(sentinel), encoding="utf-8")
        result = _build(runner, repo)
        assert "Generated wiki environment overlay" not in result.output
        assert json.loads(overlay_file.read_text(encoding="utf-8")) == sentinel

    def test_flag_not_frozen_into_generated_overlay(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ephemeral WIKI_STORE_BACKEND override never reaches the overlay.

        Unlike an explicit ``--backend`` flag (which *is* persisted to the
        base config by design — matching pre-FEAT-461 behavior — and so
        legitimately flows into a freshly generated overlay, since the
        overlay must stay consistent with whatever base just committed),
        ``WIKI_STORE_BACKEND`` is never written to the base config. The
        generated overlay must reflect the (unaffected) persisted base,
        not this one-off environment override.
        """
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.setenv("WIKI_STORE_BACKEND", "memory")
        _build(runner, repo)  # no --backend flag
        overlay_file = repo / ".parrot" / "wiki.prod.json"
        data = json.loads(overlay_file.read_text(encoding="utf-8"))
        assert data["backend"] == "sqlite"  # base default, NOT "memory"
        assert load_project_config(repo).backend == "sqlite"  # never persisted

    def test_explicit_backend_flag_flows_into_generated_overlay(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit --backend flag *is* persisted to base — and so it
        is what a freshly generated overlay for a non-local env mirrors,
        keeping the two files consistent with each other."""
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        _build(runner, repo, "--backend", "memory")
        overlay_file = repo / ".parrot" / "wiki.prod.json"
        data = json.loads(overlay_file.read_text(encoding="utf-8"))
        assert data["backend"] == "memory"
        assert load_project_config(repo).backend == "memory"


class TestReadPaths:
    def test_read_commands_never_write_overlays(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("WIKI_ENV", raising=False)
        _build(runner, repo)  # local overlay auto-generated here
        monkeypatch.setenv("ENV", "prod")
        overlay_file = repo / ".parrot" / "wiki.prod.json"
        assert not overlay_file.exists()
        result = runner.invoke(wiki, ["query", "store", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert not overlay_file.exists()

    def test_status_env_header_base_fallback(
        self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("WIKI_ENV", raising=False)
        _build(runner, repo)  # local overlay auto-generated
        monkeypatch.setenv("ENV", "prod")
        result = runner.invoke(wiki, ["status", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "Env       : prod (base (no overlay))" in result.output
        assert not (repo / ".parrot" / "wiki.prod.json").exists()

    def test_status_env_header_with_overlay(
        self, runner: CliRunner, repo_with_overlays: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        result = runner.invoke(wiki, ["status", "--path", str(repo_with_overlays)])
        assert result.exit_code == 0, result.output
        overlay_file = repo_with_overlays / ".parrot" / "wiki.dev.json"
        assert f"Env       : dev ({overlay_file})" in result.output


class TestNsAddWritesBaseNotEffective:
    def test_ns_add_never_bakes_overlay_into_base_config(
        self, runner: CliRunner, repo_with_overlays: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review finding: `ns_add` resolved its config via `_resolve_project`
        (the effective/env-merged one) even though it mutates and
        re-persists the BASE config — an active overlay's backend would
        otherwise get baked permanently into `.parrot/wiki.json` just by
        registering a namespace."""
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.delenv("WIKI_ENV", raising=False)
        # repo_with_overlays: base backend="memory", dev overlay backend="sqlite".
        assert load_project_config(repo_with_overlays).backend == "memory"
        added = runner.invoke(
            wiki,
            [
                "ns", "add", "other",
                "--project", str(repo_with_overlays.parent),
                "--path", str(repo_with_overlays),
            ],
        )
        assert added.exit_code == 0, added.output
        base_after = load_project_config(repo_with_overlays)
        assert base_after.backend == "memory"  # untouched by the dev overlay
        assert "other" in base_after.namespaces
