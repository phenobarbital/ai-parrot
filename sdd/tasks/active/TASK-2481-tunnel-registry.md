# TASK-2481: Tunnel Registry & AgentTunnel

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2478, TASK-2479, TASK-2480
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (registry half). The **private tunnel** is a lazily created 2-member
room per unordered agent pair carrying `m.parrot.task` / `m.parrot.result` /
`m.parrot.feedback`. `AgentTunnel.ask()` sends a task with a `correlation_id` and awaits the
matching result — the same future pattern as `MatrixA2ATransport.wait_for_result`
(`a2a_transport.py:249-288`) but keyed by `correlation_id`. Idle tunnels are tombstoned after
`ttl_minutes` (default 120; `0` = keep forever). Loop guard: `hops >= max_hops` rejected.

---

## Scope

- Create `crew/tunnel.py`: `AgentTunnel`, `TunnelRegistry`.
- `get_or_create(a, b)`: symmetric key `tuple(sorted((a, b)))`; on miss →
  `create_room_as_bot(is_direct=True, preset="trusted_private_chat", name=f"tunnel:{a}<->{b}",
  invitees=[mxid_a, mxid_b], initial_state=[m.parrot.tunnel])`, then `ensure_agent_in_room` for both;
  register in cache; `link_to_space` when the space is enabled.
- `on_custom_event(event_type, content, room_id, sender)`: RESULT → resolve future by
  `correlation_id` (fall back to `task_id`); FEEDBACK → append to `self._feedback[room_id]`;
  TASK → **only** if `room_id` is a known tunnel room → dispatch to
  `self._wrappers[target_agent].handle_task(TaskEventContent(**content), room_id)` (added in
  TASK-2482 — call it through `getattr` guard so this task's tests can mock it).
- `AgentTunnel.ask(...) -> AgentAnswer`: build `TaskEventContent(correlation_id=uuid4, hops=hops+1,
  origin_session, expected_schema, target_agent=target, content=question)`; reject when
  `hops + 1 > max_hops` (return `AgentAnswer(answer=None, metadata={"status": "hop_limit"})`);
  send via `send_custom_event_as_agent(requester, room_id, ParrotEventType.TASK, ...)`;
  `asyncio.wait_for(future, timeout)`; on timeout → `AgentAnswer(answer=None, metadata={"status": "timeout"})`;
  on `success=False` result → `metadata={"status": "error", "error": ...}`; else
  `AgentAnswer.from_text(result.content)` + `validate_against(expected_schema)`
  (validation failure → `metadata={"status": "schema_error"}`).
- `send_feedback(...)`: send `FeedbackEventContent` as requester; return event id.
- TTL sweeper: `start_sweeper()` creates an asyncio task (interval `min(60, ttl*60/4)`) that, for
  tunnels idle > ttl, calls `leave_as_agent` for both agents, writes `m.room.tombstone`
  state as bot (`{"body": "tunnel expired", "replacement_room": ""}`) and drops the cache entry;
  skipped entirely when `ttl_minutes == 0`. `stop()` cancels it.
- `list_tunnels() -> List[dict]` for the `!tunnels` command.
- Tests.

**NOT in scope**: `handle_task` producer (TASK-2482), toolkit (TASK-2483), transport wiring (TASK-2484).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/tunnel.py` | CREATE | `AgentTunnel`, `TunnelRegistry` |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/__init__.py` | MODIFY | export both |
| `packages/ai-parrot-integrations/tests/test_matrix_tunnel.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.appservice import MatrixAppService                           # appservice.py:36
from parrot.integrations.matrix.crew.channels import ChannelManager                          # TASK-2480
from parrot.integrations.matrix.crew.config import TunnelConfig                              # TASK-2478
from parrot.integrations.matrix.events import (AgentAnswer, FeedbackEventContent, ParrotEventType,
    ResultEventContent, TaskEventContent, TunnelStateContent)                                # events.py (+TASK-2478)
```

### Existing Signatures to Use
```python
# appservice.py
async def send_custom_event_as_agent(self, agent_name: str, room_id: str, event_type: str, content: dict) -> Optional[str]   # :316
async def ensure_agent_in_room(self, agent_name: str, room_id: str) -> None     # :196
def list_agents(self) -> Dict[str, str]                                          # :231  agent_name -> mxid
async def create_room_as_bot(..., is_direct: bool, preset: str, invitees, initial_state) -> str   # TASK-2479
async def set_room_state_as_bot(self, room_id, event_type, content, state_key="") -> str          # TASK-2479
async def leave_as_agent(self, agent_name: str, room_id: str, reason=None) -> None                # TASK-2479
# a2a_transport.py — pattern to copy
class MatrixA2ATransport:
    self._pending_results: Dict[str, asyncio.Future]                              # :44
    async def wait_for_result(self, room_id, task_id, *, timeout: float = 60.0) -> Optional[ResultEventContent]   # :249
    async def _on_result_event(self, event: Any) -> None                          # :288  resolves future by task_id
# events.py
class TaskEventContent: task_id, context_id, content, metadata, target_agent, skill_id, correlation_id, hops, origin_session, expected_schema
class ResultEventContent: task_id, context_id, content, artifacts, metadata, success=True, error
```

### Does NOT Exist
- ~~`MatrixCrewAgentWrapper.handle_task`~~ — added by TASK-2482; call via `getattr(wrapper, "handle_task", None)` and log a warning when missing.
- ~~any tunnel/DM code, `m.direct` account-data handling~~ — none exists; `is_direct=True` on creation is enough for v1.
- ~~`HybridDelegator` wiring~~ — unrelated; do not modify `delegation.py`.

---

## Implementation Notes

### Skeleton
```python
class AgentTunnel:
    def __init__(self, room_id: str, agents: Tuple[str, str], registry: "TunnelRegistry") -> None: ...
    @property room_id / agents ; last_used: datetime

    async def ask(self, requester: str, target: str, question: str, *, expected_schema=None,
                  timeout: Optional[float] = None, hops: int = 0, origin_session: Optional[str] = None) -> AgentAnswer:
        cfg = self._registry.config
        if hops + 1 > cfg.max_hops:
            return AgentAnswer(answer=None, metadata={"status": "hop_limit", "hops": hops})
        task = TaskEventContent(task_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()), content=question,
                                target_agent=target, hops=hops + 1, origin_session=origin_session,
                                expected_schema=expected_schema, metadata={"requester": requester})
        fut = self._registry.register_future(task.correlation_id)
        await self._registry.appservice.send_custom_event_as_agent(requester, self.room_id, ParrotEventType.TASK, task.model_dump())
        try:
            result = await asyncio.wait_for(fut, timeout or cfg.default_timeout)
        except asyncio.TimeoutError:
            self._registry.discard_future(task.correlation_id)
            return AgentAnswer(answer=None, metadata={"status": "timeout", "correlation_id": task.correlation_id})
        self.last_used = datetime.now(timezone.utc)
        if not result.success:
            return AgentAnswer(answer=None, metadata={"status": "error", "error": result.error})
        answer = AgentAnswer.from_text(result.content)
        try:
            answer.validate_against(expected_schema)
        except ValueError as exc:
            answer.metadata.update(status="schema_error", error=str(exc))
        else:
            answer.metadata.setdefault("status", "ok")
        answer.metadata.update(correlation_id=task.correlation_id, result_event_id=result.metadata.get("event_id"))
        return answer

class TunnelRegistry:
    def __init__(self, config: TunnelConfig, appservice: MatrixAppService, channels: ChannelManager,
                 wrappers: Dict[str, Any], server_name: str) -> None: ...
    async def get_or_create(self, agent_a: str, agent_b: str) -> AgentTunnel   # asyncio.Lock per pair
    def register_future(self, correlation_id: str) -> asyncio.Future ; def discard_future(...)
    async def on_custom_event(self, event_type: str, content: dict, room_id: str, sender: str) -> None
    async def start_sweeper(self) -> None ; async def stop(self) -> None ; async def _sweep_once(self) -> int
    def list_tunnels(self) -> List[dict]
    def is_tunnel_room(self, room_id: str) -> bool
    def feedback_for(self, room_id: str) -> List[FeedbackEventContent]
```

### Key Constraints
- Result events arrive through `MatrixAppService._handle_event` **before** the own-user filter, so virtual-user senders are delivered — do not add a sender filter that drops them.
- Futures must be created on the running loop (`asyncio.get_running_loop().create_future()`).
- Sweeper must swallow per-tunnel exceptions and continue.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/test_matrix_tunnel.py -v` passes
- [ ] `get_or_create("a","b")` and `("b","a")` return the same tunnel; room created once with `is_direct=True` and both invitees
- [ ] `ask()` roundtrip resolves via `correlation_id`; timeout/hop-limit/error/schema_error envelopes as specified
- [ ] Sweeper tombstones idle tunnels; `ttl_minutes=0` never sweeps
- [ ] `ruff check` clean

---

## Test Specification

```python
# tests/test_matrix_tunnel.py
import asyncio, pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.matrix.crew.config import TunnelConfig
from parrot.integrations.matrix.crew.tunnel import TunnelRegistry
from parrot.integrations.matrix.events import ParrotEventType, ResultEventContent

@pytest.fixture
def reg():
    svc = AsyncMock(); svc.create_room_as_bot.return_value = "!tun:parrot.local"
    svc.list_agents = MagicMock(return_value={"a": "@parrot-a:parrot.local", "b": "@parrot-b:parrot.local"})
    svc.send_custom_event_as_agent.return_value = "$task"
    channels = MagicMock(); channels._space_id = None
    return TunnelRegistry(TunnelConfig(default_timeout=0.2, max_hops=2), svc, channels, wrappers={}, server_name="parrot.local"), svc

async def test_symmetric_lazy_creation(reg):
    r, svc = reg
    t1 = await r.get_or_create("a", "b"); t2 = await r.get_or_create("b", "a")
    assert t1 is t2 and svc.create_room_as_bot.await_count == 1
    kw = svc.create_room_as_bot.call_args.kwargs
    assert kw["is_direct"] is True and set(kw["invitees"]) == {"@parrot-a:parrot.local", "@parrot-b:parrot.local"}

async def test_ask_roundtrip(reg):
    r, svc = reg; t = await r.get_or_create("a", "b")
    async def deliver():
        await asyncio.sleep(0.01)
        sent = svc.send_custom_event_as_agent.call_args.args[3]
        await r.on_custom_event(ParrotEventType.RESULT, ResultEventContent(task_id=sent["task_id"], content='{"answer": "42", "confidence": 0.8}',
                                metadata={"correlation_id": sent["correlation_id"]}).model_dump(), "!tun:parrot.local", "@parrot-b:parrot.local")
    asyncio.create_task(deliver())
    ans = await t.ask("a", "b", "meaning?")
    assert ans.answer == "42" and ans.confidence == 0.8 and ans.metadata["status"] == "ok"

async def test_ask_timeout(reg):
    r, _ = reg; t = await r.get_or_create("a", "b")
    assert (await t.ask("a", "b", "q")).metadata["status"] == "timeout"

async def test_hop_limit(reg):
    r, svc = reg; t = await r.get_or_create("a", "b")
    assert (await t.ask("a", "b", "q", hops=2)).metadata["status"] == "hop_limit"
    svc.send_custom_event_as_agent.assert_not_awaited()

async def test_schema_error(reg):
    r, svc = reg; t = await r.get_or_create("a", "b")
    async def deliver():
        await asyncio.sleep(0.01); sent = svc.send_custom_event_as_agent.call_args.args[3]
        await r.on_custom_event(ParrotEventType.RESULT, ResultEventContent(task_id=sent["task_id"], content='{"answer": {"x": 1}}',
                                metadata={"correlation_id": sent["correlation_id"]}).model_dump(), "!tun:parrot.local", "@b:s")
    asyncio.create_task(deliver())
    ans = await t.ask("a", "b", "q", expected_schema={"type": "object", "required": ["total"]})
    assert ans.metadata["status"] == "schema_error"

async def test_sweeper_tombstones_idle(reg):
    r, svc = reg; t = await r.get_or_create("a", "b")
    t.last_used = datetime.now(timezone.utc) - timedelta(minutes=500)
    assert await r._sweep_once() == 1
    assert svc.leave_as_agent.await_count == 2
    assert any(c.args[1] == "m.room.tombstone" for c in svc.set_room_state_as_bot.await_args_list)
    assert not r.is_tunnel_room("!tun:parrot.local")

async def test_ttl_zero_never_sweeps(reg):
    r, svc = reg; r.config.ttl_minutes = 0
    t = await r.get_or_create("a", "b"); t.last_used = datetime.now(timezone.utc) - timedelta(days=30)
    assert await r._sweep_once() == 0
```

---

## Agent Instructions

Same as TASK-2478.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
