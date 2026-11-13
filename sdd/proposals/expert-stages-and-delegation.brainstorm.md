---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations, sdd-tooling, docs]
tags: [domain-experts, flows, gates, sdd-delegation, otel, episodic-memory]
---

# Brainstorm: Domain Experts phases 3–4 — expert stages, dispatch modes, generic gate host and SDD delegation

**Date**: 2026-11-13
**Author**: Jesus Lara (with Claude Opus 5.5)
**Status**: exploration
**Recommended Option**: B

Continues FEAT-778 (`sdd/specs/domain-experts.spec.md`, phases 1–2 + CVE experts, all 22 tasks done).
Source phases: `sdd/proposals/domain-experts.proposal.md` §3 "Revised phases" items 3–4. This brainstorm also
resolves the deferred spec question Q6 and carries codex findings S7/S8/S9 from the FEAT-778 spec.

---

## Problem Statement

FEAT-778 delivered experts as standalone `ExpertAgent`s: a human must call `cve-analyst`, read its report and hand it to
`cve-remediation`. There is no way to:

1. **Compose experts into a process.** There is no stage vocabulary in `FlowDefinition`, so you cannot declare
   "for scope `security-patch`, run `cve-analyst` at `intake`, gate, then `cve-remediation` at `plan`".
   `AgentCrew` has four execution modes but knows nothing about experts, their tier or their knowledge resolution.
2. **Gate between stages generically.** The only approval-gate implementation (`ApprovalGate`) is locked inside
   `parrot/flows/dev_loop/session_state.py` with closed `Literal` kinds (`GateKind`, six dev-loop values).
3. **Consult experts from SDD.** `/sdd-proposal` and `/sdd-spec` cannot ask the relevant experts for findings
   (e.g. a security impact), although the `sdd-secondopinion` pattern (advisory, CONFIRM/REJECT/ESCALATE) exists.
4. **Observe and remember.** Expert spans carry no `expert.*` attributes, an expert's `tier` does not inform which
   sdd-coder seat runs it in dev-loop, and experts have no episodic memory between runs.

Affected: developers authoring SDD documents, operators building expert pipelines (CVE first), platform maintainers
(the dev-loop gate migration).

## Constraints & Requirements

Decisions from discovery (2026-11-13, two rounds):

- **Flow**: `feature` → `dev`. One brainstorm, **one spec with milestones 3→4 ordered gate/stages first**; SDD
  delegation (phase 3) builds on them.
- **Dispatch modes are all first-class**: `subagent` (one expert invoked by a conductor/stage), `pipeline`
  (experts chained with gates — the CVE case), `mob` (several experts in parallel on the same artifact + synthesis),
  plus **inline** multi-expert composition into a conductor's prompt.
- **Delegation = advisory contributions** (the `sdd-secondopinion` pattern): the command asks the experts whose scope
  matches for findings/sections; the author marks each CONFIRM / REJECT / ESCALATE. Never blocking by default.
- **Storage**: contributions are JSON files under `sdd/state/<FEAT-ID>/contributions/`, versioned in git. Promoted
  rules go through the ADR plane (`DecisionService`, `origin="inferred"`, review status) and are audited there.
- **Gate lift = adapter + hard cut**: a new gate protocol with string identifiers in `flows/core`; a compatibility
  adapter that reads persisted `ApprovalGate` envelopes; dev-loop migrates in the same feature, with **no** import
  shims (hard cuts are OK, no external consumers). Never import dev-loop `Literal`s into the expert runtime, never
  duplicate `parrot/human` (codex S9).
- **Scope grid = scope × stage → (expert, dispatch mode, gate)**, a declarative table.
- **Observability/memory, all in v1**: `expert.slug` + `expert.tier` span attributes; tier → sdd-coder seat when an
  expert runs in dev-loop; per-expert episodic memory stored in the expert's wiki namespace.
- Carried from FEAT-778: non-delegation stays enforced (allowlist + PBAC deny on `spawn_sub_agent`, S7); never mutate a
  shared `PromptBuilder` (S2); do not extend `AgentDefinition`/`CrewDefinition` for stage binding — compile a stage
  node instead (S8); `clients/base.py` untouched.
- Async-first, Pydantic v2 `extra="forbid"`, aiohttp only, no LangChain.

---

## Options Explored

### Option A: Crew-first — experts as `AgentCrew` members

Add an `ExpertCrewBuilder` that turns a scope-grid row into a `CrewDefinition` (sequential = pipeline,
parallel = mob, loop = review iteration) whose agents are `ExpertAgent`s. Gates are human-in-the-loop calls through
`parrot/human` between crew steps. SDD delegation runs a parallel crew of matching experts.

✅ **Pros:**
- Reuses the four existing crew modes as-is; mob ≈ `run_parallel` + synthesis is almost free.
- Smallest new surface; no flow-node work.

❌ **Cons:**
- `CrewDefinition` has no gate concept; gates between crew steps would be ad-hoc callbacks — exactly the
  "extend CrewDefinition for stages" path codex S8 rejected.
- No durable gate state: a crew run cannot pause for hours on an approval and resume; dev-loop's gate never moves.
- Inline composition and stage-scoped knowledge (`resolve(..., stage=...)`) do not fit the crew model.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | internal only |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/crew/crew.py` — `run_sequential` / `run_parallel` / `run_loop`
- `parrot/human/` — `HumanInteractionManager` for approvals

---

### Option B: Stage nodes on `AgentsFlow` + generic gate host in `flows/core` (compiler from the scope grid)

Three layers:

1. **Gate host (`flows/core/gates/`)** — a `Gate` protocol (`gate_id`, `kind: str`, `status`, `on_expiry`,
   `questions/answers`, TTL) plus a `GateHost` that opens/resolves/expires gates as events; human delivery is
   delegated to `parrot/human` (no duplication). A `DevLoopGateAdapter` maps persisted `ApprovalGate` envelopes
   (Redis action stream) into the generic shape and back; `dev_loop` becomes a consumer, and `GateKind` stays a
   dev-loop vocabulary *registered* as string kinds.
2. **Expert stage node** — `@register_node("expert_stage", config_model=ExpertStageConfig)` on `AgentsFlow`. Config:
   `stage`, `experts: [slug]`, `mode: subagent | pipeline | mob | inline`, optional `gate`, `synthesis`. It resolves
   experts through `ExpertRegistry.get()`, runs inside `activate_expert(..., run_id, stage)` (seat `<stage>.<expert>`),
   and uses the existing stage argument of `KnowledgeResolver.resolve()`. Modes: `subagent` = one expert;
   `mob` = concurrent + `SynthesisNode`; `pipeline` = compiled to a chain of stage nodes with gate edges;
   `inline` = a conductor whose cloned builder receives several experts' layers (identity of the conductor kept,
   experts as named `expert_rules:<slug>` / `expert_knowledge:<slug>` layers).
3. **Scope grid + compiler** — a YAML grid (`AGENTS_DIR/experts/scopes/*.yaml`, plus bundled) of
   `scope → stages[] → (experts, mode, gate)`; `compile_scope(scope) -> FlowDefinition` produces a normal
   `AgentsFlow` definition, so the grid adds no new execution engine.

Phase 3 (SDD delegation) then reuses it: `/sdd-proposal` and `/sdd-spec` call a `parrot sdd experts consult` CLI
that matches experts by the document's `projects`/`tags` against the grid's `sdd` scope, runs them in `mob` mode,
and writes `sdd/state/<FEAT-ID>/contributions/<expert>.json`; the command lists findings for CONFIRM/REJECT/ESCALATE.

✅ **Pros:**
- Gates become durable, resumable and shared by dev-loop and experts (one implementation).
- Matches S8 exactly (compile a stage node; definitions untouched) and S9 (string-id protocol + adapter).
- All four modes on one engine; the grid is pure data, testable without an LLM (compile output is a `FlowDefinition`).
- Delegation reuses the same mob stage — no second execution path.

❌ **Cons:**
- Largest effort; the dev-loop gate migration touches `session_state.py`, `runner.py`, `commands.py` and the
  integrations devloop service/bridge.
- Two serialization shapes to keep correct during the cut (adapter must round-trip persisted envelopes).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | gate + grid + contribution models | already a dependency |
| `opentelemetry-api` | `expert.slug` / `expert.tier` span attributes | already used by `parrot/observability` |
| `redis` (async) | persisted gate streams (existing dev-loop path) | unchanged |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/flow/flow.py` — `register_node`, `NODE_CONFIG_MODELS`, `AgentsFlow.from_definition`
- `parrot/bots/flows/flow/nodes.py` — `SynthesisNode` for mob
- `parrot/experts/activation.py` — `activate_expert(expert, *, run_id, stage)`
- `parrot/experts/knowledge/render.py` — `install_layers` on a cloned builder (inline mode)
- `parrot/flows/dev_loop/session_state.py` — `ApprovalGate`, `SessionHost.open_gate/resolve_gate` (source of the lift)
- `parrot/human/` — `HumanInteractionManager` as the gate's delivery channel
- `.claude/agents/sdd-secondopinion.md` — advisory finding/triage contract for contributions

---

### Option C: Delegation-first via MCP — experts as an MCP tool surface, stages later

Expose every registered expert as an MCP tool (`expert_consult(slug, artifact, question)`) using the
agent-local-MCP work; `/sdd-proposal` / `/sdd-spec` call it from any host (Claude, Codex). Stages and gates come in a
later feature; pipelines are composed by the calling agent.

✅ **Pros:**
- Fastest path to phase 3 value; host-agnostic (Codex twins get it for free).
- No engine change.

❌ **Cons:**
- Contradicts the decision "gate/stages first, delegation on top" and the "all modes first-class" goal.
- Pipelines composed by an LLM conductor are non-deterministic and unauditable; no durable gates.
- Still needs the stage work later — two delegation paths to maintain.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mcp` | expert tools over stdio | already used by parrot MCP server |

🔗 **Existing Code to Reuse:**
- `sdd/specs/agent-local-mcp.spec.md` — agent-as-local-MCP server
- `parrot/experts/registry.py` — `ExpertRegistry.get()`

---

### Option D (unconventional): Gate-as-expert — the gate is itself a `review`-capability expert

Model each gate as a stage whose "expert" is a reviewer (human via `parrot/human`, or an LLM `review` expert with
an escalation to human). The gate host collapses into the stage node; no separate gate protocol.

✅ **Pros:**
- One concept (stage) instead of two; LLM pre-review before humans comes for free.

❌ **Cons:**
- Does not give dev-loop a reusable gate (the lift goal of U4 remains undone).
- Blurs authority: an LLM "approval" looks like a gate resolution — dangerous for deployment approvals.

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:**
- `ExpertManifest.capabilities` (`"review"`), `parrot/human/node.py` `HumanDecisionNode`

---

## Recommendation

**Option B** is recommended because it is the only option consistent with all discovery decisions: gates and
stages first (durable, shared with dev-loop), all four dispatch modes on one engine, and delegation reusing the mob
stage instead of a parallel path. It follows the binding guidance from codex S8 (compile a stage node, do not extend
crew/agent definitions) and S9 (string-id gate protocol + persisted-envelope adapter).

What we trade: the highest effort and a risky hard cut of the dev-loop gate. It is mitigated by (1) ordering the
spec so the gate host + adapter land first with round-trip tests against recorded envelopes, (2) keeping the
dev-loop gate *vocabulary* as registered string kinds so behavior is unchanged. Option D's idea survives as an
optional `pre_review` expert on a gate (a gate may run a `review` expert before notifying humans; the human still
resolves). Option C's MCP surface is left to `agent-local-mcp` and can wrap `experts consult` later.

---

## Feature Description

### User-Facing Behavior

- **Operators** declare a scope grid, e.g. `security-patch: intake → cve-analyst (subagent) → gate(approval) →
  plan → cve-remediation (subagent)`, then run `parrot experts run --scope security-patch --input CVE-2026-1234`.
  The run pauses at the gate; the approver gets it through the configured `parrot/human` channel (CLI, Telegram,
  Slack…); after approval the run resumes, even after a process restart.
- **Mob**: `review: design → [security-reviewer, perf-reviewer] (mob) + synthesis` returns one merged answer with
  per-expert attribution.
- **Inline**: a conductor agent configured with `experts: [a, b]` answers with both experts' rules/knowledge in its
  prompt (each as its own named layer), with its own identity.
- **SDD authors**: `/sdd-proposal` and `/sdd-spec` gain a "Consult experts" step: experts whose grid row matches the
  document's `projects`/`tags` produce findings; the command shows them, the author marks CONFIRM/REJECT/ESCALATE,
  CONFIRMed findings are folded into the document with a reference to the contribution file. If no expert matches,
  the step is a no-op with one line of output.
- Traces show `expert.slug`, `expert.tier`, `expert.stage`, `expert.mode` on each expert span.

### Internal Behavior

1. **Gate host** (`flows/core/gates`): `GateSpec` (string `kind`, title, instructions, questions, TTL, on_expiry,
   optional `pre_review` expert) → `GateHost.open()` emits `GateOpened`; resolution via `GateHost.resolve()` with
   answers; expiry policy identical to dev-loop (`fail` | `approve` by `system:ttl-auto-approve`). Persistence
   through a pluggable store; the default is the existing Redis action-stream implementation moved out of dev-loop.
   `DevLoopGateAdapter` reads/writes the legacy envelope fields, so in-flight dev-loop runs survive the upgrade.
2. **Expert stage node**: compiled from the grid; resolves experts with tenant, opens `activate_expert` scopes,
   attributes usage `EXPERT_<TIER>` (existing), adds the OTEL attributes, and records an episodic entry
   (input digest, outcome, gate resolution, lessons) into `expert-<slug>` via the wiki `remember` API.
   Before each run the resolver injects the top-k relevant episodes as a retrieval knowledge source.
3. **Scope-grid compiler**: validates every expert exists and its `capabilities` fit the stage, every gate kind is
   registered, no cycles except an explicit `loop` stage, then emits a `FlowDefinition` (nodes `expert_stage`,
   `synthesis`, gate edges). Pure function, golden-file testable.
4. **Tier → seat**: when an expert stage runs inside dev-loop, `ExpertTier` maps to a seat-selection hint
   (JUDGMENT → strong seats, TEMPLATED → cheap seats) passed to `eligible_seats`; `RosterSeat` gains no tier field —
   the mapping lives in roster config.
5. **SDD consult**: `parrot sdd experts consult --doc <path> --feature FEAT-<NNN>` → mob stage over matching experts
   → `sdd/state/<FEAT>/contributions/<slug>.json` (`findings[]` with id, severity, section, evidence, status
   `pending`); the command updates `status` to confirm/reject/escalate with a reason; the files are committed with the
   document (SDD auto-commit rule). Twins: `.claude/commands`, `.agent/workflows`, `.agents/skills`.
6. **Promoted rules**: an expert or author can propose a rule from a CONFIRMed finding → `DecisionService` record
   with `origin="inferred"`, `review_status="unreviewed"`; once `accepted` it becomes eligible for the expert's
   `source: adr` knowledge (rejected inferred records are already hidden).

### Edge Cases & Error Handling

- Gate expires while the process is down → resolved on restart from persisted `expires_at` per `on_expiry`.
- Adapter meets an unknown legacy gate kind → load fails loudly with the envelope id (no silent drop).
- Mob with one expert failing → synthesis proceeds with the rest; the failure is attributed in the result; a
  `strict: true` stage fails instead.
- Inline mode with two experts defining the same rule id → compile-time error (rules are never trimmed, so conflicts
  must be explicit).
- Non-delegation: stage nodes call experts directly; an expert still cannot `spawn_sub_agent` (PBAC deny kept).
- Consult with no wiki/bookstore available → expert runs with degraded knowledge and the contribution records
  `knowledge_degraded: true`.
- Contribution file from an earlier run whose document digest changed → marked `stale`, not reused silently.
- Episodic memory growth → per-expert cap + recency/relevance retrieval; memories are untrusted data in the prompt.

---

## Capabilities

### New Capabilities
- `generic-gate-host`: string-kind gate protocol, host, persistence store, dev-loop envelope adapter.
- `expert-stage-node`: `expert_stage` flow node with subagent / pipeline / mob / inline modes.
- `expert-scope-grid`: declarative scope × stage grid + compiler to `FlowDefinition`.
- `expert-observability`: `expert.*` span attributes and tier → seat hint.
- `expert-episodic-memory`: per-expert episodes in the wiki namespace, served as a knowledge source.
- `sdd-expert-consult`: advisory contributions from `/sdd-proposal` and `/sdd-spec` + `parrot sdd experts consult`.
- `expert-rule-promotion`: finding → inferred ADR → reviewed rule.

### Modified Capabilities
- `domain-experts` (FEAT-778): stage-scoped resolution now exercised; `RuleSet.layer="stage"` becomes live.
- `dev-loop` approval gates: consume the generic host (hard cut, adapter for persisted envelopes).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/session_state.py` | modifies | `ApprovalGate`/gate actions move to the generic host; vocabulary kept as registered kinds |
| `parrot/flows/dev_loop/{runner,commands,streaming}.py` | modifies | call the generic host; Redis stream store moves |
| `ai-parrot-integrations` `parrot/integrations/devloop/{service,bridge}.py` | modifies | resolve through the generic host |
| `parrot/bots/flows/core/` | extends | new `gates/` package |
| `parrot/bots/flows/flow/` | extends | `expert_stage` node registration |
| `parrot/experts/` | extends | stage node, grid compiler, episodic source, OTEL attributes |
| `parrot/flows/dev_loop/sdd_coder/roster.py` | modifies | tier → seat hint in eligibility |
| `.claude/commands/sdd-{proposal,spec}.md` + twins | modifies | "Consult experts" step |
| `sdd/state/<FEAT>/contributions/` | new data | git-versioned contribution files |
| `parrot/knowledge/wiki/decisions/` | depends on | promoted rules as inferred decisions |

---

## Code Context

### User-Provided Code
None.

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
GateKind = Literal["manual_criterion", "deployment_approval", "revision_approval",
                   "plan_approval", "review_escalation", "open_questions"]          # line 174
GateStatus = Literal["pending", "approved", "rejected", "expired"]                  # line 183
class ApprovalGate(_Frozen):                                                        # line 297
    gate_id: str; kind: GateKind; node_id: NodeId; status: GateStatus = "pending"
    on_expiry: Literal["fail", "approve"] = "fail"
    title: str; instructions: str; payload_ref: str; opened_at: float
    expires_at: Optional[float]; resolved_by: str; resolved_at: Optional[float]; comment: str
    questions: List[str]; answers: Dict[str, str]                                   # FEAT-412
# GateOpened ~655, GateResolved ~660, GateExpired ~674 (actions)
class SessionHost:                                                                  # ~1346
    def resolve_gate(self, gate_id: str, resolution: Literal["approved", "rejected"],
                     resolved_by: str, comment: str = "", origin=None, answers=None, ...)   # ~1438
    def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str, instructions: str = "",
                  payload_ref: str = "", ttl_seconds=None, on_expiry="fail",
                  questions=None) -> Tuple[str, ActionEnvelope]                     # 1502

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:~1005
async def resolve_gate(self, run_id: str, gate_id: str, resolution: str, resolved_by: str, comment: str = "", ...)

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
NODE_REGISTRY: dict[str, Type[Node]]                                                # ~136
NODE_CONFIG_MODELS: dict[str, Type[BaseModel]]                                      # ~144
def register_node(name: str, *, config_model: Optional[Type[BaseModel]] = None)    # 161
@classmethod
def from_definition(cls, definition: FlowDefinition, *, agent_registry=None,
                    node_factories=None, checkpoint=None, ...)                      # ~607

# packages/ai-parrot/src/parrot/bots/flows/flow/definition.py:~155
class NodeDefinition(BaseModel):  # extra="forbid"; id, type: str, label, agent_ref, instruction,
                                  # max_retries, config: Dict[str, Any], pre_actions, post_actions, metadata, position

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
async def run_sequential(self, query: str, ...)   # ~1783
async def run_loop(self, initial_task: str, condition: str, max_iterations=2, ...)  # ~2135
async def run_parallel(self, tasks: List[Dict[str, Any]], ...)                      # ~2626
async def run_flow(self, initial_task: str, ...)                                     # ~2973

# packages/ai-parrot/src/parrot/experts/
class ExpertAgent(IdentityMixin, Agent)                    # agent.py:19 — usage component EXPERT_<TIER>
async def activate_expert(expert, *, run_id, stage)        # activation.py:15 — seat "<stage>.<expert>"
class ExpertRegistry: get(name, *, tenant=None)            # registry.py:27 / ~140
class ExpertTier(str, Enum): JUDGMENT, BALANCED, TEMPLATED # models.py:74
class ExpertManifest: capabilities: list[Literal["validate", "write", "review"]]  # models.py:105 (no stage field)
RuleSet.layer: Literal["org", "team", "project", "expert", "stage"]
def model_config_for(tier, *, overrides=None) -> ModelConfig   # policy.py:~29
class KnowledgeResolver: async def resolve(self, expert, stage, workspace, *, model, budget_tokens=None, ...)  # knowledge/resolver.py:~43
def install_layers(builder: PromptBuilder, ctx: KnowledgeContext) -> PromptBuilder  # knowledge/render.py:~54
class WikiSource: store_for, probe, seed, layers  # knowledge/sources/wiki.py:~29 — no remember()

# packages/ai-parrot/src/parrot/observability/context.py
def agent_identity(name: Optional[str]) -> Iterator[None]   # 89 (contextmanager)
def usage_attribution(run_id, seat=None, attribution=None)   # ~184

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/
class RosterSeat(BaseModel): label, kind, backend, model, fallback_model, effort  # models.py:156 — no tier
def eligible_seats(assessment, seats, policy) -> List[RosterSeat]                 # roster.py:~241

# packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py:~869
async def remember(self, wiki_name: str, text: str, title=None, category="note", related_pages=None) -> dict

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py:~96
class DecisionService: generate(target) -> GenerationResult (origin="inferred", ~443); review(request) -> DecisionRecord (~473)
# models: origin Literal["documented","inferred"]; review_status Literal["unreviewed","accepted","rejected"]

# packages/ai-parrot/src/parrot/tools/spawn.py:~88 — SpawnSubAgentTool, name "spawn_sub_agent", allowed_tools
# packages/ai-parrot/src/parrot/human/: HumanInteractionManager (manager.py:~51), HumanDecisionNode (node.py:~20)
# packages/ai-parrot/src/parrot/memory/episodic/: EpisodicMemoryStore (store.py:~57), EpisodicMemoryMixin (mixin.py:~77)
```

#### Key Attributes & Constants
- `AgentsFlow` core node types: `start`, `end`, `agent`, `decision`, `interactive_decision`, `synthesis`.
- `ApprovalGate` persistence: Redis action stream (`flows/dev_loop/streaming.py`), envelope fields
  `channel, server_seq, action, origin, rejection_reason`.
- `ApprovalGate` src import sites: none (only two tests in `ai-parrot-integrations/tests/integrations/devloop/`);
  gates are reached via `SessionHost` / runner / commands / integrations devloop service+bridge.
- `.claude/commands/sdd-spec.md:~433` "Identify delegation-eligible modules" (sdd-coder delegation, unrelated to experts).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.flows.core.gates`~~ / any generic gate host — only dev-loop's `ApprovalGate`.
- ~~`expert_stage` node type~~, ~~scope grid~~, ~~`ExpertManifest.stage`~~ — absent.
- ~~`expert.slug` / `expert.tier` / `agent.tier` span attributes~~ — absent.
- ~~`RosterSeat.tier`~~ — absent; seat choice is complexity + round-robin.
- ~~`WikiSource.remember`~~ — absent (remember lives on `LLMWikiToolkit`).
- ~~`DecisionService.propose` / `.record`~~ — absent; use `generate` + `review`.
- ~~A second-opinion/consult step in `.claude/commands/sdd-proposal.md` or `sdd-spec.md`~~ — absent.

---

## Parallelism Assessment

- **Internal parallelism**: after M1 (gate host + adapter), three tracks are independent: (a) stage node + grid
  compiler, (b) dev-loop migration onto the host, (c) observability + tier→seat + episodic memory. SDD consult (phase 3)
  depends on (a). Command twins and docs are parallel to everything after the consult CLI exists.
- **Cross-feature independence**: conflicts possible with FEAT-886 (durable-conversation-memory, active) only if it
  touches `parrot/memory/episodic/`; dev-loop / sdd_coder files are frequent collision points (check open PRs before
  starting the migration task). FEAT-790/785 are merged.
- **Recommended isolation**: `mixed`.
- **Rationale**: the gate host is a hard dependency for most tasks, but the three tracks after it touch disjoint
  packages.

---

## Open Questions

- [x] Flow / base — *Owner: Jesus Lara*: feature → dev.
- [x] One or two brainstorms — *Owner: Jesus Lara*: one, milestones 3→4, gate/stages first.
- [x] Primary use case — *Owner: Jesus Lara*: all dispatch modes first-class (pipeline, inline, mob, subagent).
- [x] Delegation semantics — *Owner: Jesus Lara*: advisory contributions, CONFIRM/REJECT/ESCALATE.
- [x] Q6 contributions storage + promoted rules — *Owner: Jesus Lara*: `sdd/state/<FEAT>/contributions/` JSON in git; promoted rules via ADR plane (inferred → reviewed).
- [x] Gate lift compatibility — *Owner: Jesus Lara*: new string-id protocol + adapter for persisted envelopes, dev-loop hard cut, no import shims.
- [x] Scope grid meaning — *Owner: Jesus Lara*: scope × stage → (expert, mode, gate).
- [x] Q6 tier / memory — *Owner: Jesus Lara*: tier → OTEL attribute and → sdd-coder seat hint; per-expert episodic memory in v1.
- [ ] Episodic store: wiki namespace (`remember`) vs `parrot/memory/episodic` `EpisodicMemoryStore` — default: wiki namespace (already mandatory per expert), revisit if retrieval quality is poor. — *Owner: spec*
- [ ] Gate persistence for non-dev-loop runs: reuse Redis action streams or add a file/PG store for CLI `parrot experts run` without Redis — *Owner: spec*
- [ ] Should `pre_review` (an LLM `review` expert before human notification) be in v1 or deferred — *Owner: Jesus Lara*
- [ ] Migration order of the remaining phase-5 experts (`mvp`/`poc` grid with Domain Design; `ContractsAgent`/`LegalLibrarianAgent`) — out of scope here; confirm they wait for this feature — *Owner: Jesus Lara*
