# Brainstorm: Inter-Agent Binary Protocol (name TBD)

Oct 25, 2026 · @Jesus Lara

## Problem statement

Agent-to-agent traffic across a trust boundary is paying for two things it does not need: human-readable wire formats and an LLM invocation on every hop. The cost unit that matters is tokens in the receiver's context, not bytes on the wire; A2A (JSON-RPC, agent cards, free-text tasks) and plain REST+JSON optimize neither.

Driving scenario: an ai-parrot agent inside an HR network has Workday and other HR systems as tools. By policy, those tools are never exposed. An external ai-parrot agent on another network needs curated answers (headcount by department, manager of X, a dataframe or a C4 diagram) through a public endpoint. Today that means A2A or REST: JSON serialization on both ends, the raw payload landing in the external agent's context, and an LLM on the internal side interpreting every request.

What we want instead: a typed remote procedure between two ai-parrot agents that (1) degrades to deterministic RPC with zero tokens whenever the call matches a contract capability, (2) never puts raw data in any agent's context, (3) carries security and provenance as first-class fields, and (4) stays open enough that non-parrot agents can join through adapters.

## Goals and non-goals

Goals:

- End-to-end efficiency measured in receiver tokens and wall-clock latency, in that order.
- Deterministic fast path: a call that matches a contract capability runs the tool and returns typed data with no LLM on the serving side.
- Raw data never enters an agent context: results travel as handle + descriptor + provenance; bytes go to a blob store.
- Security boundary as a design input: the serving agent exposes capabilities, never its tools; policy is enforced below any LLM.
- Same envelope works as point-to-point RPC and as event-bus traffic consumed by a subscriber.
- Open spec: a non-parrot client (plain gRPC, an A2A or MCP adapter) can consume a contract.

Non-goals:

- Human readability on the wire. Humans read the audit log, which renders any envelope.
- A new "agent dialect" (STE100-style or learned codes). Models are trained on natural language and tokenizers differ per provider; a dialect tuned for one hurts another.
- Latent-state or KV-cache exchange between agents. Requires identical weights and is research-stage; out of scope.
- Replacing MCP or A2A inside ai-parrot. They stay as integration surfaces; this protocol targets parrot-to-parrot cross-network calls and offers adapters outward.
- Free-form conversation between agents. Multi-turn needs are modelled as specific tools with structured input and output.

## Decisions already taken

These came out of the 2026-10-25 discussion and are inputs to the proposal, not open questions.

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | Binary, typed, streaming transport; usable as RPC and as event-bus traffic | Removes JSON-RPC envelope and serialization; long operations stream; same envelope on both paths |
| D2 | Human readability lives only in the audit log | Agents do not need readable traffic; auditors do, and the log renders any envelope |
| D3 | Results are handle + provenance; raw data never enters an agent context | Token cost is the real cost; a descriptor costs \~100-200 tokens, the payload costs zero |
| D4 | A blob store shares handles between agents on the same network | Handles compose across hops without re-entering any context |
| D5 | Remote results land in the WorkingMemory toolkit as references | The consuming agent operates on the handle through local deterministic tools |
| D6 | Polars for dataframe operations; tools export native data, never JSON | Arrow IPC is zero-copy, cross-language and already the sandbox-safe choice over pickle |
| D7 | Every data artifact carries a sample (preview) in its descriptor | Models reason poorly over bare metadata; a few rows let the LLM choose the next query |
| D8 | Categorized catalog with list, mount, unmount (per category or per tool), search and find; all as tools inside ToolManager | The catalog can grow without loading everything; the external LLM sees mounted capabilities as ordinary tools |
| D9 | Minimize LLM use on the serving side; no free-text `ask()` with free-text output | Prompt-injection surface; if an LLM is needed for a multi-turn operation, it is a specific tool with structured input and structured output |
| D10 | AgentRegistry is the discovery path; it already registers remote agents and their kind (A2A or this protocol) | Reuses the existing registry/decorator pattern |
| D11 | Policy and authorization are a layer of their own, enforced at tool execution | Probabilistic components propose; deterministic components decide |
| D12 | Budget and cost accounting on every call and result | Chargeback per caller and the promotion metric (LLM-backed vs deterministic calls) |
| D13 | Telemetry at three levels: served (internal), received (external), and shared cross-boundary trace linking both | Each side keeps its own ledger; the shared trace joins them |
| D14 | Open spec with A2A/MCP adapters for non-parrot agents | Interoperability is a stated goal; adapters live at the edge, the core stays typed |

## Architecture overview

&#91;embedded content: architecture: two networks, one typed envelope across the boundary\]

The external LLM only ever sees mounted capabilities as ordinary tools and the handles that come back. The serving side runs a deterministic dispatcher with policy enforced below any LLM, and writes every call to a signed audit ledger. AgentRegistry tells the RemoteToolkit which remote agents exist and which protocol each speaks.

## Contract and catalog

The contract is the only thing shared across the boundary: a versioned, hashed catalog of capabilities grouped by category. It is exchanged once per version and cached; after that, calls carry only `contract_hash` + field numbers.

Capability (the unit of the contract):

- `cap_id` (e.g. `hr.reports.headcount_by_dept`), `category`, short description, typed input, typed output.
- `returns`: `inline<struct>` or `artifact<media_type>` so the RemoteToolkit knows before calling what arrives and words the tool description for the external LLM accordingly.
- `backing`: `deterministic` or `llm_backed`. LLM-backed capabilities still have typed input and structured output; the backing is a serving-side detail the caller can see in cost.
- Policy annotations: data class, redaction rule, aggregation minimum, row cap, cacheable + ttl, per-caller rate limit.

Catalog tools (all inside ToolManager, always mounted):

- `catalog.list()` returns categories, one line each.
- `catalog.mount(category | cap_id)` and `catalog.unmount(...)` load or drop tool definitions from the external LLM's context.
- `catalog.search(keywords)` and `catalog.find(cap_id)` return definitions without mounting.

Versioning:

- Hash per category, not per catalog: a change in `hr.reports` does not invalidate the cache of `hr.people`.
- Handshake carries the client's known hashes; the server answers with deltas only.
- A call with a stale hash is refused with `STALE_CONTRACT` and the current category definition.
- Additive changes (new capability, new optional field) keep the major version; removals and type changes bump it and carry a deprecation window.

Discovery: AgentRegistry registers remote agents with their kind (`a2a`, this protocol) and endpoint; the RemoteToolkit resolves the endpoint from there.

## Data model: handles, descriptors, blob store

A result is either an inline struct or an artifact. An artifact is a handle plus a descriptor; the bytes travel once and land in the receiving network's blob store, never in a context.

| Field | Content | Who reads it |
| --- | --- | --- |
| `key` | content hash (sha256) of the bytes | blob store, dedup, cache |
| `media_type` | registered type: `arrow`, `parquet`, `mermaid`, `structurizr`, `svg`, `png`, `pdf` | RemoteToolkit routing |
| `size`, `ttl` | bytes and retention | blob store GC |
| `descriptor` | type-specific: for arrow, rows, columns with dtypes, 3-row preview; for C4, level, elements, relations, DSL text | the external LLM (100-200 tokens) |
| `provenance` | serving agent, capability, contract hash, policy applied, timestamp | audit, citation, promotion loop |
| `affordances` | local tools that accept this handle (`df.query`, `df.describe`, `c4.render`) | the external LLM |

WorkingMemory integration: the RemoteToolkit stores handle + descriptor + provenance in the WorkingMemory toolkit under `key`; the LLM references it by key in later tool calls. Local deterministic tools (`df.query(key, expr)`, `df.sample(key, n)`, `df.join(key_a, key_b, on)`, `chart.from_df(key)`) run in Polars and return new handles, so derived data also stays out of context.

Blob store rules:

- Content-addressed; a repeated call with equal args produces the same key and no transfer.
- Handshake can advertise known digests so the server skips bytes the client already holds.
- ACL on handles: a key is not a bearer; reading requires the capability that produced it or an explicit grant.
- Encrypted at rest when the data class demands it (HR data does).
- Bytes cross the boundary exactly once; inside a network, agents share by key.
- Materialization caps: `df.sample` has a row cap, `df.to_text` a token cap, enforced by the toolkit, not the prompt.

Unknown media types are stored with a generic descriptor (size, type, provenance) and no affordances.

## Security and policy

The serving agent exposes capabilities, never tools; the policy gate sits between the dispatcher and the internal tools and is the only place where decisions are made. This follows the standing invariant: probabilistic components propose, deterministic components decide.

Identity and authorization:

- mTLS between peers; the certificate identifies the calling agent and its network.
- Capability tokens that attenuate: a token scoped to `hr.reports.*` can be delegated to a sub-agent with a narrower scope, never a wider one. Candidates: Biscuit, macaroons. Issued by navigator-auth.
- Token travels in channel metadata, not in the payload, so the payload schema stays identity-free.

Enforcement at tool execution, below any LLM:

- Redaction by data class, aggregation minimum (no row-level HR data below k rows), row caps, per-caller and per-capability rate limits, token budget for LLM-backed capabilities.
- An LLM-backed capability receives typed args; any free text in them is treated as data. Its tools are the contract capabilities, never the raw internal tools.
- Output of an LLM-backed capability passes the same policy gate as a deterministic one.

The external side applies its own caps on materialization (sample rows, text tokens) so a confused external LLM cannot dump a frame into its own context.

Every decision of the gate is a line in the audit ledger: caller, capability, policy applied, data classes returned, result digest.

## Transport and messaging semantics

One envelope, two carriers: point-to-point gRPC for request/response, and the same envelope published on the event bus for subscribers. The wire is protobuf; dataframes ride as Arrow IPC record batches.

Envelope (minimum fields):

- Call: `cap_id`, `contract_hash`, typed `args`, `out_hints`, `budget` (tokens, ms, rows), `trace_id`, `correlation_id`, `idempotency_key`, `reply_to` (bus only).
- Result: `status`, `oneof data { inline, artifact }`, `provenance`, `cost` (tokens, ms, rows), `trace_id`, `correlation_id`.
- Progress (streaming): `op_id`, `phase`, `partial artifact` when the capability yields batches.

Semantics:

- Unary for deterministic capabilities; server-streaming for long or LLM-backed ones, with `op_id`.
- Cancellation propagates: a client cancel reaches the running tool, and a cancelled op reports `CANCELLED` with partial cost.
- Idempotency: retries carry the same `idempotency_key`; the server dedups within a window.
- Bus delivery is at-least-once; consumers dedup by `idempotency_key`; undeliverable results go to a dead-letter topic.
- Timeouts are explicit in `budget.ms`; the server refuses up front what it cannot serve within budget.
- Max message size and chunking: large artifacts stream as batches; no single frame above the configured cap.

Typed errors (no free text as the primary signal): `STALE_CONTRACT` (carries the current category), `POLICY_DENIED`, `BUDGET_EXCEEDED`, `UNAUTHORIZED`, `UNKNOWN_CAPABILITY`, `PARTIAL` (stream cut, partial artifact attached), `CANCELLED`, `UPSTREAM_FAILED`. Each may carry a short `detail` string for the audit log.

Transport alternatives considered: Cap'n Proto RPC (capabilities as first-class objects, promise pipelining; weaker Python support), Arrow Flight (gRPC specialised for dataframes; worth a spike for artifact transfer), plain CBOR over the bus (simpler, loses typed schema).

## Telemetry and audit at three levels

Each side keeps its own ledger; a shared trace joins them. Nothing in the ledgers requires the other side's cooperation to be complete.

| Level | Owner | Records | Purpose |
| --- | --- | --- | --- |
| Served | serving agent | caller identity, capability, args digest, policy applied, data classes returned, result digest, cost, backing (deterministic or LLM) | compliance, promotion loop, chargeback |
| Received | calling agent | remote agent, capability, contract hash, handle key, descriptor, cost, what the LLM did with the handle afterwards | debugging the consumer, token accounting |
| Shared | both, via `trace_id` | OpenTelemetry spans crossing the boundary, correlation ids, timings per hop | end-to-end latency, joining the two ledgers in an incident |

Rules:

- `trace_id` is generated by the caller and propagated through gRPC metadata and bus headers; the server adds its spans under it.
- The served ledger is the signed, append-only AuditLedger already defined for ai-parrot; it is separate from episodic memory.
- The human-readable view is a renderer over the served ledger plus the envelope schema: any stored envelope can be printed. This is where readability lives, nowhere else.
- Cost is reported per call and aggregated per caller and per capability. The ratio of LLM-backed to deterministic calls is the protocol's efficiency metric and drives promotion of recurring LLM-backed requests into deterministic capabilities.

## Interoperability

The contract and envelope are an open spec; ai-parrot ships the reference implementation and the adapters live at the edge.

- Parrot to parrot: native, full feature set (handles, blob store, streaming, attenuated tokens).
- Non-parrot gRPC client: consumes the `.proto` directly; gets typed calls and artifacts as bytes, no WorkingMemory integration.
- A2A adapter: exposes a contract as an A2A agent card and maps tasks to capabilities; artifacts degrade to A2A artifacts (inline or by URL). Lossy on streaming semantics and policy annotations.
- MCP adapter: exposes a mounted category as an MCP server; each capability becomes an MCP tool; artifacts degrade to MCP resources. Useful for non-parrot agent runtimes and for IDE clients.
- Inbound: AgentRegistry already registers A2A agents; a remote agent of kind `a2a` is called through the existing A2A client, so mixed fleets work from day one.

What the adapters cannot offer and the spec should state: attenuated delegation, handle ACLs, per-category hashing and cancellation semantics are native-only unless the peer implements the spec.

## Does NOT exist yet

None of the following exists in ai-parrot today; the proposal must not assume them. Each is marked VERIFY so the proposal stage checks the codebase before speccing.

- `RemoteToolkit` and `ContractServer` classes. VERIFY: no contract-based toolkit; MCP and A2A clients exist and are the closest patterns.
- Catalog tools (`catalog.list/mount/unmount/search/find`) inside ToolManager. VERIFY: ToolManager registers tools; no mount/unmount lifecycle per category.
- Artifact handle type and descriptor registry. VERIFY: WorkingMemory holds values; no handle + descriptor + provenance structure, no blob store abstraction.
- Capability tokens (Biscuit or macaroons). VERIFY: navigator-auth issues OAuth 2.1 tokens; attenuation is not implemented.
- Policy gate as a reusable component. VERIFY: PBAC exists for some paths; a gate keyed by capability annotations does not.
- gRPC transport in ai-parrot. VERIFY: MCP runs over stdio, HTTP, Unix socket and QUIC; A2A over HTTP; no protobuf-defined envelope.
- Envelope on the event bus. VERIFY: navigator-eventbus carries events; the RPC-on-bus pattern (reply\_to, correlation) is not defined.
- Three-level telemetry join. VERIFY: AuditLedger exists; cross-boundary trace propagation does not.

## Open questions

- [ ] gRPC vs Cap'n Proto vs Arrow Flight for the native transport. Default: gRPC + protobuf, Arrow IPC for frames; Flight only if the spike shows a clear win for artifact transfer.
- [ ] Capability token format: Biscuit or macaroons, and how navigator-auth issues and attenuates them.
- [ ] Where the blob store lives on each network: local disk with mmap, S3/EFS, or a Redis-backed index over object storage.
- [ ] Does the external WorkingMemory keep descriptors across sessions, or only for the session that fetched them?
- [ ] Promotion loop ownership: who curates LLM-backed requests into deterministic capabilities, and is there tooling for it.
- [ ] Should `catalog.mount` be LLM-driven (the model decides) or orchestrator-driven (the agent's planner decides before the turn)?
- [ ] Minimum `.proto` for v0: contract, call, result, progress, error. What is deliberately left out of v0?
- [ ] Is the same-host, same-vLLM variant (shared prefix cache, in-process handles) a separate spec, as discussed, or a profile of this one?
- [ ] Name of the protocol.

## Spike gates before proposal

Each spike is small, has a measurable outcome, and blocks the proposal stage until done.

| Spike | Question it answers | Pass criterion |
| --- | --- | --- |
| S1 Token accounting | How many tokens does the external LLM spend per call with handle + descriptor vs inline JSON result? | Descriptor path under 250 tokens for a 10k-row frame; inline path measured for comparison |
| S2 Arrow over gRPC | Can a Polars frame stream as Arrow IPC batches over gRPC with cancellation and partial results? | 100 MB frame streams, cancel mid-way leaves a `PARTIAL` with valid batches |
| S3 Contract to tool defs | Can a protobuf-described capability be compiled to a tool definition the LLM clients (Gemini, Claude, OpenAI, Groq) accept? | One contract, four providers, same calls succeed |
| S4 Mount/unmount | Does mounting a category mid-conversation work with each provider's tool API and prompt caching? | Mount adds definitions without breaking the cached prefix on at least two providers |
| S5 Attenuated token | Can navigator-auth issue a Biscuit (or macaroon) scoped to a category and attenuate it for a sub-agent? | Delegated token calls `hr.reports.*`, is refused on `hr.people.*` |
| S6 Envelope on the bus | Does the call/result envelope survive navigator-eventbus with correlation, reply\_to and dedup? | Request on the bus, result consumed by the right subscriber, duplicate dropped |

## Naming candidates

The name should say "typed contract between agents across a boundary" and avoid clashing with A2A, MCP, ACP or Arrow Flight. Candidates to discuss; none chosen yet.

| Candidate | Reading | Note |
| --- | --- | --- |
| Perch | where a parrot lands; a fixed, contracted point of contact | short, on-brand, no protocol with that name |
| Squawk | parrot-to-parrot call | playful; may read as noise rather than contract |
| Tether | a bounded link between two agents | conveys the trust boundary; generic word |
| Beak | the interface a parrot exposes | short; weak on meaning |
| Roost | shared place where parrots of one network gather (blob store + registry) | fits the same-network side more than the cross-boundary call |
| CAP (Contracted Agent Procedure) | descriptive acronym | clashes with the CAP theorem |
