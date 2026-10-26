---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations, ai-parrot-server]
tags: [roost, squawk, inter-agent, performatives, agent-registry, blackboard, matrix, eventbus, working-memory]
depends_on: [FEAT-746]
---

# Feature Specification: Roost — local inter-agent sub-protocol over Squawk

**Feature ID**: FEAT-747
**Date**: 2026-10-26
**Author**: Jesus Lara / AI-Parrot Team
**Status**: review
**Target version**: 1.3.0
**Proposal**: `sdd/proposals/local-inter-agent.proposal.md` (status `review`, 9/9 questions resolved 2026-10-26)
**Source brainstorm**: `sdd/state/FEAT-747/source.md`
**Parent**: FEAT-746 **Squawk** (`sdd/proposals/inter-agent-protocol.proposal.md`) — envelope, handles, blob store, catalog tools, policy gate. Reused, never redefined here.
**Builds on**: FEAT-070 (`CapabilityRegistry`), FEAT-463 (`matrix-agents-swarm`), FEAT-195 (`matrix-collaborative-crew`), FEAT-710 (`parrot-telemetry-event-fanout`)

---

## 1. Motivation & Business Requirements

### Problem Statement

Inside one trust domain, ai-parrot agents still talk to each other through serialized JSON text and an LLM turn on both ends. An agent that has been granted inter-agent communication should be able to look up who can answer, call them, and receive a typed result it can use directly, with an LLM turn only where a decision is needed.

Two things the cross-boundary spec (FEAT-746) does not cover and this one adds:

- **Intent as a typed field.** A message that says *inform agent B of this* should let B act on it with no acknowledgement and no formal reply; a *request* obliges a reply; a *call for proposals* opens a negotiation. Without that field every message costs the receiver an LLM turn just to find out what is being asked of it.
- **Many agents, one conversation.** In a shared channel (an event-bus topic, a Matrix room with humans and agents) every message would otherwise wake every agent. Speech acts plus addressing plus protocol state let the harness decide who wakes, without an LLM.

Research (proposal §2) confirms none of the protocol pieces exist: no performative, protocol state machine, inter-agent grant, versioned blackboard or by-reference passing anywhere in core, server or integrations. Every existing agent-to-agent path — crew hand-off in `crew.py`, `AgentTool`, `AgentSwarmToolkit.ask_agent`, `HybridDelegator` — is text in, text out, with the callee's LLM woken on every message. One premise of the brainstorm was wrong: a substantial Matrix integration already exists (`m.parrot.*` events, room-state records, hop-limited `ask_agent` tunnels, per-crew roster), so the Matrix carrier is an adaptation of FEAT-044/195/463, not greenfield.

### Goals

- **G1 — Performatives.** Twelve typed speech acts (`inform`, `request`, `query`, `agree`, `refuse`, `failure`, `cfp`, `propose`, `accept`, `reject`, `subscribe`, `not_understood`) with fixed reply obligations and wake rules, chosen by the harness from the origin tool, never written by the LLM as text (L3).
- **G2 — Interaction protocols.** Five per-`conversation_id` state machines enforced by the harness (Inform, Request, Query, Contract Net, Subscribe); out-of-state messages get `not_understood` and never reach an LLM; timeouts, hop budget and token budget close conversations with typed `failure`s.
- **G3 — LLM-free gating.** Addressing → protocol state → decision-needed, decided without a model. Metric: wakes per message in a shared channel; target 1 for addressed traffic, the number of capability matches for broadcast, 0 for an `inform` with no handler.
- **G4 — Capability directory.** `AgentRegistry.find_capability(keywords | cap_id)` answers in < 5 ms deterministically, ranked by locality then cost, delegating to an extended `CapabilityRegistry` (`ResourceType.AGENT`, exact index) — embedding search stays the fallback. The lookup result is mounted through FEAT-746's `catalog.mount`, so the LLM sees a remote capability as a plain tool.
- **G5 — Inter-agent grant.** Granted per agent by configuration with a capability-pattern scope (`hr.*`, `*`); a deterministic gate the model never sees. The serving agent's policy gate (`PBACToolCallGuardrail`, FEAT-746 capability gate) runs for local callers exactly as for remote ones; locality changes transport, not policy.
- **G6 — Blackboard.** Versioned, single-writer-per-key, ACL'd, subscribable store with v0 keys `roster`, `definitions`, `tasks`, `digest`, `artifacts`; in-process and Matrix room-state backends; a stale write is refused, never merged; a key change is an `inform` to subscribers.
- **G7 — Four local carriers** with one protocol: in-process (asyncio queue, full envelope, payloads by reference), same host (Arrow IPC over shared memory), same network (navigator-eventbus, dedicated instance, `reply_to` / correlation / idempotency / DLQ), Matrix (`m.parrot.*` events with a mandatory human-readable `body`). Results never become JSON text in a message body on the first three.
- **G8 — Results as native objects** (Pydantic models, Arrow tables, pandas frames, FEAT-746 handles) landing in the receiver's WorkingMemory as objects (L5).
- **G9 — Audit.** Every performative is a KMS-signed line in the serving agent's ledger and the caller's received ledger, joined by the shared `trace_id`; on Matrix the human `body` is part of the same record.
- **G10 — Subsume FEAT-463.** `AgentSwarmToolkit.ask_agent` becomes a Request/Query over the protocol engine; tunnels stay as room topology; hops, status and correlation come from one place.

### Non-Goals (explicitly out of scope)

- Redefining anything FEAT-746 owns: the Squawk envelope, Cap'n Proto RPC, handles (`ResultHandle`, via FEAT-704), blob store, catalog tools (`list`/`mount`/`unmount`/`search`/`find`), capability policy gate, Biscuit tokens, served ledger. Roost **consumes** them.
- Changing `AgentCrew.run_sequential` / `run_loop` / `run_flow` or the `FlowContext.shared_data` API for existing crews. Crew-to-channel mapping is a follow-up spec (resolved U4: crews untouched in v0).
- The FEAT-590 tool-call-delegate nodes and their `delegate` vocabulary — Roost's cfp origin tool is named `call_for_proposals`, never `delegate`.
- `HybridDelegator`'s visible human messages and the FEAT-195 collaborative session phases.
- `AuditLedger` credential entries and signers (reused, not changed); the FEAT-704 semantic audit ledger.
- WorkingMemory pandas operations and task_memory durable tiers.
- A2A JSON-RPC client/server, `A2AMeshDiscovery`, `A2AProxyRouter` — the external surface; adapters come from FEAT-746.
- Polars. FEAT-746 U3 amended D6 to pandas + Arrow IPC in v0; Roost's L-S4 gate uses a `pyarrow.Table`, not a Polars frame.
- BDI semantics, SL/KIF content languages, formal ontologies, the JADE platform model (L2).
- A new server (`ai-parrot-server`) surface: no HTTP handler ships in v0; the distribution stays in `projects` because the proposal carried it and FEAT-746's adapters live there.

---

## 2. Architectural Design

### Overview

Roost is a **sub-protocol over the Squawk envelope**: every Roost message is a `RoostMessage` (performative, protocol, `conversation_id`, `in_reply_to`, sender, receivers or capability filter, native `content`, optional human `body`) attached to one Squawk envelope. The two protocols share one wire format and differ in what the harness does with it: Squawk moves a typed call across a trust boundary; Roost decides, inside one trust domain, *who wakes and what is owed*.

The runtime unit is a **`RoostEndpoint`** per agent instance. It owns:

1. a **`ProtocolEngine`** holding one small deterministic state machine per `conversation_id` (Inform, Request, Query, Contract Net, Subscribe) plus the conversation's `ConversationBudget` (hops, tokens, deadline from the envelope's `budget_ms`);
2. a **`GatingDispatcher`** that answers three questions per inbound message, in order and without an LLM: *is this for me* (receivers or capability filter against the directory), *does the protocol state accept it* (`not_understood` otherwise), *does handling it need a decision* (run the deterministic tool, store the `inform`, bid from contract annotations, or wake the LLM);
3. one or more **carriers** (`InProcessCarrier`, `SharedMemoryCarrier`, `EventBusCarrier`, `MatrixCarrier`) chosen per registry entry — the protocol is identical on all four;
4. a **`Blackboard`** binding (in-memory or Matrix room state) and a **`RoostAuditLedger`** that signs one entry per performative with the existing `AbstractKMSSigner`.

The **capability directory** is the FEAT-070 `CapabilityRegistry`, extended (resolved U3) with `ResourceType.AGENT`, a synchronous exact-match index over capability ids and keywords, and locality/cost ranking; `AgentRegistry.find_capability` fronts it (and, through FEAT-746 U2's `kind` field, the remote `a2a`/`squawk` entries) so it does not become a fifth directory. Each registered agent advertises a `RoostAgentConfig` (capabilities, categories, category hashes, carrier, cost, backing, grant scope) on its `BotMetadata` / `BotConfig`. The **inter-agent grant** is evaluated by `GrantPolicy` on the caller side before any lookup result is mounted, and the caller's `PermissionContext` travels inside the message so the serving side runs its ordinary `PBACToolCallGuardrail` (first guard in `ToolManager.execute_tool`) unchanged.

The LLM never emits a performative. It calls a tool; **`RoostToolkit`** maps the origin tool to the act (`report` → `inform`, mounted capability tool → `request`, `ask_agent`/`AgentTool` → `query`, `call_for_proposals` → `cfp`, `watch` → `subscribe`, generic `send` with a four-value enum). Resolved decisions folded in (proposal §5): all twelve acts and five protocols ship in v0; a directly addressed `inform` wakes the receiver, a broadcast or capability-filtered `inform` is stored and wakes only when a registered handler asks for a decision; `digest` is owned by the coordinator if one exists, else by the last agent that closed a Request; Contract Net scores `propose(cost, time, confidence)` with fixed weights and a per-channel pluggable `BidScorer` override, waking the requester's LLM only when the rule cannot decide; the in-process carrier keeps the full envelope and passes payloads by reference (zero serialization, uniform audit and gating); the Matrix carrier **subsumes** FEAT-463 (`ask_agent` = Request over the engine, human `body` mandatory, `m.parrot.*` namespace extended, FEAT-195's rejection reinterpreted: Matrix is one carrier among four).

**Envelope coupling (resolved Q1/Q2).** The Squawk envelope model, its Cap'n Proto codec and the catalog tools live **only in the FEAT-746 satellite** (`ai-parrot-squawk`, import path provisionally `parrot.squawk`, fixed by the FEAT-746 spec). Roost never imports the satellite at module level: `parrot/roost/squawk_bridge.py` probes it lazily (`squawk_available()`), and every other module binds to the envelope through the structural `EnvelopeLike` `Protocol` naming only the fields Roost reads (`envelope_id`, `correlation_id`, `trace`, `budget_ms`, `token_budget`, `caller`, `idempotency_key`, `auth_token`). With the satellite present the endpoint wraps messages in the Squawk envelope and encodes them with its `CapnpEnvelopeCodec`; without it Roost **degrades, not fails**: messages ride Roost's own minimal `LocalEnvelope`, the bus carrier uses Roost's `JsonEnvelopeCodec` (both satisfy the same sync `EnvelopeCodec` protocol declared in `parrot/roost/codec.py`), and `find_and_mount` returns an empty list with a warning (no `catalog.mount`). Only that mount step and M3's read of FEAT-746's `kind` field depend on the satellite; everything else builds and tests now (see Worktree Strategy).

**Authority on the wire (resolved Q3).** In-process and same-host carriers pass the caller's `PermissionContext` by reference. On the bus and Matrix carriers the message carries **both** the serialized `PermissionContext` and, when FEAT-746 has issued one, the Biscuit token (`RoostMessage.auth_token`); the serving endpoint prefers the token and falls back to the context. Contract Net attenuation (AC-14) is a scope intersection in v0 and upgrades to token attenuation when Biscuit lands.

### Component Diagram

```
                LLM (caller agent)                       LLM (serving agent, only if llm_backed)
                      │ tool call                                     ▲ wake (decision needed)
                      ▼                                               │
   RoostToolkit ── origin tool → Performative ─┐          GatingDispatcher ── RUN_TOOL ──▶ ToolManager.execute_tool
   (send/report/call_for_proposals/watch,       │          │ addressing │ state │ decision      (PBACToolCallGuardrail,
    mounted capability tools via catalog.mount) │          │                                     FEAT-746 capability gate)
                      │                         │          ▲
                      ▼                         │          │
   RoostEndpoint (caller) ── GrantPolicy ── AgentRegistry.find_capability ──▶ CapabilityRegistry (AGENT, exact idx, locality)
        │  ProtocolEngine (per conversation_id FSM + ConversationBudget)
        │  RoostAuditLedger (AbstractKMSSigner)       Blackboard (roster/definitions/tasks/digest/artifacts)
        ▼                                                   ▲ subscribe → inform
   Carrier  ─ InProcessCarrier (asyncio.Queue, by-reference)
           ─ SharedMemoryCarrier (Arrow IPC / shm, repl_worker ownership rules)
           ─ EventBusCarrier (navigator_eventbus, dedicated instance, reply_to/correlation/idempotency/DLQ)
           ─ MatrixCarrier (m.parrot.roost event + body; m.parrot.blackboard state)  ◀── AgentSwarmToolkit.ask_agent
                      │
                      └──── RoostMessage ⟶ Squawk envelope (FEAT-746)  ⟶  RoostEndpoint (serving)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentRegistry` / `BotMetadata` / `BotConfig` (`parrot/registry/registry.py`) | extends | additive `roost: Optional[RoostAgentConfig]` on `BotMetadata` and `BotConfig`, `roost=` kwarg on `register()` / `register_bot_decorator()`, new `find_capability()`; all existing lookups unchanged |
| `CapabilityRegistry` / `ResourceType` (`parrot/registry/capabilities/`) | extends | `ResourceType.AGENT`; `register_agent_capability()`; synchronous `find_exact()`; embedding `search()` untouched and remains the fallback |
| `ToolManager` (`parrot/tools/manager.py`) | uses | `add_tool` / `unregister_tool` for mounts (through FEAT-746 catalog tools), `execute_tool(permission_context=...)` for deterministic Requests, `clone()` for per-session endpoints |
| `PBACToolCallGuardrail` (`parrot/bots/guardrails/builtin/pbac.py`) | uses | serving-side gate runs unchanged; the caller's `PermissionContext` travels in `RoostMessage.permission_context` |
| `enforce_agent_access` (`parrot/auth/agent_guard.py`) | uses | bot-resolution PBAC still applies when an endpoint resolves a peer instance |
| `WorkingMemoryToolkit.store_result` (`parrot/tools/working_memory/tool.py`) | uses | `inform` content stored as a native object (`data_type="auto"`); FEAT-746 adds the handle `EntryType` |
| `FlowContext` (`parrot/bots/flows/core/context.py`) | extends | optional `blackboard` binding beside `shared_data`; `shared_data` unchanged |
| `TraceContext` (`navigator_eventbus.lifecycle.trace`, re-exported by `parrot.core.events.lifecycle`) | uses | `trace_id` threaded through messages and audit entries |
| `AbstractKMSSigner` / `LocalHMACSigner` (`parrot/security/audit_ledger.py`) | uses | `RoostAuditLedger` is a sibling ledger sharing the signer; `AuditLedger.append()` is not called (it requires `credential_material`) |
| `navigator_eventbus.EventBus` (`parrot/observability/fanout.py` idiom) | uses | dedicated Roost instance; `Event.correlation_id` reused, `reply_to` / `idempotency_key` / trace in `Event.metadata` |
| `encode_dataframe` / `decode_dataframe_from_shm` / `unlink_shm` (`parrot/tools/repl_worker/transport.py`) | uses | same-host carrier payloads; host creates, receiver ACKs, sender unlinks |
| `AgentTool` (`parrot/tools/agent.py`) | extends | when the caller has a `RoostEndpoint` and the target is Roost-enabled, `_execute` issues a `query` instead of a bare text question |
| `AgentSwarmToolkit.ask_agent` (`matrix/crew/swarm_toolkit.py`) | extends | routed through the engine as a Request; `ctx.current_hops` seeds `ConversationBudget.hops`; the FEAT-463 status enum (`hop_limit`, `unknown_agent`, …) is preserved |
| `ParrotEventType` / `MatrixClientWrapper` (`matrix/events.py`, `matrix/client.py`) | extends / uses | `m.parrot.roost` message event, `m.parrot.blackboard` state event (one `state_key` per key); `send_event` / `set_room_state` / `get_room_state_event` / `on_custom_event` |
| FEAT-746 Squawk satellite (envelope, Cap'n Proto codec, catalog tools, capability gate, Biscuit) | optional runtime dependency | probed lazily by `parrot/roost/squawk_bridge.py` only (resolved Q1); names pinned in §6 "Does NOT Exist (provided by the FEAT-746 satellite)"; Roost degrades without it |

### Data Models

```python
# parrot/roost/performatives.py
class Performative(str, Enum):
    INFORM = "inform"; REQUEST = "request"; QUERY = "query"; AGREE = "agree"; REFUSE = "refuse"
    FAILURE = "failure"; CFP = "cfp"; PROPOSE = "propose"; ACCEPT = "accept"; REJECT = "reject"
    SUBSCRIBE = "subscribe"; NOT_UNDERSTOOD = "not_understood"

class InteractionProtocol(str, Enum):
    INFORM = "inform"; REQUEST = "request"; QUERY = "query"; CONTRACT_NET = "contract_net"; SUBSCRIBE = "subscribe"

class FailureCode(str, Enum):
    TIMEOUT = "TIMEOUT"; HOP_LIMIT = "HOP_LIMIT"; TOKEN_BUDGET = "TOKEN_BUDGET"; POLICY = "POLICY"
    CAPACITY = "CAPACITY"; NO_BIDS = "NO_BIDS"; CANCELLED = "CANCELLED"; STALE_CONTRACT = "STALE_CONTRACT"; INTERNAL = "INTERNAL"

class ReplyObligation(BaseModel):
    owed: bool
    allowed_replies: tuple[Performative, ...]
    wakes_receiver: Literal["never", "if_llm_backed", "if_addressed", "if_capability_matches", "requester_to_replan"]

OBLIGATIONS: dict[Performative, ReplyObligation]   # the table in the brainstorm "Performatives" section, verbatim

class AgentAddress(BaseModel):
    name: str                      # AgentRegistry name
    carrier: CarrierKind
    endpoint: Optional[str] = None # room id / bus topic / host id

class FailureInfo(BaseModel):
    code: FailureCode
    detail: str = ""
    retryable: bool = False

class RoostMessage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    performative: Performative
    protocol: InteractionProtocol
    conversation_id: str
    in_reply_to: Optional[str] = None
    sender: AgentAddress
    receivers: list[AgentAddress] = Field(default_factory=list)   # empty ⇒ capability_filter must be set
    capability_filter: Optional[str] = None                         # glob, e.g. "hr.people.*"
    content: Any = None                                             # native object / handle; never JSON text on carriers 1–3
    content_type: Optional[str] = None                              # dotted type name or media type, for handler lookup
    body: Optional[str] = None                                      # human rendering; MANDATORY on the Matrix carrier
    envelope: Any = None                                            # EnvelopeLike (Squawk envelope, FEAT-746)
    failure: Optional[FailureInfo] = None
    permission_context: Any = None                                  # parrot.auth.permission.PermissionContext of the caller (by reference in-process; serialized on bus/Matrix)
    auth_token: Optional[str] = None                                # FEAT-746 Biscuit token when issued; authoritative over permission_context on the serving side (Q3)
    created_at: datetime

class EnvelopeLike(Protocol):           # structural seam over the Squawk envelope (see §2 Overview)
    envelope_id: str
    correlation_id: str
    trace: Optional[TraceContext]
    budget_ms: Optional[int]
    token_budget: Optional[int]
    caller: str
    idempotency_key: Optional[str]
    auth_token: Optional[str]

class LocalEnvelope(BaseModel):        # Roost's minimal EnvelopeLike, used when the Squawk satellite is absent (Q1)
    model_config = ConfigDict(arbitrary_types_allowed=True)
    envelope_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: str
    trace: Optional[TraceContext] = None
    budget_ms: Optional[int] = None
    token_budget: Optional[int] = None
    caller: str
    idempotency_key: Optional[str] = None
    auth_token: Optional[str] = None
```

```python
# parrot/roost/codec.py  (Q2)
class EnvelopeCodec(Protocol):
    """Sync, bytes-safe codec over an EnvelopeLike + the Roost fields. Implemented by Roost's JsonEnvelopeCodec and the satellite's CapnpEnvelopeCodec."""
    content_type: str                                   # "application/json" | "application/x-capnp"
    def encode(self, msg: RoostMessage) -> bytes: ...
    def decode(self, data: bytes) -> RoostMessage: ...
```

```python
# parrot/roost/protocols.py
class TerminalState(str, Enum):
    DONE = "done"; INFORMED = "informed"; REFUSED = "refused"; FAILED = "failed"; CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"; AWARDED = "awarded"; NO_BIDS = "no_bids"; EXPIRED = "expired"

class ConversationBudget(BaseModel):
    hop_limit: int = 8
    hops: int = 0
    token_budget: Optional[int] = None
    tokens_used: int = 0
    deadline: Optional[datetime] = None        # from envelope.budget_ms
    bid_window_ms: Optional[int] = None        # Contract Net only

class ConversationState(BaseModel):
    conversation_id: str
    protocol: InteractionProtocol
    initiator: AgentAddress
    state: str                                  # machine-specific label, e.g. "awaiting_agree"
    terminal: Optional[TerminalState] = None
    budget: ConversationBudget
    last_message_id: Optional[str] = None
    proposals: list[RoostMessage] = Field(default_factory=list)   # Contract Net

class Transition(BaseModel):
    kind: Literal["accepted", "not_understood", "closed"]
    state: ConversationState
    obligations: tuple[Performative, ...] = ()
    emit: list[RoostMessage] = Field(default_factory=list)       # harness-generated replies (not_understood, failure(TIMEOUT), …)
```

```python
# parrot/roost/directory.py
class Locality(IntEnum):
    IN_PROCESS = 0; SAME_HOST = 1; SAME_NETWORK = 2; REMOTE = 3

class InterAgentGrant(BaseModel):
    scopes: list[str] = Field(default_factory=list)   # glob patterns: "hr.*", "*"; empty ⇒ not granted

class RoostAgentConfig(BaseModel):
    capabilities: list[str] = Field(default_factory=list)       # cap ids, e.g. "hr.people.salary"
    categories: list[str] = Field(default_factory=list)
    category_hashes: dict[str, str] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    carrier: CarrierKind = CarrierKind.IN_PROCESS
    host_id: Optional[str] = None
    cost: float = 1.0
    backing: Literal["deterministic", "llm_backed"] = "llm_backed"
    grant: Optional[InterAgentGrant] = None
    bid: Optional[dict[str, float]] = None                       # fixed-price Contract Net bid: cost/time/confidence

class CapabilityMatch(BaseModel):
    agent_name: str
    cap_id: str
    locality: Locality
    cost: float
    kind: str                                                    # "local" | "a2a" | "squawk" (FEAT-746 U2)
    backing: str
    score: float
```

```python
# parrot/roost/blackboard.py
class BlackboardKey(str, Enum):
    ROSTER = "roster"; DEFINITIONS = "definitions"; TASKS = "tasks"; DIGEST = "digest"; ARTIFACTS = "artifacts"

class KeyACL(BaseModel):
    readers: list[str] = Field(default_factory=lambda: ["*"])
    writer: str                                                  # single writer per key

class BlackboardEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    key: str
    value: Any
    version: int
    writer: str
    acl: KeyACL
    updated_at: datetime
    provenance: dict[str, Any] = Field(default_factory=dict)    # digest items carry trace_id + message_id
```

```python
# parrot/roost/scoring.py
class Bid(BaseModel):
    agent_name: str
    cost: float
    time_ms: float
    confidence: float
    message_id: str

class Award(BaseModel):
    winner: Optional[Bid]
    decided_by: Literal["rule", "llm"]
    rejected: list[Bid]
```

```python
# parrot/roost/audit.py
class RoostAuditEntry(BaseModel):
    entry_id: str
    direction: Literal["served", "received"]
    sender: str
    receiver: str
    performative: Performative
    protocol: InteractionProtocol
    conversation_id: str
    message_id: str
    trace_id: Optional[str]
    result_digest: Optional[str]            # sha256 of canonical content, None for by-reference objects without a handle
    body: Optional[str]                     # Matrix human rendering, when present
    signature: str = ""
    created_at: datetime
```

### New Public Interfaces

```python
from parrot.roost import (
    Performative, InteractionProtocol, FailureCode, RoostMessage, AgentAddress,
    ProtocolEngine, ConversationBudget, GatingDispatcher, HandlerRegistry, DispatchDecision,
    RoostAgentConfig, InterAgentGrant, GrantPolicy, CapabilityMatch, Locality,
    Blackboard, InMemoryBlackboard, BlackboardKey, StaleWriteError, WriterDeniedError,
    Carrier, CarrierKind, InProcessCarrier, SharedMemoryCarrier, EventBusCarrier,
    RoostAuditLedger, RoostEndpoint, RoostToolkit, FixedWeightScorer, BidScorer,
)
from parrot.integrations.matrix.roost import MatrixCarrier, MatrixBlackboard

# Registration (decorator and YAML)
@register_agent("hr-agent", roost=RoostAgentConfig(capabilities=["hr.people.salary"], backing="deterministic",
                                                   grant=InterAgentGrant(scopes=["hr.*"])))
class HRAgent(Agent): ...

# Directory lookup (harness-side, no tokens)
matches = agent_registry.find_capability("salary", caller="agent-a")      # list[CapabilityMatch], ranked

# Endpoint
endpoint = RoostEndpoint(agent_name="agent-a", config=cfg, engine=ProtocolEngine(), dispatcher=..., carriers={...})
result = await endpoint.request("hr.people.salary", {"employee_id": "E-17"}, timeout=5.0)   # native object
await endpoint.inform(receivers=[AgentAddress(name="agent-b", carrier=CarrierKind.IN_PROCESS)], content=obj)
award = await endpoint.cfp(capability_filter="docs.*", task=spec, bid_window_ms=500)
sub_id = await endpoint.subscribe(blackboard_key=BlackboardKey.DIGEST)
```

---

## 3. Module Breakdown

> Each module maps to one or more Task Artifacts in Phase 2. Paths are relative to the distribution's `src/`.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Performatives & message model | yes | enums, `OBLIGATIONS` table and `RoostMessage` fields fixed in §2 Data Models; `EnvelopeLike` Protocol fields fixed | — |
| M2: Protocol engine | yes | five machines, state labels, terminal states, `Transition` contract and budget rules fixed (§3 M2) | — |
| M3: Capability directory | yes | `ResourceType.AGENT`, `find_exact` signature, ranking key `(locality, cost, -score)`, `RoostAgentConfig` fields fixed | — |
| M4: Inter-agent grant | yes | glob-scope semantics (`fnmatch`), fail-closed when `grant is None` | — |
| M5: Gating dispatcher | yes | three-step order and `DispatchDecision` values fixed; handler registry keyed by `content_type` | — |
| M6: Blackboard | yes | CAS on `expected_version`, `WriterPolicy` table, subscribe ⇒ `inform` fixed | — |
| M7: Carrier base + in-process | yes | `Carrier` ABC, per-address `asyncio.Queue`, by-reference contract | — |
| M8: Same-host shm carrier | yes | reuse `encode_dataframe` / `decode_dataframe_from_shm` / `unlink_shm`; ownership rule fixed | — |
| M9: Event-bus carrier + codec | yes | `EnvelopeCodec` protocol (sync `encode`/`decode`, `content_type`) and `JsonEnvelopeCodec` fixed (Q2); topic layout, metadata keys and dedup fixed | — |
| M10: Roost audit ledger | yes | entry schema fixed; `AbstractKMSSigner` reuse; canonical bytes = sorted-key JSON of the entry minus `signature` | — |
| M11: Endpoint, toolkit, origin-tool map, `squawk_bridge`, `AgentTool` | yes | lazy satellite probe + degrade-to-empty contract fixed (Q1); token-over-context rule fixed (Q3); the satellite's real import path is read from one constant in `squawk_bridge.py` | — |
| M12: Matrix carrier, room-state blackboard, `ask_agent` subsumption | yes | event types, content models and `ask_agent` routing fixed (§3 M12) | — |
| M13: Spike gates L-S1…L-S6 + docs | yes | pass criteria fixed by the brainstorm table; L-S6 opt-in env var fixed (`PARROT_TEST_MATRIX=1`) | — |

### Module 1: Performatives & message model
- **Path**: `parrot/roost/__init__.py`, `parrot/roost/performatives.py`, `parrot/roost/messages.py` (new, `ai-parrot`)
- **Responsibility**: the twelve acts, five protocol names, failure codes, the `OBLIGATIONS` table (reply owed / allowed replies / wake rule, verbatim from the brainstorm), `AgentAddress`, `RoostMessage`, the `EnvelopeLike` structural seam and the `ORIGIN_TOOL_MAP`.
- **Depends on**: `TraceContext` (verified `parrot/core/events/lifecycle/__init__.py:18`), `CarrierKind` (M7 — defined in M1 to avoid a cycle; M7 imports it).
- **Interface Skeleton**:
  ```python
  # parrot/roost/performatives.py  (new)
  class Performative(str, Enum): ...            # 12 values, §2 Data Models
  class InteractionProtocol(str, Enum): ...     # 5 values
  class FailureCode(str, Enum): ...             # 9 values
  class CarrierKind(str, Enum):
      IN_PROCESS = "in_process"; SAME_HOST = "same_host"; NETWORK = "network"; MATRIX = "matrix"
  class ReplyObligation(BaseModel): ...
  OBLIGATIONS: Final[dict[Performative, ReplyObligation]]
  ORIGIN_TOOL_MAP: Final[dict[str, Performative]] = {
      "report": Performative.INFORM, "ask_agent": Performative.QUERY, "call_for_proposals": Performative.CFP,
      "watch": Performative.SUBSCRIBE,   # mounted capability tools map to REQUEST by the toolkit, not by name
  }
  def obligation_for(performative: Performative) -> ReplyObligation:
      """Return the reply obligation and wake rule for *performative* (never raises)."""

  # parrot/roost/messages.py  (new)
  class EnvelopeLike(Protocol): ...             # §2 Data Models
  class LocalEnvelope(BaseModel): ...           # §2 Data Models — Roost's own envelope when the Squawk satellite is absent (Q1)
  class AgentAddress(BaseModel): ...
  class FailureInfo(BaseModel): ...
  class RoostMessage(BaseModel):
      """One Roost speech act riding one Squawk envelope. ``content`` is by reference; ``body`` is for humans."""
      def reply(self, performative: Performative, *, content: Any = None, body: Optional[str] = None,
                failure: Optional[FailureInfo] = None) -> "RoostMessage":
          """Build the reply: same conversation_id/protocol/envelope, ``in_reply_to=self.message_id``, sender/receivers swapped.
          Raises ValueError when *performative* is not in ``obligation_for(self.performative).allowed_replies``."""
      def is_addressed_to(self, name: str) -> bool:
          """True when *name* is in ``receivers``; False for capability-filtered broadcasts."""
      def trace_id(self) -> Optional[str]:
          """``envelope.trace.trace_id`` when present, else None."""
  ```

### Module 2: Protocol engine
- **Path**: `parrot/roost/protocols.py`, `parrot/roost/scoring.py` (new)
- **Responsibility**: one deterministic state machine per `conversation_id` for Inform, Request, Query, Contract Net and Subscribe; `ConversationBudget` enforcement (hop limit → `failure(HOP_LIMIT)`, token budget → `failure(TOKEN_BUDGET)`, deadline → `failure(TIMEOUT)` to the requester); `not_understood` for out-of-state messages; closed conversations accept nothing; Contract Net bid window and scoring (`FixedWeightScorer` default, `BidScorer` override per channel; `Award.decided_by="llm"` only when the rule cannot decide, i.e. a tie within `tie_epsilon`).
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/roost/protocols.py  (new)
  class TerminalState(str, Enum): ...
  class ConversationBudget(BaseModel): ...
  class ConversationState(BaseModel): ...
  class Transition(BaseModel): ...

  class ProtocolMachine(ABC):
      """State machine for one InteractionProtocol. Pure: no I/O, no clock reads (the engine passes ``now``)."""
      protocol: ClassVar[InteractionProtocol]
      @abstractmethod
      def initial_state(self, opener: RoostMessage) -> str: ...
      @abstractmethod
      def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition: ...

  class InformMachine(ProtocolMachine): ...        # inform → DONE
  class RequestMachine(ProtocolMachine): ...       # request → agree|refuse → inform|failure ; terminal INFORMED/REFUSED/FAILED/CANCELLED/TIMED_OUT
  class QueryMachine(ProtocolMachine): ...         # query → inform|failure
  class ContractNetMachine(ProtocolMachine): ...   # cfp → N×(propose|refuse) → accept + rejects → RequestMachine ; AWARDED/NO_BIDS/CANCELLED
  class SubscribeMachine(ProtocolMachine): ...     # subscribe → N×inform → cancel ; CANCELLED/EXPIRED

  class ProtocolEngine:
      """Owns ConversationState per conversation_id and applies the machines deterministically."""
      def __init__(self, *, default_hop_limit: int = 8, scorer: Optional["BidScorer"] = None,
                   tie_epsilon: float = 1e-6, clock: Callable[[], datetime] = _utcnow) -> None: ...
      def open(self, opener: RoostMessage, *, budget: Optional[ConversationBudget] = None) -> ConversationState:
          """Create state for ``opener.conversation_id``; budget defaults from ``opener.envelope`` (budget_ms, token_budget).
          Raises ConversationExistsError when the id is already open."""
      def accept(self, msg: RoostMessage, *, hops: int = 0) -> Transition:
          """Apply *msg* to its conversation. Unknown/closed conversation or out-of-state act ⇒ ``kind="not_understood"``
          with a ``not_understood`` reply in ``emit``; hop/token budget exceeded ⇒ ``kind="closed"`` with failure(HOP_LIMIT|TOKEN_BUDGET).
          Never raises on protocol errors."""
      def charge(self, conversation_id: str, tokens: int) -> Optional[Transition]:
          """Consume LLM tokens from the budget; returns a closing Transition with failure(TOKEN_BUDGET) when exhausted."""
      def expire(self, *, now: Optional[datetime] = None) -> list[Transition]:
          """Close every conversation past its deadline or bid window; emits failure(TIMEOUT) to the initiator / NO_BIDS awards."""
      def award(self, conversation_id: str) -> Award:
          """Score the collected proposals with the scorer; ``decided_by="llm"`` when the rule cannot decide."""
      def state(self, conversation_id: str) -> Optional[ConversationState]: ...
      def close(self, conversation_id: str, terminal: TerminalState, *, reason: str = "") -> Transition: ...

  # parrot/roost/scoring.py  (new)
  class Bid(BaseModel): ...
  class Award(BaseModel): ...
  class BidScorer(Protocol):
      def score(self, bid: Bid) -> float:
          """Higher is better. Must be deterministic for a given bid."""
  class FixedWeightScorer:
      """score = w_conf*confidence - w_cost*cost_norm - w_time*time_norm with weights (0.5, 0.3, 0.2) by default."""
      def __init__(self, *, w_confidence: float = 0.5, w_cost: float = 0.3, w_time: float = 0.2) -> None: ...
      def score(self, bid: Bid) -> float: ...
  ```

### Module 3: Capability directory
- **Path**: modifies `parrot/registry/capabilities/models.py:32`, `parrot/registry/capabilities/registry.py:42,183`, `parrot/registry/registry.py:69,255,538,1450`, `parrot/registry/__init__.py:2`; new `parrot/roost/directory.py`
- **Responsibility**: `ResourceType.AGENT`; a synchronous exact-match index (cap id, category, keyword → entries) beside the embedding matrix; `RoostAgentConfig` advertised on `BotMetadata.roost` / `BotConfig.roost` and accepted by `register(roost=...)` / `register_bot_decorator(roost=...)`; `AgentRegistry.find_capability` ranking by `(locality, cost, -score)` and fronting FEAT-746's remote entries (`kind` field) so there is no fifth directory. Embedding `search()` stays the fallback when the exact index returns nothing and an embedding fn is configured.
- **Depends on**: M1 (`CarrierKind`); FEAT-746 U2 `kind` field (soft: `kind` is read via `getattr(metadata, "kind", "local")` until FEAT-746 merges).
- **Interface Skeleton**:
  ```python
  # parrot/registry/capabilities/models.py  (modifies :32 — add after VECTOR_COLLECTION)
  class ResourceType(str, Enum):             # verified: parrot/registry/capabilities/models.py:25
      AGENT = "agent"                        # FEAT-747: a registered agent's advertised capability

  # parrot/registry/capabilities/registry.py  (modifies :42 __init__ tail, :183 before search)
  class CapabilityRegistry:                  # verified: parrot/registry/capabilities/registry.py:19
      def register_agent_capability(self, agent_name: str, cap_id: str, *, keywords: Sequence[str] = (),
                                    category: Optional[str] = None, locality: int = 3, cost: float = 1.0,
                                    backing: str = "llm_backed", kind: str = "local",
                                    metadata: Optional[dict[str, Any]] = None) -> None:
          """Register one AGENT entry (name=f"{agent_name}::{cap_id}") and index cap_id/category/keywords exactly."""
      def unregister_agent(self, agent_name: str) -> int:
          """Drop every AGENT entry of *agent_name*; returns the count removed."""
      def find_exact(self, query: str, *, resource_types: Optional[list[ResourceType]] = None,
                     limit: int = 10) -> list[CapabilityEntry]:
          """Synchronous, embedding-free lookup: exact cap_id, glob cap_id ("hr.people.*"), category or keyword
          (case-insensitive). No I/O; target < 5 ms for 1 000 entries (gate L-S3)."""

  # parrot/registry/registry.py  (modifies :69 BotMetadata, :255 BotConfig, :538 register(), :1324 decorator, :1450 after get_bots_by_tag)
  class BotMetadata:                          # verified: parrot/registry/registry.py:50
      roost: Optional["RoostAgentConfig"] = None   # FEAT-747: Roost contract advert + carrier + grant
  class BotConfig(BaseModel):                 # verified: parrot/registry/registry.py:227
      roost: Optional["RoostAgentConfig"] = Field(default=None)
  class AgentRegistry:                        # verified: parrot/registry/registry.py:258
      def register(self, name, factory, *, ..., bot_config=None, roost: Optional["RoostAgentConfig"] = None, **kwargs) -> None:
          """Unchanged behaviour plus: store *roost* (or ``bot_config.roost``) on the metadata and mirror its
          capabilities into ``self.capability_registry`` via register_agent_capability()."""
      def register_bot_decorator(self, *, ..., roost: Optional["RoostAgentConfig"] = None, **kwargs): ...
      def find_capability(self, query: str, *, caller: Optional[str] = None, limit: int = 5,
                          include_remote: bool = True) -> list["CapabilityMatch"]:
          """Deterministic directory lookup: exact index first, ranked by (locality, cost, -score). When *caller* is given,
          entries outside the caller's InterAgentGrant scopes are filtered out (fail-closed: no grant ⇒ empty).
          Never calls an LLM or an embedding fn."""
      @property
      def capability_registry(self) -> "CapabilityRegistry":
          """Lazily created FEAT-070 registry used as the Roost directory index."""

  # parrot/roost/directory.py  (new)
  class Locality(IntEnum): ...
  class InterAgentGrant(BaseModel): ...
  class RoostAgentConfig(BaseModel): ...
  class CapabilityMatch(BaseModel): ...
  def locality_of(config: Optional[RoostAgentConfig], *, kind: str, local_host_id: Optional[str]) -> Locality:
      """IN_PROCESS for a local entry on the same registry; SAME_HOST when host_id matches; SAME_NETWORK for NETWORK/MATRIX carriers; REMOTE for a2a/squawk."""
  def rank(matches: Iterable[CapabilityMatch]) -> list[CapabilityMatch]:
      """Stable sort by (locality, cost, -score)."""
  ```

### Module 4: Inter-agent grant
- **Path**: `parrot/roost/grant.py` (new)
- **Responsibility**: the caller-side deterministic gate. `GrantPolicy.allows(caller_config, cap_id)` uses `fnmatch` over `InterAgentGrant.scopes`; no grant ⇒ denied (fail-closed); never exposed as a tool parameter. Delegation attenuation: an agent awarded a Contract Net task receives a scope no wider than the requester's (`attenuate(requester_scopes, awardee_scopes)` = intersection). The serving side relies on `PBACToolCallGuardrail` with the travelling `PermissionContext`; nothing here replaces it.
- **Depends on**: M3 (`InterAgentGrant`, `RoostAgentConfig`).
- **Interface Skeleton**:
  ```python
  # parrot/roost/grant.py  (new)
  class GrantDenied(Exception):
      """Raised by RoostEndpoint when a lookup/mount/send targets a capability outside the caller's grant."""
  class GrantPolicy:
      def __init__(self, *, default_deny: bool = True) -> None: ...
      def allows(self, config: Optional[RoostAgentConfig], cap_id: str) -> bool:
          """True iff some scope in ``config.grant.scopes`` fnmatch-es *cap_id*; False when config or grant is None."""
      def attenuate(self, requester: Optional[InterAgentGrant], awardee: Optional[InterAgentGrant]) -> InterAgentGrant:
          """Scopes the awardee may use for the awarded task: patterns of *awardee* that are covered by a pattern of *requester*."""
      def filter_matches(self, config: Optional[RoostAgentConfig], matches: Iterable[CapabilityMatch]) -> list[CapabilityMatch]: ...
  ```

### Module 5: Gating dispatcher
- **Path**: `parrot/roost/gating.py` (new)
- **Responsibility**: the three questions per inbound message, in order and without an LLM — addressing (named receiver, or capability filter matched against the agent's own `RoostAgentConfig.capabilities`; anything else in a shared channel is `IGNORE`), protocol state (`engine.accept`; `NOT_UNDERSTOOD` reply emitted), decision needed (`RUN_TOOL` for a `request`/`query` on a deterministic capability; `STORE` for an `inform` with no handler or a handler that does not need a decision; `WAKE_LLM` for an addressed `inform` (resolved: wake if addressed directly), an `inform` whose handler asks for a decision, a `request` on an llm_backed capability, or a `cfp` that needs judgement; `BID_FROM_CONTRACT` for a `cfp` on a fixed-price capability; `REPLAN` for a `failure` delivered to the requester). Loop termination by construction: no obligation on `inform`/`agree`/`refuse`/`failure`/`accept`/`reject`. Every wake charges `engine.charge`.
- **Depends on**: M1, M2, M3, M4.
- **Interface Skeleton**:
  ```python
  # parrot/roost/gating.py  (new)
  class DispatchDecision(str, Enum):
      IGNORE = "ignore"; NOT_UNDERSTOOD = "not_understood"; RUN_TOOL = "run_tool"; STORE = "store"
      WAKE_LLM = "wake_llm"; BID_FROM_CONTRACT = "bid_from_contract"; REPLAN = "replan"; CLOSED = "closed"
  class Handler(Protocol):
      async def __call__(self, msg: RoostMessage) -> Optional[Any]: ...
  class HandlerRegistry:
      """Handlers keyed by ``content_type`` (dotted class name or media type, "*" wildcard)."""
      def register(self, content_type: str, handler: Handler, *, needs_decision: bool = False) -> None: ...
      def resolve(self, content_type: Optional[str]) -> Optional[tuple[Handler, bool]]: ...
  class Dispatch(BaseModel):
      decision: DispatchDecision
      transition: Optional[Transition] = None
      emit: list[RoostMessage] = Field(default_factory=list)
      handler: Any = None
  class GatingDispatcher:
      def __init__(self, *, self_name: str, config: Optional[RoostAgentConfig], engine: ProtocolEngine,
                   handlers: HandlerRegistry, grant: GrantPolicy) -> None: ...
      def addressed(self, msg: RoostMessage) -> bool:
          """Step 1: named in receivers, or capability_filter fnmatch-es one of our capabilities."""
      def dispatch(self, msg: RoostMessage, *, hops: int = 0) -> Dispatch:
          """Steps 1–3 as one pure call; the endpoint executes the decision. Records ``wakes`` for the L-S1 metric."""
      @property
      def wakes(self) -> int: ...
  ```

### Module 6: Blackboard
- **Path**: `parrot/roost/blackboard.py` (new); modifies `parrot/bots/flows/core/context.py:112`
- **Responsibility**: the abstract `Blackboard` (get / put with compare-and-swap on `expected_version` / subscribe / unsubscribe / `render_prefix`), `InMemoryBlackboard`, `WriterPolicy` (`roster` and `definitions` by the harness, `tasks` by the protocol engine, `digest` by the coordinator else the last agent that closed a Request — resolved —, `artifacts` by the producer of the handle), `StaleWriteError` (never merged), `WriterDeniedError`, ACL enforcement, and the subscribe ⇒ `inform` bridge (exactly one `inform` per subscriber per accepted write). `render_prefix()` is the stable prompt prefix (rendered blackboard first in every prompt for provider prompt caching). `FlowContext` gains an optional `blackboard` binding; `shared_data` is unchanged.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/roost/blackboard.py  (new)
  class BlackboardKey(str, Enum): ...
  class KeyACL(BaseModel): ...
  class BlackboardEntry(BaseModel): ...
  class StaleWriteError(Exception): ...
  class WriterDeniedError(Exception): ...
  class ReadDeniedError(Exception): ...
  Subscriber = Callable[[RoostMessage], Awaitable[None]]
  class WriterPolicy:
      def __init__(self, *, harness: str = "harness", engine: str = "engine", coordinator: Optional[str] = None) -> None: ...
      def owner_of(self, key: str, *, last_request_closer: Optional[str] = None, producer: Optional[str] = None) -> str:
          """Single writer for *key*; ``digest`` → coordinator or last_request_closer; ``artifacts`` → producer."""
      def record_request_closed(self, agent_name: str) -> None:
          """Ownership of ``digest`` moves with the work (resolved: last closer owns it)."""
  class Blackboard(ABC):
      def __init__(self, *, scope: str, policy: WriterPolicy) -> None: ...
      @abstractmethod
      async def get(self, key: str, *, reader: str) -> Optional[BlackboardEntry]:
          """Raises ReadDeniedError when *reader* is not in the key's ACL."""
      @abstractmethod
      async def put(self, key: str, value: Any, *, writer: str, expected_version: Optional[int],
                    acl: Optional[KeyACL] = None, provenance: Optional[dict[str, Any]] = None) -> BlackboardEntry:
          """CAS write: version must equal *expected_version* (None ⇒ create). Raises StaleWriteError / WriterDeniedError.
          Exactly one ``inform`` (content=BlackboardEntry) is delivered to each subscriber of *key* on success."""
      async def subscribe(self, key: str, subscriber: Subscriber, *, subscriber_name: str) -> str: ...
      async def unsubscribe(self, subscription_id: str) -> bool: ...
      async def keys(self, *, reader: str) -> list[str]: ...
      def render_prefix(self, *, reader: str, keys: Sequence[str] = ("roster", "definitions", "tasks", "digest")) -> str:
          """Deterministic, stable text rendering for prompt-cache-friendly prefixes."""
  class InMemoryBlackboard(Blackboard): ...

  # parrot/bots/flows/core/context.py  (modifies :112 — add after trace_context)
  class FlowContext:                          # verified: parrot/bots/flows/core/context.py:56
      blackboard: Optional[Any] = field(default=None, repr=False)   # FEAT-747: optional Roost Blackboard binding; excluded from to_snapshot()
  ```

### Module 7: Carrier base + in-process carrier
- **Path**: `parrot/roost/carriers/__init__.py`, `parrot/roost/carriers/base.py`, `parrot/roost/carriers/inprocess.py` (new)
- **Responsibility**: the `Carrier` ABC (send / subscribe / unsubscribe / close, `kind`), delivery receipts, and the in-process fast path: one `asyncio.Queue` per registered address, the full `RoostMessage` object delivered **by reference** (no copy, no serialization; `content` identity preserved — gate L-S4 asserts `id(content)` equality and that a `pyarrow.Table` keeps its buffer address). A `CarrierError` hierarchy (`Undeliverable`, `CarrierClosed`).
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/roost/carriers/base.py  (new)
  class CarrierError(Exception): ...
  class Undeliverable(CarrierError): ...
  class CarrierClosed(CarrierError): ...
  Inbound = Callable[[RoostMessage], Awaitable[None]]
  class Carrier(ABC):
      kind: ClassVar[CarrierKind]
      @abstractmethod
      async def send(self, msg: RoostMessage) -> None:
          """Deliver to every address in ``msg.receivers`` (or every subscriber matching ``capability_filter``). Raises Undeliverable."""
      @abstractmethod
      async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str: ...
      @abstractmethod
      async def unsubscribe(self, subscription_id: str) -> bool: ...
      @abstractmethod
      async def close(self) -> None: ...

  # parrot/roost/carriers/inprocess.py  (new)
  class InProcessCarrier(Carrier):
      """asyncio.Queue per address; payloads by reference; shared by every RoostEndpoint in the process."""
      kind = CarrierKind.IN_PROCESS
      def __init__(self, *, maxsize: int = 1024) -> None: ...
      async def send(self, msg: RoostMessage) -> None: ...
      async def subscribe(self, address, inbound, *, capabilities=()) -> str: ...
      async def unsubscribe(self, subscription_id: str) -> bool: ...
      async def close(self) -> None: ...
      def pending(self, name: str) -> int:
          """Queue depth for *name* (tests and the L-S1 metric)."""
  ```

### Module 8: Same-host shared-memory carrier
- **Path**: `parrot/roost/carriers/shm.py` (new)
- **Responsibility**: Arrow IPC over `multiprocessing.shared_memory` for `pandas.DataFrame` / `pyarrow.Table` content between processes on one host, reusing the repl_worker transport's ownership rules (sender creates the segment, receiver decodes and ACKs, sender unlinks after ACK; no pickle across sandbox boundaries). Non-frame content goes by handle (FEAT-746 blob store) or, for small Pydantic models, as `model_dump()` inside the envelope. Signalling rides an `InProcessCarrier`-compatible local queue or the bus carrier; this module owns only the payload leg.
- **Depends on**: M7; `encode_dataframe` (verified `parrot/tools/repl_worker/transport.py:83`), `decode_dataframe_from_shm` (`:266`), `unlink_shm` (`:300`).
- **Interface Skeleton**:
  ```python
  # parrot/roost/carriers/shm.py  (new)
  class ShmPayloadRef(BaseModel):
      shm_name: str; size: int; schema_digest: str; rows: int
  class SharedMemoryCarrier(Carrier):
      """Same-host carrier: frames as Arrow IPC in shared memory, everything else by handle."""
      kind = CarrierKind.SAME_HOST
      def __init__(self, *, signal: Carrier, max_bytes: Optional[int] = None) -> None: ...
      async def send(self, msg: RoostMessage) -> None:
          """Encode frame content with encode_dataframe(); replace ``content`` by ShmPayloadRef; deliver over *signal*."""
      async def subscribe(self, address, inbound, *, capabilities=()) -> str:
          """Wrap *inbound* so a ShmPayloadRef is decoded (decode_dataframe_from_shm) and ACKed before the handler runs."""
      async def ack(self, ref: ShmPayloadRef) -> None:
          """Receiver ACK ⇒ sender unlink_shm(); idempotent."""
      async def unsubscribe(self, subscription_id: str) -> bool: ...
      async def close(self) -> None:
          """Unlink every segment still owned by this sender."""
  ```

### Module 9: Event-bus carrier + envelope codec
- **Path**: `parrot/roost/codec.py`, `parrot/roost/carriers/bus.py` (new)
- **Responsibility**: the sync `EnvelopeCodec` protocol and Roost's `JsonEnvelopeCodec` (Q2: encodes the `EnvelopeLike` fields plus the Roost fields; `content` is encoded only when it is a Pydantic model, a JSON-able value or a handle id — frames and arbitrary objects must already have been turned into a handle or `content_ref`, otherwise `encode` raises `UnencodableContent`); the satellite's `CapnpEnvelopeCodec` implements the same protocol and is selected by `squawk_bridge.load_codec()` when available. The carrier itself is the default same-network carrier on a **dedicated** `navigator_eventbus.EventBus` instance (FEAT-710 idiom: Streams transport, outbox, `event_id` dedup; config keys `PARROT_ROOST_BUS_URL` / `PARROT_ROOST_BUS_PREFIX`, never the telemetry instance). Topic layout `roost.<agent_name>` for addressed traffic, `roost.cap.<category>` for capability-filtered broadcasts, `roost.dlq` dead-letter. Mapping `RoostMessage` → `Event(event_type, payload={"codec": codec.content_type, "data": <bytes as base64 str>}, correlation_id=envelope.correlation_id, metadata={"reply_to": "roost.<sender>", "idempotency_key": ..., "trace": ..., "performative": ..., "conversation_id": ..., "auth_token": ...})`. Idempotent receive by `idempotency_key` (LRU set). Content on this carrier is a handle or a serialized typed object, never JSON text in `body`. Serialized `permission_context` and `auth_token` both travel (Q3).
- **Depends on**: M7. No FEAT-746 gate (Q1/Q2): the JSON codec and `LocalEnvelope` make the carrier self-sufficient.
- **Interface Skeleton**:
  ```python
  # parrot/roost/codec.py  (new)
  class UnencodableContent(ValueError): ...
  class EnvelopeCodec(Protocol): ...            # §2 Data Models
  class JsonEnvelopeCodec:
      """Roost's fallback codec (content_type "application/json"); round-trips LocalEnvelope and any EnvelopeLike by its fields."""
      content_type = "application/json"
      def encode(self, msg: RoostMessage) -> bytes: ...
      def decode(self, data: bytes) -> RoostMessage:
          """Rebuilds a LocalEnvelope; the satellite codec rebuilds the Squawk envelope."""

  # parrot/roost/carriers/bus.py  (new)
  class EventBusCarrier(Carrier):
      kind = CarrierKind.NETWORK
      def __init__(self, bus: "EventBus", *, topic_prefix: str = "roost", dlq_topic: str = "roost.dlq",
                   codec: Optional[EnvelopeCodec] = None, dedup_size: int = 10_000) -> None:
          """*bus* must be a dedicated instance (validated like fanout._validate_bus: Streams transport).
          *codec* defaults to squawk_bridge.load_codec() → JsonEnvelopeCodec when the satellite is absent."""
      async def send(self, msg: RoostMessage) -> None: ...
      async def subscribe(self, address, inbound, *, capabilities=()) -> str:
          """bus.subscribe(f"{prefix}.{address.name}") plus one pattern per capability category."""
      async def unsubscribe(self, subscription_id: str) -> bool: ...
      async def close(self) -> None: ...
      @staticmethod
      def to_event(msg: RoostMessage, *, codec: EnvelopeCodec, prefix: str) -> "Event": ...
      @staticmethod
      def from_event(event: "Event", *, codecs: Mapping[str, EnvelopeCodec]) -> RoostMessage:
          """Selects the codec by payload["codec"]; unknown content_type ⇒ routed to the DLQ, never raised into the handler."""
  def build_roost_bus() -> "EventBus":
      """Dedicated publish+subscribe Streams bus from PARROT_ROOST_BUS_* (navconfig with env fallback), outbox enabled."""
  ```

### Module 10: Roost audit ledger
- **Path**: `parrot/roost/audit.py` (new)
- **Responsibility**: one signed `RoostAuditEntry` per performative, `direction="served"` on the receiving endpoint and `direction="received"` on the sender, joined by `trace_id`; sibling of `AuditLedger` sharing `AbstractKMSSigner` / `LocalHMACSigner` (verified `parrot/security/audit_ledger.py:135,166`) — `AuditLedger.append()` is **not** reused because it requires `credential_material`. Canonical bytes: UTF-8 of `json.dumps(entry.model_dump(mode="json", exclude={"signature"}), sort_keys=True, separators=(",", ":"))`. Storage: in-memory dict plus an optional async `storage` sink with the same duck-typed `store(entry)` contract `AuditLedger` uses. On Matrix the human `body` is part of the entry.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/roost/audit.py  (new)
  class RoostAuditEntry(BaseModel):
      def canonical_bytes(self) -> bytes: ...
  class RoostAuditLedger:
      def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None) -> None: ...
      async def record(self, msg: RoostMessage, *, direction: Literal["served", "received"], self_name: str) -> RoostAuditEntry:
          """Build, sign and persist the entry for *msg*; result_digest = sha256 of canonical content when it is JSON-able or a handle id."""
      async def verify(self, entry: RoostAuditEntry) -> bool: ...
      def entries(self, *, conversation_id: Optional[str] = None, trace_id: Optional[str] = None) -> list[RoostAuditEntry]: ...
  ```

### Module 11: Endpoint, toolkit, origin-tool mapping, Squawk bridge and `AgentTool` integration
- **Path**: `parrot/roost/squawk_bridge.py`, `parrot/roost/endpoint.py`, `parrot/roost/toolkit.py` (new); modifies `parrot/tools/agent.py:157`
- **Responsibility**: `squawk_bridge` is the **only** place that names the satellite (one `SQUAWK_MODULE` constant, provisionally `"parrot.squawk"`): `squawk_available()`, `load_codec()` (satellite `CapnpEnvelopeCodec` else `JsonEnvelopeCodec`), `new_envelope(...)` (satellite envelope else `LocalEnvelope`), `mount_capabilities(tool_manager, matches)` (satellite `catalog.mount` else `[]` + one warning per process — Q1: degrade, never fail). `RoostEndpoint` composes engine, dispatcher, carriers, blackboard, ledger and the agent's `ToolManager`: inbound loop (`carrier.subscribe` → `dispatcher.dispatch` → execute decision: `execute_tool(permission_context=resolve_authority(msg))` for `RUN_TOOL` where `resolve_authority` prefers `msg.auth_token` (Q3) and falls back to `msg.permission_context`, `store_result(..., data_type="auto")` for `STORE`, `bot.wake(msg)` callback for `WAKE_LLM`, fixed-price `propose` for `BID_FROM_CONTRACT`), outbound helpers (`send`, `inform`, `request`, `query`, `cfp`, `subscribe`, `cancel`), harness-side `find_and_mount(query)` = `find_capability` (grant-filtered) → `squawk_bridge.mount_capabilities` (planner pre-mount, no LLM turn) and the LLM-visible `RoostToolkit` (`send` with enum `inform|request|query|subscribe`, `report`, `call_for_proposals`, `watch`, `find_agents`). `AgentTool._execute` issues a `query` through the caller's endpoint when `self.agent` is Roost-enabled (the native answer is stored to WorkingMemory and a short pointer string is returned, keeping the `-> str` contract); otherwise unchanged.
- **Depends on**: M2, M3, M4, M5, M6, M7, M9 (codec), M10. The satellite is an optional runtime dependency probed lazily; it gates only the real mount (Q1).
- **Interface Skeleton**:
  ```python
  # parrot/roost/squawk_bridge.py  (new)
  SQUAWK_MODULE: Final[str] = "parrot.squawk"       # provisional; the FEAT-746 spec fixes it — change here only
  class SquawkUnavailable(RuntimeError): ...
  def squawk_available() -> bool:
      """importlib.util.find_spec(SQUAWK_MODULE) is not None; cached per process."""
  def load_codec() -> EnvelopeCodec:
      """Satellite CapnpEnvelopeCodec when available, else JsonEnvelopeCodec (Q2)."""
  def new_envelope(*, correlation_id: str, caller: str, trace: Optional[TraceContext] = None, budget_ms: Optional[int] = None,
                   token_budget: Optional[int] = None, idempotency_key: Optional[str] = None, auth_token: Optional[str] = None) -> Any:
      """Satellite envelope when available, else LocalEnvelope; both satisfy EnvelopeLike."""
  async def mount_capabilities(tool_manager: "ToolManager", matches: Sequence[CapabilityMatch]) -> list[str]:
      """Satellite catalog.mount per match → mounted tool names; without the satellite returns [] after one process-level warning (Q1)."""
  def resolve_authority(msg: RoostMessage) -> Any:
      """Q3: the PermissionContext derived from msg.auth_token when the satellite can verify it, else msg.permission_context; None ⇒ fail-closed in execute_tool."""

  # parrot/roost/endpoint.py  (new)
  WakeCallback = Callable[[RoostMessage, Dispatch], Awaitable[Optional[RoostMessage]]]
  class RoostEndpoint:
      def __init__(self, *, agent_name: str, config: Optional[RoostAgentConfig], engine: ProtocolEngine,
                   dispatcher: GatingDispatcher, carriers: Mapping[CarrierKind, Carrier], tool_manager: "ToolManager",
                   blackboard: Optional[Blackboard] = None, ledger: Optional[RoostAuditLedger] = None,
                   working_memory: Optional["WorkingMemoryToolkit"] = None, wake: Optional[WakeCallback] = None,
                   registry: Optional["AgentRegistry"] = None, grant: Optional[GrantPolicy] = None) -> None: ...
      async def start(self) -> None: ...
      async def stop(self) -> None: ...
      def address(self) -> AgentAddress: ...
      async def send(self, performative: Performative, *, receivers: Sequence[AgentAddress] = (), capability_filter: Optional[str] = None,
                     content: Any = None, protocol: Optional[InteractionProtocol] = None, conversation_id: Optional[str] = None,
                     in_reply_to: Optional[str] = None, body: Optional[str] = None, envelope: Any = None) -> RoostMessage:
          """Build, audit (received-side), route by receiver carrier and deliver. Raises GrantDenied / Undeliverable."""
      async def inform(self, *, receivers=(), capability_filter=None, content, body=None) -> RoostMessage: ...
      async def request(self, cap_id: str, args: Mapping[str, Any], *, timeout: Optional[float] = None, receiver: Optional[AgentAddress] = None) -> Any:
          """Request protocol end to end; returns the native result object; raises RoostFailure(FailureInfo) on refuse/failure/timeout."""
      async def query(self, question: Any, *, receiver: AgentAddress, timeout: Optional[float] = None, expected_schema: Optional[dict] = None) -> Any: ...
      async def cfp(self, *, capability_filter: str, task: Any, bid_window_ms: int = 500, scorer: Optional[BidScorer] = None) -> Award: ...
      async def subscribe(self, *, blackboard_key: Optional[str] = None, capability_filter: Optional[str] = None, handler: Optional[Handler] = None) -> str: ...
      async def cancel(self, conversation_id: str, *, reason: str = "") -> None: ...
      def register_handler(self, content_type: str, handler: Handler, *, needs_decision: bool = False) -> None: ...
      async def find_and_mount(self, query: str, *, limit: int = 5) -> list[str]:
          """Harness-side: registry.find_capability(query, caller=self.agent_name) → squawk_bridge.mount_capabilities → mounted tool names
          ([] with a warning when the Squawk satellite is absent — Q1)."""
      @property
      def metrics(self) -> dict[str, int]:
          """{'messages_in', 'messages_out', 'wakes', 'not_understood', 'stored'} for the L-S1/L-S2 gates."""
  class RoostFailure(Exception):
      def __init__(self, failure: FailureInfo) -> None: ...

  # parrot/roost/toolkit.py  (new)
  class RoostToolkit(AbstractToolkit):     # AbstractToolkit verified: parrot/tools/toolkit.py (exported parrot/tools/__init__.py:151)
      """LLM-facing origin tools; the harness maps each to a Performative via ORIGIN_TOOL_MAP. Never exposes the grant."""
      def __init__(self, endpoint: RoostEndpoint, **kwargs: Any) -> None: ...
      async def send(self, performative: Literal["inform", "request", "query", "subscribe"], receiver: str, content: str, body: Optional[str] = None) -> dict:
          """Generic send when no specific tool fits; ``content`` is parsed into the receiver's expected model when known."""
      async def report(self, receiver: str, fact: str) -> dict:
          """inform: fire-and-forget; returns {'status': 'sent', 'conversation_id': ...}; never waits for a reply."""
      async def call_for_proposals(self, capability_filter: str, task: str, bid_window_ms: int = 500) -> dict:
          """cfp over Contract Net; returns the Award (winner, decided_by) — 'delegate' is reserved by FEAT-590."""
      async def watch(self, key: str) -> dict:
          """subscribe to a blackboard key; key changes arrive as inform."""
      async def find_agents(self, query: str) -> list[dict]:
          """Directory lookup (no LLM); results are grant-filtered CapabilityMatch dicts."""

  # parrot/tools/agent.py  (modifies :157 _execute)
  class AgentTool(AbstractTool):          # verified: parrot/tools/agent.py:52
      async def _execute(self, **kwargs) -> str:
          """Unchanged for non-Roost agents. When ``getattr(self.agent, 'roost_endpoint', None)`` is set and the target advertises
          a RoostAgentConfig, run endpoint.query(...) and return a pointer string to the WorkingMemory entry holding the native answer."""
  ```

### Module 12: Matrix carrier, room-state blackboard, `ask_agent` subsumption
- **Path**: `parrot/integrations/matrix/roost/__init__.py`, `parrot/integrations/matrix/roost/carrier.py`, `parrot/integrations/matrix/roost/blackboard.py` (new, `ai-parrot-integrations`); modifies `parrot/integrations/matrix/events.py:41,283`, `parrot/integrations/matrix/crew/swarm_toolkit.py:53,89`
- **Responsibility**: `m.parrot.roost` message event whose `content` carries the structured Roost fields plus the serialized envelope and whose `body` is the **mandatory** human-readable rendering (ordinary clients show readable text — gate L-S6); `m.relates_to`/`m.in_reply_to` set from `in_reply_to`; `m.parrot.blackboard` **state** event with `state_key=<key>` (replace, not append; `version` field like `ChannelStateContent`); `MatrixCarrier` over `MatrixClientWrapper.send_event` / `on_custom_event`; `MatrixBlackboard` over `set_room_state` / `get_room_state_event`; `AgentSwarmToolkit.ask_agent` routed through the endpoint as a Request (Query when `expected_schema` is None), seeding `ConversationBudget.hops` from `ctx.current_hops` and mapping engine failures back to the FEAT-463 status strings (`hop_limit`, `timeout`, `unknown_agent`, `schema_error`); tunnels remain the room topology. Content on Matrix is a handle id or `model_dump()` JSON (humans read it; resolved: JSON accepted only here).
- **Depends on**: M6, M7, M11.
- **Interface Skeleton**:
  ```python
  # parrot/integrations/matrix/events.py  (modifies :41 — add after TUNNEL; :283 — add after TunnelStateContent)
  class ParrotEventType:                       # verified: matrix/events.py:27
      ROOST = "m.parrot.roost"                 # FEAT-747 message event
      BLACKBOARD = "m.parrot.blackboard"       # FEAT-747 state event, state_key = blackboard key
  class RoostEventContent(BaseModel):
      """Content of m.parrot.roost. ``body`` is mandatory (humans read it); ``envelope`` holds the serialized Squawk envelope."""
      body: str
      performative: str; protocol: str; conversation_id: str; message_id: str
      in_reply_to: Optional[str] = None
      sender: str; receivers: List[str] = Field(default_factory=list); capability_filter: Optional[str] = None
      content: Optional[Dict[str, Any]] = None; content_ref: Optional[str] = None   # handle id
      envelope: Dict[str, Any] = Field(default_factory=dict)
      failure: Optional[Dict[str, Any]] = None
  class BlackboardStateContent(BaseModel):
      """Content of m.parrot.blackboard (state_key = key). Replaced, never accumulated."""
      key: str; value: Any; version: int; writer: str
      acl: Dict[str, Any] = Field(default_factory=dict); updated_at: datetime
      provenance: Dict[str, Any] = Field(default_factory=dict)

  # parrot/integrations/matrix/roost/carrier.py  (new)
  class MatrixCarrier(Carrier):
      kind = CarrierKind.MATRIX
      def __init__(self, client: "MatrixClientWrapper", *, room_id: str, agent_name: str, render: Optional[Callable[[RoostMessage], str]] = None) -> None: ...
      async def send(self, msg: RoostMessage) -> None:
          """client.send_event(room_id, ParrotEventType.ROOST, RoostEventContent(...).model_dump()); body rendered when msg.body is None."""
      async def subscribe(self, address, inbound, *, capabilities=()) -> str:
          """client.on_custom_event(ParrotEventType.ROOST, cb); cb filters by receivers/capability_filter before calling inbound."""
      async def unsubscribe(self, subscription_id: str) -> bool: ...
      async def close(self) -> None: ...
      @staticmethod
      def to_content(msg: RoostMessage, *, body: str) -> RoostEventContent: ...
      @staticmethod
      def from_content(content: Dict[str, Any], *, event_id: str) -> RoostMessage: ...

  # parrot/integrations/matrix/roost/blackboard.py  (new)
  class MatrixBlackboard(Blackboard):
      def __init__(self, client: "MatrixClientWrapper", *, room_id: str, policy: WriterPolicy) -> None: ...
      async def get(self, key, *, reader) -> Optional[BlackboardEntry]:   # get_room_state_event(room_id, BLACKBOARD, state_key=key)
      async def put(self, key, value, *, writer, expected_version, acl=None, provenance=None) -> BlackboardEntry:
          """Read-compare-set on the state event's ``version``; StaleWriteError when it moved. set_room_state(..., state_key=key)."""

  # parrot/integrations/matrix/crew/swarm_toolkit.py  (modifies :53 ask_agent, :89 tunnel.ask call)
  class AgentSwarmToolkit(AbstractToolkit):   # verified: matrix/crew/swarm_toolkit.py:24
      def __init__(self, ..., endpoint: Optional["RoostEndpoint"] = None, **kwargs) -> None: ...
      async def ask_agent(self, agent: str, question: str, expected_schema: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> dict:
          """When ``self._endpoint`` is set: Request/Query over the engine (hops from ctx.current_hops); engine failures map to the
          FEAT-463 status strings. Without an endpoint the FEAT-463 tunnel path is unchanged."""
  ```

### Module 13: Spike gates L-S1…L-S6 and documentation
- **Path**: `packages/ai-parrot/tests/roost/test_gate_ls1_wakes.py`, `test_gate_ls2_inform_no_reply.py`, `test_gate_ls3_directory_lookup.py`, `test_gate_ls4_by_reference.py`, `test_gate_ls5_single_writer.py`; `packages/ai-parrot-integrations/tests/test_matrix_roost_gate_ls6.py`; `docs/roost/README.md`, `docs/roost/performatives.md`, `docs/roost/carriers.md`
- **Responsibility**: the six brainstorm gates as executable acceptance tests with the brainstorm's pass criteria (§5 AC-20…AC-25); L-S6 runs only with `PARROT_TEST_MATRIX=1` against `docker-compose.matrix.yml` and is marked `integration`; docs describe the acts table, the protocols, gating, directory, blackboard, carriers and the FEAT-746 boundary.
- **Depends on**: M1–M12.
- **Interface Skeleton**: tests only; no new public symbols.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_obligations_table_complete` | M1 | every `Performative` has an `OBLIGATIONS` row; `reply()` rejects a disallowed act |
| `test_message_reply_threads_conversation` | M1 | `in_reply_to`, swapped sender/receivers, same envelope |
| `test_request_machine_happy_path` / `_refuse` / `_failure` | M2 | `request → agree → inform` terminal INFORMED; REFUSED; FAILED |
| `test_query_skips_agree` | M2 | `query → inform` |
| `test_out_of_state_not_understood` | M2 | `agree` without `request` ⇒ `not_understood` emitted, no LLM involvement |
| `test_closed_conversation_rejects` | M2 | any act after terminal ⇒ `not_understood` |
| `test_hop_limit_closes_with_failure` / `test_token_budget` / `test_timeout_expire` | M2 | typed `failure` codes, requester targeted |
| `test_contract_net_award_rule` / `_tie_wakes_llm` / `_no_bids` | M2 | fixed weights decide; tie ⇒ `decided_by="llm"`; empty window ⇒ NO_BIDS |
| `test_subscribe_cancel_expire` | M2 | Subscribe machine terminals |
| `test_resource_type_agent_added` | M3 | enum value and existing values untouched |
| `test_find_exact_capid_glob_keyword` | M3 | exact, glob and keyword hits; no embedding fn needed |
| `test_register_roost_config_mirrors_capabilities` | M3 | `register(roost=...)` populates the index; `unregister` drops entries |
| `test_find_capability_ranking` | M3 | `(locality, cost, -score)` order; remote entries after local |
| `test_find_capability_grant_filter` | M3/M4 | no grant ⇒ empty; scoped grant filters |
| `test_grant_fnmatch_and_attenuate` | M4 | `hr.*` covers `hr.people.salary`; attenuation is an intersection |
| `test_dispatch_addressed_request_deterministic` | M5 | `RUN_TOOL`, zero wakes |
| `test_dispatch_inform_addressed_wakes` / `_broadcast_stores` / `_handler_needs_decision` | M5 | resolved wake rules |
| `test_dispatch_cfp_fixed_price_bids` | M5 | `BID_FROM_CONTRACT` without a wake |
| `test_blackboard_cas_stale_refused` | M6 | second writer with old version ⇒ `StaleWriteError`, never merged |
| `test_blackboard_single_writer_policy` | M6 | `digest` owner moves to the last Request closer |
| `test_blackboard_subscribe_inform_once` | M6 | exactly one `inform` per subscriber per write |
| `test_blackboard_render_prefix_stable` | M6 | identical output for identical state |
| `test_flowcontext_blackboard_excluded_from_snapshot` | M6 | `to_snapshot()` unchanged |
| `test_inprocess_by_reference` | M7 | `id(content)` preserved across send/receive |
| `test_inprocess_capability_filter_fanout` | M7 | broadcast reaches matching subscribers only |
| `test_shm_roundtrip_and_unlink_after_ack` | M8 | frame decoded, segment unlinked once ACKed |
| `test_bus_event_mapping_reply_to_idempotency` | M9 | `correlation_id`, `metadata.reply_to`, dedup on replay |
| `test_bus_requires_dedicated_instance` | M9 | telemetry bus rejected |
| `test_json_codec_roundtrip` / `_rejects_unencodable_content` | M9 | `LocalEnvelope` + Roost fields round-trip; a frame without a handle raises `UnencodableContent` |
| `test_bus_unknown_codec_goes_to_dlq` | M9 | payload with an unregistered `codec` lands on `roost.dlq` |
| `test_bridge_degrades_without_squawk` | M11 | `squawk_available()` False ⇒ `JsonEnvelopeCodec`, `LocalEnvelope`, `mount_capabilities` returns `[]` with one warning |
| `test_bridge_selects_satellite_when_present` | M11 | a stub module at `SQUAWK_MODULE` is picked up for codec, envelope and mount |
| `test_resolve_authority_token_over_context` | M11 | token present ⇒ token-derived context; absent ⇒ `permission_context`; both absent ⇒ `None` (fail-closed) |
| `test_audit_entry_signed_and_verified` / `_joined_by_trace_id` | M10 | signer reuse; `entries(trace_id=...)` |
| `test_endpoint_request_roundtrip_native_result` | M11 | result is the object, not JSON text |
| `test_toolkit_origin_tool_map` | M11 | `report`→inform, `call_for_proposals`→cfp, `watch`→subscribe; grant never in schemas |
| `test_agent_tool_query_when_roost_enabled` | M11 | pointer string returned, native answer in WorkingMemory; legacy path unchanged |
| `test_roost_event_content_body_mandatory` | M12 | validation error without `body` |
| `test_matrix_carrier_roundtrip` | M12 | `to_content`/`from_content`, `m.relates_to` from `in_reply_to` |
| `test_matrix_blackboard_replaces_state` | M12 | version bump, stale refused |
| `test_ask_agent_routes_through_engine` | M12 | hops seeded, status strings preserved; no endpoint ⇒ legacy tunnel path |

### Integration Tests
| Test | Description |
|---|---|
| `test_gate_ls1_wakes` | 5 agents, one in-process channel: addressed `request` 1 wake; broadcast `cfp` with 2 matches 2 wakes; `inform` with no handler 0 |
| `test_gate_ls2_inform_no_reply` | `inform` updates WorkingMemory/blackboard, zero outbound messages, one audit line |
| `test_gate_ls3_directory_lookup` | `find_capability("salary")` returns the HR agent with its category hash in < 5 ms over 1 000 entries, no LLM |
| `test_gate_ls4_by_reference` | a `pyarrow.Table` passed in-process keeps its buffer address on both sides and stays addressable by handle id |
| `test_gate_ls5_single_writer` | two writers, stale versions: one accepted, one refused, each subscriber informed once |
| `test_gate_ls6_matrix_carrier` (`integration`, `PARROT_TEST_MATRIX=1`) | typed envelope on `m.parrot.roost` with readable `body`; `m.parrot.blackboard` state replaces, not appends |
| `test_salary_flow_end_to_end` | the driving flow: lookup → mount → request → deterministic HR tool → `inform` native struct → two caller LLM wakes total (stubbed client) |

### Validation Contract

tests:
- packages/ai-parrot/tests/registry/test_capability_registry.py
- packages/ai-parrot/tests/registry/test_capability_models.py
- packages/ai-parrot/tests/registry/test_unregister.py
- packages/ai-parrot/tests/registry/test_yaml_roundtrip.py
- packages/ai-parrot/tests/bots/flows/core/test_context.py
- packages/ai-parrot/tests/test_agent_tool_ai_message.py
- packages/ai-parrot/tests/unit/test_audit_ledger.py
- packages/ai-parrot/tests/auth/test_agent_guard.py
- packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py
- packages/ai-parrot-integrations/tests/test_matrix_swarm_events.py
- packages/ai-parrot-integrations/tests/test_matrix_tunnel.py
- packages/ai-parrot-integrations/tests/test_matrix_reply_to.py
markers: none

> The new `packages/ai-parrot/tests/roost/` and `packages/ai-parrot-integrations/tests/test_matrix_roost_*.py` files are
> added to this list by `/sdd-task` once they exist (they cannot be declared before creation). `test_gate_ls6_matrix_carrier`
> is `integration`-marked and env-gated; it is never listed here.

### Test Data / Fixtures
```python
@pytest.fixture
def envelope() -> SimpleNamespace:          # satisfies EnvelopeLike without FEAT-746
    return SimpleNamespace(envelope_id="env-1", correlation_id="corr-1", trace=TraceContext(trace_id="t"*32, span_id="s"*16),
                           budget_ms=5_000, token_budget=2_000, caller="agent-a", idempotency_key=None)

@pytest.fixture
def five_agents(inprocess_carrier) -> dict[str, RoostEndpoint]:
    """agent-a … agent-e on one InProcessCarrier; hr-agent advertises hr.people.salary (deterministic, grant hr.*)."""

@pytest.fixture
def hr_registry() -> AgentRegistry:
    """Fresh AgentRegistry with 1 000 synthetic AGENT entries plus the HR agent (category hash fixed) for L-S3."""

@pytest.fixture
def stub_wake() -> WakeCallback:
    """Counts wakes; returns None (no reply) unless the test installs a reply."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1 All unit tests in `packages/ai-parrot/tests/roost/` and the Matrix Roost tests pass; the Validation Contract files stay green.
- [ ] AC-2 Twelve performatives and five protocols ship (resolved U1); `OBLIGATIONS` matches the brainstorm table verbatim.
- [ ] AC-3 The LLM never emits a performative as text: every `RoostToolkit` tool and every mounted capability tool maps to an act in the harness; no tool schema exposes `performative` as free text or the grant.
- [ ] AC-4 An out-of-state or closed-conversation message is answered with `not_understood`, logged, and never reaches a wake callback.
- [ ] AC-5 Timeouts come from `envelope.budget_ms`; a timed-out Request emits `failure(TIMEOUT)` to the requester; hop budget ⇒ `failure(HOP_LIMIT)`; token budget ⇒ `failure(TOKEN_BUDGET)`.
- [ ] AC-6 No performative obliges a reply to `inform`, `agree`, `refuse`, `failure`, `accept` or `reject` (courtesy loops impossible by construction — asserted by a test that counts outbound messages after each).
- [ ] AC-7 A directly addressed `inform` wakes the receiver once; a broadcast/capability-filtered `inform` is stored and wakes only when a registered handler with `needs_decision=True` matches (resolved).
- [ ] AC-8 Contract Net uses `FixedWeightScorer` by default, accepts a per-channel `BidScorer`, and wakes the requester's LLM only on a tie (resolved).
- [ ] AC-9 `AgentRegistry.find_capability` is deterministic, calls no LLM or embedding function, ranks by `(locality, cost, -score)`, and answers in < 5 ms for 1 000 entries (L-S3).
- [ ] AC-10 `ResourceType.AGENT` exists; `CapabilityRegistry.search()` behaviour and existing `ResourceType` values are unchanged (FEAT-070 tests green); `parrot.registry.capabilities` is extended, not duplicated (resolved U3).
- [ ] AC-11 `BotMetadata.roost`, `BotConfig.roost`, `register(roost=)` and `register_bot_decorator(roost=)` are additive and optional; every existing registry lookup and the PBAC policy collection in `register()` behave as before.
- [ ] AC-12 The inter-agent grant is configuration with glob scopes, fail-closed (`grant is None` ⇒ denied), enforced before lookup results are mounted, and never a tool parameter.
- [ ] AC-13 The serving side runs `PBACToolCallGuardrail` through `ToolManager.execute_tool(permission_context=msg.permission_context)` for local callers exactly as for remote ones.
- [ ] AC-14 Contract Net awards attenuate: the awardee's effective scopes are the intersection with the requester's.
- [ ] AC-15 Blackboard keys `roster`, `definitions`, `tasks`, `digest`, `artifacts` exist with the `WriterPolicy` owners; `digest` ownership moves to the last Request closer when no coordinator exists (resolved); a stale write raises `StaleWriteError` and is never merged; each accepted write delivers exactly one `inform` per subscriber.
- [ ] AC-16 `FlowContext.shared_data` and `to_snapshot()` are unchanged; the `blackboard` binding is optional and excluded from snapshots; `AgentCrew.run_*` untouched (resolved U4).
- [ ] AC-17 In-process carrier keeps the full envelope and passes `content` by reference (resolved U5): `id(content)` equal on both sides; zero serialization.
- [ ] AC-18 On the in-process, same-host and bus carriers a result never appears as JSON text in `body`; it is an object, an Arrow table/frame reference, or a handle.
- [ ] AC-19 The bus carrier uses a dedicated `EventBus` (telemetry instance rejected), sets `Event.correlation_id`, carries `reply_to`, `idempotency_key` and trace in `metadata`, dedups by `idempotency_key`, and routes undeliverable messages to `roost.dlq`.
- [ ] AC-20 L-S1: with 5 agents in one channel — addressed `request` 1 wake, broadcast `cfp` with 2 matching capabilities 2 wakes, `inform` with no handler 0 wakes.
- [ ] AC-21 L-S2: an `inform` reaches the receiver, updates WorkingMemory or a blackboard key, produces zero outbound messages and one signed audit line.
- [ ] AC-22 L-S4: a `pyarrow.Table` passed in-process keeps its buffer address on both sides and resolves by handle id in the artifacts key.
- [ ] AC-23 L-S5: two writers with stale versions — exactly one write lands, exactly one `inform` per subscriber.
- [ ] AC-24 L-S6 (env-gated): a typed envelope rides `m.parrot.roost` with a readable `body` shown by an ordinary client; agents parse the envelope; `m.parrot.blackboard` state replaces, not appends.
- [ ] AC-25 Matrix namespace stays `m.parrot.*` (resolved); `body` is mandatory on `RoostEventContent`; FEAT-195's rejection is respected by framing Matrix as one carrier among four.
- [ ] AC-26 `AgentSwarmToolkit.ask_agent` with an endpoint runs as a Request/Query over the engine, seeds hops from `ctx.current_hops`, preserves the FEAT-463 status strings, and the 26 existing Matrix test modules stay green; without an endpoint the tunnel path is byte-for-byte unchanged (resolved U2).
- [ ] AC-27 Every performative produces a `RoostAuditEntry` on both sides, signed by `AbstractKMSSigner`, joined by `trace_id`; `AuditLedger.append()` is not called.
- [ ] AC-28 `AgentTool._execute` still returns `str`; for Roost-enabled targets it issues a `query` and stores the native answer in WorkingMemory; `tests/test_agent_tool_ai_message.py` stays green.
- [ ] AC-29 Names: no symbol named `delegate*` is introduced (FEAT-590); the cfp tool is `call_for_proposals`; the two protocols are documented as **Squawk** (FEAT-746) and **Roost** (this spec) sharing one envelope (resolved).
- [ ] AC-30 No new runtime dependency: pandas, pyarrow and navigator-eventbus are already declared (`packages/ai-parrot/pyproject.toml:170,180,187`); no Polars.
- [ ] AC-31 `docs/roost/` documents performatives, protocols, gating, directory, blackboard, carriers and the FEAT-746 boundary.
- [ ] AC-32 No breaking change to any existing public API (registry, capabilities, FlowContext, AgentTool, Matrix events, swarm toolkit).
- [ ] AC-33 (Q1) No Roost module imports the Squawk satellite at module level; `squawk_bridge.py` is the only file that names it; with the satellite absent every Roost test passes, messages ride `LocalEnvelope`, and `find_and_mount` returns `[]` with exactly one warning per process.
- [ ] AC-34 (Q2) `EnvelopeCodec` is sync with `encode(msg) -> bytes` / `decode(bytes) -> RoostMessage` / `content_type`; `JsonEnvelopeCodec` ships in core; the bus carrier accepts any codec and routes unknown `content_type`s to the DLQ.
- [ ] AC-35 (Q3) On the bus and Matrix carriers both the serialized `PermissionContext` and `auth_token` travel; the serving endpoint uses the token when present and the context otherwise; neither present ⇒ `execute_tool` receives `None` and PBAC fails closed.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against `dev` @ `729d51f57` (2026-10-26). The proposal's citations were re-probed at `14d4fc780`; line numbers below are from today's re-verification.

### Verified Imports
```python
from parrot.registry import AgentRegistry, BotConfig, BotMetadata, register_agent, agent_registry   # verified: parrot/registry/__init__.py:2,7,12,19-20
from parrot.registry.capabilities import CapabilityEntry, CapabilityRegistry, ResourceType, RouterCandidate   # verified: parrot/registry/capabilities/__init__.py:6-16
from parrot.registry.capabilities.models import ResourceType          # verified: parrot/registry/capabilities/models.py:25
from parrot.registry.capabilities.registry import CapabilityRegistry  # verified: parrot/registry/capabilities/registry.py:19
from parrot.bots.flows.core.context import FlowContext                # verified: parrot/bots/flows/core/context.py:56
from parrot.core.events.lifecycle import TraceContext                 # verified: parrot/core/events/lifecycle/__init__.py:18 (re-export of navigator_eventbus.lifecycle.trace.TraceContext)
from parrot.tools.abstract import AbstractTool                        # verified: parrot/tools/__init__.py:150
from parrot.tools.toolkit import AbstractToolkit                      # verified: parrot/tools/__init__.py:151
from parrot.tools.decorators import tool                              # verified: parrot/tools/__init__.py:152
from parrot.tools.manager import ToolManager                          # verified: parrot/tools/manager.py:289
from parrot.tools.agent import AgentTool, AgentContext, QuestionInput # verified: parrot/tools/agent.py:52,21,32
from parrot.tools.working_memory.tool import WorkingMemoryToolkit     # verified: parrot/tools/working_memory/tool.py:47
from parrot.tools.repl_worker.transport import encode_dataframe, decode_dataframe_from_shm, unlink_shm, EncodedDataFrame   # verified: parrot/tools/repl_worker/transport.py:83,266,300,74
from parrot.security.audit_ledger import AbstractKMSSigner, LocalHMACSigner, AuditLedger, AuditLedgerEntry   # verified: parrot/security/audit_ledger.py:135,166,296,80
from parrot.bots.guardrails.base import Guardrail, GuardrailContext, GuardrailResult, GuardrailAction   # verified: parrot/bots/guardrails/base.py:97,65,47,32
from parrot.bots.guardrails.builtin.pbac import PBACToolCallGuardrail  # verified: parrot/bots/guardrails/builtin/pbac.py:53
from parrot.auth.permission import PermissionContext                  # verified: parrot/auth/permission.py:81
from parrot.auth.agent_guard import enforce_agent_access, parse_bot_permissions   # verified: parrot/auth/agent_guard.py:172,73
from parrot.observability.fanout import setup_event_fanout            # verified: parrot/observability/fanout.py:90 (idiom only; Roost builds its own bus)
from navigator_eventbus import EventBus                               # verified: parrot/observability/fanout.py:15 ; navigator-eventbus 0.4.0
from navigator_eventbus.evb import Event                              # verified: installed 0.4.0 — Event(event_type, payload, event_id=…, timestamp=…, source=None, priority=NORMAL, correlation_id=None, metadata={})
from navigator_auth.abac.policies.resources import ResourceType as PBACResourceType   # verified: parrot/auth/agent_guard.py:216 (lazy import; has AGENT — NOT the FEAT-070 enum)

# ai-parrot-integrations
from parrot.integrations.matrix.events import ParrotEventType, TaskEventContent, ChannelStateContent, TunnelStateContent   # verified: matrix/events.py:27,110,269,283
from parrot.integrations.matrix.client import MatrixClientWrapper     # verified: matrix/client.py:32
from parrot.integrations.matrix.crew import AgentSwarmToolkit, AgentTunnel, TunnelRegistry   # verified: matrix/crew/__init__.py:43,45
from parrot.integrations.matrix.crew import context as swarm_ctx      # verified: matrix/crew/context.py — current_hops / current_session / current_channel_room / current_trigger_event ContextVars
from parrot.integrations.matrix.crew.registry import MatrixCrewRegistry, MatrixAgentCard   # verified: matrix/crew/registry.py:67,16
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/registry/registry.py
@dataclass
class BotMetadata:                                                   # line 50
    name: str; factory: Union[Type[AbstractBot], AgentFactory]; module_path: str; file_path: Path   # 58-61
    singleton: bool = False; tags: Optional[Set[str]]; priority: int = 0; at_startup: bool = False  # 62-65
    dependencies: List[str]; startup_config: Dict[str, Any]; bot_config: Optional[Any] = None       # 66-68
    events_block: Optional[Dict[str, Any]] = None                    # line 69  ← Roost field goes after this
    async def get_instance(self, *args, **kwargs) -> AbstractBot:    # line 85
class BotConfig(BaseModel):                                          # line 227
    name: str; class_name: str; module: str; enabled: bool = True    # 230-233
    tags: Optional[Set[str]]; singleton: bool; at_startup: bool; startup_config; priority   # 247-251
    policies: Optional[List["PolicyRuleConfig"]] = Field(default=None)   # line 255  ← Roost field goes after this
class AgentRegistry:                                                 # line 258
    def register(self, name: str, factory: Type[AbstractBot], *, singleton=False, tags=None, priority=0, dependencies=None,
                 replace=False, at_startup=False, startup_config=None, bot_config: Optional["BotConfig"] = None, **kwargs) -> None   # 526-540
        # NOTE: **kwargs are merged into startup_config (merged_kwargs = {**startup_config, **kwargs}, ~line 565) — a `roost=` kwarg
        #       must be a NAMED parameter, otherwise it silently lands in startup_config.
    def get_metadata(self, name: str) -> Optional[BotMetadata]:      # line 648
    async def get_instance(self, ...)                                # line 659 (PBAC enforcement, FEAT-1054)
    def register_bot_decorator(self, *, name=None, priority=0, dependencies=None, singleton=False, at_startup=False,
                               startup_config=None, tags=None, **kwargs)   # 1324-1334
    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:        # line 1450 (only discovery-by-attribute today)
# parrot/registry/__init__.py: agent_registry = AgentRegistry(...) (7); register_agent = agent_registry.register_bot_decorator (12)

# packages/ai-parrot/src/parrot/registry/capabilities/models.py
class ResourceType(str, Enum):                                       # line 25
    DATASET = "dataset"; TOOL = "tool"; GRAPH_NODE = "graph_node"; PAGEINDEX = "pageindex"; VECTOR_COLLECTION = "vector_collection"   # 28-32
class CapabilityEntry(BaseModel):                                    # line 48
    name: str; description: str; resource_type: ResourceType; embedding: Optional[list[float]] = None
    metadata: dict[str, Any]; not_for: list[str]                     # model_config = {"arbitrary_types_allowed": True}

# packages/ai-parrot/src/parrot/registry/capabilities/registry.py
class CapabilityRegistry:                                            # line 19
    def __init__(self, not_for_penalty: float = 0.5) -> None:        # line 36 — _entries: list[CapabilityEntry], _embedding_matrix, _index_dirty, _embedding_fn, _not_for_penalty (37-42)
    def register(self, entry: CapabilityEntry) -> None:              # line 46
    def register_from_tool(self, tool: Any) -> None:                 # line 90
    async def build_index(self, embedding_fn: Callable) -> None:     # line 148
    async def search(self, query: str, top_k: int = 5, resource_types: Optional[list[ResourceType]] = None) -> list[RouterCandidate]:   # line 183 — needs an embedding fn

# packages/ai-parrot/src/parrot/bots/flows/core/context.py
@dataclass
class FlowContext:                                                   # line 56
    shared_data: Dict[str, Any] = field(default_factory=dict)        # line 94 (plain dict, no ownership/version)
    trace_context: Optional["TraceContext"] = field(default=None)    # line 112
    def to_snapshot(self, ...)                                       # line 287 — excludes agent_registry/synthesis_client/trace_context; copies shared_data (340)

# packages/ai-parrot/src/parrot/tools/agent.py
class AgentTool(AbstractTool):                                       # line 52
    def __init__(self, agent: "AbstractBot", tool_name: str = None, tool_description: str = None, use_conversation_method: bool = True,
                 context_filter=None, execution_memory=None, **kwargs)   # 64-72 ; self.agent = agent (74)
    async def _execute(self, **kwargs) -> str:                       # line 157

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):                              # line 289 ; self._registered_agents: Dict[str, RegisteredAgent] (331)
    def search_tools(self, query: str, limit: int = 15) -> str:      # line 759
    def add_tool(self, tool: Union[ToolDefinition, AbstractTool], name: Optional[str] = None) -> None:   # line 827
    def register_toolkit(self, toolkit, **kwargs) -> List[AbstractTool]:   # line 1190
    def get_tool_schemas(self, provider_format=ToolFormat.GENERIC) -> List[Dict[str, Any]]:   # line 1313
    def get_tool(self, tool_name: str) -> Optional[Any]:             # line 1392
    def unregister_tool(self, tool_name: str) -> bool:               # line 1434
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional["PermissionContext"] = None,
                           *, return_tool_result: bool = False) -> Any:   # line 1787 (PBACToolCallGuardrail is the first guard)
    async def register_a2a_agent(self, url: str) -> RegisteredAgent: # line 2302
    def get_by_skill(self, skill: str) -> List[RegisteredAgent]:     # line 2342
    def search_a2a_agents(self, query: str) -> List[RegisteredAgent]:   # line 2371
    def clone(self, *, include_search_tool: bool = False) -> "ToolManager":   # line 2824
# parrot/bots/abstract.py: self.tool_manager: ToolManager = ToolManager(...)   # line 383

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):   # line 47
    async def _put(self, key: str, df: pd.DataFrame, **kwargs) -> Any:   # line 244
    async def _put_generic(self, key: str, data: Any, **kwargs) -> Any:  # line 264
    async def store_result(self, key: str, data: Any, data_type: str = "auto", description: str = "", metadata: Optional[dict] = None,
                           turn_id: Optional[str] = None) -> dict:   # line 374 — accepts any native object already

# packages/ai-parrot/src/parrot/tools/repl_worker/transport.py
class EncodedDataFrame(NamedTuple)                                   # line 74
def encode_dataframe(...)                                            # line 83  — Arrow IPC into multiprocessing.shared_memory
def decode_dataframe_from_shm(shm_name: str, size: int) -> pd.DataFrame:   # line 266
def unlink_shm(shm_name: str) -> None:                               # line 300

# packages/ai-parrot/src/parrot/security/audit_ledger.py
class AuditLedgerEntry(BaseModel):                                   # line 80 — entry_id, user_id, channel, tool, provider, key_fingerprint, signature, created_at (99-107)
    def canonical_bytes(self) -> bytes:                              # line 109
class AbstractKMSSigner:                                             # line 135 — async sign(data: bytes) -> str (143), async verify(data, signature) -> bool (154)
class LocalHMACSigner(AbstractKMSSigner):                            # line 166
class AuditLedger:                                                   # line 296
    def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None) -> None:   # line 327
    async def append(self, *, user_id: str, channel: str, tool: str, provider: str, credential_material: Any) -> AuditLedgerEntry:   # line 338 — credential_material REQUIRED

# packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py
class PBACToolCallGuardrail(Guardrail):                              # line 53
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:   # line 233 — ctx.tool_name + ctx.extras["permission_context"]; fail-closed

# packages/ai-parrot/src/parrot/auth/agent_guard.py
def parse_bot_permissions(...)                                       # line 73
async def enforce_agent_access(...)                                  # line 172 — uses navigator_auth ResourceType.AGENT (216, 234)

# packages/ai-parrot/src/parrot/observability/fanout.py
def _validate_bus(bus: Any) -> None:                                 # line 74 — requires Streams transport, publish-only (Roost copies the shape, not publish-only)
def setup_event_fanout(bus: Any = None) -> None:                     # line 90

# navigator_eventbus 0.4.0 (installed)
class EventBus:  __init__(self, redis_url=None, use_redis=False, *, channel_prefix=None, backend=None, transport: Literal['memory','pubsub','streams']|None=None, publish_only=False, outbox=None, **bus_options)
    async publish(self, event: Event, *, severity=None) -> int ; subscribe(self, pattern: str, handler, *, priority=0, filter_fn=None, min_severity=None) -> str ; unsubscribe(subscriber_id) -> bool ; close()
class Event(event_type: str, payload: Dict[str, Any], event_id=…, timestamp=…, source=None, priority=EventPriority.NORMAL, correlation_id=None, metadata={})   # NO reply_to field
class TraceContext(trace_id: str, span_id: str, trace_flags: int = 1, trace_state: str = '', parent_span_id: Optional[str] = None)

# packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py
class ParrotEventType:                                               # line 27 — AGENT_CARD(31) TASK(34) RESULT(35) STATUS(36) FEEDBACK(37) CHANNEL(40) TUNNEL(41)
class TaskEventContent(BaseModel):                                   # line 110 — task_id, context_id, content: str, metadata, target_agent, skill_id, correlation_id, hops: int (ge=0), origin_session, expected_schema
class ChannelStateContent(BaseModel):                                # line 269 — name, visibility, answer_policy, agents, version: int = 1
class TunnelStateContent(BaseModel):                                 # line 283 — agents, created_at, ttl_minutes, origin_session

# packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py
class MatrixClientWrapper:                                           # line 32
    async def send_event(self, room_id: str, event_type: str, content: Dict[str, Any]) -> str:            # line 193
    async def set_room_state(self, room_id: str, event_type: str, content: Dict[str, Any], state_key: str = "") -> str:   # line 217
    async def get_room_state_event(self, room_id: str, event_type: str, state_key: str = "") -> Optional[Dict[str, Any]]:   # line 244
    def on_custom_event(self, event_type: str, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:   # line 289

# packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py
class AgentSwarmToolkit(AbstractToolkit):                            # line 24 ; __init__ line 27
    async def ask_agent(self, agent: str, question: str, expected_schema: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> dict:   # line 53
        # line 89: ans = await tunnel.ask(self._agent_name, agent, question, expected_schema=..., timeout=..., hops=ctx.current_hops.get(), origin_session=ctx.current_session.get())
        # status strings documented at 65: "schema_error", "hop_limit", "unknown_agent", …
    async def post_to_channel(self, channel: str, text: str) -> str: # line 160
# matrix/crew/tunnel.py: class TunnelRegistry (208) — register_future(correlation_id) -> asyncio.Future (319), discard_future(correlation_id) (332)
# matrix/crew/context.py: current_hops: ContextVar[int] (default 0), current_session, current_channel_room, current_trigger_event
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AgentRegistry.find_capability` | `CapabilityRegistry.find_exact` | method call | `capabilities/registry.py:19` (new method beside `search` :183) |
| `AgentRegistry.register(roost=)` | `CapabilityRegistry.register_agent_capability` | method call after `BotMetadata(...)` is built | `registry.py:526-540` (BotMetadata built ~:567) |
| `RoostEndpoint` (RUN_TOOL) | `ToolManager.execute_tool(name, params, permission_context=...)` | method call | `manager.py:1787` |
| `RoostEndpoint.find_and_mount` | FEAT-746 `catalog.mount` → `ToolManager.add_tool` / `unregister_tool` | method call | `manager.py:827,1434` (catalog tool: FEAT-746, see Does NOT Exist) |
| `RoostEndpoint` (STORE) | `WorkingMemoryToolkit.store_result(key, data, data_type="auto")` | method call | `working_memory/tool.py:374` |
| `SharedMemoryCarrier` | `encode_dataframe` / `decode_dataframe_from_shm` / `unlink_shm` | function call | `repl_worker/transport.py:83,266,300` |
| `EventBusCarrier` | `EventBus.publish(Event)` / `EventBus.subscribe(pattern, handler)` | method call | navigator-eventbus 0.4.0 (fanout.py:15 import) |
| `RoostAuditLedger` | `AbstractKMSSigner.sign/verify` | method call | `audit_ledger.py:143,154` |
| `RoostMessage.trace_id()` | `TraceContext.trace_id` | attribute | `core/events/lifecycle/__init__.py:18` |
| `FlowContext.blackboard` | `Blackboard` | optional attribute | `core/context.py:112` (new field after) |
| `MatrixCarrier` | `MatrixClientWrapper.send_event` / `on_custom_event` | method call | `matrix/client.py:193,289` |
| `MatrixBlackboard` | `MatrixClientWrapper.set_room_state` / `get_room_state_event` | method call | `matrix/client.py:217,244` |
| `AgentSwarmToolkit.ask_agent` | `RoostEndpoint.request/query`; `swarm_ctx.current_hops` | method call / ContextVar | `swarm_toolkit.py:53,89`; `crew/context.py` |
| `AgentTool._execute` | `RoostEndpoint.query` | method call when `self.agent.roost_endpoint` is set | `tools/agent.py:157` |
| `GrantPolicy` | — (pure) | `fnmatch.fnmatchcase` | stdlib |

### Does NOT Exist (Anti-Hallucination)

Verified absent at `729d51f57` (`grep -rl` over `packages/*/src`, 0 hits unless noted):

- ~~`performative`~~, ~~`not_understood`~~, ~~`ContractNet`~~, ~~`class ProtocolEngine`~~, ~~`class Blackboard`~~, ~~`find_capability`~~ — nothing; Roost creates all of them.
- ~~`parrot.roost`~~, ~~`parrot_squawk`~~, ~~`parrot.squawk`~~, ~~`RoostEnvelope`~~, ~~`SquawkEnvelope`~~ — no such packages/classes yet.
- ~~`parrot.registry.capabilities.models.ResourceType.AGENT`~~ — the FEAT-070 enum has **no** `AGENT` (models.py:28-32). The 5 `ResourceType.AGENT` hits in the tree (`auth/agent_guard.py:234`, `bots/abstract.py:4423`, server `handlers/{chat,bots,agent}.py`) are the **navigator-auth PBAC enum** (`navigator_auth.abac.policies.resources.ResourceType`). Never mix the two.
- ~~`BotMetadata.kind` / `.endpoint` / `.contract` / `.roost`~~ — none exist (registry.py:58-69). `kind`/`endpoint` are **FEAT-746 U2**; `roost` is this spec.
- ~~`AgentRegistry.capability_registry`~~, ~~`CapabilityRegistry.find_exact`~~, ~~`register_agent_capability`~~ — new here.
- ~~`Event.reply_to`~~ — navigator-eventbus 0.4.0 `Event` has `correlation_id` and `metadata`, no `reply_to`; ~~`EventBus.request()` / `.reply()`~~ do not exist; ~~`navigator_eventbus.models.EventEnvelope`~~ is not importable (the `EventEnvelope` named in `docs/events/eventbus-v2.md` is a doc-level contract, not a Python class in 0.4.0).
- ~~`AuditLedger.append(... )` without `credential_material`~~ — it is a required keyword (audit_ledger.py:338-346); do not call it for performatives.
- ~~`inter_agent` grant / `allowed_agents` / `can_call`~~ — the only `inter_agent` hits are `MatrixCollaborativeSession.handle_inter_agent_message` (`matrix/crew/session.py:154`, `transport.py:320`), the FEAT-195 session round, not a grant.
- ~~`conversation_id` / `reply_to` as Roost concepts~~ — the 15/16 existing hits live in msteams/msagentsdk/telegram dialog code; unrelated.
- ~~`ai.parrot.*` Matrix namespace~~ — the namespace is `m.parrot.*` (events.py:31-41); ~~`m.parrot.roost`~~, ~~`m.parrot.blackboard`~~, ~~`RoostEventContent`~~, ~~`BlackboardStateContent`~~ do not exist yet.
- ~~`delegate` as a Roost tool~~ — `DelegateToolNode` / `LlamaCppDelegate` / `NeedleDelegate` belong to FEAT-590; do not reuse the word.
- ~~Polars~~ — not a dependency and not to be added (FEAT-746 U3).
- ~~`parrot/vectorstores/`~~, ~~`parrot/bots/orchestration/`~~ — long gone.

**Provided by the FEAT-746 satellite (`ai-parrot-squawk`, provisional import path `parrot.squawk`) — do NOT exist yet, do NOT invent them, and NEVER import them outside `parrot/roost/squawk_bridge.py` (resolved Q1):**
- the Squawk envelope model (satisfies `EnvelopeLike`: `envelope_id`, `correlation_id`, `trace`, `budget_ms`, `token_budget`, `caller`, `idempotency_key`, `auth_token`) and its `CapnpEnvelopeCodec` implementing Roost's `EnvelopeCodec` protocol (resolved Q2 — Roost's own `JsonEnvelopeCodec` and `LocalEnvelope` exist in core instead);
- the catalog tools `list` / `mount` / `unmount` / `search` / `find` (`RemoteToolkit`) used through `squawk_bridge.mount_capabilities`;
- `ResultHandle` / descriptor registry / blob store (FEAT-704 → FEAT-746), referenced by `artifacts` values and `content_ref`;
- the capability policy gate composed ahead of `PBACToolCallGuardrail`;
- Biscuit token issue/verify (FEAT-746 Q7) behind `squawk_bridge.resolve_authority` (resolved Q3);
- `BotMetadata.kind: local | a2a | squawk` + `endpoint` (U2) — `find_capability` reads `kind` via `getattr(..., "kind", "local")` until it lands.

### Edit Sites (Blueprint Anchors)

Verified against: `729d51f57` (dev, 2026-10-26). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY (M3: `BotMetadata.roost`) | `    events_block: Optional[Dict[str, Any]] = None  # FEAT-176: parsed 'events:' YAML block` | `registry.py:69` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY (M3: `BotConfig.roost`) | `    policies: Optional[List["PolicyRuleConfig"]] = Field(default=None)` | `registry.py:255` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY (M3: `register(roost=)`) | `        bot_config: Optional["BotConfig"] = None,` | `registry.py:538` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY (M3: decorator `roost=`) | `    def register_bot_decorator(` | `registry.py:1324` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY (M3: `find_capability`) | `    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:` | `registry.py:1450` | 1 |
| `packages/ai-parrot/src/parrot/registry/__init__.py` | MODIFY (M3: export `RoostAgentConfig` lazily, keep `__all__`) | `from .registry import AgentRegistry, BotConfig, BotMetadata` | `__init__.py:2` | 1 |
| `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | MODIFY (M3: `AGENT`) | `    VECTOR_COLLECTION = "vector_collection"` | `models.py:32` | 1 |
| `packages/ai-parrot/src/parrot/registry/capabilities/registry.py` | MODIFY (M3: exact index state) | `        self._not_for_penalty: float = not_for_penalty` | `registry.py:42` | 1 |
| `packages/ai-parrot/src/parrot/registry/capabilities/registry.py` | MODIFY (M3: `find_exact` before `search`) | `    async def search(` | `registry.py:183` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY (M6: `blackboard` field) | `    trace_context: Optional["TraceContext"] = field(default=None)` | `context.py:112` | 1 |
| `packages/ai-parrot/src/parrot/tools/agent.py` | MODIFY (M11: Roost query path) | `    async def _execute(self, **kwargs) -> str:` | `agent.py:157` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` | MODIFY (M12: event types) | `    TUNNEL = "m.parrot.tunnel"` | `events.py:41` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` | MODIFY (M12: content models) | `class TunnelStateContent(BaseModel):` | `events.py:283` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` | MODIFY (M12: endpoint kwarg + routing) | `    async def ask_agent(` | `swarm_toolkit.py:53` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` | MODIFY (M12: tunnel call site) | `        ans = await tunnel.ask(` | `swarm_toolkit.py:89` | 1 |
| `packages/ai-parrot/src/parrot/roost/__init__.py` | CREATE (M1 creates; M2–M11 append exports — **shared file**) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/performatives.py` | CREATE (M1) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/messages.py` | CREATE (M1) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/protocols.py` | CREATE (M2) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/scoring.py` | CREATE (M2) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/directory.py` | CREATE (M3) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/grant.py` | CREATE (M4) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/gating.py` | CREATE (M5) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/blackboard.py` | CREATE (M6) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/carriers/__init__.py` | CREATE (M7) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/carriers/base.py` | CREATE (M7) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/carriers/inprocess.py` | CREATE (M7) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/carriers/shm.py` | CREATE (M8) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/codec.py` | CREATE (M9) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/carriers/bus.py` | CREATE (M9) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/audit.py` | CREATE (M10) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/squawk_bridge.py` | CREATE (M11) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | CREATE (M11) | — | — | — |
| `packages/ai-parrot/src/parrot/roost/toolkit.py` | CREATE (M11) | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/__init__.py` | CREATE (M12) | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/carrier.py` | CREATE (M12) | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/blackboard.py` | CREATE (M12) | — | — | — |
| `packages/ai-parrot/tests/roost/__init__.py`, `conftest.py`, `test_*.py` (per §4) | CREATE (M1–M11, M13) | — | — | — |
| `packages/ai-parrot-integrations/tests/test_matrix_roost_carrier.py`, `test_matrix_roost_blackboard.py`, `test_matrix_roost_gate_ls6.py` | CREATE (M12, M13) | — | — | — |
| `docs/roost/README.md`, `docs/roost/performatives.md`, `docs/roost/carriers.md` | CREATE (M13) | — | — | — |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated implementation may only express a decision already recorded here and in the TASK's implementation blocks.

### Patterns to Follow
- **FEAT-463 hop propagation**: `swarm_ctx.current_hops` ContextVar + `hop_limit` status string — `ConversationBudget.hops` generalises it; do not add a second counter.
- **`TunnelRegistry` correlation futures** (`tunnel.py:319,332`) for request/reply pairing — the engine's `ConversationState` plays that role on every carrier; the Matrix carrier maps `correlation_id` ↔ `conversation_id`.
- **Matrix state events replace, not append** (`ChannelStateContent.version`, `agent_card`/`channel`/`tunnel`) — `m.parrot.blackboard` follows the same shape with `state_key=<key>`.
- **`PBACToolCallGuardrail` first, fail-closed** — never bypass `execute_tool`; the Roost grant is an *additional* caller-side gate, not a replacement.
- **`A2ARemoteSkillTool`** compiles a remote contract into a typed local tool — the mount step relies on FEAT-746's catalog tools doing the same.
- **FEAT-710 dedicated `EventBus` instance** with outbox and `event_id` dedup — Roost copies `_validate_bus`'s shape (Streams) but needs publish **and** subscribe; configure it from `PARROT_ROOST_BUS_*`, never from the telemetry keys.
- **repl_worker shm ownership** — sender creates, receiver ACKs, sender unlinks; no pickle across sandbox boundaries.
- **task_memory `artifact_id@version` + `ArtifactStore`** — the `artifacts` key stores handle ids in that identity space.
- **`ToolManager` runtime `add_tool` / `unregister_tool` / `clone`** — a mount needs no new lifecycle; per-session endpoints clone the manager.
- Async-first, Pydantic v2 models, `self.logger`, Google docstrings, 120 columns; no `requests`/`httpx`; no LangChain.
- Protocol machines are **pure** (no I/O, clock injected) so every transition is unit-testable without asyncio.

### Known Risks / Gotchas
- **FEAT-746 is unspecified** (C16) and, per Q1, owns the envelope and catalog tools exclusively. Mitigation: `EnvelopeLike` seam + `LocalEnvelope` + `JsonEnvelopeCodec` in core, and a single `squawk_bridge.py` that probes the satellite lazily and degrades (no mount) when absent. Only the real `catalog.mount` and M3's `kind` read wait for FEAT-746; the provisional module name `parrot.squawk` lives in one constant so the rename is a one-line change.
- **Degraded mode must be loud but not fatal**: `mount_capabilities` without the satellite logs one warning per process and returns `[]`; the planner then sees no mounted tools and the LLM falls back to `RoostToolkit.send(request, ...)` by name. Tests assert the single warning.
- **Codec mismatch on the bus**: a message encoded by the satellite codec received by a process without it cannot be decoded; `from_event` routes it to `roost.dlq` with the `content_type`, never raises into the handler. Deployments must run all Roost peers of one bus either with or without the satellite.
- **Fifth-directory drift**: `AgentRegistry`, ToolManager A2A cards, `A2AMeshDiscovery`, `MatrixCrewRegistry` already overlap. `find_capability` must front local entries now and FEAT-746's `kind=a2a|squawk` entries once they exist; the Matrix roster (`roster` key) is derived from the directory, never a separate source of truth.
- **Two `ResourceType` enums** (FEAT-070 vs navigator-auth PBAC). Import the FEAT-070 one explicitly from `parrot.registry.capabilities.models`; never pass a Roost value to `PolicyEvaluator.check_access`.
- **`register(**kwargs)` swallows unknown kwargs into `startup_config`** (registry.py ~565). `roost` must be a named parameter on `register()` and `register_bot_decorator()`, and YAML agents must carry it on `BotConfig.roost`; add a test that a stray `roost` never ends up in `startup_config`.
- **Embedding cost**: `CapabilityRegistry.search()` needs an embedding fn and cannot meet the 5 ms gate; `find_exact` is synchronous and index-backed. Keep the index rebuilt incrementally on `register_agent_capability` (no full rebuild).
- **`AuditLedger.append` requires `credential_material`** — use the sibling `RoostAuditLedger`; share the signer only.
- **`Event` has no `reply_to`** — carry it in `metadata`; the subscriber must honour it when sending replies on the bus, and dedup by `idempotency_key` because Streams is at-least-once.
- **Matrix payloads are JSON dicts** (`model_dump`), not binary — `RoostEventContent.envelope` carries the structured-fields mapping of the Squawk envelope; a base64 blob is acceptable only for opaque Cap'n Proto bytes and is a FEAT-746 serializer concern.
- **`TraceContext` is defined outside parrot** (navigator-eventbus) — the envelope trace field depends on that model; tests build it directly.
- **Courtesy loops**: enforced by `OBLIGATIONS` (no reply owed to `inform`/`agree`/`refuse`/`failure`/`accept`/`reject`); a handler that *sends* after an `inform` must open a new conversation, never reply.
- **Wake accounting**: the L-S1 metric counts `WakeCallback` invocations per endpoint, not LLM API calls; keep the stub deterministic.
- **Shared `.venv` in worktrees**: run tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`; integrations tests import `mautrix` lazily — the Roost Matrix tests must mock `MatrixClientWrapper`, not start a homeserver (except the env-gated L-S6).
- **FEAT-195 rejection**: Matrix pub/sub as the *primary* path stays rejected; the carrier is opt-in per registry entry and the human `body` is mandatory. Document this in `docs/roost/carriers.md` so the decision is not reopened by accident.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-eventbus` | `>=0.4.0` (declared, `pyproject.toml:187`) | bus carrier, `TraceContext` |
| `pyarrow` | `>=25.0` (declared, `:180`) | Arrow tables / IPC on the in-process and shm carriers |
| `pandas` | `>=2.0.0` (declared, `:170`) | frame payloads via repl_worker transport |
| `mautrix` | already a dependency of `ai-parrot-integrations` | Matrix carrier (through `MatrixClientWrapper`) |
| — | — | **No new dependency.** No Polars (FEAT-746 U3). |

---

## 8. Open Questions

### Resolved in the proposal (2026-10-26) — carried forward verbatim

- [x] **Matrix: custom event types under an `ai.parrot.*` namespace, or `m.room.message` with `msgtype` extensions?** — *Resolved by code*: the namespace is already `m.parrot.*` with message events (task/result/status/feedback) and state events (agent_card/channel/tunnel); `m.room.message` carries the human-readable text beside them. → §2, M12, AC-25.
- [x] **U1 — Which performative set ships in v0?** — *Resolved*: all eleven acts and all five protocols (Inform, Request, Query, Contract Net, Subscribe) ship in v0, so FEAT-463's tunnels can be subsumed in one pass. → G1/G2, M1/M2, AC-2.
- [x] **U2 — Matrix carrier vs the FEAT-463 swarm?** — *Resolved*: subsume. `AgentSwarmToolkit.ask_agent` becomes a Request over the protocol engine; tunnels stay as the room topology; hops, status and correlation come from one place. FEAT-195's rejection is reinterpreted, not overturned: Matrix is one carrier among four and the human-readable `body` stays mandatory. → G10, M12, AC-25/AC-26.
- [x] **U3 — Where does the capability directory live?** — *Resolved*: extend `parrot.registry.capabilities`. Add `ResourceType.AGENT`, an exact cap-id/keyword index and locality/cost ranking to `CapabilityRegistry`; embedding search stays as the fallback; `AgentRegistry.find_capability` delegates to it. → G4, M3, AC-9/AC-10.
- [x] **U4 — How do existing crews map onto the protocol in v0?** — *Resolved*: untouched in v0. The protocol applies to registry-discovered peers and shared channels; `AgentCrew.run_*` and `FlowContext.shared_data` stay as they are; crew-to-channel mapping is a follow-up spec. → Non-Goals, M6, AC-16.
- [x] **U5 — In-process carrier: envelope or direct call?** — *Resolved*: keep the full envelope with payloads passed by reference inside it (Pydantic models, Arrow tables, handles). Uniform audit, gating and protocol state on every carrier; zero serialization in-process. → M7, AC-17.
- [x] **Who owns `digest` in a channel with no coordinator?** — *Resolved*: the last agent that closed a Request; ownership moves with the work and the harness enforces single-writer per key version. → M6 `WriterPolicy`, AC-15.
- [x] **Does an `inform` ever wake the receiver's LLM by default?** — *Resolved*: wake if addressed directly. An `inform` that names the receiver in `receivers` wakes it; broadcast or capability-filtered `inform`s are stored (WorkingMemory / blackboard) and wake only when a registered handler asks for a decision. The L-S1 target becomes: addressed `inform` 1 wake, unaddressed `inform` with no handler 0. → M5, AC-7/AC-20.
- [x] **Contract Net bid scoring?** — *Resolved*: fixed default with a pluggable override. The harness scores `propose(cost, time, confidence)` with fixed weights from contract annotations; a channel may register a scoring strategy; the requester's LLM wakes only when the rule cannot decide. → M2 `FixedWeightScorer`/`BidScorer`, AC-8.
- [x] **Name: shared with FEAT-746 or a family name with two profiles?** — *Resolved*: two names, shared envelope. The FEAT-746 protocol is **Squawk** (parrot-to-parrot call across a boundary); this sub-protocol is **Roost** (where parrots of one network gather: performatives, gating, directory, blackboard, local carriers). Roost messages ride the Squawk envelope and reference it by name. → title, `parrot/roost/`, AC-29.

### Decided while writing this spec (spec-author decisions, recorded for audit)

- [x] **Package placement** — *Decided*: core modules under `parrot/roost/` in `ai-parrot` (performatives, engine, gating, directory, grant, blackboard, in-process/shm/bus carriers, audit, endpoint, toolkit); the Matrix carrier and room-state blackboard under `parrot/integrations/matrix/roost/` in `ai-parrot-integrations`; no `ai-parrot-server` module in v0. Rationale: every seam Roost extends (registry, ToolManager, FlowContext, AgentTool, navigator-eventbus) is already imported by core.
- [x] **Envelope coupling before FEAT-746 exists** — *Decided*: a structural `EnvelopeLike` `Protocol` naming only the fields Roost reads; the concrete class remains the Squawk envelope (the "shared envelope" decision is unchanged). Rationale: lets M1–M8, M10 build and test now; only M3 `kind`, M9 and M11 `find_and_mount` wait for FEAT-746.
- [x] **Polars in L-S4** — *Decided*: the gate uses a `pyarrow.Table` (FEAT-746 U3 amended D6 to pandas + Arrow IPC, no Polars).
- [x] **L-S6 gating** — *Decided*: `integration`-marked, runs only with `PARROT_TEST_MATRIX=1` against `docker-compose.matrix.yml`; never in the Validation Contract.
- [x] **Roost bus configuration keys** — *Decided*: `PARROT_ROOST_BUS_URL`, `PARROT_ROOST_BUS_PREFIX` (navconfig with env fallback, same resolution as `fanout._config_value`), a dedicated instance distinct from FEAT-710's.
- [x] **cfp origin tool name** — *Decided*: `call_for_proposals` (never `delegate`, FEAT-590).

### Resolved in status review (2026-10-26, Jesus Lara)

- [x] **Q1 — Squawk envelope and catalog-tool import paths.** — *Resolved*: **the satellite owns everything.** Envelope model, Cap'n Proto codec and catalog tools live only in `ai-parrot-squawk` (provisional import path `parrot.squawk`, fixed by the FEAT-746 spec). Core imports them lazily through `parrot/roost/squawk_bridge.py` — the only file allowed to name the satellite — and Roost degrades when it is absent: messages ride Roost's `LocalEnvelope`, `find_and_mount` returns `[]` with one warning (no `catalog.mount`). → §2 Overview, M11, AC-33, Worktree Strategy.
- [x] **Q2 — Bytes-safe envelope serializer for the bus.** — *Resolved*: **sync codec protocol + JSON fallback.** `EnvelopeCodec` (`content_type`, `encode(msg) -> bytes`, `decode(bytes) -> RoostMessage`) is declared in Roost (`parrot/roost/codec.py`) because, under Q1, core cannot host Squawk models; `JsonEnvelopeCodec` ships in core for dev/tests and satellite-less deployments, the satellite's `CapnpEnvelopeCodec` implements the same protocol and is picked by `squawk_bridge.load_codec()`. M9 is no longer gated on FEAT-746. → M9, AC-34.
- [x] **Q3 — `permission_context` on the wire.** — *Resolved*: **both travel; the token is authoritative.** On the bus and Matrix carriers the message carries the serialized `PermissionContext` and `auth_token` (Biscuit, when FEAT-746 has issued one); `squawk_bridge.resolve_authority` prefers the token and falls back to the context; neither ⇒ fail-closed. In-process and same-host carriers pass the context by reference. Contract Net attenuation stays a scope intersection in v0 and upgrades to token attenuation when Biscuit lands. → §2 Overview, M1 `auth_token`, M11, AC-35.

### Unresolved

None. Every question is closed; the spec inherits them as fixed decisions. The FEAT-746 spec may still rename the satellite module — that is a one-constant change in `squawk_bridge.py`, not a reopened question.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over this spec).
> Model: `gpt-5.6-luna` · **Status: skipped (exploration doc `sdd/proposals/local-inter-agent.proposal.md` is `status: review`, not `accepted` — §3b precondition)** · Transcript: none
> `codex` 0.162.1 is installed; flip the proposal to `accepted` and run the `second-opinion` skill over it (brief = proposal + §6 anchors, no spec text) to obtain the seat retroactively.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for this spec (`feat-FEAT-747-local-inter-agent`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = import):
  - M2 → M1 (`RoostMessage`, `Performative`, `FailureCode`)
  - M3 → M1 (`CarrierKind`) — otherwise independent (registry + capabilities edits)
  - M4 → M3 (`InterAgentGrant`, `RoostAgentConfig`, `CapabilityMatch`)
  - M5 → M1, M2, M3, M4
  - M6 → M1 (`RoostMessage` for the subscribe ⇒ inform bridge)
  - M7 → M1 (`CarrierKind`, `RoostMessage`, `AgentAddress`)
  - M8 → M7 ; M9 → M7 (codec + carrier, no FEAT-746 edge after Q2) ; M10 → M1
  - M11 → M2, M3, M4, M5, M6, M7, M9, M10 (the satellite is probed lazily — no build-time edge, Q1)
  - M12 → M6, M7, M11
  - M13 → M1–M12
  - Expected to run concurrently once M1 lands: M2, M3, M6, M7, M10 (then M4, M8, M9 behind their single edge).
- **Shared files** (tasks get serialized): `packages/ai-parrot/src/parrot/roost/__init__.py` (M1 creates, M2–M11 append exports — prefer one export block per module, appended in task order); `packages/ai-parrot/src/parrot/registry/registry.py` (M3 only, four edit sites in one task); `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` and `crew/swarm_toolkit.py` (M12 only).
- **Exclusive resources**: none — no compiled extension, no lockfile change (no new dependency), no migration.
- **Cross-feature dependencies**:
  - **FEAT-746 (Squawk)** is an optional runtime dependency, never a build-time one (Q1/Q2): every module builds and tests without the satellite (`LocalEnvelope`, `JsonEnvelopeCodec`, degraded mount). What waits for FEAT-746 is only *behaviour*: the real `catalog.mount` in `find_and_mount`, Cap'n Proto encoding on the bus, Biscuit verification in `resolve_authority`, and M3's read of `BotMetadata.kind` (soft `getattr`). No task of this feature is blocked on FEAT-746 merging; `test_bridge_selects_satellite_when_present` uses a stub module.
  - **FEAT-704** (handles) transitively through FEAT-746; only `artifacts` values and `content_ref` reference handle ids.
  - FEAT-463 (`matrix-agents-swarm`) and FEAT-710 (`parrot-telemetry-event-fanout`) are merged on `dev` (verified: `swarm_toolkit.py`, `fanout.py` present).
- **Suggested lanes for `/sdd-task`**: Lane A (core protocol): M1 → {M2, M6, M7, M10} → {M4, M5, M8, M9} → M11; Lane B (directory): M3; Lane C: M12 → M13. No lane is gated on another feature.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-26 | Jesus Lara / Claude Fable 5.1 | Initial draft from `local-inter-agent.proposal.md` (9/9 questions carried forward); FEAT-747 reused as reserved by `/sdd-proposal` (ledger `updated_by: local-inter-agent`, `next_feature_id: 748`); design-research seat skipped (proposal status `review`) |
| 0.2 | 2026-10-26 | Jesus Lara / Claude Fable 5.1 | Status review: Q1 satellite owns envelope + catalog (lazy `squawk_bridge`, `LocalEnvelope`, degraded mount), Q2 sync `EnvelopeCodec` + `JsonEnvelopeCodec` in core, Q3 both context and token travel, token authoritative. M9/M11 now delegation-eligible; no task gated on FEAT-746; AC-33…35 added |
