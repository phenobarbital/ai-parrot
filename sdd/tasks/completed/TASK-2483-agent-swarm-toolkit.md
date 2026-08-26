# TASK-2483: AgentSwarmToolkit

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2480, TASK-2481, TASK-2482
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Exposes the tunnel primitive to each agent's LLM as tools:
`ask_agent`, `send_feedback`, `list_agents`, `list_channels`, `post_to_channel`. Built on
`AbstractToolkit`, whose public async methods become tools automatically (names starting
with `_` are skipped — `toolkit.py:537-545`). Attachment to bots happens in TASK-2484 via
`ToolManager.register_toolkit(instance)` (`manager.py:1008`, verified — resolves spec §8 open question).

---

## Scope

- Create `crew/swarm_toolkit.py` with `AgentSwarmToolkit(AbstractToolkit)`.
- Tools (docstrings are the LLM descriptions — write them carefully):
  - `ask_agent(agent: str, question: str, expected_schema: Optional[dict] = None, timeout: Optional[float] = None) -> dict`
    → `AgentAnswer.model_dump()`; unknown agent → `{"status": "unknown_agent", "available": [...]}`; self-ask rejected.
  - `send_feedback(agent: str, about_event_id: str, rating: int, comment: Optional[str] = None) -> str`
  - `list_agents() -> List[dict]` from `MatrixCrewRegistry.all_agents()` (`agent_name, display_name, status, skills`)
  - `list_channels() -> List[dict]` from `ChannelManager.list_channels()` (only channels this agent is a member of + public ones)
  - `post_to_channel(channel: str, text: str) -> str` → `send_as_agent`; rejected when not a member (`ValueError` → return `{"status": "forbidden"}` string-ish message).
- `hops` propagation: the toolkit holds a contextvar `current_hops` / `current_session` set by
  `handle_task` (TASK-2482) — implement `parrot.integrations.matrix.crew.context` with two
  `contextvars.ContextVar`s and make `handle_task` set them around `agent.ask()` (small follow-up edit
  in `crew_wrapper.py`). `ask_agent` reads them so A→B→A loops hit `max_hops`.
- Optional echo: when `TunnelConfig.echo_summary_to_channel` and a `channel_room_id` is known
  (contextvar `current_channel_room`), post `🔒 <requester> asked <target> a question` as the requester
  via `send_reply_as_agent` (reply-to `current_trigger_event`) — default **on**.
- Tests.

**NOT in scope**: attaching to bots, session integration (TASK-2484/2485).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` | CREATE | toolkit |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/context.py` | CREATE | contextvars: `current_hops`, `current_session`, `current_channel_room`, `current_trigger_event` |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/crew_wrapper.py` | MODIFY | set/reset contextvars in `handle_task` and `handle_message` |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/__init__.py` | MODIFY | export `AgentSwarmToolkit` |
| `packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools import AbstractToolkit                       # parrot/tools/__init__.py:143 → tools/toolkit.py:216
from parrot.integrations.matrix.crew.tunnel import TunnelRegistry, AgentTunnel     # TASK-2481
from parrot.integrations.matrix.crew.channels import ChannelManager                # TASK-2480
from parrot.integrations.matrix.crew.registry import MatrixCrewRegistry            # registry.py:65
from parrot.integrations.matrix.events import AgentAnswer                          # TASK-2478
```

### Existing Signatures to Use
```python
# parrot/tools/toolkit.py
class AbstractToolkit(ABC):                     # :216 — "automatically converts all public async methods into tools"
    def __init__(self, **kwargs)                # :312
    def get_tools(...)                          # :484
    def _generate_tools(self) -> None           # :537 ; skips names starting with '_' (:545)
# parrot/tools/manager.py
class ToolManager.register_toolkit(self, toolkit: Union[str, AbstractToolkit, type], **kwargs) -> List[AbstractTool]   # :1008 (instance accepted)
# crew/registry.py
async def all_agents(self) -> List[MatrixAgentCard]     # :191 ; MatrixAgentCard: agent_name, display_name, mxid, status, skills (:14)
async def get(self, agent_name) -> Optional[MatrixAgentCard]   # :162
# appservice.py
async def send_as_agent(self, agent_name, room_id, message) -> str                        # :239
async def send_reply_as_agent(self, agent_name, room_id, message, reply_to_event_id) -> str   # :349
```

### Does NOT Exist
- ~~`@tool`-decorated functions for this~~ — use the toolkit; do not create standalone tools.
- ~~`ToolManager.add_toolkit`~~ — the method is `register_toolkit` (`manager.py:1008`).
- ~~a contextvars module in `crew/`~~ — you create `crew/context.py`.

---

## Implementation Notes

### Skeleton
```python
class AgentSwarmToolkit(AbstractToolkit):
    """Tools that let this agent talk to peer agents through private Matrix tunnels."""

    def __init__(self, agent_name: str, tunnels: TunnelRegistry, registry: MatrixCrewRegistry,
                 channels: ChannelManager, appservice: MatrixAppService, **kwargs) -> None:
        self._agent_name = agent_name; self._tunnels = tunnels; self._registry = registry
        self._channels = channels; self._as = appservice
        super().__init__(**kwargs)

    async def ask_agent(self, agent: str, question: str, expected_schema: Optional[dict] = None,
                        timeout: Optional[float] = None) -> dict:
        """Ask another agent of the swarm a question through a private tunnel and wait for its
        structured answer. Returns {answer, confidence, sources, metadata.status}. Use
        `list_agents` to discover names. Do not ask yourself."""
        if agent == self._agent_name: return {"status": "self_ask_rejected"}
        if await self._registry.get(agent) is None:
            return {"status": "unknown_agent", "available": [c.agent_name for c in await self._registry.all_agents()]}
        tunnel = await self._tunnels.get_or_create(self._agent_name, agent)
        await self._maybe_echo(agent)
        ans = await tunnel.ask(self._agent_name, agent, question, expected_schema=expected_schema, timeout=timeout,
                               hops=current_hops.get(), origin_session=current_session.get())
        return ans.model_dump()
    ...
```

### Key Constraints
- Every public method is a tool: keep helpers `_private`.
- Return JSON-serialisable values only (dict/list/str).
- Tool docstrings: one sentence of purpose + when to use; parameters described.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py -v` passes
- [ ] `get_tools()` yields exactly `ask_agent, send_feedback, list_agents, list_channels, post_to_channel`
- [ ] Non-member `post_to_channel` refused; unknown agent / self-ask return status envelopes
- [ ] Echo line posted by default, suppressed when `echo_summary_to_channel=False`

---

## Test Specification

```python
# tests/test_matrix_swarm_toolkit.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.matrix.crew.swarm_toolkit import AgentSwarmToolkit
from parrot.integrations.matrix.crew import context as ctx
from parrot.integrations.matrix.events import AgentAnswer

@pytest.fixture
def tk():
    tunnels = AsyncMock(); tunnel = AsyncMock(); tunnel.ask.return_value = AgentAnswer(answer="42", metadata={"status": "ok"})
    tunnels.get_or_create.return_value = tunnel; tunnels.config = MagicMock(echo_summary_to_channel=True)
    registry = AsyncMock(); registry.get.side_effect = lambda n: MagicMock(agent_name=n) if n in ("writer", "analyst") else None
    registry.all_agents.return_value = [MagicMock(agent_name="writer", display_name="W", status="ready", skills=[])]
    channels = MagicMock(); channels.is_member.side_effect = lambda a, c: c == "general"
    channels.room_for_channel.return_value = "!gen:s"; channels.list_channels.return_value = [{"name": "general", "visibility": "public"}]
    svc = AsyncMock()
    return AgentSwarmToolkit("analyst", tunnels, registry, channels, svc), tunnel, svc

def test_exposes_five_tools(tk):
    names = sorted(t.name for t in tk[0].get_tools())
    assert names == ["ask_agent", "list_agents", "list_channels", "post_to_channel", "send_feedback"]

async def test_ask_agent_roundtrip(tk):
    t, tunnel, _ = tk
    out = await t.ask_agent("writer", "hi")
    assert out["answer"] == "42" and tunnel.ask.await_args.kwargs["hops"] == 0

async def test_ask_agent_propagates_hops(tk):
    t, tunnel, _ = tk
    token = ctx.current_hops.set(2)
    try: await t.ask_agent("writer", "hi")
    finally: ctx.current_hops.reset(token)
    assert tunnel.ask.await_args.kwargs["hops"] == 2

async def test_unknown_and_self(tk):
    t, _, _ = tk
    assert (await t.ask_agent("ghost", "q"))["status"] == "unknown_agent"
    assert (await t.ask_agent("analyst", "q"))["status"] == "self_ask_rejected"

async def test_post_to_channel_policy(tk):
    t, _, svc = tk
    await t.post_to_channel("general", "hello"); svc.send_as_agent.assert_awaited_once()
    assert "forbidden" in str(await t.post_to_channel("finance", "x"))

async def test_echo_default_on(tk):
    t, _, svc = tk
    tok = ctx.current_channel_room.set("!gen:s"); tok2 = ctx.current_trigger_event.set("$trig")
    try: await t.ask_agent("writer", "q")
    finally: ctx.current_channel_room.reset(tok); ctx.current_trigger_event.reset(tok2)
    svc.send_reply_as_agent.assert_awaited_once()
```

---

## Agent Instructions

Same as TASK-2478.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Created `crew/swarm_toolkit.py` with `AgentSwarmToolkit
(AbstractToolkit)` exposing exactly 5 tools (`ask_agent`, `send_feedback`,
`list_agents`, `list_channels`, `post_to_channel`) per the skeleton, plus
`crew/context.py` with the 4 `contextvars` (`current_hops`,
`current_session`, `current_channel_room`, `current_trigger_event`).
`MatrixCrewAgentWrapper.handle_message` now sets a fresh hop chain
(`hops=0`, `session=None`) plus the originating `room_id`/`event_id` for
the echo line, and `handle_task` propagates `task.hops` /
`task.origin_session` — both reset via `contextvars.Token` in their
`finally` blocks so nested/concurrent requests stay isolated.
`ask_agent` rejects self-asks and unknown agents before touching the
tunnel, propagates `current_hops`/`current_session` into
`AgentTunnel.ask`, and posts the optional echo (`send_reply_as_agent`)
only when `TunnelConfig.echo_summary_to_channel` is set AND both context
vars are populated. `post_to_channel` checks `ChannelManager.is_member`
before resolving the room and calling `send_as_agent`. 6/6 new tests
pass; full matrix regression 214/220 pass (6 pre-existing
`test_matrix_hook.py` failures, unrelated). `ruff check` matches the
established `crew/` baseline categories with no new ones (verified via
`git stash`).
**Deviations from spec**: none
