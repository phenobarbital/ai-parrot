"""FEAT-461 Module 3 (TASK-2464): call-site migration to the effective config.

Covers the MCP server, Claude Code hook, installer, and federation's
foreign-root resolution — plus a guard against a regressed (silently
base-config-only) call site, and an offline-local degradation regression.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.claude_code.hook import build_nudge
from parrot.knowledge.wiki.claude_code.installer import install_claude_integration
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.federation import resolve_namespaces
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.project import (
    WikiNamespaceConfig,
    WikiProjectConfig,
    load_project_config,
)
from parrot.knowledge.wiki.store import SQLiteWikiStore

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
    result = runner.invoke(wiki, ["build", "--path", str(root), "--no-git", *extra])
    assert result.exit_code == 0, result.output


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake repository, no .parrot/ yet."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n\nA demo project.", encoding="utf-8")
    return tmp_path


class TestCallSiteMigration:
    def test_mcp_server_uses_effective_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        parrot_dir = tmp_path / ".parrot"
        parrot_dir.mkdir()
        (parrot_dir / "wiki.json").write_text(json.dumps({"backend": "memory"}), encoding="utf-8")
        (parrot_dir / "wiki.local.json").write_text(json.dumps({"backend": "sqlite"}), encoding="utf-8")
        (parrot_dir / "wiki" / "pages").mkdir(parents=True)
        (parrot_dir / "wiki" / "wiki.db").touch()
        server = create_wiki_mcp_server(tmp_path)
        store = server.tools["wiki_status"].tool._store
        # Base says "memory"; the local overlay (active env, no ENV set)
        # says "sqlite" — the MCP server must resolve through the
        # effective (merged) config, not the base alone.
        assert isinstance(store, SQLiteWikiStore)

    def test_hook_uses_effective_config(self, runner: CliRunner, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        _build(runner, repo)
        # Overwrite whatever `build` auto-generated for the local overlay:
        # shrink the nudge_tools list so only an effective-config read
        # (not the base's default 4-tool list) would exclude "Glob".
        (repo / ".parrot" / "wiki.local.json").write_text(
            json.dumps({"claude": {"nudge_tools": ["Grep"]}}), encoding="utf-8"
        )
        assert build_nudge({"tool_name": "Glob", "tool_input": {}, "cwd": str(repo)}, root=repo) is None
        assert build_nudge({"tool_name": "Grep", "tool_input": {}, "cwd": str(repo)}, root=repo) is not None

    def test_installer_uses_effective_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        parrot_dir = tmp_path / ".parrot"
        parrot_dir.mkdir()
        # No base wiki.json yet (fresh install) — only a local overlay.
        (parrot_dir / "wiki.local.json").write_text(json.dumps({"backend": "memory"}), encoding="utf-8")
        actions = install_claude_integration(tmp_path, git_hook=False, gitignore=False)
        assert "backend memory" in actions[0]
        assert load_project_config(tmp_path).backend == "memory"

    def test_federation_foreign_root_uses_foreign_overlays(
        self, tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        foreign_root = tmp_path / "foreign"
        foreign_root.mkdir()
        (foreign_root / "pkg").mkdir()
        (foreign_root / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
        _build(runner, foreign_root)
        # The foreign project builds sqlite by default; its own `local`
        # overlay switches to "memory" — proving resolution used the
        # FOREIGN root's environment, not whatever env the local
        # (registering) project happens to run under.
        base = load_project_config(foreign_root)
        assert base.backend == "sqlite"
        (foreign_root / ".parrot" / "wiki" / "pages").mkdir(parents=True)
        (foreign_root / ".parrot" / "wiki.local.json").write_text(json.dumps({"backend": "memory"}), encoding="utf-8")

        local_root = tmp_path / "local"
        local_root.mkdir()
        config = WikiProjectConfig(namespaces={"other": WikiNamespaceConfig(path=str(foreign_root))})
        handles, skipped = asyncio.run(resolve_namespaces(local_root, config, registry_path=tmp_path / "absent.json"))
        assert skipped == []
        assert isinstance(handles[0].store, InMemoryWikiStore)


class TestGuard:
    """Guards spec's top risk (§7): a missed call site silently uses base."""

    # cli.py owns its own precedence surfaces (TASK-2463): `_resolve_project`
    # (routes through `load_effective_config` itself), `build`'s explicit
    # `load_project_config(root)` for base persistence, and `ns add`'s
    # base-config write path. project.py is the DEFINER of both functions —
    # `load_effective_config`'s own body legitimately loads the base via
    # `load_project_config` as its first step; that is not a bypassing
    # consumer call site.
    _ALLOWED_FILES = frozenset({"cli.py", "project.py"})

    def test_no_stray_consumer_load_project_config_calls(self) -> None:
        wiki_pkg = (
            Path(__file__).resolve().parents[3] / "packages" / "ai-parrot" / "src" / "parrot" / "knowledge" / "wiki"
        )
        assert wiki_pkg.is_dir(), wiki_pkg
        pattern = re.compile(r"\bload_project_config\(")
        offenders: list[str] = []
        for path in wiki_pkg.rglob("*.py"):
            if path.name in self._ALLOWED_FILES:
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(line) and "def load_project_config" not in line:
                    offenders.append(f"{path.relative_to(wiki_pkg)}:{lineno}: {stripped}")
        assert offenders == [], (
            "Found consumer load_project_config(...) calls outside the " f"allowed write paths: {offenders}"
        )


class TestOfflineDegradation:
    def test_unreachable_namespace_skipped_bounded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local sqlite primary + unreachable Arango namespace: still
        answers from the local plane, the foreign namespace just skips."""

        class _HangingArango:
            def __init__(self, **kwargs) -> None:
                pass

            async def initialize(self) -> None:
                raise ConnectionError("no route to host")

            async def close(self) -> None:
                return None

        import parrot.knowledge.wiki.arango_store as arango_module

        monkeypatch.setattr(arango_module, "ArangoDBWikiStore", _HangingArango)
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        # Effective config for `tmp_path` (no base wiki.json): defaults to
        # sqlite — the local, no-VPN plane — with one shared namespace
        # pointing at an (unreachable) ArangoDB.
        config = WikiProjectConfig(namespaces={"shared": WikiNamespaceConfig(database="wiki_shared")})
        handles, skipped = asyncio.run(resolve_namespaces(tmp_path, config, registry_path=tmp_path / "absent.json"))
        assert handles == []
        assert skipped[0].name == "shared"
        assert skipped[0].reason == "unreachable"
