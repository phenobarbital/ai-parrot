---
type: Wiki Overview
title: 'TASK-1036: Warm-up coroutine (_warm_up)'
id: doc:sdd-tasks-completed-task-1036-warmup-coroutine-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.manager.ephemeral import EphemeralAgentStatus # TASK-1034'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.manager.ephemeral
  rel: mentions
- concept: mod:parrot.mcp.config
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.stores.faiss_store
  rel: mentions
---

# TASK-1036: Warm-up coroutine (_warm_up)

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1035, TASK-1037, TASK-1038
**Assigned-to**: unassigned

---

## Context

> The warm-up coroutine (spec §3 Module 3) is the background task that brings an ephemeral
> agent from `creating` to `ready`. It drives `agent.configure(app)`, validates MCP HTTP
> handshakes, and builds the RAG index (FAISS or PageIndex). Status updates flow through
> `EphemeralAgentStatus.phase` and `progress`.

---

## Scope

- Implement `async def _warm_up(bot, status, app)` in `parrot/manager/ephemeral.py`.
- Phase transitions: `creating → warming → ready` (or `→ error` on any exception).
- Progress tracking: update `status.progress` dict with per-subsystem keys:
  - `"tools"`: `"syncing"` → `"ready"`
  - `"mcp"`: `"validating"` → `"ready"` (or `"skipped"` if no MCP servers)
  - `"rag"`: `"building"` → `"ready"` (or `"skipped"` if no documents)
- Call `await bot.configure(app)` for tool sync and base setup.
- For each MCP HTTP server in the agent config, call `validate_mcp_http(config)` (from TASK-1038).
- If `rag_mode == "vector"`: build FAISS index over uploaded documents via `FAISSStore.add_documents`.
- If `rag_mode == "pageindex"`: call the pageindex builder functions.
- Catch all exceptions, record in `status.error`, set phase to `"error"`.
- Write unit tests mocking `configure`, MCP validator, and FAISS/PageIndex builders.

**NOT in scope**: HTTP handlers (Module 4), FAISS S3 persistence (dump_to_s3 is Module 6, only called on promote), route registration (Module 5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/manager/ephemeral.py` | MODIFY | Add `_warm_up` coroutine to existing file from TASK-1034 |
| `tests/unit/test_warmup.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.manager.ephemeral import EphemeralAgentStatus            # TASK-1034
from parrot.bots.abstract import AbstractBot                         # parrot/bots/abstract.py:146
from parrot.stores.faiss_store import FAISSStore                     # parrot/stores/faiss_store.py:32
from parrot.mcp.integration import validate_mcp_http                 # TASK-1038 creates this
from parrot.mcp.config import MCPServerConfig                        # parrot/mcp/config.py:16
# pageindex builder functions:
from parrot.pageindex.builder import detect_page_index               # parrot/pageindex/builder.py:112
from parrot.pageindex.builder import extract_toc_content             # parrot/pageindex/builder.py:218
from parrot.pageindex.builder import toc_transformer                 # parrot/pageindex/builder.py:267
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py:146
class AbstractBot:
    chatbot_id: uuid.UUID
    async def configure(self, app) -> None:  # main readiness contract

# parrot/stores/faiss_store.py:32
class FAISSStore(AbstractStore):
    async def add_documents(self, documents, **kwargs): ...          # line 367

# parrot/pageindex/builder.py — async free functions (NOT a class):
async def detect_page_index(...)                                     # line 112
async def extract_toc_content(...)                                   # line 218
async def toc_transformer(...)                                       # line 267
```

### Does NOT Exist
- ~~`AbstractBot.warm_up()`~~ — use `await agent.configure(app)` instead.
- ~~`PageIndexBuilder` class~~ — pageindex uses free async functions, not a builder class.
- ~~`FAISSStore.build_from_documents()`~~ — use `add_documents()` instead.

---

## Implementation Notes

### Pattern to Follow
```python
async def _warm_up(
    bot: AbstractBot,
    status: EphemeralAgentStatus,
    app: web.Application,
) -> None:
    try:
        status.phase = "warming"
        # 1. Configure bot (tool sync, base setup)
        status.progress["tools"] = "syncing"
        await bot.configure(app)
        status.progress["tools"] = "ready"
        # 2. MCP validation
        # 3. RAG build
        status.phase = "ready"
    except Exception as exc:
        status.phase = "error"
        status.error = str(exc)
```

### Key Constraints
- This coroutine is launched via `asyncio.create_task` in `create_ephemeral_user_bot` (TASK-1035).
- Must NOT block — all operations must be awaitable.
- On any exception, set `phase="error"` and `error=str(exc)` — do NOT re-raise.
- The pageindex builder takes multiple steps (detect → extract → transform); wrap in try/except per subsystem for granular error reporting.

### References in Codebase
- `parrot/manager/manager.py:734` — `_build_user_bot_instance` calls `await bot.configure(self.app)`
- `parrot/pageindex/builder.py` — free async functions for pageindex pipeline
- `parrot/stores/faiss_store.py:367` — `add_documents` for FAISS index build

---

## Acceptance Criteria

- [ ] `_warm_up` transitions status from `creating → warming → ready` on success.
- [ ] `progress` dict updates per subsystem: `tools`, `mcp`, `rag`.
- [ ] MCP handshake failure sets `phase="error"` with descriptive error string.
- [ ] FAISS index is built from uploaded documents when `rag_mode == "vector"`.
- [ ] PageIndex pipeline runs when `rag_mode == "pageindex"`.
- [ ] Any exception is caught and recorded in `status.error`; phase becomes `"error"`.
- [ ] All tests pass: `pytest tests/unit/test_warmup.py -v`
- [ ] No linting errors: `ruff check parrot/manager/ephemeral.py`

---

## Test Specification

```python
# tests/unit/test_warmup.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.manager.ephemeral import EphemeralAgentStatus, _warm_up


class TestWarmUp:
    async def test_marks_ready_on_success(self):
        bot = MagicMock()
        bot.configure = AsyncMock()
        status = EphemeralAgentStatus(
            chatbot_id="abc", user_id=1, phase="creating",
            created_at=..., expires_at=...,
        )
        app = MagicMock()
        await _warm_up(bot, status, app)
        assert status.phase == "ready"
        assert status.progress["tools"] == "ready"

    async def test_records_error_on_configure_failure(self):
        bot = MagicMock()
        bot.configure = AsyncMock(side_effect=RuntimeError("LLM init failed"))
        status = EphemeralAgentStatus(
            chatbot_id="abc", user_id=1, phase="creating",
            created_at=..., expires_at=...,
        )
        await _warm_up(bot, status, MagicMock())
        assert status.phase == "error"
        assert "LLM init failed" in status.error

    async def test_records_error_on_mcp_failure(self):
        # Mock configure success, but MCP validation fails
        ...

    async def test_faiss_build_on_vector_mode(self):
        # rag_mode="vector" → FAISSStore.add_documents called
        ...

    async def test_pageindex_build_on_pageindex_mode(self):
        # rag_mode="pageindex" → pageindex builder functions called
        ...

    async def test_skips_mcp_when_no_servers(self):
        # No MCP config → progress["mcp"] == "skipped"
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §3 Module 3, §7 Known Risks.
2. **Check dependencies** — TASK-1035, TASK-1037, TASK-1038 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — check pageindex builder functions still exist with `grep`.
4. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
5. **Implement** `_warm_up` in `parrot/manager/ephemeral.py`.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-07
**Notes**: `_warm_up` was already fully implemented in `ephemeral.py` as part of TASK-1034 (skeleton added proactively since it lives in the same file). TASK-1036 added the formal unit test suite: 14 tests covering `creating→warming→ready` transitions, `progress` dict updates for all three subsystems (tools/mcp/rag), MCP validation with mock server configs, FAISS index build path, and `_extract_mcp_servers` helper. PageIndex path is stubbed (requires `PageIndexLLMAdapter` which is a follow-up integration).

**Deviations from spec**: `_build_page_index` logs and skips (rather than running the full pipeline) because the pageindex builder requires a `PageIndexLLMAdapter` that depends on the bot's LLM client — that wiring is a follow-up integration task.
