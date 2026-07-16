---
type: Wiki Overview
title: 'TASK-1298: Collaborative Session Orchestrator'
id: doc:sdd-tasks-completed-task-1298-collaborative-session-orchestrator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core of the collaborative feature. `MatrixCollaborativeSession`
  orchestrates
relates_to:
- concept: mod:parrot.integrations.matrix.appservice
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.config
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.crew_wrapper
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.mention
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.registry
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.session
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.session_models
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1298: Collaborative Session Orchestrator

**Feature**: FEAT-195 — Matrix Collaborative Multi-Agent Crew
**Spec**: `sdd/specs/matrix-collaborative-crew.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1295, TASK-1296, TASK-1297
**Assigned-to**: unassigned

---

## Context

This is the core of the collaborative feature. `MatrixCollaborativeSession` orchestrates
the full session lifecycle: investigate → cross-pollinate → synthesize. It uses the
reply-to support (TASK-1295), config (TASK-1296), and session state models (TASK-1297)
to run phased rounds where all agents investigate a question in parallel, exchange
enriched context, and produce a final synthesis.

Implements Spec Module 4.

---

## Scope

- Create `parrot/integrations/matrix/crew/session.py` with `MatrixCollaborativeSession` class:
  - Constructor takes `session_id`, `room_id`, `question`, `config: CollaborativeConfig`,
    `appservice: MatrixAppService`, `registry: MatrixCrewRegistry`,
    `wrappers: Dict[str, MatrixCrewAgentWrapper]`, `server_name: str`.
  - Properties: `phase -> SessionPhase`, `is_active -> bool`.
  - `async def run() -> CollaborativeSessionState`: Full lifecycle execution.
  - `async def handle_inter_agent_message(sender_mxid, body, event_id) -> None`: Route @mentions during sessions.
  - `async def cancel(reason: str) -> None`: Cancel session, post notice.
- Implement the three session phases:
  1. **INVESTIGATING**: Call all agents in parallel via `asyncio.gather()` with `agent_timeout`.
  2. **CROSS_POLLINATING**: For each round (1..max_rounds), build enriched context prompt
     from prior results, call all agents again. Route inter-agent @mentions.
  3. **SYNTHESIZING**: Call the summarizer agent with structured `{agent_name: result}` payload.
     If no summarizer configured, post raw results.
- Post phase announcements via `appservice.send_as_bot()` (respects `session_verbosity`).
- Handle agent timeouts (skip with notice) and all-agents-fail → FAILED state.
- Export from `crew/__init__.py`.
- Write comprehensive unit tests.

**NOT in scope**: Transport routing changes (`on_room_message`), tool delegation, example code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/matrix/crew/session.py` | CREATE | Core session orchestrator |
| `parrot/integrations/matrix/crew/__init__.py` | MODIFY | Add `MatrixCollaborativeSession` export |
| `tests/test_matrix_collaborative_session.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew.session_models import (
    SessionPhase, AgentRoundResult, CollaborativeSessionState,
)  # created in TASK-1297
from parrot.integrations.matrix.crew.config import CollaborativeConfig  # created in TASK-1296
from parrot.integrations.matrix.crew.config import MatrixCrewConfig
from parrot.integrations.matrix.appservice import MatrixAppService  # matrix/__init__.py
from parrot.integrations.matrix.crew.registry import MatrixCrewRegistry  # crew/__init__.py
from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper  # crew/__init__.py
from parrot.integrations.matrix.crew.mention import parse_mention, build_pill  # crew/__init__.py
from parrot.manager.manager import BotManager  # parrot/manager/manager.py:605
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import asyncio
import logging
import uuid
```

### Existing Signatures to Use
```python
# parrot/integrations/matrix/appservice.py:239
async def send_as_agent(
    self, agent_name: str, room_id: str, message: str
) -> str:  # returns event_id

# parrot/integrations/matrix/appservice.py:263
async def send_as_bot(self, room_id: str, message: str) -> str

# parrot/integrations/matrix/appservice.py — NEW from TASK-1295:
async def send_reply_as_agent(
    self, agent_name: str, room_id: str, message: str, reply_to_event_id: str
) -> str

async def send_reply_as_bot(
    self, room_id: str, message: str, reply_to_event_id: str
) -> str

# parrot/integrations/matrix/crew/crew_wrapper.py:68
class MatrixCrewAgentWrapper:
    _agent_name: str                                    # line 53
    _config: MatrixCrewAgentEntry                       # line 54
    _mxid: str                                          # line 61
    async def handle_message(                           # line 68
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:

# parrot/integrations/matrix/crew/registry.py:191
class MatrixCrewRegistry:
    async def all_agents(self) -> List[MatrixAgentCard]:
    async def get(self, name: str) -> Optional[MatrixAgentCard]:
    async def get_by_mxid(self, mxid: str) -> Optional[MatrixAgentCard]:

# parrot/integrations/matrix/crew/registry.py:14
class MatrixAgentCard(BaseModel):
    agent_name: str
    display_name: str
    mxid: str
    status: str = "offline"
    skills: List[str] = []

# parrot/integrations/matrix/crew/mention.py:19
def parse_mention(body: str, server_name: str) -> Optional[str]:

# parrot/integrations/matrix/crew/mention.py:68
def build_pill(mxid: str, display_name: str) -> str:

# parrot/bots/abstract.py:3660
class AbstractBot:
    async def ask(
        self, question: str, session_id=None, user_id=None,
        use_conversation_history=True, use_tools=True, **kwargs
    ) -> AIMessage:

# parrot/manager/manager.py:605
class BotManager:
    async def get_bot(
        self, name: str, new=False, session_id="",
        request=None, **kwargs
    ) -> AbstractBot:
```

### Does NOT Exist
- ~~`MatrixCrewTransport.broadcast_message()`~~ — no broadcast method exists
- ~~`AgentCrew` Matrix awareness~~ — AgentCrew has no concept of Matrix rooms/messages
- ~~`MatrixCollaborativeSession`~~ — this is what we're creating
- ~~`FlowContext` Matrix message tracking~~ — no event_id or reply-to tracking

---

## Implementation Notes

### Pattern to Follow
```python
class MatrixCollaborativeSession:
    def __init__(
        self,
        session_id: str,
        room_id: str,
        question: str,
        config: CollaborativeConfig,
        appservice: MatrixAppService,
        registry: MatrixCrewRegistry,
        wrappers: Dict[str, MatrixCrewAgentWrapper],
        server_name: str,
    ) -> None:
        self._session_id = session_id
        self._room_id = room_id
        self._question = question
        self._config = config
        self._appservice = appservice
        self._registry = registry
        self._wrappers = wrappers
        self._server_name = server_name
        self._state = CollaborativeSessionState(
            session_id=session_id, room_id=room_id, question=question,
            max_rounds=config.max_rounds,
        )
        self.logger = logging.getLogger(__name__)

    async def run(self) -> CollaborativeSessionState:
        self._state.started_at = datetime.now(timezone.utc)
        self._state.phase = SessionPhase.INVESTIGATING
        try:
            await self._announce(f"Starting investigation: {self._question}")
            await self._investigate_phase()
            for round_num in range(1, self._config.max_rounds + 1):
                self._state.phase = SessionPhase.CROSS_POLLINATING
                self._state.current_round = round_num
                await self._cross_pollinate_phase(round_num)
            self._state.phase = SessionPhase.SYNTHESIZING
            await self._synthesize_phase()
            self._state.phase = SessionPhase.COMPLETED
        except Exception as e:
            self._state.phase = SessionPhase.FAILED
            self.logger.error("Session %s failed: %s", self._session_id, e)
        self._state.completed_at = datetime.now(timezone.utc)
        return self._state

    async def _investigate_phase(self):
        """Call all agents in parallel with asyncio.gather + timeout."""
        agents = await self._registry.all_agents()
        tasks = []
        for card in agents:
            if card.agent_name == self._config.summarizer_agent:
                continue  # skip summarizer during investigation
            wrapper = self._wrappers.get(card.agent_name)
            if wrapper:
                tasks.append(self._call_agent_with_timeout(
                    card, wrapper, self._question, round_number=0
                ))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Process results, skip timeouts...

    async def _call_agent_with_timeout(self, card, wrapper, prompt, round_number):
        """Call a single agent with agent_timeout."""
        try:
            return await asyncio.wait_for(
                self._invoke_agent(card, wrapper, prompt, round_number),
                timeout=self._config.agent_timeout,
            )
        except asyncio.TimeoutError:
            await self._announce(f"{card.display_name} timed out, skipping.")
            return None

    async def _cross_pollinate_phase(self, round_num):
        """Build enriched context from prior results, call all agents."""
        enriched = self._build_enriched_context(round_num)
        # Similar to _investigate_phase but with enriched prompt...

    async def _synthesize_phase(self):
        """Call summarizer with structured payload."""
        if self._config.summarizer_agent:
            # Build {agent_name: result_text} payload
            # Call summarizer
            pass
        else:
            # Post raw results as fallback
            pass
```

### Key Constraints
- All I/O is async — use `asyncio.gather()` for parallel agent calls.
- `asyncio.wait_for()` with `config.agent_timeout` per agent.
- `asyncio.wait_for()` with `config.session_timeout` for the entire `run()`.
- Use `BotManager.get_bot(chatbot_id)` → `agent.ask(enriched_prompt)` pattern from `crew_wrapper.py:111-118`.
- Enriched context prompt format:
  ```
  Original question: <question>
  Round N cross-pollination. Other agents' findings:
  - [Agent A]: <summary of A's result>
  - [Agent B]: <summary of B's result>
  Review your peers' findings and refine your analysis. You may @mention
  a colleague to ask them a question or request them to use a tool.
  ```
- Phase announcements via `appservice.send_as_bot()`.
- Respect `session_verbosity` config: "full" (all announcements), "minimal", "silent".
- Agent results posted via `appservice.send_as_agent()` or `send_reply_as_agent()`.
- Summarizer agent receives structured JSON-like payload, NOT free-form text.
- If all agents fail (timeout/error), set `phase = FAILED` and post error notice.

### References in Codebase
- `parrot/integrations/matrix/crew/crew_wrapper.py:68-120` — agent invocation pattern
- `parrot/integrations/matrix/crew/crew_wrapper.py:111` — `BotManager.get_bot()` usage
- `parrot/integrations/matrix/crew/mention.py:19` — `parse_mention()` for detecting @mentions
- `parrot/integrations/matrix/crew/coordinator.py:108` — status change notification pattern
- `parrot/bots/flows/crew/crew.py` — `AgentCrew.run_parallel()` as conceptual reference (NOT code dependency)

---

## Acceptance Criteria

- [ ] `MatrixCollaborativeSession` class created with full constructor
- [ ] `run()` executes investigate → cross-pollinate → synthesize lifecycle
- [ ] All agents called in parallel during investigation phase
- [ ] Cross-pollination injects enriched context from prior results
- [ ] `handle_inter_agent_message()` routes @mentions during active session
- [ ] Summarizer receives structured `{agent_name: result}` payload
- [ ] Summarizer fallback: raw results posted if no summarizer configured
- [ ] Agent timeout honored — timed-out agents skipped with notice
- [ ] Session timeout honored — entire session cancelled if exceeded
- [ ] All-agents-fail → FAILED phase with error notice
- [ ] Phase announcements respect `session_verbosity`
- [ ] `cancel()` transitions to FAILED and posts notice
- [ ] Model exported from `parrot.integrations.matrix.crew`
- [ ] All tests pass: `pytest tests/test_matrix_collaborative_session.py -v`
- [ ] No linting errors: `ruff check parrot/integrations/matrix/crew/session.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from parrot.integrations.matrix.crew.session import MatrixCollaborativeSession
from parrot.integrations.matrix.crew.session_models import (
    SessionPhase, CollaborativeSessionState,
)
from parrot.integrations.matrix.crew.config import CollaborativeConfig


@pytest.fixture
def collaborative_config():
    return CollaborativeConfig(
        max_rounds=1,
        agent_timeout=5.0,
        session_timeout=30.0,
        summarizer_agent="summarizer",
    )


@pytest.fixture
def mock_appservice():
    appservice = AsyncMock()
    appservice.send_as_bot.return_value = "$bot_event"
    appservice.send_as_agent.return_value = "$agent_event"
    appservice.send_reply_as_agent.return_value = "$reply_event"
    appservice.send_reply_as_bot.return_value = "$reply_bot_event"
    return appservice


@pytest.fixture
def mock_registry():
    registry = AsyncMock()
    card_a = MagicMock(agent_name="analyst", display_name="Analyst", mxid="@analyst:server")
    card_b = MagicMock(agent_name="researcher", display_name="Researcher", mxid="@researcher:server")
    card_sum = MagicMock(agent_name="summarizer", display_name="Summarizer", mxid="@summarizer:server")
    registry.all_agents.return_value = [card_a, card_b, card_sum]
    registry.get_by_mxid.return_value = card_a
    return registry


@pytest.fixture
def mock_wrappers():
    wrappers = {}
    for name in ("analyst", "researcher", "summarizer"):
        w = AsyncMock()
        w._agent_name = name
        w._mxid = f"@{name}:server"
        wrappers[name] = w
    return wrappers


@pytest.fixture
def session(collaborative_config, mock_appservice, mock_registry, mock_wrappers):
    return MatrixCollaborativeSession(
        session_id="sess-1",
        room_id="!room:server",
        question="What is the market trend?",
        config=collaborative_config,
        appservice=mock_appservice,
        registry=mock_registry,
        wrappers=mock_wrappers,
        server_name="server",
    )


class TestSessionLifecycle:
    async def test_run_completes_all_phases(self, session):
        """run() goes through INVESTIGATING → CROSS_POLLINATING → SYNTHESIZING → COMPLETED."""
        state = await session.run()
        assert state.phase == SessionPhase.COMPLETED
        assert state.started_at is not None
        assert state.completed_at is not None

    async def test_investigate_calls_all_non_summarizer_agents(self, session, mock_wrappers):
        """Investigation phase calls analyst and researcher but not summarizer."""
        await session.run()
        # Verify analyst and researcher were invoked, summarizer was not
        ...

    async def test_session_timeout_cancels(self, session, collaborative_config):
        """Session cancelled when session_timeout exceeded."""
        collaborative_config.session_timeout = 0.001  # instant timeout
        state = await session.run()
        assert state.phase == SessionPhase.FAILED


class TestCrossPollination:
    async def test_enriched_context_includes_prior_results(self, session):
        """Cross-pollination prompt includes results from investigation phase."""
        ...


class TestSynthesizer:
    async def test_summarizer_receives_structured_payload(self, session, mock_wrappers):
        """Summarizer called with {agent_name: result_text} payload."""
        ...

    async def test_no_summarizer_posts_raw_results(self, session, collaborative_config, mock_appservice):
        """Without summarizer_agent, raw results posted via send_as_bot."""
        collaborative_config.summarizer_agent = None
        state = await session.run()
        assert state.phase == SessionPhase.COMPLETED
        mock_appservice.send_as_bot.assert_called()


class TestAgentTimeout:
    async def test_timed_out_agent_skipped(self, session, mock_appservice):
        """Agent that exceeds agent_timeout is skipped with a notice."""
        ...


class TestCancel:
    async def test_cancel_transitions_to_failed(self, session):
        """cancel() sets phase to FAILED."""
        await session.cancel("User cancelled")
        assert session.phase == SessionPhase.FAILED
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1295, TASK-1296, TASK-1297 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm signatures still match
4. **Update status** in `sdd/tasks/index/matrix-collaborative-crew.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1298-collaborative-session-orchestrator.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

### Completion Note

Implemented `MatrixCollaborativeSession` in `packages/ai-parrot/src/parrot/integrations/matrix/crew/session.py`.

Key implementation decisions:
- `BotManager.get_bot()` is called with plain `await` (not wrapped in `asyncio.wait_for`) — only `agent.ask()` is wrapped with the per-agent timeout. This allows `BotManager.get_bot` to be mocked as an `AsyncMock` in tests without errors.
- Module-level `from parrot.manager import BotManager` (inside `try/except ImportError`) ensures `patch("parrot.integrations.matrix.crew.session.BotManager")` works in unit tests.
- `_announce()` respects `session_verbosity`: "silent" suppresses all messages, "minimal" passes only failure/error/cancel/complete keywords.
- All 20 tests pass. Ruff lint clean.

Updated `__init__.py` to export `MatrixCollaborativeSession` and created `test_matrix_collaborative_session.py` with 20 tests covering all acceptance criteria.
