---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review

**Feature ID**: FEAT-486
**Date**: 2026-09-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.29.0
**Brainstorm**: `sdd/proposals/refactor-dev-flow.brainstorm.md` (Recommended: Option A — Config-Surface Extension)

---

## 1. Motivation & Business Requirements

### Problem Statement

`dev_flow` (`packages/ai-parrot/src/parrot/flows/dev_flow/`) is the
SDD-oriented AgentsFlow covering intake/ideation → planner → development →
synthesis → QA → PR. Today every LLM-facing seat is effectively **one
hardcoded Claude agent**:

- **Research/ideation** is a single seat: `IdeationNode` dispatches one
  `sdd-ideation` Claude Code session with the model hardcoded to
  `claude-sonnet-4-6` (`dev_flow/nodes/ideation.py:338`). The two-sided
  complementary research design (FEAT-482) is approved but unimplemented.
- **Development** is single-agent in practice. `DevelopmentNode` has a full
  task-parallel `DevAgentPool` (`dev_loop/nodes/development.py:608`,
  `dev_loop/agent_pool.py:282`) but dev_flow cannot reach it:
  `build_dev_flow()` exposes no pool configuration path
  (`dev_flow/flow.py:85-107`), and `PlannerOutput.suggested_pool` is
  computed (`dev_loop/nodes/planner.py:171`) but consumed by nothing —
  `DevelopmentNode._resolve_pool_config` reads only
  `work_brief`/`bug_brief` (`development.py:410`), neither of which
  dev_flow populates. Token pressure concentrates on a single Claude
  model and vendor.
- **Adversarial code review** machinery is configurable in dev_loop
  (judge panel, adversarial backend triads), but dev_flow only receives a
  single pre-built `codereview_dispatcher` object — no dev-flow surface
  selects the review model pair.
- **The console** (`examples/dev_loop/server_dev.py`) exposes no per-seat
  LLM selection for research, development sub-agents, or the review pair.

Affected: operators running the dev-flow console (cost, latency, vendor
concentration) and SDD pipeline quality (single-perspective research and
review). FEAT-479 (per-run token ledger) and FEAT-480 (checkpoint/resume)
just landed, providing the accounting and resume substrate multi-agent
seats require; FEAT-482/FEAT-484 define the research-partner contracts
this feature plugs into rather than reinvents.

### Goals

- **G1 — Per-seat configurability**: every LLM client for every dev-flow
  seat (research primary, research partner, each development sub-agent,
  review pair) is configurable via arguments — a single config object on
  `build_dev_flow`/`DevFlowRunner`, env-key defaults, console UI on top.
- **G2 — Multi-agent development pool**: an operator-supplied list of
  `(backend, model)` client specs deploys as a `DevAgentPool` inside
  dev_flow; pool size N derives from the list. Console default: Bedrock
  GLM (`nova` backend, `zai.glm-5`) + Bedrock Qwen3 coder (`nova` backend,
  `qwen.qwen3-coder-480b-a35b-v1:0`).
- **G3 — Single-task collapse (no flag)**: when research/planning ends
  with exactly one `TASK-`, the Development node deploys a single
  sub-agent — the first model from `suggested_pool`/the configured list.
  More than one task ⇒ full configured pool. No new verdict field.
- **G4 — Deployment visibility**: an INFO log in the Development node
  announces pool deployment — how many sub-agents and which backend/model
  each seat runs.
- **G5 — Configurable adversarial review**: review pair defaults to
  Claude Opus 5 (primary) + `gpt-5.6-sol` over Bedrock Mantle
  (counter-reviewer, read-only), riding
  `ParallelPerspectiveReviewDispatcher`; both seats selectable.
- **G6 — Cooperative research wiring**: dev_flow consumes the FEAT-482
  coordinator seam with the primary seat raised to `claude-opus-5` by
  default; the complementary partner stays **disabled by default** with an
  explicit console enable toggle (enabled default: `gpt-5.6-sol`).
- **G7 — Console surface**: `server_dev.py` (+ `static/dev.html`) exposes
  the three selector groups and the partner toggle with the defaults above.
- **G8 — Contract compliance**: FEAT-479 telemetry attribution per seat;
  FEAT-480 checkpoint compatibility with no `TOPOLOGY_VERSION` bump.

### Non-Goals (explicitly out of scope)

- **chrome-devtools MCP for web-based QA** — separate follow-up spec
  (resolved in brainstorm; FEAT-482 Module 6's `mcp_servers` profile field
  is the natural seam when that spec is written).
- **Per-agent worktrees / branch-per-sub-agent merging** — rejected in
  brainstorm (Option B); the shared-worktree `DevAgentPool` wave model
  with serialized commits is kept.
- **Backend registry refactor** — replacing the hardcoded 9-branch
  `build_dispatcher` chain (brainstorm Option C) is deferred to a
  follow-up brainstorm after FEAT-482/484 land.
- **Re-implementing FEAT-482/FEAT-484** — this feature consumes their
  contracts; it does not duplicate the partner/coordinator/toolkit work.
- **Perspective-parallel development** (same task to multiple models with
  merge) — the pool remains task-parallel.
- **Thinking-mode escalation for dev-pool seats** — development sub-agents
  are non-thinking by default; no reasoning-effort escalation is added.
- **New NVIDIA NIM defaults** — NIM currently returns 401 Unauthorized for
  this account; it stays selectable but never a default.

---

## 2. Architectural Design

### Overview

Option A from the brainstorm: **no new node types, no topology change** —
introduce one Pydantic config object, `DevFlowModelPlan`, and thread the
machinery that already exists in dev_loop through dev_flow's build surface.

`DevFlowModelPlan` groups four seat groups:

1. `research_primary` — model for the `IdeationNode` primary seat
   (default `claude-opus-5`, replacing the hardcoded `claude-sonnet-4-6`;
   shares the `DEV_FLOW_IDEATION_MODEL` seam FEAT-482 introduces).
2. `research_partner` — enable flag + `DevAgentSpec`-shaped selection for
   the FEAT-482 complementary partner (disabled by default; when enabled,
   default `gpt-5.6-sol` over Bedrock Mantle, `nova-2-lite` selectable).
   Resolution delegates to FEAT-482's `resolve_research_partner_backend()`.
3. `dev_pool` — explicit `list[DevAgentSpec]`; empty list ⇒ today's
   single-agent claude-code path. Non-empty ⇒ `DevelopmentNode` receives a
   `pool_config` + the existing `agent_builder.build_dispatcher` as
   `dispatcher_builder`.
4. `review` — primary reviewer spec (default claude-code/`claude-opus-5`)
   + counter-reviewer spec (default Mantle/`gpt-5.6-sol`), assembled into a
   `ParallelPerspectiveReviewDispatcher` (primary write-enabled, adversary
   read-only). `JudgeSpec` and the judge panel are untouched.

The wiring closes two verified gaps:

- `build_dev_flow()` / `build_dev_flow_node_factories()` accept
  `model_plan` and forward pool config/builder into `DevelopmentNode`, the
  primary model + partner coordinator into `IdeationNode` (FEAT-482 seam),
  and the assembled review dispatcher into `QANode` — replacing nothing
  when `model_plan` is omitted (backward compatible).
- **Single-task collapse rule** (in `DevelopmentNode`, benefiting dev_loop
  too): count tasks in the readable per-spec index; exactly one `TASK-` ⇒
  deploy only the first model from `PlannerOutput.suggested_pool` (falling
  back to the first configured spec); otherwise the full pool. No new
  typed field, no FEAT-480 allowlist change. `PlannerNode._resolve_pool`
  additionally stops hardcoding `DevAgentSpec(agent="claude-code")` and
  respects the configured pool backends.

An INFO log lands in `DevelopmentNode._execute_pool` immediately after
`DevAgentPool.build(...)` (`development.py:633`), e.g.:
`Deploying 2 dev sub-agents: w1=nova:zai.glm-5, w2=nova:qwen.qwen3-coder-480b-a35b-v1:0`.

The console (`server_dev.py`, port 8081) extends `/api/config` (defaults
block + catalog payload) and the run handler (reusing the ops-console
validators `_parse_dev_agents`/`_parse_judge_panel` where shapes match)
with the three selector groups and the partner toggle.

**Telemetry (FEAT-479)**: pool workers and the review pair run through
existing dispatchers that already wrap calls in
`usage_attribution(run_id, seat)` with per-run registry-bound clients;
seats appear in the run ledger as `development.wN`, review seats, and (via
FEAT-482) `ideation.partner`. Any newly built client must have
`_events_registry` bound to the per-run registry.

**Checkpoint (FEAT-480)**: node/edge shape is unchanged — no
`TOPOLOGY_VERSION` bump. Model-plan fields that affect routing join the
`execution_policy` fingerprint (documented consequence: changing the plan
between resume attempts is a deliberate fingerprint mismatch ⇒ fresh run).
Non-routing fields (e.g. the partner's model string) stay out of the
fingerprint, per FEAT-482's precedent.

### Component Diagram

```
                       DevFlowModelPlan (new, Pydantic)
                        │ research_primary / research_partner
                        │ dev_pool: list[DevAgentSpec]
                        │ review: primary + counter specs
                        ▼
 build_dev_flow(model_plan=…) ──► build_dev_flow_node_factories(…)
        │                                   │
        │            ┌──────────────────────┼──────────────────────────┐
        ▼            ▼                      ▼                          ▼
  IdeationNode   DevelopmentNode        QANode                 (other nodes:
  model=plan.    pool_config +          codereview_dispatcher   unchanged)
  research_      dispatcher_builder =   = ParallelPerspective
  primary;       agent_builder.         ReviewDispatcher(
  coordinator =  build_dispatcher         primary=claude/Opus5,
  FEAT-482 seam  │                        adversary=Mantle/
  (partner off   ▼                        gpt-5.6-sol read-only)
  by default)  DevAgentPool.build ──► INFO deployment log
                 │  task count == 1 ⇒ collapse to first
                 ▼  suggested_pool/configured spec
               run_wave (shared worktree, serialized commits)

 examples/dev_loop/server_dev.py ──► /api/config + run payload
   (3 selector groups + partner toggle → DevFlowModelPlan)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `build_dev_flow` / `build_dev_flow_node_factories` (`dev_flow/flow.py:85`, `factories.py:41`) | extends | new optional `model_plan` kwarg; omitted ⇒ today's behavior |
| `IdeationNode` (`dev_flow/nodes/ideation.py:91`) | modifies | primary model from plan / `DEV_FLOW_IDEATION_MODEL` instead of hardcoded literal (`:338`); consumes FEAT-482 `coordinator` kwarg |
| `DevelopmentNode` (`dev_loop/nodes/development.py:84`) | modifies | single-task collapse rule; INFO deployment log in `_execute_pool` (after `:633`); benefits dev_loop too |
| `PlannerNode._resolve_pool` (`dev_loop/nodes/planner.py:246-299`) | modifies | derived pool respects configured backends instead of hardcoded `DevAgentSpec(agent="claude-code")` (`:286`, `:298`) |
| `agent_builder.build_dispatcher` (`dev_loop/agent_builder.py:102-220`) | uses | pool workers + review seats materialize through it, unmodified |
| `ParallelPerspectiveReviewDispatcher` (`dev_loop/code_review.py:341`) | uses | carries the configurable review pair; `JudgeSpec` untouched |
| `NovaAdversarialReviewDispatcher` (`dev_loop/dispatchers/nova.py:239`) | extends/pattern | Mantle-hosted `gpt-5.6-sol` counter-reviewer, read-only by construction |
| `catalog.py` `BACKENDS` (`dev_loop/catalog.py:131-253`) | extends | model-list/roles additions (Qwen row for `nova`, `gpt-5.6-sol` reachable via Mantle role) — additive only |
| FEAT-482 deliverables (`dev_flow/research_partner.py`, `complementary_research.py` — future) | depends on | hard sequencing: FEAT-484 → FEAT-482 → this feature's research portion |
| FEAT-480 checkpoint plane (`dev_loop/checkpoint.py`) | depends on | routing-relevant plan fields join `execution_policy`; no topology change |
| FEAT-479 telemetry (`observability/context.py:126-158`, `dispatchers/llm.py:376-390`) | depends on | per-seat attribution contract for every new client |
| `examples/dev_loop/server_dev.py` + `static/dev.html` | extends | `/api/config` defaults, run-payload parsing, selector UI |

### Data Models

```python
# Design sketch — final field names settled at task decomposition.
# Reuses DevAgentSpec (dev_loop/models/base.py:412) rather than inventing
# a parallel spec shape.

class ResearchPartnerPlan(BaseModel):
    """Complementary research partner selection (FEAT-482 passthrough)."""
    enabled: bool = False                      # disabled by default (resolved)
    backend: str = "gpt"                       # FEAT-482 selector: "gpt" | "nova"
    model: str = "gpt-5.6-sol"                 # over BedrockMantleClient

class ReviewPairPlan(BaseModel):
    """Adversarial review pair riding ParallelPerspectiveReviewDispatcher."""
    primary: DevAgentSpec = DevAgentSpec(agent="claude-code", model="claude-opus-5")
    counter_model: str = "gpt-5.6-sol"         # Mantle-hosted, read-only seat

class DevFlowModelPlan(BaseModel):
    """Per-seat LLM configuration for a dev-flow run (FEAT-486)."""
    research_primary: str = "claude-opus-5"    # IdeationNode primary seat
    research_partner: ResearchPartnerPlan = ResearchPartnerPlan()
    dev_pool: list[DevAgentSpec] = []          # empty ⇒ single-agent claude-code
    review: ReviewPairPlan = ReviewPairPlan()
```

### New Public Interfaces

```python
# dev_flow build surface (signatures indicative, keyword-only like the rest)
def build_dev_flow(*, ..., model_plan: DevFlowModelPlan | None = None) -> AgentsFlow: ...
def build_dev_flow_node_factories(*, ..., model_plan: DevFlowModelPlan | None = None) -> dict: ...

# Mantle-hosted read-only counter-reviewer (mirrors NovaAdversarialReviewDispatcher)
class MantleAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):
    advisory = True   # read-only by construction — no tools, forces files_modified=[]

# Console: /api/config gains a `model_plan` defaults block; POST /api/flow/run
# accepts `dev_agents` (existing shape), `research_primary`, `research_partner`
# ({enabled, backend, model}), and `review` ({primary, counter_model}) fields.
```

---

## 3. Module Breakdown

### Module 1: DevFlowModelPlan + resolution
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py` (new) + `dev_flow/models.py` (exports)
- **Responsibility**: the Pydantic plan (sketch above), env-key defaults
  (`DEV_FLOW_IDEATION_MODEL` shared with FEAT-482; new keys for pool/review
  defaults), and a resolver producing the concrete wiring inputs
  (`DevAgentPoolConfig`, review dispatcher specs) with fail-fast validation
  against `DevAgentBackend` (unknown backend ⇒ `ValueError` with the
  supported list, before any dispatch).
- **Depends on**: existing `DevAgentSpec`/`DevAgentPoolConfig`
  (`dev_loop/models/base.py`).

### Module 2: Development pool wiring in dev_flow
- **Path**: `dev_flow/flow.py`, `dev_flow/factories.py`, `dev_flow/runner.py`
- **Responsibility**: accept `model_plan`; forward `pool_config` +
  `dispatcher_builder=agent_builder.build_dispatcher` into
  `DevelopmentNode`; thread plan through `DevFlowRunner` per-run
  (`extra_shared`/flow kwargs); routing-relevant plan fields join the
  FEAT-480 `execution_policy` fingerprint.
- **Depends on**: Module 1.

### Module 3: Single-task collapse + INFO deployment log
- **Path**: `dev_loop/nodes/development.py`, `dev_loop/nodes/planner.py`
- **Responsibility**: (a) collapse rule — readable task index with exactly
  one `TASK-` ⇒ deploy one agent using the first model from
  `PlannerOutput.suggested_pool`, falling back to the first configured
  spec; unreadable index keeps today's degradation (`development.py:202-206`);
  (b) INFO log after `DevAgentPool.build(...)` (`development.py:633`)
  enumerating `wN=backend:model` per worker (and an explicit INFO when
  collapsing to one agent); (c) `PlannerNode._resolve_pool` emits specs
  from the configured pool instead of hardcoded `agent="claude-code"`.
- **Depends on**: Module 2 (for the configured pool to exist in dev_flow;
  the log itself also benefits plain dev_loop runs).

### Module 4: Configurable adversarial review pair
- **Path**: `dev_loop/code_review.py` and/or `dev_loop/dispatchers/`
  (Mantle adversarial dispatcher), `dev_flow/factories.py` (assembly)
- **Responsibility**: a Mantle-hosted read-only adversarial dispatcher for
  `gpt-5.6-sol` (mirroring `NovaAdversarialReviewDispatcher` — advisory,
  no tools, `files_modified=[]`); plan-driven assembly of
  `ParallelPerspectiveReviewDispatcher(primary=…, adversary=…)` passed as
  dev_flow's `codereview_dispatcher`. No `JudgeSpec`/judge-panel changes.
  Additive `catalog.py` role/model-list entries.
- **Depends on**: Module 1.

### Module 5: Research seats wiring
- **Path**: `dev_flow/nodes/ideation.py`, `dev_flow/factories.py`
- **Responsibility**: primary seat model from
  `model_plan.research_primary` / `DEV_FLOW_IDEATION_MODEL` (removing the
  `claude-sonnet-4-6` literal at `ideation.py:338`); partner enablement
  passthrough to the FEAT-482 coordinator (plan enabled+backend+model →
  FEAT-482's `resolve_research_partner_backend()` inputs). Soft
  degradation per FEAT-482: partner failure never fails the run.
- **Depends on**: Module 1; **FEAT-484 → FEAT-482 merged** (hard
  sequencing — this module is blocked until the coordinator seam exists;
  the primary-model portion can land independently if FEAT-482 slips).

### Module 6: Console surface
- **Path**: `examples/dev_loop/server_dev.py`, `examples/dev_loop/static/dev.html`
- **Responsibility**: `/api/config` defaults block for the plan (dev pool
  default rows: `nova`/`zai.glm-5` + `nova`/`qwen.qwen3-coder-480b-a35b-v1:0`;
  research primary `claude-opus-5`; partner toggle default off, enabled
  default `gpt-5.6-sol`; review pair Opus 5 + `gpt-5.6-sol`); run-payload
  parsing (reuse `_parse_dev_agents` for the pool; new lightweight parsing
  for research/review fields with backend validation, model free-text per
  catalog policy); selector UI in `dev.html`. NIM remains listed, never a
  default.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_model_plan_defaults` | 1 | Default plan: research primary opus-5, partner disabled, empty pool, review pair Opus 5 + gpt-5.6-sol |
| `test_model_plan_unknown_backend_fails_fast` | 1 | `dev_pool` with unknown backend raises `ValueError` naming the supported backends before any dispatch |
| `test_model_plan_env_defaults` | 1 | Env keys override built-in defaults; explicit arguments override env |
| `test_build_dev_flow_without_plan_unchanged` | 2 | Omitting `model_plan` produces today's wiring (no pool_config, no dispatcher_builder, hardcoded review) |
| `test_build_dev_flow_threads_pool` | 2 | Plan with 2 specs ⇒ `DevelopmentNode` receives matching `pool_config` + `build_dispatcher` |
| `test_execution_policy_fingerprint_includes_plan` | 2 | Routing-relevant plan fields change the FEAT-480 fingerprint; non-routing fields do not |
| `test_single_task_collapse` | 3 | Index with one TASK ⇒ one worker deployed, first `suggested_pool` model, INFO says so |
| `test_multi_task_full_pool` | 3 | Index with >1 task ⇒ all configured specs deployed |
| `test_collapse_fallback_to_configured` | 3 | Empty/absent `suggested_pool` ⇒ first configured spec used |
| `test_unreadable_index_degrades` | 3 | Unreadable index keeps existing warning + single-agent degradation |
| `test_pool_deployment_info_log` | 3 | INFO log enumerates `wN=backend:model` for every worker (caplog) |
| `test_planner_pool_respects_configured_backends` | 3 | `_resolve_pool` derives specs from configured pool, not hardcoded claude-code |
| `test_mantle_adversarial_read_only` | 4 | Mantle adversarial dispatcher: `advisory=True`, no tools, `files_modified=[]` forced |
| `test_review_pair_assembly` | 4 | Plan ⇒ `ParallelPerspectiveReviewDispatcher` with claude primary + Mantle adversary; JudgeSpec untouched |
| `test_ideation_model_from_plan` | 5 | Ideation dispatch profile uses `research_primary` (default opus-5), not the removed literal |
| `test_partner_disabled_by_default` | 5 | No coordinator invoked when `research_partner.enabled=False` |
| `test_server_config_payload` | 6 | `/api/config` carries the plan defaults block with resolved defaults |
| `test_server_run_parses_plan_fields` | 6 | Run payload with pool rows + research/review fields builds the expected `DevFlowModelPlan`; unknown backend rejected with clear error |

### Integration Tests

| Test | Description |
|---|---|
| `test_dev_flow_multi_agent_end_to_end` | Stubbed dispatchers: plan with 2 pool specs, multi-task index ⇒ both workers dispatch, INFO log emitted, per-seat usage attributed (`development.w1`/`w2`) on the run ledger |
| `test_dev_flow_checkpoint_resume_with_plan` | Run with a plan, checkpoint, resume with same plan ⇒ hit; resume with changed routing field ⇒ fingerprint mismatch (fresh run) |
| `test_dev_flow_review_pair_end_to_end` | QA path invokes the parallel-perspective pair; adversary verdict merged, no writes from the adversary seat |

### Test Data / Fixtures

```python
@pytest.fixture
def model_plan_two_seats():
    return DevFlowModelPlan(dev_pool=[
        DevAgentSpec(agent="nova", model="zai.glm-5"),
        DevAgentSpec(agent="nova", model="qwen.qwen3-coder-480b-a35b-v1:0"),
    ])

@pytest.fixture
def single_task_index(tmp_path):
    """Per-spec index JSON with exactly one pending TASK- entry."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v`)
- [ ] All integration tests pass
- [ ] `build_dev_flow(model_plan=None)` (and every existing caller) behaves
  exactly as today — no breaking changes to the public build surface
- [ ] A plan with N dev-pool specs deploys N sub-agents (task-parallel
  waves, shared worktree, serialized commits — existing `DevAgentPool`
  semantics unchanged)
- [ ] Exactly one `TASK-` in the readable index ⇒ exactly one sub-agent,
  using the first model from `suggested_pool` (fallback: first configured
  spec); no new flag/typed field introduced; FEAT-480
  `_SHARED_DATA_ALLOWLIST` unchanged
- [ ] INFO log on pool deployment names the count and each worker's
  `backend:model`; collapse to one agent is also logged at INFO
- [ ] Review pair is configurable; defaults Opus 5 + `gpt-5.6-sol`; the
  counter-reviewer runs over Bedrock Mantle, is advisory/read-only by
  construction, and `JudgeSpec`/judge-panel code is not modified
- [ ] Ideation primary model is configurable (default `claude-opus-5`);
  the `claude-sonnet-4-6` literal at `ideation.py:338` is gone
- [ ] Research partner is disabled by default; the console exposes an
  enable toggle; enabling defaults to `gpt-5.6-sol`; partner failure
  degrades softly (run continues single-seat)
- [ ] Console defaults: dev pool = Bedrock GLM + Bedrock Qwen3 coder; NIM
  listed but never a default; kimi-k3 selectable via `moonshot` backend
- [ ] Every seat's token usage lands in the FEAT-479 run ledger with a
  distinct seat label (`development.wN`, review seats; `ideation.partner`
  once FEAT-482 lands)
- [ ] No `TOPOLOGY_VERSION` bump; checkpoint resume works with an
  unchanged plan and correctly misses on a changed routing-relevant field
- [ ] Documentation updated (`docs/dev_loop/` + console README/GUIA)
- [ ] `catalog.py` changes are additive (no existing backend row or triad
  removed or reshaped)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from the brainstorm's Code Context and re-verified
> against the current tree on 2026-09-01 (spot-checked anchors:
> `ideation.py:338`, `development.py:410,633`, `planner.py:171`,
> `bedrock_models.py:128`, `openai.py:22`, `code_review.py:361`).
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot.flows.dev_flow.flow import build_dev_flow            # dev_flow/flow.py:85
from parrot.flows.dev_loop.agent_builder import build_dispatcher  # agent_builder.py:102
from parrot.flows.dev_loop.models.base import DevAgentSpec        # models/base.py:412
from parrot.clients.factory import LLMFactory                     # factory.py:161
# NOT exported from parrot.clients __init__: OpenAICodexClient, ClaudeAgentClient,
#   NovaClient, BedrockMantleClient — import from their modules or via LLMFactory.
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/flow.py:85-107 (all keyword-only)
def build_dev_flow(*, dispatcher, redis_url, jira_toolkit=None, git_toolkit=None,
    wiki_toolkit=None, codereview_dispatcher=None, development_dispatcher_builder=None,
    development_pool_max: int = 4, graph_memory=None, wiki_search=None,
    skip_qa: bool = False, require_plan_approval: bool = False,
    ideation_max_rounds=None, name: str = "dev-flow", ...) -> AgentsFlow: ...
    # NOTE: no development_pool_config / development_dispatcher / development_profile / repos

# packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py:91,105-116
class IdeationNode(...):
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 wiki_search: DevLoopWikiSearch | None = None,
                 ideation_max_rounds: int | None = None, name: str = "ideation"): ...
    # model hardcoded "claude-sonnet-4-6" at ideation.py:338 inside the dispatch profile

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:84-98
class DevelopmentNode(...):
    def __init__(self, *, dispatcher: DevLoopCodeDispatcher, dispatch_profile=None,
                 pool_config: DevAgentPoolConfig | None = None,
                 dispatcher_builder: DispatcherBuilder | None = None, pool_max: int = 4,
                 require_plan_approval: bool = False, jira_toolkit=None,
                 name: str = "development"): ...
# DispatcherBuilder = Callable[[DevAgentSpec], Tuple[DevLoopCodeDispatcher, BaseModel]]  # development.py:54
# _resolve_pool_config reads ONLY shared["work_brief"|"bug_brief"].dev_agents  # development.py:400-415
# _execute_pool: pool = DevAgentPool.build(pool_cfg, self._dispatcher_builder, self._pool_max)  # development.py:633
#   ← INFO deployment log goes immediately after this line (no log exists there today)
# unreadable-index degradation warning at development.py:202-206

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:282
class DevAgentPool:
    async def run_wave(self, ...): ...  # round-robin tasks over workers (:320-322),
                                        # asyncio.gather (:324-332), one retry on next worker (:348-377)

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:102-220
def build_dispatcher(spec: DevAgentSpec, ...) -> tuple[DevLoopCodeDispatcher, BaseModel]: ...
# backends: claude-code | codex | gemini | nvidia | grok | zai | moonshot | google_coding | nova
# claude-code branch hardcodes model "claude-sonnet-4-6" (:144-146) — only backend with no model_env

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:407-423
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding","nova"]
class DevAgentSpec(BaseModel):
    agent: DevAgentBackend; model: str = ""; count: int = 1; escalation_model: str = ""

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py:84-99,246-299
class PlannerNode(...):
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher, development_pool_max: int = 4,
                 graph_memory=None, name: str = "planner"): ...
# _resolve_pool always emits DevAgentSpec(agent="claude-code") (:286, :298);
# PlannerOutput.suggested_pool set at planner.py:171 — consumed by NOTHING today

# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher: ...              # :85, advisory: bool = False (:100)
class CodexAdversarialReviewDispatcher: ...          # :267, model default conf.DEV_LOOP_ADVERSARIAL_MODEL (:290; conf fallback "gpt-5.5")
class ParallelPerspectiveReviewDispatcher:           # :341
    def __init__(self, *, primary, adversary, judge_dispatcher=None, judge_enabled=False): ...  # :361-373
class JudgePanelReviewDispatcher:                    # :596 — NOT modified by this feature
# JudgeSpec.agent validated ∈ {claude-code, codex, gemini}  # models/base.py:834,:857 — NOT modified
# NovaAdversarialReviewDispatcher — dispatchers/nova.py:239-240 (read-only pattern to mirror)

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
BACKENDS: Tuple[BackendInfo, ...]                    # :131-253 (9 entries; BackendInfo :98-127)
ADVERSARIAL_BACKEND = "codex"; choices ("codex","nova")  # :54,:60; resolve_adversarial_backend :63-91
# model lists are advisory, "never a whitelist" — pickers accept free text (:22-24)

# packages/ai-parrot/src/parrot/clients/claude_agent.py:265,287-292
class ClaudeAgentClient(AbstractClient):             # full coding-agent session client
    _default_model = "claude-sonnet-4-6"             # :284
    def __init__(self, cli_path=None, cwd=None, permission_mode=None,
                 run_options: ClaudeAgentRunOptions | None = None, **kwargs): ...

# packages/ai-parrot/src/parrot/clients/codex_agent.py:69,82-94
class OpenAICodexClient(AbstractClient):             # full coding-agent session client
    default_model = "gpt-5.1-codex"                  # :78
    def __init__(self, *, model=None, run_options=None, backend="auto",
                 codex_bin: str = "codex", **kwargs): ...

# packages/ai-parrot/src/parrot/clients/nova/mantle.py:32,86,89-95
class BedrockMantleClient(OpenAIBaseClient):         # Bedrock OpenAI-compatible endpoint, bearer key
    _default_model = "openai.gpt-oss-120b"
    def __init__(self, api_key=None, base_url=None, region=None, **kwargs): ...
    # key: api_key → BEDROCK_MANTLE_API_KEY → AWS_NOVA_API_KEY (:96)

# packages/ai-parrot/src/parrot/clients/nova/client.py:31,68
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    _default_model = "nova-2-lite"

# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                    # :161
    @staticmethod parse_llm_string(llm) -> tuple[str, str | None]  # :171 (split on FIRST ':')
    @classmethod  create(llm, model_args=None, tool_manager=None, **kwargs) -> AbstractClient  # :193
# registry keys include: "claude-agent"/"claude-code" -> ClaudeAgentClient (:144-145, lazy),
# "codex-agent"/"openai-codex"/"codex-code" -> OpenAICodexClient (:146-148, lazy),
# "nova" -> NovaClient (:120), "bedrock-mantle"/"mantle" -> BedrockMantleClient (:125-126),
# "nvidia" (:135), "moonshot"/"kimi" (:136-137), "zai"/"z.ai" (:132-133)

# FEAT-479 telemetry integration points
# parrot/observability/context.py:126-158 — usage_attribution(run_id, seat) ctx manager
# parrot/flows/dev_loop/runner.py:545-595 — per-run EventRegistry + RunLedgerRecorder
# parrot/flows/dev_loop/dispatchers/llm.py:376-390 — client._events_registry injection

# FEAT-480 checkpoint integration points
# parrot/flows/dev_loop/checkpoint.py — compute_input_fingerprint(), TOPOLOGY_VERSION = "1",
#   _SHARED_DATA_ALLOWLIST = (bug_brief, bug_findings, research_output, planner_output,
#                             development_output, dev_brief, feature_brief, ideation_output)
```

### Configuration & Model-Name References

- `OpenAIModel.GPT5_6_SOL = "gpt-5.6-sol"` → enum member (parrot/models/openai.py:22); **not wired** into any client default or catalog entry yet
- `MoonshotModel.KIMI_K3 = "kimi-k3"` → parrot/models/moonshot.py:22; `moonshot` backend default (agent_builder.py:198, catalog.py:224-225)
- `PUBLIC_TO_BEDROCK["qwen3-coder-480b-a35b"] = "qwen.qwen3-coder-480b-a35b-v1:0"` → parrot/models/bedrock_models.py:128; `"glm-5"` → `"zai.glm-5"` :130; `"claude-opus-5"` → :116; `"nova-2-lite"` → :150
- `NvidiaModel.KIMI_K2_6 = "moonshotai/kimi-k2.6"` → parrot/models/nvidia.py:51 (account-gated); `GLM_5_2 = "z-ai/glm-5.2"` → :74
- `conf.DEV_LOOP_ADVERSARIAL_MODEL` fallback `"gpt-5.5"` → conf.py:947; `DEV_LOOP_JUDGE_PANEL` (JSON) → conf.py:991
- `server_dev.py` defaults block → :209-231 (`development_agent` fallback `"claude-code"` :210); run parsing via `ops_server._parse_dev_agents` (:169) / `_parse_judge_panel` (:172); validators at `server.py:1026-1058` / `:1065-1094` (backend strict, model free-text)

### Integration Points (contract table)

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DevFlowModelPlan` resolver | `DevAgentSpec` / `DevAgentPoolConfig` | model reuse | `dev_loop/models/base.py:412` |
| dev_flow pool wiring | `DevelopmentNode(pool_config=…, dispatcher_builder=…)` | constructor kwargs | `development.py:87-98` |
| pool workers | `agent_builder.build_dispatcher(spec)` | `DispatcherBuilder` callable | `agent_builder.py:102-220` |
| collapse rule | `PlannerOutput.suggested_pool` | shared-data read | `planner.py:171` (currently unconsumed) |
| deployment log | `DevelopmentNode._execute_pool` | after `DevAgentPool.build` | `development.py:633` |
| review pair | `ParallelPerspectiveReviewDispatcher(primary=…, adversary=…)` | constructor | `code_review.py:361-373` |
| Mantle counter-reviewer | `BedrockMantleClient` | client construction | `clients/nova/mantle.py:32` |
| ideation primary model | FEAT-482 `DEV_FLOW_IDEATION_MODEL` seam | conf key + plan | `ideation.py:338` (literal to remove) |
| partner passthrough | FEAT-482 `resolve_research_partner_backend()` / coordinator kwarg | future seam | FEAT-482 spec (not yet on disk) |
| console | `/api/config` + run handler | payload extension | `server_dev.py:195-334` |

### Does NOT Exist (Anti-Hallucination)

- ~~`moonshotai/kimi-k3` on NVIDIA NIM~~ — `NvidiaModel` has only `moonshotai/kimi-k2.6` (account-gated). kimi-k3 exists only on the direct Moonshot API (`moonshot` backend). **NIM currently returns 401 Unauthorized for this account** — never a default.
- ~~`gpt-5.5-codex` in `OpenAIModel`~~ — enum has `gpt-5.3-codex` then `gpt-5.5`; the string exists only in the catalog tuple (catalog.py:154) as a free-text picker option.
- ~~`gpt-5.6-sol` reachable via the `codex` backend or any client default~~ — enum member only; this feature (and FEAT-482) run it over `BedrockMantleClient`.
- ~~A research node in dev_flow~~ — deliberately absent (dev_flow/definition.py:126-127); the research seat is `IdeationNode`.
- ~~`development_pool_config` / `repos` / `development_profile` parameters on `build_dev_flow`~~ — do not exist yet (this spec adds the plan-driven equivalent).
- ~~Any consumer of `PlannerOutput.suggested_pool`~~ — computed but read by nothing (Module 3 becomes the first consumer).
- ~~FEAT-482 implementation~~ — `dev_flow/research_partner.py`, `complementary_research.py`, `ResearchFindings`, `ComplementaryResearchCoordinator`, `DEV_FLOW_RESEARCH_PARTNER*` conf keys: none exist yet (spec approved, 8 tasks pending). Module 5's partner portion is blocked on it.
- ~~FEAT-484 implementation~~ — `parrot/tools/repo/` does not exist on disk (tasks in-progress, no code in this checkout).
- ~~`mcp_servers` on `ClaudeCodeDispatchProfile`~~ — planned by FEAT-482 Module 6, not present.
- ~~Per-node client/model constructor params on `IdeationNode`/`PlannerNode`/`QANode`/`SynthesisNode`/`FeedbackRouterNode`~~ — models are hardcoded literals or profile defaults today.
- ~~A provider-agnostic coding-sub-agent abstraction~~ — `ClaudeAgentClient` and `OpenAICodexClient` share only `AbstractClient`; run-options types, constructor shapes, and tool bridges (in-process SDK-MCP vs. localhost HTTP MCP) all differ.
- ~~`DevFlowRunner.__init__`~~ — does not exist; the class inherits `DevLoopRunner.__init__` (dev_loop/runner.py:389-403) verbatim.
- ~~`MantleAdversarialReviewDispatcher`~~ — proposed by this spec (Module 4); does not exist yet.
- ~~`DevFlowModelPlan` / `dev_flow/model_plan.py`~~ — proposed by this spec (Module 1); does not exist yet.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first throughout; Pydantic models for all config structures;
  `self.logger` (node loggers are `parrot.node.<name>`,
  `bots/flows/core/node.py:121`) — the deployment log uses the existing
  `DevelopmentNode` logger at INFO.
- Mirror existing triad/dispatcher patterns: the Mantle adversarial
  dispatcher mirrors `NovaAdversarialReviewDispatcher` (read-only by
  construction); catalog additions follow `BackendInfo` conventions and
  stay additive; model pickers stay free-text with strict backend
  validation (`catalog.py:22-24`, `server.py:1026-1058`).
- Keyword-only build-surface parameters, `None`-default optionals, exact
  backward compatibility when `model_plan` is omitted.
- FEAT-479: every newly built client must be bound to the per-run event
  registry (`dispatchers/llm.py:376-390`) and dispatched inside
  `usage_attribution(run_id, seat)`; seat labels are free strings.
- FEAT-480: no serialized live objects; the plan is reconstructed by the
  per-run factory; routing-relevant fields enter `execution_policy` only.

### Known Risks / Gotchas

- **Sequencing**: Module 5's partner portion is hard-blocked on
  FEAT-484 → FEAT-482 merging; this feature also touches files FEAT-482
  will modify (`dev_flow/factories.py`, `ideation.py`, `catalog.py`,
  `conf.py`). Land this feature after FEAT-482, keeping edits additive.
- **Fingerprint churn**: adding routing-relevant keys to
  `execution_policy` changes fingerprints for callers that set them —
  documented, accepted consequence; omitted plan ⇒ unchanged fingerprints.
- **Partner/seat failure modes**: partner degradation is soft (run
  continues single-seat, `partner.degraded` event); a pool worker's
  provider failure uses the existing one-retry-on-next-worker wave logic;
  an unknown backend fails fast at plan-resolution time.
- **Model free-text**: a typo'd model surfaces as a provider error on that
  seat at dispatch time — by design (catalog policy), mitigated by picker
  lists in the console.
- **Mantle specifics**: bearer-key auth (`BEDROCK_MANTLE_API_KEY` →
  `AWS_NOVA_API_KEY` fallback), no model enum (raw strings), per-model
  output-token ceilings (`dev_loop/models/nova.py:51-56`) — the
  gpt-5.6-sol review seat needs a sensible max_tokens.
- **NIM 401**: NVIDIA NIM is currently unusable for this account (401
  Unauthorized even on other NIM models) — keep selectable, never default,
  and surface the provider error cleanly if chosen.
- **Concurrent-worktree discipline**: the shared-worktree pool relies on
  disjoint per-task file sets and serialized commits; the collapse rule
  reduces exposure for single-task features.
- **Spanish-locale git output** on this machine — scripts parsing git
  output must not match on localized strings.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | Rides existing deps: `claude-agent-sdk` (lazy), Codex CLI/SDK, `aioboto3` (Bedrock/Nova), aiohttp OpenAI-compatible transports (Mantle/NVIDIA/Moonshot/Z.ai), `pydantic` v2 |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one
  worktree (`.claude/worktrees/feat-486-refactor-dev-flow`, branched from
  `dev`).
- **Rationale**: Modules 1–6 converge on the same few files
  (`dev_flow/flow.py`, `factories.py`, `runner.py`,
  `dev_loop/nodes/development.py`, `server_dev.py`); parallel worktrees
  would be a merge hazard for no wall-clock gain.
- **Cross-feature dependencies (must merge first)**:
  1. FEAT-484 (`readonly-repo-toolkit`) → 2. FEAT-482
  (`devflow-complementary-research`) — hard prerequisite for Module 5's
  partner portion; strongly preferred before starting Modules 1–4 too,
  since FEAT-482 edits `dev_flow/factories.py`, `ideation.py`,
  `catalog.py`, and `conf.py`. Watch `expose-toolkits-as-local-mcp`
  (in-flight proposal) for `mcp_servers`-seam overlap.
- **Contingency**: if FEAT-482 slips, Modules 1–4 + 6 (minus the partner
  toggle) can ship first, with Module 5's partner passthrough as a
  follow-on task gated on FEAT-482.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Flow type and base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] chrome-devtools MCP for web QA — *Resolved in brainstorm*: out of this feature; separate follow-up spec (FEAT-482 Module 6's `mcp_servers` field is the natural seam).
- [x] Development pool sizing model — *Resolved in brainstorm*: fixed configurable pool — operator supplies an explicit client-spec list (size N derives from it); no lineup baked into the flow.
- [x] Worktree model for concurrent sub-agents — *Resolved in brainstorm*: one shared feature worktree, disjoint task sets, serialized commits (existing `DevAgentPool` wave model); no per-agent worktrees.
- [x] Default model pairs — *Resolved in brainstorm*: Opus 5 + `gpt-5.6-sol` everywhere (research primary+partner, adversarial review pair); AWS Nova 2 stays selectable.
- [x] kimi-k3 routing — *Resolved in brainstorm*: NVIDIA NIM currently unusable (401 Unauthorized); any unavailable NIM seat is replaced with Qwen3 coder on Amazon Bedrock (`qwen.qwen3-coder-480b-a35b-v1:0`). Console default pool = Bedrock GLM + Bedrock Qwen3 coder; NIM stays in the picker; kimi-k3 selectable via `moonshot`.
- [x] gpt-5.6-sol transport for review — *Resolved in brainstorm*: over Bedrock Mantle via a read-only-by-construction adversarial dispatcher; `codex` backend model list NOT extended.
- [x] GLM-on-Bedrock transport — *Resolved in brainstorm*: `nova` backend over Bedrock Mantle with `zai.glm-5` as the console default row; direct `zai` backend stays selectable.
- [x] Collapse-signal carrier — *Resolved in brainstorm*: no new flag or typed field; exactly one `TASK-` ⇒ one agent taking the first model from `PlannerOutput.suggested_pool`; otherwise full configured pool. No FEAT-480 allowlist change.
- [x] Research partner default state — *Resolved in brainstorm*: disabled by default (FEAT-482's shipping default); console adds an explicit enable toggle (enabling defaults the partner to `gpt-5.6-sol`).
- [x] JudgeSpec backend widening — *Resolved in brainstorm*: no change — the review pair rides `ParallelPerspectiveReviewDispatcher` (`code_review.py:341`), not the judge panel.
- [ ] Backend registry refactor (brainstorm Option C) — file as a separate follow-up brainstorm once FEAT-482/484 land? — *Owner: Jesus Lara* (does not block this feature)
- [ ] Exact conf key names for the new plan defaults (pool/review) — settle at task decomposition, mirroring `DEV_LOOP_*`/`DEV_FLOW_*` conventions and FEAT-482's key set to avoid collisions. — *Owner: spec review / task phase*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | Jesus Lara (with Claude) | Initial draft from accepted refactor-dev-flow brainstorm (Option A) and verified codebase contract |
