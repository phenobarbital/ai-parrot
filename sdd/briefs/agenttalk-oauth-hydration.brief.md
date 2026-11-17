---
kind: brief
slug: agenttalk-oauth-hydration
key: b7af2560406f
base_branch: dev
source:
  type: ledger
  ref: issue:b7af2560406f
  url: null
jira_issue_key: null
ledger_issue: issue:b7af2560406f
created: "2026-11-02"
---

# Brief: AgentTalk never hydrates OAuth toolkits from saved connections

## Problem
Ledger issue:b7af2560406f (major, from FEAT-773): a user who connected Jira/O365 via the
Connections panel gets no `JiraToolkit`/`Office365Toolkit` in AgentChat unless the agent
class wires them itself in `post_configure()`. FEAT-773's "connect once, every agent can
use it" contract is dead code on the web path.

## Root cause
`UserObjectsHandler.configure_tool_manager` only hydrates when no session ToolManager
exists **and** both `user_id` and `agent_id` are passed
(`packages/ai-parrot-server/src/parrot/handlers/user_objects.py:189`). Two callers break it:

1. `AgentTalk._configure_tool_manager` forwards only `(data, request_session, agent_name)`
   (`packages/ai-parrot-server/src/parrot/handlers/agent.py:726`), so the PATCH path
   (`_setup_agent_tools`, `agent.py:1006`) never hydrates.
2. The POST chat path never calls `configure_tool_manager` at all — it reads
   `request_session.get(f"{agent_tooling_ref(agent)}_tool_manager")` directly
   (`agent.py:1590-1591`), so a cold session (no prior PATCH) gets `None` and no hydration.
   `user_id` is already resolved at `agent.py:1559` via `_get_user_session`.

## Research findings
- Hydration impl: `UserObjectsHandler._hydrate_oauth_toolkits` (`user_objects.py:196`),
  stores the hydrated ToolManager under `session_key` in `request_session`.
- Unit tests call `configure_tool_manager` directly with ids:
  `packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py` — caller never covered.
- Related ledger: issue:9342747e35f1 (FEAT-777 AgentTalk wiring test gaps, minor).
- Skip `is_user_bot` on POST (user bots own their ToolManager) — keep that guard.

## Assumptions
- Agent id passed is `agent_tooling_ref(agent)` (same value already used as session-key
  namespace), not a separate DB id.
- On POST, hydrate only when the session has no ToolManager for this agent (cold session);
  never overwrite a PATCH-configured ToolManager.
- Descriptor providers (`toolkit_factory() -> None`): log at WARNING instead of silent skip.
- Missing-id skip in the guard logs at WARNING.

## Fix plan
- HOTFIX-b7af2560406f-1: thread `user_id`/`agent_id` through `_configure_tool_manager`,
  add cold-session hydration to the POST path, WARNING logs, and handler-level tests.

## Validation commands
- `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py packages/ai-parrot-server/tests/unit/test_agenttalk_oauth_hydration.py -q`
