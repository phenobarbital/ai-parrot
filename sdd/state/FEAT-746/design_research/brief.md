<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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


The brainstorm asks for a typed, binary, contract-driven RPC between two ai-parrot agents across a trust boundary, where a call matching a contract capability runs deterministically with no LLM on the serving side and results travel as handle + descriptor + provenance instead of raw data. Research confirms the whole "does not exist yet" list is accurate: today the only cross-network path is A2A over JSON/aiohttp (`parrot/a2a/client.py`), which returns the remote artifact text straight into the caller's context, and the serving side (`A2AServer`) exposes the agent's *tools* as skills behind a credential-shaped gate. Most building blocks the protocol needs do exist in core and are reusable as patterns: ToolManager's category index, search and per-provider schema compile; WorkingMemoryToolkit's "the agent never sees raw frames" summaries and its immutable, checksummed task-memory blob store; the signed append-only `AuditLedger` signers; PBAC enforcement already sitting below the LLM at tool execution; per-call usage/cost records with ContextVar attribution; and a strict Arrow-IPC frame transport. Two of the fourteen decisions rest on wrong premises: D10 (AgentRegistry registers remote agents — it does not; `A2AMeshDiscovery` and `ToolManager.register_a2a_agent` do) and D6 (Polars — absent from every pyproject; the repo is pandas + pyarrow). The gRPC/protobuf half is greenfield inside this repo (a dead `grpc_session.py` stub aside), while the one protobuf + grpc.aio server ever built here was extracted to navigator-eventbus, which also already provides correlation ids, at-least-once Streams with dedup and a DLQ but no request/reply convention. FEAT-704 (semantic layer, 0/26 tasks) has already specified owner-bound result handles, a signed ledger and a guarded hand-off sink with the same semantics — a design overlap the spec must resolve before anything is built. Recommendation: `/sdd-spec FEAT-746`, with the five scope decisions in §5 answered first and S1–S6 carried as gated Lane-0 tasks.

---

### Constraints and goals
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

### Recommended option / probable scope
### What's New

- **Contract model and catalog** — `Capability` (cap_id, category, typed input/output, `returns: inline|artifact`, `backing: deterministic|llm_backed`, policy annotations), per-category hashing, handshake deltas, `STALE_CONTRACT` refusal. No counterpart exists; FEAT-070's `CapabilityEntry` is an intent index. *Evidence*: F005
- **Wire envelope and transport** — a Cap'n Proto schema for Contract / Call / Result / Progress / typed errors (full v0 envelope including cancellation propagation and `PARTIAL` partial artifacts, per Q12), Arrow IPC batches for frames, a Cap'n Proto RPC server (serving dispatcher) and client, trace_id and identity in call metadata (Q6: Cap'n Proto chosen over the gRPC default). Greenfield inside this repo; the version-field and auth-in-metadata conventions of navigator-eventbus's `parrot.events.v1` still apply, its grpc.aio code does not. *Evidence*: F011, F021, F024
- **RemoteToolkit (AbstractToolkit)** with always-mounted catalog tools (`list` / `mount` / `unmount` / `search` / `find`) that register and unregister capability tool definitions in ToolManager by category, reusing `_categories`, `search_tools` and `get_tool_schemas`. *Evidence*: F003, F011
- **Handle + descriptor + provenance model**, a media-type descriptor registry (arrow, parquet, mermaid, structurizr, svg, png, pdf, generic) and a content-addressed (sha256) blob store with ACL, TTL and dedup-by-digest, built on `ArtifactBlobStore`/`BlobRef` semantics with new keying and policy. *Evidence*: F010
- **Capability policy gate** keyed by contract annotations (data class → `ScrubPolicy`, aggregation minimum, row cap, per-caller rate limit, token budget), composed ahead of `PBACToolCallGuardrail` / `PBACPermissionResolver`. *Evidence*: F007, F023
- **Served ledger** — a new signed entry type (caller, capability, args digest, policy applied, data classes, result digest, cost, backing) over `AbstractKMSSigner` with a fail-closed durable sink. *Evidence*: F006, F026
- **Local affordance tools** over handles (`df.query` / `df.sample` / `df.join` / `chart.from_df`) with toolkit-enforced materialization caps; pandas + Arrow IPC in v0, Polars as an optional engine later (U3).
- **Bus carrier in v0** (U4): the same envelope published on navigator-eventbus with `reply_to`, correlation and dedup by `idempotency_key`; needs a bytes-safe serializer and a request/reply convention in navigator-eventbus — spike S6 is a v0 gate. *Evidence*: F008, F024
- **Cross-hop trace propagation** (caller-generated trace_id in RPC metadata and bus headers) and a per-capability usage/cost event for deterministic calls on both sides. *Evidence*: F009, F025
- **Remote-agent discovery in AgentRegistry/BotConfig** (U2): `kind: local | a2a | squawk` + endpoint on `BotMetadata`/`BotConfig` so one registry answers "who serves X"; `A2AMeshDiscovery` stays as the A2A-specific health/mesh layer. *Evidence*: F004, F016
- **Promotion loop, agent-proposed / human-approved** (Q10): the served ledger aggregates LLM-backed calls per capability and args shape; a serving-side agent drafts the deterministic capability (typed I/O + tool binding) and a human approves it into the contract.
- **Mount policy** (Q11): the planner pre-mounts categories from intent with no LLM turn, and the catalog tools stay available so the model can mount/unmount mid-conversation; S4 verifies prompt-cache behaviour.
- **Adapters at the edge** — A2A (contract → agent card; artifacts degrade to A2A artifacts) and MCP (mounted category → `AgentMCPMount`-style server; artifacts → resources). Later milestone. *Evidence*: F001, F011
- **Biscuit capability tokens** issued and attenuated by navigator-auth (Q7) — spike S5; nothing exists in parrot or its history. *Evidence*: F007, F017
- **New satellite distribution** (U5) owning both the client and server halves of the protocol (Cap'n Proto schema and RPC, dispatcher, blob-store backends); core receives only the shared handle contract once FEAT-704 lands it (U1) plus the ToolManager/WorkingMemory/AgentRegistry seams. *Evidence*: F002, F012

### What Changes

- **`packages/ai-parrot/src/parrot/tools/manager.py`::`ToolManager`** — category-level mount/unmount of tool definitions (lazy loading of a mounted category into the client-facing schema set); remote entries gain a protocol kind if U2 chooses this path. *Evidence*: F003, F022
- **`packages/ai-parrot/src/parrot/tools/working_memory/tool.py`::`WorkingMemoryToolkit`, `WorkingMemoryCatalog`** — entries carry provenance, media_type and affordances; RemoteToolkit uses the Python-only `store` path. *Evidence*: F010, F015
- **`packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`::`ArtifactBlobStore`, `BlobRef`** — extended with a content-addressed key + ACL/TTL, or used as the primitive under a new blob-store facade. *Evidence*: F010
- **`packages/ai-parrot/src/parrot/registry/registry.py`::`AgentRegistry`, `BotConfig`** — remote-agent kind (`local | a2a | squawk`) + endpoint (U2). *Evidence*: F004, F016
- **`packages/ai-parrot/src/parrot/a2a/mesh.py`::`A2AMeshDiscovery`, `A2AEndpoint`** — untouched by U2; may gain a read-through from AgentRegistry later. *Evidence*: F001, F004
- **`packages/ai-parrot/src/parrot/observability/recorders/models.py`::`UsageRecord`** — a per-capability record for deterministic calls (tokens may be 0; ms, rows, backing, cap_id). *Evidence*: F009
- **`packages/ai-parrot/pyproject.toml`** — no grpcio and no polars added to core (U3, U5); the satellite declares `pycapnp`, `pyarrow` and its blob backends. *Evidence*: F002
- **`packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py`** + `mcp.proto` — delete the dead stub in this feature (U5). *Evidence*: F011

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

- **Schedule dependency on FEAT-704** (U1: FEAT-704 lands its `ResultHandle` / `SemanticAuditLedger` first, inside the semantic satellite; FEAT-746 consumes and generalizes them). FEAT-704 has 0/26 tasks done and its built branch is salvage-only, so FEAT-746's handle milestone cannot start until FEAT-704 M8/M9b merge. *Mitigation*: the spec declares an explicit dependency on FEAT-704 TASK-4474/TASK-4476 and orders transport, catalog and gate milestones first; the shared models must be importable from core (or a neutral package), not only from `ai-parrot-semantic`. *Evidence*: F020, F026
- **Cap'n Proto RPC in Python** (Q6): the brainstorm itself notes weaker Python support; `pycapnp` is the only maintained binding, its asyncio RPC layer is younger than grpc.aio, and no precedent exists in this repo or in navigator-eventbus (whose server is grpc.aio). *Mitigation*: spike S2 is re-scoped to "Arrow IPC batches over Cap'n Proto RPC with cancellation and partials" and becomes a hard v0 gate; keep the schema transport-neutral so a gRPC fallback is a transport swap, not a redesign. *Evidence*: F011, F021
- **Bus carrier in v0 depends on navigator-eventbus** (U4): bytes-safe payload serializer and a `reply_to` request/reply convention do not exist there yet. *Mitigation*: S6 becomes a v0 gate with a navigator-eventbus change request; gRPC ingress versions are no longer a concern because the native transport is Cap'n Proto. *Evidence*: F008, F024
- **Large-artifact streaming cannot use `FileManagerInterface`** (no byte-range/streaming). *Mitigation*: stream Arrow batches over the RPC into the blob-store writer; S2 covers it. *Evidence*: F010
- **Per-deployment blob backend** (Q8): local-disk and object-storage implementations behind one blob-store interface double the storage test matrix. *Mitigation*: content-hash key, ACL and TTL live in the interface; backends only move bytes. *Evidence*: F010
- **New satellite distribution** (U5): one more package to version and release (see the 0.29.0 satellite bootstrap pattern); import-path discipline (PEP 420 namespace) must keep the handle contract in core. *Evidence*: F002, F012
- **Resource-only PBAC matcher** cannot express per-caller limits or k-anonymity. *Mitigation*: caller-keyed limits live inside the capability gate, not in navigator-auth policies. *Evidence*: F023
- **Name collisions** (`Artifact` ×3, `ArtifactStore` ×2, `Capability`). *Mitigation*: fix nouns in the spec. *Evidence*: F005, F010
- **Dead gRPC stub drift** next to a second implementation. *Mitigation*: delete or replace in the same feature. *Evidence*: F011

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/a2a/client.py
packages/ai-parrot-server/src/parrot/a2a/server.py
packages/ai-parrot/src/parrot/a2a/mesh.py
packages/ai-parrot/src/parrot/a2a/router.py
packages/ai-parrot-server/src/parrot/a2a/security.py
packages/ai-parrot/src/parrot/tools/manager.py
packages/ai-parrot/src/parrot/tools/mcp_mixin.py
packages/ai-parrot/src/parrot/mcp/integration.py
packages/ai-parrot-server/src/parrot/mcp/agent_mount.py
packages/ai-parrot-server/src/parrot/mcp/result_policy.py
packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py
packages/ai-parrot-server/src/parrot/mcp/config.py
packages/ai-parrot/src/parrot/registry/registry.py
packages/ai-parrot/src/parrot/registry/capabilities/models.py
packages/ai-parrot/src/parrot/tools/working_memory/tool.py
packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py
packages/ai-parrot/src/parrot/interfaces/artifact_store.py
packages/ai-parrot/src/parrot/tools/repl_worker/transport.py
packages/ai-parrot/src/parrot/storage/artifacts.py
packages/ai-parrot/src/parrot/security/audit_ledger.py
packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py
packages/ai-parrot/src/parrot/auth/resolver.py
packages/ai-parrot/src/parrot/tools/abstract.py
packages/ai-parrot/src/parrot/auth/permission.py
packages/ai-parrot/src/parrot/auth/token_exchange.py
packages/ai-parrot/src/parrot/security/redaction.py
packages/ai-parrot/src/parrot/observability/recorders/models.py
packages/ai-parrot/src/parrot/observability/context.py
packages/ai-parrot/src/parrot/observability/fanout.py
packages/ai-parrot/src/parrot/observability/cost/__init__.py
packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py
packages/ai-parrot/src/parrot/clients/base.py
packages/ai-parrot/pyproject.toml
docs/events/eventbus-v2.md
sdd/specs/semantic-layer.spec.md

### Questions still open in the exploration document
- [ ] **Shared-contract import path under U1**: FEAT-704 plans its models inside `ai-parrot-semantic`; the spec must decide whether they move to core or to a neutral package so the Squawk satellite can import them without depending on the whole semantic layer. — *Owner*: `/sdd-spec FEAT-746`, with FEAT-704's owner.
- [ ] **navigator-eventbus change request for U4/S6**: bytes-safe payload serializer and a `reply_to` request/reply convention — outside this repo. — *Owner*: tbd.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
