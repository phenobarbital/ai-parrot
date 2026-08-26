# TASK-2485: Collaborative Session — Trigger Reply-to & Tunnel Cross-Pollination

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2481, TASK-2484
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (session half). `MatrixCollaborativeSession` becomes concurrency-safe
(per-session state only, no room-level assumptions), learns the trigger event so the final
synthesis is a reply to the human's question, and routes the cross-pollination phase through
tunnels instead of visible channel mentions — posting only the one-line echo by default.

---

## Scope

- `MatrixCollaborativeSession.__init__`: add `trigger_event_id: Optional[str] = None`,
  `tunnels: Optional[TunnelRegistry] = None` (keyword-only, defaults keep FEAT-195 callers working).
- Announcements and final synthesis: when `trigger_event_id` is set, use `send_reply_as_bot` /
  `send_reply_as_agent` (reply-to trigger) instead of plain sends; prefix announcements with the
  short `session_id` (`🐦 Swarm session #ab12 started (3 agents)`).
- `_cross_pollinate_phase(round_num)`: when `tunnels` is set, for each agent A pick peers from
  the previous round's results and call `tunnel.ask(A, B, question_built_from(B's result),
  origin_session=self.session_id, hops=0)` in parallel (`asyncio.gather`); merge the
  `AgentAnswer.answer` texts into the enriched prompt for A (`_build_enriched_context` gains an
  optional `peer_answers: Dict[str, str]` argument); echo line per ask when
  `tunnels.config.echo_summary_to_channel` (reply-to trigger). Fallback to the current channel-
  mention behaviour when `tunnels is None`.
- Set contextvars (`crew/context.py`: `current_session`, `current_channel_room`, `current_trigger_event`)
  around every `agent.ask` in `_call_agent_with_timeout` so `AgentSwarmToolkit` calls made by the
  LLM inside a session carry `origin_session` and echo to the right room.
- `handle_inter_agent_message` unchanged (legacy path).
- `_run_session` in transport (TASK-2484) already pops by session id — verify with a test that two
  sessions in one room keep separate `agent_results`.
- Tests.

**NOT in scope**: swarm policy dispatch (TASK-2484), toolkit (TASK-2483).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/session.py` | MODIFY | trigger reply-to, tunnel cross-pollination, contextvars |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/transport.py` | MODIFY | `_build_session` passes `trigger_event_id`, `tunnels` |
| `packages/ai-parrot-integrations/tests/test_matrix_session_tunnel.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew.session import MatrixCollaborativeSession     # session.py:40
from parrot.integrations.matrix.crew.session_models import AgentRoundResult, CollaborativeSessionState, SessionPhase   # session_models.py:34/:60/:14
from parrot.integrations.matrix.crew.tunnel import TunnelRegistry                  # TASK-2481
from parrot.integrations.matrix.crew import context as ctx                         # TASK-2483
```

### Existing Signatures to Use
```python
# crew/session.py
class MatrixCollaborativeSession:                                                   # :40
    def __init__(self, session_id: str, room_id: str, question: str, config: CollaborativeConfig,
                 appservice: MatrixAppService, registry: MatrixCrewRegistry,
                 wrappers: Dict[str, MatrixCrewAgentWrapper], server_name: str) -> None   # :58
    @property phase -> SessionPhase :92 ; is_active -> bool :97
    async def run(self) -> CollaborativeSessionState                                 # :108
    async def handle_inter_agent_message(self, sender_mxid, body, event_id) -> None  # :147
    async def _investigate_phase(self) -> None                                       # :258
    async def _cross_pollinate_phase(self, round_num: int) -> None                   # :285 — all_agents() minus summarizer; enriched_prompt =
                                                                                     #        _build_enriched_context(round_num, name); gather _call_agent_with_timeout
    async def _synthesize_phase(self) -> None                                        # :313
    async def _call_agent_with_timeout(self, card, wrapper, prompt, round_number) -> Optional[AgentRoundResult]   # :383 — BotManager.get_bot :402, wait_for(agent.ask) :408-410, send_as_agent :421
    def _build_enriched_context(self, round_num: int, requesting_agent: str) -> str  # :472
    def _build_synthesizer_payload(self) -> str                                      # :516
    async def _announce(self, message: str) -> None                                  # :582 — respects config.session_verbosity
# state: self._state: CollaborativeSessionState (session_id, room_id, question, phase, current_round, agent_results: Dict[str, List[AgentRoundResult]])
# appservice.py
async def send_reply_as_bot(self, room_id, message, reply_to_event_id) -> str        # :393
async def send_reply_as_agent(self, agent_name, room_id, message, reply_to_event_id) -> str   # :349
```

### Does NOT Exist
- ~~`m.thread` relations~~ — reply-to only (`m.in_reply_to`).
- ~~session persistence / store~~ — in-memory only; do not add one.
- ~~`MatrixCollaborativeSession.trigger_event_id` / `tunnels`~~ — you add them (keyword-only, defaulted).

---

## Implementation Notes

### Cross-pollination via tunnels (sketch)
```python
async def _cross_pollinate_phase(self, round_num: int) -> None:
    prev = {name: rs[-1] for name, rs in self._state.agent_results.items() if rs}
    agents = [c for c in await self._registry.all_agents() if c.agent_name != self._config.summarizer_agent]
    async def enrich(card):
        peer_answers: Dict[str, str] = {}
        if self._tunnels is not None:
            peers = [p for p in prev if p != card.agent_name]
            asks = [self._ask_peer(card.agent_name, p, prev[p]) for p in peers]
            for p, ans in zip(peers, await asyncio.gather(*asks, return_exceptions=True)):
                if not isinstance(ans, Exception) and ans.answer is not None:
                    peer_answers[p] = str(ans.answer)
        prompt = self._build_enriched_context(round_num, card.agent_name, peer_answers=peer_answers)
        wrapper = self._wrappers.get(card.agent_name)
        return await self._call_agent_with_timeout(card, wrapper, prompt, round_number=round_num) if wrapper else None
    await asyncio.gather(*(enrich(c) for c in agents), return_exceptions=True)

async def _ask_peer(self, requester: str, target: str, their_result: AgentRoundResult) -> AgentAnswer:
    tunnel = await self._tunnels.get_or_create(requester, target)
    if self._tunnels.config.echo_summary_to_channel:
        await self._appservice.send_reply_as_agent(requester, self._room_id,
            f"🔒 asked {target} to clarify their findings", self._trigger_event_id or their_result.event_id)
    q = f"Regarding your finding: {their_result.result_text[:800]}\nWhat evidence supports it and what would change your view?"
    return await tunnel.ask(requester, target, q, origin_session=self._session_id, hops=0, timeout=self._config.agent_timeout)
```

### Key Constraints
- Never block one agent's enrichment on another's tunnel timeout (`return_exceptions=True`).
- `session_verbosity == "silent"` suppresses the echo lines too.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/test_matrix_session_tunnel.py packages/ai-parrot-integrations/tests/test_matrix_collaborative_session.py packages/ai-parrot-integrations/tests/test_matrix_transport_collaborative.py -v` passes
- [ ] Cross-pollination calls `TunnelRegistry.get_or_create().ask()` when tunnels are configured; legacy mention path when not
- [ ] Echo line posted (reply-to trigger) by default; none when `echo_summary_to_channel=False` or verbosity `silent`
- [ ] Final synthesis is a reply to `trigger_event_id`; two concurrent sessions in one room keep separate results

---

## Test Specification

```python
# tests/test_matrix_session_tunnel.py  (reuse fixtures/helpers from tests/test_matrix_collaborative_session.py)
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.matrix.crew.config import CollaborativeConfig
from parrot.integrations.matrix.crew.session import MatrixCollaborativeSession
from parrot.integrations.matrix.events import AgentAnswer

def _session(tunnels, **kw):
    svc = AsyncMock(); svc.send_as_agent.return_value = "$r"; svc.send_reply_as_agent.return_value = "$echo"; svc.send_reply_as_bot.return_value = "$b"
    registry = AsyncMock(); registry.all_agents.return_value = [MagicMock(agent_name=n, display_name=n, mxid=f"@{n}:s") for n in ("a", "b")]
    wrappers = {n: MagicMock(_config=MagicMock(chatbot_id=n)) for n in ("a", "b")}
    s = MatrixCollaborativeSession("s1", "!gen:s", "Q?", CollaborativeConfig(max_rounds=1), svc, registry, wrappers, "s",
                                   trigger_event_id="$trig", tunnels=tunnels, **kw)
    return s, svc

async def test_cross_pollination_uses_tunnel():
    tunnel = AsyncMock(); tunnel.ask.return_value = AgentAnswer(answer="evidence", metadata={"status": "ok"})
    tunnels = AsyncMock(); tunnels.get_or_create.return_value = tunnel; tunnels.config = MagicMock(echo_summary_to_channel=True)
    s, svc = _session(tunnels)
    bot = MagicMock(); bot.ask = AsyncMock(return_value="finding")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await s.run()
    assert tunnel.ask.await_count == 2                 # a→b and b→a
    assert svc.send_reply_as_agent.await_count >= 2    # echo lines
    assert svc.send_reply_as_bot.await_args.args[2] == "$trig"   # final reply-to trigger

async def test_no_echo_when_disabled():
    tunnel = AsyncMock(); tunnel.ask.return_value = AgentAnswer(answer="x")
    tunnels = AsyncMock(); tunnels.get_or_create.return_value = tunnel; tunnels.config = MagicMock(echo_summary_to_channel=False)
    s, svc = _session(tunnels)
    bot = MagicMock(); bot.ask = AsyncMock(return_value="f")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await s.run()
    assert not any("🔒" in c.args[2] for c in svc.send_reply_as_agent.await_args_list)

async def test_legacy_path_without_tunnels():
    s, svc = _session(None)
    bot = MagicMock(); bot.ask = AsyncMock(return_value="f")
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        await s.run()
    assert s.phase.value == "completed"

async def test_two_sessions_isolated():
    s1, _ = _session(None); s2, _ = _session(None)
    bot = MagicMock(); bot.ask = AsyncMock(side_effect=["r1", "r1", "s", "r2", "r2", "s"])
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        st1 = await s1.run(); st2 = await s2.run()
    assert st1.agent_results != st2.agent_results
```

---

## Agent Instructions

Same as TASK-2478.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: `MatrixCollaborativeSession.__init__` gained keyword-only
`trigger_event_id`/`tunnels` (both default `None`, FEAT-195 callers
unaffected). `_announce`, `_synthesize_phase`'s summarizer-success branch,
and `_post_raw_results` now use `send_reply_as_bot`/`send_reply_as_agent`
(reply-to `trigger_event_id`) instead of plain sends when it is set;
`_announce` also prefixes with the short session id
(`🐦 [#<sid[:4]>] ...`) in that case. `_cross_pollinate_phase` was
rewritten per the skeleton's `enrich()`/`_ask_peer` pattern: when
`tunnels` is attached, each agent privately asks its peers (in parallel
via `asyncio.gather(..., return_exceptions=True)`, never blocking on one
peer's timeout) to clarify their prior finding through
`TunnelRegistry.get_or_create().ask()`, posting an optional one-line echo
(reply-to trigger, suppressed when `echo_summary_to_channel=False` or
`session_verbosity="silent"`) via `_ask_peer`; peer answers fold into
`_build_enriched_context`'s new optional `peer_answers` param. Without
`tunnels`, cross-pollination is byte-for-byte the original FEAT-195
behaviour. `_call_agent_with_timeout` now sets/resets
`current_session`/`current_channel_room`/`current_trigger_event` around
`agent.ask()` so LLM-issued `AgentSwarmToolkit.ask_agent` calls inherit
the session's origin. `transport.py::_build_session` was simplified to
pass `trigger_event_id`/`tunnels` directly (the `inspect.signature` guard
added defensively in TASK-2484 is no longer needed now that the
constructor accepts them; `inspect` import removed as it became unused).
4/4 new tests pass; full acceptance-criteria run (`test_matrix_session_tunnel.py`
+ `test_matrix_collaborative_session.py` + `test_matrix_transport_collaborative.py`)
41/41 pass; full `pytest -k matrix` 228/234 pass (6 pre-existing
`test_matrix_hook.py` failures, unrelated, unchanged since TASK-2478).
`ruff check` shows only proportional increases in the same pre-existing
categories already established in `session.py`/`transport.py` (verified
via `git stash`) — no new categories.
**Deviations from spec**: none
