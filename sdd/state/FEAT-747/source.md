---
kind: file
jira_key: null
file_path: "artifacts/interagent/Brainstorm Local Inter-Agent Protocol.md"
fetched_at: 2026-10-25T22:37:00Z
summary_oneline: Local inter-agent protocol — FIPA-style performatives, interaction protocols, LLM-free gating, capability registry, blackboard, local carriers (sister of the cross-boundary binary protocol)
parent_spec_state: sdd/state/inter-agent-protocol/
---

# Brainstorm: Local Inter-Agent Protocol (sister spec, name TBD)

Oct 25, 2026 · @Jesus Lara

Dependent sister of Doc: same envelope, handles, blob store and catalog; this spec adds speech acts, interaction protocols and gating for agents that share a trust domain.

## Problem statement

Inside one trust domain, ai-parrot agents still talk to each other through serialized JSON text and an LLM turn on both ends. An agent that has been granted inter-agent communication should be able to look up who can answer, call them, and receive a typed result it can use directly, with an LLM turn only where a decision is needed.

Two things the cross-boundary spec does not cover and this one adds:

- **Intent as a typed field.** A message that says *inform agent B of this* should let B act on it with no acknowledgement and no formal reply; a *request* obliges a reply; a *call for proposals* opens a negotiation. Without that field every message costs the receiver an LLM turn just to find out what is being asked of it.
- **Many agents, one conversation.** In a shared channel (an event-bus topic, a Matrix room with humans and agents, a crew) every message would otherwise wake every agent. Speech acts plus addressing plus protocol state let the harness decide who wakes, without an LLM.

Dependency: this spec reuses the parent's envelope, artifact handles, blob store, catalog tools and policy gate. It does not redefine them; it adds a performative layer, interaction protocols and local transports.

## Driving flow: the salary question

&#91;embedded content: driving flow: salary question across three local agents\]

Agent A is asked for an employee's salary. It has been granted inter-agent communication, so its harness searches AgentRegistry by capability (no LLM), mounts `hr.people.salary` as a tool, and the LLM calls it like any other tool. The HR agent's dispatcher takes the deterministic path: policy gate, Workday tool, typed struct back. The result is an `inform` carrying the struct and its provenance; it lands in Agent A's WorkingMemory as a native object, never as JSON text. Agent A's second and last LLM turn answers the user. Had the result been large, step 6 would carry a handle and the bytes would go to the shared blob store.

## Decisions taken

| # | Decision | Rationale |
| --- | --- | --- |
| L1 | Dependent sister of the cross-boundary spec: same envelope, handles, blob store, catalog, policy gate | One wire format for both; this spec only adds what local collaboration needs |
| L2 | Take from FIPA-ACL the speech acts, the interaction protocols and the threading fields; drop BDI semantics, SL/KIF content languages, formal ontologies and the JADE platform model | Those three parts solve real problems for LLM agents; the rest was built for symbolic agents |
| L3 | The performative is a typed field chosen by the harness (from the tool the LLM used, or a small-enum structured output), never free text the LLM writes | The LLM proposes, the deterministic layer decides and routes |
| L4 | `inform` carries no reply obligation; the receiver acts on it internally with no acknowledgement to the sender | The stated motivating case; also kills courtesy loops |
| L5 | Results travel as native objects (Pydantic models, Arrow tables, handles), never as JSON text in a message body | The receiver uses the data, it does not read it |
| L6 | AgentRegistry is the capability directory for local agents too: an agent granted inter-agent communication searches it by capability, not by agent name | Reuses the existing registry; the caller does not need to know who answers |
| L7 | Gating without an LLM: performative + addressee + protocol state decide which agents wake | In a shared channel this is the cost driver |
| L8 | Shared context lives in a blackboard with a single writer per key, not in the message stream | Agents read state, not transcript |
| L9 | Matrix is one carrier, chosen when humans share the channel; the event bus is the default carrier; in-process is the fast path | Carrier choice does not change the protocol |

## Performatives

Eleven acts cover what LLM agents actually do to each other. Each one fixes two things the harness needs before any LLM runs: whether a reply is owed, and whether the receiver's LLM wakes at all.

| Performative | Meaning | Reply owed | Wakes receiver LLM | Typical origin tool |
| --- | --- | --- | --- | --- |
| `inform` | here is a fact or result, act on it as you see fit | no | only if the receiver has a handler that needs a decision | `report`, result of any call |
| `request` | do this capability with these args | yes: `agree`/`refuse`, then `inform`/`failure` | no for deterministic capabilities; yes for LLM-backed ones | mounted capability tool |
| `query` | what is the value of X | yes: `inform`/`failure` | same as request | `ask_agent` |
| `agree` | I will do it | no | no | harness |
| `refuse` | I will not (policy, budget, capacity) | no | no | policy gate |
| `failure` | I tried and failed, typed error | no | the original requester, to replan | dispatcher |
| `cfp` | call for proposals for a task | yes: `propose`/`refuse` | yes, for agents whose capabilities match | `delegate` |
| `propose` | I can do it, under these terms (cost, time, confidence) | yes: `accept`/`reject` | no | bid handler |
| `accept` / `reject` | decision on a proposal | `accept` starts a request; `reject` ends the thread | no | harness |
| `subscribe` | send me `inform`s matching this filter | no | no | `watch` |
| `not_understood` | message does not match any protocol state | no | no | harness |

Rules:

- Every message carries `performative`, `protocol`, `conversation_id`, `in_reply_to`, `sender`, `receivers` (or a capability filter for broadcast), plus the parent spec's envelope fields.
- The LLM never emits the performative as text. It calls a tool; the toolkit maps the tool to the act. A generic `send` tool exposes a small enum when no specific tool fits.
- An `inform` with no matching handler is stored (WorkingMemory, blackboard) and never answered.
- Content is a native object or a handle; `body` text exists only on carriers where humans read (Matrix).

## Interaction protocols

A protocol is a state machine the harness enforces per `conversation_id`; the LLM is never asked to remember where a conversation stands. Five cover v0.

| Protocol | Sequence | Terminal states | Use |
| --- | --- | --- | --- |
| Inform | `inform` | done | fire-and-forget facts, results, notifications |
| Request | `request` → `agree` or `refuse` → `inform` or `failure` | informed, refused, failed, cancelled, timed out | the salary case; any capability call |
| Query | `query` → `inform` or `failure` | same as Request, without the `agree` step | cheap lookups |
| Contract Net | `cfp` → N × `propose` or `refuse` → one `accept`, others `reject` → Request | awarded then as Request; no bids; cancelled | delegation when more than one agent could do the task |
| Subscribe | `subscribe` → N × `inform` → `cancel` | cancelled, expired | watching a blackboard key or a capability's output |

State is small and deterministic: a message out of state is answered with `not_understood` and logged; it never reaches an LLM. Timeouts come from the parent envelope's `budget.ms`; a timed-out Request emits `failure(TIMEOUT)` to the requester so it can replan. Contract Net takes a bid window and a scoring rule the harness applies (cost, time, confidence from the `propose`); the LLM of the requester is woken only if the rule cannot decide.

## Gating and dispatch

The harness answers three questions per incoming message, in order, without an LLM: is this for me, does the protocol state accept it, and does handling it require a decision.

1. **Addressing.** `receivers` names agents; a capability filter (`cap: hr.people.*`) broadcasts to whoever advertises it in AgentRegistry. Anything else in a shared channel is ignored by agents and read by humans only.
2. **Protocol state.** Out-of-state messages get `not_understood`. Closed conversations accept nothing.
3. **Decision needed?** A `request` for a deterministic capability runs the tool. An `inform` goes to a handler: store, update blackboard, or wake the LLM if a handler registered for that content type asks for it. A `cfp` wakes the LLM only if bidding needs judgement; a fixed-price capability bids from its contract annotations.
4. **Loop termination.** No performative obliges a reply to an `inform`, `agree`, `refuse`, `failure`, `accept` or `reject`; courtesy replies are impossible by construction. Each conversation has a hop budget; exceeding it closes it with `failure(HOP_LIMIT)`.
5. **Budget.** Every wake consumes the conversation's token budget from the parent envelope; a conversation that exhausts it closes.

The metric is wakes per message in a shared channel: with N agents and no gating it is N; the target is 1 for addressed traffic and the number of capability matches for broadcast.

## AgentRegistry as capability directory

AgentRegistry already registers agents by decorator and knows remote agents and their kind. This spec extends the entry, not the mechanism.

- Each registered agent advertises its contract (categories, capability ids, category hashes, `returns`, `backing`) alongside its kind: `local`, `remote` (parent spec), `a2a`.
- `registry.find_capability(keywords | cap_id)` returns matching agents ranked by locality (in-process, same host, same network, remote) and by advertised cost.
- An agent is granted inter-agent communication by configuration, with a scope (`hr.*`, `*`); the grant is a deterministic gate, never a model-exposed parameter.
- The lookup is harness-side and costs no tokens; the result is mounted into the caller's ToolManager through the parent spec's `catalog.mount`, so the LLM sees the remote capability as a plain tool.
- The registry entry is what Contract Net broadcasts against: a `cfp` with a capability filter reaches exactly the agents whose entries match.

The registry remains the single source of who exists and what they can do; the blackboard holds what they are currently doing.

## Local transports

The envelope is the parent spec's; what changes locally is how little serialization it needs.

| Locality | Carrier | Payload passing | Notes |
| --- | --- | --- | --- |
| In-process | asyncio queue between agent instances | by reference: Pydantic models and Arrow tables passed as objects, zero copy | fast path for crews and sub-agents; shared prompt-cache prefix when the same model serves both |
| Same host | navigator-eventbus (local) or Unix socket | Arrow IPC over shared memory or mmap'd blob store; envelope as protobuf | no pickle across sandbox boundaries |
| Same network | navigator-eventbus | protobuf envelope; handles into the network blob store; bytes only on first fetch | the default for most deployments |
| Shared channel with humans | Matrix room | event `content` holds the typed envelope (base64 protobuf or structured fields); `body` holds the human-readable rendering | JSON on the wire is accepted here because humans read it |

Rules:

- A result never becomes JSON text in a message body on the first three carriers; it is an object, an Arrow table or a handle.
- The bus pattern follows the parent spec: `correlation_id`, `reply_to`, idempotency key, dead-letter topic.
- Carrier choice is a deployment setting per registry entry; the protocol and the performatives are identical on all four.

## Shared context: the blackboard

Agents in a collaboration read state, not transcript. The blackboard is a key-value store scoped to a conversation or a channel where each key has one writer; it replaces "read the last 200 messages" with "read the five keys that matter".

- Keys for v0: `roster` (agents present, capabilities, carrier), `definitions` (contract hashes in use), `tasks` (open Contract Net awards and Request states), `digest` (facts established, decisions, open questions, each with provenance), `artifacts` (handles produced in this conversation).
- Single writer per key: `roster` and `definitions` by the harness, `tasks` by the protocol engine, `digest` by a designated agent (the coordinator if one exists, else the last agent that closed a Request), `artifacts` by whoever produced the handle. Writes carry a version; a stale write is refused, never merged.
- Agents `subscribe` to keys; a key change is an `inform` with the new value, which is how an agent learns something without reading the channel.
- The blackboard is the stable prompt prefix: when the same model serves several agents, the rendered blackboard goes first in every prompt and provider prompt caching does the rest.

Matrix maps onto this directly: room state events are the blackboard (one event type per key, replaced not accumulated), timeline events are the messages, `m.relates_to` is `in_reply_to`, and a federated room is a channel across two homeservers. In-house, the same keys live in the blob store's index with the same single-writer rule.

## Security inside one trust domain

Same network does not mean same privilege. The salary question is the example: Agent A is inside the network and still must not get a salary unless policy says so.

- The inter-agent communication grant is per agent and scoped by capability pattern; it is configuration, enforced by the harness, never visible to the model.
- The serving agent's policy gate runs for local callers exactly as for remote ones: caller identity (per-session ToolManager identity), capability, data class, redaction, row caps. Locality changes transport, not policy.
- Delegation inherits attenuation: an agent awarded a task through Contract Net receives a token no wider than the requester's.
- Blackboard keys carry ACLs; `digest` and `artifacts` may hold handles whose bytes the reader still needs a capability to fetch.
- Audit: every performative is a line in the serving agent's AuditLedger and in the caller's received ledger, with the shared `trace_id` from the parent spec. A shared channel with humans adds the human-readable `body` to the same event, so the audit and the chat are one record.

## Does NOT exist yet

None of this is in ai-parrot today. VERIFY each against the codebase at proposal stage.

- Performative field and protocol engine. VERIFY: agents exchange messages through crews and A2A; no speech-act typing, no per-conversation state machine.
- Capability search in AgentRegistry. VERIFY: AgentRegistry registers agents and remote agents by kind; it does not index capabilities or rank by locality.
- Inter-agent communication grant with capability scope. VERIFY: no such configuration; PBAC covers tool access, not agent-to-agent calls.
- Blackboard with single-writer keys and subscriptions. VERIFY: WorkingMemory is per agent; no shared versioned key-value with ACLs.
- In-process by-reference passing of Arrow tables between agent instances. VERIFY: no zero-copy path; results are serialized today.
- Matrix carrier. VERIFY: no Matrix integration exists (Telegram, Slack, Teams, WhatsApp do).
- Everything listed as missing in the parent spec (envelope, handles, blob store, catalog tools, policy gate, capability tokens).

## Open questions

- [ ] Is eleven performatives the right v0 set, or does v0 ship with `inform`, `request`, `query`, `failure` and add Contract Net later?
- [ ] Who owns `digest` in a channel with no coordinator: last closer, a rotating owner, or a dedicated scribe agent?
- [ ] Does an `inform` ever wake an LLM by default, or only when a handler is registered for its content type?
- [ ] Scoring rule for Contract Net bids: fixed weights from contract annotations, or a pluggable strategy per crew?
- [ ] Should the in-process carrier bypass the envelope entirely (direct method call with the performative as a parameter) or keep it for uniform audit?
- [ ] How do existing crews map onto this: is a crew a channel with a coordinator, and do crew steps become Requests?
- [ ] Matrix: custom event types under an `ai.parrot.*` namespace, or `m.room.message` with `msgtype` extensions for compatibility with ordinary clients?
- [ ] Name, shared with the parent spec or a family name with two profiles (cross-boundary, local).

## Spike gates before proposal

| Spike | Question it answers | Pass criterion |
| --- | --- | --- |
| L-S1 Wakes per message | With 5 agents in one channel, how many LLM wakes does each message cause with gating vs without? | Addressed `request`: 1 wake; broadcast `cfp` with 2 matching capabilities: 2 wakes; `inform` with no handler: 0 |
| L-S2 Inform without reply | Does an `inform` reach the receiver, update its WorkingMemory or blackboard key, and produce no outbound message? | Zero outbound messages, state updated, audit line written |
| L-S3 Registry capability search | Can AgentRegistry answer `find_capability('salary')` with the HR agent and its category hash in under 5 ms, with no LLM? | Measured, deterministic, mounts the capability through `catalog.mount` |
| L-S4 By-reference Arrow in-process | Can two agent instances in one process pass a Polars frame without a copy and keep it addressable by handle? | Same buffer address on both sides; handle resolves in the blob index |
| L-S5 Blackboard single writer | Do two agents writing the same key with stale versions get one accepted and one refused, with subscribers informed once? | Exactly one write lands; exactly one `inform` per subscriber |
| L-S6 Matrix carrier | Can a typed envelope ride a custom Matrix event with a human-readable `body`, and can room state hold the blackboard keys? | Ordinary client shows readable text; agents parse the envelope; state event replaces, not appends |
