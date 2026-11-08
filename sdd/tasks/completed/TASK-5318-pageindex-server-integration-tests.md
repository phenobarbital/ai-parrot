# TASK-5318: PageIndex MCP server integration tests (factory, stdio, two writers, install)

**Feature**: FEAT-842 — PageIndex Local MCP Toolkit
**Spec**: `sdd/specs/pageindex-local-mcp-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5314, TASK-5316, TASK-5317
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5** (server integration tests) — the proof over the real
transport (Goal 6). It exercises the unchanged generic pipeline end to end:
`create_toolkit_mcp_server("pageindex")` in-process with and without `llm:`, then
`parrot mcp-local pageindex` as a subprocess over stdio, two writers on one storage
directory, and `parrot toolkits install pageindex --yes`. It adds tests only; if a test
can pass only by changing `mcp/` code, that is a spec defect to report (spec Non-Goals),
not something to fix here.

---

## Scope

Append to `tests/mcp/test_pageindex_template.py` (created by TASK-5317):
- `test_factory_hides_llm_tools_without_llm` (AC-8, no `llm:`).
- `test_factory_serves_llm_tools_with_llm` (AC-8, `LLMFactory.create` monkeypatched to a fake client; the toolkit's adapter wraps that client).
- `test_pageindex_serves_over_stdio` (AC-9).
- `test_pageindex_server_shares_storage_with_second_toolkit` (AC-10).
- `test_install_registers_claude_host` (AC-11).

**NOT in scope**: any source change; Codex/Google host assertions beyond what
`repo_with_hosts` gives for free; FEAT-840 read tools.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/mcp/test_pageindex_template.py` | MODIFY | append the five integration tests + private spawn helpers |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `1db2685b95`. Paths relative to `packages/ai-parrot/src/parrot/`
> unless they start with `packages/`.

### Verified Imports
```python
from parrot.mcp.toolkit_server import create_toolkit_mcp_server   # mcp/toolkit_server.py:258
from parrot.mcp.toolkit_seed import seed_toolkit_sections          # mcp/toolkit_seed.py:335
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit    # knowledge/pageindex/toolkit.py:63
from parrot.clients.base import AbstractClient                     # clients/base.py
from parrot.cli import cli                                         # used by tests/mcp/test_toolkit_matrix.py:25
from click.testing import CliRunner                                # used by tests/mcp/test_toolkit_matrix.py:23
```

### Existing Signatures to Use
```python
# mcp/toolkit_server.py
def create_toolkit_mcp_server(name: str, root: Optional[Path] = None, *, login_file=None, **overrides) -> StdioMCPServer  # :258
#   overrides["config_path"] -> load_toolkits_config(root, config_path=Path(config_path))      # :299-300
#   no llm  -> drop_tools = set(toolkit_cls.llm_dependent_tools)                               # :335
#   llm set -> `from parrot.clients.factory import LLMFactory` (imported INSIDE the function), llm_client = LLMFactory.create(section.llm, **section.llm_kwargs)  # :327-333
#   kwargs["llm_client"] = llm_client; toolkit = toolkit_cls(**kwargs)                          # :338-342
#   server = _ToolkitStdioMCPServer(LocalServerConfig(name=f"parrot-{name}", ...), toolkit, ...)  # :382; the toolkit is kept as server._owned_toolkit (:110)
#   server.tools: dict[str, MCPToolAdapter] keyed by tool name                                  # server_base.py:63
# clients/factory.py: `class LLMFactory` with `@staticmethod def create(...)` (:256-257)

# mcp/server_base.py — tools/call: params {"name": ..., "arguments": {...}}                    # :113-115
# mcp/local_server.py — tools/call handlers run as independent tasks; responses may arrive out of order (match by id)  # :11-19

# knowledge/pageindex/toolkit.py tool argument names
async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict          # :483
async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id=None, doc_name=None) -> dict  # :922
async def list_trees(self) -> list[str]                                                       # :479
async def search(self, tree_name, query, top_k=10, use_bm25=True, use_llm_walk=True, ...)     # :655
async def retrieve(self, tree_name, query, top_k=5) -> str                                    # :722
# after TASK-5314/5316: PageIndexToolkit(storage_dir=..., llm_client=..., max_result_chars=...), .has_llm, ._adapter.client

# knowledge/pageindex/utils.py
def count_tokens(text, model="gpt-4o") -> int   # :66 — falls back to a char estimate when tiktoken cannot load (offline-safe in the subprocess)
```

Test helpers to reuse:
- `repo_with_hosts` fixture — `packages/ai-parrot/tests/mcp/conftest.py:11` (writes `.mcp.json`, `.codex/config.toml`, redirects Google, `chdir`s into the temp repo).
- Spawn bootstrap — `tests/mcp/test_toolkit_matrix.py:36-115` (`_CORE_SRC`, `_BOOTSTRAP`, `_spawn`, `_send`, `_recv`, `_shutdown`). **Copy them** into this file as private helpers (that file's own comment at :31-34 explains the helpers are copied, not imported). Keep `_CORE_SRC = Path(__file__).resolve().parents[2] / "src"`.
- Handshake pattern — `test_installed_toolkit_actually_serves`, `test_toolkit_matrix.py:244-266`.
- Claude host check — `_entry_present`, `test_toolkit_matrix.py:123-127` (`"parrot-<name>" in .mcp.json` text).

### Does NOT Exist
- ~~importable `_spawn` from another test module~~ — copy it
- ~~`server.toolkit`~~ — the attribute is `_owned_toolkit`
- ~~a `parrot pageindex` CLI~~ / ~~`knowledge/pageindex/mcp_server.py`~~ — only `parrot mcp-local pageindex`
- ~~fakeredis / network fixtures~~ — not needed; everything is file-based

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/mcp/test_pageindex_template.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit"
  ]
}
```

---

## Implementation Notes

- Markdown fixture: ≥ 3 sections × ≥ 60 words each, so `thin_tree` keeps the nodes in the
  subprocess (no tiktoken stub there). Put one distinctive word in one section for the BM25 hit.
- In-process tests that ingest need the `_stub_tiktoken` fixture (copy from
  `tests/knowledge/pageindex/test_toolkit.py:52-62`), applied only to those tests (do not
  make it autouse for the subprocess tests — it would not reach the child anyway).
- `pytest.importorskip("bm25s")` on every test that searches.
- For the stdio test, write a config whose `pageindex` section has a small
  `max_result_chars` (e.g. 300): seed with `seed_toolkit_sections`, then rewrite the YAML
  with `yaml.safe_load`/`yaml.safe_dump`, so `retrieve` returns the truncation marker.
- Read responses with a helper that loops `_recv` until the response `id` matches the
  request — `tools/call` responses can arrive out of order (local_server.py:11-19).
  Send calls one at a time.
- The tool result arrives as MCP content; FILL IN how the text is extracted after looking
  at one real response (print it to the assertion message on failure, never to stdout).
- Every stdout line must parse as JSON — `_recv` already fails on a non-JSON line; also
  drain any remaining stdout after `_shutdown` and parse each line.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the spawn helpers — *why*: the stdio test needs them and they are private to the matrix module.
2. Add the two in-process factory tests — *why*: AC-8 is cheapest to prove without a subprocess.
3. Add the stdio test — *why*: AC-9, the only proof that stdout stays pure.
4. Add the two-writer test — *why*: AC-10 (FEAT-831 signature reload).
5. Add the install test — *why*: AC-11.

### `packages/ai-parrot/tests/mcp/test_pageindex_template.py` (MODIFY)
```python
# ADD to the imports at the top of the file:
import json
import subprocess
import sys
import textwrap
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from parrot.cli import cli
from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

# APPEND below the existing tests:
LLM_TOOLS = {
    "pageindex_insert_content",
    "pageindex_import_file",
    "pageindex_import_folder",
    "pageindex_import_pdf",
    "pageindex_search_documents_scoped",
}
CORE_TOOLS = {"pageindex_search", "pageindex_retrieve", "pageindex_insert_markdown", "pageindex_create_tree"}

DOC = """# FILL IN: >= 3 '## ' sections x >= 60 words, one distinctive word (e.g. "edelweiss") in one section
"""

# FILL IN: copy _CORE_SRC, _BOOTSTRAP, _spawn, _send, _recv, _shutdown verbatim from
#   tests/mcp/test_toolkit_matrix.py:36-115


def _call(proc: subprocess.Popen, req_id: int, method: str, params: dict) -> dict:
    """Send one request and return the response with the same id."""
    _send(proc, {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
    while True:
        msg = _recv(proc, timeout=30.0)
        if msg.get("id") == req_id:
            return msg


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
    # FILL IN: seed, then add `llm: fake:model` to the section (yaml round-trip);
    #   server = create_toolkit_mcp_server("pageindex", tmp_path); LLM_TOOLS <= set(server.tools);
    #   server._owned_toolkit._adapter.client is fake


def test_pageindex_serves_over_stdio(tmp_path: Path) -> None:
    """AC-9: handshake, tools/list, create, insert, BM25 hit, bounded retrieve, JSON-only stdout, exit 0."""
    pytest.importorskip("bm25s")
    # FILL IN: seed + small max_result_chars; proc = _spawn(tmp_path, "mcp-local", "pageindex");
    #   initialize -> serverInfo.name == "parrot-pageindex"; notifications/initialized; tools/list (CORE_TOOLS present, no LLM_TOOLS);
    #   tools/call create_tree, insert_markdown(DOC), search (hit on the distinctive word), retrieve (ends with the
    #   "lower top_k or narrow the query]" marker); _shutdown; every remaining stdout line json.loads; returncode == 0


def test_pageindex_server_shares_storage_with_second_toolkit(tmp_path: Path) -> None:
    """AC-10: the in-process toolkit sees the server's tree; the server finds text the toolkit inserted."""
    pytest.importorskip("bm25s")
    # FILL IN: server creates tree + inserts over stdio; PageIndexToolkit(storage_dir=<same dir>) lists it and
    #   retrieves its text (asyncio.run or async test); then the in-process toolkit insert_markdown()s a second
    #   doc with another distinctive word; a pageindex_search over the SAME stdio session finds it


def test_install_registers_claude_host(repo_with_hosts: Path) -> None:
    """AC-11: `parrot toolkits install pageindex --yes` seeds the section and registers parrot-pageindex."""
    result = CliRunner().invoke(cli, ["toolkits", "install", "pageindex", "--yes"])
    assert result.exit_code == 0, result.output
    # FILL IN: "parrot-pageindex" in (repo_with_hosts / ".mcp.json").read_text(); section present in .parrot/mcp-toolkits.yaml
```
**Why**: the in-process tests pin the factory contract cheaply; the subprocess tests are
the only proof of the real transport and stdout purity. `monkeypatch.setattr` on the
dotted `LLMFactory.create` works because the factory imports `LLMFactory` at call time.
If `toolkits install` refuses because `bm25s`/`pymupdf` are missing, skip the test with
`pytest.importorskip("bm25s")` / `("pymupdf")` rather than weakening the assertion.

### FILL IN checklist
- [ ] copied spawn helpers — verbatim from `test_toolkit_matrix.py:36-115`
- [ ] `DOC` fixture — bounded by "≥ 3 sections × ≥ 60 words"
- [ ] tool-result text extraction — bounded by one observed response
- [ ] five test bodies — bounded by AC-8..AC-11

---

## Acceptance Criteria

- [ ] AC-8 without `llm:` no LLM-dependent tool is served and `pageindex_search`, `pageindex_retrieve`, `pageindex_insert_markdown`, `pageindex_create_tree` are; with `llm:` all five appear.
- [ ] AC-9 stdio handshake (`serverInfo.name == "parrot-pageindex"`), `tools/list`, create tree, insert markdown, BM25 hit, bounded retrieve; every stdout line is JSON; exit code 0.
- [ ] AC-10 the second toolkit lists the server's tree, and the server finds text the second toolkit inserted.
- [ ] AC-11 `parrot toolkits install pageindex --yes` seeds the section and registers `parrot-pageindex` in `.mcp.json`.
- [ ] AC-12 `git diff origin/dev -- packages/ai-parrot/src/parrot/mcp/toolkit_server.py packages/ai-parrot/src/parrot/mcp/toolkit_seed.py packages/ai-parrot/src/parrot/mcp/toolkit_install.py packages/ai-parrot/src/parrot/mcp/hosts.py packages/ai-parrot/src/parrot/mcp/local_cli.py` is empty.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_pageindex_template.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_toolkit_matrix.py -q`

---

## Test Specification

See the MODIFY block above.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5314, TASK-5316 and TASK-5317 are `done` in the per-spec index.
2. Mark `in-progress`; commit only the index.
3. Implement from the blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (the subprocess bootstrap inserts `_CORE_SRC` itself, so the child imports the worktree's code).
4. Commit the test file; `parrot sdd task close TASK-5318 pageindex-local-mcp-toolkit verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (fallback sequential loop)
**Date**: 2026-11-08
**Notes**: five integration tests added (factory with/without llm, stdio, two writers, install). AC-8, AC-10, AC-11 and AC-12 (no diff in the five mcp/ files) pass; ruff clean; test_toolkit_matrix unaffected.

**Deviations from spec**: AC-9 is only partly met. `test_pageindex_serves_over_stdio` is a strict xfail. The handshake, tools/list, create, insert, BM25 hit and bounded retrieve (marker present) all pass, but the stdout-purity assertion fails: on the first `pageindex_insert_markdown`, the FEAT-840 injection scorer (`scan_injection` defaults True; `pytector`) prints `Loading Hugging Face model from: ...` to stdout at tool-call time, outside the factory's stdout redirect, so a non-JSON line reaches the stdio stream. It would also download an ML model on first ingest. Fixing it needs a change in `toolkit.py::_scan`, the constructor, or the template, which this test-only task and AC-12 do not allow, so it is filed as **issue:70f18da2a8d5** [major]. Once fixed, the strict xfail turns into XPASS and the marker must be removed. The two-writer test tolerates the stray line on purpose (it is not a purity test). Note for the owner: the MCP wrapper appends a `Metadata: {...}` trailer to every tool result, so the truncation marker is not the last characters of the text.
