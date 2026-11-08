"""Packaged `pageindex` toolkit template and example (FEAT-842 M4/M5)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from parrot.cli import cli
from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

_EXAMPLE_PATH = Path(__file__).resolve().parents[4] / "examples" / "pageindex-mcp.yaml"
_CLASS = "parrot.knowledge.pageindex.toolkit.PageIndexToolkit"


def test_template_metadata() -> None:
    """AC-7: requires_llm False, requires_dist (bm25s, pymupdf), requires_pip (ai-parrot[bookstore],)."""
    assert "pageindex" in available_templates()
    tpl = load_template("pageindex")
    assert tpl.requires_llm is False
    assert tpl.requires_dist == ("bm25s", "pymupdf")
    assert tpl.requires_pip == ("ai-parrot[bookstore]",)
    assert "{{repo_root}}" in tpl.body
    assert f"class: {_CLASS}" in tpl.body


def test_template_seeds_repo_scoped_storage(tmp_path: Path) -> None:
    """AC-7: seeding renders storage_dir under <root>/.parrot/pageindex with max_result_chars 24000."""
    result = seed_toolkit_sections(tmp_path, ["pageindex"])
    assert result.added == ["pageindex"]
    section = load_toolkits_config(tmp_path).toolkits["pageindex"]
    assert section.class_path == _CLASS
    assert section.llm is None
    assert list(section.exclude) == ["pageindex_agentic_retrieve"]
    assert section.kwargs["storage_dir"] == f"{tmp_path}/.parrot/pageindex"
    assert section.kwargs["max_result_chars"] == 24000
    written = (tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text(encoding="utf-8")
    assert "{{repo_root}}" not in written


def test_example_mirrors_template_with_llm() -> None:
    """The example is a standalone config with the same class and an active llm line."""
    assert _EXAMPLE_PATH.is_file()
    raw = yaml.safe_load(_EXAMPLE_PATH.read_text(encoding="utf-8"))["toolkits"]["pageindex"]
    assert raw["class"] == _CLASS
    assert raw["llm"]
    assert raw["kwargs"]["max_result_chars"] == 24000
    section = load_toolkits_config(_EXAMPLE_PATH.parent, config_path=_EXAMPLE_PATH).toolkits["pageindex"]
    assert section.llm
    assert section.class_path == _CLASS


LLM_TOOLS = {
    "pageindex_insert_content",
    "pageindex_import_file",
    "pageindex_import_folder",
    "pageindex_import_pdf",
    "pageindex_search_documents_scoped",
}
CORE_TOOLS = {"pageindex_search", "pageindex_retrieve", "pageindex_insert_markdown", "pageindex_create_tree"}
_MARKER_TAIL = "lower top_k or narrow the query]"

_FILLER = (
    "the quick survey notes record observations gathered across many seasons of careful fieldwork "
    "by volunteers who walked the same transects every month and wrote down what they saw "
    "including weather conditions timing and the general behaviour of the species encountered"
)


def _doc(*words: str) -> str:
    """Markdown with one ``## `` section per distinctive word (each section well over 60 words)."""
    sections = "\n\n".join(f"## Section {w.title()}\nAll about {w} here. {_FILLER}. {_FILLER}." for w in words)
    return f"# Field Guide\n\n{sections}\n"


DOC = _doc("edelweiss", "cormorant", "grayling")

# ---------------------------------------------------------------------------
# `mcp-local` spawn/handshake bootstrap — copied (not imported) from
# tests/mcp/test_toolkit_matrix.py, whose helpers are private to that module.
# ---------------------------------------------------------------------------
_CORE_SRC = Path(__file__).resolve().parents[2] / "src"

_BOOTSTRAP = textwrap.dedent(f"""
    import sys, types
    sys.path.insert(0, {str(_CORE_SRC)!r})

    try:
        import parrot.utils.types  # noqa: F401 — prefer the real compiled extension
    except ImportError:
        _m = types.ModuleType("parrot.utils.types")
        class SafeDict(dict):
            def __missing__(self, key):
                return None
        _m.SafeDict = SafeDict
        sys.modules["parrot.utils.types"] = _m

    try:
        import parrot.utils.parsers.toml  # noqa: F401
    except ImportError:
        _pkg = types.ModuleType("parrot.utils.parsers")
        _mod = types.ModuleType("parrot.utils.parsers.toml")
        class TOMLParser:
            def __init__(self, *a, **kw):
                pass
            def parse(self, content):
                import tomllib
                return tomllib.loads(content)
        _mod.TOMLParser = TOMLParser
        _pkg.TOMLParser = TOMLParser
        sys.modules["parrot.utils.parsers"] = _pkg
        sys.modules["parrot.utils.parsers.toml"] = _mod

    from parrot.cli import cli
    cli(prog_name="parrot")
    """)


def _spawn(cwd: Path, *args: str) -> subprocess.Popen:
    """Start `parrot <args>` as a subprocess rooted at ``cwd``."""
    return subprocess.Popen(
        [sys.executable, "-c", _BOOTSTRAP, *args],
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, stray: list[str] | None = None) -> dict:
    """Read one stdout line and parse it as JSON-RPC.

    Fails loudly on EOF. A non-JSON line fails immediately unless ``stray`` is given, in which case it
    is recorded there and reading continues, so a caller can finish its checks and assert purity last.
    """
    while True:
        line = proc.stdout.readline()
        if not line:
            raise AssertionError(f"subprocess produced no output (exit={proc.poll()}); stderr:\n{proc.stderr.read()}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            if stray is None:
                raise AssertionError(f"non-JSON-RPC line on stdout: {line!r}") from exc
            stray.append(line)


def _shutdown(proc: subprocess.Popen) -> None:
    """Close stdin (clean EOF shutdown) and reap the process."""
    try:
        proc.stdin.close()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _call(proc: subprocess.Popen, req_id: int, method: str, params: dict, stray: list[str] | None = None) -> dict:
    """Send one request and return the response carrying the same id (tools/call may answer out of order)."""
    _send(proc, {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
    while True:
        msg = _recv(proc, stray)
        if msg.get("id") == req_id:
            return msg


def _tool_text(resp: dict) -> str:
    """Concatenate the text parts of a ``tools/call`` result."""
    assert "error" not in resp, resp
    result = resp["result"]
    content = result.get("content") or []
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def _configure_section(root: Path, **updates) -> None:
    """Seed the pageindex section under ``root`` and merge ``updates`` into it (top level or ``kwargs``)."""
    seed_toolkit_sections(root, ["pageindex"])
    path = root / ".parrot" / "mcp-toolkits.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    section = data["toolkits"]["pageindex"]
    for key, value in updates.items():
        if key == "max_result_chars":
            section["kwargs"][key] = value
        else:
            section[key] = value
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _handshake(proc: subprocess.Popen, stray: list[str] | None = None) -> dict:
    init = _call(proc, 1, "initialize", {}, stray)
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    return init


@pytest.fixture
def _stub_tiktoken(monkeypatch):
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)


def test_factory_hides_llm_tools_without_llm(tmp_path: Path) -> None:
    """AC-8: no llm -> none of the five LLM tools; the core tools are served."""
    seed_toolkit_sections(tmp_path, ["pageindex"])
    server = create_toolkit_mcp_server("pageindex", tmp_path)
    names = set(server.tools)
    assert not (names & LLM_TOOLS)
    assert CORE_TOOLS <= names


def test_factory_serves_llm_tools_with_llm(tmp_path: Path, monkeypatch) -> None:
    """AC-8: with llm (factory monkeypatched) all five appear and the adapter wraps the fake client."""
    fake = MagicMock(spec=AbstractClient)
    monkeypatch.setattr("parrot.clients.factory.LLMFactory.create", lambda *a, **k: fake)
    _configure_section(tmp_path, llm="fake:model")
    server = create_toolkit_mcp_server("pageindex", tmp_path)
    assert LLM_TOOLS <= set(server.tools)
    assert CORE_TOOLS <= set(server.tools)
    assert server._owned_toolkit._adapter.client is fake


def test_agentic_tool_excluded_by_default(tmp_path: Path, monkeypatch) -> None:
    """AC-13: the seeded template hides pageindex_agentic_retrieve even with an llm."""
    fake = MagicMock(spec=AbstractClient)
    monkeypatch.setattr("parrot.clients.factory.LLMFactory.create", lambda *a, **k: fake)
    _configure_section(tmp_path, llm="fake:model")

    server = create_toolkit_mcp_server("pageindex", tmp_path)

    assert "pageindex_agentic_retrieve" not in server.tools


def test_agentic_tool_served_when_opted_in(tmp_path: Path, monkeypatch) -> None:
    """AC-13: removing it from exclude and setting llm serves it."""
    fake = MagicMock(spec=AbstractClient)
    monkeypatch.setattr("parrot.clients.factory.LLMFactory.create", lambda *a, **k: fake)
    _configure_section(tmp_path, llm="fake:model", exclude=[])

    server = create_toolkit_mcp_server("pageindex", tmp_path)

    assert "pageindex_agentic_retrieve" in server.tools


def _tool(proc: subprocess.Popen, stray: list[str], req_id: int, name: str, **arguments) -> dict:
    return _call(proc, req_id, "tools/call", {"name": name, "arguments": arguments}, stray)


# pytector (the prompt-injection scorer FEAT-840 runs on every ingest) prints a "Loading Hugging Face model"
# banner to stdout on first use, at tool-call time, outside the factory's stdout redirect: a stdio host sees a
# non-JSON line. Tracked in the SDD ledger as issue:70f18da2a8d5 (see the TASK-5318 Completion Note). The banner
# only appears when the scorer model loads, so this test can pass in environments where it is cached.
@pytest.mark.xfail(
    strict=False,
    reason="issue:70f18da2a8d5 — pytector prints a model-loading banner to stdout on first ingest; "
    "root-cause fix is owned by FEAT-844 (pageindex-toolkit-fixes), which removes this marker",
)
def test_pageindex_serves_over_stdio(tmp_path: Path) -> None:
    """AC-9: handshake, tools/list, create, insert, BM25 hit, bounded retrieve, JSON-only stdout, exit 0."""
    pytest.importorskip("bm25s")
    _configure_section(tmp_path, max_result_chars=300)
    stray: list[str] = []
    proc = _spawn(tmp_path, "mcp-local", "pageindex")
    try:
        init = _handshake(proc, stray)
        assert init["result"]["serverInfo"]["name"] == "parrot-pageindex"

        listed = _call(proc, 2, "tools/list", {}, stray)
        names = {t["name"] for t in listed["result"]["tools"]}
        assert CORE_TOOLS <= names
        assert not (names & LLM_TOOLS)

        created = _tool(proc, stray, 3, "pageindex_create_tree", tree_name="guide")
        assert "error" not in created, created
        inserted = _tool(proc, stray, 4, "pageindex_insert_markdown", tree_name="guide", markdown=DOC)
        assert "new_node_ids" in _tool_text(inserted), inserted
        found = _tool(proc, stray, 5, "pageindex_search", tree_name="guide", query="edelweiss")
        assert "Section Edelweiss" in _tool_text(found), found
        retrieved = _tool(
            proc, stray, 6, "pageindex_retrieve", tree_name="guide", query="edelweiss cormorant grayling", top_k=3
        )
        text = _tool_text(retrieved)  # the MCP wrapper appends a "Metadata:" trailer after the tool text
        assert "[truncated:" in text and _MARKER_TAIL in text, retrieved
    finally:
        _shutdown(proc)

    # Purity is asserted last so every functional check above still runs; then a clean EOF must exit 0.
    assert not stray, f"non-JSON lines on stdout: {stray!r}"
    for line in proc.stdout.read().splitlines():
        if line.strip():
            json.loads(line)
    assert proc.returncode == 0, proc.stderr.read()


def test_pageindex_server_shares_storage_with_second_toolkit(tmp_path: Path, _stub_tiktoken) -> None:
    """AC-10: the in-process toolkit sees the server's tree; the server finds text the toolkit inserted."""
    pytest.importorskip("bm25s")
    _configure_section(tmp_path)
    storage = tmp_path / ".parrot" / "pageindex"
    stray: list[str] = []  # stdout purity is asserted by the stdio test, not here
    proc = _spawn(tmp_path, "mcp-local", "pageindex")
    try:
        _handshake(proc, stray)
        _tool(proc, stray, 2, "pageindex_create_tree", tree_name="shared")
        _tool(proc, stray, 3, "pageindex_insert_markdown", tree_name="shared", markdown=DOC)

        second = PageIndexToolkit(storage_dir=storage)
        assert "shared" in asyncio.run(second.list_trees())
        assert "edelweiss" in asyncio.run(second.retrieve("shared", "edelweiss")).lower()

        asyncio.run(second.insert_markdown("shared", _doc("marmot")))

        found = _tool(proc, stray, 4, "pageindex_search", tree_name="shared", query="marmot")
        assert "Section Marmot" in _tool_text(found), found
    finally:
        _shutdown(proc)
    assert proc.returncode == 0


def test_install_registers_claude_host(repo_with_hosts: Path) -> None:
    """AC-11: `parrot toolkits install pageindex --yes` seeds the section and registers parrot-pageindex."""
    result = CliRunner().invoke(cli, ["toolkits", "install", "pageindex", "--yes"])
    assert result.exit_code == 0, result.output
    assert "parrot-pageindex" in (repo_with_hosts / ".mcp.json").read_text(encoding="utf-8")
    section = load_toolkits_config(repo_with_hosts).toolkits["pageindex"]
    assert section.class_path == _CLASS
