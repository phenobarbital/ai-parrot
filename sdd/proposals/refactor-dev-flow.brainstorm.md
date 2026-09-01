---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Refactor Dev-Flow — Cooperative Research, Multi-Agent Development Pool, Configurable Review

**Date**: 2026-08-31
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`dev_flow` (`packages/ai-parrot/src/parrot/flows/dev_flow/`) is the SDD-oriented
AgentsFlow covering intake/ideation → planner → development pool → synthesis →
QA → PR. In its current form every LLM-facing seat is effectively **one
hardcoded Claude agent**:

- **Research/ideation** is a single seat: `IdeationNode` dispatches one
  `sdd-ideation` Claude Code session with the model hardcoded to
  `claude-sonnet-4-6` (`dev_flow/nodes/ideation.py:338`). The two-sided
  complementary research design (FEAT-482) is an approved spec with **zero
  code** — 8 tasks pending, blocked on FEAT-484 (`ReadOnlyRepoToolkit`, also
  not yet on disk).
- **Development** is single-agent in practice. `DevelopmentNode` *does* have a
  task-parallel `DevAgentPool` (`dev_loop/nodes/development.py:608`,
  `dev_loop/agent_pool.py:282`), but dev_flow can never reach it:
  `build_dev_flow()` exposes no `development_pool_config` /
  `development_dispatcher_builder`-driven pool path
  (`dev_flow/flow.py:85-107`), and `PlannerOutput.suggested_pool` is computed
  (`dev_loop/nodes/planner.py:170-171`) **but never consumed** —
  `DevelopmentNode._resolve_pool_config` reads only `work_brief`/`bug_brief`
  (`development.py:410`), neither of which dev_flow populates. Result: token
  pressure concentrates on a single Claude model and vendor.
- **Adversarial code review** machinery is configurable in dev_loop
  (`JudgePanelReviewDispatcher`, `DEV_LOOP_ADVERSARIAL_MODEL`,
  `DEV_LOOP_JUDGE_PANEL`), but dev_flow only receives whatever single
  `codereview_dispatcher` object the caller pre-built — there is no dev-flow
  configuration surface for the review model pair.
- **The console** (`examples/dev_loop/server_dev.py`) exposes no per-seat LLM
  selection for research, development sub-agents, or the review pair.

Who is affected: operators running the dev-flow console (cost/latency/vendor
concentration), and the SDD pipeline quality itself (single-perspective
research and review).

Why now: FEAT-479 (per-run token ledger) and FEAT-480 (checkpoint/resume)
just landed, giving us the accounting and resume substrate multi-agent seats
need; FEAT-482/FEAT-484 define the research-partner contracts this feature
must plug into rather than reinvent.

Out of scope (decided during discovery): the chrome-devtools MCP integration
for web-based QA is a **separate follow-up spec** (see Open Questions).

## Constraints & Requirements

- **Every LLM client for every seat must be configurable via arguments**
  (constructor/config first; console UI on top; env keys as defaults).
- **Development pool**: fixed configurable pool — operator supplies an
  explicit list of `(backend, model)` client specs, pool size N derives from
  that list. No default lineup baked into the flow; the console UI defaults to
  Bedrock GLM + Bedrock Qwen3 coder. **NVIDIA NIM is currently unusable for
  this account (401 Unauthorized, observed even on other NIM models such as
  gemma): any NIM seat is replaced by Qwen coder on Amazon Bedrock**; NIM
  stays selectable in the picker, kimi-k3 stays selectable via the direct
  `moonshot` backend.
- **Single-task collapse rule (no flag)**: pool composition is fixed by
  config; no explicit verdict field is added. When research/planning ends
  with exactly one `TASK-`, the Development node deploys a single sub-agent —
  the first model from `suggested_pool`/the configured list. More than one
  task ⇒ the full configured pool deploys.
- **Development sub-agents are non-thinking models** (Claude sonnet,
  gpt-5.5-codex, kimi-k3, GLM) — the pool spec must not enable
  thinking/reasoning-effort escalation by default for these seats.
- **Worktree safety**: one shared feature worktree, concurrent sub-agents on
  disjoint task file-sets, commits serialized by the dispatcher (this is
  `DevAgentPool`'s existing shared-worktree wave model — keep it; do not
  introduce per-agent worktrees in this feature).
- **INFO log** in the Development node announcing pool deployment: how many
  sub-agents and which LLM model each one uses.
- **Defaults** (user decision): research primary = Claude Opus 5, research
  complementary partner = `gpt-5.6-sol`; adversarial review pair = Claude
  Opus 5 + `gpt-5.6-sol`. AWS Nova 2 stays selectable everywhere.
- **Reuse, don't fork**: cooperative research must reuse/extend the approved
  FEAT-482 contracts (`AbstractResearchPartner`, `ComplementaryResearchCoordinator`,
  `ResearchPartnerFactory`) — this feature depends on FEAT-484 → FEAT-482
  landing first and only adds the dev_flow wiring + configurability on top.
- **Telemetry contract (FEAT-479)**: every new seat's client must have
  `_events_registry` bound to the per-run registry and run inside
  `usage_attribution(run_id, seat)` so its tokens reach the run ledger.
- **Checkpoint contract (FEAT-480)**: no node/edge shape change without a
  `TOPOLOGY_VERSION` bump; routing-relevant config goes through
  `execution_policy` (accepting the documented fingerprint invalidation);
  partner findings/pool results must ride inside allowlisted typed results.
- Async-first, Pydantic models for all config structures, `self.logger` for
  logging (project standards).

---

## Options Explored

### Option A: Config-Surface Extension — thread existing machinery through dev_flow (Recommended)

No new node types, no topology change. Introduce one Pydantic config object —
working name `DevFlowModelPlan` — grouping the per-seat client specs:

- `research_primary: str` (default `"claude-opus-5"` — feeds the FEAT-482
  `DEV_FLOW_IDEATION_MODEL` seam so IdeationNode stops hardcoding
  `claude-sonnet-4-6`),
- `research_partner: DevAgentSpec | None` (default backend `nova`/Mantle,
  model `gpt-5.6-sol` — resolved through FEAT-482's
  `resolve_research_partner_backend()`),
- `dev_pool: list[DevAgentSpec]` (explicit operator list; empty = single-agent
  with the first/default claude-code seat),
- `review_panel: list[JudgeSpec]` / adversarial pair (default Opus 5 +
  `gpt-5.6-sol`).

Then wire what already exists:

1. `build_dev_flow()` / `build_dev_flow_node_factories()` accept the plan and
   forward `pool_config` + `dispatcher_builder`
   (`dev_loop/agent_builder.build_dispatcher`) into `DevelopmentNode`, the
   coordinator into `IdeationNode` (FEAT-482 seam), and a
   panel/parallel-perspective dispatcher into `QANode`.
2. Close the `suggested_pool` gap: `DevelopmentNode` (or the dev_flow wiring)
   consumes `PlannerOutput.suggested_pool`/an ideation "single-agent-ok"
   signal to collapse the configured pool to its first entry.
3. Add the INFO deployment log in `DevelopmentNode._execute_pool` right after
   `DevAgentPool.build(...)` (`development.py:633`), enumerating
   `backend/model` per worker.
4. `server_dev.py`: extend `/api/config` defaults + run-payload parsing
   (reusing `_parse_dev_agents` / `_parse_judge_panel`, which already accept
   free-text models) with the three new selector groups and the agreed
   defaults.

✅ **Pros:**
- Smallest diff for the full requirement set; every mechanism (pool, waves,
  retry, conflict resolver, judge panel, partner coordinator) already exists
  and is battle-tested in dev_loop.
- No `TOPOLOGY_VERSION` bump — node/edge shape is unchanged, so FEAT-480
  checkpoints keep working (only fingerprints of runs that opt into new
  `execution_policy` keys change, which is the documented behavior).
- FEAT-479 telemetry works for free for pool workers (dispatchers already
  wrap calls in `usage_attribution`; seats appear as `development.wN`).
- Keeps dev_flow's "consume dev_loop nodes by type name" architecture intact
  — fixes land once and benefit both flows.

❌ **Cons:**
- Hard sequencing dependency: research configurability is only as good as
  FEAT-484 → FEAT-482 landing first (7 + 8 tasks still pending).
- `build_dev_flow`'s keyword surface keeps growing (mitigated by the single
  `DevFlowModelPlan` object instead of N loose kwargs).
- Does not fix the underlying backend-registration debt (hardcoded 9-branch
  `build_dispatcher` chain + hand-maintained catalog tuple) — extending model
  lists still means editing `catalog.py`.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Everything rides on existing deps: `claude-agent-sdk` (lazy in `clients/claude_agent.py`), Codex CLI/SDK (`clients/codex_agent.py`), `aioboto3` (Bedrock/Nova), aiohttp (Mantle/NVIDIA/Moonshot/Z.ai OpenAI-compatible transports) |
| `pydantic` (already core) | `DevFlowModelPlan` config model | v2, matches project standard |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/agent_builder.py:102-220` — `build_dispatcher(spec)` maps `DevAgentSpec` → `(dispatcher, profile)` for all 9 backends
- `parrot/flows/dev_loop/agent_pool.py:282-395` — `DevAgentPool.run_wave` shared-worktree wave dispatch with retry
- `parrot/flows/dev_loop/code_review.py:341,596` — `ParallelPerspectiveReviewDispatcher`, `JudgePanelReviewDispatcher`
- `parrot/flows/dev_loop/catalog.py:131-253` — `BACKENDS` metadata + `catalog_payload()` already feeding the console pickers
- FEAT-482 contracts (once landed): `dev_flow/research_partner.py`, `dev_flow/complementary_research.py`, the `IdeationNode(coordinator=...)` seam
- `examples/dev_loop/server.py:1026-1094` — `_parse_dev_agents` / `_parse_judge_panel` validators

---

### Option B: Dedicated Multi-Perspective Nodes in dev_flow

Fork the reused dev_loop nodes: new `CooperativeResearchNode` (replacing the
FEAT-482 in-node coordinator with a first-class two-seat node),
`MultiAgentDevelopmentNode` (owning pool logic natively, per-agent branches +
merge in Synthesis), and a `ConfigurableReviewNode`, all under
`dev_flow/nodes/`.

✅ **Pros:**
- dev_flow gets full ownership of its seats; no coupling to dev_loop node
  internals or the `suggested_pool` compat bridge.
- A two-seat research *node* (vs. an in-node coordinator) makes the partner a
  visible topology element with its own lifecycle events and checkpoint entry.

❌ **Cons:**
- Duplicates large, subtle machinery (waves, retries, conflict resolution,
  judge merge) that dev_loop already owns — divergence risk is high.
- Topology change ⇒ `TOPOLOGY_VERSION` bump, all in-flight checkpoints
  invalidated; new typed results must be added to
  `_SHARED_DATA_ALLOWLIST` + `register_checkpoint_type()`.
- Directly contradicts FEAT-482's approved design (coordinator inside the
  existing node, "one optional constructor kwarg", explicitly to avoid
  fingerprint churn) — would require re-opening an approved spec.
- Highest task count; per-agent worktree merging was explicitly rejected in
  discovery (shared worktree, serialized commits, is the decided model).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Same client stack as Option A |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/core/` node primitives; `dev_loop/agent_pool.py` (as a copy-base, which is the problem)

---

### Option C: Backend Registry + Role-Based Model Plane (unconventional)

Attack the root debt instead of the symptom: replace the hardcoded
`build_dispatcher` if/elif chain (`agent_builder.py:141-220`), the
hand-maintained `BACKENDS` tuple (`catalog.py:131-253`), and the
`DevAgentBackend` Literal (`dev_loop/models/base.py:407-409`) with a
decorator-registered `BackendRegistry` (mirroring `parrot.registry` /
`CodeReviewDispatcherFactory.register`). Every backend declares its roles
(`development`, `research_primary`, `research_partner`, `judge`,
`adversarial`), and a single `RunModelPlan` resolves *every* seat in both
dev_loop and dev_flow by role. Console pickers become fully registry-driven.

✅ **Pros:**
- Solves configurability once, for all current and future seats; adding a
  vendor becomes one registration, not three parallel edits.
- Eliminates the drift class of bugs the catalog docstring already warns
  about (catalog must mirror the chain by hand).
- Roles subsume FEAT-482's `roles=("research_partner",)` catalog extension
  cleanly.

❌ **Cons:**
- Large blast radius across dev_loop **and** dev_flow while FEAT-482/484 are
  in flight on the same files — guaranteed merge friction.
- Rewrites surfaces that two just-approved specs treat as stable contracts
  (`catalog.py` triads, `DevAgentSpec` validation, `JudgeSpec.agent` Literal).
- Delays the user-visible outcome (multi-vendor dev pool, configurable
  review) behind an infrastructure refactor.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Pure refactor of existing registration patterns |

🔗 **Existing Code to Reuse:**
- `parrot/registry` decorator pattern; `code_review.py:164` `CodeReviewDispatcherFactory` (register/create); `catalog.py` `BackendInfo` dataclass (kept as the registered metadata record)

---

## Recommendation

**Option A** is recommended because:

- Every capability the user asked for maps to machinery that already exists
  and works in dev_loop — the actual defect is that dev_flow cannot *reach*
  it (`build_dev_flow` surface, unconsumed `suggested_pool`). Wiring beats
  rebuilding.
- It is the only option compatible with the two in-flight approved specs:
  FEAT-482 explicitly designed its coordinator as an in-node seam to avoid
  topology/fingerprint churn, and Option A consumes that seam as-is; Option B
  would re-open the spec, Option C would rewrite its foundations mid-flight.
- Checkpoint (FEAT-480) and telemetry (FEAT-479) keep working with no
  `TOPOLOGY_VERSION` bump and no new attribution plumbing.
- What we trade off: the backend-registration debt (Option C) stays. That is
  acceptable — it is invisible to operators, and Option A's
  `DevFlowModelPlan` gives us the role-shaped config object that a later
  registry refactor can adopt wholesale. Recorded as an open question for a
  follow-up brainstorm.

---

## Feature Description

### User-Facing Behavior

- The dev-flow console (`server_dev.py`, port 8081) gains three selector
  groups on the run form, all backed by `/api/config`:
  1. **Development sub-agents**: an editable list of `(backend, model)` rows
     (same shape as the existing ops-console `dev_agents` rows). UI default:
     Bedrock GLM (`nova` backend, `zai.glm-5`) + Qwen3 coder (`nova` backend,
     `qwen.qwen3-coder-480b-a35b-v1:0`; public alias `qwen3-coder-480b-a35b`,
     `parrot/models/bedrock_models.py:128`). NIM stays selectable but is not
     a default (401 for this account); kimi-k3 selectable via the `moonshot`
     backend. Empty list ⇒ single-agent claude-code.
  2. **Research models**: primary (default `claude-opus-5`) and complementary
     partner — **disabled by default** (FEAT-482's shipping default) with an
     explicit enable flag in the UI; when enabled, defaults to `gpt-5.6-sol`
     over Bedrock Mantle, `nova-2-lite` selectable.
  3. **Adversarial review pair**: primary reviewer (default `claude-opus-5`)
     and counter-reviewer (default `gpt-5.6-sol` over Bedrock Mantle via a
     read-only adversarial dispatcher; Nova 2 selectable).
- When the Development node deploys the pool, the operator sees an INFO log
  line (and the existing flow events) stating how many sub-agents launched
  and which backend/model each seat runs, e.g.
  `Deploying 2 dev sub-agents: w1=nova:zai.glm-5, w2=moonshot:kimi-k3`.
- The research artifact (`sdd/proposals/<slug>.research.md`, FEAT-482) shows
  both seats' findings with attribution; the run's usage report breaks token
  spend down per seat (`ideation`, `ideation.partner`, `development.wN`,
  judges) — vendor diversification is visible in the ledger.
- If research/planning produces exactly one task, the run proceeds
  single-agent with the first model from the suggested/configured pool; the
  log says so explicitly.

### Internal Behavior

- A new `DevFlowModelPlan` Pydantic model carries the four seat groups
  (research primary, research partner, dev pool list, review pair). It is
  accepted by `build_dev_flow(...)` / `DevFlowRunner`, resolved once per run,
  and threaded to: `IdeationNode` (model override + FEAT-482 coordinator),
  `DevelopmentNode` (`pool_config` + `dispatcher_builder` from
  `agent_builder.build_dispatcher`), and `QANode`
  (`ParallelPerspectiveReviewDispatcher` or judge panel built from the pair).
- Pool collapse rule: pool composition comes from config; **no new flag or
  typed field is introduced** (so no FEAT-480 allowlist change). The
  Development node counts tasks in the per-spec index: exactly one `TASK-` ⇒
  deploy only the first model from `PlannerOutput.suggested_pool` (falling
  back to the first configured spec); otherwise deploy the full pool.
  Dependency-chained task graphs already serialize naturally through the
  existing wave logic.
- Worktree model is unchanged: one feature worktree, `DevAgentPool.run_wave`
  round-robins disjoint tasks across workers, dispatch serialization and the
  existing conflict resolver handle commit ordering.
- Per-seat clients are built through the existing factory paths
  (`LLMFactory.create`, `agent_builder.build_dispatcher`,
  `ResearchPartnerFactory`), each bound to the per-run event registry and
  wrapped in `usage_attribution(run_id, seat)` so FEAT-479 accounting holds.
- Console: `server_dev.py` extends its `/api/config` defaults block and run
  handler; parsing reuses `_parse_dev_agents`/`_parse_judge_panel`.

### Edge Cases & Error Handling

- **Partner unavailable/misconfigured** (missing `AWS_NOVA_API_KEY`, backend
  rejected): FEAT-482 soft degradation applies — coordinator returns `None`,
  research continues single-seat, `partner.degraded` event emitted. Never
  fails the run.
- **A pool worker's backend fails mid-wave**: existing `run_wave` retry
  (reassign to next worker once) applies; if a backend cannot even be built
  (`build_dispatcher` `ValueError` on unknown backend), the run fails fast at
  config-resolution time with the supported-backend list — before any
  dispatch.
- **Empty dev pool list**: identical to today's single-agent path
  (`_execute_single`), including honoring an injected profile.
- **Task index unreadable**: falls back to today's behavior (existing warning
  + single-agent degradation at `development.py:202-206`); with a readable
  index, one task ⇒ one agent, multiple tasks ⇒ full configured pool (config
  is authoritative; the task count only shrinks the pool, never grows it).
- **Checkpoint resume**: model-plan fields that affect routing enter the
  FEAT-480 `execution_policy` fingerprint — changing the plan between resume
  attempts is a deliberate fingerprint mismatch (fresh run), not a silent
  reuse. Non-routing fields (e.g. partner model name) stay out of the
  fingerprint per FEAT-482's precedent.
- **Model id typos**: model strings remain free text by design
  (`catalog.py:22-24`); backend validation is strict, model validation is
  advisory (picker lists). A wrong model surfaces as a provider error on the
  seat, retried/degraded per the mechanisms above.

---

## Capabilities

### New Capabilities
- `dev-flow-model-plan`: per-seat LLM client configuration object accepted by
  `build_dev_flow`/`DevFlowRunner` (research primary/partner, dev pool,
  review pair), with env-key defaults.
- `dev-flow-multi-agent-development`: reachable `DevAgentPool` in dev_flow —
  operator-defined pool, single-task collapse to one agent, INFO deployment
  log.
- `dev-flow-configurable-review`: configurable adversarial review pair for
  dev_flow (default Opus 5 + gpt-5.6-sol).
- `dev-flow-console-llm-selectors`: `server_dev.py` UI + API surface for all
  of the above.

### Modified Capabilities
- `sdd-dev-flow` (FEAT-412 spec): `build_dev_flow` surface, factories wiring.
- `devflow-complementary-research` (FEAT-482): consumed dependency; the
  partner keeps FEAT-482's disabled-by-default, with an enable flag exposed
  in the dev-flow console.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_flow/flow.py`, `factories.py`, `runner.py` | modifies | accept + thread `DevFlowModelPlan`; forward pool/coordinator/review wiring |
| `parrot/flows/dev_flow/nodes/ideation.py` | modifies | replace hardcoded `claude-sonnet-4-6` with plan/`DEV_FLOW_IDEATION_MODEL` (shared seam with FEAT-482) |
| `parrot/flows/dev_loop/nodes/development.py` | modifies | consume `suggested_pool`/collapse signal; add INFO deployment log in `_execute_pool` (benefits dev_loop too) |
| `parrot/flows/dev_loop/nodes/planner.py` | modifies | derived pool respects configured backends instead of hardcoded `DevAgentSpec(agent="claude-code")` (`planner.py:286,298`) |
| `parrot/flows/dev_loop/catalog.py` | extends | model lists/roles for the new default pairs (e.g. `gpt-5.6-sol` reachable via `nova`/Mantle role) |
| `examples/dev_loop/server_dev.py` (+ `static/dev.html`) | extends | `/api/config` defaults, run-payload parsing, selector UI |
| FEAT-482 / FEAT-484 deliverables | depends on | hard sequencing: FEAT-484 → FEAT-482 → this feature (research portion) |
| FEAT-480 checkpoint plane | depends on | routing-relevant plan fields join `execution_policy` fingerprint; no topology change |
| FEAT-479 telemetry | depends on | new seats must run under `usage_attribution` with per-run registry-bound clients |

No breaking changes to existing callers: every new parameter is optional with
today's behavior as the default.

---

## Code Context

### User-Provided Code

(none — user provided requirements prose only)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/flows/dev_flow/flow.py:85-107 (all keyword-only)
def build_dev_flow(*, dispatcher, redis_url, jira_toolkit=None, git_toolkit=None,
    wiki_toolkit=None, codereview_dispatcher=None, development_dispatcher_builder=None,
    development_pool_max: int = 4, graph_memory=None, wiki_search=None,
    skip_qa: bool = False, require_plan_approval: bool = False,
    ideation_max_rounds=None, name: str = "dev-flow", ...) -> AgentsFlow: ...
    # NOTE: no development_pool_config / development_dispatcher / development_profile / repos

# From packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py:91,105-116
class IdeationNode(...):
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 wiki_search: DevLoopWikiSearch | None = None,
                 ideation_max_rounds: int | None = None, name: str = "ideation"): ...
    # model hardcoded "claude-sonnet-4-6" at ideation.py:338 inside the dispatch profile

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:84-98
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

# From packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:282
class DevAgentPool:
    async def run_wave(self, ...): ...  # round-robin tasks over workers (:320-322),
                                        # asyncio.gather (:324-332), one retry on next worker (:348-377)

# From packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:102-220
def build_dispatcher(spec: DevAgentSpec, ...) -> tuple[DevLoopCodeDispatcher, BaseModel]: ...
# backends: claude-code | codex | gemini | nvidia | grok | zai | moonshot | google_coding | nova
# claude-code branch hardcodes model "claude-sonnet-4-6" (:144-146) — only backend with no model_env

# From packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:407-423
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding","nova"]
class DevAgentSpec(BaseModel):
    agent: DevAgentBackend; model: str = ""; count: int = 1; escalation_model: str = ""

# From packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py:84-99,246-299
class PlannerNode(...):
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher, development_pool_max: int = 4,
                 graph_memory=None, name: str = "planner"): ...
# _resolve_pool always emits DevAgentSpec(agent="claude-code") (:286, :298);
# PlannerOutput.suggested_pool set at planner.py:171 — consumed by NOTHING today

# From packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher: ...              # :85, advisory: bool = False (:100)
class CodexAdversarialReviewDispatcher: ...          # :267, model default conf.DEV_LOOP_ADVERSARIAL_MODEL (:290; conf fallback "gpt-5.5")
class ParallelPerspectiveReviewDispatcher:           # :341
    def __init__(self, *, primary, adversary, judge_dispatcher=None, judge_enabled=False): ...  # :361-373
class JudgePanelReviewDispatcher:                    # :596
    def __init__(self, *, judges=None, decision="majority", redis_url, max_concurrent=4, ...): ...  # :641-657
# JudgeSpec.agent validated ∈ {claude-code, codex, gemini}  # models/base.py:834,:857
# default_judge_panel(): claude-code/claude-sonnet-4-6 + codex/gpt-5.5 + gemini  # models/base.py:877-893

# From packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
BACKENDS: Tuple[BackendInfo, ...]                    # :131-253 (9 entries; BackendInfo :98-127)
ADVERSARIAL_BACKEND = "codex"; choices ("codex","nova")  # :54,:60; resolve_adversarial_backend :63-91
# model lists are advisory, "never a whitelist" — pickers accept free text (:22-24)

# From packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                    # :161
    @staticmethod parse_llm_string(llm) -> tuple[str, str | None]  # :171 (split on FIRST ':')
    @classmethod  create(llm, model_args=None, tool_manager=None, **kwargs) -> AbstractClient  # :193
# registry keys include: "claude-agent"/"claude-code" -> ClaudeAgentClient (:144-145, lazy),
# "codex-agent"/"openai-codex"/"codex-code" -> OpenAICodexClient (:146-148, lazy),
# "nova" -> NovaClient (:120), "bedrock-mantle"/"mantle" -> BedrockMantleClient (:125-126),
# "nvidia" (:135), "moonshot"/"kimi" (:136-137), "zai"/"z.ai" (:132-133)

# From packages/ai-parrot/src/parrot/clients/claude_agent.py:265,287-292
class ClaudeAgentClient(AbstractClient):             # full coding-agent session client
    _default_model = "claude-sonnet-4-6"             # :284
    def __init__(self, cli_path=None, cwd=None, permission_mode=None,
                 run_options: ClaudeAgentRunOptions | None = None, **kwargs): ...

# From packages/ai-parrot/src/parrot/clients/codex_agent.py:69,82-94
class OpenAICodexClient(AbstractClient):             # full coding-agent session client
    default_model = "gpt-5.1-codex"                  # :78
    def __init__(self, *, model=None, run_options=None, backend="auto",
                 codex_bin: str = "codex", **kwargs): ...

# From packages/ai-parrot/src/parrot/clients/nova/mantle.py:32,86,89-95
class BedrockMantleClient(OpenAIBaseClient):         # Bedrock OpenAI-compatible endpoint, bearer key
    _default_model = "openai.gpt-oss-120b"
    def __init__(self, api_key=None, base_url=None, region=None, **kwargs): ...
    # key: api_key → BEDROCK_MANTLE_API_KEY → AWS_NOVA_API_KEY (:96)

# From packages/ai-parrot/src/parrot/clients/nova/client.py:31,68
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    _default_model = "nova-2-lite"

# FEAT-479 telemetry integration points
# parrot/observability/context.py:126-158 — usage_attribution(run_id, seat) ctx manager
# parrot/flows/dev_loop/runner.py:545-595 — per-run EventRegistry + RunLedgerRecorder
# parrot/flows/dev_loop/dispatchers/llm.py:376-390 — client._events_registry injection

# FEAT-480 checkpoint integration points
# parrot/flows/dev_loop/checkpoint.py — compute_input_fingerprint(), TOPOLOGY_VERSION = "1",
#   _SHARED_DATA_ALLOWLIST = (bug_brief, bug_findings, research_output, planner_output,
#                             development_output, dev_brief, feature_brief, ideation_output)
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.flows.dev_flow.flow import build_dev_flow            # dev_flow/flow.py:85
from parrot.flows.dev_loop.agent_builder import build_dispatcher  # agent_builder.py:102
from parrot.flows.dev_loop.models.base import DevAgentSpec        # models/base.py:412
from parrot.clients.factory import LLMFactory                     # factory.py:161
# NOT exported from parrot.clients __init__: OpenAICodexClient, ClaudeAgentClient,
#   NovaClient, BedrockMantleClient — import from their modules or via LLMFactory.
```

#### Key Attributes & Constants
- `OpenAIModel.GPT5_6_SOL = "gpt-5.6-sol"` → enum member only (parrot/models/openai.py:22); **not wired** into any client default or catalog entry
- `MoonshotModel.KIMI_K3 = "kimi-k3"` → parrot/models/moonshot.py:22; dev-loop `moonshot` backend default (agent_builder.py:198, catalog.py:224-225); in `REASONING_EFFORT_MODELS` (models/moonshot.py:47-49)
- `PUBLIC_TO_BEDROCK["glm-5"] = "zai.glm-5"` → parrot/models/bedrock_models.py:130; `"claude-opus-5"` → :116; `"nova-2-lite"` → :150
- `NvidiaModel.KIMI_K2_6 = "moonshotai/kimi-k2.6"` → parrot/models/nvidia.py:51 (account-gated); `GLM_5_2 = "z-ai/glm-5.2"` → :74
- `conf.DEV_LOOP_ADVERSARIAL_MODEL` fallback `"gpt-5.5"` → conf.py:947; `DEV_LOOP_JUDGE_PANEL` (JSON) → conf.py:991
- `server_dev.py` defaults block → :209-231 (`development_agent` fallback `"claude-code"` :210); run parsing via `ops_server._parse_dev_agents` (:169) / `_parse_judge_panel` (:172)

### Does NOT Exist (Anti-Hallucination)
- ~~`moonshotai/kimi-k3` on NVIDIA NIM~~ — `NvidiaModel` has only `moonshotai/kimi-k2.6` (account-gated). kimi-k3 exists only on the direct Moonshot API (`moonshot` backend). The requested "NVIDIA nim: kimi-k3" seat must be re-routed (open question).
- ~~`gpt-5.5-codex` in `OpenAIModel`~~ — enum has `gpt-5.3-codex` then `gpt-5.5`; the string `gpt-5.5-codex` exists only in the catalog tuple (catalog.py:154) as a free-text picker option.
- ~~`gpt-5.6-sol` reachable via the `codex` backend or any client default~~ — enum member only; FEAT-482 plans to run it over `BedrockMantleClient`.
- ~~A research node in dev_flow~~ — deliberately absent (dev_flow/definition.py:126-127); the research seat is `IdeationNode`.
- ~~`development_pool_config` / `repos` / `development_profile` parameters on `build_dev_flow`~~ — do not exist (dev_flow/flow.py:85-107).
- ~~Any consumer of `PlannerOutput.suggested_pool`~~ — computed but read by nothing.
- ~~FEAT-482 implementation~~ — `dev_flow/research_partner.py`, `complementary_research.py`, `ResearchFindings`, `ComplementaryResearchCoordinator`, `DEV_FLOW_RESEARCH_PARTNER*` conf keys: none exist yet (spec approved, 8 tasks pending).
- ~~FEAT-484 implementation~~ — `parrot/tools/repo/` does not exist on disk (7 tasks marked in-progress, no code in this checkout).
- ~~`mcp_servers` on `ClaudeCodeDispatchProfile`~~ — planned by FEAT-482 Module 6, not present.
- ~~Per-node client/model constructor params on `IdeationNode`/`PlannerNode`/`QANode`/`SynthesisNode`/`FeedbackRouterNode`~~ — models are hardcoded literals or profile defaults.
- ~~A provider-agnostic coding-sub-agent abstraction~~ — `ClaudeAgentClient` and `OpenAICodexClient` share only `AbstractClient`; run-options types, constructor shapes, and tool bridges (in-process SDK-MCP vs. localhost HTTP MCP) all differ.
- ~~`DevFlowRunner.__init__`~~ — does not exist; the class inherits `DevLoopRunner.__init__` (dev_loop/runner.py:389-403) verbatim.

---

## Parallelism Assessment

- **Internal parallelism**: Low. The wiring tasks all converge on the same
  few files (`dev_flow/flow.py`, `factories.py`, `runner.py`,
  `dev_loop/nodes/development.py`, `server_dev.py`); the console task depends
  on the config surface existing. Only the INFO-log task and the planner
  backend-respect task are independently implementable.
- **Cross-feature independence**: **Conflicts with FEAT-482 and FEAT-484 by
  design** — FEAT-482 modifies `dev_flow/factories.py`, `nodes/ideation.py`,
  `dev_loop/catalog.py`, and `conf.py`, all of which this feature also
  touches. Hard sequencing: FEAT-484 → FEAT-482 → this feature. Also keep an
  eye on `sdd/proposals/expose-toolkits-as-local-mcp` (overlaps the
  `mcp_servers` seam).
- **Recommended isolation**: `per-spec` (one worktree, sequential tasks).
- **Rationale**: heavy file overlap between tasks and with in-flight
  features makes parallel worktrees a merge hazard for no wall-clock gain;
  the feature is mostly sequential wiring on a shared config object.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] chrome-devtools MCP (puppeteer tabs over headless Chromium for web QA) — *Owner: Jesus Lara*: out of this feature; write a separate follow-up spec (QA-node MCP integration; note FEAT-482 Module 6's `mcp_servers` profile field is the natural seam).
- [x] Development pool sizing model — *Owner: Jesus Lara*: fixed configurable pool — operator supplies an explicit client-spec list (size N derives from it); console UI defaults to Bedrock GLM + kimi-k3; no lineup baked into the flow.
- [x] Can research collapse the pool? — *Owner: Jesus Lara*: yes — a single-agent-sufficient verdict from research/planner deploys only the first configured client; otherwise the full configured pool runs.
- [x] Worktree model for concurrent sub-agents — *Owner: Jesus Lara*: one shared feature worktree, disjoint task sets, serialized commits (existing `DevAgentPool` wave model); no per-agent worktrees.
- [x] Default model pairs — *Owner: Jesus Lara*: Opus 5 + `gpt-5.6-sol` everywhere (research primary+partner, adversarial review pair); AWS Nova 2 stays selectable.
- [x] **kimi-k3 routing** — *Owner: Jesus Lara*: NVIDIA NIM is currently unusable for this account (401 Unauthorized, observed even on other NIM models such as gemma) — any unavailable NIM seat is replaced with Qwen3 coder on Amazon Bedrock (`qwen.qwen3-coder-480b-a35b-v1:0`, public alias `qwen3-coder-480b-a35b`, `bedrock_models.py:128`). Console default pool becomes Bedrock GLM + Bedrock Qwen3 coder; NIM stays in the picker (not default), kimi-k3 stays selectable via the direct `moonshot` backend.
- [x] **gpt-5.6-sol transport for review** — *Owner: Jesus Lara*: Option 1 — run the counter-reviewer over Bedrock Mantle with a read-only-by-construction adversarial dispatcher (like `NovaAdversarialReviewDispatcher`); implied by the JudgeSpec answer below (pair rides `ParallelPerspectiveReviewDispatcher`). The `codex` backend model list is NOT extended.
- [x] **GLM-on-Bedrock transport for the dev pool** — *Owner: Jesus Lara*: Option 1 — `nova` backend over Bedrock Mantle with `zai.glm-5` as the console default row; direct `zai` backend stays selectable.
- [x] **Collapse-signal carrier** — *Owner: Jesus Lara*: no new flag or typed field. The signal is the task count itself: research/planning ending with exactly one `TASK-` ⇒ Development deploys one agent, taking the first model from `PlannerOutput.suggested_pool`; otherwise the full configured pool. No FEAT-480 allowlist change.
- [x] **Research partner default state in dev_flow** — *Owner: Jesus Lara*: Option 2 — keep disabled by default (FEAT-482's shipping default); the console adds an explicit enable flag/configuration toggle (enabling defaults the partner to `gpt-5.6-sol`).
- [x] **JudgeSpec backend widening** — *Owner: Jesus Lara*: no change to `JudgeSpec` — the configurable review pair rides `ParallelPerspectiveReviewDispatcher` (`code_review.py:341`), not the judge panel.
- [ ] **Backend registry refactor (Option C)**: file as a separate follow-up brainstorm once FEAT-482/484 land? — *Owner: Jesus Lara*
