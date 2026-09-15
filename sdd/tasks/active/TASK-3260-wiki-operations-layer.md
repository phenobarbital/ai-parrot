# TASK-3260: Framework-free wiki operations layer

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 relocates the wiki `AbstractTool` subclasses to `parrot_tools.wiki`, and
Module 5 needs the **same** operations registrable on an `mcp`-SDK stdio server without
`parrot.tools`. Both require the tool *logic* to live in a framework-free module first.

This task extracts that logic out of `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
into a NEW module `parrot/knowledge/wiki/operations.py` that imports nothing from
`parrot.tools.*`. `wiki/tools.py` keeps every `AbstractTool` class (same class names,
`name`, `description`, `args_schema`) but each `_execute` becomes a thin delegate. Nothing
moves between distributions yet — that is TASK-3262. Behaviour, tool names and input
schemas must stay byte-identical, which this task pins with a golden file generated
**before any edit**.

Design brief decision D5 (binding). Spec §7 gotcha: `_scoped_store` /
`_unknown_namespace_error` must stay on the framework-free side — they move to
`operations.py`, never to `parrot_tools`.

---

## Scope

- Generate the golden schema file for the 12 wiki + ledger + vault tools from the **unmodified** code (Step 1).
- Create `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` with:
  `OperationResult`, `WikiOperation`, module `logger`, the moved helpers
  (`_scoped_store`, `_reject_foreign_id`, `_LEDGER_KIND_PREFIXES`, `_qualify_ledger_target`,
  `_unknown_namespace_error`, `_QUERY_FETCH_LIMIT`, `_NAMESPACE_DESC`), all 12 input models,
  name/description constants per tool, one handler coroutine per tool, and
  `build_wiki_operations()` / `build_vault_ingest_operation()`.
- Rewrite `wiki/tools.py` so it imports helpers + input models from `operations.py` and each
  tool's `_execute` delegates to its handler, converting `OperationResult` → `ToolResult`.
- Repoint the two `WikiBookkeeper.log_operation` patch strings in
  `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py` (:113, :150) to
  `parrot.knowledge.wiki.operations.WikiBookkeeper.log_operation`.
- Add unit tests calling the handlers directly with `AsyncMock` stores.

**NOT in scope**:
- Structural tools (`wiki/structural/tools.py`) — TASK-3261.
- Moving any `AbstractTool` class to `parrot_tools`, deleting `wiki/tools.py`, touching
  `mcp_server.py` — TASK-3262 / TASK-3265.
- Fixing the pre-existing `IssueKind(kind)` call in `LedgerReadyTool` (`IssueKind` is a
  `typing.Literal`, not callable — tools.py:677) — move it verbatim; record in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/fixtures/wiki_tool_schemas.golden.json` | CREATE | Golden name/description/inputSchema for 12 tools, generated BEFORE edits |
| `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` | CREATE | Framework-free operations layer |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | Tools become thin delegates; helpers/models imported from operations |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py` | MODIFY | Repoint two patch strings |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_operations.py` | CREATE | Handler-level unit tests + golden self-check |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `63cc2198e` on 2026-09-15.

### Verified Imports
```python
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                 # bookkeeper.py:31 (log_operation :175)
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, pack_results  # context.py:115, :208
from parrot.knowledge.wiki.context import split_namespaced_id              # context.py:54 (lazy import inside _reject_foreign_id)
from parrot.knowledge.wiki.project import WikiProjectConfig                # project.py:379 (storage_path :519, body_max_chars :417, max_file_kb :418)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens  # store.py:525, :409, :318
from parrot.knowledge.wiki.federation import FederatedWikiStore            # federation.py:622 (lazy, inside _scoped_store; .scoped :712)
from parrot.knowledge.wiki.ledger.service import LedgerService             # ledger/service.py:96 — TYPE_CHECKING only
from parrot.knowledge.wiki.ledger.events import IssueKind                  # ledger/events.py:21 — Literal alias, lazy inside ledger_ready
# lazy, inside vault_ingest only (as today, tools.py:512-521):
from parrot.knowledge.wiki.cli import _ingest_files, _open_sources, _prune_removed  # cli.py:683, :455, :959
from parrot.knowledge.wiki.project import resolve_vault_dir, wiki_write_lock        # project.py:638, :71
from parrot.knowledge.wiki.vault_scan import scan_vault                              # vault_scan.py:118
# golden-script only (test/tooling side, never in operations.py):
from parrot.knowledge.wiki.tools import create_wiki_tools, VaultIngestTool           # tools.py:741, :482
from parrot.mcp.adapter import MCPToolAdapter                                       # parrot/mcp/adapter.py:8 (to_mcp_tool_definition :27)
from parrot.tools.abstract import AbstractTool, ToolResult                          # tools/abstract.py:281, :250
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py  (785 lines)
from parrot.tools.abstract import AbstractTool, ToolResult                       # line 22
def _scoped_store(store: BaseWikiStore, namespace: str | None) -> BaseWikiStore  # line 25 (raises KeyError)
def _reject_foreign_id(store: BaseWikiStore, page_id: str) -> str | None         # line 51
_LEDGER_KIND_PREFIXES = ("issue:", "task:", "spec:", "insight:")                 # line 81
def _qualify_ledger_target(target: str) -> str                                   # line 84
def _unknown_namespace_error(store: BaseWikiStore, namespace: str) -> str        # line 108
_QUERY_FETCH_LIMIT = 30                                                          # line 117
_NAMESPACE_DESC = (...)                                                          # line 120
class WikiQueryInput / WikiPageInput / WikiRelatedInput / WikiRememberInput
      / WikiNoteInput / VaultIngestInput / WikiStatusInput(BaseModel)            # lines 127,142,150,158,168,173,187

class WikiQueryTool(AbstractTool)      # 191  name "wiki_query"   __init__(store) :207
    async def _execute(self, question: str, budget_tokens: int = DEFAULT_BUDGET_TOKENS,
                       namespace: str | None = None, include_symbols: bool = False) -> str   # :211
class WikiPageTool(AbstractTool)       # 233  "wiki_page"    __init__(store) :245
    async def _execute(self, page_id: str, namespace: str | None = None) -> ToolResult    # :249
class WikiRelatedTool(AbstractTool)    # 270  "wiki_related" __init__(store) :282
    async def _execute(self, page_id: str, namespace: str | None = None) -> ToolResult    # :286
class WikiRememberTool(AbstractTool)   # 302  "wiki_remember" __init__(store, storage_dir: Path | None = None) :313
    async def _execute(self, fact: str, category: str = "note", title: str | None = None,
                       link_page_id: str | None = None, rel: str | None = "references",
                       derived_from: str | None = None, about: list[str] | None = None) -> ToolResult  # :318
    # uses self.logger.warning(...) on OSError from WikiBookkeeper().log_operation
class WikiNoteTool(AbstractTool)       # 401  "wiki_note"    __init__(store, storage_dir: Path | None = None) :408
    async def _execute(self, page_id: str, text: str) -> ToolResult                       # :413
class WikiStatusTool(AbstractTool)     # 466  "wiki_status"  __init__(store) :473
    async def _execute(self) -> ToolResult                                                 # :477
class VaultIngestTool(AbstractTool)    # 482  "vault_ingest" __init__(store, root: Path, config: WikiProjectConfig) :494
    async def _execute(self, vault_path: str | None = None, force: bool = False, **kwargs) -> ToolResult  # :505
if TYPE_CHECKING: from parrot.knowledge.wiki.ledger.service import LedgerService           # :595-596
class LedgerOpenInput / LedgerReadyInput / LedgerClaimInput / LedgerCloseInput / LedgerContextInput(BaseModel)  # 599,608,612,616,621
class LedgerOpenTool(AbstractTool)     # 626 "ledger_open"    __init__(ledger_service) :633
    async def _execute(self, title, body, kind="bug", severity="minor", discovered_from="", about=None) -> ToolResult  # :637
class LedgerReadyTool(AbstractTool)    # 661 "ledger_ready"   _execute(self, kind: str | None = None) :672
class LedgerClaimTool(AbstractTool)    # 684 "ledger_claim"   _execute(self, issue_id: str) :695
class LedgerCloseTool(AbstractTool)    # 703 "ledger_close"   _execute(self, issue_id: str, reason: str) :714
class LedgerContextTool(AbstractTool)  # 722 "ledger_context" _execute(self, file_paths: list[str], max_tokens: int = 3000) :733
def create_wiki_tools(store: BaseWikiStore, root: Path | None = None, config: WikiProjectConfig | None = None,
                      ledger_service: Union["LedgerService", None] = None) -> list[AbstractTool]   # :741
    # storage_dir = config.storage_path(root) if root is not None and config is not None else None
    # order: Query, Page, Related, Remember(storage_dir), Note(storage_dir), Status, then 5 ledger tools iff ledger_service

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):  # :250 — success: bool=True, status: str="success", result: Any, error: str|None=None, metadata: dict
class AbstractTool:           # :281 — self.logger = logging.getLogger(f"{self.name}.Tool") (:413)

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
async def open_issue(...) :166; async def ready_work(self, kind: IssueKind | None = None) :199
async def claim(self, issue_id: str, actor: str) -> bool :209; async def close_issue(self, issue_id, reason, actor) -> bool :235
async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str :247

# Consumers that must keep working unchanged after this task:
# packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py:29
from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error   # (keep re-exported from tools.py)
# tests/knowledge/wiki/test_ledger_tools.py:6, tests/knowledge/wiki/test_mcp_server_ledger.py:8,
# tests/knowledge/wiki/structural/test_tools.py:17, packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py:4,:317
#   (imports WikiPageInput/WikiQueryInput/WikiRelatedInput from parrot.knowledge.wiki.tools — keep re-exported)
# packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py:10
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.operations`~~ / ~~`OperationResult`~~ / ~~`WikiOperation`~~ / ~~`build_wiki_operations`~~ — created by this task.
- ~~`packages/ai-parrot/tests/knowledge/wiki/fixtures/wiki_tool_schemas.golden.json`~~ — created by this task (the `fixtures/` dir exists, holding `jira/`).
- ~~`store.add_note()`~~ — notes are read-modify-write on the page body (tools.py:414-438).
- ~~`AbstractTool.get_schema()` as the MCP schema source~~ — MCP uses `args_schema.model_json_schema()` via `MCPToolAdapter.to_mcp_tool_definition`.
- ~~`IssueKind` as an Enum~~ — it is `Literal["bug","tech_debt","feature_gap","vulnerability"]` (events.py:21).
- ~~`parrot_tools.wiki`~~ — not yet (TASK-3262).

---

## Implementation Notes

### Key Constraints
- `operations.py` must import NOTHING from `parrot.tools`, `parrot.mcp`, `parrot_tools`,
  `parrot.clients`, `parrot.stores`, `parrot.loaders`, `parrot.embeddings` at module level.
- Byte-identical: tool `name`, `description`, and `args_schema.model_json_schema()` — the
  input model classes move *as-is* (same class names, field order, `Field` descriptions);
  `model_json_schema()` embeds the class name as `title`, so never rename a model.
- Handlers replace `self.logger` with the module `logger` (name changes from `"<tool>.Tool"`
  to `"parrot.knowledge.wiki.operations"` — acceptable; note it).
- Handlers keep the exact return type of today's `_execute`: `wiki_query` returns `str`;
  every other handler returns `OperationResult` with the same `result`/`error` payloads.
- Async throughout; `vault_ingest` keeps `asyncio.to_thread(scan_vault, ...)` and the lazy
  imports (stdout-clean MCP import path).

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/adapter.py:108` — how `ToolResult` reaches MCP (str/dict/error).
- `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py:44-110` — module style precedent.

---

## Implementation Blueprint

### Steps (in order)
1. **Generate the golden file BEFORE touching any source file** (snippet below) — *why*: the only trustworthy "pre-move" schema is the current code; generating after the edit would ratify any drift.
2. Create `operations.py` blocks A→D — *why*: the handler layer must exist before tools can delegate to it.
3. Move helpers + input models verbatim from tools.py into operations.py (cut, don't copy) — *why*: one definition; duplicates would diverge and break schema identity.
4. Move each `_execute` body into its handler verbatim, then apply the mechanical swaps: `ToolResult(` → `OperationResult(`, `self._store` → `store`, `self._storage_dir` → `storage_dir`, `self._root` → `root`, `self._config` → `config`, `self._ledger_service` → `service`, `self.logger` → `logger` — *why*: logic must not change, only its host.
5. Rewrite tools.py per its blocks: import from operations, add `_to_tool_result`, make every `_execute` delegate — *why*: keeps all existing consumers (structural/tools.py:29, tests, mcp_server.py) green until TASK-3262.
6. Repoint the two patch strings in `test_wiki_tools.py` — *why*: `WikiBookkeeper` is now looked up in `operations`.
7. Write `test_wiki_operations.py`; run tests (commands in Acceptance Criteria) — *why*: prove handlers are callable without `parrot.tools`.

### Step 1 — golden generation (run from repo root, before any edit)
```python
# scratch script — run once:  PYTHONPATH=packages/ai-parrot/src python gen_golden.py
import contextlib, json, sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

with contextlib.redirect_stdout(sys.stderr):  # parrot.mcp import prints to stdout
    from parrot.mcp.adapter import MCPToolAdapter
    from parrot.knowledge.wiki.project import WikiProjectConfig
    from parrot.knowledge.wiki.tools import VaultIngestTool, create_wiki_tools

store = AsyncMock()
tools = create_wiki_tools(store, ledger_service=MagicMock())          # 6 wiki + 5 ledger
tools.append(VaultIngestTool(store, root=Path("."), config=WikiProjectConfig()))
golden = sorted((MCPToolAdapter(t).to_mcp_tool_definition() for t in tools), key=lambda d: d["name"])
assert len(golden) == 12, len(golden)
out = Path("packages/ai-parrot/tests/knowledge/wiki/fixtures/wiki_tool_schemas.golden.json")
out.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
```
**Why**: TASK-3261 appends the 3 structural tools to this same file (also before its edit);
TASK-3262 compares the relocated `parrot_tools.wiki` tools against it. Do not commit the script.

### `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` (CREATE) — block A: header, types, helpers
```python
"""Framework-free wiki operations (FEAT-540 Module 3).

The logic behind every wiki MCP/agent tool, with no dependency on
``parrot.tools``. ``parrot_tools.wiki`` wraps these as ``AbstractTool``s;
the ``mcp``-SDK stdio server registers them directly.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, pack_results
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens

if TYPE_CHECKING:
    from parrot.knowledge.wiki.ledger.service import LedgerService

logger = logging.getLogger(__name__)


class OperationResult(BaseModel):
    """Transport-neutral result of one wiki operation (mirrors ToolResult's core fields)."""

    success: bool = True
    status: str = "success"
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class WikiOperation:
    """One registrable operation: its public tool name, description, input schema and bound handler."""

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable[..., Awaitable[str | OperationResult]]
    requires_confirmation: bool = False


def _error(message: str) -> OperationResult:
    """Build the error result every handler returns on a refused/failed call."""
    return OperationResult(success=False, status="error", result=None, error=message)


# MOVE VERBATIM from tools.py (cut): _scoped_store (:25), _reject_foreign_id (:51),
# _LEDGER_KIND_PREFIXES (:81), _qualify_ledger_target (:84), _unknown_namespace_error (:108),
# _QUERY_FETCH_LIMIT (:117), _NAMESPACE_DESC (:120). Keep their docstrings and lazy imports.
```
**Why this shape**: `OperationResult` field names/defaults equal `ToolResult`'s so the
conversion is a field copy. `_error` is optional sugar — the moved bodies may keep the
explicit `OperationResult(success=False, status="error", result=None, error=...)` form.

### `operations.py` — block B: input models + name/description constants
```python
# MOVE VERBATIM from tools.py (cut): WikiQueryInput (:127), WikiPageInput (:142),
# WikiRelatedInput (:150), WikiRememberInput (:158), WikiNoteInput (:168),
# VaultIngestInput (:173), WikiStatusInput (:187), LedgerOpenInput (:599),
# LedgerReadyInput (:608), LedgerClaimInput (:612), LedgerCloseInput (:616),
# LedgerContextInput (:621). Class names and field order MUST NOT change.

WIKI_QUERY_NAME = "wiki_query"
WIKI_PAGE_NAME = "wiki_page"
WIKI_RELATED_NAME = "wiki_related"
WIKI_REMEMBER_NAME = "wiki_remember"
WIKI_NOTE_NAME = "wiki_note"
WIKI_STATUS_NAME = "wiki_status"
VAULT_INGEST_NAME = "vault_ingest"
LEDGER_OPEN_NAME = "ledger_open"
LEDGER_READY_NAME = "ledger_ready"
LEDGER_CLAIM_NAME = "ledger_claim"
LEDGER_CLOSE_NAME = "ledger_close"
LEDGER_CONTEXT_NAME = "ledger_context"

# MOVE VERBATIM each tool's `description = (...)` expression into a constant:
# WIKI_QUERY_DESCRIPTION (tools.py:197-204), WIKI_PAGE_DESCRIPTION (:238-242),
# WIKI_RELATED_DESCRIPTION (:275-279), WIKI_REMEMBER_DESCRIPTION (:307-310),
# WIKI_NOTE_DESCRIPTION (:405), WIKI_STATUS_DESCRIPTION (:470),
# VAULT_INGEST_DESCRIPTION (:486-491), LEDGER_OPEN_DESCRIPTION (:630),
# LEDGER_READY_DESCRIPTION (:665), LEDGER_CLAIM_DESCRIPTION (:688),
# LEDGER_CLOSE_DESCRIPTION (:707), LEDGER_CONTEXT_DESCRIPTION (:726).
# FILL IN: exact constant values — bounded by golden-file byte identity (Step 1).
```
**Why**: one source of truth for name + description, shared by the TASK-3262 wrappers and the
TASK-3265 SDK server. The golden test fails on any retyping slip.

### `operations.py` — block C: handlers (signatures fixed; bodies moved)
```python
async def wiki_query(
    store: BaseWikiStore, *, question: str, budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    namespace: str | None = None, include_symbols: bool = False,
) -> str:
    """Search the plane; returns packed text (unknown namespace → error text)."""
    # MOVE VERBATIM: WikiQueryTool._execute body (tools.py:218-230)
    raise NotImplementedError


async def wiki_page(store: BaseWikiStore, *, page_id: str, namespace: str | None = None) -> OperationResult:
    """Read one page with body."""
    # MOVE VERBATIM: WikiPageTool._execute body (tools.py:250-267)
    raise NotImplementedError


async def wiki_related(store: BaseWikiStore, *, page_id: str, namespace: str | None = None) -> OperationResult:
    """Neighbours of a page, wrapped as {"neighbors": [...]}."""
    # MOVE VERBATIM: WikiRelatedTool._execute body (tools.py:287-299)
    raise NotImplementedError


async def wiki_remember(
    store: BaseWikiStore, *, storage_dir: Path | None = None, fact: str, category: str = "note",
    title: str | None = None, link_page_id: str | None = None, rel: str | None = "references",
    derived_from: str | None = None, about: list[str] | None = None,
) -> OperationResult:
    """Upsert a memory page (+ provenance edges, + audit log when storage_dir)."""
    # MOVE VERBATIM: WikiRememberTool._execute body (tools.py:327-398)
    raise NotImplementedError


async def wiki_note(store: BaseWikiStore, *, storage_dir: Path | None = None, page_id: str, text: str) -> OperationResult:
    """Append a dated note to a page body."""
    # MOVE VERBATIM: WikiNoteTool._execute body (tools.py:414-463)
    raise NotImplementedError


async def wiki_status(store: BaseWikiStore) -> OperationResult:
    """Plane statistics."""
    # MOVE VERBATIM: WikiStatusTool._execute body (tools.py:478-479)
    raise NotImplementedError


async def vault_ingest(
    store: BaseWikiStore, *, root: Path, config: WikiProjectConfig,
    vault_path: str | None = None, force: bool = False, **kwargs: Any,
) -> OperationResult:
    """(Re)build the plane from an Obsidian vault; lazy imports stay inside."""
    # MOVE VERBATIM: VaultIngestTool._execute body (tools.py:511-589)
    raise NotImplementedError

# Ledger handlers — first positional param `service: "LedgerService"`, then keyword-only args
# exactly as the tools' _execute signatures (tools.py:637, :672, :695, :714, :733):
#   ledger_open(service, *, title, body, kind="bug", severity="minor", discovered_from="", about=None)
#   ledger_ready(service, *, kind=None)          ledger_claim(service, *, issue_id)
#   ledger_close(service, *, issue_id, reason)   ledger_context(service, *, file_paths, max_tokens=3000)
# MOVE VERBATIM each body (incl. the try/except → error result and the lazy IssueKind import).
```
**Why**: keyword-only arguments after the bound first parameter let `functools.partial` bind
`store`/`service` (+ `storage_dir`/`root`/`config`) while MCP/tool arguments arrive as kwargs.

### `operations.py` — block D: builders
```python
def build_wiki_operations(
    store: BaseWikiStore,
    root: Path | None = None,
    config: WikiProjectConfig | None = None,
    ledger_service: LedgerService | None = None,
) -> list[WikiOperation]:
    """Bind the wiki (and, with ``ledger_service``, ledger) operations to ``store``.

    Same order and ledger condition as ``create_wiki_tools``.
    """
    storage_dir = config.storage_path(root) if root is not None and config is not None else None
    ops = [
        WikiOperation(WIKI_QUERY_NAME, WIKI_QUERY_DESCRIPTION, WikiQueryInput, partial(wiki_query, store)),
        WikiOperation(WIKI_PAGE_NAME, WIKI_PAGE_DESCRIPTION, WikiPageInput, partial(wiki_page, store)),
        WikiOperation(WIKI_RELATED_NAME, WIKI_RELATED_DESCRIPTION, WikiRelatedInput, partial(wiki_related, store)),
        WikiOperation(
            WIKI_REMEMBER_NAME, WIKI_REMEMBER_DESCRIPTION, WikiRememberInput,
            partial(wiki_remember, store, storage_dir=storage_dir),
        ),
        WikiOperation(
            WIKI_NOTE_NAME, WIKI_NOTE_DESCRIPTION, WikiNoteInput, partial(wiki_note, store, storage_dir=storage_dir)
        ),
        WikiOperation(WIKI_STATUS_NAME, WIKI_STATUS_DESCRIPTION, WikiStatusInput, partial(wiki_status, store)),
    ]
    if ledger_service is not None:
        # FILL IN: append the 5 ledger WikiOperations in tools.py:774-782 order — bounded by create_wiki_tools order
        pass
    return ops


def build_vault_ingest_operation(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> WikiOperation:
    """Bind ``vault_ingest`` to a project; registered only when a vault resolves."""
    return WikiOperation(
        VAULT_INGEST_NAME, VAULT_INGEST_DESCRIPTION, VaultIngestInput,
        partial(vault_ingest, store, root=root, config=config),
    )
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY) — block E: imports
```python
# occurrences: 1 (verified: grep -c '^from parrot.tools.abstract import AbstractTool, ToolResult$' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# REPLACE lines 10-22 (stdlib/pydantic/wiki imports) and DELETE the moved helpers/constants/input models
# (lines 25-189 and 595-624) with:
from pathlib import Path
from typing import TYPE_CHECKING, Union

from parrot.knowledge.wiki import operations as ops
from parrot.knowledge.wiki.operations import (  # noqa: F401 — re-exported for existing importers
    LedgerClaimInput, LedgerCloseInput, LedgerContextInput, LedgerOpenInput, LedgerReadyInput,
    OperationResult, VaultIngestInput, WikiNoteInput, WikiPageInput, WikiQueryInput,
    WikiRelatedInput, WikiRememberInput, WikiStatusInput,
    _NAMESPACE_DESC, _qualify_ledger_target, _reject_foreign_id, _scoped_store, _unknown_namespace_error,
)
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.abstract import AbstractTool, ToolResult

if TYPE_CHECKING:
    from parrot.knowledge.wiki.ledger.service import LedgerService


def _to_tool_result(outcome: OperationResult) -> ToolResult:
    """Copy an OperationResult into the framework ToolResult."""
    return ToolResult(**outcome.model_dump())
```
**Why**: `structural/tools.py:29` and five test modules import helpers/models from
`parrot.knowledge.wiki.tools`; re-exporting keeps them green until TASK-3261/3262 repoint them.

### `tools.py` — block F: delegate pattern (apply to all 12 tools)
```python
class WikiPageTool(AbstractTool):
    """Read a full wiki page by ID — file summaries, API outlines, content.
    Use IDs returned by wiki_query."""

    name = ops.WIKI_PAGE_NAME
    description = ops.WIKI_PAGE_DESCRIPTION
    args_schema = WikiPageInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self, page_id: str, namespace: str | None = None) -> ToolResult:
        return _to_tool_result(await ops.wiki_page(self._store, page_id=page_id, namespace=namespace))

# WikiQueryTool._execute: `return await ops.wiki_query(self._store, question=..., ...)`  (str, no conversion)
# WikiRememberTool / WikiNoteTool: pass storage_dir=self._storage_dir
# VaultIngestTool: pass root=self._root, config=self._config, vault_path=..., force=..., **kwargs
# Ledger tools: pass self._ledger_service as the first positional argument
# Keep every class docstring, __init__ signature and create_wiki_tools unchanged.
```

### `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '"parrot.knowledge.wiki.tools.WikiBookkeeper.log_operation",' packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py)
# REPLACE both (lines 113 and 150):
            "parrot.knowledge.wiki.operations.WikiBookkeeper.log_operation",
```

### FILL IN checklist
- [ ] Golden file generated from unmodified code, 12 entries, committed.
- [ ] `operations.py` block B — description constants copied verbatim; bounded by golden identity.
- [ ] `operations.py` block C — every handler body moved with only the mechanical swaps of Step 4.
- [ ] `build_wiki_operations` — ledger operations appended in create_wiki_tools order.
- [ ] `tools.py` — all 12 `_execute` methods delegate; no logic remains in tools.py.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/knowledge/wiki/fixtures/wiki_tool_schemas.golden.json` exists, generated before edits, 12 tools.
- [ ] `operations.py` has no module-level import of `parrot.tools`, `parrot.mcp`, `parrot_tools`, `parrot.clients`, `parrot.stores`, `parrot.loaders`, `parrot.embeddings`.
- [ ] `python -c "import sys, parrot.knowledge.wiki.operations; assert 'parrot.tools.abstract' not in sys.modules"` succeeds.
- [ ] Tool names, descriptions and MCP input schemas from `create_wiki_tools` + `VaultIngestTool` equal the golden file.
- [ ] `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_operations.py packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py -v` passes.
- [ ] `PYTHONPATH=packages/ai-parrot/src pytest tests/knowledge/wiki/test_ledger_tools.py tests/knowledge/wiki/test_mcp_server_ledger.py tests/knowledge/wiki/structural/test_tools.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/operations.py packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_wiki_operations.py
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.wiki import operations as ops

GOLDEN = Path(__file__).parent / "fixtures" / "wiki_tool_schemas.golden.json"


@pytest.fixture
def store():
    s = AsyncMock()
    s.search_fts.return_value = [{"concept_id": "p1", "title": "T", "score": 0.9}]
    s.get_page.return_value = {"concept_id": "p1", "title": "T", "body": "B"}
    s.neighbors.return_value = []
    s.stats.return_value = {"pages": 1}
    return s


def test_operations_import_is_framework_free():
    code = "import sys, parrot.knowledge.wiki.operations; print('parrot.tools.abstract' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_build_wiki_operations_order_and_ledger_condition(store):
    names = [op.name for op in ops.build_wiki_operations(store)]
    assert names == ["wiki_query", "wiki_page", "wiki_related", "wiki_remember", "wiki_note", "wiki_status"]
    with_ledger = ops.build_wiki_operations(store, ledger_service=MagicMock())
    assert len(with_ledger) == 11


@pytest.mark.asyncio
async def test_wiki_page_not_found_returns_error(store):
    store.get_page.return_value = None
    result = await ops.wiki_page(store, page_id="missing")
    assert result.success is False and "Page not found" in result.error


@pytest.mark.asyncio
async def test_wiki_query_returns_text(store):
    assert isinstance(await ops.wiki_query(store, question="q"), str)


def test_operation_schemas_match_golden(store):
    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    op_list = ops.build_wiki_operations(store, ledger_service=MagicMock())
    op_list.append(ops.build_vault_ingest_operation(store, Path("."), MagicMock()))
    for op in op_list:
        # FILL IN: compare description + args_schema.model_json_schema() against golden[op.name] — bounded by AC-4
        assert op.name in golden
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md` §3 Module 3, §7) and design brief D5.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-grep every line number above; if drifted, update the contract first.
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`.
5. **Run Step 1 (golden) before editing anything.**
6. **Implement** from the blueprint; complete every `FILL IN`.
7. Run tests with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable against the main checkout). Note: CI collects the repo-root `tests/` tree — run the root-tree wiki tests listed in the ACs too.
8. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
