# TASK-3352: `actor.py` ContextVar + replace the hardcoded `"agent:mcp"` identities (M2a)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (actor part), AC4. Today the MCP tools assert every write as
the literal `"agent:mcp"` (five sites in `tools.py`). The remote server must
attribute writes to the `X-Wiki-Actor` header (brainstorm decision), and the
only way to reach the tools from an aiohttp middleware without changing every
tool signature is a request-scoped `ContextVar`. This task creates that
ContextVar (`current_actor()` / `actor_scope()`) and swaps the five literals
for `current_actor()`. The default stays `"agent:mcp"` so the local stdio
server's attribution is byte-identical (AC14).

---

## Scope

- Create `parrot/knowledge/wiki/actor.py` with `_ACTOR: ContextVar[str | None]`, `current_actor(default="agent:mcp") -> str`, and `actor_scope(actor)` context manager (set → yield → reset token).
- In `tools.py`: import `current_actor` and replace the 5 `"agent:mcp"` sites (lines 352, 446, 654, 697, 716) with `current_actor()`.
- Unit tests for the ContextVar and for attribution through `WikiRememberTool` / `LedgerOpenTool`.

**NOT in scope**: the HTTP middleware that sets the actor (TASK-3360), header validation regex (TASK-3360), CLI identity (`_authoring_identity` stays as is).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/actor.py` | CREATE | ContextVar + helpers |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | import + 5 literal replacements |
| `packages/ai-parrot/tests/knowledge/wiki/test_actor.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from contextlib import contextmanager
from contextvars import ContextVar
from parrot.knowledge.wiki.tools import WikiRememberTool, WikiNoteTool, LedgerOpenTool, LedgerClaimTool, LedgerCloseTool   # tools.py:302, :401, :626, :~684, :~703
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store     # store.py:409, :2247
from parrot.tools.abstract import AbstractTool, ToolResult                     # already imported in tools.py:22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                    # :18  (import anchor, 1 occurrence)
class WikiRememberTool(AbstractTool):                                          # :302
    def __init__(self, store: BaseWikiStore, storage_dir: Path | None = None)  # :313
    async def _execute(...)                                                    # :318-398; writes WikiPageRecord(..., origin="memory", asserted_by="agent:mcp")  ← :352
class WikiNoteTool(AbstractTool):                                              # :401 — asserted_by="agent:mcp" ← :446
class LedgerOpenTool(AbstractTool):                                            # :626 — open_issue(..., actor="agent:mcp") ← :654
class LedgerClaimTool(AbstractTool):   # claim(issue_id, "agent:mcp")           ← :697
class LedgerCloseTool(AbstractTool):   # close_issue(issue_id, reason, "agent:mcp") ← :716
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService: open_issue(..., actor: str) :166 · claim(issue_id, actor) :209 · close_issue(issue_id, reason, actor) :235
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.actor`~~ — created here.
- ~~`WikiRememberTool(..., actor=...)`~~ — do NOT add constructor/argument parameters for the actor; the ContextVar is the only channel.
- ~~`AbstractTool.actor`~~ / ~~`ToolResult.actor`~~ — no such attributes.
- ~~`asyncio.current_task().context`~~-style hacks — use `contextvars` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/actor.py", "action": "CREATE" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_actor.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiRememberTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiNoteTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#LedgerOpenTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `actor_scope(None)` must be a no-op (yield without setting) so callers can pass an optional header value.
- Reset with the token in `finally` — concurrent requests must never inherit another request's actor (design research S4).
- After this task `grep -c '"agent:mcp"' tools.py` must be **0** and `actor.py` holds the only default literal (AC4).

---

## Implementation Blueprint

### Steps (in order)
1. Create `actor.py` — *why*: one module, no parrot imports, importable from the HTTP middleware and the tools alike.
2. Add the import to `tools.py` below the `WikiBookkeeper` import — *why*: keeps the `parrot.knowledge.wiki.*` imports grouped; anchor is unique.
3. Replace the five literals — *why*: every write path (memory pages, notes, ledger open/claim/close) must read the request actor.
4. Tests; `ruff check` both files.

### `packages/ai-parrot/src/parrot/knowledge/wiki/actor.py` (CREATE)
```python
"""Request-scoped write identity for the wiki tools (FEAT-569).

The MCP tools used to hardcode ``"agent:mcp"``. The remote server sets the
caller's ``X-Wiki-Actor`` here per request; the local stdio server sets
nothing and keeps the historical default.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_ACTOR = "agent:mcp"

_ACTOR: ContextVar[str | None] = ContextVar("wiki_actor", default=None)


def current_actor(default: str = DEFAULT_ACTOR) -> str:
    """Return the identity asserting the current write.

    Args:
        default: Value when no actor was set for this context.

    Returns:
        The actor string, e.g. ``"human:jlara"`` or ``"agent:mcp"``.
    """
    return _ACTOR.get() or default


@contextmanager
def actor_scope(actor: str | None) -> Iterator[None]:
    """Set the actor for the enclosed block; ``None`` leaves the context untouched.

    Args:
        actor: Identity to assert, or ``None`` for a no-op scope.
    """
    if actor is None:
        yield
        return
    token = _ACTOR.set(actor)
    try:
        yield
    finally:
        _ACTOR.reset(token)
```
**Why this shape**: spec M2 skeleton verbatim; the `None` short-circuit lets the middleware pass the raw optional header. No validation here — the server validates the header format (TASK-3360).

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# AFTER — insert below `from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper` (verified: tools.py:18)
from parrot.knowledge.wiki.actor import current_actor

# occurrences: 2 (verified: grep -c 'asserted_by="agent:mcp",' tools.py) — replace BOTH (tools.py:352 WikiRememberTool, :446 WikiNoteTool):
#     asserted_by="agent:mcp",            →   asserted_by=current_actor(),
# occurrences: 1 (verified: grep -c 'actor="agent:mcp",' tools.py) — tools.py:654 LedgerOpenTool:
#     actor="agent:mcp",                  →   actor=current_actor(),
# occurrences: 1 — tools.py:697 LedgerClaimTool:
#     self._ledger_service.claim(issue_id, "agent:mcp")               →   self._ledger_service.claim(issue_id, current_actor())
# occurrences: 1 — tools.py:716 LedgerCloseTool:
#     self._ledger_service.close_issue(issue_id, reason, "agent:mcp") →   self._ledger_service.close_issue(issue_id, reason, current_actor())
```
**Why**: these are the only five writers in the MCP tool surface (verified `grep -n '"agent:mcp"' tools.py`). Do not touch `LedgerReadyTool`/`LedgerContextTool` (reads).

### FILL IN checklist
- [ ] none — this task is fully mechanical; the only judgement is confirming the five sites are still the only literals (`grep -c '"agent:mcp"' tools.py` → 0 afterwards).

---

## Acceptance Criteria

- [ ] `current_actor()` returns `"agent:mcp"` outside any scope; inside `actor_scope("human:x")` returns `"human:x"`; after the block the default is back.
- [ ] `actor_scope(None)` does not change the value.
- [ ] `WikiRememberTool` executed inside `actor_scope("human:alice")` writes a page whose `asserted_by == "human:alice"` (SQLite store in `tmp_path`); outside → `"agent:mcp"`.
- [ ] `LedgerOpenTool` passes `current_actor()` as `actor` (assert via a stub `LedgerService` capturing kwargs).
- [ ] `grep -c '"agent:mcp"' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` == 0.
- [ ] Existing `test_wiki_tools.py`, `test_mcp_server.py` still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_actor.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_actor.py
import asyncio
import pytest
from parrot.knowledge.wiki.actor import actor_scope, current_actor
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.tools import LedgerOpenTool, WikiRememberTool


def test_default_and_scope():
    assert current_actor() == "agent:mcp"
    with actor_scope("human:x"):
        assert current_actor() == "human:x"
        with actor_scope(None):
            assert current_actor() == "human:x"
    assert current_actor() == "agent:mcp"


async def test_remember_uses_actor(tmp_path):
    store = create_wiki_store(tmp_path, wiki_name="t", backend="sqlite")
    tool = WikiRememberTool(store)
    with actor_scope("human:alice"):
        await tool._execute(fact="remote wins", category="note", title="t1")  # FILL IN: match the real kwargs of _execute (tools.py:318)
    page = await store.get_page("memory:t1")  # FILL IN: use the concept_id scheme the tool builds
    assert page["asserted_by"] == "human:alice"


async def test_ledger_open_passes_actor():
    captured = {}
    class Stub:
        async def open_issue(self, **kw):
            captured.update(kw); return "issue:1"
    tool = LedgerOpenTool(Stub())
    with actor_scope("agent:codex"):
        await tool._execute(title="t", body="b")
    assert captured["actor"] == "agent:codex"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-run `grep -n '"agent:mcp"' tools.py` and confirm exactly 5 hits
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder (native, sonnet), consolidated by sdd-worker
**Date**: 2026-09-18
**Notes**: Implemented exactly per blueprint — `actor.py` created with
`current_actor()`/`actor_scope()`, all 5 `"agent:mcp"` literals in
`tools.py` replaced with `current_actor()`. `test_actor.py` (4 tests)
passes; `test_wiki_tools.py` (31 tests) passes with no regression.
`test_mcp_server.py` has 2 pre-existing failures unrelated to this task
(`test_sqlite_backend_unaffected_by_arango_branch` — unrelated
`sqlite_policy` kwarg from TASK-3235; `test_initialize_and_list_tools` —
subprocess spawns a fresh interpreter that lacks the worktree's compiled
Cython extensions). Confirmed via a merge-tier test run against 13
failures total: 12 reproduce identically on the pre-feature base commit
(dev tip), and the 13th (`test_vault_tools_over_stdio`) turned green once
the worktree's missing `parrot.utils.types`/`toml` compiled `.so`
extensions were copied in from the main checkout for local testing only
(gitignored, not committed) — a documented environment gap, not a
regression from this diff. Review recorded:
`coder-review:6e9deb1f8ca5df945af5038c` (0 corrections).
Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1

**Deviations from spec**: none
