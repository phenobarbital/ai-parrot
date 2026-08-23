"""End-to-end namespace scenarios (FEAT-450).

Drives the real ``wikitoolkit`` commands with ``CliRunner`` over temp
projects and a temp Obsidian vault — no mocks, no LLM. Every test runs
under an isolated ``PARROT_HOME`` (autouse fixture in ``conftest.py``),
so the developer's real ``~/.parrot/wikis.json`` is never touched.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.federation import FederatedWikiStore
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
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


def _build(runner: CliRunner, root: Path, *extra: str) -> None:
    result = runner.invoke(
        wiki, ["build", "--path", str(root), "--no-git", *extra]
    )
    assert result.exit_code == 0, result.output


@pytest.fixture
def repo(tmp_path: Path, runner: CliRunner) -> Path:
    """A built code project."""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    (root / "README.md").write_text("# Demo\n\nA demo project.", encoding="utf-8")
    _build(runner, root)
    return root


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A minimal Obsidian vault: .obsidian/ plus two linked notes."""
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "A.md").write_text(
        "# Alpha\n\nA note about zebras that links to [[B]].\n", encoding="utf-8"
    )
    (root / "B.md").write_text("# Beta\n\n#tag content\n", encoding="utf-8")
    return root


class TestVaultNamespaceEndToEnd:
    """A vault becomes a namespace with no new scanner and no new build path."""

    def test_vault_namespace_end_to_end(self, runner, repo, vault):
        # 1. Build the vault's own plane (inside the vault, Delta 2).
        _build(runner, vault)
        assert (vault / ".parrot" / "wiki" / "wiki.db").exists()

        # 2. Register it as a namespace of the repo.
        added = runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)],
        )
        assert added.exit_code == 0, added.output
        assert load_project_config(repo).namespaces["notes"].kind == "vault"

        # 3. The repo's query now reaches the vault, with qualified ids.
        result = runner.invoke(
            wiki, ["query", "zebras", "--path", str(repo), "--json"]
        )
        assert result.exit_code == 0, result.output
        rows = {row["concept_id"]: row for row in json.loads(result.output)}
        assert "notes::file:A.md" in rows
        assert rows["notes::file:A.md"]["category"] == "document"
        assert rows["notes::file:A.md"]["namespace"] == "notes"

        # 4. The page and its wiki-link edge are readable through the repo.
        page = runner.invoke(
            wiki, ["page", "notes::file:A.md", "--path", str(repo), "--json"]
        )
        assert page.exit_code == 0, page.output
        assert "zebras" in json.loads(page.output)["body"]

        related = runner.invoke(
            wiki, ["related", "notes::file:A.md", "--path", str(repo), "--json"]
        )
        assert related.exit_code == 0, related.output
        assert all(
            row["concept_id"].startswith("notes::")
            for row in json.loads(related.output)
        )

    def test_rebuild_never_ingests_the_vault_plane(self, runner, vault):
        """`.parrot/` is excluded, so a rebuild does not eat its own output."""
        _build(runner, vault)
        log = vault / ".parrot" / "wiki" / "log.md"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("# log\n\nBUILD ...\n", encoding="utf-8")

        _build(runner, vault)
        listing = runner.invoke(
            wiki, ["query", "log", "--path", str(vault), "--json"]
        )
        assert listing.exit_code == 0, listing.output
        ids = {row["concept_id"] for row in json.loads(listing.output)}
        assert not any(".parrot" in i for i in ids)

    def test_ns_add_vault_hints_when_unbuilt(self, runner, repo, vault):
        added = runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)],
        )
        assert added.exit_code == 0, added.output
        assert "wikitoolkit build --path" in added.output

        # ...and the unbuilt namespace is a note, never a failure (G9).
        result = runner.invoke(
            wiki, ["query", "store", "--path", str(repo)]
        )
        assert result.exit_code == 0, result.output
        assert "skipped: unbuilt" in result.output
        assert "file:pkg/store.py" in result.output


class TestPrecedenceWithNamespaces:
    """The `--store > --path > WIKI_STORE > project` chain is unchanged."""

    def test_explicit_path_beats_env_with_namespaces(
        self, runner, repo, vault, monkeypatch
    ):
        _build(runner, vault)
        runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)],
        )
        monkeypatch.setenv("WIKI_STORE", str(repo / "nowhere"))
        result = runner.invoke(
            wiki, ["query", "store", "--path", str(repo), "--json"]
        )
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert "file:pkg/store.py" in ids

    def test_store_flag_never_federates(self, runner, repo, vault):
        _build(runner, vault)
        runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)],
        )
        result = runner.invoke(
            wiki,
            [
                "query", "store", "--json",
                "--store", str(load_project_config(repo).storage_path(repo)),
            ],
        )
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert ids and all("::" not in i for i in ids)


class TestQueryJsonShape:
    """Every row carries its namespace; local rows stay unprefixed (U3)."""

    def test_query_json_rows_carry_namespace(self, runner, repo, vault):
        _build(runner, vault)
        runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)],
        )
        result = runner.invoke(
            wiki, ["query", "a", "--path", str(repo), "--json", "--top-k", "50"]
        )
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert rows
        for row in rows:
            assert "namespace" in row
            if row["namespace"] is None:
                assert "::" not in row["concept_id"]
            else:
                assert row["concept_id"].startswith(f"{row['namespace']}::")
            assert 0.0 <= row["score"] <= 1.0


class TestMCPEndToEnd:
    """The MCP server serves the same federation the CLI does."""

    def test_mcp_server_injects_federated_store(self, runner, repo, vault):
        _build(runner, vault)
        runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)],
        )
        server = create_wiki_mcp_server(repo)
        store = server.tools["wiki_query"].tool._store
        assert isinstance(store, FederatedWikiStore)
        assert set(store.namespaces) == {"notes"}
        assert "notes" in server.config.description


class TestGlobalRegistryEndToEnd:
    """A namespace registered globally is visible from any project."""

    def test_global_namespace_is_readable_and_removable(
        self, runner, repo, vault, isolated_parrot_home
    ):
        _build(runner, vault)
        added = runner.invoke(
            wiki,
            [
                "ns", "add", "notes", "--vault", str(vault),
                "--global", "--path", str(repo),
            ],
        )
        assert added.exit_code == 0, added.output
        registry = json.loads(
            (isolated_parrot_home / "wikis.json").read_text(encoding="utf-8")
        )
        assert registry["namespaces"]["notes"]["vault"] == str(vault)
        # Nothing was written to the repo config (U1).
        assert load_project_config(repo).namespaces == {}

        result = runner.invoke(
            wiki, ["query", "zebras", "--path", str(repo), "--json"]
        )
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert "notes::file:A.md" in ids

        removed = runner.invoke(
            wiki, ["ns", "remove", "notes", "--global", "--path", str(repo)]
        )
        assert removed.exit_code == 0, removed.output
        after = runner.invoke(
            wiki, ["query", "zebras", "--path", str(repo), "--json"]
        )
        ids = {row["concept_id"] for row in json.loads(after.output)}
        assert not any(i.startswith("notes::") for i in ids)


class TestReadOnlyGuarantee:
    """Reading a foreign namespace leaves its plane byte-identical (G5)."""

    def test_foreign_plane_is_untouched_by_reads(self, runner, repo, vault):
        _build(runner, vault)
        runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(vault), "--path", str(repo)],
        )
        plane = vault / ".parrot" / "wiki" / "wiki.db"
        # Quiesce the plane first. `build`'s aiosqlite connection closes on
        # a worker thread, and that close checkpoints the WAL into the main
        # file — snapshotting before it lands would race a change this test
        # has nothing to do with. A checkpointed plane is also exactly the
        # state the no-sidecar guarantee is specified for.
        with contextlib.closing(sqlite3.connect(str(plane))) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ("-wal", "-shm"):
            plane.with_name(plane.name + suffix).unlink(missing_ok=True)

        before = (plane.stat().st_mtime_ns, plane.stat().st_size)
        sidecars_before = sorted(
            p.name for p in plane.parent.iterdir() if p.name.startswith("wiki.db")
        )

        for args in (
            ["query", "zebras", "--path", str(repo), "--json"],
            ["page", "notes::file:A.md", "--path", str(repo), "--json"],
            ["related", "notes::file:A.md", "--path", str(repo), "--json"],
            ["status", "--path", str(repo), "--json"],
        ):
            result = runner.invoke(wiki, args)
            assert result.exit_code == 0, result.output

        assert (plane.stat().st_mtime_ns, plane.stat().st_size) == before
        assert sorted(
            p.name for p in plane.parent.iterdir() if p.name.startswith("wiki.db")
        ) == sidecars_before == ["wiki.db"]
