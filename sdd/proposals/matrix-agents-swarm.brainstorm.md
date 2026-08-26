---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Matrix Agents Swarm

**Date**: 2026-08-25
**Author**: Jesus Lara / AI-Parrot Team
**Status**: exploration
**Recommended Option**: A (+ D as optional add-on)

---

## Problem Statement

`parrot.integrations.matrix` already ships two completed features:

- **FEAT-044 `integrations-matrix-multi`** — N agents on one homeserver via the
  Application Service protocol (`MatrixAppService`, virtual MXIDs), a shared room +
  one private room per agent, `@mention` routing (`MatrixCrewTransport`), a
  coordinator bot with a pinned status board, and an A2A bus built on custom
  `m.parrot.{agent_card,task,result,status}` events (`MatrixA2ATransport`).
- **FEAT-195 `matrix-collaborative-crew`** — `!investigate <question>` starts a
  phased *investigate → cross-pollinate → synthesize* session
  (`MatrixCollaborativeSession`) with reply-to threading and peer tool delegation
  (`HybridDelegator`).

What is still missing to call the integration an **agents swarm**:

1. **Channels as first-class objects.** Today rooms are created ad hoc by the
   transport (`general` + per-agent). There is no notion of a *public* or
   *private channel of agents* that an operator declares, that agents join/leave,
   and whose membership defines who answers.
2. **Agent ↔ agent conversations.** `MatrixA2ATransport` can push a task and await
   a result, but it is not exposed to the agent's LLM as a tool, and there is no
   dedicated, discoverable **private tunnel** (2-member room) where two agents
   exchange *structured* payloads (question / answer / feedback) out of the
   humans' sight. `HybridDelegator` only covers tool delegation.
3. **Swarm answers.** A plain (un-mentioned) human message in a channel is
   ignored unless it starts with `!investigate`. The collaborative session is
   single-instance per room, so two humans cannot ask at the same time.
4. **Humans from other networks.** Nobody can reach the swarm from Slack, Signal,
   Discord, Instagram, e-mail or XMPP — the compose file only starts a bare
   Synapse, no bridges and no client.
5. **No documented client story.** Developers testing the crew have to pick a
   Matrix client on their own.

**Affected users**: operators deploying agent teams on Matrix, developers of
ai-parrot, and end users who reach the swarm through Matrix or a bridged network.

## Constraints & Requirements

- Build on FEAT-044 / FEAT-195 — no rewrite of `MatrixCrewTransport`,
  `MatrixAppService` or `MatrixCollaborativeSession`; existing `@mention` and
  `!investigate` behaviour stays backward compatible.
- Async-only (`mautrix` client, no blocking I/O); Pydantic models for every
  payload; Google docstrings + type hints.
- Structured outputs between agents are **Matrix events** (`m.parrot.*`
  namespace) so they remain auditable and federation-ready; no side channel
  (Redis/HTTP) for the tunnel.
- Agents remain virtual users of one AppService on one homeserver (federation
  and E2EE stay out of scope, as in FEAT-044).
- Humans arriving through bridges are treated exactly like native humans.
- Homeserver: **Synapse** (AGPL-3.0, runs as an isolated container — no linking
  with MIT ai-parrot code). Bridges: best-available per platform, licence noted
  per bridge; the compose file is **dev/local only** (no TLS/workers).
- Flooding protection: a swarm answer must not produce N uncoordinated replies to
  every message in a busy bridged room.
- Landing on `dev` as a regular feature.

---

## Options Explored

### Option A: Channel Registry + Private-Room Tunnel on top of `m.parrot.*` events (extend FEAT-195)

Introduce a **channel model** (`MatrixChannel`: name, visibility
public/private, member agents, answer policy) declared in `matrix_crew.yaml` and
materialised by the transport at startup (room creation, aliases, join rules,
`m.parrot.channel` state event with the policy). A **tunnel** is a
two-member private room lazily created between agent A and agent B
(`MatrixAgentTunnel`), cached in a registry, where `m.parrot.task` /
`m.parrot.result` events (plus a new `m.parrot.feedback` event) carry Pydantic
payloads. Agents get an `AgentSwarmToolkit` (`AbstractToolkit`) with
`ask_agent`, `send_feedback`, `list_agents`, `list_channels`, and
`post_to_channel` tools. The un-mentioned-message path in
`MatrixCrewTransport` is extended: if the channel's policy is `swarm`, a
`MatrixCollaborativeSession` is started (now allowed to run concurrently per
room, keyed by the triggering event id) — the same session engine reuses the
tunnel primitive for its cross-pollination phase.

✅ **Pros:**
- Reuses ~4.4 kLOC of tested code; only three new modules + toolkit.
- Tunnels are ordinary rooms: visible in any client, replayable, exportable.
- Both entry points (autonomous tool use and orchestrated sessions) share one
  primitive, so behaviour and telemetry are consistent.
- Channel policy gives a single knob for flood control on bridged rooms.

❌ **Cons:**
- Room-per-pair grows O(N²) rooms for large crews (mitigated by lazy creation +
  TTL/archival).
- Concurrent sessions per room need state isolation refactor in
  `MatrixCollaborativeSession`.
- Tool-driven `ask_agent` can loop (A asks B asks A): needs hop-limit/TTL.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mautrix>=0.20` | AppService + client (already a dep of `[matrix]` extra) | Python, Apache-2.0 |
| `python-olm>=3.2.16` | already in extra; unused (no E2EE) | keep as-is |
| `pydantic>=2` | payload models | already core |
| `pyyaml` | channel config | already used by `crew/config.py` |

🔗 **Existing Code to Reuse:**
- `integrations/matrix/a2a_transport.py` — `MatrixA2ATransport.send_task()/wait_for_result()` become the tunnel's send/await.
- `integrations/matrix/events.py` — `ParrotEventType`, `TaskEventContent`, `ResultEventContent` (add `FEEDBACK`, `CHANNEL`).
- `integrations/matrix/crew/transport.py` — message dispatch; extend the "no mention" branch.
- `integrations/matrix/crew/session.py` — `MatrixCollaborativeSession` for swarm answers.
- `integrations/matrix/crew/delegation.py` — `HybridDelegator` pattern for tool-shaped peer calls.
- `integrations/matrix/crew/registry.py` — `MatrixCrewRegistry` for agent discovery inside tools.
- `parrot/tools/toolkit.py` — `AbstractToolkit` for `AgentSwarmToolkit`.

---

### Option B: Threads-only swarm (no extra rooms) with hidden custom events

Keep everything inside the channel room. Every human question opens an
`m.thread`; agents post their public replies into the thread, and the
agent-to-agent structured exchange is carried by `m.parrot.*` events **inside
the same thread**, which clients don't render (custom event types are hidden
by Element/Nheko). Swarm coordination state is an `m.parrot.session` state
event keyed by thread root.

✅ **Pros:**
- Zero new rooms; one place to look for everything about a question.
- Threads are natively supported by Element / Element X.
- Simplest deployment story.

❌ **Cons:**
- No real *privacy*: any room member (including bridged users and puppets)
  can read the raw events via `/context` or a dev client; "private tunnel"
  requirement is not met.
- Bridges (Slack/Discord) flatten threads inconsistently; hidden events may
  leak as "unsupported message" on some bridges.
- Existing code uses `m.in_reply_to`, not `m.thread`; would need a threading
  refactor in `appservice.py` / `mention.py` and FluffyChat can't show threads.
- Pairwise conversations unrelated to a human question have no natural
  thread root.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mautrix>=0.20` | `m.thread` relations via `RelationType.THREAD` | already dep |

🔗 **Existing Code to Reuse:**
- `integrations/matrix/appservice.py` — `send_reply_as_agent()` (would gain a `thread_root` arg).
- `integrations/matrix/crew/session.py` — session engine unchanged except reply target.

---

### Option C: Matrix as transport only; swarm orchestrated by `AgentsFlow`

Treat Matrix purely as I/O. A human message becomes a `FlowContext`, an
`AgentsFlow` DAG (built with `DecisionFlowNode` CONSENSUS mode + `SynthesisNode`)
computes the swarm answer in-process, and only the final message (plus optional
per-agent "thinking" bubbles) is posted. Agent-to-agent Q&A is in-memory flow
edges; the "tunnel" is just an optional mirror of flow events into a private
room for auditing.

✅ **Pros:**
- Deterministic, testable orchestration without Matrix round trips; fast.
- Reuses the mature `bots/flows/` engine and its telemetry.
- Concurrency and loop protection come from the DAG, not from room state.

❌ **Cons:**
- Contradicts FEAT-195's explicit decision (Matrix-native orchestrator, not an
  `AgentCrew`/flow adapter) and duplicates `MatrixCollaborativeSession`.
- Agents are not really *talking on Matrix*; the audit mirror is a second
  write path that can drift from reality.
- Cross-process/cross-host agents (the point of using a protocol) are not
  supported — everything must live in one Python process.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.bots.flows` | DAG execution | core |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/flow/flow.py` — `AgentsFlow`, `flows/flow/nodes.py` — `DecisionFlowNode`, `SynthesisNode`.

---

### Option D (unconventional): Matrix Spaces as swarm boundary + MSC3401-style "agent presence"

Model each swarm as a **Matrix Space** (`m.space`) containing public channels,
private channels and tunnel rooms as children. Agent availability is published as
presence + `m.parrot.agent_card` in the Space root; discovery = reading the
Space hierarchy (`/hierarchy` API). Clients (Element/Element X) render the
Space as a sidebar, giving humans a free UI for "which agents live here".

✅ **Pros:**
- Excellent UX in Element/Element X (Spaces are native); tunnels stay hidden
  from humans via private child rooms with `restricted` join rule.
- Hierarchy API gives cheap discovery without scanning rooms.

❌ **Cons:**
- Nheko/FluffyChat Space support is partial; bridges ignore Spaces.
- Adds a layer on top of Option A rather than replacing it.

📊 **Effort:** Low (as an add-on to A)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mautrix>=0.20` | `m.space.child`/`m.space.parent` state events, `/hierarchy` | already dep |

🔗 **Existing Code to Reuse:**
- `integrations/matrix/client.py` — `set_room_state()` for space child links.

---

## Recommendation

**Option A** is recommended, with **Option D folded in as an optional
"space grouping" sub-capability** (cheap, purely additive).

- It satisfies the *privacy* requirement of the tunnel literally (2-member
  rooms) which Option B cannot, and keeps agents genuinely conversing over
  Matrix, which Option C abandons.
- It respects the FEAT-195 architectural decision (Matrix-native
  orchestrator) instead of re-litigating it.
- The O(N²)-rooms concern is real but bounded: crews are ~3–10 agents and
  tunnels are lazy, reusable and archivable; a `tunnel_ttl` config closes idle
  rooms.
- Trade-off accepted: more room-management code (creation, invite, join-rule,
  cleanup) and a refactor of `MatrixCollaborativeSession` to support
  concurrent sessions keyed by trigger event.

---

## Feature Description

### User-Facing Behavior

**Operator (YAML):**
```yaml
channels:
  - name: general           # public, everybody can join
    visibility: public
    agents: [researcher, analyst, writer]
    answer_policy: swarm     # mention | swarm | silent   (router: deferred follow-up)
    swarm:
      max_concurrent_sessions: 3
      cooldown_seconds: 10
  - name: finance-private
    visibility: private      # invite-only
    agents: [analyst]
    answer_policy: mention
tunnels:
  enabled: true
  ttl_minutes: 120                # 0 = keep forever
  echo_summary_to_channel: true   # post "🔒 analyst asked writer a question" in the originating channel
space:
  enabled: false                  # optional Matrix Space grouping (Option D)
  name: "Parrot Swarm"
```

**Human in a channel (native or via Slack/Signal/Discord bridges):**
- `@researcher what's the Q2 trend?` → only `researcher` answers (unchanged).
- Plain text in a `swarm` channel → the coordinator posts *"🐦 Swarm session
  #a1b2 started (3 agents)"*, each agent posts its findings as a reply to the
  question, agents may consult each other (visible one-line echo if enabled,
  full exchange in the tunnel), and the summarizer posts the final answer in
  reply to the original event. Several humans can ask simultaneously; each
  question gets its own session id.
- `!investigate …` keeps working as an explicit trigger in `mention` channels.
- Commands: `!channels`, `!agents`, `!tunnels` (coordinator lists rooms and
  their state), `!join <channel>` for humans on private channels (admin-gated).

**Agent (LLM tools, `AgentSwarmToolkit`):**
- `ask_agent(agent: str, question: str, expected_schema: dict | None, timeout: int)` →
  returns an `AgentAnswer` envelope `{answer, confidence, sources, metadata}`;
  when `expected_schema` is given, `answer` is validated against it (JSON Schema).
- `send_feedback(agent: str, about_event_id: str, rating: int, comment: str)`.
- `list_agents()` / `list_channels()` from the registry.
- `post_to_channel(channel: str, text: str)` (policy-checked).

**Developer / operator (deployment):**
- `docker compose -f docker-compose.matrix.yml --profile bridges up` starts
  Synapse + Postgres + Element Web + the signal/slack/discord bridges; a
  `scripts/matrix/bootstrap.sh` registers the AppService, the coordinator user,
  the bridge registrations and prints login hints.
- `docs/integrations/matrix/CLIENTS.md` documents the selected clients.

### Recommended clients (research result)

| Role | Client | Why | Licence |
|---|---|---|---|
| Linux — primary | **Element Desktop / Element Web** (v1.12.x, 2026) | Full support for Spaces, threads, reply-to, custom-event hiding, pinned messages (status board), AppService puppets render correctly; Web build ships as a container (`vectorim/element-web`) so it goes in the compose file | AGPL-3.0 (client only) |
| Linux — secondary | **Nheko** (v0.12.x) | Native Qt/C++, ~100 MB RAM, good for long-running dev sessions, shows raw event source (handy to inspect `m.parrot.*` payloads), packaged in Debian/Fedora/Flathub | GPL-3.0 |
| Linux — alternative | Fractal (GTK4/Rust) for GNOME users, Cinny (web, Discord-like UI) | mentioned for completeness | GPL-3.0 / AGPL-3.0 |
| Mobile | **Element X** (Android/iOS, v26.08) | Fastest Matrix client (Rust SDK, sliding sync), threads + Spaces support, push notifications via Sygnal/UnifiedPush | AGPL-3.0 |
| Mobile — alternative | FluffyChat | Simple UI, but **no thread rendering** and truncates long messages — unsuitable for swarm sessions | AGPL-3.0 |

Note: Element X requires **sliding sync**, which Synapse ≥1.114 provides natively
(`experimental_features.msc3575_enabled` no longer needed on current releases);
the compose file must expose `/.well-known/matrix/client` for Element X to
discover the homeserver.

### Homeserver + bridges (research result)

| Component | Image | Licence | Notes |
|---|---|---|---|
| Synapse (chosen) | `ghcr.io/element-hq/synapse:v1.15x` (2026) | AGPL-3.0 | Best AppService/bridge compatibility; separate container → no licence contamination of MIT code |
| Alternative | Tuwunel (`ghcr.io/matrix-construct/tuwunel`) | Apache-2.0 | Rust, light; AppService support exists but bridges are far less tested against it — documented as optional swap, not default |
| Postgres | `postgres:16-alpine` | PostgreSQL | replaces SQLite (bridges + Synapse) |
| Element Web | `vectorim/element-web` | AGPL-3.0 | dev client on :8080 |
| Signal | `dock.mau.dev/mautrix/signal` v26.07 | AGPL-3.0 | needs a phone number to link |
| Slack | `dock.mau.dev/mautrix/slack` v26.08 | AGPL-3.0 | bridgev2, native password/token login |
| Discord | `dock.mau.dev/mautrix/discord` v0.7.7 | AGPL-3.0 | supports bot accounts (recommended for the swarm) |
| Instagram | `dock.mau.dev/mautrix/meta` (Instagram mode) | AGPL-3.0 | **Documentation only, not in compose.** `mautrix-instagram` is deprecated; mautrix-meta with `MODE=instagram` uses an unofficial API → account-ban risk |
| XMPP | `mautrix-jabber` (bridgev2, Go) — alternative `slidge` + `matridge` | (unstated, repo very young) / AGPL-3.0 | **Documentation only, not in compose.** Both immature; MUC support limited |
| E-mail | — | — | **Out of scope.** E-mail notifications are sent by agents through `async-notify` (`NotificationMixin`); Postmoogle evaluated and rejected (SMTP server + MX/TLS requirements) |

The compose file ships **signal, slack and discord** under the `bridges`
profile. All three use **AppService** registration files mounted into Synapse
(`app_service_config_files`).

### Internal Behavior

1. **Startup** — `MatrixCrewTransport.start()` loads `MatrixCrewConfig`
   (extended with `channels`, `tunnels`, `space`); `ChannelManager` ensures
   each channel room exists (alias `#<name>:<server>`), sets join rules,
   invites/joins member agents, publishes an `m.parrot.channel` state event
   with the answer policy, and (if enabled) links it into the Space.
2. **Inbound message** — dispatch order: command (`!…`) → `@mention` →
   channel policy. For `swarm`, `SwarmSessionManager` checks concurrency/cooldown
   and spawns a `MatrixCollaborativeSession` (refactored to accept a
   `session_id`/`trigger_event_id` and to keep per-session state instead of a
   room-wide singleton). For `silent`, nothing. (`router` — coordinator LLM
   picks agents — is deferred to a follow-up feature.)
3. **Tunnel** — `TunnelRegistry.get_or_create(a, b)` returns a private room
   (`m.parrot.tunnel` state event, both agents joined via the AppService
   intents, `preset=private_chat`, `is_direct=true`). `ask_agent` sends a
   `m.parrot.task` with a `correlation_id` and awaits the matching
   `m.parrot.result` (reuses `MatrixA2ATransport` futures). The peer agent
   receives the task through its `MatrixCrewAgentWrapper` inbox and answers
   using the requested schema (structured output). `hops` and `origin_session`
   fields are propagated to break loops.
4. **Feedback** — `m.parrot.feedback` events (rating + comment) referencing a
   result event; stored in the tunnel and surfaced via `!tunnels`.
5. **Session cross-pollination** reuses `TunnelRegistry` for its exchanges,
   posting only a one-line echo to the channel when
   `echo_summary_to_channel` is on.
6. **Bridged humans** — MXIDs from bridge namespaces (`@signal_…`,
   `@slack_…`, `@discord_…`; configurable regex list so documented-only
   bridges can be added) are classified as *human* by the registry (non-agent,
   non-coordinator); replies go to the room and the bridge relays them.
7. **Cleanup** — idle tunnels past `ttl_minutes` are left by both agents and
   tombstoned; `ToolManager.cleanup_toolkits()` closes the toolkit.

### Edge Cases & Error Handling

- Peer agent offline / timeout → `ask_agent` returns a structured
  `{"status": "timeout"}`; the session marks the agent as skipped (existing
  FEAT-195 behaviour).
- Loop A→B→A → rejected when `hops >= max_hops` (default 3).
- Room already exists with a different config → reconcile state event, warn.
- Concurrency cap reached → coordinator replies "busy, queued/ignored" per
  config.
- Human edits/deletes the trigger message → session continues; deleted trigger
  posts final answer without reply relation.
- Bridge relays an edit or reaction → ignored (no new session).
- AppService registration missing the tunnel namespace → startup fails loudly
  with the expected `registration.yaml` snippet.
- Non-Synapse homeserver (Tuwunel) → capability probe at startup logs
  unsupported features (e.g. alias creation restrictions).

---

## Capabilities

### New Capabilities
- `matrix-channel-registry`: declarative public/private agent channels, aliases,
  membership, answer policy, `m.parrot.channel` state, optional Space grouping.
- `matrix-agent-tunnel`: private 2-agent rooms carrying structured
  `m.parrot.task/result/feedback` events, registry, TTL cleanup, loop guard.
- `matrix-swarm-toolkit`: `AgentSwarmToolkit` (`ask_agent`, `send_feedback`,
  `list_agents`, `list_channels`, `post_to_channel`).
- `matrix-swarm-sessions`: policy-driven, concurrent collaborative sessions
  per room (extends FEAT-195 engine).
- `matrix-dev-stack`: docker-compose with Synapse+Postgres+Element Web and a
  `bridges` profile (signal, slack, discord) + bootstrap script + `CLIENTS.md`
  + `BRIDGES.md` (incl. documentation-only Instagram/XMPP guidance).
- `matrix-space-grouping` (optional, off by default): Space root +
  `m.space.child` links for channels; tunnels as private children.

### Modified Capabilities
- `integrations-matrix-multi` (FEAT-044): `MatrixCrewConfig` gains
  `channels/tunnels/space`; `MatrixCrewTransport` gains the policy dispatch
  branch; `MatrixCrewRegistry` learns bridge-namespace human classification.
- `matrix-collaborative-crew` (FEAT-195): `MatrixCollaborativeSession`
  supports concurrent sessions and uses tunnels for cross-pollination.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `integrations/matrix/crew/config.py` | extends | new `ChannelConfig`, `TunnelConfig`, `SpaceConfig` sections; backward compatible defaults |
| `integrations/matrix/crew/transport.py` | modifies | policy dispatch for un-mentioned messages; channel bootstrap |
| `integrations/matrix/crew/session.py` | modifies | session id + concurrent state; tunnel-backed cross-pollination |
| `integrations/matrix/crew/registry.py` | extends | human/bridge classification, channel lookup |
| `integrations/matrix/events.py` | extends | `CHANNEL`, `TUNNEL`, `FEEDBACK` event types + models |
| `integrations/matrix/a2a_transport.py` | depends on | reused for correlation futures |
| `integrations/matrix/appservice.py` | extends | NEW `create_room_as_bot()` helper (no room-creation API exists today); `set_custom_event_callback` finally wired by the transport; route `m.parrot.feedback` |
| `integrations/matrix/crew/crew_wrapper.py` | extends | NEW inbound `m.parrot.task` handler that runs the agent with the requested schema and emits `m.parrot.result` (today no producer of results exists) |
| new `integrations/matrix/crew/channels.py`, `tunnel.py`, `swarm_toolkit.py` | new | core of this feature |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/__init__.py` | extends | lazy exports |
| `docker-compose.matrix.yml`, `docker/matrix/**` | modifies/new | Postgres, Element Web, bridge profiles, registration templates |
| `scripts/matrix/bootstrap.sh` | new | registration + user creation |
| `examples/matrix_crew/*.yaml`, `MATRIX_CREW_GUIDE.md`, `docs/integrations/matrix/CLIENTS.md` | extends/new | docs |
| `packages/ai-parrot-integrations/pyproject.toml` | no change expected | deps already present |

No breaking changes; new config sections default to disabled.

---

## Code Context

### User-Provided Code

None — the request was given as prose (see Problem Statement).

### Verified Codebase References

Verified 2026-08-25 on branch `dev`. Base dir `M` = `packages/ai-parrot-integrations/src/parrot/integrations/matrix/`. Line numbers are exact.

**Key gaps that drive this feature** (all verified below): (1) neither `MatrixClientWrapper` nor `MatrixAppService` can create a room — only invite/join into a pre-existing `room_id`; (2) `HybridDelegator` and `MatrixA2ATransport.wait_for_result()` have no producer: nothing in `M/` handles an incoming `m.parrot.task` and emits `m.parrot.result`, and `MatrixCrewTransport` never calls `set_custom_event_callback`; (3) `_active_sessions` is keyed by `room_id`, enforcing one session per room; (4) `MatrixAppService._handle_event` routes only TASK/RESULT custom events (not STATUS / AGENT_CARD).

Base dir `M` = `packages/ai-parrot-integrations/src/parrot/integrations/matrix/`. Line numbers are exact.

#### Package surface

- `M/__init__.py:31` `def __getattr__(name: str)` — lazy map (avoids importing mautrix at package import):
  `MatrixClientWrapper`→`.client`, `MatrixStreamHandler`→`.streaming`, `MatrixA2ATransport`→`.a2a_transport`, `MatrixAppService`→`.appservice`, `MatrixAppServiceConfig`→`.models`, `ParrotEventType`/`TaskEventContent`/`ResultEventContent`/`StatusEventContent`/`AgentCardEventContent`→`.events`, `generate_registration`/`generate_tokens`→`.registration`, `MatrixCrewTransport`/`MatrixCrewConfig`/`MatrixCrewAgentEntry`/`MatrixCrewRegistry`/`MatrixAgentCard`/`MatrixCoordinator`/`MatrixCrewAgentWrapper`→`.crew`. (`CollaborativeConfig`, `MatrixCollaborativeSession`, `HybridDelegator`, `SessionPhase` are NOT in the top-level lazy map; only via `.crew`.)
- `M/crew/__init__.py:22-34` eager imports; `__all__` (lines 37-54): CollaborativeConfig, MatrixCrewConfig, MatrixCrewAgentEntry, MatrixCrewRegistry, MatrixAgentCard, MatrixCoordinator, MatrixCrewAgentWrapper, MatrixCrewTransport, MatrixCollaborativeSession, SessionPhase, AgentRoundResult, CollaborativeSessionState, DelegationRequest, HybridDelegator, parse_mention, format_reply, build_pill, build_reply_content.
- pyproject extra `packages/ai-parrot-integrations/pyproject.toml:61-64`: `matrix = ["mautrix>=0.20", "python-olm>=3.2.16"]`. Core `packages/ai-parrot/pyproject.toml:613` comment only: "matrix extra moved to ai-parrot-integrations[matrix]".
- Core shim `packages/ai-parrot/src/parrot/core/hooks/matrix.py:32` `class MatrixHook(BaseHook)`; `:49 __init__(self, config: MatrixHookConfig, **kwargs: Any) -> None` (`MatrixHookConfig` from `navigator_eventbus.hooks.models`, line 27); `:61 _get_delegate(self) -> BaseHook` resolves `HookRegistry.get("matrix")` → `M/hook.py:27 class MatrixHook(BaseHook)`; `:99 async send_reply(self, room_id: str, message: str) -> bool`.

#### (a) Agent-to-agent structured messaging

##### `M/events.py`
- `:21 class ParrotEventType` — constants `AGENT_CARD="m.parrot.agent_card"` (:25), `TASK="m.parrot.task"` (:28), `RESULT="m.parrot.result"` (:29), `STATUS="m.parrot.status"` (:30); mautrix `EventType.find(...)` objects `AGENT_CARD_EVENT/TASK_EVENT/RESULT_EVENT/STATUS_EVENT` (:35-47), `None` when mautrix missing (:52-55).
- `:62 class AgentCardEventContent(BaseModel)`: name:str, description:str, version:str="1.0", skills:List[Dict[str,Any]], tags:List[str], capabilities:Dict[str,Any], default_input_modes/default_output_modes:List[str], protocol_version:str="0.3", icon_url:Optional[str].
- `:87 class TaskEventContent(BaseModel)`: task_id:str, context_id:Optional[str], content:str, metadata:Dict, target_agent:Optional[str], skill_id:Optional[str].
- `:103 class ResultEventContent(BaseModel)`: task_id:str, context_id:Optional[str], content:str, artifacts:List[Dict], metadata:Dict, success:bool=True, error:Optional[str].
- `:118 class StatusEventContent(BaseModel)`: task_id:str, state:str ("working"|"failed"|"input_required"|"cancelled"), message:Optional[str], progress:Optional[float], metadata:Dict.

##### `M/a2a_transport.py:25 class MatrixA2ATransport` (wraps a `MatrixClientWrapper`, i.e. a *single* logged-in user, not the AppService)
- `:41 __init__(self, wrapper: MatrixClientWrapper) -> None`
- `:54 async publish_card(self, room_id: str, card_data: Dict[str, Any], *, state_key: str = "") -> str` (state event `m.parrot.agent_card`)
- `:84 async discover_card(self, room_id: str, state_key: str = "") -> Optional[AgentCardEventContent]`
- `:111 async send_task(self, room_id: str, content: str, *, task_id: Optional[str]=None, context_id: Optional[str]=None, target_agent: Optional[str]=None, skill_id: Optional[str]=None, metadata: Optional[Dict[str,Any]]=None) -> str`
- `:162 async send_result(self, room_id: str, task_id: str, content: str, *, context_id=None, artifacts: Optional[List[Dict]]=None, success: bool=True, error: Optional[str]=None, metadata=None) -> str`
- `:210 async send_status(self, room_id: str, task_id: str, state: str, *, message: Optional[str]=None, progress: Optional[float]=None) -> str`
- `:249 async wait_for_result(self, room_id: str, task_id: str, *, timeout: float = 60.0) -> Optional[ResultEventContent]` (future in `_pending_results`, resolved by `:288 async _on_result_event(self, event: Any) -> None`)
- Consumers: `packages/ai-parrot/src/parrot/a2a/mixin.py:105 set_matrix_transport(self, transport: Any) -> None` / `:117 get_matrix_transport(self) -> Optional[Any]` on `A2AClientMixin` — stores only; NO code in `packages/*/src` reads `_a2a_matrix_transport` to send anything. `MatrixA2ATransport(` is never instantiated inside `M/`.

##### `M/client.py:32 class MatrixClientWrapper` (mautrix `Client`, single user)
- `:38 __init__(self, homeserver: str, mxid: str, access_token: str, *, device_id: str = "PARROT") -> None`
- `:63 async connect() -> None`, `:81 async start_sync() -> None`, `:90 async disconnect() -> None`, `:105 @property client -> MautrixClient`, `:112 @property mxid -> str`
- `:120 async send_text(self, room_id: str, text: str, *, html: Optional[str]=None, msg_type: str="m.text") -> str`
- `:152 async edit_message(self, room_id: str, original_event_id: str, new_text: str, *, new_html: Optional[str]=None) -> str`
- `:193 async send_event(self, room_id: str, event_type: str, content: Dict[str, Any]) -> str`
- `:217 async set_room_state(self, room_id: str, event_type: str, content: Dict[str, Any], state_key: str = "") -> str`
- `:244 async get_room_state_event(self, room_id: str, event_type: str, state_key: str = "") -> Optional[Dict[str, Any]]`
- `:277 on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None`; `:289 on_custom_event(self, event_type: str, callback: Callable[..., Coroutine]) -> None`
- **No room-creation, invite, join, or DM method** on this class.

##### `M/appservice.py:36 class MatrixAppService` (mautrix AppService; virtual users via IntentAPI)
- `:33 EventCallback = Callable[[str, str, str, Any], Coroutine[Any, Any, None]]` (room_id, sender, body, raw_event)
- `:64 __init__(self, config: MatrixAppServiceConfig) -> None`; `:82 async start() -> None` (auto-joins `config.auto_join_rooms` via `bot_intent.ensure_joined`, :112-114); `:121 async stop() -> None`; `:131 @property running -> bool`; `:136 @property bot_intent -> IntentAPI`
- `:146 async register_agent(self, agent_name: str, displayname: Optional[str] = None) -> str` → `intent.ensure_registered()` + `set_displayname`, returns mxid
- `:179 async unregister_agent(self, agent_name: str) -> None`
- `:196 async ensure_agent_in_room(self, agent_name: str, room_id: str) -> None` → `bot_intent.invite_user(RoomID, UserID)` (:218) then `intent.ensure_joined(RoomID)` (:224). Requires an existing room_id.
- `:231 list_agents(self) -> Dict[str, str]`
- `:239 async send_as_agent(self, agent_name: str, room_id: str, message: str) -> str`
- `:263 async send_formatted_as_agent(self, agent_name: str, room_id: str, body: str, formatted_body: str) -> str`
- `:309 async send_as_bot(self, room_id: str, message: str) -> str`
- `:316 async send_custom_event_as_agent(self, agent_name: str, room_id: str, event_type: str, content: dict) -> Optional[str]` (`intent.send_message_event` with `EventType.find(event_type, t_class=MESSAGE)`)
- `:349 async send_reply_as_agent(self, agent_name: str, room_id: str, message: str, reply_to_event_id: str) -> str` — sets `m.relates_to.m.in_reply_to` (:388)
- `:393 async send_reply_as_bot(self, room_id: str, message: str, reply_to_event_id: str) -> str` (:422 same relation)
- `:431 set_event_callback(self, callback: EventCallback) -> None`; `:444 set_custom_event_callback(self, callback: Callable) -> None` (signature `(event_type: str, content: dict)`)
- `:456 async _handle_event(self, event: Event) -> None`: routes `m.parrot.task`/`m.parrot.result` to custom callback (:461-471, returns); non-`ROOM_MESSAGE` dropped (:474); drops sender in own virtual users or bot (:485-488); drops `m.replace` edits (:491-494); else `_event_callback(room_id, sender, body, event)` (:500). `m.parrot.status` / `agent_card` are NOT routed.
- `:526 _get_intent(self, mxid: str) -> IntentAPI` → `self._appservice.intent.user(UserID(mxid))`
- **No create_room / DM helper.** Only invite+join to a given room_id.

##### `M/models.py:7 class MatrixAppServiceConfig(BaseModel)`
as_token:str, hs_token:str, homeserver:str="http://localhost:8008", server_name:str="parrot.local", listen_host:str="0.0.0.0", listen_port:int=9090, bot_localpart:str="parrot", as_id:str="ai-parrot", namespace_regex:str="parrot-.*", agent_mxid_map:Dict[str,str], auto_join_rooms:List[str]; `:36 @property bot_mxid -> str`; `:40 agent_mxid(self, agent_name: str) -> str` (default localpart `parrot-<name-lower-dashed>`).

##### `M/streaming.py:19 class MatrixStreamHandler`
`:33 __init__(self, wrapper: MatrixClientWrapper, room_id: str, *, min_edit_interval_ms: int=500, min_chars_delta: int=50) -> None`; `:59 async begin_stream(self, initial_text: str="▌") -> str`; `:79 async send_token(self, event_id: str, token: str) -> None`; `:98 async end_stream(...)`. Edit-based (`m.replace`) only.

##### `M/registration.py`
`:15 generate_tokens() -> tuple[str, str]`; `:20 generate_registration(...)` (AS registration YAML).

#### (b) Crew routing

##### `M/crew/transport.py:22 class MatrixCrewTransport`
- `:39 __init__(self, config: MatrixCrewConfig) -> None` — state: `_appservice`, `_coordinator`, `_registry = MatrixCrewRegistry()`, `_wrappers: Dict[str, MatrixCrewAgentWrapper]`, `_room_to_agent: Dict[str,str]` (dedicated room→agent), `_agent_mxids: set[str]`, `_active_sessions: Dict[str, MatrixCollaborativeSession]` (room_id→session).
- `:55 @classmethod from_yaml(cls, path: str) -> "MatrixCrewTransport"`
- `:71 async start() -> None`: builds `MatrixAppServiceConfig` (listen_port=`appservice_port`), `MatrixAppService.start()`, `register_agent` per agent (:111), `MatrixCrewAgentWrapper(...)` per agent (:127), `ensure_agent_in_room` for general + dedicated rooms (:154, :165), `MatrixCoordinator` with `_AppServiceBotClient` (:175-180), `set_event_callback(self.on_room_message)` (:194). **`set_custom_event_callback` is never called; `HybridDelegator` is never instantiated here.**
- `:198 async stop() -> None`
- `:218 async on_room_message(self, room_id: str, sender: str, body: str, event_id) -> None` — dispatch order:
  1. `:245` sender in `_agent_mxids` → if `_active_sessions[room_id].is_active` and `parse_mention(body, server_name)` → `session.handle_inter_agent_message(sender, body, event_id)` (:255); otherwise **dropped** (:258).
  2. `:263` `_is_collaborative_command(body)` non-None → if `config.collaborative is None` fall through (:266); if room already in `_active_sessions` → `send_as_bot("A collaborative session is already active…")` and return (:273-281); else construct `MatrixCollaborativeSession(...)` (:282-291), `asyncio.create_task(self._run_session(...))` (:296), return.
  3. `:303` `room_id in _room_to_agent` → `wrapper.handle_message(room_id, sender, body, event_id_str)`.
  4. `:314` `parse_mention(body, server_name)` → match `entry.mxid_localpart` among `config.agents` → `wrapper.handle_message(...)` (:317-327). Only the FIRST mention in the body is honoured.
  5. `:330` `config.unaddressed_agent` set → route to that wrapper.
  6. `:340` otherwise debug-log "No routing match" and ignore.
- `:345 async _run_session(self, room_id: str, session) -> None` (pops `_active_sessions` in `finally`)
- `:367 _is_collaborative_command(self, body: str) -> Optional[str]` — `None` if no `collaborative` config; `body.strip().startswith(collab.command_prefix)` → remainder stripped, `None` if empty.
- `:397 __aenter__ / :402 __aexit__`
- `:412 class _AppServiceBotClient` (duck-typed client for MatrixCoordinator): `:420 __init__(self, appservice, room_id: str)`, `:424 async send_text(room_id, text) -> str`, `:436 async send_reply(...) -> str`, `:453 async edit_message(...) -> str`, `:483 async set_room_state(...) -> None`.

##### `M/crew/mention.py`
- `:9 _PLAIN_MENTION_RE = r"@(\w[\w.-]*)(?:\s|$|:)"`; `:10 _PILL_MENTION_RE = r'href="https://matrix\.to/#/@([\w][\w.-]*):([^"]+)"'`
- `:19 parse_mention(body: str, server_name: str) -> Optional[str]` — pill first (server must equal `server_name`, else `None`), then plain `@localpart`; returns a single localpart.
- `:54 format_reply(agent_mxid: str, display_name: str, text: str) -> str`; `:68 build_pill(mxid: str, display_name: str) -> str`; `:85 build_reply_content(text: str, reply_to_event_id: str) -> dict` (`m.in_reply_to`).

##### `M/crew/registry.py`
- `:14 class MatrixAgentCard(BaseModel)`: agent_name:str, display_name:str, mxid:str, status:str="offline" (ready|busy|offline), current_task:Optional[str], skills:List[str], joined_at/last_seen:Optional[datetime]; `:39 to_status_line(self) -> str`.
- `:65 class MatrixCrewRegistry` (in-memory, asyncio-locked): `:84 __init__() -> None`; `:89 async register(self, card: MatrixAgentCard) -> None`; `:109 async unregister(self, agent_name: str) -> None`; `:129 async update_status(self, agent_name: str, status: str, current_task: Optional[str]=None) -> None`; `:162 async get(self, agent_name: str) -> Optional[MatrixAgentCard]`; `:174 async get_by_mxid(self, mxid: str) -> Optional[MatrixAgentCard]`; `:191 async all_agents(self) -> List[MatrixAgentCard]`.

##### `M/crew/crew_wrapper.py:20 class MatrixCrewAgentWrapper`
- `:42 __init__(self, agent_name: str, config: MatrixCrewAgentEntry, appservice: MatrixAppService, registry: MatrixCrewRegistry, coordinator: MatrixCoordinator, server_name: str, streaming: bool=True, max_message_length: int=4096) -> None`
- `:68 async handle_message(self, room_id: str, sender: str, body: str, event_id: str) -> None` — `registry.update_status(name,"busy",body[:50])` (:92), typing task (:102), `BotManager.get_bot(config.chatbot_id)` (:111), `response = await agent.ask(body)` (:118, raw body, no mention stripping, no reply relation), `_send_response`, `update_status("ready")` (:149).
- `:158 async _send_response(self, room_id: str, response: str) -> None` — streaming: placeholder + `m.replace` edit (:184); else chunked `send_as_agent` (:198-200).
- `:202 async _send_typing(self, room_id: str) -> None`; `:230 @staticmethod _chunk_text(text: str, max_length: int) -> List[str]`.

##### `M/crew/coordinator.py:16 class MatrixCoordinator`
`:31 __init__(self, client, registry: MatrixCrewRegistry, general_room_id: str, rate_limit_interval: float=0.5) -> None`; `:50 start`, `:72 stop`, `:90 on_agent_join(card)`, `:99 on_agent_leave(agent_name)`, `:108 on_status_change(agent_name)`, `:120 refresh_status_board()`, `:154 _render_board() -> str`, `:177 _pin_message(event_id)`. Status board only.

#### (c) Collaborative session

##### `M/crew/session_models.py`
- `:14 class SessionPhase(str, Enum)`: CREATED, INVESTIGATING, CROSS_POLLINATING, SYNTHESIZING, COMPLETED, FAILED.
- `:34 class AgentRoundResult(BaseModel)`: agent_name, display_name, mxid, round_number:int, result_text:str, event_id:str, timestamp:datetime.
- `:60 class CollaborativeSessionState(BaseModel)`: session_id, room_id, question, phase:SessionPhase=CREATED, current_round:int=0, max_rounds:int=1, agent_results:Dict[str, List[AgentRoundResult]], started_at/completed_at:Optional[datetime], final_synthesis:Optional[str].

##### `M/crew/session.py:40 class MatrixCollaborativeSession`
- `:58 __init__(self, session_id: str, room_id: str, question: str, config: CollaborativeConfig, appservice: MatrixAppService, registry: MatrixCrewRegistry, wrappers: Dict[str, MatrixCrewAgentWrapper], server_name: str) -> None`
- `:92 @property phase -> SessionPhase`; `:97 @property is_active -> bool`
- `:108 async run(self) -> CollaborativeSessionState` (phases `_investigate_phase` :258 → `_cross_pollinate_phase(round_num)` :285 × max_rounds → `_synthesize_phase` :313 or `_post_raw_results` :558)
- `:147 async handle_inter_agent_message(self, sender_mxid: str, body: str, event_id: str) -> None` — `parse_mention` (:166), resolve card via registry → `wrappers[card.agent_name].handle_message(room_id, sender_mxid, body, event_id)` (:191). Fire-and-forget; no result is captured into session state.
- `:198 async cancel(self, reason: str = "Cancelled by user") -> None`
- `:383 async _call_agent_with_timeout(self, card: MatrixAgentCard, wrapper: MatrixCrewAgentWrapper, prompt: str, round_number: int) -> Optional[AgentRoundResult]` — bypasses wrapper: `BotManager.get_bot(wrapper._config.chatbot_id)` (:402), `asyncio.wait_for(agent.ask(prompt), agent_timeout)` (:408-410), posts via `appservice.send_as_agent` (:421).
- `:472 _build_enriched_context(self, round_num: int, requesting_agent: str) -> str`; `:516 _build_synthesizer_payload(self) -> str`; `:582 async _announce(self, message: str) -> None` (respects `session_verbosity`).

##### `M/crew/delegation.py`
- `:31 class DelegationRequest(BaseModel)`: requester_name:str, target_agent:str, task_description:str, room_id:str, context:Optional[str].
- `:49 class HybridDelegator`: `:61 __init__(self, appservice: MatrixAppService, registry: MatrixCrewRegistry) -> None`; `:71 async delegate(self, request: DelegationRequest, timeout: float=60.0) -> Optional[str]` — posts visible "Asking <pill> to: …" as requester (:102), sends `m.parrot.task` via `send_custom_event_as_agent` (:128-133, `TaskEventContent` with uuid task_id + `target_agent`), awaits `m.parrot.result` future (:136); `:153 async on_custom_event(self, event_type: str, content: dict) -> None` (meant for `set_custom_event_callback`); `:184 async _send_custom_event(self, requester_name, room_id, event_type, content) -> None`; `:214 async _wait_for_result(self, task_id: str, timeout: float) -> Optional[ResultEventContent]`.
- HybridDelegator is a plain class, **not** an `AbstractTool`; referenced only by `M/crew/__init__.py`, `packages/ai-parrot-integrations/tests/test_matrix_delegation.py`, and `examples/matrix_crew/MATRIX_CREW_GUIDE.md`. Nothing consumes `m.parrot.task` on the receiving side (no handler produces `m.parrot.result`) in `M/`.

#### (d) Config models — `M/crew/config.py`
- `:19 _substitute_env_vars(value: str) -> str` / `:39 _walk_and_substitute(obj)` — `${ENV}` substitution.
- `:57 class MatrixCrewAgentEntry(BaseModel)`: chatbot_id:str (req), display_name:str (req), mxid_localpart:str (req), avatar_url:Optional[str], dedicated_room_id:Optional[str], skills:List[str], tags:List[str], file_types:List[str].
- `:91 class CollaborativeConfig(BaseModel)`: command_prefix:str="!investigate", max_rounds:int=1 (1..10), agent_timeout:float=120.0, session_timeout:float=600.0, summarizer_agent:Optional[str], session_verbosity:Literal["full","minimal","silent"]="full", include_chat_context:bool=True.
- `:139 class MatrixCrewConfig(BaseModel)`: homeserver_url:str, server_name:str, as_token:str, hs_token:str, bot_mxid:str, general_room_id:str (all req), agents:Dict[str, MatrixCrewAgentEntry], appservice_port:int=8449, pinned_registry:bool=True, typing_indicator:bool=True, streaming:bool=True, unaddressed_agent:Optional[str], max_message_length:int=4096, collaborative:Optional[CollaborativeConfig]; `:193 @model_validator(mode="after") validate_summarizer_agent(self) -> "MatrixCrewConfig"`; `:217 @classmethod from_yaml(cls, path: str) -> "MatrixCrewConfig"`.
- `M/models.py:7 MatrixAppServiceConfig` — see (a).

#### Examples / infra
- `examples/matrix_crew/matrix_crew.yaml`: 3 agents (analyst, researcher w/ `dedicated_room_id`, general-assistant as `unaddressed_agent`), `streaming: false`, `appservice_port: 8449`, all rooms are pre-existing `${MATRIX_*_ROOM_ID}` env vars.
- `examples/matrix_crew/collaborative_crew.yaml`: adds `summarizer` agent + `collaborative:` block (lines 33-40: `!investigate`, max_rounds 2, 120s/600s, summarizer_agent "summarizer", verbosity full, include_chat_context true).
- `docker-compose.matrix.yml`: single service `synapse` (`matrixdotorg/synapse:latest`, port 8008, volume `synapse-data`, healthcheck). Nothing else.

#### A2A base (brief) — `packages/ai-parrot/src/parrot/a2a/`, `packages/ai-parrot-server/src/parrot/a2a/`
- `models.py:959 @dataclass AgentCard` (v1.0): name, description, version, skills:List[AgentSkill], supported_interfaces:List[AgentInterface], capabilities:AgentCapabilities, default_input_modes/default_output_modes, provider, documentation_url, security_schemes, security_requirements, signatures, icon_url, tags; `:1035 to_dict(self, version: str="1.0") -> Dict[str, Any]`; `AgentSkill` :873, `AgentCapabilities` :930. (`AgentCardEventContent` in `M/events.py` is a separate, flatter Pydantic mirror using `protocol_version="0.3"`.)
- Transport: HTTP/JSON-RPC only. `client.py:40 class A2AClient` (`__init__(self, base_url: str, *, timeout: float=60.0, headers=None, auth_token=None, api_key=None)`, aiohttp); `client.py:543 class A2ARemoteAgentTool(AbstractTool)` `name="ask_remote_agent"` (:551), `:607 async _execute(self, question: str, context_id: Optional[str]=None, **kwargs) -> str`; `client.py:695 A2ARemoteSkillTool`. `server/…/a2a/server.py:77 class A2AServer` (`__init__(self, agent, *, base_path="/a2a", version="1.0.0", capabilities, extra_skills, tags, broker, identity_mapper, credential_resolvers, suspended_store, audit_ledger, push_store, output_mode=OutputMode.TEXT)`), `:1816 class A2AEnabledMixin`. `mixin.py:34 class A2AClientMixin` with `set_matrix_transport/get_matrix_transport` (:105/:117, storage only), mesh/router/orchestrator hooks. No abstract transport interface exists; "transport" is a string in `AgentInterface`.
- Other existing "ask another agent" tools: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/mcp_server.py:66 name = "ask_agent"` (MCP tool over the agentd daemon, `_execute(self, prompt: str, **kwargs) -> str`, :69) — unrelated to Matrix.

### Does NOT Exist (Anti-Hallucination)
- Room/DM creation: no `create_room`, `createRoom`, `is_direct`, `m.direct` anywhere in `M/`. Only invite+join into pre-existing room ids (`ensure_agent_in_room`, `auto_join_rooms`).
- Tunnel / private channel / pair-room abstraction: no `tunnel`, `swarm`, `pair`, `dm` concept.
- `m.thread` relations: zero hits. Only `m.in_reply_to` (appservice.py:388/:422, mention.py:102) and `m.replace` (edits, crew_wrapper.py:184; filtered on ingest appservice.py:493, hook.py:127).
- Agent-facing tool for asking a peer: no `AbstractTool` / `@tool` in `M/`; no `ask_agent`/`delegate` tool. `HybridDelegator` is not a tool and is not wired into `MatrixCrewTransport`; `set_custom_event_callback` has no caller.
- Receiving side of `m.parrot.task`: no handler that runs an agent and emits `m.parrot.result` (in `M/`); `MatrixA2ATransport.wait_for_result` and `HybridDelegator._wait_for_result` have no producer.
- `m.parrot.status` / `m.parrot.agent_card` are not routed by `MatrixAppService._handle_event` (only TASK/RESULT).
- Multiple mentions in one message: `parse_mention` returns a single localpart; no fan-out.
- Mention stripping: the raw body (including `@localpart`) is passed to `agent.ask`.
- Session state persistence: `CollaborativeSessionState` is in-memory only; no archive/store.
- E2EE: no `encrypt`/`olm`/`e2ee` usage in `M/` (despite `python-olm` in the extra).
- Bridges (mautrix-*), Element web client, or any service besides Synapse in `docker-compose.matrix.yml`.
- Any consumer of `A2AClientMixin.get_matrix_transport()` in `packages/*/src`.
- `MatrixA2ATransport` instantiation anywhere in `packages/*/src` (only tests/docs).

---

## Parallelism Assessment

- **Internal parallelism**: high. Three largely independent lanes: (1) Python
  core — events + config + tunnel + toolkit + transport/session changes (mostly
  sequential on shared files); (2) `docker-compose` + bridge profiles + bootstrap
  script (no Python overlap); (3) docs — `CLIENTS.md`, guide, examples. Lane 1
  itself is sequential (config → events → tunnel → toolkit → transport → session).
- **Cross-feature independence**: no in-flight spec touches
  `integrations/matrix/` (only FEAT-457/458 form-builder work is active). Shared
  files with nothing else.
- **Recommended isolation**: `mixed` — one worktree for the Python lane, a
  second worktree for the deployment lane (compose/scripts/docs) that can run in
  parallel and merge first.
- **Rationale**: the deployment lane has zero file overlap with the code lane and
  is useful on its own (developers need the stack to test the code lane).

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] Tunnel mechanism — *Owner: Jesus Lara*: private DM room + `m.parrot.*` events (no E2EE).
- [x] Swarm mode — *Owner: Jesus Lara*: extend FEAT-195 `MatrixCollaborativeSession` with policy switch + concurrent sessions.
- [x] Deployment target — *Owner: Jesus Lara*: dev/local docker-compose (no TLS/workers).
- [x] Homeserver — *Owner: Jesus Lara*: keep Synapse (AGPL, isolated container); Tuwunel documented as alternative.
- [x] Bridge selection strictness — *Owner: Jesus Lara*: best-available per platform, licence noted per bridge.
- [x] Agent-to-agent Q&A exposure — *Owner: Jesus Lara*: both — `AgentSwarmToolkit` tools and session-driven cross-pollination share the tunnel primitive.
- [x] Bridged humans — *Owner: Jesus Lara*: treated the same as native humans.
- [x] Should `router` answer policy (coordinator LLM chooses responders) ship in v1 or be deferred? — *Owner: Jesus Lara*: deferred to a follow-up; v1 ships `mention | swarm | silent`.
- [x] Tunnel rooms: keep forever (audit) vs `ttl_minutes` tombstone default? — *Owner: Jesus Lara*: `ttl_minutes: 120` default; idle tunnels are left by both agents and tombstoned (history stays on the server); `0` = keep forever.
- [x] `echo_summary_to_channel` default on or off? — *Owner: Jesus Lara*: on by default.
- [x] Should the Space grouping (Option D) be included in the spec or left as follow-up? — *Owner: Jesus Lara*: included as an optional capability, `space.enabled: false` by default.
- [x] Instagram (mautrix-meta) and XMPP (mautrix-jabber/slidge) are unofficial/immature — ship as `experimental` profiles or drop from the compose file? — *Owner: Jesus Lara*: dropped from the compose file; documented only (how to add them, licences, risks).
- [x] Postmoogle needs SMTP ports + MX for real mail; is a dev-only (localhost SMTP) setup acceptable for v1? — *Owner: Jesus Lara*: e-mail bridge removed from scope entirely. E-mail is handled by agents via `async-notify` (`NotificationMixin`), not via Matrix.
- [x] Structured answer schema for `ask_agent`: free JSON schema passed by the caller vs fixed `AgentAnswer` model? — *Owner: Jesus Lara*: fixed `AgentAnswer` envelope `{answer, confidence, sources, metadata}`; when the caller passes `expected_schema`, `answer` must validate against it.
