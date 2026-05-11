---
id: F003
query: "Existing hook/callback patterns in codebase"
type: grep
---

## Existing Hook Infrastructure

### 1. Node Pre/Post Actions (flows/core/node.py, lines 87-135)
- `add_pre_action(action: ActionCallback)` — runs before node execution
- `add_post_action(action: ActionCallback)` — runs after node execution
- `ActionCallback = Callable[..., Union[None, Awaitable[None]]]` (flows/core/types.py:27)
- Handles both sync and async via `asyncio.iscoroutine()` check

### 2. AbstractBot Event Listeners (bots/abstract.py, lines 818-834)
- `add_event_listener(event_name: str, callback: Callable)` — generic event system
- `_trigger_event(event_name: str, **kwargs)` — fires listeners
- Supports both sync and async callbacks
- Events: EVENT_STATUS_CHANGED, EVENT_TASK_STARTED, EVENT_TASK_COMPLETED, EVENT_TASK_FAILED

### 3. FSM Transition Hooks (bots/flow/fsm.py, lines 642-684)
- `on_success()`, `on_error()`, `on_condition()` — workflow transitions, not callbacks

### 4. on_agent_complete in run_flow (orchestration/crew.py, line 2160)
- Only in flow mode, per-agent granularity
- Signature: `async def callback(agent_name: str, result: Any, context: FlowContext)`

**Gap**: No crew-level lifecycle hooks for when the entire crew completes or fails.
