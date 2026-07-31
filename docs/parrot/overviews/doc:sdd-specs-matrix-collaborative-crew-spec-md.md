---
type: Wiki Overview
title: 'Feature Specification: Matrix Collaborative Multi-Agent Crew'
id: doc:sdd-specs-matrix-collaborative-crew-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The Matrix multi-agent crew infrastructure (FEAT-044) provides solid building
  blocks:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.integrations.matrix
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew
  rel: mentions
- concept: mod:parrot.integrations.matrix.events
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Matrix Collaborative Multi-Agent Crew

**Feature ID**: FEAT-195
**Date**: 2026-05-26
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Brainstorm**: `sdd/proposals/matrix-collaborative-crew.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The Matrix multi-agent crew infrastructure (FEAT-044) provides solid building blocks:
AppService virtual users, message routing, A2A custom events, registry, streaming, and
coordinator status board. However, the current architecture operates as a **hub-and-spoke**
model — a human message is routed to exactly one agent, which replies independently.

The missing capability is **collaborative investigation**: a human posts a question,
multiple agents investigate in parallel based on their specializations, exchange
information between themselves (visible as reply-to messages in the channel), optionally
delegate tool calls to peers with privileged access, and ultimately produce a synthesized
final answer.

Without this, the Matrix crew is functionally equivalent to N independent chatbots in the
same room.

### Goals

- Enable phased collaborative investigation triggered by `!investigate` in a Matrix room.
- All registered agents investigate in parallel, post results visibly.
- Agents exchange information via visible @mention reply-to threads (cross-pollination).
- Agents can autonomously delegate tool calls to peers who have privileged access.
- A dedicated summarizer agent produces a final synthesis from all agent results.
- Configurable cross-pollination rounds (default: 1) with bounded lifecycle.
- Full phase announcements visible to human users for transparency.
- Backward compatible — existing single-agent @mention routing continues to work.

### Non-Goals (explicitly out of scope)

- Modifying or extending `AgentCrew` with Matrix awareness. This is a Matrix-native
  orchestrator, not an AgentCrew adapter (rejected in brainstorm — see Option B).
- Event-driven pub/sub orchestration via `m.parrot.*` custom events as the primary
  communication path (rejected in brainstorm — see Option C).
- Multi-room collaborative sessions (only one room per session).
- Concurrent collaborative sessions in the same room.
- Voice/audio agent support.

---

## 2. Architectural Design

### Overview

Build a `MatrixCollaborativeSession` class that orchestrates phased rounds directly
via Matrix messages. The session is a first-class concept: it has a lifecycle, tracks
participating agents, manages round transitions, and coordinates the summarizer.

The key insight is that the **Matrix room IS the shared memory** — agents communicate
by posting messages that other agents (and humans) can see. The coordinator manages
phase transitions and context enrichment between rounds, but agents are autonomous
within each round.

**Session phases:**
1. **INVESTIGATE**: Broadcast question to all agents in parallel. Each posts results.
2. **CROSS-POLLINATE** (1-N configurable rounds, default 1): Agents see each other's
   results (injected by coordinator as enriched prompt). Can @mention peers for
   delegation.
3. **SYNTHESIZE**: Dedicated summarizer agent receives structured results + optional
   chat context and produces the final answer.

**Loop safety**: Agents only respond to explicit @mentions (from humans, coordinator,
or other agents). The existing self-filter stays in place for non-mention messages.
The coordinator enriches context between rounds by collecting all agent responses and
injecting them as structured summaries into the next round's prompts.

**Agent autonomy for delegation**: Agents know the registry (skills list) and can
@mention any peer directly. The coordinator does not mediate individual inter-agent
routing.

**Tool delegation (hybrid)**: When an agent delegates to a peer:
1. A visible message is posted: "Asking @peer to analyze..."
2. The actual tool call uses `m.parrot.task` custom event.
3. The result is posted as a visible reply-to message.

### Component Diagram

```
Human posts "!investigate <question>"
       │
       ▼
MatrixCrewTransport.on_room_message()
       │ detects "!investigate" prefix
       ▼
MatrixCollaborativeSession(question, room_id, config)
       │
       ├── Phase: INVESTIGATING ─────────────────────────────┐
       │   ├── Coordinator posts: "Starting investigation…"  │
       │   ├── agent_1.ask(question) ──→ post result         │ parallel
       │   ├── agent_2.ask(question) ──→ post result         │ via
       │   └── agent_N.ask(question) ──→ post result         │ asyncio.gather
       │                                                     │
       ├── Phase: CROSS_POLLINATING (round 1..max_rounds) ───┤
       │   ├── Coordinator posts: "Cross-pollination 1/N…"   │
       │   ├── Inject all results as enriched context         │
       │   ├── agent_1.ask(enriched) ──→ post reply-to       │
       │   ├── agent_2.ask(enriched) ──→ post reply-to       │
       │   ├── Inter-agent @mentions ──→ routed via session   │
       │   └── Tool delegation: visible msg + m.parrot.task  │
       │                                                     │
       ├── Phase: SYNTHESIZING ──────────────────────────────┤
       │   ├── Coordinator posts: "Synthesizing…"            │
       │   ├── Build structured payload per agent            │
       │   └── summarizer.ask(payload + context) ──→ post    │
       │                                                     │
       └── Phase: COMPLETED ─────────────────────────────────┘
            └── Session archived, transport returns to normal
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MatrixCrewTransport` | extends | New `!investigate` command parser, session management, inter-agent routing |
| `MatrixCrewConfig` | extends | New `collaborative:` config section with session parameters |
| `MatrixCoordinator` | extends | Phase announcement messages |
| `MatrixCrewAgentWrapper` | extends | Session-aware `handle_message()` with enriched context |
| `MatrixAppService` | extends | Reply-to message sending via `m.in_reply_to` |
| `parse_mention()` / `build_pill()` | uses | Agent-autonomous @mention routing |
| `MatrixCrewRegistry` | uses | Agent discovery for skills-based delegation |
| `ParrotEventType.TASK/RESULT` | uses | Hybrid tool delegation custom events |
| `BotManager.get_bot()` | uses | Agent resolution (unchanged) |

### Data Models

```python
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class SessionPhase(str, Enum):
    CREATED = "created"
    INVESTIGATING = "investigating"
    CROSS_POLLINATING = "cross_pollinating"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"

class AgentRoundResult(BaseModel):
    """Result from one agent in one round."""
    agent_name: str
    display_name: str
    mxid: str
    round_number: int
    result_text: str
    event_id: str  # Matrix event ID for reply-to threading
    timestamp: datetime

class CollaborativeSessionState(BaseModel):
    """Full state of a collaborative session."""
    session_id: str
    room_id: str
    question: str
    phase: SessionPhase = SessionPhase.CREATED
    current_round: int = 0
    max_rounds: int = 1
    agent_results: Dict[str, List[AgentRoundResult]] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    final_synthesis: Optional[str] = None

class CollaborativeConfig(BaseModel):
    """Config section for collaborative sessions within MatrixCrewConfig."""
    command_prefix: str = Field(default="!investigate", description="Trigger command")
    max_rounds: int = Field(default=1, ge=1, le=10, description="Cross-pollination rounds")
    agent_timeout: float = Field(default=120.0, description="Per-agent timeout in seconds")
    session_timeout: float = Field(default=600.0, description="Max session duration in seconds")
    summarizer_agent: Optional[str] = Field(default=None, description="Agent name for synthesis")
    session_verbosity: str = Field(default="full", description="'full' or 'minimal'")
    include_chat_context: bool = Field(default=True, description="Pass chat history to summarizer")
```

### New Public Interfaces

```python
class MatrixCollaborativeSession:
    """Stateful session managing one collaborative investigation."""

    def __init__(
        self,
        question: str,
        room_id: str,
        config: CollaborativeConfig,
        appservice: MatrixAppService,
        registry: MatrixCrewRegistry,
        wrappers: Dict[str, MatrixCrewAgentWrapper],
        server_name: str,
    ) -> None: ...

    @property
    def phase(self) -> SessionPhase: ...

    @property
    def is_active(self) -> bool: ...

    async def run(self) -> CollaborativeSessionState:
        """Execute the full session lifecycle (investigate → cross-pollinate → synthesize)."""

    async def handle_inter_agent_message(
        self,
        sender_mxid: str,
        body: str,
        event_id: str,
    ) -> None:
        """Route an @mention from one agent to another during an active session."""

    async def cancel(self, reason: str = "Cancelled by user") -> None:
        """Cancel the session and post a notice."""
```

---

## 3. Module Breakdown

### Module 1: Reply-to Threading Support
- **Path**: `parrot/integrations/matrix/appservice.py` (extend) + `parrot/integrations/matrix/crew/mention.py` (extend)
- **Responsibility**: Add `m.in_reply_to` relation support for sending messages as
  replies to a specific event. New method `send_reply_as_agent()` on AppService.
  New helper `send_reply()` in mention utilities.
- **Depends on**: None (standalone Matrix protocol feature)

### Module 2: Collaborative Config Extension
- **Path**: `parrot/integrations/matrix/crew/config.py` (extend)
- **Responsibility**: Add `CollaborativeConfig` model and integrate it as a
  `collaborative: Optional[CollaborativeConfig]` field on `MatrixCrewConfig`.
  YAML config backward-compatible (field is optional).
- **Depends on**: None

### Module 3: Session State Models
- **Path**: `parrot/integrations/matrix/crew/session_models.py` (new)
- **Responsibility**: Pydantic models for `SessionPhase`, `AgentRoundResult`,
  `CollaborativeSessionState`. Used by the session orchestrator and transport.
- **Depends on**: None

### Module 4: Collaborative Session Orchestrator
- **Path**: `parrot/integrations/matrix/crew/session.py` (new)
- **Responsibility**: `MatrixCollaborativeSession` class implementing the full
  session lifecycle: investigate → cross-pollinate → synthesize. Manages phase
  transitions, parallel agent execution, context enrichment between rounds,
  inter-agent @mention routing, and summarizer invocation.
- **Depends on**: Module 1 (reply-to), Module 2 (config), Module 3 (models)

### Module 5: Transport Integration
- **Path**: `parrot/integrations/matrix/crew/transport.py` (extend)
- **Responsibility**: Modify `on_room_message()` to detect `!investigate` prefix,
  create and manage `MatrixCollaborativeSession`, and route inter-agent @mentions
  through the session when one is active (selective self-filter bypass).
- **Depends on**: Module 4 (session)

### Module 6: Hybrid Tool Delegation
- **Path**: `parrot/integrations/matrix/crew/delegation.py` (new)
- **Responsibility**: When an agent requests tool execution from a peer via @mention,
  post a visible "Asking @peer to..." message, send `m.parrot.task` custom event
  via the AppService, wait for `m.parrot.result`, and post the result as a visible
  reply-to. Bridges A2A transport concepts into AS mode.
- **Depends on**: Module 1 (reply-to), Module 4 (session context)

### Module 7: Example and Documentation
- **Path**: `examples/matrix_crew/` (extend)
- **Responsibility**: Update `matrix_crew_example.py` and YAML config to demonstrate
  collaborative mode with `!investigate`. Add a second example config showing
  collaborative settings.
- **Depends on**: Module 5 (transport integration)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_collaborative_config_defaults` | Module 2 | CollaborativeConfig loads with correct defaults |
| `test_collaborative_config_from_yaml` | Module 2 | Full YAML round-trip with env var substitution |
| `test_collaborative_config_backward_compat` | Module 2 | MatrixCrewConfig loads without `collaborative:` section |
| `test_session_phase_transitions` | Module 3 | SessionPhase enum values and state model validation |
| `test_agent_round_result_serialization` | Module 3 | AgentRoundResult Pydantic serialization |
| `test_reply_to_message_content` | Module 1 | `m.in_reply_to` relation is correctly set in event content |
| `test_send_reply_as_agent` | Module 1 | AppService sends reply with correct virtual MXID |
| `test_session_investigate_phase` | Module 4 | All agents called in parallel, results collected |
| `test_session_cross_pollinate_phase` | Module 4 | Enriched context injected, results from round N fed to round N+1 |
| `test_session_synthesize_phase` | Module 4 | Summarizer receives structured payload |
| `test_session_agent_timeout` | Module 4 | Timed-out agent is skipped, session continues |
| `test_session_all_agents_fail` | Module 4 | Session moves to FAILED, coordinator posts error |
| `test_session_summarizer_fallback` | Module 4 | If summarizer fails, raw results posted |
| `test_transport_investigate_command` | Module 5 | `!investigate` triggers session creation |
| `test_transport_concurrent_session_rejected` | Module 5 | Second `!investigate` during active session is rejected |
| `test_transport_mention_routing_during_session` | Module 5 | Agent @mention routes through session, not normal path |
| `test_transport_mention_routing_no_session` | Module 5 | Without session, @mention routes normally |
| `test_delegation_hybrid_visible_message` | Module 6 | Visible "Asking @peer..." message posted |
| `test_delegation_custom_event_sent` | Module 6 | `m.parrot.task` event sent after visible message |

### Integration Tests
| Test | Description |
|---|---|
| `test_full_collaborative_session` | End-to-end: `!investigate` → investigate → cross-pollinate → synthesize → final result |
| `test_collaborative_with_inter_agent_mention` | Agent A mentions Agent B during cross-pollination, B responds |
| `test_collaborative_backward_compat` | `@agent question` still works in single-agent mode alongside collaborative config |

### Test Data / Fixtures

```python
@pytest.fixture
def collaborative_config():
    return CollaborativeConfig(
        command_prefix="!investigate",
        max_rounds=1,
        agent_timeout=30.0,
        session_timeout=120.0,
        summarizer_agent="summarizer",
    )

@pytest.fixture
def mock_appservice():
    """Mock MatrixAppService with send_as_agent, send_as_bot, send_reply_as_agent."""
    ...

@pytest.fixture
def crew_config_with_collaborative(collaborative_config):
    """MatrixCrewConfig with collaborative section populated."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `!investigate <question>` in a Matrix room triggers a collaborative session.
- [ ] All registered agents investigate the question in parallel.
- [ ] Each agent's response is posted as a visible message in the room.
- [ ] Coordinator announces phase transitions (e.g., "Starting investigation 1/3...").
- [ ] Cross-pollination round(s) inject enriched context from prior results.
- [ ] Agents can @mention peers during cross-pollination; peer responds with reply-to.
- [ ] `m.in_reply_to` threading works correctly for agent reply chains.
- [ ] Dedicated summarizer agent receives structured `{agent_name: result}` payload.
- [ ] Summarizer's response is posted as the final room message.
- [ ] Only one collaborative session per room at a time (concurrent rejected).
- [ ] Existing `@agent question` single-agent routing is unaffected.
- [ ] Agent timeout is honored — timed-out agents are skipped with a notice.
- [ ] Session timeout is honored — entire session cancelled if exceeded.
- [ ] `collaborative:` YAML config section is optional (backward compatible).
- [ ] All unit tests pass (`pytest tests/ -k matrix_collaborative -v`).
- [ ] No infinite message loops between agents.
- [ ] Hybrid tool delegation posts visible message + `m.parrot.task` event.

---

## 6. Codebase Contract

### Verified Imports

```python
# These imports have been confirmed to work (2026-05-26):
from parrot.integrations.matrix.crew import MatrixCrewTransport      # crew/__init__.py
from parrot.integrations.matrix.crew import MatrixCrewConfig          # crew/__init__.py
from parrot.integrations.matrix.crew import MatrixCrewRegistry        # crew/__init__.py
from parrot.integrations.matrix.crew import MatrixCoordinator         # crew/__init__.py
from parrot.integrations.matrix.crew import MatrixCrewAgentWrapper    # crew/__init__.py
from parrot.integrations.matrix.crew import parse_mention, build_pill # crew/__init__.py
from parrot.integrations.matrix import MatrixAppService               # matrix/__init__.py
from parrot.integrations.matrix import MatrixA2ATransport             # matrix/__init__.py
from parrot.integrations.matrix import MatrixClientWrapper            # matrix/__init__.py
from parrot.integrations.matrix.events import ParrotEventType         # events.py
from parrot.integrations.matrix.events import TaskEventContent        # events.py
from parrot.integrations.matrix.events import ResultEventContent      # events.py
```

### Existing Class Signatures

```python
# parrot/integrations/matrix/crew/transport.py
class MatrixCrewTransport:
    _agent_mxids: set[str]                              # line 43
    _wrappers: Dict[str, MatrixCrewAgentWrapper]        # line 41
    _room_to_agent: Dict[str, str]                      # line 42
    _config: MatrixCrewConfig                           # line 37
    _appservice: Optional[object]                       # line 38
    _coordinator: Optional[MatrixCoordinator]           # line 39
    _registry: MatrixCrewRegistry                       # line 40

    async def on_room_message(                          # line 214
        self, room_id: str, sender: str, body: str, event_id
    ) -> None:
        if sender in self._agent_mxids:                 # line 237 — SELF-FILTER
            return

    async def start(self) -> None:                      # line 67
    async def stop(self) -> None:                       # line 194

# parrot/integrations/matrix/crew/crew_wrapper.py
class MatrixCrewAgentWrapper:
    _agent_name: str                                    # line 53
    _config: MatrixCrewAgentEntry                       # line 54
    _appservice: MatrixAppService                       # line 55
    _registry: MatrixCrewRegistry                       # line 56
    _coordinator: MatrixCoordinator                     # line 57
    _mxid: str                                          # line 61

    async def handle_message(                           # line 68
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:
        agent = await BotManager.get_bot(self._config.chatbot_id)  # line 111
        response: str = await agent.ask(body)                       # line 118

# parrot/integrations/matrix/appservice.py
class MatrixAppService:
    async def send_as_agent(                            # line 239
        self, agent_name: str, room_id: str, message: str
    ) -> str:  # returns event_id

    async def send_as_bot(                              # line 263
        self, room_id: str, message: str
    ) -> str:  # returns event_id

    async def _handle_event(self, event: Event) -> None:  # line 287
        if event.type != EventType.ROOM_MESSAGE:           # line 291
            return

    def _get_intent(self, mxid: str) -> IntentAPI:      # line 343

# parrot/integrations/matrix/a2a_transport.py
class MatrixA2ATransport:
    async def send_task(                                # line 111
        self, room_id: str, content: str, *,
        task_id=None, context_id=None,
        target_agent=None, skill_id=None, metadata=None,
    ) -> str:  # returns task_id

    async def send_result(                              # line 162
        self, room_id: str, task_id: str, content: str, *,
        context_id=None, artifacts=None, success=True,
        error=None, metadata=None,
    ) -> str:  # returns event_id

    async def wait_for_result(                          # line 249
        self, room_id: str, task_id: str, *, timeout=60.0
    ) -> Optional[ResultEventContent]:

# parrot/integrations/matrix/crew/coordinator.py
class MatrixCoordinator:
    async def start(self) -> None:                      # line 50
    async def stop(self) -> None:                       # line 72
    async def on_status_change(self, agent_name: str):  # line 108
    async def refresh_status_board(self) -> None:       # line 120

# parrot/integrations/matrix/crew/registry.py
class MatrixAgentCard(BaseModel):
    agent_name: str
    display_name: str
    mxid: str                                           # line 30
    status: str = "offline"                             # line 31
    skills: List[str] = []                              # line 33

class MatrixCrewRegistry:
    async def register(self, card: MatrixAgentCard):    # line 89
    async def get(self, name: str) -> Optional[MatrixAgentCard]:  # line 162
    async def all_agents(self) -> List[MatrixAgentCard]:          # line 191
    async def get_by_mxid(self, mxid: str) -> Optional[MatrixAgentCard]:  # line 174

# parrot/integrations/matrix/crew/mention.py
def parse_mention(body: str, server_name: str) -> Optional[str]:  # line 19
def build_pill(mxid: str, display_name: str) -> str:              # line 68

# parrot/integrations/matrix/crew/config.py
class MatrixCrewAgentEntry(BaseModel):                  # line 57
    chatbot_id: str
    display_name: str
    mxid_localpart: str
    skills: List[str] = []

class MatrixCrewConfig(BaseModel):                      # line 91
    homeserver_url: str
    server_name: str
    as_token: str
    hs_token: str
    bot_mxid: str
    general_room_id: str
    agents: Dict[str, MatrixCrewAgentEntry] = {}
    appservice_port: int = 8449
    unaddressed_agent: Optional[str] = None
    max_message_length: int = 4096
    # from_yaml classmethod at line 140

# parrot/integrations/matrix/events.py
class ParrotEventType:                                  # line 21
    AGENT_CARD = "m.parrot.agent_card"
    TASK = "m.parrot.task"
    RESULT = "m.parrot.result"
    STATUS = "m.parrot.status"

# parrot/bots/abstract.py
class AbstractBot:
    async def ask(                                      # line 3660
        self, question: str, session_id=None, user_id=None,
        use_conversation_history=True, use_tools=True, **kwargs
    ) -> AIMessage:

# parrot/manager/manager.py
class BotManager:
    async def get_bot(                                  # line 605
        self, name: str, new=False, session_id="",
        request=None, **kwargs
    ) -> AbstractBot:
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MatrixCollaborativeSession` | `MatrixCrewAgentWrapper.handle_message()` | method call with enriched context | `crew_wrapper.py:68` |
| `MatrixCollaborativeSession` | `MatrixAppService.send_as_agent()` | posting agent responses | `appservice.py:239` |
| `MatrixCollaborativeSession` | `MatrixAppService.send_as_bot()` | coordinator announcements | `appservice.py:263` |
| `MatrixCollaborativeSession` | `MatrixCrewRegistry.all_agents()` | discovering participants | `registry.py:191` |
| `MatrixCollaborativeSession` | `parse_mention()` | detecting inter-agent @mentions | `mention.py:19` |

…(truncated)…
