---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Matrix Agents Swarm

**Feature ID**: FEAT-463
**Date**: 2026-08-26
**Author**: Jesus Lara / AI-Parrot Team
**Status**: approved
**Target version**: 0.28.0 (next minor)
**Brainstorm**: `sdd/proposals/matrix-agents-swarm.brainstorm.md`
**Builds on**: FEAT-044 (`integrations-matrix-multi`), FEAT-195 (`matrix-collaborative-crew`)

---

## 1. Motivation & Business Requirements

> Turn the Matrix crew (N agents on one homeserver) into a real **agents swarm**: declared
> public/private channels, private agent-to-agent tunnels carrying structured payloads, and
> collaborative answers to un-mentioned human questions — reachable from Slack, Signal and
> Discord through bridges and testable with a one-command dev stack.

### Problem Statement

`parrot.integrations.matrix` already ships FEAT-044 (AppService virtual users, shared +
per-agent rooms, `@mention` routing, coordinator status board, `m.parrot.*` A2A events)
and FEAT-195 (`!investigate` phased sessions, reply-to threading, `HybridDelegator`).
What is still missing:

1. **Channels as first-class objects.** Rooms are pre-existing ids in YAML; there is no
   operator-declared *public/private channel of agents* with membership and an answer policy.
2. **Agent ↔ agent conversations.** `MatrixA2ATransport` / `HybridDelegator` can *send*
   `m.parrot.task`, but nothing on the receiving side runs an agent and emits
   `m.parrot.result` (verified: no producer exists, `set_custom_event_callback` is never
   wired). There is no discoverable **private tunnel** between two agents and no LLM tool
   to ask a peer.
3. **Swarm answers.** Un-mentioned human text is ignored unless it starts with
   `!investigate`; `_active_sessions` is keyed by `room_id`, so one session per room.
4. **Humans from other networks.** Nobody can reach the swarm from Slack/Signal/Discord —
   `docker-compose.matrix.yml` is a bare Synapse with no bridges and no client.
5. **No room-creation API.** Neither `MatrixClientWrapper` nor `MatrixAppService` can create
   a room; both only invite/join into pre-existing ids.
6. **No documented client story** for developers testing the crew.

### Goals

- Declarative **channels** (`public` | `private`) with member agents and an
  `answer_policy` of `mention | swarm | silent`, materialised at startup (room, alias, join
  rule, `m.parrot.channel` state).
- **Tunnels**: lazily created private 2-agent rooms carrying `m.parrot.task` /
  `m.parrot.result` / `m.parrot.feedback` events with Pydantic payloads; registry with
  `ttl_minutes: 120` default (idle → both agents leave + tombstone; `0` = keep forever).
- **`AgentSwarmToolkit`** (`AbstractToolkit`): `ask_agent`, `send_feedback`, `list_agents`,
  `list_channels`, `post_to_channel`. `ask_agent` returns a fixed **`AgentAnswer`** envelope
  `{answer, confidence, sources, metadata}`; if the caller passes `expected_schema`,
  `answer` is validated against it.
- **Inbound task handler**: an agent receiving `m.parrot.task` runs its bot and replies with
  `m.parrot.result` (the missing producer).
- **Swarm sessions**: plain human text in a `swarm` channel starts a
  `MatrixCollaborativeSession`; sessions become **concurrent per room** (keyed by session id /
  trigger event), bounded by `max_concurrent_sessions` + `cooldown_seconds`; cross-pollination
  uses tunnels, with a one-line echo in the channel (`echo_summary_to_channel: true` default).
- **Bridged humans** (Slack/Signal/Discord puppets) are treated exactly like native humans.
- Optional **Matrix Space** grouping (`space.enabled: false` default): Space root +
  `m.space.child` links for channels, tunnels as private children.
- **Dev stack**: `docker-compose.matrix.yml` with Synapse + Postgres + Element Web and a
  `bridges` profile (mautrix-signal, mautrix-slack, mautrix-discord), a bootstrap script, and
  `CLIENTS.md` / `BRIDGES.md` documentation.
- Backward compatibility: existing `@mention`, `unaddressed_agent`, dedicated rooms and
  `!investigate` keep working with unchanged YAML.

### Non-Goals (explicitly out of scope)

- `router` answer policy (coordinator LLM chooses responders) — deferred to a follow-up.
- E-mail bridging (Postmoogle) — rejected; e-mail is sent by agents via `async-notify`
  (`parrot.notifications.NotificationMixin`), not via Matrix.
- Instagram (mautrix-meta) and XMPP (mautrix-jabber / slidge) bridges in the compose file —
  documented in `BRIDGES.md` only (unofficial API / immature upstream).
- E2EE for tunnels (rejected in brainstorm; `python-olm` stays unused), federation across
  homeservers, production TLS/workers compose, Synapse-alternative support (Tuwunel is
  documented as an alternative only).
- Threads-only design (`m.thread`) and `AgentsFlow`-orchestrated swarm — rejected in brainstorm
  (Options B and C).
- Persisting session/tunnel state outside Matrix (Matrix room history *is* the audit log).

---

## 2. Architectural Design

### Overview

Option A from the brainstorm, with Option D (Spaces) folded in as optional.

Three new modules under `integrations/matrix/crew/` — `channels.py`, `tunnel.py`,
`swarm_toolkit.py` — plus targeted extensions of `config.py`, `events.py`, `appservice.py`,
`crew_wrapper.py`, `transport.py`, `session.py`, `registry.py`:

- **`ChannelManager`** reads `MatrixCrewConfig.channels`, and for each channel ensures the room
  exists (creating it through a new `MatrixAppService.create_room_as_bot()`), sets the alias
  `#<name>:<server_name>`, join rule (`public` / `invite`), invites + joins member agents, and
  writes a `m.parrot.channel` state event carrying the policy. It also resolves `room_id →
  ChannelConfig` for the transport.
- **`TunnelRegistry`** returns the private room for an unordered agent pair, creating it on
  first use (`preset=private_chat`, `is_direct=true`, both intents joined, `m.parrot.tunnel`
  state). `AgentTunnel.ask()` sends `m.parrot.task` with `correlation_id`, `hops`,
  `origin_session` and awaits the matching `m.parrot.result` (future map, same pattern as
  `MatrixA2ATransport.wait_for_result`). A periodic sweeper tombstones idle tunnels after
  `ttl_minutes`.
- **Inbound task handling** lives in `MatrixCrewAgentWrapper.handle_task()`: it runs the bot
  with a structured-output prompt built from `TaskEventContent` (+ `expected_schema`), validates
  the `AgentAnswer`, and sends `m.parrot.result` as the target agent.
  `MatrixCrewTransport.start()` finally calls `appservice.set_custom_event_callback()` and
  dispatches TASK → wrapper, RESULT/FEEDBACK → `TunnelRegistry`.
- **`AgentSwarmToolkit`** is instantiated once per agent by the transport and attached to the
  bot's `ToolManager`; its public async methods become tools. It uses `TunnelRegistry`,
  `MatrixCrewRegistry` and `ChannelManager`; `post_to_channel` is policy-checked (an agent can
  only post to channels it is a member of).
- **Swarm dispatch** in `MatrixCrewTransport.on_room_message()`: after commands and
  `@mention`, an un-mentioned human message in a channel with `answer_policy: swarm` goes to
  `SwarmSessionManager`, which enforces `max_concurrent_sessions` / `cooldown_seconds` and
  spawns a `MatrixCollaborativeSession` with `trigger_event_id`. `_active_sessions` becomes
  `Dict[str, Dict[str, MatrixCollaborativeSession]]` (room → session_id → session).
  `!investigate` continues to work in any channel.
- **Session cross-pollination** calls `TunnelRegistry` instead of posting inter-agent mentions
  in the channel; when `echo_summary_to_channel` is on, a one-line
  "🔒 *analyst* asked *writer* a question" is posted as the requester with reply-to the trigger.
- **Human classification**: `MatrixCrewRegistry.is_human(mxid)` — not an agent, not the bot;
  bridge puppets match a configurable `human_namespace_patterns` list (defaults for
  `@signal_`, `@slack_`, `@discord_`).
- **Space** (optional): `ChannelManager` creates the Space room and links channels and
  tunnels via `m.space.child` / `m.space.parent`.
- **Dev stack**: compose services `synapse`, `postgres`, `element-web`, and profile
  `bridges` → `mautrix-signal`, `mautrix-slack`, `mautrix-discord`; registration YAMLs
  under `docker/matrix/`, `scripts/matrix/bootstrap.sh` registers the parrot AppService,
  creates the coordinator user and prints Element / Element X login hints (`.well-known`
  served by an nginx sidecar so Element X can discover the homeserver).

### Component Diagram

```
Human (Element / Element X / Slack ⇄ mautrix-slack / Signal / Discord)
   │  m.room.message in channel room
   ▼
MatrixAppService._handle_event ──(m.parrot.task/result/feedback)──► custom_event_callback
   │ event_callback(room_id, sender, body, event)                        │
   ▼                                                                     ▼
MatrixCrewTransport.on_room_message                          TunnelRegistry.on_custom_event
   ├─ !command ──► coordinator                                   ├─ RESULT → resolve future
   ├─ @mention ──► MatrixCrewAgentWrapper.handle_message         ├─ FEEDBACK → store
   ├─ dedicated room / unaddressed_agent (unchanged)             └─ TASK → wrapper.handle_task
   └─ ChannelManager.policy(room_id)                                     │ runs bot, validates
        ├─ mention → ignore                                              │ AgentAnswer
        ├─ silent  → ignore                                              ▼
        └─ swarm   → SwarmSessionManager.start(trigger)          send m.parrot.result
                        │ (concurrency + cooldown)
                        ▼
              MatrixCollaborativeSession(session_id, trigger_event_id)
                 investigate → cross-pollinate (via AgentTunnel.ask) → synthesize
                                                    │
Agent LLM ──► AgentSwarmToolkit.ask_agent ──► TunnelRegistry.get_or_create(a,b).ask()
                                                    │ private 2-member room
                                                    ▼
                                    m.parrot.task ──► peer wrapper.handle_task ──► m.parrot.result
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MatrixCrewConfig` (`crew/config.py:139`) | extends | new optional `channels`, `tunnels`, `space`, `human_namespace_patterns`; `CollaborativeConfig` gains `max_concurrent_sessions`, `cooldown_seconds` |
| `ParrotEventType` / event models (`events.py`) | extends | `CHANNEL = "m.parrot.channel"` (state), `TUNNEL = "m.parrot.tunnel"` (state), `FEEDBACK = "m.parrot.feedback"`; `TaskEventContent` gains `correlation_id`, `hops`, `origin_session`, `expected_schema`; new `FeedbackEventContent`, `ChannelStateContent`, `TunnelStateContent`, `AgentAnswer` |
| `MatrixAppService` (`appservice.py:36`) | extends | new `create_room_as_bot()`, `invite_as_bot()`, `leave_as_agent()`, `set_room_state_as_bot()`; `_handle_event` routes FEEDBACK too |
| `MatrixCrewAgentWrapper` (`crew/crew_wrapper.py:20`) | extends | new `handle_task(TaskEventContent, room_id) -> None` (structured-output run + `m.parrot.result`) |
| `MatrixCrewTransport` (`crew/transport.py:22`) | modifies | channel bootstrap in `start()`, policy branch in `on_room_message()`, `set_custom_event_callback` wiring, toolkit attachment, concurrent sessions map |
| `MatrixCollaborativeSession` (`crew/session.py:40`) | modifies | `trigger_event_id` param; cross-pollination through `TunnelRegistry`; per-session state only (no room-level singleton assumptions) |
| `MatrixCrewRegistry` (`crew/registry.py:65`) | extends | `is_human(mxid)`, `human_namespace_patterns` |
| `MatrixA2ATransport.wait_for_result` (`a2a_transport.py:249`) | pattern reuse | correlation-future pattern copied into `TunnelRegistry` (single-user wrapper is not used by the crew) |
| `AbstractToolkit` (`parrot/tools/toolkit.py:216`) | subclass | `AgentSwarmToolkit`; public async methods become tools |
| `parrot.notifications.NotificationMixin` (`notifications/__init__.py:60`) | documented alternative | e-mail is out of Matrix scope |
| `docker-compose.matrix.yml`, `docker/matrix/**`, `scripts/matrix/bootstrap.sh` | modifies / new | dev stack |
| `examples/matrix_crew/*`, `docs/integrations/matrix/{CLIENTS,BRIDGES}.md` | extends / new | docs |

### Data Models

```python
# crew/config.py (additions — field names are normative)
class ChannelConfig(BaseModel):
    name: str                                   # alias localpart: #<name>:<server_name>
    visibility: Literal["public", "private"] = "public"
    agents: List[str] = []                      # keys of MatrixCrewConfig.agents
    answer_policy: Literal["mention", "swarm", "silent"] = "mention"
    room_id: Optional[str] = None               # pre-existing room; created when None
    topic: Optional[str] = None

class TunnelConfig(BaseModel):
    enabled: bool = True
    ttl_minutes: int = 120                      # 0 = keep forever
    max_hops: int = 3
    default_timeout: float = 60.0
    echo_summary_to_channel: bool = True

class SpaceConfig(BaseModel):
    enabled: bool = False
    name: str = "Parrot Swarm"
    room_id: Optional[str] = None

class CollaborativeConfig(BaseModel):           # existing, extended
    max_concurrent_sessions: int = 3
    cooldown_seconds: float = 10.0

class MatrixCrewConfig(BaseModel):              # existing, extended
    channels: List[ChannelConfig] = []
    tunnels: TunnelConfig = TunnelConfig()
    space: SpaceConfig = SpaceConfig()
    human_namespace_patterns: List[str] = [r"^@signal_", r"^@slack_", r"^@discord_"]

# events.py (additions)
class AgentAnswer(BaseModel):
    answer: Any                                 # str or object validated against expected_schema
    confidence: Optional[float] = None          # 0..1
    sources: List[str] = []
    metadata: Dict[str, Any] = {}

class TaskEventContent(BaseModel):              # existing, extended
    correlation_id: Optional[str] = None
    hops: int = 0
    origin_session: Optional[str] = None
    expected_schema: Optional[Dict[str, Any]] = None

class FeedbackEventContent(BaseModel):
    correlation_id: str
    about_event_id: str
    from_agent: str
    to_agent: str
    rating: int                                 # -1..5 (spec: ge=-1, le=5)
    comment: Optional[str] = None

class ChannelStateContent(BaseModel):           # m.parrot.channel (state_key="")
    name: str; visibility: str; answer_policy: str; agents: List[str]; version: int = 1

class TunnelStateContent(BaseModel):            # m.parrot.tunnel (state_key="")
    agents: List[str]; created_at: datetime; ttl_minutes: int; origin_session: Optional[str]
```

### New Public Interfaces

```python
# crew/channels.py
class ChannelManager:
    def __init__(self, config: MatrixCrewConfig, appservice: MatrixAppService) -> None: ...
    async def ensure_channels(self) -> Dict[str, str]           # name -> room_id
    def channel_for_room(self, room_id: str) -> Optional[ChannelConfig]
    def room_for_channel(self, name: str) -> Optional[str]
    def is_member(self, agent_name: str, channel: str) -> bool
    async def ensure_space(self) -> Optional[str]                # room_id when enabled
    async def link_to_space(self, room_id: str) -> None

# crew/tunnel.py
class AgentTunnel:
    room_id: str; agents: tuple[str, str]
    async def ask(self, requester: str, target: str, question: str, *,
                  expected_schema: Optional[dict] = None, timeout: Optional[float] = None,
                  hops: int = 0, origin_session: Optional[str] = None) -> AgentAnswer
    async def send_feedback(self, requester: str, target: str, about_event_id: str,
                            rating: int, comment: Optional[str] = None) -> str

class TunnelRegistry:
    def __init__(self, config: TunnelConfig, appservice: MatrixAppService,
                 channels: ChannelManager, wrappers: Dict[str, "MatrixCrewAgentWrapper"]) -> None
    async def get_or_create(self, agent_a: str, agent_b: str) -> AgentTunnel
    async def on_custom_event(self, event_type: str, content: dict, room_id: str, sender: str) -> None
    async def start_sweeper(self) -> None; async def stop(self) -> None
    async def list_tunnels(self) -> List[TunnelStateContent]

# crew/swarm_toolkit.py
class AgentSwarmToolkit(AbstractToolkit):
    def __init__(self, agent_name: str, tunnels: TunnelRegistry, registry: MatrixCrewRegistry,
                 channels: ChannelManager, appservice: MatrixAppService, **kwargs) -> None
    async def ask_agent(self, agent: str, question: str, expected_schema: Optional[dict] = None,
                        timeout: Optional[float] = None) -> dict          # AgentAnswer.model_dump()
    async def send_feedback(self, agent: str, about_event_id: str, rating: int,
                            comment: Optional[str] = None) -> str
    async def list_agents(self) -> List[dict]
    async def list_channels(self) -> List[dict]
    async def post_to_channel(self, channel: str, text: str) -> str

# crew/swarm.py
class SwarmSessionManager:
    def __init__(self, config: CollaborativeConfig, transport: "MatrixCrewTransport") -> None
    async def maybe_start(self, room_id: str, sender: str, body: str, event_id: str) -> Optional[str]
    def active(self, room_id: str) -> List[MatrixCollaborativeSession]

# crew/crew_wrapper.py (addition)
async def handle_task(self, task: TaskEventContent, room_id: str) -> None

# appservice.py (additions)
async def create_room_as_bot(self, *, name: Optional[str] = None, alias_localpart: Optional[str] = None,
                             topic: Optional[str] = None, is_direct: bool = False,
                             preset: str = "private_chat", invitees: Optional[List[str]] = None,
                             initial_state: Optional[List[dict]] = None) -> str
async def set_room_state_as_bot(self, room_id: str, event_type: str, content: dict, state_key: str = "") -> str
async def leave_as_agent(self, agent_name: str, room_id: str) -> None
```

Coordinator commands added: `!channels`, `!agents`, `!tunnels`.

---

## 3. Module Breakdown

### Module 1: Config & Event Models
- **Path**: `crew/config.py`, `events.py`, `crew/__init__.py`, `matrix/__init__.py`
- **Responsibility**: `ChannelConfig`, `TunnelConfig`, `SpaceConfig`, `CollaborativeConfig` and `MatrixCrewConfig` extensions with validators (channel agents must exist; unique names; `swarm` requires `collaborative`); new event types and Pydantic contents; `AgentAnswer`; lazy exports.
- **Depends on**: none

### Module 2: AppService Room Primitives
- **Path**: `appservice.py`
- **Responsibility**: `create_room_as_bot`, `set_room_state_as_bot`, `leave_as_agent`, alias creation; route `m.parrot.feedback` in `_handle_event`; custom-event callback receives `(event_type, content, room_id, sender)` (keep backward-compatible 2-arg call for `HybridDelegator` via inspection or adapter).
- **Depends on**: Module 1

### Module 3: Channel Manager (+ Space)
- **Path**: `crew/channels.py`
- **Responsibility**: ensure rooms/aliases/join rules/membership, publish `m.parrot.channel` state, reconcile existing rooms, optional Space root + child links, room↔channel lookup.
- **Depends on**: Modules 1, 2

### Module 4: Tunnel Registry & Inbound Task Handler
- **Path**: `crew/tunnel.py`, `crew/crew_wrapper.py`
- **Responsibility**: `AgentTunnel`, `TunnelRegistry` (pair→room cache, correlation futures, hop guard, TTL sweeper with tombstone), `MatrixCrewAgentWrapper.handle_task` (structured-output prompt, `AgentAnswer` validation incl. `expected_schema`, `m.parrot.result` emission, error result on failure).
- **Depends on**: Modules 1, 2, 3

### Module 5: Agent Swarm Toolkit
- **Path**: `crew/swarm_toolkit.py`
- **Responsibility**: `AgentSwarmToolkit` tools with docstrings; membership/policy checks; timeout → `{"status": "timeout"}` envelope.
- **Depends on**: Module 4

### Module 6: Transport Integration & Swarm Sessions
- **Path**: `crew/transport.py`, `crew/swarm.py`, `crew/session.py`, `crew/registry.py`, `crew/coordinator.py`
- **Responsibility**: startup wiring (channels, tunnels, toolkit attachment to each bot's `ToolManager`, `set_custom_event_callback`), policy dispatch, `SwarmSessionManager` (concurrency, cooldown, session ids), concurrent `_active_sessions`, session `trigger_event_id` + tunnel-based cross-pollination + echo line, `is_human`, `!channels/!agents/!tunnels`.
- **Depends on**: Modules 3, 4, 5

### Module 7: Dev Stack (docker-compose + bootstrap)
- **Path**: `docker-compose.matrix.yml`, `docker/matrix/{synapse,element,bridges}/**`, `scripts/matrix/bootstrap.sh`
- **Responsibility**: Synapse (pinned `ghcr.io/element-hq/synapse`) + Postgres 16 + Element Web + `.well-known` sidecar; `bridges` profile with mautrix-signal/slack/discord registration templates mounted via `app_service_config_files`; bootstrap script (generate homeserver config, register parrot AppService via `generate_registration`, create coordinator user, print hints).
- **Depends on**: none (parallelisable)

### Module 8: Docs & Examples
- **Path**: `docs/integrations/matrix/CLIENTS.md`, `docs/integrations/matrix/BRIDGES.md`, `examples/matrix_crew/swarm_crew.yaml`, `examples/matrix_crew/swarm_example.py`, `examples/matrix_crew/MATRIX_CREW_GUIDE.md`
- **Responsibility**: client selection (Element Desktop/Web primary, Nheko secondary, Element X mobile; FluffyChat caveat), bridge docs incl. documentation-only Instagram/XMPP and the e-mail decision, swarm YAML example and walkthrough.
- **Depends on**: Modules 6, 7 (content), otherwise parallel

---

## 4. Test Specification

Tests live in `packages/ai-parrot-integrations/tests/` next to the existing `test_matrix_*.py`
files and mock `MatrixAppService` / intents (no live homeserver in unit tests).

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_channel_config_validation` | 1 | unknown agent, duplicate name, `swarm` without `collaborative` → `ValidationError` |
| `test_crew_config_backward_compat` | 1 | FEAT-044/195 YAML loads with empty channels / default tunnels |
| `test_agent_answer_expected_schema` | 1 | `answer` validated against JSON schema; failure → error result |
| `test_feedback_event_content` | 1 | rating bounds, required fields |
| `test_create_room_as_bot` | 2 | preset/is_direct/alias/initial_state forwarded to intent |
| `test_handle_event_routes_feedback` | 2 | `m.parrot.feedback` reaches custom callback with room/sender |
| `test_ensure_channels_creates_missing` | 3 | rooms created only when `room_id` is None; alias + join rule + state set |
| `test_ensure_channels_reconciles_existing` | 3 | existing room gets updated `m.parrot.channel` state, warning logged |
| `test_space_links_children` | 3 | `space.enabled` → `m.space.child` for each channel |
| `test_tunnel_get_or_create_is_symmetric` | 4 | `(a,b)` and `(b,a)` return the same room |
| `test_tunnel_ask_roundtrip` | 4 | task sent, result resolves future, `AgentAnswer` returned |
| `test_tunnel_hop_limit` | 4 | `hops >= max_hops` → rejected without sending |
| `test_tunnel_ttl_sweeper` | 4 | idle tunnel → both leave + tombstone; `ttl_minutes: 0` never sweeps |
| `test_wrapper_handle_task_emits_result` | 4 | bot invoked, `m.parrot.result` sent as target agent with same `correlation_id` |
| `test_wrapper_handle_task_error` | 4 | bot exception → `success=False` result |
| `test_toolkit_exposes_five_tools` | 5 | `get_tools()` names = ask_agent, send_feedback, list_agents, list_channels, post_to_channel |
| `test_toolkit_post_to_channel_policy` | 5 | non-member agent → rejected |
| `test_toolkit_ask_agent_timeout` | 5 | returns `{"status": "timeout", ...}` envelope |
| `test_transport_swarm_policy_dispatch` | 6 | un-mentioned human text in swarm channel starts session; mention/silent channels do not |
| `test_transport_concurrent_sessions` | 6 | two triggers in one room → two sessions; third beyond cap → busy notice |
| `test_transport_cooldown` | 6 | second trigger within cooldown ignored with notice |
| `test_session_cross_pollinate_via_tunnel` | 6 | cross-pollination calls `TunnelRegistry`, echo line posted when enabled |
| `test_registry_is_human_bridge_patterns` | 6 | `@slack_x`, `@signal_y` are human; agents/bot are not |
| `test_investigate_still_works` | 6 | `!investigate` path unchanged in any channel |
| `test_coordinator_list_commands` | 6 | `!channels/!agents/!tunnels` render |

### Integration Tests
| Test | Description |
|---|---|
| `test_swarm_end_to_end_mocked` | human message → session → agents consult via tunnel → synthesis reply-to trigger (all Matrix I/O mocked) |
| `test_compose_config_valid` | `docker compose -f docker-compose.matrix.yml --profile bridges config` succeeds (skipped if docker missing) |
| `test_bootstrap_script_dry_run` | `scripts/matrix/bootstrap.sh --dry-run` prints expected steps |

### Test Data / Fixtures
```python
@pytest.fixture
def swarm_config(tmp_path) -> MatrixCrewConfig: ...   # 3 agents, general(swarm) + finance(private, mention)
@pytest.fixture
def fake_appservice() -> MatrixAppService: ...        # AsyncMock intents; captures sent events
@pytest.fixture
def fake_bot_manager(monkeypatch): ...                # BotManager.get_bot -> stub agent with .ask()
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/ -k matrix -v`
- [ ] Existing FEAT-044 / FEAT-195 tests pass unchanged; `examples/matrix_crew/matrix_crew.yaml` and `collaborative_crew.yaml` load without modification
- [ ] `answer_policy` accepts only `mention | swarm | silent` (`router` rejected at validation)
- [ ] Channels declared in YAML are created (or reconciled) with alias, join rule, membership and `m.parrot.channel` state at `MatrixCrewTransport.start()`
- [ ] A tunnel is a 2-member private room; `get_or_create` is symmetric and lazy; default `ttl_minutes` is 120 and idle tunnels are tombstoned; `0` keeps forever
- [ ] `ask_agent` returns an `AgentAnswer` envelope; `expected_schema`, when given, is enforced; loops stop at `max_hops`
- [ ] An inbound `m.parrot.task` produces an `m.parrot.result` from the target agent (producer exists)
- [ ] Un-mentioned human text in a `swarm` channel starts a collaborative session; sessions are concurrent per room up to `max_concurrent_sessions` with `cooldown_seconds`
- [ ] Cross-pollination goes through tunnels and posts a one-line echo by default (`echo_summary_to_channel: true`)
- [ ] Bridged MXIDs matching `human_namespace_patterns` are treated as humans (mentions + swarm identical)
- [ ] `space.enabled: false` by default; when `true`, channels and tunnels are linked as Space children
- [ ] `docker compose -f docker-compose.matrix.yml --profile bridges config` is valid; services: synapse, postgres, element-web, well-known, mautrix-signal, mautrix-slack, mautrix-discord — no e-mail, Instagram or XMPP services
- [ ] `docs/integrations/matrix/CLIENTS.md` (Element Desktop/Web, Nheko, Element X; FluffyChat caveat) and `BRIDGES.md` (incl. Instagram/XMPP docs-only, e-mail via `NotificationMixin`) exist
- [ ] No new runtime dependency; `[matrix]` extra unchanged
- [ ] No blocking I/O; all new code has Google docstrings + type hints; Pydantic for every payload

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-26 on `dev` (matrix package last modified 2026-08-03, commit `c8de2129f`).
> `M` = `packages/ai-parrot-integrations/src/parrot/integrations/matrix/`. Line numbers exact.

### Verified Imports
```python
from parrot.integrations.matrix import (            # M/__init__.py:31 lazy __getattr__
    MatrixAppService, MatrixAppServiceConfig, ParrotEventType,
    TaskEventContent, ResultEventContent, StatusEventContent, AgentCardEventContent,
    generate_registration, generate_tokens,
    MatrixCrewTransport, MatrixCrewConfig, MatrixCrewAgentEntry,
    MatrixCrewRegistry, MatrixAgentCard, MatrixCoordinator, MatrixCrewAgentWrapper,
)
from parrot.integrations.matrix.crew import (       # M/crew/__init__.py:22-54 (eager)
    CollaborativeConfig, MatrixCollaborativeSession, SessionPhase, AgentRoundResult,
    CollaborativeSessionState, DelegationRequest, HybridDelegator,
    parse_mention, format_reply, build_pill, build_reply_content,
)
from parrot.tools import AbstractTool, AbstractToolkit   # parrot/tools/__init__.py:142-143
from parrot.notifications import NotificationMixin       # parrot/notifications/__init__.py:60
from mautrix.types import EventType, RoomID, UserID      # mautrix>=0.20 (pyproject.toml:61-64 [matrix] extra)
```

### Existing Class Signatures
```python
# M/events.py
class ParrotEventType:                                   # :21
    AGENT_CARD = "m.parrot.agent_card"; TASK = "m.parrot.task"   # :25, :28
    RESULT = "m.parrot.result"; STATUS = "m.parrot.status"       # :29, :30
    AGENT_CARD_EVENT / TASK_EVENT / RESULT_EVENT / STATUS_EVENT  # :35-47 EventType.find(...), None w/o mautrix
class AgentCardEventContent(BaseModel)                   # :62
class TaskEventContent(BaseModel)                        # :87  task_id, context_id, content, metadata, target_agent, skill_id
class ResultEventContent(BaseModel)                      # :103 task_id, context_id, content, artifacts, metadata, success=True, error
class StatusEventContent(BaseModel)                      # :118

# M/models.py
class MatrixAppServiceConfig(BaseModel)                  # :7  as_token, hs_token, homeserver, server_name, listen_host,
                                                         #     listen_port=9090, bot_localpart="parrot", as_id, namespace_regex="parrot-.*",
                                                         #     agent_mxid_map, auto_join_rooms
    @property bot_mxid -> str                            # :36
    def agent_mxid(self, agent_name: str) -> str         # :40

# M/appservice.py
EventCallback = Callable[[str, str, str, Any], Coroutine[Any, Any, None]]   # :33 (room_id, sender, body, raw_event)
class MatrixAppService:                                  # :36
    def __init__(self, config: MatrixAppServiceConfig) -> None            # :64
    async def start(self) -> None                                          # :82  (auto-join :112-114)
    async def stop(self) -> None                                           # :121
    @property running -> bool                                              # :131
    @property bot_intent -> IntentAPI                                      # :136
    async def register_agent(self, agent_name: str, displayname: Optional[str] = None) -> str   # :146
    async def unregister_agent(self, agent_name: str) -> None              # :179
    async def ensure_agent_in_room(self, agent_name: str, room_id: str) -> None   # :196 (invite :218, ensure_joined :224)
    def list_agents(self) -> Dict[str, str]                                # :231
    async def send_as_agent(self, agent_name: str, room_id: str, message: str) -> str   # :239
    async def send_formatted_as_agent(self, agent_name, room_id, body, formatted_body) -> str   # :263
    async def send_as_bot(self, room_id: str, message: str) -> str        # :309
    async def send_custom_event_as_agent(self, agent_name: str, room_id: str, event_type: str, content: dict) -> Optional[str]   # :316
    async def send_reply_as_agent(self, agent_name, room_id, message, reply_to_event_id) -> str   # :349 (m.in_reply_to :388)
    async def send_reply_as_bot(self, room_id, message, reply_to_event_id) -> str   # :393
    def set_event_callback(self, callback: EventCallback) -> None          # :431
    def set_custom_event_callback(self, callback: Callable) -> None        # :444 — callback(event_type: str, content: dict)
    async def _handle_event(self, event: Event) -> None                    # :456 — TASK/RESULT → custom cb (:461-471); drops own
                                                                           #   virtual users (:485-488) and m.replace edits (:491-494)
    def _get_intent(self, mxid: str) -> IntentAPI                          # :526

# M/client.py (single-user client; NOT used by the crew transport)
class MatrixClientWrapper:                               # :32
    async def send_event(self, room_id: str, event_type: str, content: Dict[str, Any]) -> str   # :193
    async def set_room_state(self, room_id, event_type, content, state_key="") -> str            # :217
    async def get_room_state_event(self, room_id, event_type, state_key="") -> Optional[Dict]   # :244

# M/a2a_transport.py
class MatrixA2ATransport:                                # :25 (wraps MatrixClientWrapper)
    async def send_task(self, room_id, content, *, task_id=None, context_id=None, target_agent=None, skill_id=None, metadata=None) -> str   # :111
    async def wait_for_result(self, room_id: str, task_id: str, *, timeout: float = 60.0) -> Optional[ResultEventContent]   # :249
    async def _on_result_event(self, event: Any) -> None                   # :288

# M/crew/config.py
def _substitute_env_vars(value: str) -> str              # :19 ; _walk_and_substitute(obj) :39
class MatrixCrewAgentEntry(BaseModel)                    # :57  chatbot_id, display_name, mxid_localpart, avatar_url, dedicated_room_id, skills, tags, file_types
class CollaborativeConfig(BaseModel)                     # :91  command_prefix="!investigate", max_rounds=1, agent_timeout=120.0,
                                                         #      session_timeout=600.0, summarizer_agent, session_verbosity, include_chat_context=True
class MatrixCrewConfig(BaseModel)                        # :139 homeserver_url, server_name, as_token, hs_token, bot_mxid, general_room_id,
                                                         #      agents: Dict[str, MatrixCrewAgentEntry], appservice_port=8449, pinned_registry,
                                                         #      typing_indicator, streaming, unaddressed_agent, max_message_length, collaborative
    @model_validator(mode="after") validate_summarizer_agent   # :193
    @classmethod from_yaml(cls, path: str) -> "MatrixCrewConfig"   # :217

# M/crew/registry.py
class MatrixAgentCard(BaseModel)                         # :14  agent_name, display_name, mxid, status, current_task, skills, joined_at, last_seen
class MatrixCrewRegistry:                                # :65
    async def register(self, card) / unregister(name) / update_status(name, status, current_task=None)   # :89 / :109 / :129
    async def get(self, agent_name) -> Optional[MatrixAgentCard]           # :162
    async def get_by_mxid(self, mxid) -> Optional[MatrixAgentCard]         # :174
    async def all_agents(self) -> List[MatrixAgentCard]                    # :191

# M/crew/mention.py
_PLAIN_MENTION_RE = re.compile(r"@(\w[\w.-]*)(?:\s|$|:)")               # :11
def parse_mention(body: str, server_name: str) -> Optional[str]          # :19 (single localpart)
def build_reply_content(text: str, reply_to_event_id: str) -> dict       # :85

# M/crew/crew_wrapper.py
class MatrixCrewAgentWrapper:                            # :20
    def __init__(self, agent_name, config: MatrixCrewAgentEntry, appservice, registry, coordinator, server_name, streaming=True, max_message_length=4096)   # :42
    async def handle_message(self, room_id: str, sender: str, body: str, event_id: str) -> None   # :68 (BotManager.get_bot :111, agent.ask :118)
    async def _send_response(self, room_id: str, response: str) -> None   # :158

# M/crew/coordinator.py
class MatrixCoordinator:                                 # :16  __init__(client, registry, general_room_id, rate_limit_interval=0.5) :31
    async def refresh_status_board(self) -> None         # :120

# M/crew/transport.py
class MatrixCrewTransport:                               # :22
    def __init__(self, config: MatrixCrewConfig) -> None # :39  _appservice, _coordinator, _registry, _wrappers, _room_to_agent,
                                                         #      _agent_mxids, _active_sessions: Dict[str, MatrixCollaborativeSession]
    @classmethod from_yaml(cls, path: str)               # :55
    async def start(self) -> None                        # :71  (register_agent :111, wrappers :127, rooms :154/:165, coordinator :175-180,
                                                         #       set_event_callback :194)
    async def stop(self) -> None                         # :198
    async def on_room_message(self, room_id, sender, body, event_id) -> None   # :218
        # agent sender → session.handle_inter_agent_message or drop (:245-258)
        # !investigate (:263-296) ; dedicated room (:303) ; @mention (:314-327) ; unaddressed_agent (:330) ; ignore (:340)
    async def _run_session(self, room_id, session) -> None                 # :345
    def _is_collaborative_command(self, body: str) -> Optional[str]        # :367
class _AppServiceBotClient                               # :412 (duck-typed client for coordinator)

# M/crew/session_models.py
class SessionPhase(str, Enum)                            # :14 CREATED, INVESTIGATING, CROSS_POLLINATING, SYNTHESIZING, COMPLETED, FAILED
class AgentRoundResult(BaseModel)                        # :34
class CollaborativeSessionState(BaseModel)               # :60 session_id, room_id, question, phase, current_round, max_rounds, agent_results, ...

# M/crew/session.py
class MatrixCollaborativeSession:                        # :40
    def __init__(self, session_id, room_id, question, config: CollaborativeConfig, appservice, registry, wrappers, server_name) -> None   # :58
    @property phase / is_active                          # :92 / :97
    async def run(self) -> CollaborativeSessionState     # :108 (_investigate_phase :258, _cross_pollinate_phase :285, _synthesize_phase :313)
    async def handle_inter_agent_message(self, sender_mxid, body, event_id) -> None   # :147
    async def cancel(self, reason="Cancelled by user") -> None   # :198
    async def _call_agent_with_timeout(self, card, wrapper, prompt, round_number) -> Optional[AgentRoundResult]   # :383
    def _build_enriched_context(self, round_num, requesting_agent) -> str  # :472
    async def _announce(self, message: str) -> None      # :582

# M/crew/delegation.py
class DelegationRequest(BaseModel)                       # :31
class HybridDelegator:                                   # :49  __init__(appservice, registry) :61
    async def delegate(self, request: DelegationRequest, timeout: float = 60.0) -> Optional[str]   # :71
    async def on_custom_event(self, event_type: str, content: dict) -> None   # :153
    async def _wait_for_result(self, task_id: str, timeout: float) -> Optional[ResultEventContent]   # :214

# parrot/tools/toolkit.py
class AbstractToolkit(ABC):                              # :216 — public async methods become tools; names starting with '_' skipped (:545)
    def __init__(self, **kwargs)                         # :312
    def get_tools(...)                                   # :484
    def _generate_tools(self) -> None                    # :537
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ChannelManager.ensure_channels` | `MatrixAppService.ensure_agent_in_room()` | invite+join | `M/appservice.py:196` |
| `ChannelManager` | `MatrixAppService.bot_intent` | new `create_room_as_bot` wraps `IntentAPI.create_room` | `M/appservice.py:136` |
| `TunnelRegistry.on_custom_event` | `MatrixAppService.set_custom_event_callback()` | registered in `MatrixCrewTransport.start()` | `M/appservice.py:444`, `M/crew/transport.py:71` |
| `AgentTunnel.ask` | `MatrixAppService.send_custom_event_as_agent()` | `m.parrot.task` | `M/appservice.py:316` |
| `MatrixCrewAgentWrapper.handle_task` | `BotManager.get_bot(config.chatbot_id)` + `agent.ask()` | same as `handle_message` | `M/crew/crew_wrapper.py:111,118` |
| `SwarmSessionManager` | `MatrixCollaborativeSession(...)` + `MatrixCrewTransport._run_session` | replaces single-session branch | `M/crew/transport.py:263-296, :345` |
| `MatrixCollaborativeSession._cross_pollinate_phase` | `TunnelRegistry.get_or_create().ask()` | replaces channel mentions | `M/crew/session.py:285` |
| `AgentSwarmToolkit` | bot `ToolManager` (`tool_manager.add_toolkit` / equivalent — verify exact API at task time) | attached per agent in `start()` | `parrot/tools/toolkit.py:216` (unverified attach API — check before use) |
| Coordinator commands | `MatrixCoordinator` via `_AppServiceBotClient.send_text` | `!channels/!agents/!tunnels` | `M/crew/transport.py:412-424` |
| Bridges (compose) | Synapse `app_service_config_files` | registration YAML mounts | `docker-compose.matrix.yml` (currently none) |

### Does NOT Exist (Anti-Hallucination)
- ~~`MatrixAppService.create_room*` / `MatrixClientWrapper.create_room`~~ — no room-creation, DM (`m.direct`, `is_direct`) or alias API anywhere in `M/`; Module 2 adds it.
- ~~any handler that consumes `m.parrot.task` and emits `m.parrot.result`~~ — `wait_for_result` / `HybridDelegator._wait_for_result` have no producer; Module 4 adds `handle_task`.
- ~~`MatrixCrewTransport` calling `set_custom_event_callback`~~ — never called; `HybridDelegator` is never instantiated by the transport.
- ~~`m.thread` support~~ — only `m.in_reply_to` (`appservice.py:388/:422`, `mention.py:102`) and `m.replace`.
- ~~`ask_agent` / tunnel / swarm / channel tool or class in `M/`~~ — none; `HybridDelegator` is a plain class, not an `AbstractTool`. (An unrelated `ask_agent` MCP tool exists in `integrations/agentd/mcp_server.py:66`.)
- ~~`m.parrot.status` / `m.parrot.agent_card` routing in `_handle_event`~~ — only TASK/RESULT are routed.
- ~~multi-mention fan-out~~ — `parse_mention` returns a single localpart.
- ~~`A2AClientMixin.get_matrix_transport()` consumers~~ — storage only (`parrot/a2a/mixin.py:105/:117`); `MatrixA2ATransport` is never instantiated in `packages/*/src`.
- ~~E2EE / olm usage~~ — none, despite `python-olm` in the extra.
- ~~bridges, Element, Postgres in `docker-compose.matrix.yml`~~ — single `synapse` service today.
- ~~`answer_policy: router`~~ — deliberately not in v1.
- ~~Postmoogle / e-mail bridge~~ — out of scope by decision.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- All Matrix I/O through `MatrixAppService` intents (`_get_intent`, `bot_intent`); never through
  the single-user `MatrixClientWrapper` in crew code.
- Copy the correlation-future pattern of `MatrixA2ATransport.wait_for_result` (`:249-288`) for
  `TunnelRegistry`; key futures by `correlation_id`, not `task_id`, so retries stay distinct.
- Reuse `build_reply_content` / `send_reply_as_agent` for the echo line and final synthesis
  (reply-to the trigger event id).
- Toolkit: public async methods only; helpers prefixed `_`; every tool docstring is the LLM
  description (`AbstractToolkit._generate_tools`, `toolkit.py:537-545`). Use the FEAT-391
  `_open/_close` hooks for the sweeper if the toolkit owns it (see `.agent/CONTEXT.md`).
- `${ENV}` substitution in YAML via existing `_walk_and_substitute` (`config.py:39`).
- Structured output for `handle_task`: build the prompt from `TaskEventContent.content` +
  JSON-schema hint from `expected_schema`; parse/validate with Pydantic; on failure emit
  `ResultEventContent(success=False, error=...)` — never raise into the AppService loop.
- Keep `HybridDelegator` working: the transport's custom-event dispatcher must accept the
  new 4-arg callback and adapt when forwarding to the 2-arg `HybridDelegator.on_custom_event`.
- Logging via `logging.getLogger("parrot.matrix.<module>")` as in existing modules.

### Known Risks / Gotchas
- **O(N²) tunnel rooms** — bounded by lazy creation, symmetric pair key and TTL sweeper
  (120 min default); document `ttl_minutes: 0` cost.
- **A→B→A loops** — `hops` propagated in `TaskEventContent`, rejected at `max_hops` (3).
- **Session refactor** — moving from room-keyed singleton to `session_id`; `handle_inter_agent_message`
  must resolve the session from `origin_session` on the task/result, not from the room.
- **Peer offline/timeout** — `ask_agent` returns `{"status": "timeout"}`; session marks the agent
  skipped (existing FEAT-195 behaviour).
- **Existing room with different config** — reconcile state event and warn; never delete rooms.
- **Concurrency cap / cooldown reached** — coordinator posts a short busy notice (reply-to trigger).
- **Trigger message edited/deleted** — session continues; final synthesis posted without
  reply relation if the trigger is redacted.
- **Bridge relays edits/reactions** — ignored (`m.replace` already dropped at `:491-494`; add
  `m.reaction` drop).
- **AppService namespace** — tunnel/channel aliases must be covered by the registration
  (`namespace_regex`, aliases namespace); startup fails loudly with the required snippet.
- **Element X discovery** — needs `/.well-known/matrix/client` (sidecar) and Synapse ≥1.114
  for native sliding sync; pin the Synapse image.
- **Licensing** — Synapse, Element and mautrix bridges are AGPL-3.0; they run as separate
  containers and are never imported by MIT ai-parrot code; state this in `BRIDGES.md`.
- **Bridges need credentials** — signal (linked device), slack (token/password), discord
  (bot token recommended); bootstrap script must not embed secrets — `.env` template only.

### External Dependencies
| Package / Image | Version | Reason |
|---|---|---|
| `mautrix` | `>=0.20` (existing `[matrix]` extra) | AppService, intents, `EventType`, room creation |
| `pydantic` | `>=2` (core) | payloads, `AgentAnswer`, config |
| `pyyaml` | existing | config |
| `ghcr.io/element-hq/synapse` | pinned 1.15x (2026) | homeserver (AGPL, container) |
| `postgres` | `16-alpine` | Synapse + bridge DBs |
| `vectorim/element-web` | 1.12.x | dev client |
| `dock.mau.dev/mautrix/signal` | v26.07 | Signal bridge |
| `dock.mau.dev/mautrix/slack` | v26.08 | Slack bridge |
| `dock.mau.dev/mautrix/discord` | v0.7.7 | Discord bridge |
| `nginx:alpine` | latest | `.well-known` sidecar |

No new Python dependency is introduced.

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Worktree A (code lane, sequential)**: Modules 1 → 2 → 3 → 4 → 5 → 6, then Module 8 docs
  that describe code.
- **Worktree B (deployment lane, parallel)**: Module 7 (compose, `docker/matrix/**`,
  `scripts/matrix/bootstrap.sh`) and the `CLIENTS.md` / `BRIDGES.md` parts of Module 8 — zero
  file overlap with lane A; may merge first so developers can test lane A against it.
- **Cross-feature dependencies**: none in flight touch `integrations/matrix/` (FEAT-457/458/462
  are unrelated). No spec must be merged first.

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec; decisions are reflected in the body.

- [x] Flow type / base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] Tunnel mechanism — *Resolved in brainstorm*: private DM room + `m.parrot.*` events (no E2EE).
- [x] Swarm mode — *Resolved in brainstorm*: extend FEAT-195 `MatrixCollaborativeSession` with policy switch + concurrent sessions.
- [x] Deployment target — *Resolved in brainstorm*: dev/local docker-compose (no TLS/workers).
- [x] Homeserver — *Resolved in brainstorm*: keep Synapse (AGPL, isolated container); Tuwunel documented as alternative.
- [x] Bridge selection strictness — *Resolved in brainstorm*: best-available per platform, licence noted per bridge.
- [x] Agent-to-agent Q&A exposure — *Resolved in brainstorm*: both — `AgentSwarmToolkit` tools and session-driven cross-pollination share the tunnel primitive.
- [x] Bridged humans — *Resolved in brainstorm*: treated the same as native humans.
- [x] `router` answer policy in v1? — *Resolved in brainstorm*: deferred to a follow-up; v1 ships `mention | swarm | silent`.
- [x] Tunnel lifetime — *Resolved in brainstorm*: `ttl_minutes: 120` default; idle tunnels are left by both agents and tombstoned; `0` = keep forever.
- [x] `echo_summary_to_channel` default — *Resolved in brainstorm*: on by default.
- [x] Space grouping (Option D) — *Resolved in brainstorm*: included as an optional capability, `space.enabled: false` by default.
- [x] Instagram / XMPP bridges — *Resolved in brainstorm*: dropped from the compose file; documented only.
- [x] E-mail bridge — *Resolved in brainstorm*: removed from scope; e-mail handled by agents via `async-notify` (`NotificationMixin`).
- [x] `ask_agent` contract — *Resolved in brainstorm*: fixed `AgentAnswer` envelope `{answer, confidence, sources, metadata}`; `expected_schema` validates `answer` when given.
- [ ] Exact `ToolManager` API to attach a toolkit to an already-constructed bot (`add_toolkit` vs `register_tools`) — *Owner: implementer, decide in Module 6 task after grep*.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-26 | Jesus Lara / AI-Parrot Team | Initial draft from brainstorm (FEAT-463) |
