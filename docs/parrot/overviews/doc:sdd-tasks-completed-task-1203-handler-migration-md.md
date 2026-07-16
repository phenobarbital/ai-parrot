---
type: Wiki Overview
title: 'TASK-1203: Handler Migration from retrieval() to session()'
id: doc:sdd-tasks-completed-task-1203-handler-migration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Three handlers call `retrieval()` and must be updated to use `session()`.
relates_to:
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.handlers.chat
  rel: mentions
---

# TASK-1203: Handler Migration from retrieval() to session()

**Feature**: FEAT-175 — Migrate RequestBot to ContextVar-based RequestContext
**Spec**: `sdd/specs/migrate-requestbot-contextvars.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1202
**Assigned-to**: unassigned

---

## Context

Three handlers call `retrieval()` and must be updated to use `session()`.
The change is mechanical — replace `retrieval(...)` with `session(...)` and
adjust the argument names. The yielded `bot` is now the real bot instance
(not a RequestBot wrapper), so all downstream calls work unchanged since
the ContextVar fallback provides ctx automatically.

Implements Spec §3 Module 3.

---

## Scope

- Update `AgentTalk.post()` in `agent.py:1504` — replace `agent.retrieval(...)` with `agent.session(...)`
- Update `ChatTalk.post()` in `chat.py:455` — replace `chatbot.retrieval(...)` with `chatbot.session(...)`
- Update `BotConfigTestHandler` in `test_handler.py:197` — replace `agent.retrieval(...)` with `agent.session(...)`
- Verify `_handle_stream_response()` still works (it receives `bot` and calls `bot.ask_stream()` — should work unchanged since ask_stream reads from ContextVar)
- Remove any `RequestBot` type annotations if present in these files

**NOT in scope**: modifying abstract.py (TASK-1202), modifying base.py (TASK-1204).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/agent.py` | MODIFY | Replace retrieval() → session() at line 1504 |
| `packages/ai-parrot/src/parrot/handlers/chat.py` | MODIFY | Replace retrieval() → session() at line 455 |
| `packages/ai-parrot/src/parrot/handlers/test_handler.py` | MODIFY | Replace retrieval() → session() at line 197 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# agent.py does NOT import RequestBot or RequestContext directly
# It uses agent.retrieval() which returns a RequestBot — after migration,
# agent.session() returns the real bot (AbstractBot)
```

### Existing Signatures to Use

**AgentTalk.post() — retrieval call at agent.py:1504:**
```python
async with agent.retrieval(self.request, app=app, user_id=user_id, session_id=user_session) as bot:
```
Replace with:
```python
async with agent.session(request=self.request, app=app, user_id=user_id, session_id=user_session) as bot:
```

**ChatTalk.post() — retrieval call at chat.py:455:**
```python
async with chatbot.retrieval(self.request, app=app, llm=llm) as bot:
```
Replace with:
```python
async with chatbot.session(request=self.request, app=app, llm=llm) as bot:
```

**BotConfigTestHandler — retrieval call at test_handler.py:197:**
```python
async with agent.retrieval(
```
Replace with:
```python
async with agent.session(
```
(Read the full call to get exact kwargs — likely `request=...` needs keyword form)

**_handle_stream_response at agent.py:1948:**
```python
async def _handle_stream_response(
    self,
    bot: AbstractBot,       # line 1950 — type is already AbstractBot, not RequestBot
    query: str,
    ...
) -> web.StreamResponse:
    ...
    async for chunk in bot.ask_stream(   # line 1989
        question=query,
        ...
    ):
```
No changes needed here — `bot` is now the real AbstractBot, and `ask_stream()`
reads ctx from ContextVar.

### Does NOT Exist
- ~~`RequestBot` import in agent.py~~ — agent.py does NOT import RequestBot
- ~~`RequestBot` type annotation in _handle_stream_response~~ — already typed as `AbstractBot`

---

## Implementation Notes

### Key Change Pattern

The main change in each handler is:

**Before:**
```python
async with agent.retrieval(self.request, app=app, user_id=user_id, session_id=user_session) as bot:
```

**After:**
```python
async with agent.session(request=self.request, app=app, user_id=user_id, session_id=user_session) as bot:
```

Note the argument name change: `retrieval()` takes `request` as the first
positional arg, while `session()` takes it as a keyword arg (`request=`).
Check the `session()` signature from TASK-1202 to confirm the exact parameter
names before implementing.

### Key Constraints
- Read the `session()` signature (from TASK-1202's implementation in abstract.py)
  before making changes — the keyword argument names may differ from `retrieval()`
- The `bot` variable inside the `async with` block is now the real bot, not a
  RequestBot wrapper. All calls on `bot` (`.ask()`, `.ask_stream()`, `.followup()`)
  work unchanged because the ContextVar fallback provides ctx.
- Do NOT add `ctx=` explicitly to any `.ask()` or `.ask_stream()` calls — the
  ContextVar handles it automatically

---

## Acceptance Criteria

- [ ] `agent.py:1504` uses `agent.session(...)` instead of `agent.retrieval(...)`
- [ ] `chat.py:455` uses `chatbot.session(...)` instead of `chatbot.retrieval(...)`
- [ ] `test_handler.py:197` uses `agent.session(...)` instead of `agent.retrieval(...)`
- [ ] No references to `retrieval(` remain in any handler file
- [ ] No references to `RequestBot` remain in any handler file
- [ ] `ruff check packages/ai-parrot/src/parrot/handlers/` passes

---

## Test Specification

No new tests needed for this task — the handler changes are mechanical
substitutions. The existing PBAC integration tests (TASK-1205) verify
the full flow. Manual smoke test:

```bash
# Verify no import errors
python -c "from parrot.handlers.agent import AgentTalk; print('OK')"
python -c "from parrot.handlers.chat import ChatTalk; print('OK')"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-requestbot-contextvars.spec.md`
2. **Check dependencies** — TASK-1202 must be complete (verify `session()` exists on AbstractBot)
3. **Read the session() signature** in `abstract.py` to confirm parameter names
4. **Read each handler's retrieval() call** (agent.py:1504, chat.py:455, test_handler.py:197) to understand the full context
5. **Replace** retrieval → session in all three files
6. **Verify** no remaining references to `retrieval(` or `RequestBot` in handlers
7. **Run lint**: `ruff check packages/ai-parrot/src/parrot/handlers/`
8. **Commit** with message: `feat(FEAT-175): migrate handlers from retrieval() to session()`

---

## Completion Note

Replaced agent.retrieval(self.request, ...) with agent.session(request=self.request, ...) in agent.py:1504, chatbot.retrieval(...) with chatbot.session(request=...) in chat.py:455, and agent.retrieval(...) with agent.session(request=...) in test_handler.py:197. Updated the stale comment on test_handler.py:194. No RequestBot references found in any handler. All three modules import cleanly. Lint: only pre-existing violations.
