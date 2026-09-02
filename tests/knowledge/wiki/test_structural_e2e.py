"""FEAT-498 TASK-2752 — cross-module e2e proofs (spec §4, AC1/2/12/13/14).

Every other FEAT-498 task proved its own module in isolation; this suite
is the only place that drives the FULL pipeline (scan → ingest → store →
service → tool → MCP/CLI) end to end, and the only place that proves the
"no extra installed" degradation is a pure no-op beyond Python `sym:`
pages and `content_hash` (AC2).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import _ingest_files, wiki
from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.repo_scan import file_concept_id, scan_repository
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store
from parrot.knowledge.wiki.structural.service import StructuralService

# ``polyglot_repo``/``force_no_astgrep`` come from
# tests/knowledge/wiki/languages/conftest.py — pytest auto-discovers
# fixtures from any conftest.py in a parent directory of the test file,
# and languages/ is a sibling directory, not an ancestor, so it is
# imported explicitly here as a plugin rather than relying on discovery.
pytest_plugins = ["tests.knowledge.wiki.languages.conftest"]


def _open(root: Path, name: str) -> tuple[BaseWikiStore, SourceCollectionManager]:
    """Open a fresh store + matching source manifest under ``root/.parrot/<name>``.

    Mirrors ``cli.py``'s own ``_open_store``/``_open_sources`` pair
    (storage dir → ``wiki.db`` + a ``sources/`` subdir) rather than the
    spec's own illustrative ``SourceCollectionManager(storage_dir)``
    one-liner, which passes the wiki storage directory itself as
    ``sources_dir`` with no explicit ``db_path`` — that resolves the
    manifest's default db path to ``storage_dir/../wiki.db``, one level
    above where ``create_wiki_store`` actually puts it. See this task's
    Completion Note.
    """
    storage = root / ".parrot" / name
    store = create_wiki_store(storage, wiki_name=name, backend="sqlite")
    sources = SourceCollectionManager(storage / "sources", db_path=storage / "wiki.db")
    return store, sources


def _snapshot(root: Path) -> dict[str, str]:
    """SHA-1 every file under ``root`` outside ``.parrot/``/``.git/`` (read-only guard)."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".parrot" not in path.parts and ".git" not in path.parts:
            out[str(path.relative_to(root))] = hashlib.sha1(path.read_bytes()).hexdigest()
    return out


def _outline_section(body: str) -> str:
    """Extract the ``## API outline`` section text from a rendered ``file:`` page body."""
    if "## API outline" not in body:
        return ""
    section = body.split("## API outline", 1)[1]
    return section.split("## Content", 1)[0].strip()


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class TestPolyglotBuildProducesSymbols:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("seam", ["on", "off"])
    async def test_polyglot_build_produces_symbols(self, polyglot_repo: Path, seam: str, monkeypatch):
        """AC3: Python symbols/edges/content_hash exist regardless of the extra."""
        if seam == "off":
            monkeypatch.setattr(astgrep, "is_available", lambda: False)
            astgrep.RuleSet.load.cache_clear()

        store, sources = _open(polyglot_repo, "wiki")
        scan = scan_repository(polyglot_repo, use_git=False)
        await _ingest_files(store, sources, polyglot_repo, scan)

        pages = await store.dump_pages()
        assert any(p["concept_id"] == "sym:src/app.py#helper" for p in pages)
        file_pages = [p for p in pages if p["concept_id"].startswith("file:")]
        assert file_pages and all(p.get("content_hash") for p in file_pages)

        edges = await store.dump_edges()
        assert ("file:src/app.py", "sym:src/app.py#helper", "defines") in {
            (e["src"], e["dst"], e["rel"]) for e in edges
        }

        if seam == "off":
            astgrep.RuleSet.load.cache_clear()

    @pytest.mark.asyncio
    async def test_outline_bodies_identical_with_and_without_seam(self, polyglot_repo: Path, monkeypatch):
        """AC1: rendered `## API outline` sections match seam vs. fallback.

        Runs the FULL ingest pipeline twice (not `scanner.outline()`
        directly — see `test_outline_parity.py` for that narrower layer)
        and diffs the rendered `file:` page bodies for every deep-scanned
        language.
        """
        store_on, sources_on = _open(polyglot_repo, "wiki_on")
        scan_on = scan_repository(polyglot_repo, use_git=False)
        await _ingest_files(store_on, sources_on, polyglot_repo, scan_on)
        pages_on = {p["concept_id"]: p for p in await store_on.dump_pages()}

        monkeypatch.setattr(astgrep, "is_available", lambda: False)
        astgrep.RuleSet.load.cache_clear()
        store_off, sources_off = _open(polyglot_repo, "wiki_off")
        scan_off = scan_repository(polyglot_repo, use_git=False)
        await _ingest_files(store_off, sources_off, polyglot_repo, scan_off)
        pages_off = {p["concept_id"]: p for p in await store_off.dump_pages()}
        astgrep.RuleSet.load.cache_clear()

        for rel in (
            "src/Service.php", "web/index.ts", "native/src/lib.rs",
            "lib/MyApp/User.pm", "src/app.py",
        ):
            cid = file_concept_id(rel)
            outline_on = _outline_section(pages_on[cid]["body"])
            outline_off = _outline_section(pages_off[cid]["body"])
            assert outline_on == outline_off, f"{rel}: outline differs between seam on/off"


class TestNoExtraIsNoop:
    @pytest.mark.asyncio
    async def test_no_extra_installed_is_noop(self, polyglot_repo: Path, monkeypatch):
        """AC2: without the extra, only Python gains `sym:` pages/edges.

        `file:`/`dir:` pages and their `references`/`contains` edges are
        otherwise identical to a run with the extra available (diffed
        directly here — no committed pre-feature golden file, per this
        task's own "Does NOT Exist" note).
        """
        store_on, sources_on = _open(polyglot_repo, "wiki_on")
        scan_on = scan_repository(polyglot_repo, use_git=False)
        await _ingest_files(store_on, sources_on, polyglot_repo, scan_on)
        pages_on = {p["concept_id"]: p for p in await store_on.dump_pages()}
        edges_on = {(e["src"], e["dst"], e["rel"]) for e in await store_on.dump_edges()}

        monkeypatch.setattr(astgrep, "is_available", lambda: False)
        astgrep.RuleSet.load.cache_clear()
        store_off, sources_off = _open(polyglot_repo, "wiki_off")
        scan_off = scan_repository(polyglot_repo, use_git=False)
        await _ingest_files(store_off, sources_off, polyglot_repo, scan_off)
        pages_off = {p["concept_id"]: p for p in await store_off.dump_pages()}
        edges_off = {(e["src"], e["dst"], e["rel"]) for e in await store_off.dump_edges()}
        astgrep.RuleSet.load.cache_clear()

        # Only Python sym: pages survive without the extra.
        sym_off = [cid for cid in pages_off if cid.startswith("sym:")]
        assert sym_off and all(cid.split("#")[0].endswith(".py") for cid in sym_off)
        sym_on = [cid for cid in pages_on if cid.startswith("sym:")]
        assert len(sym_on) > len(sym_off)  # the extra adds non-Python symbols

        # file:/dir: pages: identical bodies (content_hash is additive,
        # identical either way — both runs use current, post-feature code).
        file_dir_on = {cid: p["body"] for cid, p in pages_on.items() if not cid.startswith("sym:")}
        file_dir_off = {cid: p["body"] for cid, p in pages_off.items() if not cid.startswith("sym:")}
        assert file_dir_on == file_dir_off

        # references/contains(file/dir) edges: identical either way —
        # only symbol-plane edges (defines/calls/extends/implements) are
        # additive.
        non_symbol_edges_on = {
            (s, d, r) for s, d, r in edges_on if not s.startswith("sym:") and not d.startswith("sym:")
        }
        non_symbol_edges_off = {
            (s, d, r) for s, d, r in edges_off if not s.startswith("sym:") and not d.startswith("sym:")
        }
        assert non_symbol_edges_on == non_symbol_edges_off


class TestMCPServerNineTools:
    def test_mcp_server_registers_nine_tools_and_round_trips(self, tmp_path: Path):
        # NOT an async def: `build`/`_run` calls `asyncio.run()` internally
        # (cli.py), which raises "cannot be called from a running event
        # loop" if this test itself already runs inside pytest-asyncio's
        # loop. The one async step (the stdio adapter round trip) gets
        # its own `asyncio.run()` below instead.
        root = tmp_path / "repo"
        root.mkdir()
        (root / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
        result = CliRunner().invoke(wiki, ["build", "--path", str(root), "--no-git", "-q"])
        assert result.exit_code == 0, result.output

        server = create_wiki_mcp_server(root)
        names = set(server.tools.keys())
        assert len(names) == 9
        assert {"wiki_symbol_lookup", "wiki_code_outline", "wiki_blast_radius"} <= names

        adapter = server.tools["wiki_symbol_lookup"]
        response = asyncio.run(adapter.execute({"query": "helper"}))
        assert response.get("isError") is not True
        text = response["content"][0]["text"]
        payload = json.loads(text) if text.strip().startswith("{") else None
        # The tool's ToolResult.result is a dict; the adapter serialises it
        # as the MCP text content — either JSON or repr, either way the
        # symbol id must be visible in it.
        assert "sym:a.py#helper" in text or (payload and "sym:a.py#helper" in json.dumps(payload))


class TestUpsertChangedRefreshesSymbols:
    def test_upsert_changed_refreshes_symbols(self, tmp_path: Path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
        (root / "b.py").write_text(
            "from a import helper\n\n\ndef run():\n    return helper()\n", encoding="utf-8"
        )
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "t@t.t")
        _git(root, "config", "user.name", "t")
        _git(root, "config", "commit.gpgsign", "false")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "init")

        runner = CliRunner()
        build = runner.invoke(wiki, ["build", "--path", str(root), "-q"])
        assert build.exit_code == 0, build.output

        store = create_wiki_store(root / ".parrot" / "wiki", wiki_name="repo", backend="sqlite")
        edges_before = {(e["src"], e["dst"], e["rel"]) for e in asyncio.run(store.dump_edges())}
        assert ("sym:b.py#run", "sym:a.py#helper", "calls") in edges_before

        # Rename the symbol (same file, new name) — the old sym: page
        # must disappear and the new one appear. b.py itself is
        # untouched, so `upsert --changed` (git diff-tree of the last
        # commit) never re-scans it.
        (root / "a.py").write_text("def helper_renamed():\n    return 1\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "rename helper")

        upsert = runner.invoke(wiki, ["upsert", "--changed", "--path", str(root), "-q"])
        assert upsert.exit_code == 0, upsert.output

        old_page = asyncio.run(store.get_page("sym:a.py#helper", include_body=False))
        new_page = asyncio.run(store.get_page("sym:a.py#helper_renamed", include_body=False))
        assert old_page is None
        assert new_page is not None

        # `replace_source_slice` (store.py) proactively deletes every edge
        # touching a removed concept id as part of the SAME atomic
        # transaction that drops the old `sym:a.py#helper` page — verified
        # directly against its SQL (`DELETE FROM edges WHERE src = ? OR
        # dst = ?` for every old id, before the "preserved incoming edges"
        # re-insert, which only re-adds edges whose dst SURVIVES the
        # replacement). So b.py's now-stale `calls` edge is never left
        # dangling for `broken_edges()` to catch — it is gone in the same
        # commit that removed its target, a stronger guarantee than the
        # "reported until the dependent file is upserted" this task's own
        # Scope assumed (see this task's Completion Note).
        edges_after = {(e["src"], e["dst"], e["rel"]) for e in asyncio.run(store.dump_edges())}
        assert ("sym:b.py#run", "sym:a.py#helper", "calls") not in edges_after
        assert asyncio.run(store.broken_edges()) == []

        # Upserting the dependent file too changes nothing further here —
        # run() still textually calls helper(), which no longer resolves
        # to anything (SymbolResolver produces no edge for an unresolvable
        # call), so no NEW edge appears either.
        upsert2 = runner.invoke(wiki, ["upsert", "b.py", "--path", str(root), "-q"])
        assert upsert2.exit_code == 0, upsert2.output
        edges_final = {(e["src"], e["dst"], e["rel"]) for e in asyncio.run(store.dump_edges())}
        assert not any(dst == "sym:a.py#helper" for _src, dst, _rel in edges_final)
        assert asyncio.run(store.broken_edges()) == []


class TestEndToEndLookupBlastRepair:
    def test_end_to_end_lookup_blast_repair(self, tmp_path: Path):
        # NOT an async def — see TestMCPServerNineTools's note: `build`
        # calls `asyncio.run()` internally, so it must run outside any
        # already-running event loop.
        root = tmp_path / "repo"
        root.mkdir()
        (root / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
        (root / "b.py").write_text(
            "from a import helper\n\n\ndef run():\n    return helper()\n", encoding="utf-8"
        )
        build = CliRunner().invoke(wiki, ["build", "--path", str(root), "--no-git", "-q"])
        assert build.exit_code == 0, build.output

        from parrot.knowledge.wiki.project import load_effective_config

        config = load_effective_config(root).config
        store = create_wiki_store(config.storage_path(root), wiki_name=config.wiki_name, backend=config.backend)
        service = StructuralService(store, root, config)

        async def _run() -> None:
            lookup1 = await service.lookup("helper")
            assert lookup1.hits and not lookup1.repaired_files

            blast = await service.blast_radius("sym:a.py#helper")
            assert "b.py" in blast.files

            (root / "a.py").write_text(
                (root / "a.py").read_text(encoding="utf-8") + "\ndef another(): ...\n", encoding="utf-8"
            )
            lookup2 = await service.lookup("helper")
            assert lookup2.repaired_files == ["a.py"]
            assert not any(hit.stale for hit in lookup2.hits)

        asyncio.run(_run())


class TestToolCallsAreReadOnly:
    def test_tool_calls_are_read_only(self, tmp_path: Path):
        """AC14: the source tree is byte-identical before/after every tool/CLI call."""
        root = tmp_path / "repo"
        root.mkdir()
        (root / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
        build = CliRunner().invoke(wiki, ["build", "--path", str(root), "--no-git", "-q"])
        assert build.exit_code == 0, build.output

        from parrot.knowledge.wiki.project import load_effective_config
        from parrot.knowledge.wiki.structural.tools import create_structural_tools

        config = load_effective_config(root).config
        store = create_wiki_store(config.storage_path(root), wiki_name=config.wiki_name, backend=config.backend)
        tools = create_structural_tools(store, root, config)

        async def _call_tools() -> None:
            for tool in tools:
                if tool.name == "wiki_symbol_lookup":
                    await tool._execute(query="helper")
                elif tool.name == "wiki_code_outline":
                    await tool._execute(target="file:a.py")
                else:
                    await tool._execute(symbol="sym:a.py#helper")

        before = _snapshot(root)
        asyncio.run(_call_tools())
        assert _snapshot(root) == before

        # CLI path too.
        for args in (
            ["symbols", "lookup", "helper", "--path", str(root)],
            ["symbols", "outline", "file:a.py", "--path", str(root)],
            ["symbols", "blast", "sym:a.py#helper", "--path", str(root)],
        ):
            result = CliRunner().invoke(wiki, args)
            assert result.exit_code == 0, result.output
        assert _snapshot(root) == before
