# TASK-4497: HTTP tenant binding (server-resolved tenant, client tenant discarded)

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 and design-research S2 (verified security issue).
`ChatHandler` forwards the whole client JSON body into `bot.ask()` /
`bot.ask_stream()` / custom-method params as `**data`, so a client could send
`{"tenant": "epson"}` and read another customer's skills. The tenant must come
only from the server-side Navigator session (`RequestScope.tenant`, the
user's single `program`). `AgentHandler.ask_agent()` never resolves a scope at
all. Unit tests use a fake bot, so no dependency on TASK-4496.

---

## Scope

- Add `async def resolve_request_tenant(app, request) -> str | None` to `handlers/scope.py`.
- `chat.py`: pop `tenant` from `data` before any forwarding (WARNING log when present), resolve the
  server tenant once, pass `tenant=tenant` to both `bot.ask_stream(...)` and `bot.ask(...)`.
- `handlers/agents/abstract.py` `ask_agent`: pass `tenant=` from the helper.
- Write `packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py`.

**NOT in scope**: any core change, Telegram (TASK-4500), superuser override (spec Non-Goal),
other handlers that do not call `ask`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/scope.py` | MODIFY | `resolve_request_tenant()` |
| `packages/ai-parrot-server/src/parrot/handlers/chat.py` | MODIFY | drop client tenant, pass server tenant |
| `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` | MODIFY | pass server tenant in `ask_agent` |
| `packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.scope import RequestScope, get_scope_resolver, has_installed_resolver  # verified: ai-parrot-server handlers/scope.py:38 / :140 / :135
from .studio.access import studio_scope_kwargs        # verified: chat.py:34 (existing import in chat.py)
from aiohttp import web                               # already used by scope.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/scope.py
class RequestScope: user_id: str | None; tenant: str | None; groups; is_superuser; ...   # line 38
class SessionScopeResolver: async def resolve(self, request: web.Request) -> RequestScope  # 73 / 82 — owner-only scope (tenant None) on ANY failure; tenant = programs[0] iff exactly one program (120)
def has_installed_resolver(app: Any) -> bool         # line 135 — app["scope_resolver"] or app["ui_surfaces_scope_resolver"]
def get_scope_resolver(app: Any) -> ScopeResolver    # line 140
# keys: SCOPE_RESOLVER_APP_KEY = "scope_resolver", LEGACY_SCOPE_RESOLVER_APP_KEY = "ui_surfaces_scope_resolver" (see test_request_scope.py:35-41)

# packages/ai-parrot-server/src/parrot/handlers/chat.py
        stream = data.pop('stream', False)                                              # line 450
        async with chatbot.session(request=self.request, app=app, llm=llm,
                                   **await studio_scope_kwargs(app, self.request, chatbot)) as bot:   # 454-455
                        method_params = {**method_params, **data}                      # line 496 (custom-method dispatch)
                        async for event in await bot.ask_stream(question=..., ..., request=self.request, **data):  # 530-540
                response = await bot.ask(question=..., ..., request=self.request, **data)  # 556-566

# packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py
    async def ask_agent(self, query: str = None, prompt_file: str = None, *args, **kwargs) -> Tuple[AgentResponse, AIMessage]:  # 835
            response = await agent.ask(                                                  # 886
                question=query, use_conversation_history=False, use_vector_context=False, max_tokens=16000
            )
# self.request.app available (abstract.py:846 uses self.request.app[self.agent_id])
```

### Does NOT Exist
- ~~`resolve_request_tenant`~~ — added here.
- ~~`RequestScope.programs`~~ — only `tenant` (already reduced from programs by the resolver).
- ~~Reading the tenant from `data`/query string~~ — forbidden by design (AC-H1).
- ~~`packages/ai-parrot-server/tests/unit/`~~ — handler tests live in `tests/handlers/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/scope.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/chat.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#RequestScope",
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#get_scope_resolver",
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#has_installed_resolver"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The `data.pop('tenant', None)` MUST happen before line 496's custom-method merge and before both `ask*` calls — place it right after `stream = data.pop('stream', False)` (line 450), which precedes all three.
- Never raise from `resolve_request_tenant`: catch resolver exceptions, log at DEBUG, return `None` (spec §7).
- `tenant=None` is a valid value — bots without the mixin ignore it (TASK-4496).

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper to `scope.py` below `get_scope_resolver` — *why*: one trusted source reused by both handlers.
2. In `chat.py`, pop + log the client tenant and resolve the server tenant right after line 450 — *why*: AC-H1 covers all three forwarding sites.
3. Add `tenant=tenant` to the `ask_stream` and `ask` calls — *why*: AC-H2.
4. In `agents/abstract.py`, pass the resolved tenant — *why*: AC-H3.
5. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/scope.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def get_scope_resolver(app: Any) -> ScopeResolver:' .../handlers/scope.py)
# AFTER — insert below the body of get_scope_resolver (scope.py:140-142)


async def resolve_request_tenant(app: Any, request: web.Request) -> str | None:
    """Server-side tenant for ``request`` (FEAT-707), never client-supplied.

    Returns ``RequestScope.tenant`` from the installed resolver, or ``None`` when no resolver is
    installed, the session has zero/several programs, or resolution fails. Never raises.
    """
    if not has_installed_resolver(app):
        return None
    # FILL IN: try: scope = await get_scope_resolver(app).resolve(request); return scope.tenant
    #          except Exception as exc: logging.getLogger(__name__).debug(...); return None
    #          — bounded by spec §7 (never raise) and AC-H2
```

### `packages/ai-parrot-server/src/parrot/handlers/chat.py` (MODIFY)
```python
# import (top of file, next to `from .studio.access import studio_scope_kwargs` at chat.py:34):
from .scope import resolve_request_tenant

# occurrences: 1 (verified: grep -c "        stream = data.pop('stream', False)" .../handlers/chat.py)
# AFTER — insert below `        stream = data.pop('stream', False)` (chat.py:450)
        if data.pop('tenant', None) is not None:
            self.logger.warning("Ignoring client-supplied 'tenant' for chatbot %s (FEAT-707)", getattr(chatbot, 'name', chatbot))
        tenant = await resolve_request_tenant(app, self.request)

# occurrences: 1 each — add `tenant=tenant,` right before `request=self.request,` in:
#   `                        async for event in await bot.ask_stream(` (chat.py:530)
#   `                response = await bot.ask(` (chat.py:556)
# `self.logger` is already used inside ChatHandler (chat.py:92, :112 — class at chat.py:40).
```

### `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            response = await agent.ask(' .../handlers/agents/abstract.py)
# REPLACE the call at abstract.py:886-891 with:
            response = await agent.ask(
                question=query,
                use_conversation_history=False,
                use_vector_context=False,
                max_tokens=16000,
                tenant=await resolve_request_tenant(self.request.app, self.request),
            )
# import at the top of agents/abstract.py:
from ..scope import resolve_request_tenant
# FILL IN: verify the relative import depth (`handlers/agents/abstract.py` → `handlers/scope.py` is `..scope`)
```

### `packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py` (CREATE)
```python
"""FEAT-707 — HTTP tenant binding (TASK-4497)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.scope import RequestScope, resolve_request_tenant

# FILL IN tests:
#  test_resolve_request_tenant_no_resolver            → None for {}
#  test_resolve_request_tenant_single_program         → {"scope_resolver": stub returning RequestScope(tenant="pokemon", ...)}
#  test_resolve_request_tenant_resolver_raises        → None, no exception
#  test_chat_handler_drops_client_tenant              → body {"query": "...", "tenant": "epson"}; fake bot records kwargs;
#                                                       ask() gets tenant from the resolver, never "epson"; WARNING logged
#  test_chat_handler_passes_server_tenant_stream_and_sync
#  test_chat_handler_custom_method_never_sees_tenant  (line-496 branch)
#  test_ask_agent_passes_tenant
# Reuse the handler-test scaffolding pattern of tests/handlers/test_a2ui_handler.py (aiohttp app + stub auth
# middleware + MagicMock bot); build RequestScope with every required field.
# — bounded by AC-H1, AC-H2, AC-H3
```

### FILL IN checklist
- [ ] helper body — §7, AC-H2
- [ ] relative import depth in agents/abstract.py
- [ ] seven tests

---

## Acceptance Criteria

- [ ] AC-H1: a client `tenant` never reaches `ask`, `ask_stream` or the custom-method params; WARNING logged.
- [ ] AC-H2: `tenant=` equals the resolver's `RequestScope.tenant`; `None` without resolver / on failure.
- [ ] AC-H3: `ask_agent` passes the same server tenant.
- [ ] Existing handler tests still pass; `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_request_scope.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §3 Module 9, §7, §9 S2.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract**.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4497 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note


- Task: TASK-4497
- Feature: per-tenant-skills
- Implementation SHA: da3fc0fd326538047d2db4d4d8c64c21e16c2e38
- Closed at (UTC): 2026-10-19T21:38:13+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 316s · Tokens: n/a |
