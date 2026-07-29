---
type: Wiki Overview
title: 'Brainstorm: Matrix Collaborative Multi-Agent Crew'
id: doc:sdd-proposals-matrix-collaborative-crew-brainstorm-md
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

# Brainstorm: Matrix Collaborative Multi-Agent Crew

**Date**: 2026-05-26
**Author**: Jesus Lara + Claude
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The Matrix multi-agent crew infrastructure (FEAT-044) provides solid building blocks:
AppService virtual users, message routing, A2A custom events, registry, streaming, and
coordinator status board. However, the current architecture operates as a **hub-and-spoke**
model — a human message is routed to exactly one agent, which replies independently.

The missing capability is **collaborative investigation**: a human posts a question,
multiple agents investigate in parallel based on their specializations, exchange
information between themselves (visible as reply-to messages in the channel), optionally
delegate tool calls to peers with privileged access, and ultimately produce a synthesized
final answer.

**Who is affected:**
- End users who interact with AI crews via Matrix channels and need multi-perspective
  answers that combine different agents' expertise.
- Developers who deploy multi-agent crews and want agents to collaboratively refine
  answers rather than produce isolated, potentially contradictory responses.

**Why now:**
The infrastructure layer is ~85% complete. The remaining gap is the orchestration layer
that connects existing building blocks into a collaborative workflow. Without it, the
Matrix crew is functionally equivalent to N independent chatbots in the same room.

## Constraints & Requirements

- Must not break existing single-agent @mention routing (backward compatible).
- Must prevent infinite message loops between agents (loop safety).
- Agent-to-agent messages must be visible to the human in the Matrix room for
  transparency and auditability.
- Must work with the existing `MatrixAppService` (AS mode) — no separate client
  connections per agent.
- Collaborative sessions must have a bounded lifecycle (max rounds + timeout).
- Configuration via YAML (extending existing `MatrixCrewConfig`).
- Must support the existing `BotManager.get_bot()` resolution for agent instances.
- Agents are autonomous in choosing whom to @mention for delegation; the coordinator
  does not mediate individual inter-agent requests.
- The summarizer is a dedicated agent (configured in YAML), not the coordinator bot.

---

## Options Explored

### Option A: Matrix-Native Collaborative Session

Build a `MatrixCollaborativeSession` class that orchestrates phased rounds directly
via Matrix messages. The session is a first-class concept: it has a lifecycle, tracks
participating agents, manages round transitions, and coordinates the summarizer.

The key insight is that the **Matrix room IS the shared memory** — agents communicate
by posting messages that other agents (and humans) can see. The coordinator manages
phase transitions and context enrichment between rounds, but agents are autonomous
within each round.

**Architecture:**
- `MatrixCollaborativeSession`: Stateful session object managing one investigation.
- `MatrixCrewTransport` gains a `!investigate` command parser in `on_room_message()`.
- The self-filter is relaxed for @mention messages only: if an agent posts a message
  containing `@peer_agent`, the transport routes it to the mentioned peer instead of
  discarding it.
- The coordinator announces phase transitions as visible messages.
- Between rounds, the coordinator collects all agent responses and injects them as
  enriched context into the next round's agent prompts.
- The summarizer agent receives a structured payload (agent_name → result) plus the
  optional chat history for context.
- Reply-to threading via `m.in_reply_to` makes cross-pollination visually clear.

**Phases:**
1. **INVESTIGATE**: Broadcast question to all agents in parallel. Each posts results.
2. **CROSS-POLLINATE** (1-N configurable rounds): Agents see each other's results
   (injected by coordinator as enriched prompt). Can @mention peers for delegation.
3. **SYNTHESIZE**: Summarizer agent receives structured results + chat context.

This is a **new class** that does NOT wrap or extend `AgentCrew`. It uses Matrix
messages as the communication substrate rather than in-memory `FlowContext`.

✅ **Pros:**
- Clean separation: Matrix collaboration is its own concern, not bolted onto AgentCrew.
- The room timeline IS the audit log — full transparency.
- Agents can be on different homeservers (federation) in the future.
- Easy to reason about: each phase is a clear state transition.
- Natural fit with Matrix's event model (reply-to, threading, reactions).

❌ **Cons:**
- More new code: does not reuse AgentCrew's execution/synthesis machinery.
- Duplicates some concepts (phase management, result collection) that AgentCrew has.
- Testing requires mocking Matrix events, which is more complex than in-memory testing.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mautrix` | Matrix client/AS SDK | Already in use (v0.20+) |
| `pydantic` | Session config and state models | Already in use (v2) |
| `asyncio` | Concurrent agent execution, round management | stdlib |

🔗 **Existing Code to Reuse:**
- `parrot/integrations/matrix/crew/transport.py` — Extend `on_room_message()` routing.
- `parrot/integrations/matrix/crew/crew_wrapper.py` — Reuse `handle_message()` as base.
- `parrot/integrations/matrix/crew/registry.py` — Agent discovery and status tracking.
- `parrot/integrations/matrix/crew/coordinator.py` — Phase announcement messages.
- `parrot/integrations/matrix/crew/mention.py` — `parse_mention()` + `build_pill()`.
- `parrot/integrations/matrix/appservice.py` — `send_as_agent()`, `send_as_bot()`.
- `parrot/integrations/matrix/events.py` — `m.parrot.task/result` for tool delegation.

---

### Option B: AgentCrew Adapter with Matrix Message Hooks

Wrap `AgentCrew`'s existing `run_parallel` + `run_flow` execution behind a Matrix
adapter. The adapter translates AgentCrew's internal phase transitions into Matrix
messages. Cross-pollination is implemented by feeding agent results back through
AgentCrew's `FlowContext.shared_data`.

**Architecture:**
- `MatrixCrewAdapter`: Wraps an `AgentCrew` instance.
- Hooks into AgentCrew's lifecycle hooks (`on_complete`, `on_error` from FEAT-157).
- Each agent execution callback posts the result to the Matrix room.
- Cross-pollination rounds use `run_loop` with `_evaluate_loop_condition()`.
- Inter-agent @mentions are handled by the adapter intercepting messages and
  re-routing them through AgentCrew's internal tool mechanism (AgentTool).
- The summarizer uses `_synthesize_results()` from `SynthesisMixin`.

✅ **Pros:**
- Maximum code reuse: leverages AgentCrew's battle-tested execution engine.
- Result persistence (FEAT-147) comes for free.
- Synthesis machinery (`SynthesisMixin`) already works.
- Familiar patterns for anyone who knows AgentCrew.

❌ **Cons:**
- Impedance mismatch: AgentCrew operates in-memory, Matrix operates via events.
  The adapter must constantly translate between the two models.
- Reply-to threading is awkward: AgentCrew doesn't know about Matrix event IDs.
- Inter-agent @mention routing is bolted on — AgentCrew's tool delegation model
  (AgentTool) doesn't map cleanly to "post @mention in room and wait for reply."
- Cross-pollination via `run_loop` is sequential, not the parallel "all agents read
  each other's results" model the user described.
- Lifecycle coupling: AgentCrew's session management doesn't align with Matrix room
  state management.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mautrix` | Matrix messaging | Already in use |
| `pydantic` | Models | Already in use |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/crew/crew.py` — `AgentCrew` core execution.
- `parrot/bots/flows/core/storage/synthesis.py` — `SynthesisMixin`.
- `parrot/bots/flows/core/context.py` — `FlowContext`.
- `parrot/bots/flows/core/result.py` — `FlowResult`, `NodeResult`.
- `parrot/integrations/matrix/crew/transport.py` — Message routing.

---

### Option C: Event-Driven Pub/Sub over m.parrot.* Custom Events

Use the existing `MatrixA2ATransport` custom events (`m.parrot.task`, `m.parrot.result`,
`m.parrot.status`) as the primary communication substrate between agents. Visible Matrix
messages are posted as a side effect for human consumption, but the actual orchestration
happens via custom events that agents subscribe to.

**Architecture:**
- Extend `MatrixA2ATransport` to work in AS mode (currently requires `MatrixClientWrapper`).
- Each agent subscribes to `m.parrot.task` events targeting them.
- The coordinator publishes `m.parrot.task` events to trigger investigation.
- Agents publish `m.parrot.result` events when done, and post a visible summary message.
- Cross-pollination: agents subscribe to `m.parrot.result` events from all agents and
  can autonomously publish follow-up `m.parrot.task` events to peers.
- The summarizer subscribes to all `m.parrot.result` events and triggers synthesis when
  a quorum is reached.

✅ **Pros:**
- Cleanest separation of concerns: machine communication (custom events) vs.
  human communication (visible messages).
- Naturally async and event-driven — no central orchestrator polling.
- Could leverage Matrix federation for cross-homeserver agent communication.
- Custom events can carry structured payloads (JSON) richer than text messages.

❌ **Cons:**
- Requires bridging `MatrixA2ATransport` (client mode) to `MatrixAppService` (AS mode).
  This is a significant refactor: `MatrixA2ATransport.__init__()` takes a
  `MatrixClientWrapper`, but the crew uses AS intents — different API surface.
- Custom events are invisible to most Matrix clients — humans can't see the
  orchestration without the visible message side-channel.
- Harder to debug: the real communication is in custom events, visible messages are
  a lossy projection.
- Loop prevention in a fully event-driven system is harder than round-based gating.
- No existing code handles `m.parrot.*` events in the AppService event handler
  (`appservice.py:287-322` only handles `EventType.ROOM_MESSAGE`).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mautrix` | Matrix events | Already in use |
| `pydantic` | Event content models | Already in use |

🔗 **Existing Code to Reuse:**
- `parrot/integrations/matrix/a2a_transport.py` — `send_task()`, `send_result()`.
- `parrot/integrations/matrix/events.py` — Custom event types and content models.
- `parrot/integrations/matrix/appservice.py` — Needs extension for custom events.
- `parrot/integrations/matrix/crew/registry.py` — Agent discovery.

---

## Recommendation

**Option A** (Matrix-Native Collaborative Session) is recommended because:

1. **Alignment with user vision**: The user described a collaborative chat where agents
   exchange visible messages, reply to each other, and the human sees everything. This
   maps directly to a Matrix-native approach where the room timeline IS the collaboration
   log. Option B's in-memory execution with message side-effects would feel artificial.

2. **Clean architecture**: A dedicated `MatrixCollaborativeSession` class avoids the
   impedance mismatch of wrapping AgentCrew. Matrix rooms have their own state model
   (events, relations, threads) that doesn't map to `FlowContext`'s in-memory dict.

3. **Loop safety by design**: Round-based gating (the coordinator controls when each
   phase starts/ends) is inherently safe. The self-filter stays in place except for
   @mention routing — agents can only communicate when explicitly addressed.

4. **Extensibility**: Future features (agent reactions, voting via Matrix reactions,
   threaded sub-discussions) map naturally to Matrix primitives without adapter layers.

**Tradeoff accepted**: More new code vs. reusing AgentCrew. This is acceptable because
the collaboration model is fundamentally different — agents communicate via room messages,
not in-memory function calls. The synthesis logic from `SynthesisMixin` CAN still be
reused by the summarizer agent's system prompt, just not the orchestration machinery.

---

## Feature Description

### User-Facing Behavior

A human in a Matrix room with an AI-Parrot crew types:

```
!investigate What are the emerging trends in renewable energy investment for Q3 2026?
```

The room then shows:

```
[Coordinator Bot] 🔍 Starting collaborative investigation (3 agents, 1 cross-pollination round)

[Financial Analyst] I'll analyze the investment data for renewable energy sectors...
  → [result: detailed financial analysis with data points]

[Research Assistant] Researching recent policy changes and market reports...
  → [result: policy analysis and market trend summary]

[General Assistant] Gathering general context on renewable energy trends...
  → [result: broad overview with key statistics]

[Coordinator Bot] 🔄 Cross-pollination round 1/1 — agents are reviewing each other's findings

[Financial Analyst] (replying to Research Assistant) Interesting point about the EU taxonomy
  changes — let me recalculate the impact on green bond yields...
  → [updated analysis incorporating policy context]

[Research Assistant] @analyst Can you confirm the YoY growth rate for solar installations?
  I'm seeing conflicting numbers.

[Financial Analyst] (replying to Research Assistant) The YoY growth rate is 23.4% per
  BloombergNEF, the 18% figure is for capacity factor, not installations.

[Coordinator Bot] 📊 Synthesizing final answer...

[Summarizer Agent] Based on the collaborative analysis:
  **Key Finding**: Renewable energy investment is accelerating...
  [comprehensive synthesis with confidence-weighted conclusions]
```

Key behaviors:
- `@mention` routing for single-agent mode still works as before.
- `!investigate` triggers collaborative mode with all agents.
- Agent-to-agent messages appear as reply-to threads in the room.
- The coordinator announces phase transitions visibly.
- The summarizer produces the final consolidated answer.

### Internal Behavior

**Session lifecycle:**

1. `MatrixCrewTransport.on_room_message()` detects `!investigate` prefix.
2. Creates `MatrixCollaborativeSession(question, room_id, agents, config)`.
3. Session transitions through phases:

```
CREATED → INVESTIGATING → CROSS_POLLINATING → SYNTHESIZING → COMPLETED
                                    ↑              |
                                    └──────────────┘  (if round < max_rounds)
```

**Phase: INVESTIGATING**
- Coordinator posts phase announcement.
- For each agent: inject question + agent's system prompt into `agent.ask()`.
- Agents execute in parallel via `asyncio.gather()`.
- Each agent's response is posted as a visible message in the room using
  `appservice.send_as_agent()`.
- Responses are collected in `session.agent_results: Dict[str, AgentRoundResult]`.
- Event IDs of response messages are tracked for reply-to threading.

**Phase: CROSS_POLLINATING** (repeated `max_rounds` times)
- Coordinator posts round announcement.
- For each agent: inject enriched context (all previous agent results as structured
  summary) + the original question + instruction to review peers' findings.
- Agents can @mention peers in their responses — the transport routes these through
  the session's inter-agent handler instead of the normal single-agent path.
- Agents can request tool delegation from peers using natural language @mentions
  (e.g., "@analyst run your financial_data tool on AAPL"). The hybrid approach:
  1. A visible message is posted: "Asking @analyst to analyze AAPL..."
  2. The actual delegation uses `m.parrot.task` custom event.
  3. The result is posted as a visible reply-to message.
- All new messages are collected and added to the session context.

**Phase: SYNTHESIZING**
- Coordinator posts synthesis announcement.
- Build structured payload: `{agent_name: final_result_text}` for each agent.
- Optionally append chat history (configurable).
- Invoke the summarizer agent with the payload as its prompt.
- Post the summarizer's response as the final room message.

**Phase: COMPLETED**
- Session is archived (stored in coordinator or discarded).
- Transport returns to normal single-agent routing.

**Inter-agent @mention routing within a session:**

When the session is active, `on_room_message()` checks:
1. Is sender a virtual agent MXID? (normally filtered)
2. Is there an active session?
3. Does the message contain an @mention of another agent?

If all three: route to the mentioned agent's wrapper with enriched context
(the session's accumulated results + the mentioning agent's message).
The response is posted as a reply-to the mentioning message.

**Reply-to support:**

New helper in `mention.py` or a new `threading.py`:
```
send_reply_as_agent(agent_name, room_id, text, reply_to_event_id)
```
Uses `m.relates_to` with `m.in_reply_to` relation (MSC2781), which is the
standard Matrix threading mechanism supported by all major clients.

### Edge Cases & Error Handling

- **Agent timeout**: If an agent doesn't respond within `agent_timeout` seconds
  during any phase, the session marks it as timed out and proceeds without it.
  The coordinator posts a notice: "Agent X timed out."
- **All agents fail**: If no agent produces a result in the INVESTIGATING phase,
  the coordinator posts an error and the session moves to COMPLETED.
- **Summarizer fails**: If the summarizer agent fails, the coordinator posts the
  raw agent results as a fallback (formatted list).
- **Concurrent sessions**: Only one collaborative session per room at a time.
  If `!investigate` is sent while a session is active, the coordinator replies
  with "Investigation already in progress."
- **Human messages during session**: Humans can still @mention individual agents
  during a session. These are routed normally (single-agent mode), not through
  the session.
- **Agent references non-existent peer**: If an agent @mentions a peer that isn't
  in the crew, the message is ignored (no routing match) and the agent's message
  is posted as-is.
- **Empty cross-pollination**: If no agent produces new information during a
  cross-pollination round, the coordinator skips remaining rounds and moves to
  synthesis.

---

## Capabilities

### New Capabilities
- `matrix-collaborative-session`: Phased multi-agent investigation triggered by
  `!investigate` command in Matrix rooms.
- `matrix-reply-to-threading`: Support for `m.in_reply_to` relations in agent
  messages, enabling visible reply chains.
- `matrix-inter-agent-routing`: Selective bypass of the agent self-filter for
  @mention messages during active collaborative sessions.
- `matrix-tool-delegation-hybrid`: Visible message + `m.parrot.task` custom event
  for peer-to-peer tool delegation within a session.
- `matrix-summarizer-agent`: Configurable dedicated agent that receives structured
  results and produces a final synthesis.

### Modified Capabilities
- `matrix-crew-transport`: Extended `on_room_message()` with `!investigate` parser
  and session-aware inter-agent routing.
- `matrix-crew-config`: New YAML fields for collaborative session configuration.
- `matrix-coordinator`: Phase announcement messages and session lifecycle tracking.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `matrix/crew/transport.py` | extends | New `!investigate` command, session management, inter-agent routing |
| `matrix/crew/config.py` | extends | New `collaborative:` config section |
| `matrix/crew/coordinator.py` | extends | Phase announcements, session lifecycle |
| `matrix/crew/crew_wrapper.py` | extends | Session-aware handle_message with enriched context |
| `matrix/crew/mention.py` | extends | `send_reply_as_agent()` with `m.in_reply_to` |
| `matrix/appservice.py` | extends | Reply-to message sending, custom event handling in AS mode |
| `matrix/events.py` | depends on | Reuse `m.parrot.task/result` for tool delegation |
| `matrix/crew/registry.py` | depends on | Agent discovery for autonomous @mention routing |
| `examples/matrix_crew/` | extends | Updated example showing collaborative mode |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/integrations/matrix/crew/transport.py:214
async def on_room_message(
    self,
    room_id: str,
    sender: str,
    body: str,
    event_id,
) -> None:
    # Self-filter at line 237:
    if sender in self._agent_mxids:
        return
    # Dedicated room routing at line 243
    # @mention routing at line 254
    # Default agent routing at line 271

# From parrot/integrations/matrix/crew/crew_wrapper.py:68
async def handle_message(
    self,
    room_id: str,
    sender: str,
    body: str,
    event_id: str,
) -> None:
    # Agent resolution at line 111:
    agent = await BotManager.get_bot(self._config.chatbot_id)
    # Agent call at line 118:
    response: str = await agent.ask(body)

# From parrot/integrations/matrix/appservice.py:239
async def send_as_agent(
    self,
    agent_name: str,
    room_id: str,
    message: str,
) -> str:  # returns event_id

# From parrot/integrations/matrix/appservice.py:263
async def send_as_bot(self, room_id: str, message: str) -> str

# From parrot/integrations/matrix/a2a_transport.py:111
async def send_task(
    self,
    room_id: str,
    content: str,
    *,
    task_id: Optional[str] = None,
    context_id: Optional[str] = None,
    target_agent: Optional[str] = None,
    skill_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:  # returns task_id

# From parrot/integrations/matrix/a2a_transport.py:249
async def wait_for_result(
    self,
    room_id: str,
    task_id: str,
    *,
    timeout: float = 60.0,
) -> Optional[ResultEventContent]:

# From parrot/integrations/matrix/crew/coordinator.py:50
async def start(self) -> None:
async def on_status_change(self, agent_name: str) -> None:  # line 108
async def refresh_status_board(self) -> None:  # line 120

# From parrot/integrations/matrix/crew/registry.py:89
async def register(self, card: MatrixAgentCard) -> None:
async def get(self, agent_name: str) -> Optional[MatrixAgentCard]:  # line 162
async def all_agents(self) -> List[MatrixAgentCard]:  # line 191
async def get_by_mxid(self, mxid: str) -> Optional[MatrixAgentCard]:  # line 174

# From parrot/integrations/matrix/crew/mention.py:19
def parse_mention(body: str, server_name: str) -> Optional[str]:
def build_pill(mxid: str, display_name: str) -> str:  # line 68

# From parrot/integrations/matrix/crew/config.py:91
class MatrixCrewConfig(BaseModel):
    homeserver_url: str
    server_name: str
    as_token: str
    hs_token: str
    bot_mxid: str
    general_room_id: str
    agents: Dict[str, MatrixCrewAgentEntry] = {}
    appservice_port: int = 8449
    pinned_registry: bool = True
    typing_indicator: bool = True
    streaming: bool = True
    unaddressed_agent: Optional[str] = None
    max_message_length: int = 4096

# From parrot/integrations/matrix/crew/config.py:57
class MatrixCrewAgentEntry(BaseModel):
    chatbot_id: str
    display_name: str
    mxid_localpart: str
    avatar_url: Optional[str] = None
    dedicated_room_id: Optional[str] = None
    skills: List[str] = []
    tags: List[str] = []
    file_types: List[str] = []

# From parrot/bots/abstract.py:3660
async def ask(
    self,
    question: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_conversation_history: bool = True,
    use_tools: bool = True,
    **kwargs
) -> AIMessage:

# From parrot/manager/manager.py:605
async def get_bot(
    self,
    name: str,
    new: bool = False,
    session_id: str = "",
    request: Optional[web.Request] = None,
    **kwargs
) -> AbstractBot:

# From parrot/integrations/matrix/client.py:120
async def send_text(
    self,
    room_id: str,
    text: str,
    *,
    html: Optional[str] = None,

…(truncated)…
