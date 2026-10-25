---
id: FEAT-746
title: Typed binary inter-agent protocol for parrot-to-parrot cross-network calls (contract catalog, handles, policy gate, gRPC + bus)
slug: inter-agent-protocol
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-25
  summary_oneline: Typed binary inter-agent protocol for parrot-to-parrot cross-network calls (contract catalog, handles, policy gate, gRPC + bus)
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [inter-agent, protocol, grpc, handles, policy-gate, a2a]
research_state: sdd/state/FEAT-746/
created: 2026-10-26
updated: 2026-10-26
---

# FEAT-746 — Typed binary inter-agent protocol for parrot-to-parrot cross-network calls

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: artifacts/interagent/Brainstorm Inter-Agent Binary Protocol.md` (2026-10-25)
> **Audit**: [`sdd/state/FEAT-746/`](../state/FEAT-746/)
> **Sister document**: `artifacts/interagent/Brainstorm Local Inter-Agent Protocol.md` declares itself a dependent of this spec (same envelope, handles, blob store, catalog, policy gate) and has its own FEAT-ID reserved in parallel; see U4.

---

## 0. Origin

The original brainstorm is preserved verbatim at `sdd/state/FEAT-746/source.md`. Excerpt:

> Agent-to-agent traffic across a trust boundary is paying for two things it does not need: human-readable wire formats and an LLM invocation on every hop. The cost unit that matters is tokens in the receiver's context, not bytes on the wire […]
>
> What we want instead: a typed remote procedure between two ai-parrot agents that (1) degrades to deterministic RPC with zero tokens whenever the call matches a contract capability, (2) never puts raw data in any agent's context, (3) carries security and provenance as first-class fields, and (4) stays open enough that non-parrot agents can join through adapters.
>
> […] None of the following exists in ai-parrot today; the proposal must not assume them. Each is marked VERIFY so the proposal stage checks the codebase before speccing: `RemoteToolkit` and `ContractServer` · catalog tools inside ToolManager · artifact handle type and descriptor registry · capability tokens (Biscuit or macaroons) · policy gate as a reusable component · gRPC transport · envelope on the event bus · three-level telemetry join.

**Initial signals** (extracted, not interpreted):
- Verbs: "want", "expose", "degrade", "carry", "stay open", "ship", "VERIFY" → additive, a new capability (enrichment)
- Named entities: RemoteToolkit, ContractServer, ToolManager, WorkingMemory, AgentRegistry, AuditLedger, navigator-auth, navigator-eventbus, PBAC, A2A, MCP, gRPC, protobuf, Arrow IPC, Polars
- Decisions already taken in the source: D1–D14 (inputs, not open questions)
- Acceptance criteria provided: no formal ACs; six spike gates S1–S6 with pass criteria, nine open questions, a naming shortlist

---

## 1. Synthesis Summary

The brainstorm asks for a typed, binary, contract-driven RPC between two ai-parrot agents across a trust boundary, where a call matching a contract capability runs deterministically with no LLM on the serving side and results travel as handle + descriptor + provenance instead of raw data. Research confirms the whole "does not exist yet" list is accurate: today the only cross-network path is A2A over JSON/aiohttp (`parrot/a2a/client.py`), which returns the remote artifact text straight into the caller's context, and the serving side (`A2AServer`) exposes the agent's *tools* as skills behind a credential-shaped gate. Most building blocks the protocol needs do exist in core and are reusable as patterns: ToolManager's category index, search and per-provider schema compile; WorkingMemoryToolkit's "the agent never sees raw frames" summaries and its immutable, checksummed task-memory blob store; the signed append-only `AuditLedger` signers; PBAC enforcement already sitting below the LLM at tool execution; per-call usage/cost records with ContextVar attribution; and a strict Arrow-IPC frame transport. Two of the fourteen decisions rest on wrong premises: D10 (AgentRegistry registers remote agents — it does not; `A2AMeshDiscovery` and `ToolManager.register_a2a_agent` do) and D6 (Polars — absent from every pyproject; the repo is pandas + pyarrow). The gRPC/protobuf half is greenfield inside this repo (a dead `grpc_session.py` stub aside), while the one protobuf + grpc.aio server ever built here was extracted to navigator-eventbus, which also already provides correlation ids, at-least-once Streams with dedup and a DLQ but no request/reply convention. FEAT-704 (semantic layer, 0/26 tasks) has already specified owner-bound result handles, a signed ledger and a guarded hand-off sink with the same semantics — a design overlap the spec must resolve before anything is built. Recommendation: `/sdd-spec FEAT-746`, with the five scope decisions in §5 answered first and S1–S6 carried as gated Lane-0 tasks.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-746/findings/`. Each cites the finding ID(s) that justify its inclusion. Line numbers are as read on `dev` at research time (HEAD `984d3a4cb`); six citations were corrected after the probe pass and are tagged `[citation-check]` inside the findings.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/a2a/client.py` | `A2AClient`, `A2ARemoteAgentTool`, `A2ARemoteSkillTool` | 40-60, 213-310, 543-625, 695-707 | only cross-network agent-to-agent client today; JSON over aiohttp; remote artifact text returned into context; closest analogue of RemoteToolkit | F001 |
| 2 | `packages/ai-parrot-server/src/parrot/a2a/server.py` | `A2AServer`, `_build_skills_from_tools`, `_try_invoke_with_gate`, `_extract_identity` | 85-100, 961-985, 1249-1302 | serving side today: tools exposed as skills, credential-broker gate with AuditLedger entries, broker/audit_ledger/identity_mapper in the constructor | F001, F013 |
| 3 | `packages/ai-parrot/src/parrot/a2a/mesh.py` | `A2AMeshDiscovery`, `A2AEndpoint` | 73-136 | the existing remote-agent registry (YAML + env substitution, health, get_by_skill/tag) | F001, F004 |
| 4 | `packages/ai-parrot/src/parrot/a2a/router.py` | `A2AProxyRouter` | — | deterministic no-LLM gateway routing by skill/tag/regex; can mount as an A2A server | F001 |
| 5 | `packages/ai-parrot-server/src/parrot/a2a/security.py` | `A2ASecurityMiddleware`, `SecureA2AClient`, `MTLSAuthenticator`, `JWTAuthenticator` | 1409, 1682 | only in-repo precedent for "the certificate identifies the calling agent" | F001 |
| 6 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager` (`register_tool`, `unregister_tool`, `list_categories`, `get_tools_by_category`, `search_tools`, `get_tool_schemas`, `execute_tool`, `register_a2a_agent`, `share_dataframe`) | 289, 723-794, 853-860, 1313, 1404-1458, 1787-1800, 2302-2338, 2895-2937 | flat register/unregister; `_categories` is a dict index only; per-provider schema compile; guard chain on execute; seam for catalog mount/unmount | F003, F022 |
| 7 | `packages/ai-parrot/src/parrot/tools/mcp_mixin.py` | `MCPToolManagerMixin` | 31 | the mixin pattern that attaches remote (MCP) servers to ToolManager | F003, F011 |
| 8 | `packages/ai-parrot/src/parrot/mcp/integration.py` | `MCPClient`, `MCPToolProxy`, `_TRANSPORT_SESSIONS`, `MCPEnabledMixin` | 92, 363-422, 481-509, 1356 | "remote tools become local AbstractTools"; results flattened to text; no grpc transport entry | F011 |
| 9 | `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py` | `AgentMCPMount`, `_AgentBoundMCPServer._guard` | 1-16, 124-184, 265-298 | per-agent MCP endpoints gated by PBAC resource `mcp:agent:{name}:tool:{tool}` — base for the MCP adapter | F011 |
| 10 | `packages/ai-parrot-server/src/parrot/mcp/result_policy.py` | `_approx_tokens`, `resolve_cap`, `apply_size_policy`, `run_with_deadline` | 1-20, 53-134 | adapter-enforced result caps (char heuristic) + per-call deadline | F011 |
| 11 | `packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py` | `GrpcMCPSession`, `GrpcMCPConfig` | 1-32, 83-150 | abandoned client-only gRPC stub; protobuf import commented out; `mcp.proto` beside it, no generated module | F011 |
| 12 | `packages/ai-parrot-server/src/parrot/mcp/config.py` | `MCPServerConfig` (`transport`, `grpc_host`, `grpc_use_protobuf`, `quic_serialization`) | 139, 203-216 | grpc_* fields reserved; QUIC already uses msgpack | F011 |
| 13 | `packages/ai-parrot/src/parrot/registry/registry.py` | `AgentRegistry`, `BotMetadata`, `BotConfig`, `register_bot_decorator` | 50-72, 258, 526-540, 586-624, 1324 | local bots only; zero hits for remote/a2a/endpoint | F004, F016 |
| 14 | `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | `CapabilityEntry`, `ResourceType`, `RoutingDecision` | 1-5, 25-35, 48-69, 91-106 | FEAT-070 intent-router index; a different "capability" (name collision) | F005 |
| 15 | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | `WorkingMemoryToolkit` (`store`, `store_result`, `list_tool_dataframes`, `exclude_tools`) | 47-75, 89, 217, 357-425, 917-936 | "the agent NEVER sees raw DataFrames"; pandas-only; Python-only `store` path; landing zone for remote handles | F010, F015, F022 |
| 16 | `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py` | `ArtifactBlobStore`, `BlobRef`, `BlobFormat`, `DurableBlobSweeper` | 1-9, 132-148, 185-215, 382-471, 647-992, 1073 | immutable, checksummed + fingerprinted Parquet/JSON/text blobs; publish-then-reference; no byte-range read | F010, F015 |
| 17 | `packages/ai-parrot/src/parrot/interfaces/artifact_store.py` | `ArtifactStore` (Protocol), `PayloadRefusal` | — | scoped, versioned, byte-bounded artifact contract with bounded `load_payload` refusals | F010 |
| 18 | `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py` | `encode_dataframe`, `EncodedDataFrame`, `StrictTransportError`, `DEFAULT_STRICT_MAX_BYTES` | 1-7, 36, 46-56, 74-167 | Arrow IPC stream encoding, strict no-pickle; host↔worker over shared memory | F010 |
| 19 | `packages/ai-parrot/src/parrot/storage/artifacts.py` | `ArtifactStore`, `Artifact`, `ArtifactType` | 54-70, 73-204, 274-337 | unrelated conversation-artifact store (S3 overflow, signed URLs, tenant-partitioned exports) — name collision | F010, F019 |
| 20 | `packages/ai-parrot/src/parrot/security/audit_ledger.py` | `AuditLedger`, `AuditLedgerEntry`, `AbstractKMSSigner`, `LocalHMACSigner`, `AzureKeyVaultSigner` | 1-18, 80-105, 135-199, 296-346, 407-444 | signed append-only ledger; credential-shaped entry; in-memory by default; storage failures swallowed | F006 |
| 21 | `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` | `PBACToolCallGuardrail`, `PolicyDenialReport` | — | first in `execute_tool()`; navigator-auth PolicyEvaluator on TOOL / `tool:execute`; fail-closed; resource-only matching | F022, F023 |
| 22 | `packages/ai-parrot/src/parrot/auth/resolver.py` | `PBACPermissionResolver`, `AbstractPermissionResolver` | 25-65, 247-262, 289-300, 341 | Layer-2 PBAC re-check keyed by tool name | F007, F023 |
| 23 | `packages/ai-parrot/src/parrot/tools/abstract.py` | `AbstractTool.execute` | 916-954 | pops `_resolver`, calls `gates.pre_execute_refusal` before running | F007 |
| 24 | `packages/ai-parrot/src/parrot/auth/permission.py` | `PermissionContext`, `UserSession` | 21, 81 | per-request carrier (session, channel, trace_context) a remote call must populate from channel metadata | F023 |
| 25 | `packages/ai-parrot/src/parrot/auth/token_exchange.py` | `TokenExchangeClient`, `ExchangeResult` | 1-63 | navigator-auth integration is session/OAuth2 exchange; no biscuit/macaroon anywhere | F007, F017 |
| 26 | `packages/ai-parrot/src/parrot/security/redaction.py` | `ScrubPolicy` | 128 | redaction primitive for the policy gate | F007 |
| 27 | `packages/ai-parrot/src/parrot/observability/recorders/models.py` | `UsageRecord` | 22-85 | per-LLM-call tokens/cost/duration/trace_id/run_id | F009 |
| 28 | `packages/ai-parrot/src/parrot/observability/context.py` | `agent_identity`, `invocation_context`, `usage_attribution` | 1-15, 86-162 | in-process ContextVar attribution; nothing crosses a network hop | F009, F025 |
| 29 | `packages/ai-parrot/src/parrot/observability/fanout.py` | `setup_event_fanout` | 24 | FEAT-710 publish-only bus fan-out of usage events | F008, F018, F024 |
| 30 | `packages/ai-parrot/src/parrot/observability/cost/__init__.py` | `ensure_shared_cost_calculator`, `CostCalculator` | 57 | process-wide cost calculator (corrected citation) | F018, F025 |
| 31 | `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` | `TraceContext`, `LifecycleEvent`, `EventRegistry` | 18-24, 54-56 | parrot's only navigator-eventbus surface (in-process lifecycle registry) | F008, F024 |
| 32 | `packages/ai-parrot/src/parrot/clients/base.py` | `AbstractClient._apply_cache_hints` | 565-590 | provider-native cache hints; where S4 lands | F003 |
| 33 | `packages/ai-parrot/pyproject.toml` | `pyarrow`, `grpc` (extra) | 174-180, 707-712 | pyarrow hard dep; grpcio only via `navigator-eventbus[grpc]`; protobuf pinned at root 199-203; no polars anywhere | F002 |
| 34 | `docs/events/eventbus-v2.md` | `EventEnvelope`, `RedisStreamsBackend`, `GrpcIngress` | — | bus contract: correlation_id + trace_context, at-least-once + dedup + DLQ, gRPC ingress `parrot.events.v1`; no reply_to | F021, F024 |
| 35 | `sdd/specs/semantic-layer.spec.md` | `ResultHandle`, `ResultHandleStore.claim`, `SemanticAuditEntry`, `SemanticAuditLedger`, `GovernedDatasetSink`, `GovernancePipeline` | 541-590, 605-633, 634-671, 679-687 | FEAT-704's planned handles/ledger/sink with matching ACL + provenance semantics; 0/26 tasks done | F020, F026 |

### 2.2 Constraints Discovered

- **Every remote-tool path stringifies into context.** `A2ARemoteAgentTool._execute`, `A2AClient.invoke_skill` and `MCPToolProxy._extract_result_text` all return the remote payload as text/JSON to the LLM.
  *Implication*: the handle path cannot wrap them; the RemoteToolkit needs its own result route that lands handle + descriptor + provenance in WorkingMemory before anything reaches the model.
  *Evidence*: F001, F011

- **A2AServer exposes tools, not capabilities, behind a credential-shaped gate.** `_build_skills_from_tools` converts the agent's tools to skills; the gate is `CredentialBroker` per user.
  *Implication*: the serving side inverts the A2A model (contract catalog is the surface; gate keys on capability annotations). A2AServer is a pattern, not a base class.
  *Evidence*: F001, F013

- **D10 is wrong as written.** `AgentRegistry` holds local `BotMetadata`/`BotConfig` only (no kind/protocol/endpoint, zero remote hits in source or 180 days of history); remote agents live in `ToolManager.register_a2a_agent → RegisteredAgent` and `A2AMeshDiscovery`.
  *Implication*: discovery is a design decision (U2), not a reuse.
  *Evidence*: F003, F004, F016

- **AuditLedger reuse is mechanism-only.** The entry schema is fixed (user_id, channel, tool, provider, key_fingerprint); FEAT-704's TASK-4474 declines to reuse it and defines its own entry over `AbstractKMSSigner` + async storage callable; the in-memory ledger swallows storage failures.
  *Implication*: the served ledger is a new signed entry type with a fail-closed durable sink.
  *Evidence*: F006, F026

- **PBAC already sits below the LLM.** `PBACToolCallGuardrail` runs first in `execute_tool`, `PBACPermissionResolver` re-checks inside `AbstractTool.execute`; keyed by tool name; matcher is resource-only.
  *Implication*: the capability gate composes ahead of this chain; per-caller rate limits and aggregation minimums need subject-aware logic the matcher lacks.
  *Evidence*: F007, F022, F023

- **gRPC is greenfield in this repo.** `grpc_session.py` is a dead client stub (protobuf import commented out, tunnels JSON-RPC); grpcio arrives only through `navigator-eventbus[grpc]`; the protobuf + grpc.aio server built in TASK-1791 (`parrot.events.v1`) was extracted to navigator-eventbus in FEAT-312.
  *Implication*: lift the generated-stub, auth-in-metadata and "open dicts as JSON strings" conventions from navigator-eventbus; delete or replace the stub in the same feature.
  *Evidence*: F002, F011, F021, F024

- **The bus has the primitives but not the pattern.** navigator-eventbus v2: `EventEnvelope` with `correlation_id`/`trace_context`, Redis Streams at-least-once with event_id dedup and DLQ; JSON wire; no `reply_to`; parrot is publish-only today.
  *Implication*: S6 needs a bytes-safe serializer and a request/reply convention partly outside this repo.
  *Evidence*: F008, F024

- **pandas + pyarrow everywhere, Polars nowhere.** WorkingMemory summariser, Arrow transport and `share_dataframe` are pandas; pyarrow ≥ 25 is pinned; no pyproject declares polars.
  *Implication*: D6 adds a dependency and a second frame engine (U3); Arrow IPC on the wire is engine-neutral.
  *Evidence*: F002, F003, F010

- **Blob store base is close but not content-addressed.** `ArtifactBlobStore`/`BlobRef` are immutable, checksummed (`ck_`) and fingerprinted (`fp_`), publish-then-reference, but keyed by (scope, artifact_id, version); no media-type registry, TTL, ACL or affordances; `FileManagerInterface` has no byte-range or streaming read.
  *Implication*: content addressing, handle ACLs and dedup-by-digest are new; S2 streaming cannot sit on the file manager.
  *Evidence*: F010, F015, F019

- **Telemetry exists per LLM call, not per hop.** `UsageRecord` + `CostCalculator` + ContextVar attribution + FEAT-710 fan-out exist; nothing injects/extracts a trace across a network hop; deterministic tool calls emit no usage event.
  *Implication*: D13 needs a trace carrier in gRPC metadata/bus headers and a per-capability usage event on the served side.
  *Evidence*: F009, F018, F025

- **Name collisions.** Three `Artifact` types (`storage.models.Artifact`, `interfaces.artifact_store.ArtifactStore` / task-memory, `a2a.models.Artifact`) and FEAT-070's `CapabilityEntry`.
  *Implication*: the spec must pick distinct nouns for the handle and the contract capability.
  *Evidence*: F005, F010

- **S3/S4 have landing points.** `ToolSchemaAdapter` compiles per `ToolFormat` (OpenAI/Anthropic/Google/Groq/Vertex/Bedrock); `AbstractClient._apply_cache_hints` owns cache hints.
  *Evidence*: F003

- **FEAT-704 overlap is design-only.** Owner-bound `ResultHandle`/`claim`, `SemanticAuditLedger`, `GovernedDatasetSink` are specified inside the semantic satellite; 0/26 tasks started.
  *Implication*: own the shared contract in core or consume FEAT-704's (U1).
  *Evidence*: F020, F026

- **MCP adapter is nearly free.** `AgentMCPMount` + `RemoteMCPServerBase.register_tool` + `result_policy` caps map almost 1:1 onto "expose a mounted category as an MCP server".
  *Evidence*: F011

### 2.3 Recent History (Relevant)

| Area | Window | Activity | Relevance | Evidence |
|------|--------|----------|-----------|----------|
| `a2a/` (server) | 120 d, 21 commits | FEAT-272 v1.0 protocol complete 2026-07-10; since then credential-broker gate, agent-card extension + DataPart dispatch (FEAT-469), identity/PBAC wiring (TASK-2610), lazy imports (10-14) | feature-stable JSON/HTTP surface; nothing binary | F013 |
| `mcp/` | 90 d, 25+ commits | sdd-coder stdio server, expose-local-mcp-tools (HostAdapter, install/enable/disable), LSP template | transport layer untouched; install-time enable/disable is the nearest "mount" lifecycle | F014 |
| `tools/working_memory/` | 120 d, ~25 commits | Sep 8-9 rebuild (TASK-2977…3004): entry descriptors, durable journal, **immutable artifact blob I/O (TASK-2996)**, bounded recall | the brainstorm's "no blob store abstraction" line is partly contradicted | F015 |
| `registry/` | 180 d, 15 commits | AgentStudio YAML round-trip, `update_agent_tooling`, enumerator | no remote-agent/kind commit ever | F016 |
| `security/` + `auth/` | 120 d, 20+ commits | Identity Vault token sync (FEAT-735), Teams user-auth lane, scope enforcement moved into core (TASK-3989), OAuth 3LO | only OAuth/bearer/approval tokens; no attenuation | F017 |
| `observability/` | 120 d, 15 commits | FEAT-705/710 (10-19…22): tenant ContextVar, cost_usd on usage events, shared CostCalculator, `attach_bus`/`forward_to_bus` over Streams | per-call cost + bus pipeline landed days ago; cost plumbing still settling | F018 |
| `storage/` + `outputs/` | 120 d, 15 commits | PA-11/PA-12 tenant-partitioned export store + checked download (10-09); A2UI; telemetry hot tier | no content addressing, TTL or handles | F019 |
| semantic-layer spec/index | 90 d, 6 commits | spec rev 0.3 2026-10-25, 26 tasks, 0 done | handles/ledger/gate are planned, not shipped | F020 |
| protobuf/grpc anywhere | 365 d, 8 commits | TASK-1791 built `GrpcIngress` + `events.proto` (07-16); FEAT-312 moved it to navigator-eventbus the next day; OTLP gRPC exporters | the only binary transport ever built here left the repo | F021 |

---

## 3. Probable Scope

### What's New

- **Contract model and catalog** — `Capability` (cap_id, category, typed input/output, `returns: inline|artifact`, `backing: deterministic|llm_backed`, policy annotations), per-category hashing, handshake deltas, `STALE_CONTRACT` refusal. No counterpart exists; FEAT-070's `CapabilityEntry` is an intent index. *Evidence*: F005
- **Wire envelope and transport** — a `.proto` for Call / Result / Progress / typed errors, Arrow IPC batches for frames, gRPC server (serving dispatcher) and client, trace_id and identity in channel metadata. Greenfield inside this repo; conventions lifted from navigator-eventbus's `parrot.events.v1`. *Evidence*: F011, F021, F024
- **RemoteToolkit (AbstractToolkit)** with always-mounted catalog tools (`list` / `mount` / `unmount` / `search` / `find`) that register and unregister capability tool definitions in ToolManager by category, reusing `_categories`, `search_tools` and `get_tool_schemas`. *Evidence*: F003, F011
- **Handle + descriptor + provenance model**, a media-type descriptor registry (arrow, parquet, mermaid, structurizr, svg, png, pdf, generic) and a content-addressed (sha256) blob store with ACL, TTL and dedup-by-digest, built on `ArtifactBlobStore`/`BlobRef` semantics with new keying and policy. *Evidence*: F010
- **Capability policy gate** keyed by contract annotations (data class → `ScrubPolicy`, aggregation minimum, row cap, per-caller rate limit, token budget), composed ahead of `PBACToolCallGuardrail` / `PBACPermissionResolver`. *Evidence*: F007, F023
- **Served ledger** — a new signed entry type (caller, capability, args digest, policy applied, data classes, result digest, cost, backing) over `AbstractKMSSigner` with a fail-closed durable sink. *Evidence*: F006, F026
- **Local affordance tools** over handles (`df.query` / `df.sample` / `df.join` / `chart.from_df`) with toolkit-enforced materialization caps; engine per U3.
- **Cross-hop trace propagation** (caller-generated trace_id in gRPC metadata and bus headers) and a per-capability usage/cost event for deterministic calls on both sides. *Evidence*: F009, F025
- **Remote-agent discovery entry** with kind (`a2a` | native) and endpoint — placement per U2.
- **Adapters at the edge** — A2A (contract → agent card; artifacts degrade to A2A artifacts) and MCP (mounted category → `AgentMCPMount`-style server; artifacts → resources). Later milestone. *Evidence*: F001, F011
- **Attenuated capability tokens** with navigator-auth — spike S5; nothing exists in parrot or its history. *Evidence*: F007, F017

### What Changes

- **`packages/ai-parrot/src/parrot/tools/manager.py`::`ToolManager`** — category-level mount/unmount of tool definitions (lazy loading of a mounted category into the client-facing schema set); remote entries gain a protocol kind if U2 chooses this path. *Evidence*: F003, F022
- **`packages/ai-parrot/src/parrot/tools/working_memory/tool.py`::`WorkingMemoryToolkit`, `WorkingMemoryCatalog`** — entries carry provenance, media_type and affordances; RemoteToolkit uses the Python-only `store` path. *Evidence*: F010, F015
- **`packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`::`ArtifactBlobStore`, `BlobRef`** — extended with a content-addressed key + ACL/TTL, or used as the primitive under a new blob-store facade. *Evidence*: F010
- **`packages/ai-parrot/src/parrot/registry/registry.py`::`AgentRegistry`, `BotConfig`** — only if U2 selects it: remote-agent kind + endpoint. *Evidence*: F004, F016
- **`packages/ai-parrot/src/parrot/a2a/mesh.py`::`A2AMeshDiscovery`, `A2AEndpoint`** — only if U2 selects it: protocol kind on endpoints. *Evidence*: F001, F004
- **`packages/ai-parrot/src/parrot/observability/recorders/models.py`::`UsageRecord`** — a per-capability record for deterministic calls (tokens may be 0; ms, rows, backing, cap_id). *Evidence*: F009
- **`packages/ai-parrot/pyproject.toml`** — grpcio + grpcio-tools (today only via `navigator-eventbus[grpc]`); polars only if U3 adopts it. *Evidence*: F002
- **`packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py`** + `mcp.proto` — delete or replace the dead stub so one gRPC implementation exists. *Evidence*: F011

### What's Untouched (Non-Goals)

- A2A JSON-RPC/REST surface and AgentCard discovery (FEAT-272) — stays as the inbound `kind=a2a` path and adapter target.
- MCP transports (stdio/http/streamable-http/sse/unix/websocket/quic), `MCPClient`, `MCPToolProxy` — the MCP adapter is additive.
- `parrot/clients/base.py` beyond consuming the existing `_apply_cache_hints` hook in S4.
- Existing `AuditLedger`/`AuditLedgerEntry` schema and the `CredentialBroker` gate — reused via the signer contract only.
- FEAT-704 semantic-layer tasks and the `ai-parrot-semantic` satellite — only the shared-contract decision (U1) touches them.
- navigator-eventbus and navigator-auth internals — outside this repo; the spec records what it needs from them (reply_to convention, bytes-safe serializer, attenuated tokens).
- Conversation `ArtifactStore` (`parrot/storage/artifacts.py`) and the A2UI structured-artifact contract.
- Free-form agent conversation, agent dialects, KV-cache exchange, replacing MCP/A2A — brainstorm non-goals.

### Patterns to Follow

- Remote tools become local `AbstractTool`s via a proxy class registered in ToolManager (`MCPToolProxy`, `A2ARemoteSkillTool`); the RemoteToolkit's capability tools keep the shape and change the result route. *Evidence*: F001, F011
- Own entry model + core signers + async storage callable, fail-closed when required (FEAT-704 `SemanticAuditLedger` over `AbstractKMSSigner`). *Evidence*: F006, F026
- Guardrail-first enforcement in `execute_tool` with sanitized denial reports (`PBACToolCallGuardrail` / `PolicyDenialReport`); `POLICY_DENIED` reports the same way. *Evidence*: F022, F023
- Publish-then-reference, checksum + fingerprint, bounded page reads, strict no-pickle Arrow IPC (`ArtifactBlobStore`, `repl_worker/transport.py`). *Evidence*: F010
- Per-agent mount with canonical PBAC resource names (`AgentMCPMount` mirroring `A2AServer.setup()`) for the MCP adapter. *Evidence*: F011
- Protobuf service with explicit version field, auth in RPC metadata, open dicts as JSON strings (navigator-eventbus `parrot.events.v1`, formerly TASK-1791). *Evidence*: F021, F024
- "Mirror the invariant subset of a draft external spec; quarantine wire compatibility behind an adapter" (FEAT-322) for the A2A/MCP adapters. *Evidence*: F027

### Integration Risks

- **Contract duplication with FEAT-704**: two handle/provenance/ledger definitions if the shared contract is not placed first. *Mitigation*: resolve U1 before `/sdd-spec`; make the shared models the first milestone here or in FEAT-704. *Evidence*: F020, F026
- **Two frame engines** (pandas in WorkingMemory/transport vs Polars in affordance tools). *Mitigation*: resolve U3; keep Arrow IPC as the only wire format so the engine choice stays local. *Evidence*: F002, F010
- **Bus carrier depends on navigator-eventbus** (binary payload serializer, reply_to) and grpcio versions must stay in lockstep with its `[grpc]` extra. *Mitigation*: S6 as a cross-repo spike; declare grpc deps through one extra. *Evidence*: F002, F024
- **Large-artifact streaming cannot use `FileManagerInterface`** (no byte-range/streaming). *Mitigation*: stream Arrow batches over gRPC into the blob-store writer; S2 covers it. *Evidence*: F010
- **Heavy dependencies in core** (grpcio, grpcio-tools, protobuf runtime, optional polars). *Mitigation*: resolve U5; server/transport half outside core behind an extra. *Evidence*: F002, F012
- **Resource-only PBAC matcher** cannot express per-caller limits or k-anonymity. *Mitigation*: caller-keyed limits live inside the capability gate, not in navigator-auth policies. *Evidence*: F023
- **Name collisions** (`Artifact` ×3, `ArtifactStore` ×2, `Capability`). *Mitigation*: fix nouns in the spec. *Evidence*: F005, F010
- **Dead gRPC stub drift** next to a second implementation. *Mitigation*: delete or replace in the same feature. *Evidence*: F011

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | A2A (JSON/aiohttp, free text in, artifact text out) is the only cross-network path and lands the raw payload in context | F001, F013 | high | client/server read; `_execute` returns `artifacts[0].parts[0].text` |
| C2 | No gRPC server, generated protobuf or typed envelope in ai-parrot; `grpc_session.py` is dead; grpcio only via `navigator-eventbus[grpc]` | F002, F011, F021 | high | stub read; no `*_pb2` in packages; extra re-verified at core pyproject:712 |
| C3 | ToolManager has flat register/unregister and a dict category index, no mount/unmount lifecycle | F003, F022 | high | manager.py read; only static `exclude_tools` exists |
| C4 | AgentRegistry has no remote agents or protocol kind; remote registries are `RegisteredAgent` and `A2AMeshDiscovery` — D10 is wrong | F003, F004, F016 | high | registry.py scan 0 hits; history has no remote-kind commit |
| C5 | WorkingMemoryToolkit already keeps raw frames out of context and has an immutable task-memory blob substrate; pandas-only; no provenance/affordances | F010, F015 | high | tool.py/internals.py/blob.py read; TASK-2996 in history |
| C6 | AuditLedger exists but is credential-shaped; the pattern is a new entry model reusing the signers | F006, F026 | high | audit_ledger.py read; TASK-4474 declines reuse for the same reason |
| C7 | PBAC is enforced below the LLM at execution, keyed by tool name, resource-only matching; no capability-annotation gate | F007, F022, F023 | high | resolver.py + abstract.py read; pbac.py outline |
| C8 | No attenuated capability tokens exist; auth is OAuth2/JWT/mTLS via navigator-auth and A2A security | F007, F017, F023 | high | repo-wide grep empty; 120 days of auth history |
| C9 | navigator-eventbus v2 has correlation/trace, at-least-once + dedup + DLQ, but no reply_to; parrot is publish-only | F008, F018, F024 | medium | contract from docs via wiki; bus publish module read skipped on budget; code outside repo |
| C10 | A protobuf + grpc.aio server pattern (`parrot.events.v1`, auth in metadata) exists in navigator-eventbus and is reusable as convention | F021, F024 | medium | inferred from TASK-1791/1804 completion notes; current source not read |
| C11 | Per-call usage/cost/trace_id with ContextVar attribution exists; nothing propagates a trace across a hop; deterministic calls emit no usage event | F009, F018, F025 | medium | presence direct; absence inferred from A2A headers and pages read |
| C12 | pyarrow is a hard dep with a strict Arrow-IPC transport; Polars absent everywhere | F002, F010 | high | pyproject greps re-verified 2026-10-26; transport.py read |
| C13 | `ArtifactBlobStore`/`BlobRef` are immutable + checksummed but not content-addressed; no media-type registry, TTL, ACL; no byte-range read beneath | F010, F015 | high | blob.py docstrings and fields read |
| C14 | `MCPToolProxy`/`MCPClient` and `AgentMCPMount` (+ result caps) are the closest precedents for RemoteToolkit and the MCP adapter | F011 | high | integration.py, agent_mount.py, result_policy.py read |
| C15 | FEAT-704 specifies owner-bound `ResultHandle`/claim, `SemanticAuditLedger`, `GovernedDatasetSink`; 0/26 tasks started | F020, F026 | high | spec sections read; index shows 0 done |
| C16 | `ToolSchemaAdapter` compiles per provider and `_apply_cache_hints` owns cache hints, so S3/S4 have landing points | F003 | high | ToolFormat enum and clients/base.py hook read |
| C17 | A2A security's `MTLSAuthenticator`/`JWTAuthenticator` are the only precedent for identifying a calling agent by certificate | F001 | medium | names from lazy exports and line citations; security.py not read |
| C18 | Three `Artifact` types and FEAT-070's `Capability` collide with the protocol's nouns | F005, F010 | high | all four modules cited |
| C19 | Nothing in the brainstorm's "does not exist yet" list exists; two nuances (dead gRPC stub; task-memory blobs/descriptors partially cover the blob-store item) | F003, F004, F006, F007, F010, F011, F021, F024 | medium | aggregate absence claim across a truncated run |
| C20 | The sister "Local Inter-Agent Protocol" brainstorm depends on this spec and reuses its envelope, handles, blob store, catalog and policy gate | — | low | seen in `artifacts/interagent/` at source resolution, not by a finding; bounds U4 |

Distribution: **14** high, **5** medium, **1** low. Overall **medium** — bounded by scope confidence (U1–U5 unresolved) and by the truncated research run, not by localization.

---

## 5. Open Questions

### Resolved (during proposal phase)

*None yet — the five unknowns below were not put to the user in this run (autonomous resume from `research_complete`); answers will be promoted here and the status moved to `review`.*

### Unresolved (defer to spec / implementation)

- [ ] **U1 — Where does the shared handle / provenance / signed-ledger contract live?** Defined in core by FEAT-746 with FEAT-704 (0/26 tasks) refactored to consume it, or FEAT-746 consumes FEAT-704's planned `ResultHandle`/`SemanticAuditLedger`? — *Owner*: tbd
  *Blocks claims*: C6, C13, C15
  *Plausible answers*: a) FEAT-746 owns the contract in core; FEAT-704 amended to import it · b) FEAT-704 lands its models first (semantic satellite) and FEAT-746 depends on and generalizes them · c) both keep their own for now; converge via a later refactor feature

- [ ] **U2 — Discovery (D10 is wrong as written).** Extend `AgentRegistry`/`BotConfig` with a remote-agent kind + endpoint, or build endpoint resolution on `A2AMeshDiscovery` / `RegisteredAgent`? — *Owner*: tbd
  *Blocks claims*: C4
  *Plausible answers*: a) extend AgentRegistry/BotConfig (`kind: local | a2a | native`, endpoint) so one registry answers "who serves X" · b) extend A2AMeshDiscovery/A2AEndpoint with a protocol kind; AgentRegistry stays local · c) new contract-aware discovery component with adapters to both

- [ ] **U3 — Frame engine for the local affordance tools.** D6 says Polars; the repo is pandas + pyarrow, Polars absent. — *Owner*: tbd
  *Blocks claims*: C5, C12
  *Plausible answers*: a) Polars for the new `df.*` tools only; Arrow IPC bridges to the pandas summariser · b) pandas + Arrow IPC for v0, Polars as an optional engine later · c) Polars everywhere incl. migrating the WorkingMemory summariser

- [ ] **U4 — v0 scope and ordering.** Is FEAT-746 the parent that lands before the sister Local spec, and does v0 include the bus carrier (S6, partly in navigator-eventbus) or gRPC point-to-point only? — *Owner*: tbd
  *Blocks claims*: C9, C20
  *Plausible answers*: a) gRPC only in v0; bus carrier is v1 after S6; Local spec depends on v0 · b) both carriers in v0 because the Local spec needs the bus from day one · c) bus first, gRPC second

- [ ] **U5 — Package placement** for the heavy halves (gRPC server, protobuf stubs, blob backend, optional Polars), and whether to delete the dead `grpc_session.py`/`mcp.proto` stub here. — *Owner*: tbd
  *Blocks claims*: C2, C14
  *Plausible answers*: a) contract models + RemoteToolkit client in core; server/transport in ai-parrot-server behind a `[grpc]` extra; delete the stub · b) new satellite distribution for both halves; core only gets the handle contract; delete the stub · c) everything in core behind extras; stub left for a separate cleanup

Carried over from the brainstorm, not blocking the spec (recorded for §8 of the spec): native transport choice (gRPC vs Cap'n Proto vs Arrow Flight — default gRPC + Arrow IPC, Flight only if S2 shows a win), capability-token format (S5), blob-store location per network, descriptor persistence across sessions, promotion-loop ownership, LLM-driven vs orchestrator-driven `catalog.mount`, minimum `.proto` for v0, and the protocol's name (Perch / Squawk / Tether / Beak / Roost / CAP).

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-746`** — *Rationale*: the source already is the brainstorm (D1–D14 decided; alternatives considered and rejected in-document), so `/sdd-brainstorm` would be the wrong lane; localization is high-confidence (C1–C8, C12–C16) and the remaining forks are scope and placement decisions (U1–U5) that the spec's §8 can carry, with S1–S6 as gated Lane-0 tasks (the FEAT-571 pattern). Overall confidence stays medium only because the research run was truncated and the bus/auth halves live outside this repo. Answer U1, U2 and U5 before running the spec; U3 and U4 can be §8 open questions.

### Alternatives

- **`/sdd-brainstorm FEAT-746`** — if the D10/D6 corrections and the FEAT-704 overlap reopen the architecture (e.g. "consume FEAT-704 first" changes the milestone order enough to want options on the table again).
- **Manual review** — read `sdd/state/FEAT-746/findings/F021`, `F024`, `F026` first if you want to challenge the navigator-eventbus and FEAT-704 dependencies before speccing; the research was truncated (files_read cap, wall time exceeded).
- **`/sdd-task`** — not applicable (not a localized fix; research truncated).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-746/state.json` |
| Source (raw) | `sdd/state/FEAT-746/source.md` |
| Research plan (60 queries, 3 lanes) | `sdd/state/FEAT-746/research_plan.json` |
| Findings (27 merged digests) | `sdd/state/FEAT-746/findings/F001-*.md` … `F027-*.md` |
| Lane originals (38, archived) | `sdd/state/FEAT-746/findings/.audit/` |
| Merge report | `sdd/state/FEAT-746/merge_report.json` |
| Citation probes (185 checks, 5 sheets) | `sdd/state/FEAT-746/probe_sheet_*.json`, `probe_report_*.json`, `probe_map.json` |
| Synthesis (JSON) | `sdd/state/FEAT-746/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 37 / 40
- Grep calls: 22 / 25
- Git calls: 10 / 10
- Wall time: 535.5s / 300s (lanes were allowed to finish rather than failed)
- Truncated: **yes** — codebase lane hit its files_read cap (24/24); Q044 (eventbus publish module) skipped, covered by F008 + F024.

**Citation probe triage**: 130 verified, 6 ambiguous (overloaded method names — line ranges disambiguate), 49 "missing" of which 6 were real and are tagged `[citation-check]` in F001, F006, F007, F021, F024, F025 (two corrected citations added); the rest were probe-sheet artifacts re-verified inline on 2026-10-26 (see F002 notes).

**Mode determination**: `auto` → resolved to `enrichment` (plan `mode_hint`; additive verbs; no broken behaviour).

**Provenance of the state directory**: research ran on 2026-10-25 under `sdd/state/inter-agent-protocol/` (FEAT-ID deferred because `reserve_ids` refused on a dirty main checkout); FEAT-746 was reserved on 2026-10-26 and the directory moved.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (resumed from `research_complete`) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (Claude Code, Fable 5.1) |
