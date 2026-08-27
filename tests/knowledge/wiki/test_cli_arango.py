"""CLI backend-routing tests for the ArangoDB backend (FEAT-400, TASK-2061).

Drives the click commands end-to-end with ``CliRunner`` (same pattern as
``test_cli.py``), but with ``parrot.knowledge.wiki.arango_store.AsyncDB``
patched — no real ArangoDB server is needed.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import load_project_config


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake repository."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(
        '"""A tiny module."""\n\n\ndef fn():\n    """Docstring."""\n    return 1\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n\nA demo project.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_arango_driver():
    """Mocked ``asyncdb`` ArangoDB driver instance (already connected).

    ``_connection`` mocks the underlying ``arangoasync.database.Database``
    directly — ``ArangoDBWikiStore._create_pages_view()`` drives that
    layer's ``views()``/``create_view()`` rather than the installed
    ``asyncdb`` driver's own (buggy against a real server)
    ``create_arangosearch_view()`` wrapper.
    """
    db = MagicMock()
    db.connection = AsyncMock(return_value=db)
    db.close = AsyncMock()
    db.collection_exists = AsyncMock(return_value=False)
    db.create_collection = AsyncMock()
    db.create_arangosearch_view = AsyncMock()
    db.query = AsyncMock(return_value=([], None))
    db.execute = AsyncMock(return_value=([], None))
    db._connection = MagicMock()
    db._connection.views = AsyncMock(return_value=[])
    db._connection.create_view = AsyncMock()
    return db


def _build_arangodb(runner: CliRunner, repo: Path, *extra: str):
    return runner.invoke(
        wiki, ["build", "--path", str(repo), "--no-git", "--backend", "arangodb", *extra]
    )


class TestBuildBackendChoice:
    """``--backend arangodb`` is accepted and routed correctly."""

    def test_build_backend_arangodb_accepted(self, runner, repo, mock_arango_driver):
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            result = _build_arangodb(runner, repo, "--no-graph", "--no-export")
        assert result.exit_code == 0, result.output
        mock_arango_driver.connection.assert_awaited()

    def test_build_backend_arangodb_saved_to_config(
        self, runner, repo, mock_arango_driver
    ):
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            result = _build_arangodb(runner, repo, "--no-graph", "--no-export")
        assert result.exit_code == 0, result.output
        config = load_project_config(repo)
        assert config.backend == "arangodb"

    def test_build_creates_collections_and_view(
        self, runner, repo, mock_arango_driver
    ):
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            result = _build_arangodb(runner, repo, "--no-graph", "--no-export")
        assert result.exit_code == 0, result.output
        mock_arango_driver._connection.create_view.assert_awaited_once()
        assert mock_arango_driver.create_collection.await_count == 5

    def test_sqlite_backend_still_works(self, runner, repo):
        result = runner.invoke(
            wiki,
            ["build", "--path", str(repo), "--no-git", "--no-graph", "--no-export"],
        )
        assert result.exit_code == 0, result.output
        config = load_project_config(repo)
        assert config.backend == "sqlite"


class TestQueryBackendArango:
    """``query --backend arangodb`` resolves via project config."""

    def test_query_backend_arangodb_uses_project_config(
        self, runner, repo, mock_arango_driver
    ):
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            build_result = _build_arangodb(runner, repo, "--no-graph", "--no-export")
            assert build_result.exit_code == 0, build_result.output

            mock_arango_driver.query = AsyncMock(
                return_value=(
                    [
                        {
                            "concept_id": "intro",
                            "node_id": None,
                            "title": "Intro",
                            "category": "concept",
                            "summary": "s",
                            "source_id": None,
                            "token_count": 5,
                            "score": 3.2,
                        }
                    ],
                    None,
                )
            )
            result = runner.invoke(
                wiki,
                [
                    "query",
                    "some question",
                    "--path",
                    str(repo),
                    "--backend",
                    "arangodb",
                    "--json",
                ],
            )
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert rows[0]["concept_id"] == "intro"

    def test_unreachable_arangodb_gives_clear_error(self, runner, repo):
        broken_driver = MagicMock()
        broken_driver.connection = AsyncMock(
            side_effect=RuntimeError("connection refused")
        )
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=broken_driver,
        ):
            # Save an arangodb-backed config first (bypassing a real build).
            from parrot.knowledge.wiki.project import (
                WikiProjectConfig,
                save_project_config,
            )

            save_project_config(
                repo, WikiProjectConfig(wiki_name=repo.name, backend="arangodb")
            )
            result = runner.invoke(
                wiki,
                ["query", "some question", "--path", str(repo), "--backend", "arangodb"],
            )
        assert result.exit_code != 0
        assert "Could not connect to ArangoDB" in result.output


class TestStatusBackendArango:
    """``status`` reports ArangoDB backend + stats after an arangodb build."""

    def test_status_shows_arangodb_backend(
        self, runner, repo, mock_arango_driver, monkeypatch
    ):
        # FEAT-461: with no ENV/WIKI_ENV, `build` auto-generates the missing
        # `local` overlay (`{"backend": "sqlite"}` — the no-VPN default),
        # which `status` (no `--backend` option of its own) would then
        # report instead of the arangodb backend just built. Set an
        # explicit non-local env so the generated overlay mirrors the
        # arangodb base instead.
        monkeypatch.setenv("ENV", "dev")
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            build_result = _build_arangodb(runner, repo, "--no-graph", "--no-export")
            assert build_result.exit_code == 0, build_result.output

            result = runner.invoke(
                wiki, ["status", "--path", str(repo), "--json"]
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["backend"] == "arangodb"
