# TASK-4552: AgentTalk: server-resolved tenant + per-turn usage metadata

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4548
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / Goal G4. AgentTalk (`handlers/agent.py`) neither resolves nor passes the tenant, and both `save_turn` calls omit `metadata`.

---

## Scope

- Copy the `chat.py:454-458` pattern: pop and warn on a client-supplied `tenant`, then `tenant = await resolve_request_tenant(app, self.request)`.
- Pass `tenant=tenant` to `bot.ask(` (:1883) and `bot.ask_stream(` (:2653).
- In both `chat_storage.save_turn(` calls (:2729 streaming → `ai_message`; :2968 non-streaming → `response`) pass `metadata={"usage": ..., "cost_usd": msg.usage.estimated_cost, "tenant": tenant, "agent": agent_name}`; tenant passed explicitly (never read from a ContextVar inside the background task).
- Do NOT modify `_get_user_session`.
- Write tests.

**NOT in scope**: ChatHandler (already resolves the tenant).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Tenant resolution + save_turn metadata |
| `packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from .scope import resolve_request_tenant  # verified: handlers/chat.py:34 (same package as agent.py)
```

### Existing Signatures to Use
```python
# ai-parrot-server handlers/scope.py:147  async def resolve_request_tenant(app, request) -> str | None
# handlers/chat.py:454-458 — pattern:
#   if data.pop('tenant', None) is not None: self.logger.warning("Ignoring client-supplied 'tenant' ... (FEAT-707)", ...)
#   tenant = await resolve_request_tenant(app, self.request)
# handlers/agent.py
response: AIMessage = await bot.ask(          # :1883
async for chunk in bot.ask_stream(            # :2653
chat_storage.save_turn(                       # :2729 (streaming, ai_message), :2968 (non-streaming, response)
# storage/chat.py:106 save_turn(..., metadata=None)
# models/basic.py:91 CompletionUsage.estimated_cost
```

### Does NOT Exist
- ~~`self.tenant`~~ on the handler — no such attribute
- ~~`AIMessage.cost_usd`~~ — use `usage.estimated_cost`
- ~~changes to `_get_user_session`~~ — forbidden by spec

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#resolve_request_tenant"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Locate where AgentTalk pops request `data` before calling the bot and add the tenant pop/resolve there — *why*: same FEAT-707 contract as ChatHandler.
2. Thread `tenant` to both bot calls and both `save_turn` calls — *why*: telemetry and storage must share the same server-resolved value.
3. Write tests.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# FILL IN: anchor — find the method(s) that build `data` before :1883 and :2653 (grep -n "data.pop(" packages/ai-parrot-server/src/parrot/handlers/agent.py);
#          insert once per request path, verbatim from chat.py:454-458:
        if data.pop("tenant", None) is not None:
            self.logger.warning("Ignoring client-supplied 'tenant' for agent %s (FEAT-707)", agent_name)
        tenant = await resolve_request_tenant(app, self.request)
```
```python
# occurrences: 1 (verified: grep -c 'response: AIMessage = await bot.ask(' agent.py) — add kwarg:  tenant=tenant,
# occurrences: 1 (verified: grep -c 'async for chunk in bot.ask_stream(' agent.py) — add kwarg:  tenant=tenant,
```
```python
# occurrences: 2 (verified: grep -c 'chat_storage.save_turn(' agent.py)
# FILL IN: disambiguate — first (:2729) uses `ai_message`, second (:2968) uses `response`. Add to each call:
                            metadata={
                                "usage": msg.usage.model_dump() if msg.usage is not None else None,
                                "cost_usd": msg.usage.estimated_cost if msg.usage is not None else None,
                                "tenant": tenant,
                                "agent": agent_name,
                            },
```
**Why**: `msg` stands for `ai_message` / `response`; `tenant` must be in scope at each save site (`# FILL IN: thread it into _handle_stream_response if the stream save lives there`) — AC-2.

### `packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py` (CREATE)
```python
"""FEAT-710 TASK-4552 — AgentTalk tenant + per-turn metadata."""
import pytest


@pytest.mark.asyncio
async def test_client_tenant_ignored_and_resolved_tenant_passed() -> None:
    # FILL IN: pattern from tests/handlers/test_request_tenant_binding.py (_Resolver, _FakeBot); body with tenant="evil",
    #          resolver returns "acme"; assert bot.ask got tenant="acme" — AC-1
    raise NotImplementedError


@pytest.mark.asyncio
async def test_save_turn_metadata_both_paths() -> None:
    # FILL IN: mocked chat_storage; streaming and non-streaming; assert metadata keys usage/cost_usd/tenant/agent — AC-2
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Anchors for the tenant pop/resolve — AC-1
- [ ] save_turn disambiguation + tenant in scope — AC-2
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] A client-supplied `tenant` is ignored (warning logged); the server-resolved one reaches `ask`/`ask_stream`.
- [ ] Both `save_turn` calls persist `usage`, `cost_usd`, `tenant`, `agent`.
- [ ] `_get_user_session` unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4552 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
