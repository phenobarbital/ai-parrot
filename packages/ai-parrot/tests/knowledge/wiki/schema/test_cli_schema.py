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
