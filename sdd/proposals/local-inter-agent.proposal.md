---
id: FEAT-747
title: Roost — local inter-agent sub-protocol (performatives, LLM-free gating, capability directory, blackboard, local carriers) over the Squawk envelope (FEAT-746)
slug: local-inter-agent
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-25
  summary_oneline: Local inter-agent protocol — FIPA-style performatives, interaction protocols, LLM-free gating, capability registry, blackboard, local carriers (sister of the cross-boundary binary protocol)
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations, ai-parrot-server]
tags: [roost, squawk, inter-agent, performatives, agent-registry, blackboard, matrix, eventbus, working-memory]
research_state: sdd/state/FEAT-747/
depends_on: [FEAT-746]
created: 2026-10-25
updated: 2026-10-26
resolved_questions: 9
---

# FEAT-747 — Roost: local inter-agent sub-protocol over Squawk (FEAT-746)

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: artifacts/interagent/Brainstorm Local Inter-Agent Protocol.md`
> **Parent**: [FEAT-746 inter-agent-protocol (Squawk)](inter-agent-protocol.proposal.md) — envelope, handles, blob store, catalog tools, policy gate (reused, never redefined here)
> **Audit**: [`sdd/state/FEAT-747/`](../state/FEAT-747/)

---

## 0. Origin

The original request is a brainstorm document authored on 2026-10-25, preserved verbatim at `sdd/state/FEAT-747/source.md`.

> Inside one trust domain, ai-parrot agents still talk to each other through serialized JSON text and an LLM turn on both ends. An agent that has been granted inter-agent communication should be able to look up who can answer, call them, and receive a typed result it can use directly, with an LLM turn only where a decision is needed.
>
> Two things the cross-boundary spec does not cover and this one adds: **Intent as a typed field** […] **Many agents, one conversation** […]
>
> Dependency: this spec reuses the parent's envelope, artifact handles, blob store, catalog tools and policy gate. It does not redefine them; it adds a performative layer, interaction protocols and local transports.
>
> […] Decisions taken L1–L9 · Eleven performatives · Five interaction protocols (Inform, Request, Query, Contract Net, Subscribe) · Gating and dispatch in five steps · AgentRegistry as capability directory · Four local carriers (in-process, same host, same network, Matrix) · Blackboard with single-writer keys · Security inside one trust domain · "Does NOT exist yet — VERIFY" list · Eight open questions · Six spike gates L-S1…L-S6.

**Initial signals** (extracted, not interpreted):
- Verbs: "add", "extend", "reuse", "take from", "advertise", "search", "mount" → additive feature, not a bug
- Named entities: AgentRegistry, WorkingMemory, ToolManager, AuditLedger, PBAC, AgentCrew, navigator-eventbus, Matrix, A2A, Arrow, Polars, `catalog.mount`, FIPA-ACL, Contract Net
- Components / labels: none (file source)
- Acceptance criteria provided: six spike gates with pass criteria (L-S1…L-S6); decisions L1–L9 fixed; eight open questions; an explicit "VERIFY each against the codebase" list

---

## 1. Synthesis Summary

The brainstorm asks for a performative layer (typed speech acts with reply obligations), per-conversation interaction protocols enforced by the harness, LLM-free gating in shared channels, a capability directory on `AgentRegistry`, a single-writer blackboard and four local carriers, all layered on the FEAT-746 envelope. Research confirms that none of the protocol pieces exist: there is no performative, protocol state machine, inter-agent grant, versioned blackboard or by-reference passing anywhere in core, server or integrations (`registry/registry.py`, `bots/flows/core/context.py`, `tools/working_memory/`). It contradicts one premise: a substantial Matrix integration already exists under `parrot.integrations.matrix` with an `m.parrot.*` event namespace, room-state records, hop-limited `ask_agent` tunnels and a per-crew roster, so the Matrix carrier is an adaptation of FEAT-044/195/463, not greenfield. Every existing agent-to-agent path (crew hand-off in `crew.py`, `AgentTool`, `AgentSwarmToolkit.ask_agent`, `HybridDelegator`) is text in, text out, with the callee's LLM woken on every message, which is exactly the cost the brainstorm attacks. The seams are concrete: `BotMetadata` for contract advertisement, the FEAT-070 `CapabilityRegistry` as the seed of `find_capability`, `PBACToolCallGuardrail` and `agent_guard` for the grant, `FlowContext.shared_data` and Matrix state events for the blackboard, the FEAT-710 bus idiom and the REPL-worker Arrow/shm transport for carriers. The recommendation is `/sdd-spec`, sequenced after the FEAT-746 spec, carrying five bounded open questions (performative set, Matrix subsumption vs coexistence, directory home, crew mapping, in-process envelope).

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted at `sdd/state/FEAT-747/findings/`. Each cites the finding ID(s) that justify its inclusion. Citations were re-verified by eight read-only probe agents at HEAD `14d4fc780` (293 checks, 5 stale line/symbol drifts annotated in the findings, 0 missing) — see `sdd/state/FEAT-747/probe_results.json`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/registry/registry.py` | `BotMetadata` | 50-71 | registry entry: name/factory/tags/priority/dependencies/bot_config — no kind, endpoint, contract or locality | F001 |
| 2 | `packages/ai-parrot/src/parrot/registry/registry.py` | `AgentRegistry.register` / `get_bots_by_tag` / `register_bot_decorator` | 526-584, 1324-1420, 1450-1452 | name+tag directory; `register()` feeds PBAC policy collection; only discovery-by-attribute is `get_bots_by_tag` | F001 |
| 3 | `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | `ResourceType` / `CapabilityEntry` | 25-33, 48-75 | FEAT-070 capability model (dataset/tool/graph_node/pageindex/vector_collection) — no AGENT type | F014 |
| 4 | `packages/ai-parrot/src/parrot/registry/capabilities/registry.py` | `CapabilityRegistry.register*` / `build_index` / `search` | 19-44, 46-148, 183 | embedding (cosine) index over tools/datasets; seed for `find_capability`, needs an embedding fn, no exact cap-id or locality path | F014, F001 |
| 5 | `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | `FlowContext.shared_data` / `trace_context` / `to_snapshot` | 55-119, 287-342 | per-run shared state: plain dict, no writer ownership/version/ACL/subscriptions; carries W3C `TraceContext` | F003 |
| 6 | `packages/ai-parrot/src/parrot/bots/flows/flow/actions.py` | `SetContextAction` | 309-320 | only flow-level writer of a `shared_context` key | F003 |
| 7 | `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | `AgentCrew.run_sequential` / `run_loop` / `run_flow` | 1744-1876, 2090-2094, 2933-3077 | hand-off is a rendered prompt string; per-run `max_iterations`, no per-conversation hop/token budget | F005 |
| 8 | `packages/ai-parrot/src/parrot/bots/flows/tools.py` | `ResultRetrievalTool` | 16-48, 124-156 | read-only result retrieval returning text; no delegate/cfp origin tool | F004 |
| 9 | `packages/ai-parrot/src/parrot/tools/agent.py` | `AgentTool` / `AgentContext` / `QuestionInput` | 20-55 | agents-as-tools wrapper: text question in, text answer out | F006 |
| 10 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` | `ParrotEventType` / `ChannelStateContent` / `TunnelStateContent` / `TaskEventContent` / `AgentAnswer` | 27-40, 89-165, 269-293 | `m.parrot.*` namespace already chosen: message events task/result/status/feedback, STATE events agent_card/channel/tunnel | F006 |
| 11 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py` | `MatrixClientWrapper.send_event` / `set_room_state` / `get_room_state_event` / `on_custom_event` | 193-262, 277-303 | mautrix wrapper with custom-event and room-state primitives | F006 |
| 12 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/appservice.py` | `MatrixAppService.send_reply_as_agent` | 341-402 | `m.relates_to` / `m.in_reply_to` threading for human clients (the only `in_reply_to` in the tree) | F002 |
| 13 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` | `AgentSwarmToolkit.ask_agent` / `post_to_channel` | 24-51, 53-98, 160-178 | FEAT-463 name-addressed ask: self-ask rejection, unknown-agent envelope, ContextVar `hops` + `hop_limit` status, channel membership check | F006 |
| 14 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/tunnel.py` | `TunnelRegistry.register_future` / `discard_future` | 1-10, 318-338 | private 2-agent rooms with correlation-id futures | F006 |
| 15 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/delegation.py` | `HybridDelegator.delegate` / `DelegationRequest` | 31-47, 71-151 | visible human message + `m.parrot.task`, awaits `m.parrot.result` by task_id | F006 |
| 16 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/registry.py` | `MatrixCrewRegistry` / `MatrixAgentCard` | 16-39, 67-92 | per-crew roster keyed by name with status and display-only skills; separate from core `AgentRegistry` | F006 |
| 17 | `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py` | `MatrixHook` | 1-27 | Matrix inbound hook is a navigator_eventbus `BaseHook` | F006 |
| 18 | `docker-compose.matrix.yml` | synapse service | 1-20, 39-62 | dev homeserver stack (Synapse, Element, well-known, bridges) usable for spike L-S6 as-is | F007 |
| 19 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.add_tool` / `unregister_tool` / `execute_tool` / `register_a2a_agent` / `get_by_skill` / `search_a2a_agents` / `clone` | 289, 299-330, 827-853, 1434-1458, 1787, 2302-2398, 2824 | runtime register/unregister and per-session clone (a `catalog.mount` needs no new lifecycle); also hosts remote A2A cards with substring skill search | F011, F020 |
| 20 | `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` | `PBACToolCallGuardrail` / `.check` | 53-72, 233-283 | first guard in `execute_tool`; `PolicyEvaluator.check_access` keyed by `ResourceType.TOOL` + tool name; fail-closed | F010, F017 |
| 21 | `packages/ai-parrot/src/parrot/auth/agent_guard.py` | `enforce_agent_access` / `parse_bot_permissions` | 1-45 | PBAC at bot resolution — nearest thing to an inter-agent grant | F017 |
| 22 | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | `WorkingMemoryToolkit` / `store_result` / `_put` | 47-106, 244-279, 374-405 | per-session pandas/generic catalog with compact summaries; seam for a handle `EntryType` (parent D5) | F008 |
| 23 | `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py` | pyarrow imports (parquet only) | 135, 244-245, 306, 331-332 | pyarrow used only to write/read parquet blobs; no Arrow IPC / shm / Polars | F008 |
| 24 | `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py` | `encode_dataframe` / `decode_dataframe_from_shm` / `unlink_shm` | 1-30 | Arrow IPC over `multiprocessing.shared_memory` with documented ownership rules — the only zero-copy primitive, host→REPL worker only | F022 |
| 25 | `packages/ai-parrot/src/parrot/security/audit_ledger.py` | `AuditLedgerEntry` / `AuditLedger.append` | 80-107, 338-406 | append-only KMS-signed ledger; entry schema is credential-centric and `append()` requires `credential_material` | F009 |
| 26 | `packages/ai-parrot/src/parrot/observability/fanout.py` | `setup_event_fanout` / `_validate_bus` | 1-45 | FEAT-710 dedicated Streams publish-only `EventBus` with outbox — the bus idiom to copy for a carrier | F018, F006 |
| 27 | `packages/ai-parrot/src/parrot/a2a/mesh.py` | `A2AMeshDiscovery` | n/a | remote-only capability directory (`get_by_skill` / `get_by_tag` / `search`) | F019 |
| 28 | `packages/ai-parrot/src/parrot/a2a/router.py` | `A2AProxyRouter` | n/a | LLM-free routing by skill/tag/regex for remote A2A agents | F019 |
| 29 | `packages/ai-parrot/src/parrot/a2a/client.py` | `A2ARemoteSkillTool` / `_create_skill_input_model` | 1-15 | precedent for compiling a remote contract into a typed local tool | F019 |
| 30 | `sdd/specs/matrix-collaborative-crew.spec.md` | FEAT-195 Non-Goals | 1-60 | prior decision: rejected `m.parrot.*` pub/sub as the PRIMARY path and rejected extending `AgentCrew` with Matrix awareness | F006 |
| 31 | `sdd/specs/matrix-agents-swarm.spec.md` | FEAT-463 | 10-18, 28-50 | approved swarm spec (tunnels, hops, `answer_policy: mention|swarm|silent`) the local protocol must subsume, not duplicate | F006 |
| 32 | `sdd/specs/parrot-telemetry-event-fanout.spec.md` | `setup_event_fanout` / Overview | 80-112, 259-292 | FEAT-710/711 bus pattern: Streams transport, outbox, `event_id` dedup, dedicated instance (§8 Q2) | F006 |
| 33 | `sdd/specs/tool-call-delegate.spec.md` | FEAT-590 | 8-20 | "delegate" already means small-model tool-call planning — vocabulary collision | F015 |
| 34 | `sdd/proposals/workingmemory-toolkit.proposal.md` | `ArtifactStore` / Closed decisions D1-D8 | 11-24, 252-270 | `artifact_id@version` identity + `ArtifactStore` protocol + blob tier: the identity space the blackboard `artifacts` key should reuse | F008 |

### 2.2 Constraints Discovered

- **Matrix namespace and prior rejection.** The custom-event namespace is already `m.parrot.*` (task/result/status/feedback) with STATE events agent_card/channel/tunnel, and FEAT-195 explicitly rejected `m.parrot.*` pub/sub as the primary communication path.
  *Implication*: the Matrix carrier must extend the existing namespace (no `ai.parrot.*`), keep a human-readable body, and either route FEAT-463's tunnels through the protocol engine or justify a parallel path; room state is the natural blackboard backend.
  *Evidence*: F006

- **AgentRegistry consumers.** `AgentRegistry` is name+tag keyed and consumed by `result_agent`, `studio_runtime`, `handlers/agents/data`, bot factory tools and CLI loaders; PBAC policy collection hangs off `register()`.
  *Implication*: contract/kind/carrier/grant fields on `BotMetadata` must be additive and optional; `find_capability` is a new method, not a change to existing lookups.
  *Evidence*: F001

- **`registry.capabilities` is taken.** `parrot.registry.capabilities` already names a `CapabilityRegistry` (FEAT-070) that indexes tools/datasets by embedding, with no AGENT resource type and no exact cap-id path.
  *Implication*: either extend it (`ResourceType.AGENT` + exact/keyword index + locality ranking) or pick a distinct name; the <5 ms deterministic lookup of spike L-S3 cannot ride the embedding path.
  *Evidence*: F014, F001

- **PBAC shape.** PBAC is enforced per tool call (`PBACToolCallGuardrail`, `ResourceType.TOOL`, first guard in `ToolManager.execute_tool`) and at bot resolution (`agent_guard.enforce_agent_access`); no capability-scoped agent-to-agent grant exists.
  *Implication*: mounting a remote capability as a local tool inherits the caller-side gate for free; the serving side needs the caller's `PermissionContext` to travel in the message, and the grant is a new deterministic config, not a policy on tools.
  *Evidence*: F010, F017

- **Everything is text today.** Crew hand-off, `AgentTool`, `AgentSwarmToolkit.ask_agent`, `HybridDelegator` and `ResultRetrievalTool` are text in / text out and wake the callee LLM; there is no performative, protocol state or reply-obligation typing anywhere.
  *Implication*: the performative layer is greenfield; existing tools become origin tools that the harness maps to acts (additive, not a rewrite).
  *Evidence*: F005, F006, F004, F002, F021

- **Hop limiting exists once.** `ask_agent` propagates `hops` / `origin_session` via ContextVars and returns a `hop_limit` status; crews only have per-run `max_iterations`.
  *Implication*: the conversation hop budget should generalise the FEAT-463 mechanism rather than add a second counter.
  *Evidence*: F006, F005

- **Bus policy.** FEAT-710 decided telemetry uses a DEDICATED navigator-eventbus instance (Streams, publish-only, outbox); the RPC-on-bus pattern (`reply_to`, correlation) is not defined anywhere.
  *Implication*: an eventbus carrier is a third bus instance (or must justify sharing) and must define `reply_to` / correlation / idempotency itself, reusing the outbox + `event_id` dedup idiom.
  *Evidence*: F006, F018

- **AuditLedger schema.** `AuditLedger` is append-only and KMS-signed but its entry schema is credential-centric and `append()` requires `credential_material`; a semantic audit ledger (TASK-4474) is being built in parallel.
  *Implication*: per-performative audit lines need a new entry kind or a sibling ledger sharing the signer; coordinate with TASK-4474.
  *Evidence*: F009

- **Data plane.** WorkingMemory is a per-session pandas catalog; task_memory already defines `artifact_id@version` identity, an `ArtifactStore` protocol and a parquet blob tier; Arrow IPC/shared-memory exists only on the REPL worker boundary; no Polars in core.
  *Implication*: by-reference in-process passing and the blackboard `artifacts` key should reuse task_memory identity and the repl_worker shm ownership rules; Polars (parent D6) is a new dependency.
  *Evidence*: F008, F022

- **"delegate" is taken.** FEAT-590 tool-call-delegate owns the word (`DelegateToolNode`, `LlamaCppDelegate`, `NeedleDelegate`).
  *Implication*: the cfp origin tool needs another name or an explicit disambiguation.
  *Evidence*: F015

- **Trace carrier exists.** `TraceContext` (W3C) is carried by `FlowContext` and already propagates across an A2A hop; its class is re-exported into `parrot.core.events.lifecycle` from a dependency.
  *Implication*: the shared `trace_id` has a carrier; the protocol only threads it through envelopes and audit lines.
  *Evidence*: F003

- **Four partial directories.** `AgentRegistry` (local, name/tag), `ToolManager._registered_agents` (remote A2A cards, substring skill search), `A2AMeshDiscovery` (remote, skill/tag/search), `MatrixCrewRegistry` (per-crew roster).
  *Implication*: `find_capability` must be the unifying front, otherwise it becomes a fifth directory.
  *Evidence*: F001, F011, F019, F006

- **Test baseline.** 26 Matrix test modules, crew regression suites, `AgentRegistry` and `CapabilityRegistry` tests, working-memory tests inside the source tree.
  *Implication*: regression coverage exists for every seam the spec would touch; new behaviour needs new suites, not retrofits.
  *Evidence*: F013

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `ae7ebda977` | 2026-10-22 | Jesus Lara | feat(bots-agent-tech-debt): TASK-4617 — guard the nine post-super configure sites | `bots/a2a_agent.py`, flows |
| `0aca76bebe` | 2026-10-21 | Jesus | sdd: FEAT-710 spec rev 0.4 — Q2 dedicated EventBus instance | `sdd/specs/parrot-telemetry-event-fanout.spec.md` |
| `dc347e0dc` | 2026-10-14 | Jesus Lara | feat(a2ui-lazy-imports): TASK-4292 — server handlers defer heavy imports | `ai-parrot-server/parrot/a2a/` |
| `f638ba6fad` | 2026-09-23 | Jesus | TASK-3657 — AgentRegistry.update_agent_tooling() in-place atomic YAML rewrite | `registry/registry.py` |
| `4b15dbc4ae` | 2026-09-23 | Jesus | feat(tool-call-delegate): TASK-3631 — DelegateToolNode + factory | `bots/flows/plan/delegate/` |
| `59d1d1dfae` | 2026-09-19 | Jesus | style(matrix-agents-swarm): FEAT-463 — lint fixes | `matrix/crew/session.py` |
| `4eb5769181` | 2026-09-22 | Jesus | feat(plan-then-execute-hardening): TASK-3592 | `working_memory/tool.py` |
| `8ae42e6131` | 2026-09-08 | Jesus Lara | feat(workingmemory-toolkit): TASK-2991 — preserve plan and tee artifact provenance after dispatch | flows ↔ working memory |
| `a2381e729f` | 2026-09-08 | Jesus Lara | TASK-2997 — atomic durable aliases, versions and evidence pins | `task_memory/store/postgres.py` |
| `4723c75327` | 2026-08-26 | Jesus | fix(matrix-agents-swarm): address remaining code-review important findings | `crew/{config,session,transport,tunnel}.py` |
| `ad13833b6b` | 2026-08-26 | Jesus Lara | sdd: add spec for FEAT-463 — matrix-agents-swarm | `sdd/specs/matrix-agents-swarm.spec.md` |
| `cf98ee289` | 2026-07-10 | Jesus | feat(a2a-protocol-compatibility): TASK-1712 — v1.0 data models, core types & enums | `parrot/a2a/` |
| `0c4f5ebb5d` | 2026-05-07 | Jesus Lara | feat(botmanager-pbac-permissions): TASK-1054 — AgentRegistry.get_instance enforcement | `registry/registry.py` |

The registry has been stable since 2026-09-23; flows activity is FEAT-590 (tool-call planning), not messaging; the Matrix swarm (FEAT-463) landed 2026-08-26; nothing in 365 days of SDD history touches performatives, grants or a blackboard. *Evidence*: F001, F015, F006, F008, F016

---

## 3. Probable Scope

### What's New

- **Performative model** — all eleven acts in v0 (`inform`, `request`, `query`, `agree`, `refuse`, `failure`, `cfp`, `propose`, `accept`, `reject`, `subscribe`, plus `not_understood`) and message fields `performative` / `protocol` / `conversation_id` / `in_reply_to` / `sender` / `receivers` | capability filter, layered on the FEAT-746 envelope. The harness maps origin tools to acts (`AgentTool` → request|query; a generic send tool with a small enum). *Evidence*: F002, F021, F006
- **Protocol engine** — per-conversation state machines for all five protocols in v0 (Inform, Request, Query, Contract Net with fixed-weight scoring and a pluggable override, Subscribe); `not_understood` for out-of-state messages; timeout → `failure(TIMEOUT)`; hop budget → `failure(HOP_LIMIT)`; token budget. Modelled after the flows FSM precedent and the `ask_agent` status enum. *Evidence*: F003, F006
- **Gating dispatcher** — addressing (receivers | capability filter) → protocol state → decision-needed; a directly addressed `inform` wakes the receiver, an unaddressed one goes to a handler registry (store / blackboard update / wake only when a handler asks); the wakes-per-message metric of spike L-S1. *Evidence*: F006
- **Capability directory** — `ResourceType.AGENT` + exact cap-id/keyword index + locality/cost ranking exposed as `AgentRegistry.find_capability`; per-agent contract advertisement on the registry entry; the inter-agent grant as scoped configuration enforced by the harness. *Evidence*: F001, F014, F010
- **Blackboard** — versioned single-writer keyed store (`roster`, `definitions`, `tasks`, `digest` owned by the last agent that closed a Request when no coordinator exists, `artifacts`) with ACLs and subscriptions; in-process backend (successor to `FlowContext.shared_data` for protocol runs) and Matrix room-state backend. *Evidence*: F003, F006, F008
- **Local carriers** — in-process asyncio queue carrying the full envelope with payloads by reference; same-host Arrow IPC/shm reusing the repl_worker transport ownership rules; navigator-eventbus carrier (dedicated instance, `reply_to` / correlation / idempotency / DLQ); Matrix carrier adapter over `m.parrot.*` events with a human-readable body. *Evidence*: F022, F018, F006
- **Audit** — a performative entry kind for the signed ledger (or a sibling ledger sharing the signer), joined by `trace_id`. *Evidence*: F009, F003

### What Changes

- **`packages/ai-parrot/src/parrot/registry/registry.py`**::`BotMetadata` / `AgentRegistry` — additive contract/kind/carrier/grant fields; new `find_capability(keywords | cap_id)` ranked by locality and cost. *Evidence*: F001
- **`packages/ai-parrot/src/parrot/registry/capabilities/models.py`**::`ResourceType` — add `AGENT`, with an exact-match path beside the embedding search in `capabilities/registry.py`. *Evidence*: F014
- **`packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`**::`TaskEventContent` / `ParrotEventType` — carry the typed envelope + performative fields; blackboard keys as additional state event types. *Evidence*: F006
- **`packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`**::`AgentSwarmToolkit.ask_agent` — route through the protocol engine (Request/Query) so hops, status and correlation come from one place. *Evidence*: F006
- **`packages/ai-parrot/src/parrot/tools/agent.py`**::`AgentTool` — emit request/query performatives instead of a bare text question when the target is protocol-enabled. *Evidence*: F006
- **`packages/ai-parrot/src/parrot/bots/flows/core/context.py`**::`FlowContext` — optional blackboard binding alongside `shared_data` (`shared_data` itself unchanged). *Evidence*: F003
- **`packages/ai-parrot/src/parrot/security/audit_ledger.py`**::`AuditLedgerEntry` / `AuditLedger.append` — new entry kind (sender, receiver, performative, conversation_id, trace_id, result digest) or sibling ledger. *Evidence*: F009
- **`packages/ai-parrot/src/parrot/tools/working_memory/tool.py`**::`WorkingMemoryToolkit.store_result` — accept native objects/handles arriving from an `inform` (parent D5 seam). *Evidence*: F008

### What's Untouched (Non-Goals)

- A2A JSON-RPC client/server, `A2AMeshDiscovery` and `A2AProxyRouter` stay as the external surface; adapters come from FEAT-746.
- FEAT-590 tool-call-delegate nodes and their "delegate" vocabulary.
- `AgentCrew.run_sequential` / `run_loop` / `run_flow` behaviour and the `FlowContext.shared_data` API for existing crews (crew-to-channel mapping is an open question, not v0 scope).
- `HybridDelegator`'s visible human messages and the FEAT-195 collaborative session phases.
- `AuditLedger` credential entries and signers; the TASK-4474 semantic audit ledger.
- WorkingMemory pandas operations and task_memory durable tiers.
- FEAT-746's envelope, handles, blob store, catalog tools and policy gate (a dependency, not redefined here).

### Patterns to Follow

- `ask_agent` status enum + ContextVar hop propagation + `hop_limit`. *Evidence*: F006
- `TunnelRegistry` correlation-id futures for request/reply pairing. *Evidence*: F006
- Matrix state events replace-not-append (`agent_card` / `channel` / `tunnel`) with a `version` field on `ChannelStateContent`. *Evidence*: F006
- `PBACToolCallGuardrail` as the first guard, fail-closed, keyed by resource type + name. *Evidence*: F010, F017
- `A2ARemoteSkillTool` compiles a remote contract into a typed local tool. *Evidence*: F019
- FEAT-710 dedicated `EventBus` instance with outbox and `event_id` dedup. *Evidence*: F006, F018
- repl_worker Arrow IPC/shm ownership rules (host creates/unlinks after ACK). *Evidence*: F022
- task_memory `artifact_id@version` + `ArtifactStore` protocol for handles. *Evidence*: F008
- `ToolManager` runtime register/unregister + `clone` for per-session mounts. *Evidence*: F011, F020

### Integration Risks

- **Fifth directory**: `AgentRegistry`, ToolManager A2A cards, `A2AMeshDiscovery` and `MatrixCrewRegistry` already overlap — `find_capability` must front all four or the roster drifts. *Evidence*: F001, F011, F019, F006
- **FEAT-195 rejection**: the Matrix carrier must be framed as one carrier among four with a mandatory human body, or the prior decision revisited explicitly. *Evidence*: F006
- **Embedding cost**: `CapabilityRegistry.search` needs an embedding function — spike L-S3's <5 ms lookup needs an exact index first. *Evidence*: F014
- **Name collisions**: `registry.capabilities` (intent routing) and `delegate` (FEAT-590) — the spec must choose names up front. *Evidence*: F001, F015
- **AuditLedger.append requires credential_material** — performative audit cannot reuse `append()` as-is. *Evidence*: F009
- **FEAT-746 ordering**: envelope, handles, blob store, catalog and policy gate are reserved (proposal committed `14d4fc780`, status discussion) but not yet specified; this spec cannot close its Codebase Contract until the parent's models exist. *Evidence*: F008, F020
- **Matrix payloads are JSON dicts** (`model_dump`), not a binary envelope — the parent's protobuf envelope needs a base64/structured-fields mapping. *Evidence*: F006
- **`TraceContext` is defined outside parrot src** — envelope trace fields depend on a navigator dependency's model. *Evidence*: F003

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | No performative, speech-act, protocol state machine, Contract Net or FIPA concept exists in core, server or integrations | F002, F021 | high | repo-wide grep (0 hits for five patterns, re-probed) plus wiki query with only false positives |
| C2 | `AgentRegistry` indexes agents by name and tag only; no capability id, locality, cost or remote kind on `BotMetadata` | F001 | high | read of `BotMetadata` and the lookup API plus a zero-match grep (re-probed) |
| C3 | A `CapabilityRegistry` (embedding index of tools/datasets) lives at `parrot.registry.capabilities` and is the seam for `find_capability` | F014, F001 | high | read of models.py and registry.py; `ResourceType` has no AGENT |
| C4 | No inter-agent communication grant exists; PBAC gates tool execution (`ResourceType.TOOL`) and bot resolution only | F010, F017 | high | read of `PBACToolCallGuardrail.check` and `agent_guard`; grep for allowed_agents/can_call/inter_agent empty (re-probed) |
| C5 | No shared versioned single-writer blackboard exists; `FlowContext.shared_data` is a plain dict and `SetContextAction` its only flow-level writer | F003 | high | read of context.py and actions.py plus zero-match grep for blackboard/single_writer (re-probed) |
| C6 | No in-process by-reference or Arrow zero-copy path exists between agents; Arrow IPC/shm exists only host→REPL worker; pyarrow only for parquet; no Polars | F008, F022 | high | grep over working_memory/stores/memory (polars, shared_memory absent, re-probed) and the repl_worker transport page |
| C7 | A substantial Matrix integration exists (mautrix client, AppService, `m.parrot.*` message + state events, A2A transport, FEAT-463 swarm with tunnels, hop limit, roster, dev Synapse stack); the brainstorm's "no Matrix integration" claim is false | F006, F007 | high | 24 module files read/listed, three approved specs, docker-compose read; all symbols re-probed |
| C8 | Crew hand-off is a rendered prompt string and loop termination is LLM-evaluated; iteration caps are per run, not per conversation | F005 | high | read of `run_sequential` 1862-1876 and `run_loop` / `run_flow` signatures |
| C9 | All existing agent-calling tools (`AgentTool`, `ask_agent`, `HybridDelegator`) are text in / text out and await an answer — implicit request semantics, no inform | F006, F004 | high | read of swarm_toolkit.py and delegation.py; wiki page of tools/agent.py |
| C10 | `AuditLedger` exists, append-only and KMS-signed, but its entry schema is credential-centric and `append()` requires `credential_material` | F009 | high | read of `AuditLedgerEntry` (80-107) and `append` (338-406) |
| C11 | navigator-eventbus is already used for hooks and FEAT-710 telemetry fan-out (dedicated Streams publish-only instance with outbox), not as an agent-to-agent carrier; no `reply_to`/correlation bus pattern exists | F018, F006 | medium | grep clusters + wiki page of fanout.py; absence of `reply_to` on the bus inferred from no hits, not a targeted read of navigator-eventbus |
| C12 | `TraceContext` propagates through `FlowContext` and across an A2A hop; the class is re-exported from a dependency | F003 | medium | context.py import and an integration test; the defining module was not located |
| C13 | FEAT-195 rejected `m.parrot.*` pub/sub as the primary path and rejected extending `AgentCrew` with Matrix awareness | F006 | high | wiki page of the approved spec's Non-Goals (lines 1-60) |
| C14 | `ToolManager` can register/unregister tools at runtime and clone per session, so a `catalog.mount` needs no new lifecycle; it also hosts remote A2A cards with substring skill search | F011, F020 | high | read of manager.py line ranges, all re-probed |
| C15 | "delegate" is taken by FEAT-590 and "capabilities" by FEAT-070 intent routing | F015, F001 | high | git log + spec header read; registry tree |
| C16 | FEAT-746 (the cross-boundary parent) is in proposal, so the envelope/handle/blob/catalog/policy-gate models this proposal depends on do not exist | F008, F020, F011 | medium | absence of a handle type and mount lifecycle confirmed; the parent's status is session knowledge (id ledger, commit `14d4fc780`), not a finding |
| C17 | Spike L-S6 (Matrix carrier) can run today against docker-compose.matrix.yml; spike L-S3 cannot be met by `CapabilityRegistry.search` without an exact index | F007, F014 | medium | stack read directly; the 5 ms bound is an inference about embedding cost, not measured |

Distribution: **13** high, **4** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase, 2026-10-26)

- [x] **Matrix: custom event types under an `ai.parrot.*` namespace, or `m.room.message` with `msgtype` extensions?** — *Resolved by code*: the namespace is already `m.parrot.*` with message events (task/result/status/feedback) and state events (agent_card/channel/tunnel); `m.room.message` carries the human-readable text beside them.
  *Resolves claims*: C7, C13

- [x] **U1 — Which performative set ships in v0?** — *Resolved*: all eleven acts and all five protocols (Inform, Request, Query, Contract Net, Subscribe) ship in v0, so FEAT-463's tunnels can be subsumed in one pass.
  *Resolves claims*: C1, C9

- [x] **U2 — Matrix carrier vs the FEAT-463 swarm?** — *Resolved*: subsume. `AgentSwarmToolkit.ask_agent` becomes a Request over the protocol engine; tunnels stay as the room topology; hops, status and correlation come from one place. FEAT-195's rejection is reinterpreted, not overturned: Matrix is one carrier among four and the human-readable `body` stays mandatory.
  *Resolves claims*: C7, C13

- [x] **U3 — Where does the capability directory live?** — *Resolved*: extend `parrot.registry.capabilities`. Add `ResourceType.AGENT`, an exact cap-id/keyword index and locality/cost ranking to `CapabilityRegistry`; embedding search stays as the fallback; `AgentRegistry.find_capability` delegates to it.
  *Resolves claims*: C3, C2

- [x] **U4 — How do existing crews map onto the protocol in v0?** — *Resolved*: untouched in v0. The protocol applies to registry-discovered peers and shared channels; `AgentCrew.run_*` and `FlowContext.shared_data` stay as they are; crew-to-channel mapping is a follow-up spec.
  *Resolves claims*: C8

- [x] **U5 — In-process carrier: envelope or direct call?** — *Resolved*: keep the full envelope with payloads passed by reference inside it (Pydantic models, Arrow tables, handles). Uniform audit, gating and protocol state on every carrier; zero serialization in-process.
  *Resolves claims*: C6, C10

- [x] **Who owns `digest` in a channel with no coordinator?** — *Resolved*: the last agent that closed a Request; ownership moves with the work and the harness enforces single-writer per key version.

- [x] **Does an `inform` ever wake the receiver's LLM by default?** — *Resolved*: wake if addressed directly. An `inform` that names the receiver in `receivers` wakes it; broadcast or capability-filtered `inform`s are stored (WorkingMemory / blackboard) and wake only when a registered handler asks for a decision. The L-S1 target becomes: addressed `inform` 1 wake, unaddressed `inform` with no handler 0.

- [x] **Contract Net bid scoring?** — *Resolved*: fixed default with a pluggable override. The harness scores `propose(cost, time, confidence)` with fixed weights from contract annotations; a channel may register a scoring strategy; the requester's LLM wakes only when the rule cannot decide.

- [x] **Name: shared with FEAT-746 or a family name with two profiles?** — *Resolved*: two names, shared envelope. The FEAT-746 protocol is **Squawk** (parrot-to-parrot call across a boundary); this sub-protocol is **Roost** (where parrots of one network gather: performatives, gating, directory, blackboard, local carriers). Roost messages ride the Squawk envelope and reference it by name.

### Unresolved (defer to spec / implementation)

None. All nine questions were answered on 2026-10-26; the spec inherits them as fixed decisions.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-747`** — *Rationale*: decisions L1–L9 are fixed by the source, localization is high-confidence (C1–C10, C13–C15) and the forks U1–U5 plus the four carried questions were resolved on 2026-10-26 (§5), so the spec starts with no open architecture. **Sequence it after the FEAT-746 spec**: this spec reuses the parent's envelope, handles, blob store, catalog and policy gate, and its Codebase Contract cannot close until those models exist (C16).

### Alternatives

- **`/sdd-brainstorm FEAT-747`** — no longer needed: U2 (subsume FEAT-463) and U3 (extend CapabilityRegistry) are decided; reopen only if the FEAT-746 spec changes the envelope in a way that breaks the shared-envelope naming decision.
- **`/sdd-task FEAT-747`** — not applicable: six new subsystems across two distributions.
- **Manual review** — run spikes L-S1 (wakes per message) and L-S3 (registry lookup) as throwaway prototypes first if the medium-confidence claims C11, C16, C17 need hard numbers before the spec.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-747/state.json` |
| Source (raw) | `sdd/state/FEAT-747/source.md` |
| Research plan | `sdd/state/FEAT-747/research_plan.json` (49 queries, three lanes) |
| Findings (digests) | `sdd/state/FEAT-747/findings/F001-*.md` … `F022-*.md` (22 canonical, merged from 38 lane findings; originals in `findings/.audit/`) |
| Merge report | `sdd/state/FEAT-747/merge_report.json` |
| Citation probe | `sdd/state/FEAT-747/probe_sheet_{1..8}.json`, `probe_map.json`, `probe_results.json` |
| Synthesis (JSON) | `sdd/state/FEAT-747/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed** (profile `default`):
- Files read: 28 / 40 (codebase lane 24, git lane 4)
- Grep calls: 20 / 25
- Git calls: 6 / 10
- Wiki queries: 17 (free)
- Queries executed / skipped: 48 / 1 (Q038 a2a tree, budget)
- Wall time: the first dispatch's codebase lane never wrote findings; it was re-dispatched on resume (§4.0), so the run spanned two sessions
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs; explicit "VERIFY" list; no negation of existing behaviour).

**Parallel research**: three lanes (codebase FC-001…018, git FG-001…006, wiki FW-001…014), merged by `(path, symbol)` identity into F001…F022. State directory was created as `sdd/state/local-inter-agent/` while the id ledger was blocked by a dirty checkout and moved to `sdd/state/FEAT-747/` once FEAT-747 was reserved (commit `89ffda894`).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (FEAT-708 parallel lanes + citation probe) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara / Claude Fable 5.1 (plan and review gates auto-proceeded in the autonomous run; Q&A answered interactively on 2026-10-26 → status `review`) |
