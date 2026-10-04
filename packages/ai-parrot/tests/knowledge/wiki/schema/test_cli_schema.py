"""CLI coverage for the SQL schema-plane command group."""

from __future__ import annotations

import json

from click.testing import CliRunner

from parrot.knowledge.wiki import cli
from parrot.knowledge.wiki.cli import wiki


def test_group_lists_six_verbs() -> None:
    """The schema group exposes each specified verb."""
    result = CliRunner().invoke(wiki, ["schema", "--help"])
    assert result.exit_code == 0
    assert all(verb in result.output for verb in ("sources", "add-source", "sync", "ingest-ddl", "diff", "lookup"))


def test_write_verbs_refuse_linked_worktree(tmp_path, monkeypatch) -> None:
    """Schema writes do not target shared state from a linked worktree."""
    (tmp_path / ".git").write_text("gitdir: /elsewhere", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    commands = (
        ["schema", "sync", "pg"],
        ["schema", "ingest-ddl", "--origin", "pg", "--dialect", "postgres"],
        ["schema", "diff", "pg", "--ledger"],
    )
    for command in commands:
        result = runner.invoke(wiki, command)
        assert result.exit_code != 0
        assert "linked worktree" in result.output


def test_add_source_refuses_existing_alias(tmp_path, monkeypatch) -> None:
    """Declaring an alias twice preserves an env-name-only configuration."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    command = ["schema", "add-source", "pg", "--dialect", "postgres", "--dsn-env", "POSTGRES_DSN"]
    first = runner.invoke(wiki, command)
    second = runner.invoke(wiki, command)
    assert first.exit_code == 0, first.output
    assert second.exit_code != 0
    assert "pg" in second.output
    config = json.loads((tmp_path / ".parrot" / "wiki.json").read_text(encoding="utf-8"))
    assert config["schema"]["sources"]["pg"]["dsn_env"] == "POSTGRES_DSN"
    assert "postgresql://" not in json.dumps(config)


def test_lookup_ambiguous_prints_candidates(monkeypatch) -> None:
    """An ambiguous short reference is reported instead of guessed."""

    class FakeService:
        async def lookup(self, ref: str) -> list[str]:
            return ["table:a/public.users", "table:b/public.users"]

    monkeypatch.setattr(cli, "_schema_service", lambda: FakeService())
    result = CliRunner().invoke(wiki, ["schema", "lookup", "public.users"])
    assert result.exit_code != 0
    assert "candidates" in result.output
    assert "table:a/public.users" in result.output


def _declare_sources(tmp_path) -> None:
    """Declare one DDL-backed postgres source and one live-only mysql source."""
    runner = CliRunner()
    for alias, dialect in (("pg", "postgres"), ("my", "mysql")):
        result = runner.invoke(wiki, ["schema", "add-source", alias, "--dialect", dialect, "--dsn-env", "DSN"])
        assert result.exit_code == 0, result.output
    path = tmp_path / ".parrot" / "wiki.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["schema"]["sources"]["pg"]["ddl_paths"] = ["db/*.sql"]
    path.write_text(json.dumps(config), encoding="utf-8")


def test_hook_invocation_ingests_every_declared_source(tmp_path, monkeypatch) -> None:
    """The post-merge hook's exact argv parses and ingests each source with its own dialect."""
    from parrot.knowledge.wiki.claude_code import assets

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    _declare_sources(tmp_path)
    ddl = tmp_path / "db" / "users.sql"
    ddl.parent.mkdir()
    ddl.write_text("CREATE TABLE users (id int);", encoding="utf-8")
    calls: list[tuple[str, str, list]] = []

    class FakeService:
        async def ingest_ddl(self, files, *, origin, dialect, changed_only, root):
            calls.append((origin, dialect, list(files)))
            return type("Report", (), {"created": [], "updated": [], "parse_errors": []})()

    monkeypatch.setattr(cli, "_schema_service", lambda: FakeService())
    monkeypatch.setattr(cli, "_changed_ddl_paths", lambda root, origin: [ddl] if origin == "pg" else [])
    hook_line = next(line for line in assets.git_hook_block(tmp_path).splitlines() if "schema ingest-ddl" in line)
    argv = hook_line.split(">/dev/null")[0].split()[1:]

    result = CliRunner().invoke(wiki, argv)

    assert result.exit_code == 0, result.output
    assert calls == [("pg", "postgres", [ddl])]


def test_ingest_ddl_requires_origin_without_changed(tmp_path, monkeypatch) -> None:
    """Explicit PATHS or a non-``--changed`` run still need an origin."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    ddl = tmp_path / "users.sql"
    ddl.write_text("CREATE TABLE users (id int);", encoding="utf-8")

    result = CliRunner().invoke(wiki, ["schema", "ingest-ddl", str(ddl)])

    assert result.exit_code != 0
    assert "--origin is required" in result.output
