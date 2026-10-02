# TASK-3991: Bind studio_scope in normal chat, direct execute and options; assert test-chat / meta-agent bindings (M5)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3990
**Assigned-to**: unassigned
**Wave**: 4 (spec §9) · **Module**: M5 scope-binding

---

## Context

Spec §3 M5: wrap each call in `RequestContext(request=..., app=..., studio_scope=build_tool_scope(scope, agent))`
(FEAT-605 `handlers/studio/access.py`). Normal chat (`chat.py:455`) binds a `StudioAgentRef` when the bot is a Studio
agent (recognised by `bot._studio_key`, FEAT-621 runtime) — in v1 only tenant-NULL Studio rows reach chat, whose
tools refuse `agent_tenant_unset`; a non-Studio bot binds `agent=None`. Options resolve the agent through
`AgentToolingStore` → `StudioAccess.agent_ref`. Execute binds `agent=None`. With no installed resolver
(`has_installed_resolver(app)` false) nothing is bound → `no_scope`. Test chat and meta-agent are bound by
FEAT-605 v0.2 — this task only asserts them (or binds test chat if FEAT-605 binds only the meta-agent, spec §8 row 3).

---

## Scope

- `chat.py:455`: pass `studio_scope=<built scope>` to `chatbot.session(...)` when `has_installed_resolver(app)`.
- `testing.py` execute and `toolkit_config.py` options: bind a `RequestContext(request=self.request, app=app,
  studio_scope=...)` with `_current_ctx.set` / `reset` around `ensure_tool_scope` + construction + call.
- Check the chat **streaming** path: a generator consumed after the `async with` exits loses the context
  (spec §7 "ContextVar reach") — keep consumption inside, or document the `no_context` refusal.
- Tests `test_normal_chat_binds_scope`, `test_execute_binds_caller_scope_agent_none` (incl. no resolver → 403
  `no_scope`), the mismatched leg of `test_execute_standalone_refuses_without_scope`, and assertions that FEAT-605's
  test chat (`testing.py:270`) and meta-agent (`meta_agent.py:110`) bind `studio_scope`.

**NOT in scope**: building/authorizing the scope (FEAT-605); tenant agents in normal chat (storage/FEAT-605 P13
follow-up); `meta_agent.py` edits (FEAT-605 W3.5 owns them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/chat.py` | MODIFY | bind studio_scope in chatbot.session |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | execute: bind RequestContext (agent=None) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | MODIFY | options: bind RequestContext with the agent ref |
| `packages/ai-parrot-server/tests/studio/test_scope_binding.py` | CREATE | binding tests incl. test-chat / meta-agent assertions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.utils.helpers import RequestContext, _current_ctx  # utils/helpers.py:7, :53
# FEAT-605 v0.2 (verify on origin/dev before use; NOT on dev @ 32b1a45d4):
#   from parrot.handlers.studio.access import build_tool_scope, StudioAgentRef   # W2.1
#   has_installed_resolver(app), get_scope_resolver(app), RequestScope            # W0.1 (X9)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/chat.py
            async with chatbot.session(request=self.request, app=app, llm=llm) as bot:  # :455 (occurrences: 1)
# packages/ai-parrot/src/parrot/bots/abstract.py
    async def session(self, ctx=None, *, request=None, app=None, llm=None, user_id=None, session_id=None, **ctx_kwargs)  # :4143
        # RequestContext(**ctx_kwargs) → bound via _current_ctx.set (:4262) / reset (:4267)
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py:270 — test chat session (FEAT-605 W3.4 binds)
# packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py:110 — meta-agent session (FEAT-605 W3.5 binds)
```

### Does NOT Exist
- ~~`studio_scope` bound anywhere today~~ — `grep -rn studio_scope packages` → 0.
- ~~`bot._studio_key`, `bot._tooling_ref`~~ — FEAT-621 W2 runtime.
- ~~`build_tool_scope`, `StudioAgentRef`, `has_installed_resolver`~~ — FEAT-605 W2.1 / W0.1.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/chat.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_scope_binding.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.session",
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#RequestContext"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- One helper per handler, `_bind_scope(agent_ref)` as an async context manager doing set/reset.
- The scope fixture in tests is `build_tool_scope(RequestScope(...), StudioAgentRef(...))` — FEAT-605's real types
  (spec §4); requests via `make_mocked_request` with `request[SESSION_OBJECT]`.

### Cross-feature ordering
- **Wave 4 needs FEAT-605 W2.1 (`build_tool_scope`, `StudioAgentRef`, tenant partitions) and FEAT-621 W2 (runtime identity: `bot._studio_key`, `bot._tooling_ref`) merged** (X16 cross-spec waits); the asserted test-chat / meta-agent bindings need FEAT-605 W3.4 / W3.5.
- `testing.py` / `toolkit_config.py`: after the FEAT-621 W2/W3 task for each file (X16). `chat.py` is not on the
  per-file list.
- If FEAT-605 W3.4 binds only the meta-agent, this task also binds test chat at `testing.py:270` (spec §8 row 3).

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Bind in chat, execute and options — *why*: G2 accessor works on every path.
2. Verify the streaming path keeps the context — *why*: spec §7 gotcha.
3. Tests; mutation: drop the binding ⇒ `whoami` returns `no_scope` ⇒ RED.

### `packages/ai-parrot-server/src/parrot/handlers/chat.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async with chatbot.session(request=self.request, app=app, llm=llm) as bot:' chat.py)
# REPLACE chat.py:455 with:
            scope_kwargs = await self._studio_scope_kwargs(app, chatbot)
            async with chatbot.session(request=self.request, app=app, llm=llm, **scope_kwargs) as bot:
# FILL IN: _studio_scope_kwargs → {} without an installed resolver; else {"studio_scope": build_tool_scope(scope,
#   agent_ref_or_None)} where agent_ref comes from bot._studio_key (Studio) else None
```

### FILL IN checklist
- [ ] `_studio_scope_kwargs` (chat), `_bind_scope` (execute/options) — bounded by spec §3 M5 bullets.

---

## Acceptance Criteria

- [ ] Normal chat binds `studio_scope`; execute binds `agent=None` with the caller tenant; options bind the agent ref.
- [ ] No resolver installed → nothing bound → tenant-bound tools refuse `no_scope` (execute 403).
- [ ] Mismatched scope on execute → 403 `tool_scope_unavailable` (`tenant_mismatch` in `details.reason`).
- [ ] Test chat and meta-agent bindings asserted.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_scope_binding.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_scope_enforcement_handlers.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_meta_agent.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_scope_binding.py
async def test_normal_chat_binds_scope(host_plugins): ...
async def test_execute_binds_caller_scope_agent_none(host_plugins): ...
async def test_execute_refuses_mismatched_scope(host_plugins): ...
async def test_test_chat_and_meta_agent_bind_studio_scope(host_plugins): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Mutation evidence**: <for each new assertion: the code reverted, the test that went RED>

**Deviations from spec**: none | describe if any
