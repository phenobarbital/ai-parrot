---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Nova (AWS Bedrock) Dispatcher, Pluggable Research Seat & Per-Agent Usage Report

**Date**: 2026-08-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

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
   highest-volume consumer of tokens in the loop, yet it defaults to the same
   frontier-tier models used for review. Bedrock now carries agent-native,
   token-efficient models (MiniMax M2.5, GLM-5, Kimi) that are a better fit for
   mechanical code production, while reserving Claude Opus 5 for the seat where
   judgement actually pays — adversarial review. There is currently no way to
   express that split within one provider.

3. **Per-agent usage is invisible — and, for most backends, uncollected.**
   `run_bundle.py` renders a per-node table with `input_tokens`/`output_tokens`
   (`run_bundle.py:61-67`), but those numbers only ever arrive from
   `ClaudeCodeDispatcher._extract_result_usage` (`dispatchers/claude.py:625`),
   which reads the Claude Agent SDK's `ResultMessage.usage`. **`LLMCodeDispatcher`
   emits no usage at all** — its tool loop (`dispatchers/llm.py:190`) never
   inspects the response for token counts. So every API-backed backend (nvidia,
   zai, moonshot, grok — and nova, once added) reports `None`. You cannot answer
   "what did this run cost, and which agent spent it?" for exactly the backends
   whose cost you most want to compare.

The opportunity: add a **single `nova` backend** that reaches Claude Opus 5,
Claude Haiku 4.5, MiniMax M2.5 and friends through one AWS credential, wire it
into the seats where each model earns its keep, make the research seat
backend-agnostic instead of hard-wired to Claude Code, and close the usage-
telemetry gap so the resulting model mix can actually be measured.

---

## Constraints & Requirements

Established across four rounds of discovery (Round 0 flow type; Rounds 1–3
design decisions). Decisions marked **[R*]** are user-confirmed, not inferred.

- **[R0]** `type: feature`, `base_branch: dev`. Never bases on `main`.
- **[R3]** **Fully opt-in.** Nothing changes for an operator who does not select
  `nova`. `claude-code` remains the development default; `codex` remains the
  adversarial default. This is a pure addition.
- **[R1]** **Research seat becomes pluggable**, with `claude-code` still the
  default. `ResearchNode` is generalized to accept any `DevLoopCodeDispatcher`
  + profile; `nova` becomes one selectable option.
- **[R1]** **Adversarial reviewer is read-only by construction**: no tools, the
  diff and criteria go in the prompt, the model returns the verdict JSON. Read-
  only-ness must not depend on enforcement code being correct.
- **[R3]** The adversarial seat becomes **selectable** over `{codex, nova}`;
  `codex` stays the shipped default.
- **[R2]** **PR-creation seat enriches, never replaces.** The deterministic
  `_build_title`/`_build_body` templates remain the skeleton *and* the fallback;
  Haiku 4.5 contributes only a "Summary of changes" section.
- **[R2]** **One `nova` backend id**; the model string selects the family.
  Per-seat defaults live in config keys with the stated models as fallbacks.
- **[R1/R2]** **Usage report**: a `UsageReport` Pydantic model is the single
  source of truth; emit `usage.json` and render **both** markdown (into the
  existing bundle) and a standalone HTML artifact from it. A "round" is one
  model call in a dispatcher's tool loop. **No dollar-cost estimation** — no
  price table to maintain or get wrong.
- **[R1]** Bedrock model IDs are **pinned from verified AWS documentation**, not
  guessed. (See "Verified AWS Facts" — the user-supplied IDs were cross-checked
  against the AWS model cards, and two of them needed correction.)
- **[R3]** The spec **assumes** the `dev_loop/models/` + `dev_loop/dispatchers/`
  split is already committed to `dev`. See Open Questions Q1 — this is currently
  **not true** and is a hard precondition.
- No new vendor SDK dependencies beyond what Bedrock access already requires.
- Async throughout; Google-style docstrings; Pydantic v2 models; `self.logger`.

---

## Verified AWS Facts

Fetched from the AWS Bedrock user guide during this brainstorm. **These override
assumption** — three of them invalidate the codebase's current handling.

| Model | Bedrock model ID | Geo inference IDs | Global ID | Context | Max output | Converse | OpenAI Chat Completions |
|---|---|---|---|---|---|---|---|
| Claude Opus 5 | `anthropic.claude-opus-5` | `us.` / `eu.` / `au.` | `global.anthropic.claude-opus-5` | 1M | 128K | ✅ | ❌ **not supported** |
| MiniMax M2.5 | `minimax.minimax-m2.5` | **Not supported** | **Not supported** | 196K | **8K** | ✅ | ✅ (via `bedrock-mantle`) |
| Z.ai GLM-5 | `zai.glm-5` | **Not supported** | **Not supported** | 200K | 128K | ✅ | ✅ (via `bedrock-mantle`) |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` | `us.` (user-supplied) | — | — | — | ✅ | ❌ (Anthropic family) |
| Kimi K2.5 | `moonshotai.kimi-k2.5` (user-supplied) | **unverified** | **unverified** | — | — | — | — |
| Claude Fable 5 | `anthropic.claude-fable-5` (user-supplied) | `us.` (user-supplied) | — | — | — | — | — |

Four consequences that shape the design:

1. **`bedrock-mantle` is an OpenAI-compatible endpoint.**
   `https://bedrock-mantle.{region}.api.aws/v1` accepts standard
   `chat.completions.create(model="minimax.minimax-m2.5", ...)` with the Bedrock
   API key as the bearer token. AWS explicitly recommends it ("Whenever
   possible, we recommend you use the `bedrock-mantle` endpoint"). This means
   MiniMax/GLM-5 need **no Converse↔OpenAI translation at all**.

2. **Anthropic models on Bedrock do NOT expose Chat Completions.** Claude Opus 5
   supports Converse, Invoke, and the Anthropic Messages API (`bedrock-mantle`
   serves it at `/anthropic/v1/messages`, not `/v1`). The OpenAI-compatible
   shortcut is available for the *coding* models and unavailable for the
   *reviewing* models — which, as it happens, is exactly the right way round
   (see Option A).

3. **MiniMax/GLM-5 reject inference-profile prefixes.** Geo and Global inference
   IDs are "Not supported" — the bare `minimax.minimax-m2.5` is the only valid
   id. But `NovaClient.__init__` defaults `region_prefix="us"`
   (`clients/nova/client.py:72`), which would produce the invalid
   `us.minimax.minimax-m2.5`. **The default that makes Nova 2 Lite work breaks
   MiniMax.** Prefix application must become per-model, not per-client.

4. **`bedrock_models.py`'s translator is wrong for this generation on three
   counts**: `_REGION_PREFIXES = ("us.", "eu.", "apac.")`
   (`models/bedrock_models.py:29`) omits the real `au.` and `global.` prefixes;
   the pass-through detector recognises only `anthropic.`/`amazon.` and so
   treats `minimax.`/`zai.`/`moonshotai.` as untranslatable (warn-and-passthrough);
   and the `anthropic.<id>-vN:0` convention the map is built on **does not hold
   for Claude Opus 5**, whose id carries no date or version suffix.

---

## Options Explored

The options differ on **one axis: how a Bedrock model is driven from a dev-loop
seat.** The usage-report module and the pluggable research seat are common to
all four and are described under "Feature Description".

### Option A: Transport-split — match each seat to the API that already fits it

Recognise that the three Nova seats have *different* interaction shapes, and
give each the transport AWS already provides for it, rather than forcing one
uniform mechanism:

- **Adversarial reviewer (Claude Opus 5) — no tools [R1].** A single
  `ask()` call. `BedrockConverseBase.ask()` (`clients/bedrock.py:578`) already
  does exactly this, and `use_tools` defaults off. No tool loop, no adapter, no
  translation. Read-only holds because the model is never handed a tool.
- **Mechanical/PR seat (Claude Haiku 4.5) — no tools [R2].** Same shape: one
  `ask()` producing a summary paragraph. Same zero-adapter path.
- **Development seat (MiniMax M2.5) — needs the tool loop.** Point an
  OpenAI-compatible client at the `bedrock-mantle` base URL and reuse
  `LLMCodeDispatcher` (`dispatchers/llm.py:39`) essentially unchanged — its
  loop already speaks OpenAI `tools` / `tool_calls`, which is precisely what
  `bedrock-mantle` serves for MiniMax.

The Converse↔OpenAI adapter is deliberately **not built**, because after this
split no seat needs it.

✅ **Pros:**
- **No translation layer exists to be wrong.** The two hardest-looking seats
  (adversarial, mechanical) turn out to need no tool plumbing whatsoever, and
  the one that does gets a natively OpenAI-shaped endpoint.
- Smallest new surface: profiles + a thin dispatcher per shape, no client-class
  surgery on `BedrockConverseBase` (shared with `BedrockConverseClient`).
- Directly follows AWS's own recommendation to prefer `bedrock-mantle`.
- Reuses `LLMCodeDispatcher`'s cwd-safety guard, Redis event streaming, output
  validation and `SessionHost` shim for free on the dev seat.
- The `base_url`-override pattern is already proven in this codebase —
  `ZaiClient` takes `base_url` with a `ZAI_BASE_URL` config override
  (`clients/zai.py:35,45`).

❌ **Cons:**
- **Two transports inside one `nova` backend** — a reviewer reading the code
  must understand why the adversarial seat goes through Converse and the dev
  seat through `bedrock-mantle`. Needs a clear module docstring.
- A Claude model **cannot** hold the *development* seat under this option
  (tool loop + Anthropic ⇒ Converse `toolConfig` required, which this option
  never builds). Acceptable given [R2]'s stated defaults, but it is a real
  limitation, not a nuance.
- `bedrock-mantle` auth is a Bedrock API key (bearer), a different credential
  path from the `aws_id`/SigV4 resolution `BedrockConverseBase` uses — two
  credential stories to document.
- Contradicts the Round 2 answer ("adapter on the client side"), which was
  given before the `bedrock-mantle` and Chat-Completions-unsupported facts were
  known. Flagged as Open Question Q2.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Bedrock Runtime (Converse) — adversarial + mechanical seats | Already a dependency via `BedrockConverseBase` |
| `openai` (async) | `bedrock-mantle` OpenAI-compatible endpoint — dev seat | Already used by nvidia/zai/moonshot clients |
| `pydantic` v2 | `NovaCodeDispatchProfile`, `UsageReport` | Already core |

🔗 **Existing Code to Reuse:**
- `parrot/clients/bedrock.py:578` — `BedrockConverseBase.ask()`, the no-tools path for both review seats
- `parrot/clients/nova/client.py:30` — `NovaClient`, already `LLMFactory`-registered
- `parrot/flows/dev_loop/dispatchers/llm.py:39` — `LLMCodeDispatcher`, the dev seat's whole loop
- `parrot/flows/dev_loop/dispatchers/moonshot.py:18` — the exact "subclass `LLMCodeDispatcher`, override the two completion hooks" pattern to copy
- `parrot/clients/zai.py:35` — the configurable-`base_url` precedent
- `parrot/flows/dev_loop/code_review.py:164` — `CodeReviewDispatcherFactory.register` decorator

---

### Option B: Client-side Converse↔OpenAI adapter on `BedrockConverseBase`

Add an OpenAI-shaped `_chat_completion(model, messages, use_tools, tools, ...)`
to `BedrockConverseBase` (or to `NovaClient`) that translates OpenAI tool
schemas into Converse `toolSpec` on the way in and Converse `toolUse` blocks
into OpenAI `tool_calls` on the way out. Every dev-loop dispatcher then drives
Bedrock through the single uniform path it already knows, and
`NovaCodeDispatcher` becomes a near-empty subclass of `LLMCodeDispatcher`.

*This was the Round 2 selection, made before the AWS facts above were gathered.*

✅ **Pros:**
- **One uniform mechanism** for every seat and every model family — no
  "why does this seat use a different transport" question.
- **Any Bedrock model can hold any seat**, including a Claude model in the
  development seat with full tool use. Strictly more capable than Option A.
- The adapter is reusable beyond the dev-loop: any future consumer of
  `BedrockConverseClient` gets OpenAI-shaped access for free.
- Only one credential story (SigV4 / `aws_id`), no Bedrock API key.
- `_prepare_tools` already converts registered tools to Bedrock `toolSpec` via
  `ToolSchemaAdapter` with `ToolFormat.BEDROCK` (`clients/bedrock.py:413`) —
  roughly half the inbound translation already exists.

❌ **Cons:**
- **Touches a foundational class with a wide blast radius.** `BedrockConverseBase`
  is shared with `BedrockConverseClient`; CLAUDE.md's ban on casually modifying
  `abstract_client.py` reflects the same instinct one tier down.
- The translation layer becomes **the** correctness risk: tool-call id
  round-tripping, multi-block content, `stopReason: tool_use` handling,
  streaming, and per-family quirks all have to be right, and get exercised on
  every single dev-loop turn.
- Builds a Converse tool-loop adapter that **the chosen seat configuration never
  needs** — under [R1]/[R2] the only tool-using Nova seat is MiniMax, which
  already speaks OpenAI natively.
- More code to test than Option A for the same shipped capability.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Bedrock Runtime Converse | Already a dependency |
| `pydantic` v2 | Profiles + usage models | Already core |

🔗 **Existing Code to Reuse:**
- `parrot/clients/bedrock.py:413` — `_prepare_tools()` → `ToolFormat.BEDROCK`, the inbound half
- `parrot/clients/bedrock.py:724-731` — existing `payload["toolConfig"]` injection
- `parrot/flows/dev_loop/dispatchers/llm.py:369` — `_chat_completion`, the hook the adapter satisfies

---

### Option C: Bedrock-native tool loop inside `NovaCodeDispatcher`

Leave every client class untouched and write a Converse-native agent loop in
`dispatchers/nova.py`, borrowing only the shared helpers from
`dispatchers/_shared.py:82-119`.

✅ **Pros:**
- Zero impedance mismatch — the loop speaks Converse end to end, so `toolUse`,
  `toolResult`, and `stopReason` are handled in their native shapes.
- No changes to `BedrockConverseBase`; blast radius confined to one new module.
- Full freedom to exploit Bedrock-only features (prompt caching checkpoints —
  Opus 5 supports 4 per request with 5-minute/1-hour TTL — guardrails, service
  tiers) without contorting them through an OpenAI shape.

❌ **Cons:**
- **Duplicates `LLMCodeDispatcher` wholesale**: the turn loop, cwd-safety guard,
  Redis event publishing, output validation, and the `SessionHost` context
  shim are ~900 lines that would be reimplemented and would then drift. The
  `_shared.py` docstring already records how actively this area churns.
- Highest long-term maintenance cost of the four for the least reuse.
- Every future dev-loop dispatcher improvement has to be ported by hand.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Bedrock Runtime Converse | Already a dependency |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/dispatchers/_shared.py:82-119` — exceptions, `DevLoopCodeDispatcher` protocol, `SessionHost` shim
- `parrot/clients/bedrock.py:413` — `_prepare_tools()`

---

### Option D (unconventional): Configuration-only Nova — profiles, no new dispatcher

Ship **no new dispatcher class at all**. Observe that `LLMCodeDispatcher` is
already model-agnostic and that its client is produced by an injected
`client_factory` (the Moonshot dispatcher passes
`lambda model, **kw: LLMFactory.create(model, **kw)`,
`dispatchers/moonshot.py:44`). So `dev_loop/models/nova.py` contains only
`NovaCodeDispatchProfile` (+ the review/mechanical profiles), and
`build_dispatcher`'s `nova` branch instantiates the plain `LLMCodeDispatcher`
pointed at a `bedrock-mantle` base URL — exactly as the `nvidia` branch already
does (`agent_builder.py:159`). `dev_loop/dispatchers/nova.py` exists only to
hold the two no-tools review/mechanical dispatchers.

✅ **Pros:**
- **Smallest possible diff** — one config-carrying profile module plus a
  `build_dispatcher` branch that mirrors an existing one line for line.
- Nothing to drift: the dev seat inherits every future `LLMCodeDispatcher` fix
  automatically, because it *is* an `LLMCodeDispatcher`.
- Fastest path to measuring whether MiniMax M2.5 is actually good at this repo's
  code before investing in bespoke machinery.

❌ **Cons:**
- **No place to put per-family quirks.** Moonshot and Z.ai each needed a
  dispatcher subclass precisely because their models rejected standard sampling
  args or needed thinking-flag injection; MiniMax's 8K output cap and any
  reasoning-flag handling would have nowhere natural to live.
- Violates the user's explicit instruction to create `dev_loop/dispatchers/nova.py`
  as a real dispatcher module — it would exist, but hold only the review seats.
- Likely a way-station: the first MiniMax quirk forces a promotion to Option A.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `openai` (async) | `bedrock-mantle` endpoint | Already used by the nvidia/zai/moonshot clients |

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/agent_builder.py:159` — the `nvidia` branch, copied verbatim with a different base URL
- `parrot/flows/dev_loop/dispatchers/moonshot.py:44` — the `client_factory` injection pattern

---

## Recommendation

**Option A** is recommended.

The decisive finding is that **the seat configuration the user asked for does
not actually require a Converse tool loop.** [R1] makes the adversarial reviewer
no-tools, and [R2] makes the PR seat a summary-paragraph generator — both are
single `ask()` calls that `BedrockConverseBase.ask()` (`clients/bedrock.py:578`)
already serves. The only tool-using Nova seat is the MiniMax development worker,
and MiniMax is one of the models AWS exposes over the **OpenAI-compatible
`bedrock-mantle` endpoint**. So the hardest piece of Option B — a bidirectional
Converse↔OpenAI tool-call translator — would be built to serve **zero** seats in
the shipped configuration.

What Option A trades away is real and worth stating plainly: **a Claude model
cannot hold the development seat.** Anthropic models on Bedrock do not expose
Chat Completions, so a tool-using Claude worker would need exactly the adapter
Option A declines to build. If that becomes a requirement, Option B's adapter is
the follow-up feature — and Option A does not block it, because the profiles and
the `nova` catalog entry stay unchanged when the transport underneath the dev
seat is swapped.

Option A over Option D because MiniMax's verified **8K max-output cap** is
already a per-family quirk needing a home: `LLMCodeDispatchProfile.max_tokens`
is bounded `le=32768` (`models/llm.py:24`), so a naive profile can request more
than the model can return. That is precisely the class of constraint the
Moonshot and Z.ai dispatcher subclasses exist to encode, and it argues for a
real `NovaCodeDispatcher` from day one rather than after the first failure.

Option A over Option C because duplicating ~900 lines of actively-churning
dispatcher logic to gain Converse-native handling that only one seat would use
is a poor trade; `_shared.py`'s own docstring documents how much this area moves.

Honest caveat: Option A contradicts the Round 2 selection. That answer was given
before the AWS model cards were read, and two of the facts they contain
(`bedrock-mantle` exists; Anthropic has no Chat Completions on Bedrock) point
the other way. **Open Question Q2 puts this back to the user** rather than
quietly overriding a stated decision.

---

## Feature Description

### User-Facing Behavior

An operator with AWS Bedrock access can run the entire dev-loop without a single
vendor API key or coding CLI installed:

```
DEV_LOOP_DEV_AGENTS='[{"agent":"nova","model":"minimax.minimax-m2.5","count":2}]'
DEV_LOOP_ADVERSARIAL_BACKEND=nova
DEV_LOOP_NOVA_REVIEW_MODEL=us.anthropic.claude-opus-5
DEV_LOOP_NOVA_MECHANICAL_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
DEV_LOOP_RESEARCH_BACKEND=nova     # optional; default stays claude-code
```

Setting none of these changes nothing [R3]: `claude-code` still develops,
`codex` still reviews adversarially, Claude Code still researches.

In the console UI, `nova` appears as one more backend in the picker, offering
the curated Bedrock model list and — like every other backend — accepting a
free-text model id. The adversarial picker, previously a fixed single-value
display driven by `ADVERSARIAL_BACKEND` (`catalog.py:48,294`), becomes a real
two-option select.

At the end of every run — Nova or not — two new artifacts land beside the
existing bundle:

- `usage.json` — the `UsageReport` envelope, machine-readable.
- `usage.html` — a standalone, self-contained report: one row per agent seat
  with backend, model, rounds, input/output/cache tokens and wall-clock, a
  per-node timeline, and run totals.

The existing markdown bundle gains a per-agent section rendered from the same
envelope, so the three views can never disagree.

### Internal Behavior

**Module 1 — Bedrock model-ID translation.** `models/bedrock_models.py` learns
this model generation: add `au.` and `global.` to `_REGION_PREFIXES`
(currently `("us.", "eu.", "apac.")`, line 29); teach the pass-through detector
the `minimax.`, `zai.`, and `moonshotai.` vendor namespaces; add the verified
map entries, noting that Claude Opus 5 and Fable 5 carry **no** `-vN:0` suffix,
breaking the existing `anthropic.<id>-vN:0` convention. Critically, prefix
application becomes **per-model**: models whose card says geo/global inference
is "Not supported" (MiniMax, GLM-5) must never receive a prefix, even when the
client's `region_prefix` is set. `NovaClient` defaults `region_prefix="us"`
(`clients/nova/client.py:72`) because Nova 2 Lite requires it — that default
must not leak onto MiniMax.

**Module 2 — `dev_loop/models/nova.py`.** `NovaCodeDispatchProfile` (extending
`LLMCodeDispatchProfile`, `models/llm.py:10`, following
`MoonshotCodeDispatchProfile`, `models/moonshot.py:10`) with a `max_tokens`
bound that respects the target model's real ceiling — 8192 for MiniMax M2.5.
Plus `NovaAdversarialReviewProfile` (no tools, read-only by construction) and
`NovaMechanicalProfile` (no tools, short output).

**Module 3 — `dev_loop/dispatchers/nova.py`.** `NovaCodeDispatcher` extends
`LLMCodeDispatcher` and overrides the two completion hooks
(`_completion_args`, `dispatchers/llm.py:347`, and `_chat_completion`, line 369)
to route through the `bedrock-mantle` client — the same two-hook override shape
`MoonshotCodeDispatcher` uses (`dispatchers/moonshot.py:47,82`). Alongside it,
`NovaAdversarialReviewDispatcher` — registered via
`@CodeReviewDispatcherFactory.register("nova-adversarial")`
(`code_review.py:170`), `advisory = True`, mirroring
`CodexAdversarialReviewDispatcher` (`code_review.py:266`) including its
belt-and-braces `files_modified = []` override — issues one `ask()` with the
diff in the prompt and no tools.

**Module 4 — Wiring.** Add `"nova"` to the `DevAgentBackend` Literal
(`models/base.py:383`) and a branch to `build_dispatcher` before the
`raise ValueError` at `agent_builder.py:210`; add a `BackendInfo` row to
`catalog.py:88`; turn `ADVERSARIAL_BACKEND` from a constant into a
config-resolved choice over `{codex, nova}` defaulting to `codex` [R3], updating
both use sites (`catalog.py:294,296`).

**Module 5 — Pluggable research seat.** `ResearchNode.__init__` currently
demands `dispatcher: ClaudeCodeDispatcher` (`nodes/research.py:142`) and builds
`ClaudeCodeDispatchProfile(subagent="sdd-research")` (line 283). Widen the type
to the `DevLoopCodeDispatcher` protocol (`_shared.py:105`) and inject the
profile from the factory instead of constructing it inline. The Jira-before-
dispatch ordering (pinned by
`test_research_node_creates_jira_then_dispatches`) and the duplicate-worktree
check are untouched. Default stays `claude-code` [R1]. **A Nova research seat
cannot run `/sdd-spec` or `/sdd-task`** — those are Claude Code slash commands —
so the nova path must be documented as triage-and-report only, and must fail
loudly rather than silently skip scaffolding. See Open Question Q3.

**Module 6 — Usage capture (the real gap).** Today, usage flows only from
`ClaudeCodeDispatcher._extract_result_usage` (`dispatchers/claude.py:625`) into
the `dispatch.completed` payload, is absorbed by `session_state.py:1259-1278`
into `DispatchState` (`session_state.py:202-208`), and is projected into
`NodeReport` (`run_bundle.py:61-67`). `LLMCodeDispatcher` contributes nothing.
This module adds usage extraction to the `LLMCodeDispatcher` turn loop
(`dispatchers/llm.py:190`), **accumulating across turns** — which is the whole
point, and where the known trap lives:

> Saved wiki lesson `mem-db9c4515cb6e`: *"AIMessage.usage does NOT aggregate
> tokens across the client-side tool loop — the loop discards intermediate
> rounds' usage and only the final round reaches CompletionUsage."*

A naive implementation that reads usage once after the loop will therefore
under-report a 20-turn dev session as a 1-turn one. The accumulator must sum
per turn, inside the loop, and the round counter [R2] falls out of the same
place.

**Module 7 — `UsageReport` + renderers.** A `UsageReport` Pydantic model keyed
by agent seat (backend, model, rounds, input/output/cache tokens, duration),
serialised to `usage.json`, rendered to markdown inside the existing bundle
(reusing `_format_tokens`, `run_bundle.py:365`) and to a self-contained HTML
artifact. No cost estimation [R2].

**Module 8 — Haiku PR enrichment.** In `feature_handoff.py` and
`deployment_handoff.py`, the deterministic `_build_body`
(`feature_handoff.py:511`, `deployment_handoff.py:479`) stays authoritative;
when the mechanical seat is configured, a Haiku `ask()` contributes one
"Summary of changes" section spliced in [R2]. Any failure, timeout, or absent
config falls back to today's exact output.

### Edge Cases & Error Handling

- **Invalid prefix on a prefix-less model.** `us.minimax.minimax-m2.5` is not a
  valid id. The translator must strip/withhold the prefix per-model and a unit
  test must pin it — this is the single most likely day-one failure.
- **MiniMax 8K output cap.** A profile requesting more than 8192 output tokens
  must be clamped (and warned) rather than rejected by Bedrock mid-run.
- **Model not enabled in the account/region.** Bedrock returns
  `AccessDeniedException`; surface it as a `DispatchExecutionError` naming the
  model and region, not a bare stack trace.
- **Region mismatch.** Claude Opus 5 has **no in-region access in us-west-2 or
  us-east-2** — only via a geo/global profile. An operator on us-west-2 with
  `region_prefix=None` gets a confusing failure; detect and explain it.
- **Unverified ids.** `moonshotai.kimi-k2.5` and `anthropic.claude-fable-5` are
  user-supplied and could not be confirmed against a model card. They must
  warn-and-passthrough, never hard-fail the run (Q4).
- **Usage absent.** Any dispatcher that cannot report tokens yields `None`, and
  the renderers must show "—", never a fabricated `0` — `RunTotals` already
  documents this rule (`run_bundle.py:120-123`); the new report must honour it.
- **Adversarial degrade path.** `AbstractCodeReviewDispatcher.review()`
  degrades an infra error to a *passing* verdict with a nit-level finding
  (`code_review.py:145-157`). A Bedrock outage would therefore silently pass the
  adversarial gate — inherited behaviour, but worth an explicit test.
- **Truncated diff.** Opus 5's 1M context is generous, but a very large diff must
  be truncated deterministically with an explicit marker rather than silently.

---

## Capabilities

### New Capabilities
- `nova-dev-loop-backend`: a `nova` backend for the dev-loop reaching Bedrock-hosted models (Claude Opus 5 / Haiku 4.5 / Fable 5, MiniMax M2.5, GLM-5, Kimi) through one AWS credential.
- `nova-adversarial-review`: a read-only, no-tools adversarial reviewer on Claude Opus 5, selectable against the incumbent `codex`.
- `pluggable-research-seat`: `ResearchNode` accepts any dispatcher/profile pair instead of hard-wired `ClaudeCodeDispatcher`.
- `dev-loop-usage-report`: per-agent token/round accounting emitted as `usage.json` plus markdown and HTML renderings.
- `bedrock-model-id-translation-2026`: correct prefix and vendor-namespace handling for the 2026 Bedrock model generation.

### Modified Capabilities
- `new-codereviewers` (`sdd/specs/new-codereviewers.spec.md`) — the adversarial seat stops being codex-only.
- `novaclient-amazon-aws` (`sdd/specs/novaclient-amazon-aws.spec.md`) — `NovaClient` gains non-Nova Bedrock model coverage and per-model prefix handling.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/models/nova.py` | **new** | `NovaCodeDispatchProfile` + review/mechanical profiles |
| `parrot/flows/dev_loop/dispatchers/nova.py` | **new** | `NovaCodeDispatcher` + `NovaAdversarialReviewDispatcher` |
| `parrot/flows/dev_loop/usage_report.py` | **new** | `UsageReport` model + markdown/HTML renderers (no such module today) |
| `parrot/flows/dev_loop/models/base.py:383` | modifies | `DevAgentBackend` Literal gains `"nova"` (also used at line 847) |
| `parrot/flows/dev_loop/agent_builder.py:100-210` | extends | new `nova` branch before the `raise ValueError` |
| `parrot/flows/dev_loop/catalog.py:48,88,294` | modifies | `ADVERSARIAL_BACKEND` const → config-resolved choice; new `BackendInfo` row |
| `parrot/flows/dev_loop/code_review.py:164` | extends | register `nova-adversarial` |
| `parrot/flows/dev_loop/dispatchers/llm.py:190` | modifies | **accumulate** per-turn usage in the tool loop |
| `parrot/flows/dev_loop/nodes/research.py:142,283` | modifies | widen dispatcher type; inject profile |
| `parrot/flows/dev_loop/nodes/feature_handoff.py:511` | extends | optional Haiku summary section |
| `parrot/flows/dev_loop/nodes/deployment_handoff.py:479` | extends | same |
| `parrot/flows/dev_loop/run_bundle.py` | extends | per-agent section from `UsageReport` |
| `parrot/models/bedrock_models.py:29,37` | modifies | prefixes, vendor namespaces, new ids, per-model prefix policy |
| `parrot/clients/nova/client.py:72` | modifies | `region_prefix` must not leak onto prefix-less models |
| `parrot/conf.py:1048` | extends | new `DEV_LOOP_NOVA_*` keys; `DEV_LOOP_ADVERSARIAL_BACKEND` |
| `parrot/flows/dev_loop/models/__init__.py`, `dispatchers/__init__.py` | extends | export the new symbols |
| `packages/ai-parrot/tests/flows/dev_loop/` | extends | new tests alongside `test_dispatcher.py`, `test_dispatch_telemetry.py` |

**Breaking changes:** none intended [R3] — every default is preserved.
**New runtime dependency:** AWS credentials with Bedrock model access; a Bedrock
API key additionally, if Option A's `bedrock-mantle` path is adopted.

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (Bedrock model IDs, this conversation)
us.anthropic.claude-opus-5
us.anthropic.claude-haiku-4-5-20251001-v1:0
us.anthropic.claude-fable-5
minimax.minimax-m2.5
moonshotai.kimi-k2.5

# Source: user-provided (AWS documentation references)
https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-zai-glm-5.html
https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-minimax-minimax-m2-5.html
```

Cross-check against the AWS model cards (see "Verified AWS Facts"):
`us.anthropic.claude-opus-5` ✅ confirmed as the US geo inference id (base id
`anthropic.claude-opus-5`). `minimax.minimax-m2.5` ✅ confirmed — and confirmed
to accept **no** prefix. `moonshotai.kimi-k2.5` and `us.anthropic.claude-fable-5`
❓ model cards not retrievable; treat as unverified. `zai.glm-5` is a bonus id
discovered from the supplied documentation link.

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/clients/nova/client.py:30
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    client_type: str = "nova"                     # line 62
    client_name: str = "nova"                     # line 63
    _default_model: str = "nova-2-lite"           # line 64
    _fallback_model: str = "nova-lite"            # line 65

    def __init__(                                  # line 67
        self,
        aws_id: Optional[str] = None,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        region_prefix: Optional[str] = "us",       # line 72 — leaks onto MiniMax
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        voice_id: str = "matthew",
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        **kwargs,
    ): ...

# From parrot/clients/bedrock.py
class BedrockConverseBase:
    def _prepare_tools(self, filter_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:  # line 413
        ...  # → ToolSchemaAdapter with ToolFormat.BEDROCK
    async def ask(self, ..., tools=None, use_tools=None, ...):  # line 578; tools line 589, use_tools line 590
        ...  # line 724-731: payload["toolConfig"] = {"tools": tool_specs}

# From parrot/flows/dev_loop/dispatchers/_shared.py
T = TypeVar("T", bound=BaseModel)                  # line 21
class DispatchExecutionError(Exception): ...        # line 82
class DispatchOutputValidationError(Exception):     # line 91
    def __init__(self, message: str, *, raw_payload: str = "") -> None: ...  # line 100
class DevLoopCodeDispatcher(Protocol):              # line 105
    async def dispatch(                             # line 108
        self, *, brief: BaseModel, profile: BaseModel, output_model: Type[T],
        run_id: str, node_id: str, cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T: ...

# From parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                            # line 39
    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None): ...  # line 65
    async def _dispatch_loop(self, *, brief, profile, output_model, run_id, node_id, stream_key, cwd): ...   # line 172
        # line 190: for turn_index in range(profile.max_turns):   ← usage must accumulate HERE
    def _completion_args(self, profile, tools) -> Dict[str, Any]: ...  # line 347
    async def _chat_completion(self, *, client, model, messages, args) -> Any: ...  # line 369
        # requires client._chat_completion(model=..., messages=..., use_tools=True, **args)

# From parrot/flows/dev_loop/models/llm.py:10
class LLMCodeDispatchProfile(BaseModel):
    subagent: Literal["sdd-worker"] = "sdd-worker"                    # line 18
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"              # line 19
    max_turns: int = Field(default=24, ge=1, le=100)                  # line 23
    max_tokens: int = Field(default=4096, ge=256, le=32768)           # line 24 — > MiniMax's 8K cap
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)           # line 25

# From parrot/flows/dev_loop/models/moonshot.py:10 — the pattern to copy
class MoonshotCodeDispatchProfile(LLMCodeDispatchProfile):
    model: str = Field(default="kimi-k3")                             # line 21
    llm: str = "moonshot:kimi-k3"                                     # line 25
    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "MoonshotCodeDispatchProfile": ...  # line 43

# From parrot/flows/dev_loop/dispatchers/moonshot.py:18 — the two-hook override shape
class MoonshotCodeDispatcher(LLMCodeDispatcher):
    def _completion_args(self, profile, tools) -> Dict[str, Any]: ...  # line 47
    async def _chat_completion(self, *, client, model, messages, args) -> Any: ...  # line 82
    # ctor injects: client_factory=lambda model, **kw: LLMFactory.create(model, **kw)  # line 44

# From parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):            # line 85
    agent_name: str                                  # line 99
    advisory: bool = False                           # line 100
    async def review(self, *, brief, run_id, node_id, cwd, session_host=None, round="") -> CodeReviewVerdict: ...  # line 106
    @abstractmethod
    def build_review_profile(self) -> BaseModel: ...  # line 159
class CodeReviewDispatcherFactory:                   # line 164
    @classmethod
    def register(cls, name: str): ...                # line 170
    @classmethod
    def create(cls, name: str, **kwargs) -> AbstractCodeReviewDispatcher: ...  # line 180

@CodeReviewDispatcherFactory.register("codex-adversarial")   # line 266 — the model to mirror
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):  # line 267
    agent_name = "codex-adversarial"                 # line 277
    advisory = True                                  # line 278
    # line 290: self._model = model or conf.DEV_LOOP_ADVERSARIAL_MODEL
    # line 337: returns verdict.model_copy(update={"files_modified": [], ...})

# From parrot/flows/dev_loop/run_bundle.py
class NodeReport(_Frozen):                           # line 48
    input_tokens: Optional[int] = None               # line 61
    output_tokens: Optional[int] = None              # line 62
    cache_creation_input_tokens: Optional[int] = None  # line 63
    cache_read_input_tokens: Optional[int] = None    # line 64
    total_cost_usd: Optional[float] = None           # line 65
    num_turns: Optional[int] = None                  # line 66
class RunTotals(_Frozen): ...                        # line 120 — "must not render fake zeros"
class RunBundle(_Frozen): ...                        # line 137
def _format_tokens(input_tokens, output_tokens) -> str: ...  # line 365
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot.clients.nova import NovaClient                       # clients/nova/__init__.py
from parrot.clients.factory import LLMFactory                    # "nova": _lazy_nova at factory.py:96
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError, T, DevLoopCodeDispatcher
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile
from parrot.flows.dev_loop.models import DevAgentBackend, DevAgentSpec   # models/__init__.py:29,93
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory, AbstractCodeReviewDispatcher
from parrot.models.bedrock_models import PUBLIC_TO_BEDROCK, translate
```

#### Key Attributes & Constants

- `DevAgentBackend` → `Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding"]` (`models/base.py:383`) — **no `nova`**; also referenced at line 847
- `JUDGE_BACKENDS` → `("claude-code","codex","gemini","google_coding")` (`catalog.py:42`)
- `ADVERSARIAL_BACKEND` → `"codex"` (`catalog.py:48`; consumed at 294 and 296)
- `PRIMARY_REVIEW_BACKENDS` → `("claude-code","codex","gemini","google_coding")` (`catalog.py:52`)
- `_REGION_PREFIXES` → `("us.", "eu.", "apac.")` (`models/bedrock_models.py:29`) — missing the real `au.` and `global.`
- `conf.DEV_LOOP_ADVERSARIAL_MODEL` → `str`, fallback `"gpt-5.5"` (`conf.py:1048`)
- `conf.DEV_LOOP_ADVERSARIAL_SCOPE` → fallback `"uncommitted"` (`conf.py:1053`); `DEV_LOOP_ADVERSARIAL_BASE_REF` (`conf.py:1076`)
- `ZaiClient.base_url` → configurable, `ZAI_BASE_URL` override (`clients/zai.py:35,45`) — the precedent for a `bedrock-mantle` base URL
- `build_dispatcher` branch line numbers: claude-code 138, codex 145, gemini 152, nvidia 159, grok 175, zai 182, moonshot 193, google_coding 203, `raise ValueError` 210 (`agent_builder.py`)
- Existing tests to extend: `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py`, `test_dispatch_telemetry.py`, `test_codex_dispatcher.py`, `test_gemini_dispatcher.py`

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.flows.dev_loop.dispatchers.nova`~~ / ~~`NovaCodeDispatcher`~~ — this feature creates them
- ~~`parrot.flows.dev_loop.models.nova`~~ / ~~`NovaCodeDispatchProfile`~~ — this feature creates them
- ~~`parrot.flows.dev_loop.usage_report`~~ — no usage-report module exists (verified: no `usage*` file in the package)
- ~~`"nova"` in `DevAgentBackend`~~ — the Literal has exactly 8 values, none of them `nova`
- ~~`BedrockConverseBase._chat_completion(...)`~~ — **does not exist**; the class exposes `ask()`/`ask_stream()`/`invoke()`/`resume()` in Converse shape. `LLMCodeDispatcher._chat_completion` (llm.py:369) would raise `DispatchExecutionError("... does not expose chat completion")` against it today.
- ~~`PUBLIC_TO_BEDROCK["claude-opus-5"]`~~ / ~~`["claude-fable-5"]`~~ / ~~`["minimax-m2.5"]`~~ / ~~`["kimi-k2.5"]`~~ — absent; `bedrock_models.py:65` explicitly says "Bedrock IDs TBD"
- ~~Usage collection in `LLMCodeDispatcher`~~ — the tool loop never reads token counts; only `ClaudeCodeDispatcher._extract_result_usage` (claude.py:625) reports any
- ~~An LLM in the PR-creation path~~ — `_build_title`/`_build_body` are pure string templates (`feature_handoff.py:507,511`; `deployment_handoff.py:474,479`)
- ~~`ResearchNode` accepting a generic dispatcher~~ — it is typed `dispatcher: ClaudeCodeDispatcher` (`nodes/research.py:142`) and hardcodes `ClaudeCodeDispatchProfile(subagent="sdd-research")` (line 283)
- ~~A `nova` entry in `catalog.BACKENDS`~~ — the tuple starts at `catalog.py:88` with no Bedrock backend
- ~~Chat Completions for Anthropic models on Bedrock~~ — the Opus 5 model card marks it **not supported**; only Converse / Invoke / Messages
- ~~Geo or global inference profiles for MiniMax M2.5 or GLM-5~~ — both cards say "Not supported" for each

---

## Parallelism Assessment

- **Internal parallelism**: Genuinely high. Three clusters barely touch:
  (a) the Bedrock translator + Nova profiles/dispatchers,
  (b) the usage-capture + `UsageReport` + renderers,
  (c) the pluggable research seat + Haiku PR enrichment.
  Cluster (b) is valuable on its own and does not depend on Nova existing.
- **Cross-feature independence**: Moderate risk. `catalog.py`, `agent_builder.py`,
  `models/base.py` and `code_review.py` are the same files touched by the
  in-flight `new-codereviewers` work, and `dispatchers/llm.py` is described by
  its own sibling module as "hot, actively-churning". `models/bedrock_models.py`
  and `clients/nova/client.py` overlap `novaclient-amazon-aws`.
- **Recommended isolation**: `per-spec`
- **Rationale**: Although the three clusters are internally parallel, they
  converge on the same handful of shared registration points
  (`DevAgentBackend`, `build_dispatcher`, `catalog.BACKENDS`,
  `dispatchers/__init__.py`). Splitting them across worktrees would buy modest
  wall-clock and cost repeated three-way merges in the most contended files in
  the package. Sequential tasks in one worktree is the better trade.

---

## Open Questions

- [ ] **Q1 — The base branch does not currently contain the split.** [R3] chose
      "assume it's already committed", but as of this brainstorm
      `dev_loop/models/` and `dev_loop/dispatchers/` are **untracked**, the old
      `models.py`/`dispatcher.py` show as **deleted**, and `models_new/`,
      `dispatchers_new/`, `models.py.bak`, `dispatcher.py.bak` are stray. A
      worktree cut from `dev` HEAD would contain none of the modules this
      feature extends, so `/sdd-start` would fail immediately. Committing the
      split (and removing the strays) is a hard precondition. Who does it, and
      when? — *Owner: Jesus Lara*
- [ ] **Q2 — Revisit the Round 2 transport decision.** Round 2 selected the
      client-side Converse↔OpenAI adapter (Option B). The AWS model cards read
      afterwards show that (i) `bedrock-mantle` already serves MiniMax/GLM-5
      over OpenAI Chat Completions, and (ii) Anthropic models on Bedrock do not
      support Chat Completions at all — so the adapter would serve no seat in
      the configured setup. Option A is recommended instead. Confirm the switch,
      or keep Option B for the future ability to put a tool-using Claude model
      in the development seat? — *Owner: Jesus Lara*
- [ ] **Q3 — What does the Nova research seat actually produce?** `/sdd-spec`
      and `/sdd-task` are Claude Code slash commands; a Bedrock API seat cannot
      invoke them. Should the nova research path (a) emit triage + `ResearchOutput`
      only and fail loudly if scaffolding is required, or (b) be gated to
      feature-mode runs where the spec already exists? — *Owner: Jesus Lara*
- [ ] **Q4 — Two model ids remain unverified.** `moonshotai.kimi-k2.5` and
      `anthropic.claude-fable-5` could not be confirmed against an AWS model
      card (the Kimi card URL did not resolve). Ship them as warn-and-passthrough
      entries, or omit them from the curated list until confirmed? Also: the
      original request mentioned "Claude Opus 5.8", for which no id was supplied
      — drop it? — *Owner: Jesus Lara*
- [ ] **Q5 — Per-model output caps.** MiniMax M2.5 caps output at 8K while
      `LLMCodeDispatchProfile.max_tokens` allows up to 32768. Clamp silently
      with a warning, or reject the profile at construction time? — *Owner: Jesus Lara*
- [ ] **Q6 — Should the usage report cover non-Nova runs from day one?** Adding
      usage capture to `LLMCodeDispatcher` benefits nvidia/zai/moonshot/grok
      equally. Ship it loop-wide, or scope it to the nova path first? —
      *Owner: Jesus Lara*
