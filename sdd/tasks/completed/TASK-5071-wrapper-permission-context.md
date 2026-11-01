# TASK-5071: Wrapper passes the Teams `permission_context` to every agent call + saves conversation refs

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5066, TASK-5067, TASK-5070
**Assigned-to**: unassigned

---

## Context

Spec §2 "Principal (M1)" and "Notifier (M4)" (ref store refreshed by the wrapper), §3 Modules 1 and 4, AC-1, AC-6.
Today the four orchestrator call sites pass only `user_id` / `session_id`, so no `PermissionContext` with
`channel="msteams"` reaches `ToolManager` and FEAT-773's resolver cannot resolve a Teams caller.
`FormOrchestrator.process_message` already forwards `context` verbatim to `agent.ask(**context)`
(orchestrator.py:320-324; `ask(permission_context=...)` at bots/base.py:1083), so only the wrapper changes.
Depends on TASK-5070 because both edit `wrapper.py` (and this task uses `self._principal_source` from it).

---

## Scope

- `async def _permission_context_for_turn(self, turn_context) -> Optional[PermissionContext]`: validated session
  from `self._principal_source.session_for_turn` → `build_msteams_permission_context(session)`, else `None`.
- At all four call sites (normal text :813, voice :1165, card resume :568, deep-link resume :523) add
  `"permission_context"` **only when** the helper returns a context. Keep `user_id` exactly as today.
- `MSTeamsConversationRefStore` built in `__init__` from `self.app.get("redis")` (`None` when absent) as
  `self._convref_store`; `async def _remember_conversation(turn_context)` saves the serialized reference for
  authenticated **personal** turns only; called once per message turn just before command dispatch.
- Tests: `test_permission_context_reaches_ask`, `test_conv_ref_saved_on_personal_authenticated_turn_only`.

**NOT in scope**: notifier attach and legacy notifier removal (TASK-5072), the needs-auth collector (TASK-5075).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | helper, 4 call sites, ref store + save |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_connections.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.msteams.connections import (                    # TASK-5066 / TASK-5067
    MSTeamsConversationRefStore, build_msteams_permission_context,
)
from parrot.auth.permission import PermissionContext                     # verified: permission.py:81
from botbuilder.core import TurnContext                                  # already imported by wrapper.py
```

### Existing Signatures to Use
```python
# msteams/wrapper.py
    async def _effective_user_id(self, turn_context, fallback: str) -> str           # :350 (unchanged)
#   call sites — each is a dict literal passed as `context=` to self.form_orchestrator.process_message:
#   :523  `                            context={`  then `"user_id": await self._effective_user_id(turn_context, user_id),` (:524)
#   :568  `                    context={`         then `"user_id": await self._effective_user_id(turn_context, user_id),` (:569)
#   :813  `                context={`             then `"user_id": await self._effective_user_id(turn_context, turn_context.activity.from_property.id),` (:814)
#   :1165 `                context={`             same user_id line (:1166) and a `"source": "voice_note"` key
#   :714  `        if clean_text:` — command dispatch starts here (after the FEAT-729 auth gate)
#   self.app = app (:144); self._principal_source (TASK-5070); config.client_id
# TurnContext.get_conversation_reference(activity).serialize()            # jira_commands.py:203-222 pattern
```

### Does NOT Exist
- ~~`permission_context` in the wrapper's orchestrator `context`~~ — added here.
- ~~saving refs for group/channel conversations~~ — forbidden (spec §7 "Group conversations").
- ~~calling `ensure_authenticated` from these helpers~~ — never (may run an exchange).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_connections.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._effective_user_id"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add helpers below `_effective_user_id`. 2. Build the ref store in `__init__` after the connector block
(TASK-5070). 3. Call `_remember_conversation` before `        if clean_text:` (wrapper.py:714, occurrences: 1).
4. Edit the four call sites with a shared pattern. 5. Tests.

### `.../msteams/wrapper.py` (MODIFY) — helpers
```python
    # AFTER the `_effective_user_id` method (ends `        return fallback` at :368; insert before `    def _build_user_context(`)
    async def _permission_context_for_turn(self, turn_context: TurnContext) -> Optional[PermissionContext]:
        """Teams PBAC context for an authenticated turn, else ``None`` (fail closed)."""
        source = getattr(self, "_principal_source", None)
        if source is None or self._auth is None:
            return None
        session = await source.session_for_turn(turn_context)
        return build_msteams_permission_context(session) if session is not None else None

    async def _agent_context(self, turn_context: TurnContext, fallback_user_id: str, session_id: str,
                             **extra: Any) -> Dict[str, Any]:
        """Orchestrator ``context`` with ``permission_context`` only when the turn is authenticated."""
        context: Dict[str, Any] = {
            "user_id": await self._effective_user_id(turn_context, fallback_user_id),
            "session_id": session_id,
            **extra,
        }
        permission_context = await self._permission_context_for_turn(turn_context)
        if permission_context is not None:
            context["permission_context"] = permission_context
        return context

    async def _remember_conversation(self, turn_context: TurnContext) -> None:
        """Refresh the personal conversation reference of an authenticated user (notifier fallback)."""
        # FILL IN: return unless self._convref_store and conversation_type == "personal" and a validated session
        # exists; save(session.nav_user_id, serialized ref) — bounded by AC-6 / spec §7 group rule; log, never raise
        ...
```

### Same file — the four call sites
```python
# Each `context={ "user_id": ..., "session_id": ... [, "source": "voice_note"] },` dict becomes:
                context=await self._agent_context(turn_context, <same fallback>, <same session id>[, source="voice_note"]),
# :523-526  fallback user_id,  session_id      (deep-link resume)
# :568-571  fallback user_id,  conversation_id (card resume)
# :813-816  fallback turn_context.activity.from_property.id, conversation_id
# :1165-1169 same as :813 plus source="voice_note"
# Anchors are duplicated (`                context={` ×2, user_id line ×2 at :814/:1166): FILL IN — disambiguate each
# edit by quoting the preceding `message=...` / `conversation_id=conversation_id,` lines and the enclosing method name.
```
**Why**: one helper keeps the four sites identical and guarantees `user_id` keeps today's value (AC-1).

### `.../tests/integrations/msteams/test_msteams_wrapper_connections.py` (CREATE)
```python
"""FEAT-775 M1/M4: wrapper permission context + conversation refs."""
# FILL IN: build a wrapper with patched heavy dependencies (follow test_msteams_wrapper_jira.py's construction helpers),
#   fake principal source, fake orchestrator capturing `context`.
# test_permission_context_reaches_ask — authenticated → context has permission_context (channel "msteams", user_id nav,
#   channel_user_id oid) and user_id == nav id; unauthenticated → key absent and user_id == from_property.id
# test_voice_and_resume_sites_pass_context — the voice path keeps source="voice_note" and gets the context
# test_conv_ref_saved_on_personal_authenticated_turn_only — group or unauthenticated → no save; personal → save(nav, ref)
```

### FILL IN checklist
- [ ] `_remember_conversation` body; store construction (`self.app.get("redis")`)
- [ ] four call-site disambiguations
- [ ] three tests

---

## Acceptance Criteria

- [ ] Authenticated turns pass `permission_context` (Navigator id, `channel="msteams"`, AAD oid in `channel_user_id`); unauthenticated pass none (AC-1).
- [ ] `user_id` values are unchanged at every call site.
- [ ] Conversation refs saved only for authenticated personal turns (AC-6 fallback path).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_connections.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py -q`

---

## Test Specification

Three tests listed in the test-file block.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented by gpt-5.6-terra (codex), 1 attempt; fidelity gate and lint clean; own validation 13 passed, 2 skipped. Pre-existing failures (also red on origin/dev): test_msteams_oauth_callback::TestStatePayloadShapeParity, test_o365_refresh (2). 0 review corrections.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

