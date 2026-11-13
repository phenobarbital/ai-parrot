---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations, sdd-tooling, docs]
tags: [domain-experts, flows, gates, sdd-delegation, otel, episodic-memory]
docs:
  policy: required
  pages: [wiki/experts/expert-stages-and-scope-grid.md, wiki/flows/generic-gate-host.md, wiki/sdd-tooling/sdd/expert-consult.md]
  api_modules: [parrot.bots.flows.core.gates, parrot.experts.stages, parrot.experts.grid]
---

# Feature Specification: Expert stages, dispatch modes, generic gate host and SDD expert delegation (FEAT-778 phases 3–4)

**Feature ID**: FEAT-890
**Date**: 2026-11-13
**Author**: Jesus Lara (with Claude Opus 5.5)
**Status**: approved
**Target version**: 1.4.0

Source: `sdd/proposals/expert-stages-and-delegation.brainstorm.md` (Option B). Extends FEAT-778
(`sdd/specs/domain-experts.spec.md`, phases 1–2 merged) and closes its deferred §8 Q6.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-778 delivered experts as standalone `ExpertAgent`s: a human must call `cve-analyst`, read its report and hand
it to `cve-remediation`. There is no way to:

1. **Compose experts into a process.** `FlowDefinition` has no stage vocabulary, so "for scope `security-patch`,
   run `cve-analyst` at `intake`, gate, then `cve-remediation` at `plan`" cannot be declared. `AgentCrew` knows
   nothing about experts, their tier or stage-scoped knowledge.
2. **Gate between stages generically.** The only approval gate (`ApprovalGate`) is locked in
   `parrot/flows/dev_loop/session_state.py` with a closed `GateKind` Literal of six dev-loop values.
3. **Consult experts from SDD.** `/sdd-proposal` and `/sdd-spec` cannot ask matching experts for findings.
4. **Observe and remember.** Expert spans carry no `expert.*` attributes, `tier` does not inform sdd-coder seat
   choice, and experts have no episodic memory between runs.

### Goals
- G1 — A generic, durable gate host in `parrot/bots/flows/core/gates/` with string gate kinds, a pluggable
  `GateStore` (Redis action streams, SQLite default, HelixDB optional) and an optional advisory `pre_review` expert.
- G2 — dev-loop consumes the generic host (hard cut, no import shims); persisted `ApprovalGate` envelopes keep
  loading through `DevLoopGateAdapter`.
- G3 — An `expert_stage` `AgentsFlow` node with four first-class modes: `subagent`, `pipeline`, `mob`, `inline`.
- G4 — A declarative scope grid (scope × stage → experts, mode, gate) compiled to a plain `FlowDefinition`.
- G5 — `expert.slug`, `expert.tier`, `expert.stage`, `expert.mode` span attributes; tier → sdd-coder seat hint.
- G6 — Per-expert episodic memory in the expert's wiki namespace, served back as a knowledge source.
- G7 — Advisory SDD delegation: `parrot sdd experts consult` + a "Consult experts" step in `/sdd-proposal` and
  `/sdd-spec` (and twins); contributions as JSON under `sdd/state/<FEAT-ID>/contributions/`.
- G8 — Rule promotion: a CONFIRMed finding becomes an inferred ADR (`DecisionService`) that only feeds expert
  knowledge once reviewed `accepted`.

### Non-Goals (explicitly out of scope)
- Remaining phase-5 experts (`mvp`/`poc` grid with Domain Design; `ContractsAgent`/`LegalLibrarianAgent`
  migration) — wait for this feature (brainstorm Q, resolved).
- Extending `AgentDefinition` / `CrewDefinition` with stages (codex S8 of FEAT-778) — stages are compiled nodes.
- An MCP surface for experts (brainstorm Option C, rejected; left to `agent-local-mcp`).
- Gate-as-expert resolution (Option D, rejected): an LLM never resolves a gate; `pre_review` is advisory only.
- Blocking SDD gates: consult is advisory, never blocks `/sdd-spec` approval.
- `parrot/memory/episodic` (`EpisodicMemoryStore`) is not used by experts.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:d7e74f1b49b84974cd23352313494504d78a416e08c2913fdfcd632b5415729f evaluation_digest=sha256:0f0c87821167c00812d258a683ebd5cfec87a32f9e1ad49bcafce521daede536 rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, flows, integrations, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools

## 2. Architectural Design

### Overview

Three layers, built in order (gate → stages/grid → SDD delegation), all on the existing `AgentsFlow` engine:

1. **Generic gate host** (`parrot/bots/flows/core/gates/`). `GateSpec` (string `kind`, title, instructions,
   questions, `ttl_seconds`, `on_expiry: fail | approve`, optional `pre_review` expert slug) → `GateHost.open()`
   persists a `GateRecord` through a `GateStore` and emits a `GateEvent`; `GateHost.resolve()` records
   `approved | rejected` with answers; expiry follows dev-loop semantics exactly (`fail` emits expiry,
   `approve` auto-resolves by `system:ttl-auto-approve`), including expiries that elapsed while the process was down
   (evaluated on `GateHost.recover()`). Gate kinds are registered strings (`register_gate_kind`); dev-loop registers
   its six legacy kinds. Human delivery goes through `parrot/human` (`HumanInteractionManager`) — the gate host
   never re-implements channels. **Stores**: `RedisGateStore` (the existing dev-loop action-stream path, moved out
   of dev-loop), `SQLiteGateStore` (default when no Redis is configured, `aiosqlite`), `HelixGateStore` (optional
   extra; built only if a verified async HelixDB Python client exists — see §8 Q1).
   **`pre_review` (v1)**: when set, the named `review`-capability expert runs before human notification; its verdict
   is attached to the gate as advisory context (`GateRecord.pre_review`) and **never** resolves the gate.
2. **dev-loop migration (hard cut)**. `ApprovalGate`, `GateOpened/GateResolved/GateExpired` and
   `SessionHost.open_gate/resolve_gate` delegate to the generic host; `GateKind` stays as dev-loop's vocabulary of
   registered string kinds. `DevLoopGateAdapter` converts persisted `ApprovalGate` envelopes (Redis action stream,
   `ActionEnvelope`) to `GateRecord` and back, so in-flight runs survive the upgrade. No import shims.
3. **Expert stage node + scope grid**. `@register_node("expert_stage", config_model=ExpertStageConfig)` resolves
   experts via `ExpertRegistry.get(name, tenant=...)` and runs each inside `activate_expert(expert, run_id, stage)`;
   `KnowledgeResolver.resolve(..., stage=...)` receives the stage (making `RuleSet.layer="stage"` live). Modes:
   - `subagent` — one expert answers the stage input.
   - `mob` — experts run concurrently; a `SynthesisNode` merges with per-expert attribution; a failing expert is
     reported and skipped unless `strict: true`.
   - `pipeline` — compiled into a chain of `expert_stage` nodes connected through gate edges.
   - `inline` — a conductor agent receives a **cloned** builder with each expert's layers installed under
     per-expert names (`expert_rules:<slug>`, `expert_knowledge:<slug>`); the conductor keeps its own identity.
     Conflicting rule ids across inlined experts are a compile error.
   The **scope grid** (`AGENTS_DIR/experts/scopes/*.yaml`, plus bundled `parrot/experts/bundled/scopes/`, workspace
   shadows bundled by name) maps `scope → stages[] → {experts, mode, gate?, synthesis?, strict?}`.
   `compile_scope(scope) -> FlowDefinition` is a pure function: it validates experts exist and their `capabilities`
   fit the stage, gate kinds are registered, and there are no cycles (except an explicit `loop` stage).
4. **Observability + tier → seat**. The stage node sets span attributes `expert.slug`, `expert.tier`,
   `expert.stage`, `expert.mode`. In dev-loop, `ExpertTier` maps to a seat hint consumed by `eligible_seats`
   (JUDGMENT → the complex-task allowlist, BALANCED → standard rotation, TEMPLATED → cheapest seats); the mapping
   lives in `RosterConfig`, `RosterSeat` gains no field.
5. **Episodic memory (wiki)**. After each stage run the node records an episode (input digest, outcome, gate
   resolution, lesson) into `expert-<slug>` via the wiki `remember` API (category `note`, title prefixed
   `episode:`), capped per expert. A new `EpisodeSource` (`KnowledgeSourceKind.EPISODES`, retrieval mode) returns
   the top-k relevant episodes, wrapped as untrusted data.
6. **SDD delegation**. `parrot sdd experts consult --doc <path> [--feature FEAT-<NNN>]` matches experts whose
   bundled `sdd` scope rows declare the document's `projects`/`tags`, runs them in `mob` mode, and writes
   `sdd/state/<FEAT-ID>/contributions/<slug>.json` (or `sdd/state/.contributions/<doc-slug>/` before a FEAT-ID
   exists — §2 rule: promoted by `/sdd-spec` §6 like design research). The command step lists findings; the author
   marks each `confirm | reject | escalate` with a reason (`parrot sdd experts triage`); CONFIRMed findings are folded
   into the document with a reference to the contribution file. No match ⇒ one-line no-op.
7. **Rule promotion**. `parrot sdd experts promote <contribution> <finding-id>` creates a `DecisionService` record
   with `origin="inferred"`, `review_status="unreviewed"`; once reviewed `accepted` it is eligible for the expert's
   `source: adr` knowledge (rejected inferred records are already hidden by `DecisionService`).

### Component Diagram
```
scope grid YAML ──compile_scope──→ FlowDefinition ──AgentsFlow.from_definition──→ flow
                                                     │
                     ┌───────────────────────────────┼──────────────────────────────┐
              expert_stage(subagent|mob|inline)   gate edge                   SynthesisNode (mob)
                     │                               │
       ExpertRegistry.get → activate_expert     GateHost ──→ GateStore (Redis | SQLite | Helix)
       KnowledgeResolver.resolve(stage)            │  ├─ pre_review expert (advisory)
       + EpisodeSource (wiki expert-<slug>)        │  └─ parrot/human delivery
       OTEL expert.* attrs                          └── DevLoopGateAdapter ←── dev-loop SessionHost
parrot sdd experts consult ──mob stage──→ sdd/state/<FEAT>/contributions/*.json ──promote──→ DecisionService
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentsFlow` / `register_node` | extends | new `expert_stage` node type |
| `SynthesisNode` | uses | mob merge |
| `ExpertRegistry`, `activate_expert`, `KnowledgeResolver`, `install_layers` | uses | stage execution, inline mode on a cloned builder |
| `KnowledgeSourceKind` / registry source list | extends | `EPISODES` kind + `EpisodeSource` |
| dev-loop `SessionHost`, `ApprovalGate`, runner, commands, streaming | modifies | delegate to `GateHost` |
| `ai-parrot-integrations` devloop service/bridge | modifies | resolve via `GateHost` |
| `parrot/human` | uses | gate delivery |
| `sdd_coder` `eligible_seats`, `RosterConfig` | modifies | tier → seat hint |
| `observability` context / spans | extends | `expert.*` attributes |
| `parrot sdd` click group | extends | `experts consult | triage | promote` |
| `.claude/commands/sdd-{proposal,spec}.md` + twins | modifies | "Consult experts" step |
| `DecisionService.generate/review` | uses | rule promotion |

### Data Models
```python
class GateSpec(BaseModel):            # extra="forbid"
    kind: str                          # must be registered
    title: str
    instructions: str = ""
    questions: list[str] = []
    ttl_seconds: int | None = None
    on_expiry: Literal["fail", "approve"] = "fail"
    pre_review: str | None = None      # expert slug with "review" capability

class GateRecord(BaseModel):
    gate_id: str; kind: str; owner: str          # owner = flow run id / dev-loop node id
    status: Literal["pending", "approved", "rejected", "expired"]
    spec: GateSpec; payload_ref: str = ""
    opened_at: float; expires_at: float | None
    resolved_by: str = ""; resolved_at: float | None = None; comment: str = ""
    answers: dict[str, str] = {}
    pre_review: PreReviewVerdict | None = None    # advisory only

class ExpertStageConfig(BaseModel):   # extra="forbid"
    stage: str
    experts: list[str]                 # >=1; subagent => exactly 1
    mode: Literal["subagent", "pipeline", "mob", "inline"]
    gate: GateSpec | None = None
    synthesis: str | None = None       # synthesis prompt for mob
    strict: bool = False

class ScopeGrid(BaseModel):
    scope: str; description: str = ""
    match: ScopeMatch | None = None    # projects/tags for SDD consult
    stages: list[ExpertStageConfig]

class Finding(BaseModel):
    id: str; severity: Literal["info", "minor", "major", "critical"]
    section: str; statement: str; evidence: list[str] = []
    status: Literal["pending", "confirm", "reject", "escalate"] = "pending"; reason: str = ""

class Contribution(BaseModel):
    expert: str; tier: str; doc_path: str; doc_digest: str
    feature_id: str | None; created_at: str
    knowledge_degraded: bool = False; stale: bool = False
    findings: list[Finding]
```

### New Public Interfaces
See §3 Interface Skeletons.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Gate core | no | — | protocol + expiry recovery semantics are the design core |
| M2: Gate stores | yes | `GateStore` protocol from M1; aiosqlite; Redis stream code moved verbatim | — |
| M3: dev-loop gate migration | no | — | hard cut over persisted envelopes; risky |
| M4: Expert stage node | no | — | mode semantics + inline layering |
| M5: Scope grid + compiler | yes | models in §2, pure `compile_scope`, golden-file tests | — |
| M6: Observability + tier→seat | yes | 4 span attrs; tier map in `RosterConfig` | — |
| M7: Episodic memory | yes | `remember(wiki_name=f"expert-{slug}", category="note", title="episode:…")`; `EpisodeSource` per `KnowledgeSource` protocol | — |
| M8: SDD consult CLI | yes | models in §2, paths in §2.6 | — |
| M9: SDD command steps + twins | yes | step text mirrors the CLI; 3 hosts | — |
| M10: Rule promotion | yes | `DecisionService.generate` + record fields | — |
| M11: Docs | yes | §10 pages | — |

### Module 1: Gate core
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/gates/{__init__,models,host,kinds}.py` (new)
- **Responsibility**: `GateSpec`/`GateRecord`/`GateEvent`, kind registry, `GateHost` (open/resolve/expire/recover,
  `pre_review` hook, `parrot/human` delivery).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  def register_gate_kind(kind: str, *, description: str = "") -> None:
      """Register a string gate kind; idempotent; raises GateError(GATE_KIND_CONFLICT) on a different description."""
  class GateStore(Protocol):
      async def put(self, record: GateRecord) -> None: ...
      async def get(self, gate_id: str) -> GateRecord | None: ...
      async def pending(self, owner: str | None = None) -> list[GateRecord]: ...
  class GateHost:
      def __init__(self, store: GateStore, *, notifier: "HumanInteractionManager | None" = None,
                   pre_reviewer: Callable[[GateRecord], Awaitable[PreReviewVerdict]] | None = None) -> None: ...
      async def open(self, spec: GateSpec, *, owner: str, payload_ref: str = "") -> GateRecord:
          """Persist a pending gate, run pre_review (advisory) then notify humans; raises GateError(UNKNOWN_KIND)."""
      async def resolve(self, gate_id: str, resolution: Literal["approved", "rejected"], *, resolved_by: str,
                        comment: str = "", answers: Mapping[str, str] | None = None) -> GateRecord:
          """Resolve a pending gate; raises GateError(NOT_PENDING) otherwise."""
      async def recover(self, *, now: float | None = None) -> list[GateRecord]:
          """Apply on_expiry to every pending gate whose expires_at elapsed (incl. while down)."""
  ```

### Module 2: Gate stores
- **Path**: `.../core/gates/stores/{redis,sqlite,helix}.py` (new); `resolve_gate_store(config) -> GateStore`
- **Responsibility**: Redis (action stream, moved from dev-loop `streaming.py`), SQLite default, HelixDB optional.
- **Depends on**: M1

### Module 3: dev-loop gate migration
- **Path**: modifies `flows/dev_loop/session_state.py`, `runner.py`, `commands.py`, `streaming.py`;
  `ai-parrot-integrations/.../integrations/devloop/{service,bridge}.py`; new `flows/dev_loop/gate_adapter.py`
- **Responsibility**: `DevLoopGateAdapter` (envelope ⇄ `GateRecord`), register the six legacy kinds, `SessionHost`
  delegates to `GateHost`; behavior unchanged for every existing dev-loop test.
- **Depends on**: M1, M2
- **Interface Skeleton**:
  ```python
  # flows/dev_loop/gate_adapter.py (new)
  class DevLoopGateAdapter:
      @staticmethod
      def to_record(gate: "ApprovalGate", *, owner: str) -> GateRecord: ...   # ApprovalGate verified: session_state.py:297
      @staticmethod
      def to_action(record: GateRecord) -> "GateOpened | GateResolved | GateExpired": ...  # verified: session_state.py:655,660,674
  ```

### Module 4: Expert stage node
- **Path**: `packages/ai-parrot/src/parrot/experts/stages/{__init__,node,modes,inline}.py` (new)
- **Responsibility**: `ExpertStageNode` (subagent / mob / inline; pipeline handled by M5's compiler), gate edges.
- **Depends on**: M1, existing experts package
- **Interface Skeleton**:
  ```python
  @register_node("expert_stage", config_model=ExpertStageConfig)   # register_node verified: bots/flows/flow/flow.py:161
  class ExpertStageNode(Node):                                      # Node verified: bots/flows/core/node.py:68
      async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> NodeResult:
          """Run the stage's experts per mode inside activate_expert(run_id, stage); record episodes; set expert.* attrs."""
  def build_inline_conductor(conductor: "Agent", experts: Sequence["ExpertAgent"], ctx_by_slug: Mapping[str, "KnowledgeContext"]) -> "PromptBuilder":
      """Clone the conductor builder and install each expert's layers under per-expert names; raises on rule-id clash."""
  ```

### Module 5: Scope grid + compiler
- **Path**: `packages/ai-parrot/src/parrot/experts/grid/{__init__,models,loader,compiler}.py` (new);
  `parrot/experts/bundled/scopes/security-patch.yaml`, `sdd-review.yaml` (new)
- **Depends on**: M4 (node type name), M1 (kind registry)
- **Interface Skeleton**:
  ```python
  def load_scopes(agents_dir: Path | None, *, bundled_dir: Path = BUNDLED_SCOPES_DIR) -> dict[str, ScopeGrid]: ...
  def compile_scope(grid: ScopeGrid, *, registry: "ExpertRegistry") -> FlowDefinition:
      """Pure; raises ScopeGridError(UNKNOWN_EXPERT|CAPABILITY_MISMATCH|UNKNOWN_GATE_KIND|CYCLE)."""
  ```
  CLI: `parrot experts run --scope <name> --input <text|@file>` (resumes a paused run with `--run-id`).

### Module 6: Observability + tier → seat
- **Path**: modifies `parrot/experts/activation.py` (span attributes), `flows/dev_loop/sdd_coder/{models,roster}.py`
- **Interface Skeleton**:
  ```python
  # experts/activation.py:15 — activate_expert gains keyword `mode: str | None = None` and sets expert.* attrs
  # sdd_coder/models.py:294 RosterConfig gains: expert_tier_seats: dict[str, Literal["complex", "standard", "cheap"]]
  ```

### Module 7: Episodic memory
- **Path**: `parrot/experts/knowledge/sources/episodes.py` (new); modifies `experts/models.py` (`EPISODES` kind),
  `experts/registry.py` (source list), `experts/stages/node.py` (record)
- **Interface Skeleton**:
  ```python
  class EpisodeSource:                       # implements KnowledgeSource (experts/knowledge/sources/base.py:13)
      kind = KnowledgeSourceKind.EPISODES
      async def layers(self, spec, bundle, *, workspace, counter) -> list[KnowledgeLayer]: ...
  async def record_episode(wiki_toolkit: Any, slug: str, episode: Episode, *, cap: int = 200) -> None: ...
  ```

### Module 8: SDD consult CLI
- **Path**: `parrot/sdd/experts_cli.py` (new), registered on the `sdd` click group (`parrot/sdd/cli.py:71`)
- **Commands**: `consult --doc <path> [--feature]`, `triage <contribution> <finding-id> confirm|reject|escalate --reason`,
  `promote <contribution> <finding-id>` (M10).

### Module 9: SDD command steps + twins
- **Path**: `.claude/commands/sdd-proposal.md`, `.claude/commands/sdd-spec.md`, `.agent/workflows/sdd-{proposal,spec}.md`,
  `.agents/skills/sdd-{proposal,spec}/` — add "Consult experts" step; `/sdd-spec` §6 promotes `.contributions/`.

### Module 10: Rule promotion
- **Path**: `parrot/experts/promotion.py` (new) — uses `DecisionService.generate()` (`knowledge/wiki/decisions/service.py:389`).

### Module 11: Documentation
- §10 pages.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_gate_open_resolve_roundtrip` | M1 | open → resolve approved, answers kept |
| `test_gate_expiry_fail_and_approve` | M1 | both `on_expiry` policies, incl. `system:ttl-auto-approve` |
| `test_gate_recover_after_downtime` | M1 | elapsed `expires_at` applied on `recover()` |
| `test_pre_review_never_resolves` | M1 | verdict attached, status stays `pending` |
| `test_unknown_gate_kind_rejected` | M1 | `GateError(UNKNOWN_KIND)` |
| `test_store_contract[redis,sqlite]` | M2 | same parametrized contract suite |
| `test_default_store_sqlite_without_redis` | M2 | resolver picks SQLite |
| `test_adapter_roundtrip_recorded_envelopes` | M3 | recorded legacy envelopes → record → action equal |
| `test_devloop_gate_behavior_unchanged` | M3 | existing dev-loop gate tests green |
| `test_stage_subagent_mob_inline` | M4 | each mode, fake experts, no LLM |
| `test_mob_partial_failure_strict` | M4 | skip vs fail |
| `test_inline_rule_clash_errors` | M4 | compile error |
| `test_inline_does_not_mutate_conductor` | M4 | cloned builder |
| `test_compile_scope_golden` | M5 | YAML → FlowDefinition golden file |
| `test_compile_scope_errors` | M5 | four error codes |
| `test_expert_span_attributes` | M6 | four attrs set |
| `test_tier_seat_hint` | M6 | JUDGMENT restricted, TEMPLATED cheapest |
| `test_episode_record_and_retrieve` | M7 | cap + untrusted wrapping |
| `test_consult_writes_contributions` | M8 | match by projects/tags, no-match no-op |
| `test_contribution_stale_on_digest_change` | M8 | `stale: true` |
| `test_promote_creates_inferred_decision` | M10 | origin inferred, unreviewed |

### Integration Tests
| Test | Description |
|---|---|
| `test_security_patch_pipeline_pause_resume` | grid → flow: cve-analyst → gate → (restart) → approve → cve-remediation, fake LLM |
| `test_devloop_inflight_gate_survives_upgrade` | persisted pre-upgrade gate resolves after migration |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/
- packages/ai-parrot/tests/experts/
markers: none

> The dev-loop and experts test files are the existing coverage of the touched code; `/sdd-task` must narrow
> these to files (never a directory) once the new test files exist.

---

## 5. Acceptance Criteria

- [ ] AC1 — `GateHost` opens, resolves and expires gates with dev-loop semantics; expiries elapsed while down are applied by `recover()`.
- [ ] AC2 — Gate kinds are registered strings; no module under `parrot/experts` or `parrot/bots/flows/core/gates` imports `parrot.flows.dev_loop`.
- [ ] AC3 — `SQLiteGateStore` is used when no Redis is configured; Redis and SQLite pass the same store contract suite; HelixDB per §8 Q1.
- [ ] AC4 — `pre_review` runs before notification and never changes gate status.
- [ ] AC5 — Gate delivery uses `parrot/human`; no new channel code.
- [ ] AC6 — dev-loop uses `GateHost`; no import shims remain; all existing dev-loop gate tests pass; recorded legacy envelopes round-trip.
- [ ] AC7 — `expert_stage` supports `subagent`, `pipeline`, `mob`, `inline`; inline never mutates the conductor's builder; rule-id clashes fail at compile time.
- [ ] AC8 — `compile_scope` is pure and emits a `FlowDefinition` run by unchanged `AgentsFlow`; `AgentDefinition`/`CrewDefinition` untouched.
- [ ] AC9 — The bundled `security-patch` scope runs cve-analyst → gate → cve-remediation and resumes after a restart.
- [ ] AC10 — Expert spans carry `expert.slug`, `expert.tier`, `expert.stage`, `expert.mode`.
- [ ] AC11 — In dev-loop, expert tier maps to a seat hint via `RosterConfig`; `RosterSeat` unchanged.
- [ ] AC12 — Episodes are written to `expert-<slug>` (wiki) with a cap and served back by `EpisodeSource` as untrusted data.
- [ ] AC13 — `parrot sdd experts consult` writes `sdd/state/<FEAT-ID>/contributions/<slug>.json`; consult never blocks; no match is a one-line no-op.
- [ ] AC14 — `/sdd-proposal`, `/sdd-spec` and their twins have the "Consult experts" step with CONFIRM/REJECT/ESCALATE triage.
- [ ] AC15 — Promotion creates an `inferred`/`unreviewed` decision; only `accepted` ones reach expert ADR knowledge.
- [ ] AC16 — Non-delegation preserved: experts still cannot call `spawn_sub_agent` (FEAT-778 AC20–21 tests green).
- [ ] AC17 — Documentation pages in §10 exist (`parrot sdd techwiki check`).

---

## 6. Codebase Contract

Verified against: `b697d36467` (dev, 2026-11-13).

### Verified Imports
```python
from parrot.experts.activation import activate_expert          # experts/activation.py:15
from parrot.experts.models import ExpertTier, KnowledgeSourceKind, KnowledgeSourceSpec  # models.py:74,62,82
from parrot.experts.knowledge.sources.base import KnowledgeSource   # sources/base.py:13
from parrot.experts.policy import model_config_for              # policy.py:29
from parrot.experts.registry import ExpertRegistry              # registry.py:27
from parrot.bots.flows.flow.flow import register_node, NODE_REGISTRY, NODE_CONFIG_MODELS  # flow.py:161,136,144
from parrot.bots.flows.core.node import Node                    # core/node.py:68
from parrot.observability.context import agent_identity, usage_attribution  # context.py:89,184
from parrot.flows.dev_loop.sdd_coder.roster import eligible_seats  # roster.py:241
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class _Frozen(BaseModel)                                        # 130
GateKind = Literal[...6 kinds...]                               # 174
GateStatus = Literal["pending", "approved", "rejected", "expired"]  # 183
class ApprovalGate(_Frozen)  # gate_id, kind, node_id, status, on_expiry, title, instructions, payload_ref,
                             # opened_at, expires_at, resolved_by, resolved_at, comment, questions, answers   # 297
class GateOpened(_ActionBase) # 655 ; class GateResolved(_ActionBase) # 660 ; class GateExpired(_ActionBase) # 674
class ActionEnvelope(_Frozen): channel: str; server_seq: int; action: DevLoopAction; origin: Optional[ActionOrigin]; rejection_reason: str  # 815
class SessionHost:                                              # 1346
    def resolve_gate(self, gate_id, resolution: Literal["approved","rejected"], resolved_by, comment="", origin=None, answers=None)  # 1438
    def open_gate(self, *, kind: GateKind, node_id, title, instructions="", payload_ref="", ttl_seconds=None, on_expiry="fail", questions=None) -> Tuple[str, ActionEnvelope]  # 1502

# flows/dev_loop/runner.py:1005
async def resolve_gate(self, run_id: str, gate_id: str, resolution: str, resolved_by: str, comment: str = "",
                       origin: Optional[ActionOrigin] = None, answers: Optional[Dict[str, str]] = None) -> ActionEnvelope
# flows/dev_loop/commands.py:77
async def resolve_gate_handler(request: web.Request) -> web.Response
# flows/dev_loop/streaming.py:73 class FlowStreamMultiplexer ; :106 self._actions_key = f"flow:{run_id}:actions"

# bots/flows/flow/flow.py
def register_node(name: str, *, config_model: Optional[Type[BaseModel]] = None) -> Callable[[Type[Node]], Type[Node]]  # 161
def from_definition(...)  # 607

# experts/activation.py:15
async def activate_expert(expert: "ExpertAgent", *, run_id: str | None, stage: str | None) -> AsyncIterator["ExpertAgent"]
# experts/agent.py:19  class ExpertAgent(IdentityMixin, Agent)
# experts/models.py:62 class KnowledgeSourceKind(str, Enum): BUNDLED, WORKSPACE, WIKI, BOOKSTORE, GRAPHINDEX, ADR, KB
# experts/knowledge/sources/base.py:13 class KnowledgeSource(Protocol): kind; async def layers(self, spec, bundle, *, workspace, counter) -> list[KnowledgeLayer]
# experts/registry.py:~245 source list built per bundle: BundledSource, WorkspaceSource, WikiSource(namespace=f"expert-{name}"), BookstoreSource, GraphIndexSource, ADRSource
# sdd_coder/models.py:156 class RosterSeat(BaseModel) ; :294 class RosterConfig(BaseModel)
# sdd_coder/roster.py:241 def eligible_seats(assessment, seats, policy) -> List[RosterSeat]
# parrot_tools/wiki/toolkit.py:~869 async def remember(self, wiki_name, text, title=None, category="note", related_pages=None) -> dict
# knowledge/wiki/decisions/service.py:~96 class DecisionService; generate(target) ~389 (origin="inferred" ~443); review(request) ~473
# sdd/cli.py:71 @click.group(name="sdd")
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ExpertStageNode` | `NODE_REGISTRY` | `@register_node` | `flow.py:161` |
| `ExpertStageNode` | `activate_expert` | async context manager | `activation.py:15` |
| `EpisodeSource` | registry source list | list entry | `registry.py:~245` |
| `DevLoopGateAdapter` | `ApprovalGate`, gate actions | conversion | `session_state.py:297,655,660,674` |
| `RedisGateStore` | action stream key | moved code | `streaming.py:106` |
| `experts_cli` | `sdd` group | `sdd.add_command` | `sdd/cli.py:71,390` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.flows.core.gates`~~ — no generic gate host exists.
- ~~`expert_stage` node~~, ~~scope grid~~, ~~`ExpertManifest.stage`~~.
- ~~`expert.*` / `agent.tier` span attributes~~.
- ~~`RosterSeat.tier`~~.
- ~~`WikiSource.remember`~~ — remember lives on the wiki toolkit.
- ~~`DecisionService.propose` / `.record`~~.
- ~~Any HelixDB client or dependency in the repo~~ — none found.
- ~~Consult/second-opinion step in `sdd-proposal.md` / `sdd-spec.md`~~.
- ~~`KnowledgeSourceKind.EPISODES`~~ — added by M7.

### Edit Sites (Blueprint Anchors)

Verified against: `b697d36467`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | `class ApprovalGate(_Frozen):` | `:297` | 1 |
| same | MODIFY | `    def open_gate(` | `:1502` | 1 |
| same | MODIFY | `    def resolve_gate(` | `:1438` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `    async def resolve_gate(` | `:1005` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` | MODIFY | `async def resolve_gate_handler(request: web.Request) -> web.Response:` | `:77` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` | MODIFY | `        self._actions_key = f"flow:{run_id}:actions"` | `:106` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/service.py` | MODIFY | (unverified — check before use; resolve path ~:242) | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/bridge.py` | MODIFY | (unverified — check before use; ~:20,78) | — | — |
| `packages/ai-parrot/src/parrot/experts/activation.py` | MODIFY | `async def activate_expert(` | `:15` | 1 |
| `packages/ai-parrot/src/parrot/experts/models.py` | MODIFY | `    KB = "kb"` | `:~70` | 1 |
| `packages/ai-parrot/src/parrot/experts/registry.py` | MODIFY | `            GraphIndexSource(),` | `:~247` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `class RosterConfig(BaseModel):` | `:294` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py` | MODIFY | `def eligible_seats(` | `:241` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `sdd.add_command(_launch)` | `:400` | 1 |
| `.claude/commands/sdd-proposal.md`, `.claude/commands/sdd-spec.md` + twins | MODIFY | (step insertion — anchor chosen at task time) | — | — |
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/gate_adapter.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/stages/`, `experts/grid/`, `experts/promotion.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/episodes.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/experts/bundled/scopes/*.yaml` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/experts_cli.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Pydantic v2 `extra="forbid"`, Google docstrings, `self.logger`, async I/O, aiohttp only; no LangChain.
- Never mutate a shared `PromptBuilder` (FEAT-778 S2): inline mode clones.
- Gate code never imports dev-loop `Literal`s (codex S9); dev-loop depends on the gate core, not the reverse.
- Episodes and contributions are untrusted data when re-injected into prompts.
- Hard cut: no deprecation shims for the moved gate API (internal API, no external consumers).
- `clients/base.py` untouched.

### Known Risks / Gotchas
- **Persisted envelopes** — the adapter must round-trip real recorded envelopes; record fixtures from current dev
  before changing `session_state.py`. Unknown legacy kind ⇒ fail loudly with the envelope id.
- **dev-loop collision hotspot** — `session_state.py`/`runner.py`/`sdd_coder/*` change often; check open PRs before M3/M6.
- **Gate expires while down** — handled by `recover()` on host start; never silently dropped.
- **Mob partial failure** — synthesis proceeds with attribution unless `strict`.
- **Inline rule clash** — compile error, rules are never trimmed.
- **No wiki/bookstore at consult time** — run degraded, set `knowledge_degraded: true`.
- **Stale contribution** — document digest changed ⇒ `stale: true`, never reused silently.
- **Episode growth** — per-expert cap, recency + relevance retrieval.
- **HelixDB** — not in the repo; unverified client ⇒ optional extra only (§8 Q1).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiosqlite` | `>=0.17` (already core) | SQLite gate store |
| `redis` (async) | existing | Redis gate store |
| `helix-py` (name unverified) | TBD | optional HelixDB store extra (§8 Q1) |

---

## Decisions

```yaml
schema_version: 1
document_id: expert-stages-and-delegation
entries:
  - id: gate-core-independent-of-dev-loop
    statement: The generic gate host must not import from parrot.flows.dev_loop; dev-loop depends on it.
    relation: forbids
    about: [flows]
    targets: [dir:packages/ai-parrot/src/parrot/bots/flows/core]
    contradicts: []
    supersedes: []
    rationale: "codex S9 (FEAT-778): string-id protocol, no dev-loop Literals in the expert runtime."
    rejected_alternatives: ["coexisting gate implementations"]
  - id: llm-never-resolves-gate
    statement: A gate is resolved only by a human or its TTL on_expiry policy; pre_review verdicts are advisory.
    relation: constrains
    about: [flows]
    targets: [dir:packages/ai-parrot/src/parrot/bots/flows/core]
    contradicts: []
    supersedes: []
    rationale: "Brainstorm Option D rejected; deployment approvals must stay human."
    rejected_alternatives: ["gate-as-expert"]
  - id: stages-are-compiled-nodes
    statement: Expert stages are compiled into AgentsFlow nodes; AgentDefinition and CrewDefinition are not extended.
    relation: constrains
    about: [flows]
    targets: [dir:packages/ai-parrot/src/parrot/experts]
    contradicts: []
    supersedes: []
    rationale: "codex S8 (FEAT-778)."
    rejected_alternatives: ["crew-first (Option A)"]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:d7e74f1b49b84974cd23352313494504d78a416e08c2913fdfcd632b5415729f evaluation_digest=sha256:0f0c87821167c00812d258a683ebd5cfec87a32f9e1ad49bcafce521daede536 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `possible-supersession` [advisory]; waived_by: not recorded; participants: adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop@1, adr:spec:expert-stages-and-delegation#llm-never-resolves-gate@1; scope: dir:packages/ai-parrot/src/parrot/bots/flows/core; message: adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop and adr:spec:expert-stages-and-delegation#llm-never-resolves-gate share targets and about without an explicit link
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop@1, adr:spec:expert-stages-and-delegation#llm-never-resolves-gate@1; scope: dir:packages/ai-parrot/src/parrot/bots/flows/core; message: adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop (forbids) and adr:spec:expert-stages-and-delegation#llm-never-resolves-gate (constrains) govern overlapping scope

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, integrations, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: domain-experts, episodic-memory, gates, otel, sdd-delegation
- Targets resolved: 2/2
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "integrations",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 2,
    "targets_total": 2,
    "unmapped_tags": [
      "domain-experts",
      "episodic-memory",
      "gates",
      "otel",
      "sdd-delegation"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:0f0c87821167c00812d258a683ebd5cfec87a32f9e1ad49bcafce521daede536",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:68307b3128be2a0c41280872281c294f11fea2cbf84ab20fc86f2c2af9b15c40",
      "kind": "possible-supersession",
      "message": "adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop and adr:spec:expert-stages-and-delegation#llm-never-resolves-gate share targets and about without an explicit link",
      "participants": [
        {
          "decision_id": "adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:expert-stages-and-delegation#llm-never-resolves-gate",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "dir:packages/ai-parrot/src/parrot/bots/flows/core"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:7f263531377b6381b738aa748ef318385d725dae6a770ed880db49ae419d9214",
      "kind": "potential-conflict",
      "message": "adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop (forbids) and adr:spec:expert-stages-and-delegation#llm-never-resolves-gate (constrains) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:expert-stages-and-delegation#gate-core-independent-of-dev-loop",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:expert-stages-and-delegation#llm-never-resolves-gate",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "dir:packages/ai-parrot/src/parrot/bots/flows/core"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:d7e74f1b49b84974cd23352313494504d78a416e08c2913fdfcd632b5415729f",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:2bcb33ed524473ca2dda066391e47fb4f97464ad5ea73769839c9a4d5261eca8",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Flow / base — *Resolved in brainstorm*: feature → dev.
- [x] One spec, milestones — *Resolved in brainstorm*: one spec; gate/stages first, SDD delegation on top. → §2 order, §3.
- [x] Dispatch modes — *Resolved in brainstorm*: all four first-class. → §2.3, AC7.
- [x] Delegation semantics — *Resolved in brainstorm*: advisory contributions, CONFIRM/REJECT/ESCALATE. → §2.6, AC13–14.
- [x] Contributions storage + promoted rules — *Resolved in brainstorm*: `sdd/state/<FEAT>/contributions/` JSON in git; promoted rules via ADR plane. → §2.6–2.7, AC13, AC15.
- [x] Gate lift compatibility — *Resolved in brainstorm*: string-id protocol + adapter for persisted envelopes, dev-loop hard cut, no import shims. → §2.1–2.2, AC2, AC6.
- [x] Scope grid meaning — *Resolved in brainstorm*: scope × stage → (expert, mode, gate). → §2.3, M5.
- [x] Tier / memory — *Resolved in brainstorm*: tier → OTEL attribute and sdd-coder seat hint; episodic memory in v1. → §2.4–2.5, AC10–12.
- [x] Episodic store — *Resolved in brainstorm*: the expert's wiki namespace via `remember`; `parrot/memory/episodic` not used. → §2.5, M7, AC12.
- [x] Gate persistence without Redis — *Resolved in brainstorm*: pluggable `GateStore`; Redis when configured, SQLite default, HelixDB optional. → §2.1, M2, AC3.
- [x] `pre_review` in v1 — *Resolved in brainstorm*: yes, advisory, never resolves. → §2.1, AC4, Decisions.
- [x] Remaining phase-5 experts — *Resolved in brainstorm*: wait for this feature. → Non-Goals.
- [ ] Q1 — HelixDB: confirm a maintained async Python client exists and its package name; if not, ship Redis + SQLite only and record HelixDB as a follow-up. — *Owner: Jesus Lara*
- [ ] Q2 — Bundled `sdd-review` scope: which experts match SDD documents by default (only `cve-analyst` for `security`-tagged docs in v1?). — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (exploration doc status is `exploration`, not `accepted`) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/experts/expert-stages-and-scope-grid.md` — create: stage modes, grid format, `parrot experts run`.
  - `wiki/flows/generic-gate-host.md` — create: gate protocol, stores, pre_review, dev-loop adapter.
  - `wiki/sdd-tooling/sdd/expert-consult.md` — create: consult/triage/promote workflow.
- **API modules**: `parrot.bots.flows.core.gates`, `parrot.experts.stages`, `parrot.experts.grid`

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-890-expert-stages-and-delegation`); the sdd-coder engine gives each task a sub-worktree.
- **Module dependency graph**:
  - M2 → M1 (implements `GateStore`); M3 → M1, M2 (adapter targets `GateRecord`, Redis store);
  - M4 → M1 (gate edges); M5 → M4 (`expert_stage` type), M1 (kind registry);
  - M6 → M4 (attrs set where stages run; activation change is independent); M7 → M4 (record), experts models;
  - M8 → M4, M5 (mob stage, `sdd-review` scope); M9 → M8; M10 → M8; M11 → all.
  - Concurrent after M1: {M2}, {M4}; after M2: M3 ‖ M4/M5 ‖ M6/M7.
- **Shared files**: `experts/models.py` (M7), `experts/registry.py` (M7), `experts/activation.py` (M6), `experts/stages/node.py` (M4, M6, M7) — serialize M4 → M6 → M7 on the node.
- **Exclusive resources**: none (no migrations; SQLite schema created by the store at runtime).
- **Cross-feature dependencies**: none to merge first; watch open PRs touching dev-loop `session_state.py`/`runner.py`/`sdd_coder/` and FEAT-886 (no overlap expected — it does not use the expert wiki namespace).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-13 | Jesus Lara (with Claude Opus 5.5) | Initial draft from brainstorm (Option B) |
