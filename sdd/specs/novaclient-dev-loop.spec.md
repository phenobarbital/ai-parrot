---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report

**Feature ID**: FEAT-405
**Date**: 2026-08-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/novaclient-dev-loop.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-loop flow (`parrot/flows/dev_loop/`) materialises every agent seat —
development pool workers, QA judges, the adversarial reviewer, the planner —
through `build_dispatcher` (`agent_builder.py:100`), which today knows exactly
eight backends: `claude-code`, `codex`, `gemini`, `nvidia`, `grok`, `zai`,
`moonshot`, `google_coding` (`models/base.py:383`). Every one of them reaches
its model over a **vendor-direct** path: a CLI on `$PATH` (Claude Code, Codex,
Gemini) or a vendor API key (Nvidia, Z.ai, Moonshot, xAI).

That creates three concrete pain points:

1. **No AWS-governed path.** Teams that consume LLMs through AWS Bedrock — one
   IAM boundary, one bill, one data-residency story, no per-vendor API keys —
   cannot run the dev-loop at all. `NovaClient` (`clients/nova/client.py:30`)
   already exists and is already registered in `LLMFactory`
   (`clients/factory.py:96`), but **nothing in `dev_loop/` references it**
   (verified: zero `nova` matches across the package).

2. **Cost concentration on the wrong seats.** The write-the-code seat is the
   highest-volume token consumer in the loop, yet it defaults to the same
   frontier-tier models used for review. Bedrock now carries agent-native,
   token-efficient models (MiniMax M2.5, GLM-5, Kimi K2.5) that suit mechanical
   code production, while reserving Claude Opus 5 for the seat where judgement
   pays — adversarial review. There is no way to express that split today.

3. **Per-agent usage is invisible in the dev-loop, even though the platform
   now measures it.** FEAT-397 (`sdd/specs/tokens-observability.spec.md`)
   solved per-round accumulation at the **client** layer. The dev-loop consumes
   none of it: `run_bundle.py` renders a per-node table (`run_bundle.py:61-67`)
   fed solely by `ClaudeCodeDispatcher._extract_result_usage`
   (`dispatchers/claude.py:625`). Every other backend reports `None`, for two
   distinct reasons:
   - **Coverage**: FEAT-397's non-goals name `BedrockClient` a follow-up, so
     the Bedrock/Nova client does not accumulate rounds yet (→ FEAT-404,
     out of scope here).
   - **Bypass**: `LLMCodeDispatcher` never calls `ask()`. It drives
     `client._chat_completion(...)` in its own loop (`dispatchers/llm.py:190`),
     so FEAT-397's in-`ask()` accumulation never reaches the dev-loop dispatch
     path — for *any* backend.

### Goals

- Add a single **`nova`** dev-loop backend reaching Bedrock-hosted models
  through one AWS credential, wired to the seats where each model earns its
  keep: MiniMax M2.5 for development, Claude Opus 5 for adversarial review,
  Claude Haiku 4.5 for mechanical PR text.
- Make the adversarial seat **selectable** over `{codex, nova}` instead of a
  codex-only constant, with `codex` remaining the default.
- Correct Bedrock model-ID translation for the 2026 model generation
  (prefixes, vendor namespaces, suffix-less Anthropic ids).
- Close the dev-loop's usage-telemetry gap by emitting `ClientRoundEvent` from
  `LLMCodeDispatcher`'s loop, and render a per-agent usage report as
  `usage.json` + markdown + a standalone HTML artifact.
- Ship as a **pure addition**: an operator who selects nothing sees no change.

### Non-Goals (explicitly out of scope)

- **Per-round usage accumulation inside any dev-loop dispatcher.** Accumulation
  is FEAT-397's client-layer responsibility; this feature emits per-round
  events and *reads* totals. A summing loop in a dispatcher is forbidden.
- **FEAT-397 coverage for `NovaClient`/`BedrockConverseBase`.** Shipping
  separately as **FEAT-404** (`sdd/proposals/bedrock-per-round-token.proposal.md`).
  This feature must degrade cleanly without it.
- **A pluggable research seat.** `ResearchNode` stays hard-wired to
  `ClaudeCodeDispatcher` + `/sdd-spec` + `/sdd-task`. A Bedrock API seat cannot
  invoke slash commands, so the generalization would ship an option that could
  not do the job — see brainstorm Q3/[R7].

  > **Narrowed by FEAT-482 (2026-08-31)** — not reversed. This non-goal rules out
  > *replacing* the research seat with a Bedrock seat, and that reasoning still
  > holds: only the Claude seat can run slash commands, author the SDD document,
  > and create the worktree. FEAT-482 (`devflow-complementary-research`) instead
  > adds a Bedrock seat *beside* it as a read-only, advisory **collaborator** that
  > contributes findings and never writes under `sdd/**`. Contribute-to, not
  > replace. See `sdd/specs/devflow-complementary-research.spec.md` §1.
- **A Converse↔OpenAI tool-call adapter on `BedrockConverseBase`.** Rejected in
  brainstorm Option B: Bedrock exposes no Chat Completions for Anthropic
  models, so a tool-using Claude worker is served by the existing `claude-code`
  backend instead.
- **Dollar-cost estimation.** Tokens and rounds only; no price table.
- **Changing any existing default.** `claude-code` remains the development
  default; `codex` remains the adversarial default.

---

## 2. Architectural Design

### Overview

**Transport-split (brainstorm Option A).** The three Nova seats have different
interaction shapes, and each gets the API AWS already provides for it rather
than one forced-uniform mechanism:

| Seat | Model (default) | Shape | Transport |
|---|---|---|---|
| Adversarial review | `us.anthropic.claude-opus-5` | no tools, one call | Converse — `BedrockConverseBase.ask()` |
| Mechanical / PR text | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | no tools, one call | Converse — `ask()` |
| Development worker | `minimax.minimax-m2.5` | tool loop | `bedrock-mantle` OpenAI-compatible endpoint → `LLMCodeDispatcher` |

The decisive fact is that **the configured seats need no Converse tool-call
adapter**: the two review seats are single `ask()` calls (`ask()` already
defaults `use_tools` off), and the only tool-using seat is MiniMax, which AWS
serves over the OpenAI-compatible `bedrock-mantle` endpoint
(`https://bedrock-mantle.{region}.api.aws/v1`) that `LLMCodeDispatcher`'s loop
already speaks. AWS explicitly recommends `bedrock-mantle`.

The consequence to accept deliberately: **a Claude model cannot hold the
`nova` development seat**, because Bedrock offers no Chat Completions for the
Anthropic family. That need is served by the existing `claude-code` backend.

### Component Diagram

```
                        ┌──────────────────────────────────────┐
build_dispatcher ──────→│ spec.agent == "nova"                 │
(agent_builder.py:100)  └──────────────┬───────────────────────┘
                                       │
                    ┌──────────────────┴───────────────────┐
                    ▼                                      ▼
        NovaCodeDispatcher                    NovaAdversarialReviewDispatcher
        (dispatchers/nova.py)                 (dispatchers/nova.py)
        extends LLMCodeDispatcher             extends AbstractCodeReviewDispatcher
                    │                          advisory = True, NO tools
                    │                                      │
                    ▼                                      ▼
        bedrock-mantle (OpenAI shape)          NovaClient.ask()  (Converse)
        minimax.minimax-m2.5                   us.anthropic.claude-opus-5
                    │                                      │
                    └──────────────┬───────────────────────┘
                                   ▼
                    translate()  (models/bedrock_models.py)
                    REQUIRES_REGION_PREFIX decides prefixing
                                   │
                                   ▼
                             AWS Bedrock

  ── usage path (all backends) ──────────────────────────────────────
  LLMCodeDispatcher._dispatch_loop ──→ client._emit_round_event(tc, …)
        (per turn, no summing)              (clients/base.py:488)
                                                   │
                                                   ▼
                                            ClientRoundEvent
                                                   │
                                                   ▼
                              UsageReport ──→ usage.json + markdown + HTML
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LLMCodeDispatcher` (`dispatchers/llm.py:39`) | extends + modifies | `NovaCodeDispatcher` subclasses it; its loop gains round-event emission for **all** backends |
| `AbstractCodeReviewDispatcher` (`code_review.py:85`) | extends | `NovaAdversarialReviewDispatcher`, registered `"nova-adversarial"` |
| `CodeReviewDispatcherFactory` (`code_review.py:164`) | uses | `@register("nova-adversarial")` decorator |
| `BedrockConverseBase.ask()` (`clients/bedrock.py:578`) | uses | no-tools review + mechanical seats |
| `NovaClient` (`clients/nova/client.py:30`) | uses (unchanged) | `region_prefix="us"` default **stays** |
| `DevAgentBackend` (`models/base.py:383`) | modifies | Literal gains `"nova"` |
| `build_dispatcher` (`agent_builder.py:100-210`) | extends | new `nova` branch before the `raise ValueError` at :210 |
| `catalog.ADVERSARIAL_BACKEND` (`catalog.py:48`) | modifies | constant → config-resolved choice over `{codex, nova}` |
| `AbstractClient._emit_round_event` (`clients/base.py:488`) | uses | called from the dispatcher loop; no extraction needed |
| `run_bundle.py` (`:48`, `:120`, `:365`) | extends | per-agent section rendered from `UsageReport` |
| `translate()` / `PUBLIC_TO_BEDROCK` (`models/bedrock_models.py:38`) | modifies | prefixes, vendor namespaces, new ids |
| `nodes/feature_handoff.py:511`, `nodes/deployment_handoff.py:479` | extends | optional Haiku summary section |
| `nodes/research.py` | **untouched** | research seat stays Claude Code (Non-Goal) |
| FEAT-404 (Bedrock per-round usage) | **depends on (soft)** | absent → rounds/tokens render `—`; present → no rework |

### Data Models

```python
# parrot/flows/dev_loop/models/nova.py  (NEW)

class NovaCodeDispatchProfile(LLMCodeDispatchProfile):
    """Development-seat profile; routes via the bedrock-mantle endpoint."""
    model: str = Field(default="minimax.minimax-m2.5")
    llm: str = "nova:minimax.minimax-m2.5"
    max_tokens: int = Field(default=4096, ge=256, le=32768)  # clamped per-model at dispatch

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "NovaCodeDispatchProfile": ...
    # mirrors MoonshotCodeDispatchProfile._sync_llm_with_model (models/moonshot.py:43)


class NovaAdversarialReviewProfile(BaseModel):
    """Read-only by construction: NO tools are ever passed to the model."""
    model: str = Field(default="us.anthropic.claude-opus-5")
    review_scope: Literal["uncommitted", "base", "commit"] = "uncommitted"
    review_base: str = ""
    review_commit: str = ""
    max_tokens: int = Field(default=8192, ge=256, le=131072)
    max_diff_chars: int = Field(default=200_000, ge=1000)


class NovaMechanicalProfile(BaseModel):
    """Short, no-tools text generation (PR summary section)."""
    model: str = Field(default="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    timeout_seconds: int = Field(default=60, ge=5, le=600)


# parrot/flows/dev_loop/usage_report.py  (NEW)

class AgentUsage(BaseModel):
    """One agent seat's usage. None (never 0) when unreported."""
    seat: str                      # "dev-agent-1", "adversarial", "qa-judge-2", …
    node_id: str
    backend: str                   # "nova", "claude-code", …
    model: str
    rounds: Optional[int] = None   # model calls in the tool loop
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    duration_seconds: Optional[float] = None


class UsageReport(BaseModel):
    """Single source of truth for usage.json, markdown and HTML."""
    run_id: str
    generated_at: float
    agents: List[AgentUsage] = Field(default_factory=list)
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None
    total_rounds: Optional[int] = None


# parrot/models/bedrock_models.py  (NEW constant)

REQUIRES_REGION_PREFIX: dict[str, str] = {
    # public/base id -> default prefix when the caller supplies none.
    # Models ABSENT from this map are NEVER prefixed.
}
```

### New Public Interfaces

```python
# parrot/flows/dev_loop/dispatchers/nova.py  (NEW)

class NovaCodeDispatcher(LLMCodeDispatcher):
    """Dev-seat loop over the bedrock-mantle OpenAI-compatible endpoint."""
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...
    def _completion_args(self, profile: NovaCodeDispatchProfile,
                         tools: List[Dict[str, Any]]) -> Dict[str, Any]: ...
    async def _chat_completion(self, *, client: Any, model: str,
                               messages: List[Dict[str, Any]],
                               args: Dict[str, Any]) -> Any: ...


@CodeReviewDispatcherFactory.register("nova-adversarial")
class NovaAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):
    agent_name = "nova-adversarial"
    advisory = True
    def build_review_profile(self) -> NovaAdversarialReviewProfile: ...
    async def review(self, *, brief: BaseModel, run_id: str, node_id: str,
                     cwd: str, session_host: Optional[SessionHost] = None,
                     round: str = "") -> CodeReviewVerdict: ...


# parrot/flows/dev_loop/usage_report.py  (NEW)
def build_usage_report(snapshot: Snapshot, run_id: str) -> UsageReport: ...
def render_usage_markdown(report: UsageReport) -> str: ...
def render_usage_html(report: UsageReport) -> str: ...   # self-contained, no CDN
```

---

## 3. Module Breakdown

### Module 1: Bedrock model-ID translation (2026 generation)
- **Path**: `parrot/models/bedrock_models.py`
- **Responsibility**: Add `au.` and `global.` to `_REGION_PREFIXES` (line 27);
  teach the pass-through detector the `minimax.`, `zai.`, `moonshotai.` vendor
  namespaces; add verified map entries (note Opus 5 / Fable 5 carry **no**
  `-vN:0` suffix, breaking the `anthropic.<id>-vN:0` convention at line 38);
  introduce `REQUIRES_REGION_PREFIX` as the allowlist that decides prefixing.
  Models absent from the map are never prefixed, whatever `region_prefix` is.
  Warn (do not silently drop) when an explicit prefix is passed for an
  unmapped model.
- **Depends on**: nothing
- **Must NOT**: change `NovaClient.__init__`'s `region_prefix="us"` default.

### Module 2: Nova dispatch profiles
- **Path**: `parrot/flows/dev_loop/models/nova.py` (NEW)
- **Responsibility**: `NovaCodeDispatchProfile`, `NovaAdversarialReviewProfile`,
  `NovaMechanicalProfile`; export from `models/__init__.py`.
- **Depends on**: Module 1

### Module 3: Nova dispatchers
- **Path**: `parrot/flows/dev_loop/dispatchers/nova.py` (NEW)
- **Responsibility**: `NovaCodeDispatcher` (two-hook override of
  `LLMCodeDispatcher`, mirroring `dispatchers/moonshot.py:47,82`) and
  `NovaAdversarialReviewDispatcher` (no tools; post-dispatch
  `files_modified = []` hardening mirroring `code_review.py:337`). Export from
  `dispatchers/__init__.py`.
- **Depends on**: Module 2

### Module 4: Per-model output-token clamping
- **Path**: `parrot/flows/dev_loop/dispatchers/nova.py` + `models/nova.py`
- **Responsibility**: A `MODEL_MAX_OUTPUT_TOKENS` map (MiniMax 8192, Kimi
  16384, GLM-5 131072, Opus 5 131072). At dispatch, clamp the effective
  `max_tokens` to the model's ceiling and log a warning naming model,
  requested and effective values. **Clamp — never raise** (Q5 resolved).
- **Depends on**: Module 2

### Module 5: Backend registration & wiring
- **Path**: `models/base.py`, `agent_builder.py`, `catalog.py`, `conf.py`
- **Responsibility**: `"nova"` into the `DevAgentBackend` Literal
  (`models/base.py:383`; also referenced at :847); a `nova` branch in
  `build_dispatcher` before `raise ValueError` (`agent_builder.py:210`); a
  `BackendInfo` row in `catalog.BACKENDS` (`catalog.py:88`); turn
  `ADVERSARIAL_BACKEND` (`catalog.py:48`) into a config-resolved choice over
  `{codex, nova}` defaulting to `codex`, updating both use sites
  (`catalog.py:294,296`); new `DEV_LOOP_NOVA_*` config keys.
- **Depends on**: Module 3

### Module 6: Round-event emission from the dispatcher loop
- **Path**: `parrot/flows/dev_loop/dispatchers/llm.py`
- **Responsibility**: In `_dispatch_loop` (`:172`), obtain
  `tc = client._emit_before_call(...)` before the turn loop (`:190`), call
  `client._emit_round_event(tc, …, round_number=turn_index + 1, usage=…,
  duration_ms=…)` after each turn, and `await client._emit_after_call(tc, …)`
  at the end. Extract each turn's `CompletionUsage` from the
  `_chat_completion` response. **NO accumulation** — one event per round;
  summing belongs downstream. Covers **all** backends (nvidia, zai, moonshot,
  grok, nova) from day one.
- **Depends on**: nothing (independent of Modules 1–5)

### Module 7: UsageReport model + renderers
- **Path**: `parrot/flows/dev_loop/usage_report.py` (NEW) + `run_bundle.py`
- **Responsibility**: `UsageReport`/`AgentUsage`; `build_usage_report()` from
  the run snapshot; `usage.json`; `render_usage_markdown()` folded into the
  existing bundle (reusing `_format_tokens`, `run_bundle.py:365`);
  `render_usage_html()` producing a self-contained page (no external assets).
  Unreported values render `—`, never `0` (`run_bundle.py:120-123` rule).
- **Depends on**: Module 6

### Module 8: Haiku PR enrichment
- **Path**: `nodes/feature_handoff.py`, `nodes/deployment_handoff.py`
- **Responsibility**: Keep the deterministic `_build_body`
  (`feature_handoff.py:511`, `deployment_handoff.py:479`) authoritative; when
  the mechanical seat is configured, splice in one LLM-written "Summary of
  changes" section. Any failure, timeout or absent config falls back to
  today's exact output.
- **Depends on**: Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_translate_adds_au_and_global_prefixes` | 1 | `au.`/`global.` recognised as pass-through prefixes |
| `test_translate_passthrough_vendor_namespaces` | 1 | `minimax.`/`zai.`/`moonshotai.` ids returned verbatim, no warning |
| `test_opus5_has_no_version_suffix` | 1 | `anthropic.claude-opus-5` maps without `-vN:0` |
| `test_unmapped_model_never_prefixed` | 1 | `minimax.minimax-m2.5` + `region_prefix="us"` → `minimax.minimax-m2.5` (**the day-one bug**) |
| `test_mapped_model_uses_caller_prefix` | 1 | explicit prefix wins over the map default |
| `test_mapped_model_falls_back_to_map_default` | 1 | no caller prefix → map's declared default |
| `test_explicit_prefix_on_unmapped_model_warns` | 1 | warning emitted, prefix not applied |
| `test_nova_profile_syncs_llm_with_model` | 2 | `model` → `llm` derivation unless `llm` set explicitly |
| `test_adversarial_profile_has_no_tools` | 2 | profile exposes no tool configuration |
| `test_nova_dispatcher_routes_to_mantle` | 3 | completion args target the `bedrock-mantle` base URL |
| `test_adversarial_forces_files_modified_empty` | 3 | verdict returns `files_modified == []` regardless of dispatch |
| `test_adversarial_tags_findings_with_source` | 3 | findings carry `source="nova-adversarial"` |
| `test_clamp_minimax_to_8192` | 4 | `max_tokens=32768` → effective 8192 + warning |
| `test_clamp_kimi_to_16384` | 4 | `max_tokens=32768` → effective 16384 + warning |
| `test_no_clamp_when_under_ceiling` | 4 | value below the cap passes through unchanged, no warning |
| `test_build_dispatcher_nova_branch` | 5 | returns `(NovaCodeDispatcher, NovaCodeDispatchProfile)` |
| `test_adversarial_backend_defaults_to_codex` | 5 | unset config → `codex` (**no behaviour change**) |
| `test_adversarial_backend_selects_nova` | 5 | config `nova` → `nova-adversarial` dispatcher |
| `test_catalog_lists_nova_backend` | 5 | `catalog_payload()` includes `nova` with its roles |
| `test_round_event_emitted_per_turn` | 6 | a 3-turn dispatch emits exactly 3 `ClientRoundEvent`s with `round_number` 1..3 |
| `test_dispatcher_does_not_accumulate` | 6 | each event carries only its own round's usage |
| `test_round_events_for_non_nova_backend` | 6 | nvidia/zai path emits events too ([R8]) |
| `test_no_events_when_no_subscribers` | 6 | `has_subscribers` short-circuit — zero overhead |
| `test_usage_report_renders_dash_for_none` | 7 | unreported values render `—`, never `0` |
| `test_usage_report_json_roundtrip` | 7 | `usage.json` validates back into `UsageReport` |
| `test_usage_html_is_self_contained` | 7 | no external `src`/`href` in the rendered HTML |
| `test_pr_body_falls_back_on_llm_failure` | 8 | Haiku error → byte-identical to today's template output |

### Integration Tests

| Test | Description |
|---|---|
| `test_nova_dev_seat_end_to_end` | Pool spec `{"agent":"nova"}` → dispatcher built, loop runs against a mocked mantle endpoint, `DevelopmentOutput` validates |
| `test_nova_adversarial_gate_end_to_end` | QA dispatches the nova adversarial reviewer; verdict is advisory and `files_modified == []` |
| `test_usage_report_written_at_run_end` | A completed run emits `usage.json` + markdown section + `usage.html`, agents attributed to seats |
| `test_defaults_unchanged_without_nova` | A run configuring nothing behaves byte-identically to pre-feature (regression guard for [R3]) |

### Test Data / Fixtures

```python
@pytest.fixture
def nova_pool_spec():
    return DevAgentPoolConfig(agents=[DevAgentSpec(agent="nova",
                                                   model="minimax.minimax-m2.5",
                                                   count=1)])

@pytest.fixture
def fake_mantle_client():
    """OpenAI-shaped stub exposing _chat_completion + the _emit_* trio."""

@pytest.fixture
def round_event_collector():
    """Subscribes to ClientRoundEvent on the global registry and records them."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/flows/dev_loop/ -v`)
- [ ] All integration tests pass
- [ ] `ruff check` and `mypy` clean on all changed files
- [ ] **`translate("minimax.minimax-m2.5", region_prefix="us")` returns
      `minimax.minimax-m2.5`** — the prefix-leak bug is unreachable
- [ ] `au.` and `global.` are recognised prefixes; `minimax.`/`zai.`/
      `moonshotai.` are recognised vendor namespaces
- [ ] `NovaClient.__init__` still declares `region_prefix: Optional[str] = "us"`
      — **unchanged**, no caller migration
- [ ] `DevAgentBackend` contains `"nova"`; `build_dispatcher` returns a
      `(NovaCodeDispatcher, NovaCodeDispatchProfile)` pair for it
- [ ] The adversarial reviewer is selectable over `{codex, nova}` and
      **defaults to `codex`** when unconfigured
- [ ] The Nova adversarial reviewer passes **no tools** to the model, and its
      verdict always reports `files_modified == []`
- [ ] `max_tokens` above a model's ceiling is **clamped with a warning**, never
      rejected (MiniMax → 8192, Kimi → 16384)
- [ ] `LLMCodeDispatcher` emits one `ClientRoundEvent` per turn for **every**
      backend, and contains **no** token-summing logic
- [ ] `usage.json`, the markdown section, and `usage.html` are all rendered
      from one `UsageReport`; unreported values render `—`, never `0`
- [ ] `usage.html` is self-contained (no external stylesheet, script, or image)
- [ ] `nodes/research.py` is **unmodified** (diff is empty for that file)
- [ ] PR body generation falls back to the exact current template on any LLM
      failure, timeout, or missing config
- [ ] A run that configures no Nova settings behaves identically to pre-feature
- [ ] Docs updated: `docs/` note on the `nova` backend + `DEV_LOOP_NOVA_*` keys

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below was re-verified against `dev` at commit `2aa9366bf`
> on 2026-08-03 (after the `dev_loop` per-client split landed as `a50567f39`).

### Verified Imports

```python
# Confirmed to resolve:
from parrot.clients.nova import NovaClient                  # clients/nova/__init__.py
from parrot.clients.factory import LLMFactory               # "nova": _lazy_nova at factory.py:96
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.dispatchers._shared import (
    DispatchExecutionError, DispatchOutputValidationError, DevLoopCodeDispatcher, T,
)
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile
from parrot.flows.dev_loop.models import DevAgentBackend, DevAgentSpec   # models/__init__.py:29,93
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher, CodeReviewDispatcherFactory,
)
from parrot.models.bedrock_models import PUBLIC_TO_BEDROCK, translate
```

### Existing Class Signatures

```python
# parrot/clients/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):   # line 30
    client_type: str = "nova"                      # line 62
    _default_model: str = "nova-2-lite"            # line 64
    def __init__(self, aws_id=None, region=None, profile=None,
                 region_prefix: Optional[str] = "us",              # line 72 — DO NOT CHANGE
                 guardrail_id=None, guardrail_version=None,
                 voice_id="matthew", aws_access_key=None,
                 aws_secret_key=None, aws_session_token=None, **kwargs): ...  # line 67

# parrot/clients/bedrock.py
class BedrockConverseBase:
    def _prepare_tools(self, filter_names=None) -> List[Dict[str, Any]]: ...  # line 413
    async def ask(self, ..., tools=None, use_tools=None, ...): ...            # line 578

# parrot/clients/base.py  — the FEAT-397 emitter trio (Module 6)
class AbstractClient(EventEmitterMixin, ABC):
    def _emit_before_call(self, *, client_name: str, model: str,
                          temperature=None, system_prompt=None,
                          has_tools: bool = False,
                          parent_trace=None) -> "TraceContext": ...    # line 431
    def _emit_round_event(self, tc: "TraceContext", *, client_name: str,
                          model: str, round_number: int,
                          usage: "Optional[CompletionUsage]",
                          raw_usage: "Optional[dict]",
                          tool_calls: "Sequence[str]",
                          duration_ms: float) -> None: ...             # line 488
    async def _emit_after_call(self, tc: "TraceContext", *, client_name: str,
                               model: str, duration_ms: float,
                               input_tokens=None, output_tokens=None,
                               finish_reason=None) -> None: ...        # line 564

# parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                                               # line 39
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd, session_host=None): ...           # line 65
    async def _dispatch_loop(self, *, brief, profile, output_model,
                             run_id, node_id, stream_key, cwd): ...    # line 172
        # line 190: for turn_index in range(profile.max_turns):  ← Module 6 hooks here
    def _completion_args(self, profile, tools) -> Dict[str, Any]: ...  # line 347
    async def _chat_completion(self, *, client, model, messages, args): ...  # line 369

# parrot/flows/dev_loop/dispatchers/_shared.py
T = TypeVar("T", bound=BaseModel)                                      # line 21
class DispatchExecutionError(Exception): ...                           # line 82
class DispatchOutputValidationError(Exception): ...                    # line 91
class DevLoopCodeDispatcher(Protocol):                                 # line 105
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd, session_host=None) -> T: ...      # line 108

# parrot/flows/dev_loop/models/llm.py
class LLMCodeDispatchProfile(BaseModel):                               # line 10
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"               # line 19
    max_turns: int = Field(default=24, ge=1, le=100)                   # line 23
    max_tokens: int = Field(default=4096, ge=256, le=32768)            # line 24

# parrot/flows/dev_loop/models/moonshot.py — THE PATTERN TO COPY
class MoonshotCodeDispatchProfile(LLMCodeDispatchProfile):             # line 10
    @model_validator(mode="after")
    def _sync_llm_with_model(self): ...                                # line 43

# parrot/flows/dev_loop/dispatchers/moonshot.py — THE TWO-HOOK OVERRIDE SHAPE
class MoonshotCodeDispatcher(LLMCodeDispatcher):                       # line 18
    def _completion_args(self, profile, tools) -> Dict[str, Any]: ...  # line 47
    async def _chat_completion(self, *, client, model, messages, args): ...  # line 82
    # ctor injects client_factory=lambda model, **kw: LLMFactory.create(model, **kw)  # line 44

# parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):                               # line 85
    agent_name: str                                                    # line 99
    advisory: bool = False                                             # line 100
    async def review(self, *, brief, run_id, node_id, cwd,
                     session_host=None, round="") -> CodeReviewVerdict: ...  # line 106
    @abstractmethod
    def build_review_profile(self) -> BaseModel: ...                   # line 159
class CodeReviewDispatcherFactory:                                     # line 164
    @classmethod
    def register(cls, name: str): ...                                  # line 170
@CodeReviewDispatcherFactory.register("codex-adversarial")             # line 266 — MIRROR THIS
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):  # line 267
    agent_name = "codex-adversarial"; advisory = True                  # lines 277-278
    # line 337: verdict.model_copy(update={"files_modified": [], "findings": tagged})

# parrot/flows/dev_loop/run_bundle.py
class NodeReport(_Frozen):                                             # line 48
    input_tokens: Optional[int] = None                                 # line 61
    num_turns: Optional[int] = None                                    # line 66
class RunTotals(_Frozen): ...   # line 120 — "must not render fake zeros"
class RunBundle(_Frozen): ...   # line 137
def _format_tokens(input_tokens, output_tokens) -> str: ...            # line 365

# parrot/models/responses.py
def total_usage(self) -> CompletionUsage: ...                          # line 281

# parrot/core/events/lifecycle/events/client.py
class ClientRoundEvent(LifecycleEvent): ...                            # line 177
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `NovaCodeDispatcher` | `LLMCodeDispatcher._completion_args` / `_chat_completion` | override | `dispatchers/llm.py:347,369` |
| `NovaAdversarialReviewDispatcher` | `CodeReviewDispatcherFactory.register` | decorator | `code_review.py:170` |
| `NovaAdversarialReviewDispatcher` | `NovaClient.ask()` | method call | `clients/bedrock.py:578` |
| Module 6 hooks | `AbstractClient._emit_round_event` | method call | `clients/base.py:488` |
| Module 6 hooks | `AbstractClient._emit_before_call` | method call | `clients/base.py:431` |
| `build_dispatcher` nova branch | `raise ValueError` fallthrough | insert before | `agent_builder.py:210` |
| `UsageReport` | `_format_tokens` | function call | `run_bundle.py:365` |

### Key Attributes & Constants

- `DevAgentBackend` → `Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding"]` (`models/base.py:383`) — **no `nova`**; also referenced at :847
- `JUDGE_BACKENDS` → `("claude-code","codex","gemini","google_coding")` (`catalog.py:42`)
- `ADVERSARIAL_BACKEND` → `"codex"` (`catalog.py:48`; consumed at :294, :296)
- `PRIMARY_REVIEW_BACKENDS` (`catalog.py:52`); `BACKENDS` tuple (`catalog.py:88`)
- `_REGION_PREFIXES` → `("us.", "eu.", "apac.")` (`models/bedrock_models.py:27`) — missing the real `au.` and `global.`
- `PUBLIC_TO_BEDROCK` (`models/bedrock_models.py:38`); "Bedrock IDs TBD" comment at :65
- `conf.DEV_LOOP_ADVERSARIAL_MODEL` → fallback `"gpt-5.5"` (`conf.py:1048`)
- `DispatchState.input_tokens` (`session_state.py:202`); usage absorption at `session_state.py:1259-1278`
- `ZaiClient.base_url` configurable with `ZAI_BASE_URL` override (`clients/zai.py:35,45`) — precedent for a `bedrock-mantle` base URL
- `build_dispatcher` branches: claude-code 138, codex 145, gemini 152, nvidia 159, grok 175, zai 182, moonshot 193, google_coding 203, `raise ValueError` 210
- Tests live in `packages/ai-parrot/tests/flows/dev_loop/` (`test_dispatcher.py`, `test_dispatch_telemetry.py`, `test_codex_dispatcher.py`, `test_gemini_dispatcher.py`)

### Verified AWS Facts (from the Bedrock model cards, 2026-08-03)

| Model | Bedrock ID | Geo IDs | Global ID | Context | Max output | Converse | Chat Completions |
|---|---|---|---|---|---|---|---|
| Claude Opus 5 | `anthropic.claude-opus-5` | `us.` / `eu.` / `au.` | `global.anthropic.claude-opus-5` | 1M | 128K | ✅ | ❌ |
| Claude Fable 5 | `anthropic.claude-fable-5` | — | `global.anthropic.claude-fable-5` | — | — | — | ❌ |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` | `us.` | — | — | — | ✅ | ❌ |
| MiniMax M2.5 | `minimax.minimax-m2.5` | **Not supported** | **Not supported** | 196K | **8K** | ✅ | ✅ |
| Kimi K2.5 | `moonshotai.kimi-k2.5` | **Not supported** | **Not supported** | 256K | **16K** | ✅ | ✅ |
| Z.ai GLM-5 | `zai.glm-5` | **Not supported** | **Not supported** | 200K | 128K | ✅ | ✅ |

- `bedrock-mantle` OpenAI-compatible endpoint: `https://bedrock-mantle.{region}.api.aws/v1`,
  Bedrock API key as bearer. **Anthropic models are served at
  `/anthropic/v1/messages` instead — they have no Chat Completions.**
- Claude Opus 5 has **no in-region access** in us-west-2 / us-east-2 — a geo or
  global prefix is required there. Prompt caching: 512 min tokens, 4
  checkpoints, 5-minute / 1-hour TTL.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.flows.dev_loop.dispatchers.nova`~~ / ~~`NovaCodeDispatcher`~~ — created by this feature
- ~~`parrot.flows.dev_loop.models.nova`~~ / ~~`NovaCodeDispatchProfile`~~ — created by this feature
- ~~`parrot.flows.dev_loop.usage_report`~~ — no usage-report module exists
- ~~`REQUIRES_REGION_PREFIX`~~ / ~~`MODEL_MAX_OUTPUT_TOKENS`~~ — introduced by Modules 1 and 4
- ~~`"nova"` in `DevAgentBackend`~~ — the Literal has exactly 8 values, none of them `nova`
- ~~`BedrockConverseBase._chat_completion(...)`~~ — **does not exist**. The class exposes `ask()`/`ask_stream()`/`invoke()`/`resume()` in Converse shape. `LLMCodeDispatcher._chat_completion` (`llm.py:369`) would raise `DispatchExecutionError("… does not expose chat completion")` against it. This is why the dev seat uses `bedrock-mantle`, not `NovaClient`.
- ~~`PUBLIC_TO_BEDROCK["claude-opus-5"]`~~ / ~~`["claude-fable-5"]`~~ / ~~`["minimax-m2.5"]`~~ / ~~`["kimi-k2.5"]`~~ — absent; `bedrock_models.py:65` says "Bedrock IDs TBD"
- ~~Round accumulation in `BedrockConverseBase`~~ — not implemented; **FEAT-404**, out of scope
- ~~Usage collection in `LLMCodeDispatcher`~~ — its loop reads no tokens and calls no `_emit_round_event`. **Do NOT add a summing loop** — emit per-round events only
- ~~An LLM anywhere in the PR-creation path~~ — `_build_title`/`_build_body` are pure string templates (`feature_handoff.py:507,511`; `deployment_handoff.py:474,479`)
- ~~`ResearchNode` accepting a generic dispatcher~~ — typed `dispatcher: ClaudeCodeDispatcher` (`nodes/research.py:142`), hardcodes `subagent="sdd-research"` (`:284`). **Leave it that way** — out of scope
- ~~A `nova` entry in `catalog.BACKENDS`~~ — the tuple at `catalog.py:88` has no Bedrock backend
- ~~Chat Completions for Anthropic models on Bedrock~~ — not supported; do not attempt
- ~~Geo/global inference profiles for MiniMax, Kimi or GLM-5~~ — all three cards say "Not supported"
- ~~"Claude Opus 5.8"~~ — no such model card; dropped

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Copy `moonshot.py`, not `claude.py`.** `MoonshotCodeDispatchProfile`
  (`models/moonshot.py:10`) and `MoonshotCodeDispatcher`
  (`dispatchers/moonshot.py:18`) are the closest precedent: a profile
  subclassing `LLMCodeDispatchProfile` plus a dispatcher overriding exactly
  two hooks.
- **Mirror `CodexAdversarialReviewDispatcher`** (`code_review.py:266-337`) for
  the adversarial seat, including `advisory = True` and the post-dispatch
  `files_modified = []` hardening.
- `async`/`await` throughout; `self.logger`, never `print`.
- Pydantic v2 models with Google-style docstrings and strict type hints.
- Config via `conf.config.get` with fallbacks, following the existing
  `DEV_LOOP_*` key convention.

### Known Risks / Gotchas

- **Prefix leak (highest day-one risk).** `us.minimax.minimax-m2.5` is invalid.
  Mitigated by `REQUIRES_REGION_PREFIX` as an allowlist and pinned by
  `test_unmapped_model_never_prefixed`.
- **Unmapped prefix-requiring model.** The residual risk of the allowlist
  approach: a new model needing a prefix but absent from the map fails with
  `AccessDeniedException`. Preferred to a silent misroute; the error must name
  the model and suggest the map entry.
- **Region mismatch.** Claude Opus 5 has no in-region access in us-west-2 /
  us-east-2. An operator there without a prefix gets a confusing failure —
  detect and explain.
- **Per-model output caps.** 8K/16K/128K/128K against a profile bound of 32768.
  Clamp with a warning (Q5). Note the profile bound only constrains the dev
  seat (MiniMax 8K, Kimi 16K — both well under 32768), so the "exceeds 32768"
  direction is unreachable for the shipped configuration.
- **Adversarial degrade path masks outages.** `AbstractCodeReviewDispatcher.review()`
  degrades an infra error to a *passing* verdict with a nit-level finding
  (`code_review.py:145-157`). A Bedrock outage would therefore silently pass
  the adversarial gate. Inherited behaviour — add an explicit test so it is a
  known property, not a surprise.
- **Truncated diff.** Opus 5's 1M context is generous, but a very large diff
  must be truncated deterministically with an explicit marker
  (`max_diff_chars`), never silently.
- **Private-method coupling.** Module 6 calls `client._emit_before_call` /
  `_emit_round_event` / `_emit_after_call` — underscore-private on
  `AbstractClient`. This is the same intimacy the dispatcher already has with
  `client._chat_completion` (`llm.py:369-384`), so it is consistent rather than
  novel, but it must be a documented choice. `has_subscribers` short-circuits,
  so there is no cost when nobody listens.
- **Two credential stories.** `bedrock-mantle` uses a Bedrock API key (bearer);
  `BedrockConverseBase` uses `aws_id`/SigV4. Both must be documented.
- **`dispatchers/llm.py` is hot and actively churning** (per its sibling
  `_shared.py` docstring). Module 6 touches it — keep the diff minimal and
  rebase often.
- **Concurrent branch resets.** During this feature's development, concurrent
  SDD processes twice reset `dev` to `origin`, once discarding committed local
  work. **Push immediately after every commit.**

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aioboto3` | existing | Bedrock Runtime Converse — adversarial + mechanical seats |
| `openai` (async) | existing | `bedrock-mantle` OpenAI-compatible endpoint — dev seat |
| `pydantic` | v2, existing | Profiles + `UsageReport` |

Runtime requirements: AWS credentials with Bedrock model access, plus a
Bedrock API key for the `bedrock-mantle` path. No new packages.

---

## 8. Open Questions

- [x] **Is the `dev_loop` split present on `base_branch`?** — *Resolved in brainstorm (Q1)*: Yes. Landed as `a50567f39`, destroyed by a concurrent `reset --hard`, recovered via reflog + cherry-pick, now on `dev` and pushed. Contract re-verified against `2aa9366bf`.
- [x] **Transport: adapter or split?** — *Resolved in brainstorm (Q2/[R4])*: Option A. Anthropic models on Bedrock have no Chat Completions, so Nova never uses that path for them; a Claude development seat uses the `claude-code` backend. The Converse↔OpenAI adapter is not built.
- [x] **Should the research seat become pluggable?** — *Resolved in brainstorm (Q3/[R7])*: No — discarded entirely. `ResearchNode` stays on the Claude Code Agent with `/sdd-spec` + `/sdd-task` and is not modified.
- [x] **Are all model ids verified?** — *Resolved in brainstorm (Q4)*: Yes. Kimi K2.5 = `moonshotai.kimi-k2.5` (256K/16K, no prefix); Fable 5 corrected to `global.anthropic.claude-fable-5`; "Claude Opus 5.8" dropped (no model card).
- [x] **Per-model output caps: clamp or reject?** — *Resolved during /sdd-spec*: **Clamp with a warning.** A `MODEL_MAX_OUTPUT_TOKENS` map caps the effective value at dispatch and logs model + requested + effective. Runs never fail on a config nobody deliberately chose. See Module 4 and `test_clamp_minimax_to_8192`.
- [x] **Is `_emit_round_event` reusable from a dispatcher?** — *Resolved in brainstorm (Q6)*: Yes, no extraction needed. It is an `AbstractClient` instance method depending only on `self.events`/`get_global_registry()` plus a `TraceContext` from `_emit_before_call`; `_dispatch_loop` already holds the client. See Module 6.
- [x] **Coverage of non-Nova backends?** — *Resolved in brainstorm (Q7/[R8])*: All backends from day one — nvidia, zai, moonshot, grok and nova together.
- [x] **Bedrock per-round usage coverage?** — *Resolved in brainstorm (Q8/[R5])*: Out of scope; ships as FEAT-404. This feature degrades cleanly without it.
- [ ] **Which seat-identity granularity does the report key on?** `AgentUsage.seat` needs a stable id for pool workers (`dev-agent-1`, `dev-agent-2`). Confirm whether `agent_pool.py` already exposes such an id or one must be derived from `node_id` + worker index — decide during Module 7. — *Owner: implementer*
- [ ] **Should `zai.glm-5` be offered in the curated `nova` model list?** It is verified and Bedrock-hosted, but the repo already has a vendor-direct `zai` backend, so the same model would be reachable two ways. Cosmetic; decide during Module 5. — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Rationale**: Although the work splits into three internally-parallel
  clusters — (a) translation + profiles + dispatchers, (b) round events +
  usage report, (c) PR enrichment — they converge on the same shared
  registration points (`DevAgentBackend`, `build_dispatcher`,
  `catalog.BACKENDS`, `dispatchers/__init__.py`, `models/__init__.py`).
  Splitting across worktrees would buy modest wall-clock and cost repeated
  three-way merges in the most contended files in the package.
- **Parallelisable if ever needed**: Module 6 + Module 7 (the usage path) are
  genuinely independent of Modules 1–5 and touch a disjoint file set. They
  could run in a second worktree, at the cost of one merge in `run_bundle.py`.
- **Cross-feature dependencies**:
  - **FEAT-404** (Bedrock per-round token usage) — *soft* dependency. Not
    required to merge first; without it, Bedrock-backed seats render `—` for
    rounds and tokens. Landing it later requires no rework here.
  - `new-codereviewers` (FEAT-270) shares `code_review.py` and `catalog.py`;
    `novaclient-amazon-aws` (FEAT-315) shares `clients/nova/client.py` and
    `models/bedrock_models.py`. Check for in-flight work in those files before
    starting.

```bash
git worktree add -b feat-405-novaclient-dev-loop \
  .claude/worktrees/feat-405-novaclient-dev-loop HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-03 | Jesus Lara | Initial draft from `novaclient-dev-loop.brainstorm.md` (Option A; 8 brainstorm questions resolved, Q5 resolved during spec) |
| 0.2 | 2026-08-03 | Jesus Lara | Status → approved; ready for `/sdd-task` |
