---
type: Wiki Overview
title: Jira Transition Actions — Activating `TRIGGER_AGENT` Dispatch
id: doc:docs-jira-transition-actions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: them, and routes `jira.transitioned` events through
relates_to:
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.bots._types
  rel: mentions
---

# Jira Transition Actions — Activating `TRIGGER_AGENT` Dispatch

> **Feature**: FEAT-265 — jiraspecialist-trigger-agent-orchestrator
> (follow-up to the jira webhooks feature — see
> `sdd/specs/jiraspecialist-webhooks.spec.md`)
> **Since**: ai-parrot next minor
> **Stability**: stable

---

## Background

`JiraSpecialist` receives Jira webhooks via `JiraWebhookHook`, classifies
them, and routes `jira.transitioned` events through
`handle_hook_event()` → `_dispatch_transition()` → a registry of
`TransitionAction` entries (`self._transition_actions`). Each action has an
`action_type`:

| `action_type` | Handler | Behaviour |
|---|---|---|
| `NOTIFY_CHANNEL` | `_action_notify_channel` | Sends a Telegram message via the agent's `TelegramAgentWrapper`. |
| `CALL_HANDLER` | `_action_call_handler` | Invokes a named method on the agent instance. |
| `LOG` | `_action_log_transition` | Emits a structured log line. |
| `TRIGGER_AGENT` | `_action_trigger_agent` | Dispatches another agent with a rendered task. **See below.** |

## Activating `TRIGGER_AGENT` dispatch

`JiraSpecialist` lives in the `ai-parrot` (core) package and **must not**
import the server-side `AutonomousOrchestrator`
(`ai-parrot-server`'s `parrot.autonomous.orchestrator`) — that would be a
layering violation. Instead, `JiraSpecialist` exposes a narrow, injectable
async slot:

```python
def set_agent_dispatcher(self, dispatcher: AgentDispatcher) -> None: ...
```

where `AgentDispatcher` (`parrot.bots._types.AgentDispatcher`) is a
structural `typing.Protocol`:

```python
async def __call__(self, agent_name: str, task: str, *,
                    user_id: Optional[str] = None,
                    session_id: Optional[str] = None) -> Any: ...
```

`AutonomousOrchestrator.execute_agent` already matches this shape, so
wiring it in is a single call — made **in the consuming deployment
project's `app.py`** (not in this repo; `agents/` here is gitignored and is
not the dispatch host), once both the orchestrator and the concrete Jira
agent exist:

```python
# in the consuming project's app.py, after both objects are constructed
jira_agent.set_agent_dispatcher(orchestrator.execute_agent)
```

### Degrade behaviour (no dispatcher wired)

If `set_agent_dispatcher()` is never called, `TRIGGER_AGENT` actions log
the trigger intent at `WARNING` level and return
`{"status": "skipped", "reason": "no dispatcher wired", "agent_id", "task"}`
— the webhook still returns `200`; nothing raises.

### Return-status vocabulary

| `status` | Meaning |
|---|---|
| `dispatched` | The dispatcher was awaited successfully; `result` carries a truncated string summary. |
| `skipped` | No `agent_id` in `action_config`, or no dispatcher wired. |
| `error` | The dispatcher raised; the exception is caught and logged (`exc_info=True`); the transition action loop continues for any remaining matched actions. |

### Latency caveat (v1: await-inline)

The dispatcher is `await`ed **inline** — the action's return dict carries
the real result/error, but this ties webhook response latency to the
downstream agent's runtime. Verify after rollout that slow agents don't
push the webhook response past Jira's timeout; if they do, a follow-up may
move this to `asyncio.create_task` fire-and-forget.

### Example

```python
TransitionAction(
    from_status="*",
    to_status="Ready For Deploy",
    action_type=TransitionActionType.TRIGGER_AGENT,
    action_config={
        "agent_id": "deploy_bot",
        "task_template": "Deploy {issue_key}",
    },
)
```

When a NAV ticket transitions to *Ready For Deploy* and a dispatcher is
wired, this fires `await orchestrator.execute_agent("deploy_bot", "Deploy NAV-1234", ...)`.

See `packages/ai-parrot/tests/test_jira_transition_dispatch.py` for the
full behavioural test suite (dispatch / skip / error / template rendering /
end-to-end).
