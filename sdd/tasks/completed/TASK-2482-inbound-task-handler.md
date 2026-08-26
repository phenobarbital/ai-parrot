# TASK-2482: Inbound Task Handler (`handle_task` → `m.parrot.result`)

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2478, TASK-2481
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (producer half). Verified gap: nothing in the package consumes an
`m.parrot.task` and emits an `m.parrot.result` — `wait_for_result` and `HybridDelegator`
have no producer. This task adds `MatrixCrewAgentWrapper.handle_task()`, which runs the
agent with a structured-output prompt and replies as the target agent.

---

## Scope

- Add `async def handle_task(self, task: TaskEventContent, room_id: str) -> None` to
  `MatrixCrewAgentWrapper`.
- Prompt building: `_build_task_prompt(task)` — question + requester + JSON instruction:
  always ask for a JSON object `{"answer": ..., "confidence": 0..1, "sources": [...]}`; when
  `expected_schema` is present, embed it and require `answer` to conform.
- Run: `BotManager.get_bot(self._config.chatbot_id)` → `asyncio.wait_for(agent.ask(prompt), timeout)`
  where timeout = `task.metadata.get("timeout")` or 120s; registry status `busy`/`ready` like
  `handle_message` (`:92`, `:149`).
- Reply: `ResultEventContent(task_id=task.task_id, content=<raw text>, success=True,
  metadata={"correlation_id": task.correlation_id, "origin_session": task.origin_session, "hops": task.hops})`
  sent via `appservice.send_custom_event_as_agent(self._agent_name, room_id, ParrotEventType.RESULT, ...)`.
  On any exception/timeout → `success=False, error=str(exc)`. Never raise.
- Make `HybridDelegator`-style tasks (no `correlation_id`) also work: `metadata.correlation_id` falls
  back to `task_id`.
- Tests.

**NOT in scope**: tool exposure (TASK-2483), dispatch wiring (TASK-2484).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/crew_wrapper.py` | MODIFY | `handle_task`, `_build_task_prompt` |
| `packages/ai-parrot-integrations/tests/test_matrix_handle_task.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper           # crew_wrapper.py:20
from parrot.integrations.matrix.events import ParrotEventType, ResultEventContent, TaskEventContent
from parrot.manager import BotManager     # imported lazily inside methods (crew_wrapper.py:109) — keep it lazy
```

### Existing Signatures to Use
```python
# crew/crew_wrapper.py
class MatrixCrewAgentWrapper:                                                             # :20
    def __init__(self, agent_name: str, config: MatrixCrewAgentEntry, appservice: MatrixAppService,
                 registry: MatrixCrewRegistry, coordinator: MatrixCoordinator, server_name: str,
                 streaming: bool = True, max_message_length: int = 4096) -> None          # :42
        # attributes: self._agent_name, self._config, self._appservice, self._registry, self._coordinator, self.logger
    async def handle_message(self, room_id: str, sender: str, body: str, event_id: str) -> None   # :68
        # :92  await self._registry.update_status(self._agent_name, "busy", body[:50])
        # :109 from parrot.manager import BotManager ; :111 agent = await BotManager.get_bot(self._config.chatbot_id)
        # :118 response: str = await agent.ask(body)
        # :149 await self._registry.update_status(self._agent_name, "ready")
# appservice.py
async def send_custom_event_as_agent(self, agent_name, room_id, event_type: str, content: dict) -> Optional[str]   # :316
```

### Does NOT Exist
- ~~`agent.ask_structured()` / `agent.ask(..., schema=...)`~~ — only `agent.ask(prompt)` is used here; structure via prompt + parse.
- ~~`MatrixCrewAgentWrapper.handle_task`~~ — you add it.
- ~~a producer of `m.parrot.result` anywhere~~ — this task is the first one.

---

## Implementation Notes

### Skeleton
```python
_JSON_INSTRUCTION = (
    "Reply ONLY with a JSON object: {\"answer\": <your answer>, \"confidence\": <0..1>, \"sources\": [<strings>]}."
)

def _build_task_prompt(self, task: TaskEventContent) -> str:
    requester = task.metadata.get("requester", "another agent")
    parts = [f"A peer agent ({requester}) asks you: {task.content}", _JSON_INSTRUCTION]
    if task.expected_schema:
        parts.append("The value of \"answer\" MUST conform to this JSON Schema:\n" + json.dumps(task.expected_schema))
    return "\n\n".join(parts)

async def handle_task(self, task: TaskEventContent, room_id: str) -> None:
    """Answer an inbound m.parrot.task in a tunnel room and emit m.parrot.result as this agent."""
    corr = task.correlation_id or task.task_id
    meta = {"correlation_id": corr, "origin_session": task.origin_session, "hops": task.hops}
    timeout = float(task.metadata.get("timeout", 120.0))
    await self._registry.update_status(self._agent_name, "busy", task.content[:50])
    try:
        from parrot.manager import BotManager  # type: ignore
        agent = await BotManager.get_bot(self._config.chatbot_id)
        if agent is None:
            raise RuntimeError(f"Agent '{self._config.chatbot_id}' not found in BotManager")
        text: str = await asyncio.wait_for(agent.ask(self._build_task_prompt(task)), timeout)
        result = ResultEventContent(task_id=task.task_id, content=text, success=True, metadata=meta)
    except Exception as exc:  # noqa: BLE001 — never propagate into the AppService loop
        self.logger.error("handle_task failed for %s: %s", self._agent_name, exc)
        result = ResultEventContent(task_id=task.task_id, content="", success=False, error=str(exc), metadata=meta)
    finally:
        await self._registry.update_status(self._agent_name, "ready")
    await self._appservice.send_custom_event_as_agent(self._agent_name, room_id, ParrotEventType.RESULT, result.model_dump())
```

### Key Constraints
- Strip markdown code fences from the reply before returning (LLMs often wrap JSON) — `AgentAnswer.from_text` in the tunnel handles parsing, but pass clean text.
- Do not post anything human-visible in the tunnel room for v1 (structured events only).

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/test_matrix_handle_task.py -v` passes
- [ ] Result carries the same `correlation_id` (fallback `task_id`) and is sent as the target agent
- [ ] Bot exception / timeout → `success=False` result, status returns to `ready`
- [ ] Existing `test_matrix_crew.py` still passes

---

## Test Specification

```python
# tests/test_matrix_handle_task.py
import asyncio, pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.matrix.crew.config import MatrixCrewAgentEntry
from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper
from parrot.integrations.matrix.events import ParrotEventType, TaskEventContent

@pytest.fixture
def wrapper():
    svc = AsyncMock(); reg = AsyncMock()
    w = MatrixCrewAgentWrapper("writer", MatrixCrewAgentEntry(chatbot_id="writer", display_name="W", mxid_localpart="parrot-writer"),
                               svc, reg, MagicMock(), "parrot.local", streaming=False)
    return w, svc, reg

def _task(**kw):
    return TaskEventContent(task_id="t1", content="Summarise Q2", target_agent="writer", correlation_id="c1", hops=1, **kw)

async def test_emits_result_with_correlation(wrapper):
    w, svc, reg = wrapper
    bot = MagicMock(); bot.ask = AsyncMock(return_value='{"answer": "ok", "confidence": 0.7, "sources": []}')
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(_task(), "!tun:s")
    args = svc.send_custom_event_as_agent.call_args.args
    assert args[0] == "writer" and args[2] == ParrotEventType.RESULT
    assert args[3]["success"] is True and args[3]["metadata"]["correlation_id"] == "c1"
    assert reg.update_status.await_args_list[-1].args[1] == "ready"

async def test_schema_in_prompt(wrapper):
    w, svc, _ = wrapper
    bot = MagicMock(); bot.ask = AsyncMock(return_value="{}")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(_task(expected_schema={"type": "object", "required": ["total"]}), "!tun:s")
    assert '"required"' in bot.ask.call_args.args[0]

async def test_bot_error_yields_failed_result(wrapper):
    w, svc, _ = wrapper
    bot = MagicMock(); bot.ask = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(_task(), "!tun:s")
    assert svc.send_custom_event_as_agent.call_args.args[3]["success"] is False

async def test_correlation_falls_back_to_task_id(wrapper):
    w, svc, _ = wrapper
    bot = MagicMock(); bot.ask = AsyncMock(return_value="x")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await w.handle_task(TaskEventContent(task_id="legacy", content="q", target_agent="writer"), "!r:s")
    assert svc.send_custom_event_as_agent.call_args.args[3]["metadata"]["correlation_id"] == "legacy"
```

---

## Agent Instructions

Same as TASK-2478.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Added `handle_task` and `_build_task_prompt` to
`MatrixCrewAgentWrapper` per the skeleton — the first producer of
`m.parrot.result` in the package. Runs the agent via
`BotManager.get_bot(chatbot_id)` + `agent.ask(prompt)` under
`asyncio.wait_for(timeout)`, registry status busy→ready around the call,
and always replies via `send_custom_event_as_agent` with a
`ResultEventContent` whose `metadata` carries `correlation_id` (falls
back to `task_id` for legacy/no-correlation callers), `origin_session`,
`hops`. Any exception/timeout is caught and reported as
`success=False, error=str(exc)` — never propagates. 4/4 new tests pass;
full matrix regression 208/214 (6 pre-existing `test_matrix_hook.py`
failures, unrelated); `test_matrix_crew.py` (23) unaffected.
`ruff check` matches the pre-existing baseline exactly (verified via
`git stash`) after removing two redundant quoted forward-refs on the new
`TaskEventContent` params (the type is imported unconditionally in this
module, unlike the TYPE_CHECKING-only params already in `__init__`).
Environment note: `patch("parrot.manager.BotManager.get_bot", ...)`
transitively imports compiled Cython extensions
(`parrot.utils.types`, `parrot.utils.parsers.toml`) that exist as
prebuilt `.so` files in the main repo checkout but only as uncompiled
`.pyx` sources in this worktree (a known worktree/Cython gotcha — the
root `conftest.py` intentionally prepends worktree `src/` dirs ahead of
the main-repo editable install). Copied the two missing gitignored
`.so` build artifacts from the main repo into the worktree to unblock
these tests; no source files were touched to work around this.
**Deviations from spec**: none
