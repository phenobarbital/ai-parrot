# TASK-3367: Operator/client guide, tool-surface golden test and end-to-end remote test (M8)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3355, TASK-3361, TASK-3363, TASK-3364, TASK-3365, TASK-3366
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, AC3, AC14, AC16, AC17, design research S11. Everything is
implemented by the earlier tasks; this task proves the whole chain in one
process (serve → client → CLI proxy → build push → structural tools without a
source tree → attribution), freezes the tool surface per mode with a golden
test, and writes the guide operators and developers will actually read.

---

## Scope

- `docs/guides/llm-wiki-remote.md`: server (`server.yaml` reference, token, container sketch, **single process**, TLS behind a reverse proxy or `--ssl-*`), client (`remote` block, overlay per env, `WIKITOOLKIT_REMOTE_URL`, `WIKITOOLKIT_TOKEN`), pass-through vs native install (Claude/Codex commands), what works remotely and what is refused, v1 limitations (ledger SQLite on server, per-slice atomicity, no tombstones, no Codex actor header, `merge_blockers` empty on server), troubleshooting by `[remote:<code>]`.
- Link from `docs/guides/llm-wiki-guide.md` "## See Also" and a one-paragraph mention in the CLAUDE.md wiki section is **out of scope** (CLAUDE.md is edited by humans).
- `test_tool_surface_golden.py`: frozen sorted tool-name lists for (a) local stdio (`create_wiki_mcp_server`), (b) server bundle (`include_bulk_tools=True`), (c) pass-through (`tools/list` forwarded) — fails on any drift.
- `test_e2e_remote.py`: boot `build_server_app()` (two SQLite test wikis, `allow_sqlite_for_tests=True`) on an ephemeral port; `RemoteWikiClient` → `wiki_query` on both mounts; 401 / 404; `wiki_remember` with `X-Wiki-Actor` → `asserted_by`; CLI proxy `wikitoolkit query` against it; local `build` of a fixture repo → push → remote `wiki_code_outline` returns pushed symbols (SQLite plane, `read_repair=False`); interop with the official `mcp` SDK client (`importorskip("mcp")`).

**NOT in scope**: any production code change (if the e2e reveals a bug, open a ledger issue / fix in the owning task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/guides/llm-wiki-remote.md` | CREATE | Operator + client guide |
| `docs/guides/llm-wiki-guide.md` | MODIFY | "See Also" link |
| `packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py` | CREATE | Golden tool lists per mode |
| `packages/ai-parrot/tests/knowledge/wiki/test_e2e_remote.py` | CREATE | End-to-end test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.serve import WikiServerConfig, build_server_app                 # TASK-3360/3361
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError                 # TASK-3359
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server, build_wiki_tools, create_proxy_mcp_server   # TASK-3358/3364
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config, load_effective_config
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.cli import wiki                                                  # cli.py:1328
from parrot.knowledge.wiki.claude_code.cli import claude                                    # claude_code/cli.py:50 — `parrot claude install --remote` (TASK-3365)
from parrot.knowledge.wiki.codex.cli import codex                                           # codex/cli.py — `parrot codex install --remote` (TASK-3366)
from click.testing import CliRunner
from aiohttp import web
import aiohttp, asyncio, pytest
```

### Existing Signatures to Use
```python
# docs/guides/llm-wiki-guide.md — headings: "## CLI Reference" :1529 · "## Architecture" :1565 · "## See Also" :1615 (anchor for the link)
# packages/ai-parrot-server/tests/mcp/test_streamable_http_interop.py — precedent: `pytest.importorskip("mcp", reason="requires the mcp extra")` :22 ; async def test_official_sdk_client_roundtrip(server_url) :68 (copy its client-side usage of the official SDK's streamable HTTP client)
# Tool surface today (spec §6): wiki_query, wiki_page, wiki_related, wiki_remember, wiki_note, wiki_status, wiki_symbol_lookup, wiki_code_outline, wiki_blast_radius, ledger_open, ledger_ready, ledger_claim, ledger_close, ledger_context (+ Obsidian tools when a vault exists); server adds wiki_page_hashes, wiki_ingest_batch, wiki_sync_push, wiki_sync_pull
```

### Does NOT Exist
- ~~`docs/guides/llm-wiki-remote.md`~~ — created here.
- ~~`docs/wiki/`~~ directory — guides live in `docs/guides/` (verified listing).
- ~~a pytest-aiohttp plugin dependency~~ — tests boot `web.AppRunner` + `TCPSite(port=0)` by hand, as TASK-3359/3361 tests do.
- ~~an ArangoDB in CI~~ — the e2e uses SQLite planes via `allow_sqlite_for_tests=True`; the ArangoDB symbol plane (TASK-3355) is unit-tested with fakes and documented as "verify against a real server before release".

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "docs/guides/llm-wiki-remote.md", "action": "CREATE" },
    { "path": "docs/guides/llm-wiki-guide.md", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py", "action": "CREATE" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_e2e_remote.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#create_wiki_mcp_server"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The golden lists are **sorted lists of names**, one constant per mode; when a later feature adds a tool the test must be updated deliberately (that is the point).
- The e2e must not need network beyond loopback and must clean up runners/stores (`await runner.cleanup()`).
- Docs: every command shown must exist after this feature (`wikitoolkit serve`, `parrot claude install --remote`, `parrot codex install --remote`); include the exact `[remote:<code>]` table from `remote.py`.

---

## Implementation Blueprint

### Steps (in order)
1. Golden test — *why*: cheapest, catches accidental surface drift from every other task.
2. E2E test — *why*: proves AC1–AC12 together on SQLite planes.
3. Guide + link — *why*: AC16.

### `docs/guides/llm-wiki-remote.md` (CREATE — outline)
```markdown
# LLM Wiki — Remote MCP server (FEAT-569)

## Why
<!-- share the graph without exposing ArangoDB; one deployable; bearer token -->

## Server
### server.yaml reference   <!-- every WikiServerConfig / WikiServerEntry field with defaults -->
### Running                 <!-- WIKITOOLKIT_SERVER_TOKEN=… wikitoolkit serve --config …; pip install 'ai-parrot[wikitoolkit-server]' -->
### Deployment notes        <!-- SINGLE PROCESS (in-memory sessions); TLS at a reverse proxy or --ssl-cert/--ssl-key; ArangoDB reachability; ledger_dir on server disk -->

## Client
### Configure a repository  <!-- .parrot/wiki.json "remote" block; overlay wiki.<env>.json; WIKITOOLKIT_REMOTE_URL; WIKITOOLKIT_TOKEN -->
### What works remotely     <!-- table: command → tool; build/upsert/ingest scan locally then push (--no-push); sync push/pull -->
### What is refused         <!-- --store/--backend, ns *, communities, export, link, memories, audit, ground, ingest-jira, sync obsidian, non-tool ledger subcommands -->
### Errors                  <!-- [remote:token_missing|unauthorized|wiki_not_found|unreachable|timeout|protocol|tool_error|session_expired] → meaning + fix; exit code 2 -->

## Coding agents
### Pass-through (default)  <!-- nothing to reinstall; wikitoolkit mcp forwards; carries X-Wiki-Actor; recommended for Codex -->
### Native HTTP (optional)  <!-- parrot claude install --remote …; parrot codex install --remote … (no actor header → default_actor) -->

## Limitations (v1)
<!-- ledger = SQLite on server; merge_blockers empty on server; per-slice atomicity; no tombstones in sync; structural tools need TASK-3355 on ArangoDB (verify on a real server); no vector search remotely -->
```
**Why**: mirrors the structure of `llm-wiki-guide.md`; each section maps to an AC so reviewers can check completeness.

### `docs/guides/llm-wiki-guide.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^## See Also' docs/guides/llm-wiki-guide.md)
# AFTER — insert below the `## See Also` heading (docs/guides/llm-wiki-guide.md:1615), as the first bullet:
- [Remote MCP server (serve, proxy, install)](llm-wiki-remote.md) — share a wiki over HTTPS without exposing ArangoDB (FEAT-569)
```

### `packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py` (CREATE)
```python
"""Golden tool surface per mode (FEAT-569, design research S11). Update deliberately when a tool is added."""
import pytest
from parrot.knowledge.wiki.mcp_server import build_wiki_tools, create_wiki_mcp_server
from parrot.knowledge.wiki.project import WikiProjectConfig, load_effective_config, save_project_config
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

LOCAL_NO_LEDGER = sorted(["wiki_query", "wiki_page", "wiki_related", "wiki_remember", "wiki_note", "wiki_status",
                          "wiki_symbol_lookup", "wiki_code_outline", "wiki_blast_radius"])
LEDGER = sorted(["ledger_open", "ledger_ready", "ledger_claim", "ledger_close", "ledger_context"])
BULK = sorted(["wiki_page_hashes", "wiki_ingest_batch", "wiki_sync_push", "wiki_sync_pull"])


@pytest.fixture
def repo(tmp_path):
    cfg = WikiProjectConfig(wiki_name="g"); (tmp_path / ".parrot").mkdir(); save_project_config(tmp_path, cfg)
    store = create_wiki_store(cfg.storage_path(tmp_path), wiki_name="g", backend="sqlite")
    import asyncio; asyncio.run(store.upsert_pages([WikiPageRecord(concept_id="c", title="c", body="b")]))
    return tmp_path


def test_local_stdio_surface(repo):
    assert sorted(create_wiki_mcp_server(repo).tools) == LOCAL_NO_LEDGER   # tmp_path has no git root → no ledger tools


def test_server_surface(repo):
    b = build_wiki_tools(repo, load_effective_config(repo).config, ledger_dir=repo / ".parrot" / "ledger", read_repair=False, include_bulk_tools=True)
    assert sorted(t.name for t in b.tools) == sorted(LOCAL_NO_LEDGER + LEDGER + BULK)
```
**Why**: two frozen lists cover AC3 and AC14 at once; the pass-through surface equals the server surface by construction (asserted in the e2e).

### `packages/ai-parrot/tests/knowledge/wiki/test_e2e_remote.py` (CREATE — skeleton)
```python
"""End-to-end: serve two SQLite wikis → client → CLI proxy → build push → structural tools without source tree."""
import asyncio, os, pytest, aiohttp
from aiohttp import web
from click.testing import CliRunner
pytest.importorskip("parrot.mcp.transports.streamable_http")
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError
from parrot.knowledge.wiki.serve import WikiServerConfig, build_server_app
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store


@pytest.fixture
async def served(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKITOOLKIT_SERVER_TOKEN", "t0k3n"); monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    # FILL IN: two wiki dirs a/b with .parrot/wiki.json + seeded SQLite planes (copy TASK-3361's fixture); build_server_app(WikiServerConfig(wikis=..., allow_sqlite_for_tests=True));
    #          AppRunner/TCPSite(port=0); yield (base_url, paths); cleanup — bounded by AC1
    raise NotImplementedError


async def test_query_both_mounts_auth_404(served): ...            # FILL IN: AC1/AC2 — 200 both, 401 bad token, 404 unknown wiki
async def test_actor_attribution(served): ...                    # FILL IN: AC4 — X-Wiki-Actor human:alice → asserted_by; no header → agent:unknown
def test_cli_proxy_query(served, tmp_path, monkeypatch): ...      # FILL IN: AC7 — client repo with remote block, no wiki.db, `wikitoolkit query` exit 0
def test_build_push_then_remote_outline(served, tmp_path): ...   # FILL IN: AC5/AC10 — fixture repo with one .py; `wikitoolkit build`; remote wiki_code_outline("file:pkg/mod.py") lists its symbols; server root has no pkg/ dir
def test_native_installers_point_at_served_url(served, tmp_path, monkeypatch): ...   # FILL IN: AC13 — `parrot claude install --remote --remote-url <base>/a` writes the http entry (claude_code/cli.py) and `parrot codex install --remote --remote-url <base>/a` writes url + bearer_token_env_var (codex/cli.py); a RemoteWikiClient built from the written URL answers wiki_status
async def test_official_sdk_interop(served):                      # FILL IN: importorskip("mcp"); mirror packages/ai-parrot-server/tests/mcp/test_streamable_http_interop.py:68 with Authorization header
    pytest.importorskip("mcp", reason="requires the mcp extra")
```
**Why**: each test names the AC it proves so `/sdd-done` can map evidence to criteria.

### FILL IN checklist
- [ ] E2E fixtures and the five test bodies — bounded by the listed ACs.
- [ ] Guide sections filled from the shipped code (no invented flags).
- [ ] "See Also" link.

---

## Acceptance Criteria

- [ ] `test_tool_surface_golden.py` passes and its lists equal spec §6's tool inventory (+ bulk on the server).
- [ ] `test_e2e_remote.py` passes on loopback with SQLite planes: both mounts answer, 401/404 behave, attribution works, CLI proxy works with no local plane, a local `build` pushes and the remote outline shows the symbols with no source tree on the server; SDK interop passes when `mcp` is installed and is skipped otherwise.
- [ ] `docs/guides/llm-wiki-remote.md` covers every item in Scope; every command in it exists (`wikitoolkit serve --help`, `parrot claude install --help`, `parrot codex install --help` show the flags).
- [ ] `docs/guides/llm-wiki-guide.md` links the new guide under "See Also".
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki -k "remote or serve or bulk or actor or proxy or golden" -q` green (AC17).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_e2e_remote.py -q`

---

## Test Specification

See the two CREATE blocks above; they are the test specification.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3355, 3361, 3363, 3364, 3365, 3366 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — run `wikitoolkit serve --help` and both installers' `--help` before writing docs
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
