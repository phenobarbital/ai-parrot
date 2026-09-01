# Dev-flow per-seat LLM configuration (`DevFlowModelPlan`)

FEAT-486 makes every LLM-facing seat in `dev_flow` selectable from one
Pydantic object instead of a set of hardcoded Claude literals. This
document is the operator reference: what the seats are, how to configure
them, and what changes (and deliberately does not) when you do.

The feature is **backward compatible by construction**: omit `model_plan`
and `build_dev_flow` behaves exactly as it did before — no pool is
derived, no dispatcher builder is defaulted, no review pair is assembled,
and FEAT-480 checkpoint fingerprints do not move.

## The four seat groups

| Seat group | What it drives | Default | Notes |
|---|---|---|---|
| `research_primary` | `IdeationNode`'s dispatch model — the seat that writes the SDD document | `claude-opus-5` | Replaces the `claude-sonnet-4-6` literal that used to sit in `dev_flow/nodes/ideation.py` |
| `research_partner` | The FEAT-482 complementary research seat | **disabled**; `gpt` / `gpt-5.6-sol` when enabled | Pure passthrough — this plan neither builds nor validates the partner. Blocked on FEAT-482 |
| `dev_pool` | `DevelopmentNode`'s `DevAgentPool` | `[]` (single-agent path) | N specs ⇒ N sub-agents, task-parallel, one shared worktree, serialized commits |
| `review` | `QANode`'s adversarial review pair | `claude-code`/`claude-opus-5` primary + `gpt-5.6-sol` counter | Rides `ParallelPerspectiveReviewDispatcher`; the judge panel is untouched |

```python
from parrot.flows.dev_flow import build_dev_flow
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan
from parrot.flows.dev_loop.models import DevAgentSpec

flow = build_dev_flow(
    dispatcher=dispatcher,
    redis_url=redis_url,
    model_plan=DevFlowModelPlan(
        research_primary="claude-opus-5",
        dev_pool=[
            DevAgentSpec(agent="nova", model="zai.glm-5"),
            DevAgentSpec(agent="nova", model="qwen.qwen3-coder-480b-a35b-v1:0"),
        ],
    ),
)
```

## Configuration keys

Resolution order is **explicit argument > env key > built-in default**,
decided per field: a field you actually set is never overwritten by
config, while an unset one falls through.

| Key | Seat | Default |
|---|---|---|
| `DEV_FLOW_IDEATION_MODEL` | research primary | `claude-opus-5` |
| `DEV_FLOW_RESEARCH_PARTNER` | partner on/off **and** backend in one key — `""` = disabled, else `gpt` \| `nova` | `""` (disabled) |
| `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL` | partner model for the `gpt` backend | `gpt-5.6-sol` |
| `DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL` | partner model for the `nova` backend | `us.amazon.nova-2-lite-v1:0` |
| `DEV_FLOW_DEV_POOL` | dev pool (JSON array of `{agent, model, count}`) | *(unset)* |
| `DEV_FLOW_REVIEW_PRIMARY_BACKEND` | review primary backend | `claude-code` |
| `DEV_FLOW_REVIEW_PRIMARY_MODEL` | review primary model | `claude-opus-5` |
| `DEV_FLOW_REVIEW_COUNTER_MODEL` | counter-reviewer model | `gpt-5.6-sol` |
| `DEV_LOOP_MANTLE_REVIEW_MODEL` | the Mantle counter-reviewer's own model key | `gpt-5.6-sol` |

`DEV_FLOW_IDEATION_MODEL` is deliberately **shared** with FEAT-482 rather
than duplicated.

The research-partner keys are **FEAT-482's, not this feature's** (FEAT-487).
FEAT-486 briefly shipped its own `DEV_FLOW_RESEARCH_PARTNER_ENABLED` /
`_BACKEND` / `_MODEL`; those are **retired and inert** — setting them does
nothing. Two properties of FEAT-482's shape are worth knowing:

* **One key carries both enable and backend.** `DEV_FLOW_RESEARCH_PARTNER=""`
  (the default) disables the seat; any other value is the backend. The two
  cannot disagree because there is only one of them.
* **The model key is per backend.** The plan resolves the backend first and
  then that backend's model key, so a `nova` partner gets a Nova model
  rather than inheriting a `gpt-*` default.

`DevFlowModelPlan.research_partner` keeps its `enabled` / `backend` / `model`
*fields* — a plan names exactly one backend, so one `model` field is enough.
An explicit plan value still beats config.

> **Env keys only apply when a plan is supplied.** An omitted `model_plan`
> ignores `DEV_FLOW_DEV_POOL` entirely, so a stray env var can never turn
> a single-agent deployment into a pool behind your back. Passing an
> all-defaults `DevFlowModelPlan()` is the explicit opt-in to env
> resolution.

## Validation posture

**Backends are strict, models are free text** — the same rule the catalog
has always had (`dev_loop/catalog.py:22-24`). An unknown `dev_pool`
backend raises `ValueError` naming every supported backend at plan
construction time, long before any dispatch:

```
unknown dev agent backend 'bogus' — supported: claude-code, codex, gemini,
nvidia, grok, zai, moonshot, google_coding, nova
```

A typo'd *model* surfaces as a provider error on that seat at dispatch
time. That is by design: model lists are a curated starting point, never a
whitelist.

## Single-task collapse

A feature whose per-spec index holds exactly one `TASK-` deploys **one**
sub-agent, whatever the configured pool says. There is no flag and no new
typed field — the task count is the signal.

The surviving seat is the first spec of `PlannerOutput.suggested_pool`
(FEAT-486 is its first consumer), falling back to the first configured
spec. Collapse only ever shrinks; the configured pool remains the upper
bound. An unreadable index keeps the pre-existing warning and
single-agent degradation.

```
INFO  parrot.node.development  Single-task feature FEAT-486 (1 task in the
      per-spec index): collapsing the configured 2-slot pool to ONE dev
      sub-agent nova:zai.glm-5 (source: planner suggested_pool).
```

## Deployment visibility

Every pool deployment is announced at INFO, after `DevAgentPool.build()`
has expanded replicas and applied the `pool_max` cap — so the log reports
what will really run, not what was requested:

```
INFO  parrot.node.development  Deploying 2 dev sub-agent(s) for FEAT-486:
      w1=nova:zai.glm-5, w2=nova:qwen.qwen3-coder-480b-a35b-v1:0
```

An empty model prints as `<backend default>`.

## The adversarial review pair

`gpt-5.6-sol` cannot run over the Codex CLI, so the counter-review seat
uses **`MantleAdversarialReviewDispatcher`** — a read-only reviewer over
the OpenAI-compatible `bedrock-mantle` endpoint, mirroring
`NovaAdversarialReviewDispatcher`.

It is read-only in three independent structural layers:

1. `MantleAdversarialReviewProfile` has no `tools` / `allowed_commands` /
   `sandbox` field — a tool configuration cannot be *expressed*.
2. The single client call passes `use_tools=False` and no `tools` kwarg.
3. The returned verdict is rewritten with `files_modified=[]`, whatever
   the model claims.

`ParallelPerspectiveReviewDispatcher` runs it concurrently with the
write-enabled primary and merges deterministically: `passed` is the AND of
both sides (the adversary can veto), `files_modified` is always the
primary's. A Mantle outage — including a missing bearer key — degrades to
a passing verdict with a nit-level finding rather than crashing QA.

**Precedence**: an explicit `codereview_dispatcher=` argument always wins
over the plan. The plan assembles a pair only when that argument is
`None`.

`JudgeSpec` and `JudgePanelReviewDispatcher` are **not** modified by this
feature. The review pair rides the parallel dispatcher instead.

### Adversarial backend triad

`DEV_LOOP_ADVERSARIAL_BACKEND` now accepts `codex` (default, unchanged),
`nova`, and `mantle`. An operator who configures nothing sees
byte-identical behaviour.

## Auth and transports

| Seat | Transport | Credential |
|---|---|---|
| Research primary | Claude Agent SDK | Claude CLI credentials |
| Dev pool (`nova` backend) | `bedrock-mantle`, OpenAI-compatible | `BEDROCK_MANTLE_API_KEY` → `AWS_NOVA_API_KEY` |
| Counter-reviewer (`mantle`) | `bedrock-mantle`, OpenAI-compatible | `BEDROCK_MANTLE_API_KEY` → `AWS_NOVA_API_KEY` |

> **NVIDIA NIM is not usable on this account** — it returns 401
> Unauthorized even on models the account should have. It stays selectable
> in the catalog and pickers, but is never a default anywhere.

## Telemetry (FEAT-479)

Every seat lands in the per-run ledger under a distinct label:
`development.w1`, `development.w2`, … for pool workers, and the review
seats under their node id. Any newly constructed client must have its
`_events_registry` bound to the run's registry, or its usage never reaches
the ledger — `MantleAdversarialReviewDispatcher` accepts an
`event_registry_resolver` for exactly that.

## Checkpointing (FEAT-480)

`TOPOLOGY_VERSION` is **not** bumped and `_SHARED_DATA_ALLOWLIST` is
unchanged — the graph shape did not change.

Only *routing-relevant* plan fields join the `execution_policy`
fingerprint:

| In the fingerprint | Out of the fingerprint |
|---|---|
| per-spec `(agent, count)` of the pool | pool worker `model` strings |
| `review.primary.agent` | `review.counter_model` |
| `research_partner.enabled` | `research_primary` |

So swapping a *model* between resume attempts is a cache hit, while
changing the *shape* of the run (how many workers, which backends, whether
the partner runs) is a deliberate mismatch that starts fresh. The whole
`model_plan` key is omitted when no plan is supplied, keeping pre-FEAT-486
fingerprints bit-stable.

## Planner interaction

`PlannerNode._resolve_pool` no longer hardcodes
`DevAgentSpec(agent="claude-code")`. When a pool is configured, the
derived wave width is spread over the configured backends round-robin
(width 3 over 2 backends ⇒ 2 + 1). With nothing configured it still
returns a single `claude-code` spec, so plain dev_loop runs are unchanged.

## Known limitation

`model_plan` is a **build-time** input: the seats it selects are baked into
node constructors. A console or server that builds one flow at startup
cannot swap seats per run — see `examples/dev_loop/README.md`.

## See also

- `sdd/specs/refactor-dev-flow.spec.md` — the full specification
- `docs/dev_loop/nova-backend.md` — the `nova` backend's three seats
- `docs/dev_loop/telemetry-accounting.md` — the FEAT-479 run ledger
