# HOTFIX-b7af2560406f-1: Wire AgentTalk into OAuth toolkit hydration

**Feature**: brief agenttalk-oauth-hydration (issue:b7af2560406f)
**Spec**: sdd/briefs/agenttalk-oauth-hydration.brief.md
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
See the brief's Root cause: hydration in `UserObjectsHandler.configure_tool_manager` is
never reached from AgentTalk (PATCH omits ids; POST bypasses it).

## Scope
1. `AgentTalk._configure_tool_manager` gains `user_id: str | None = None, agent_id: str | None = None`
   and forwards them to `user_objects_handler.configure_tool_manager(..., user_id=..., agent_id=...)`.
2. `_setup_agent_tools` resolves `user_id` (via `_get_user_session(data)` or the value already
   resolved by the caller) and passes `agent_id=ref`.
3. POST path (`agent.py` ~1588-1592): when `request_session` exists, `not is_user_bot`, the
   session has no ToolManager for `session_key`, and `user_id` is set, call
   `self.user_objects_handler._hydrate_oauth_toolkits(user_id, ref, session_key, request_session)`
   (or a small public wrapper on UserObjectsHandler) before `_apply_user_toolkit_overrides`.
4. In `user_objects.py`, log WARNING when hydration is skipped for a missing id (only when no
   session ToolManager), and WARNING when a provider's `toolkit_factory` returns `None`.

**NOT in scope**: changing provider toolkit factories, PBAC filtering, user-bot ToolManagers.

## Files to Create / Modify
- MODIFY `packages/ai-parrot-server/src/parrot/handlers/agent.py`
- MODIFY `packages/ai-parrot-server/src/parrot/handlers/user_objects.py`
- CREATE `packages/ai-parrot-server/tests/unit/test_agenttalk_oauth_hydration.py`

## Codebase Contract
### Verified anchors
- `agent.py:710` `async def _configure_tool_manager(self, data, request_session, agent_name=None)`
- `agent.py:726` `return await self.user_objects_handler.configure_tool_manager(data, request_session, agent_name)`
- `agent.py:1006` call in `_setup_agent_tools`
- `agent.py:1559` `user_id, user_session = await self._get_user_session(data)`
- `agent.py:1590` `session_key = f"{agent_tooling_ref(agent)}_tool_manager"`
- `user_objects.py:99` `configure_tool_manager(..., user_id: Optional[str]=None, agent_id: Optional[str]=None)`
- `user_objects.py:189` guard `if tool_manager is None and user_id and agent_id:`
- `user_objects.py:196` `_hydrate_oauth_toolkits(self, user_id, agent_id, session_key, request_session)`
### Does NOT Exist
- No public `hydrate` wrapper on UserObjectsHandler yet (add one if preferred over calling the private method).

## Acceptance Criteria
- PATCH `_setup_agent_tools` with a cold session and an active `users_integrations` row registers the provider toolkit.
- POST chat with a cold session hydrates and the swapped-in `agent.tool_manager` contains the provider toolkit.
- POST with an existing session ToolManager does not re-hydrate/overwrite.
- User bots (`is_user_bot`) are untouched.
- Skips log at WARNING.
- Existing `test_user_objects_hydration.py` and `test_agenttalk_toolkit_overrides.py` still pass.

## Validation Commands
- `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py packages/ai-parrot-server/src/parrot/handlers/user_objects.py`
- `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py packages/ai-parrot-server/tests/unit/test_agenttalk_oauth_hydration.py packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py -q`

## Test Specification
Mock `list_users_integrations` to return one active row and a provider whose
`toolkit_factory` returns a stub toolkit; drive `_setup_agent_tools` and the POST
tool-manager block with a dict-backed session; assert the toolkit is registered.

## Completion Note
Done. `_configure_tool_manager` forwards user_id/agent_id; new `_hydrate_cold_session` used by PATCH (`_setup_agent_tools`, before tool config so it extends hydrated toolkits) and cold-session POST (skips user bots, never overwrites existing ToolManager). WARNING logs for missing ids and factories returning None. 12 tests pass (hydration, new AgentTalk tests, toolkit overrides).
