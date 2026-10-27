---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [guardrails, security, jailbreak, prompt-injection, prompt-leakage, onnx]
---

# Brainstorm: Agent Security Guardrails — Jailbreak, Tool-Output Injection, Prompt Leakage

**Date**: 2026-10-27
**Author**: Jesús Lara (brainstorm drafted with Claude Code)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot's guardrails infrastructure (FEAT-396) today enforces exactly one
security category with a real engine: **prompt injection on user INPUT**, via
`PromptInjectionGuardrail` backed by the Wolf Defender ONNX classifier
(`patronus-studio/wolf-defender-prompt-injection-small`, FEAT-439). For agents
deployed in higher-assurance environments we need the next three guardrail
categories as additional, independent security layers:

- **JAILBREAK** — attempts to override the agent's system instructions or
  bypass its operational boundaries (role-play exploits, DAN-style prompts,
  instruction-override framing). Today nothing classifies these distinctly:
  the injection model catches some, misses the rest, and there is no
  per-category policy or telemetry.
- **PROMPT_INJECTION beyond INPUT** — unintended instructions embedded in
  retrieved documents, tool outputs, or RAG chunks. The TOOL_OUTPUT pipeline
  seam exists (FEAT-396 Module 3) but only `SecretsGuardrail` runs there;
  a poisoned document reaches the agent loop unmarked.
- **PROMPT_LEAKAGE** — attempts to extract the system prompt or internal
  configuration (INPUT side), and actual reproduction of the system prompt in
  a response (OUTPUT side). Nothing detects either today.

Affected: every bot/agent exposed to untrusted users or untrusted retrieved
content; operators who need per-category security telemetry and blocking
policies.

## Constraints & Requirements

- **Follow the existing pattern**: each category is a pluggable `Guardrail`
  (FEAT-396) registered by name, configured via `guardrails=[...]`, with the
  `PromptInjectionGuardrail` policy shape (`strict_mode`, `block_on_threat`,
  probability threshold) and verdict semantics (default TRANSFORM/FLAG,
  BLOCK opt-in via `block_on_threat`).
- **No network on the request path**: ML engines are local ONNX classifiers
  with the FEAT-439 resolution chain (env dir → cached HF snapshot →
  fallback → heuristic floor) and an explicit `warmup_*` download function.
- **ES/EN mandatory with a false-positive gate**: every candidate model runs
  through the `benchmarks/injection_guardrail_latency/` harness (extended
  with jailbreak/leakage corpora) and must pass a Spanish-benign FP gate
  before becoming a default — the Wolf Defender precedent (DeBERTa produced
  7–8/10 Spanish FPs; wolf-defender 0/10).
- **Hybrid engines**: ML classifiers for jailbreak/injection; deterministic
  matching (n-grams + fuzzy) against the real system prompt for OUTPUT-side
  leakage — no classifier can know *our* prompt.
- **Zero behavior change by default**: bots that don't register the new
  guardrails behave bit-identically; TOOL_OUTPUT injection scanning is
  opt-in on the existing guardrail.
- **Telemetry never carries content** (FEAT-396 invariant): reports carry
  categories, scores, counts — never the offending text or the system prompt.
- Lazy imports: no ONNX/transformers import at module import time (FEAT-439
  discipline); registry factories stay lazy.

---

## Options Explored

### Option A: Per-category plugins on a shared ONNX-engine chassis (hybrid)

Three deliverables, mirroring how `PromptInjectionGuardrail` is built:

1. **`JailbreakGuardrail`** (INPUT, sanitizer band): its own ONNX engine —
   primary candidate **`0dinai/jailbreak-embeddings-base-onnx`** (0din /
   Mozilla threat-feed fine-tune of `intfloat/multilingual-e5-base`,
   ~278M params, 768-dim, multilingual XLM-R backbone, 512 max tokens;
   model card verified 2026-10-27). It is an **embedding-similarity
   detector, not a classifier**: the engine embeds the input (mean pooling
   + L2 norm, implemented app-side per the card) and scores it as the max
   cosine similarity against a **reference corpus of known jailbreak
   prompts** (card's optimal threshold ≈ 0.70). The corpus is a managed
   data asset — seeded from WildJailbreak + curated ES/EN attacks — so
   detection improves by *adding vectors*, no retraining. Alternative if
   the license or FP gate fails: a classifier head (Meta Prompt Guard 2
   86M, exported to ONNX ourselves via the existing `export.py` flow).
   Same resolution chain and its own `warmup_jailbreak_model()`; heuristic
   keyword/pattern floor when no model is available.
2. **Tool-output injection scanning**: extend `PromptInjectionGuardrail`
   with an opt-in `scan_tool_output=True` policy that adds
   `GuardrailStage.TOOL_OUTPUT` to its stages. On detection in a tool/RAG
   result: TRANSFORM — wrap the content in the existing untrusted-content
   markers (`_wrap_flagged_input`) + FLAG report; never BLOCK the turn for
   one poisoned document.
3. **`PromptLeakageGuardrail`** (INPUT + OUTPUT): INPUT side detects
   extraction attempts with deterministic patterns (reusing the
   `PromptInjectionDetector` regex machinery style); OUTPUT side runs
   deterministic leak detection — normalized word n-gram shingles of the
   rendered system prompt matched against the response, plus a fuzzy
   similarity pass to catch lightly edited copies. Optional canary-token
   policy (operator embeds a canary in the prompt; detection is exact).

To avoid triplicating the ~500 lines of engine-resolution/warmup machinery
in `prompt_injection.py`, the chassis (engine protocol, probe/build/resolve/
warmup functions) is factored into a shared private module parametrized by
env-var prefix, model id, and graph path, with **two engine shapes** behind
the same `score(text) -> [0,1]` protocol: the existing classifier engine
(softmax over logits) and a new embedding-similarity engine (embed → max
cosine vs a reference-corpus matrix). Both ML guardrails consume it.

✅ **Pros:**
- Maximum consistency with the existing, proven pattern — config, policy,
  telemetry, warmup, and ops story identical per category.
- Independent thresholds, models, and policies per category; categories can
  ship and be tuned independently.
- Deterministic leakage detection is cheap, explainable, and immune to the
  classifier-FP problem; zero ML on the OUTPUT hot path.
- The chassis refactor pays down existing tech debt in
  `prompt_injection.py` instead of copying it twice.

❌ **Cons:**
- Two ML models resident (injection + jailbreak) → more memory (0din base
  ONNX is ~1 GB fp32; the `large-onnx-int8` sibling trades size/speed) and
  one extra inference on INPUT at 512 tokens.
- The embedding approach adds a managed artifact: the reference attack
  corpus (sourcing, versioning, loading it next to the model).
- Benign-FP behavior of the 0din model is **untested** — it was trained and
  evaluated for *duplicate detection among attacks* (55-pair eval, authors
  call it directional), not benign-vs-attack discrimination; the ES/EN
  benign gate is load-bearing, not a formality.
- The chassis refactor touches the existing guardrail (regression-test
  burden; golden tests required).
- OUTPUT leakage needs the rendered system prompt plumbed into the
  guardrail context — a new wiring point in `AbstractBot`.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `onnxruntime>=1.16` | Jailbreak engine inference | already a core dep (pyproject:747) |
| `0dinai/jailbreak-embeddings-base-onnx` | Jailbreak embedding model, primary candidate | multilingual e5-base fine-tune (0din/Mozilla threat feed); ONNX at `onnx/model.onnx` + `tokenizer.json`; threshold ≈0.70; **NO license declared on either 0dinai repo (HF API checked 2026-10-27) — must be resolved before adoption**; single-turn only; ~1 GB fp32 |
| `0dinai/jailbreak-embeddings-large-onnx-int8` | Quantized sibling | e5-large int8 — benchmark against base for latency/size/accuracy |
| `allenai/wildjailbreak` | Seed dataset for the reference attack corpus | public (AI2); also check its license for redistribution of derived embeddings |
| `meta-llama/Llama-Prompt-Guard-2-86M` | Fallback classifier candidate | multilingual; Llama community license — verify; no official ONNX found, export via existing `export.py` flow; benchmark gate decides |
| `protectai/deberta-v3-base-prompt-injection-v2` | Comparison baseline | known 7–8/10 ES FPs — likely fails the gate |
| `rapidfuzz>=3.0` | Fuzzy leak matching | already pinned but **declared only in the `graphindex` extra** (pyproject:282, boundary test at :354); either move/add to core or use stdlib `difflib` — open question |

🔗 **Existing Code to Reuse:**
- `parrot/bots/guardrails/builtin/prompt_injection.py` — the whole engine
  chassis to factor out (`_OnnxInjectionEngine`:188, resolution chain
  :565/:618, `warmup_injection_model`:915) plus `_wrap_flagged_input`:836.
- `parrot/bots/guardrails/base.py` — `Guardrail` ABC, stages, verdicts.
- `parrot/bots/guardrails/registry.py` — lazy factory registration (:146-174).
- `parrot/security/prompt_injection.py` — `PromptInjectionDetector` (regex
  machinery, :102), `SecurityEventLogger` (:297), `ThreatLevel` (:14).
- `benchmarks/injection_guardrail_latency/` — corpus/harness/metrics/export
  to extend with jailbreak + leakage-attempt corpora.
- `tools/abstract.py:188-196` — TOOL_OUTPUT pipeline seam (already live).
- `bots/abstract.py:2758-2815` — OUTPUT pipeline seam incl. `extras` dict.

---

### Option B: One multi-category threat classifier, thin per-category guardrails

A single `ThreatClassifierEngine` runs ONE multi-label model (e.g. a
fine-tuned classifier emitting `{injection, jailbreak, benign}` scores) once
per INPUT; three thin guardrails read their category's score from a shared
per-request memo. Leakage OUTPUT stays deterministic as in Option A.

✅ **Pros:**
- One inference per turn regardless of how many categories are enabled —
  lowest INPUT latency and memory.
- One model to benchmark, cache, and warm up.

❌ **Cons:**
- Couples model choice across categories: upgrading the jailbreak detector
  means re-validating injection (and vice versa); no per-category model
  substitution.
- Few strong off-the-shelf multi-head models cover exactly these categories
  multilingually; likely requires fine-tuning — a model-training project,
  not a framework feature.
- Cross-guardrail shared-memo state breaks the "each guardrail is
  self-contained" FEAT-396 contract; pipeline has no per-request memo today.

📊 **Effort:** High (model work dominates)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `onnxruntime>=1.16` | inference | core dep |
| fine-tuned multi-label classifier | all categories | no validated off-the-shelf candidate; training pipeline out of scope for this repo |

🔗 **Existing Code to Reuse:** same chassis and seams as Option A.

---

### Option C: LLM-as-judge guardrails via AbstractClient

Each category is a guardrail that asks a small/fast LLM (through
`AbstractClient`, e.g. Haiku/Flash tier) to classify the content with a
structured verdict. No local models.

✅ **Pros:**
- Best accuracy on subtle/novel attacks and paraphrased leakage; trivially
  multilingual.
- No model distribution/warmup story; prompt-tunable without retraining.

❌ **Cons:**
- Adds a network LLM round-trip (~300–1500 ms) to every guarded turn —
  violates the "no network on the request path" constraint and doubles
  per-turn cost.
- The judge itself is injectable/jailbreakable (guarding the guard).
- Provider dependency for a security control; offline deployments lose all
  protection.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | uses existing `AbstractClient` providers | no new deps; per-request cost instead |

🔗 **Existing Code to Reuse:** `parrot/clients/base.py` (AbstractClient),
guardrails base/pipeline/registry as above.

---

### Option D (unconventional): Zero-new-model release — canary + shingles + ModerationBackend

Ship security value without any new ML: PROMPT_LEAKAGE entirely
deterministic (canary tokens + n-gram/fuzzy matching, as Option A);
JAILBREAK as a **`ModerationBackend`** implementation (the FEAT-396 Module 4
socket built exactly for this) backed by a curated multilingual
keyword/pattern ruleset, exposed as `ModerationGuardrail` category
`"jailbreak"`; TOOL_OUTPUT scanning reuses the existing injection engine
unchanged.

✅ **Pros:**
- Fastest to ship; zero model-licensing/benchmarking work; exercises the
  dormant moderation socket as designed.
- Deterministic = explainable verdicts, no FP-gate anxiety.

❌ **Cons:**
- Pattern-based jailbreak detection is weak against novel/obfuscated attacks
  — materially lower protection than a classifier; this is the capability
  the user explicitly asked to strengthen.
- Jailbreak-as-moderation-category gives it a different config surface than
  `prompt_injection` (inconsistent operator experience).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | stdlib + existing machinery only | |

🔗 **Existing Code to Reuse:** `builtin/moderation.py` (`ModerationPolicy`:33,
`ModerationBackend`:50, `ModerationGuardrail`:99) + Option A's leakage pieces.

---

## Recommendation

**Option A** is recommended (and matches the discovery-round decisions):

- It is the only option that satisfies all four of: parity with the current
  Wolf Defender pattern (explicit user requirement), per-category
  independence, no network on the request path, and real (ML-grade)
  jailbreak detection. Option B's single-model economy is attractive but
  stands on a model that doesn't exist off-the-shelf; Option C violates the
  latency/offline constraints for a security control; Option D under-delivers
  on jailbreak, the headline category.
- What we trade: one extra ONNX inference + resident model on INPUT
  (~1 GB fp32 for the 0din base model, or its int8 sibling), a managed
  reference-attack-corpus artifact, and a careful refactor of the engine
  chassis out of `prompt_injection.py`. All bounded and testable; the
  refactor is debt we would otherwise copy.
- Option D's canary-token idea is absorbed into Option A's leakage policy as
  an optional extra; Option D's heuristic ruleset becomes the jailbreak
  guardrail's no-model floor — so the fallback path still ships value.

---

## Feature Description

### User-Facing Behavior

- New registry names usable in the existing bot kwarg:
  `guardrails=["jailbreak", "prompt_leakage", {"name": "prompt_injection", "scan_tool_output": True}]`.
- Each new guardrail accepts the familiar policy shape:
  `strict_mode`, `block_on_threat`, and a category threshold
  (`jailbreak_probability_threshold`; leakage uses deterministic
  `ngram_size` / `similarity_threshold` / optional `canary` instead).
- Default posture mirrors `prompt_injection`: detections TRANSFORM (wrap as
  untrusted / annotate) and FLAG into
  `AIMessage.metadata["guardrails"][<name>]`; `block_on_threat=True`
  upgrades CRITICAL/HIGH detections to BLOCK with the existing canned
  response and selects `on_error="fail_closed"`.
- Ops: `warmup_jailbreak_model()` downloads/caches the jailbreak classifier
  at host startup (same contract as `warmup_injection_model()`); env vars
  `PARROT_JAILBREAK_ONNX_DIR` / `..._ONNX_MODEL` / `..._ONNX_GRAPH` mirror
  the injection ones. Telemetry events carry guardrail name, stage, action,
  score band, duration — never content.

### Internal Behavior

- **Shared chassis**: the engine protocol, ONNX engine (thread-capped ORT
  session, local-only tokenizer, id2label-resolved class index), snapshot
  probes, env-dir/cache builders, memoized resolver, and warmup downloader
  currently private to `builtin/prompt_injection.py` move to a shared
  private module parametrized by (env prefix, default model id, known graph
  paths, positive-label matcher). `prompt_injection.py` keeps its public
  surface (`warmup_injection_model`, back-compat attributes) delegating to
  the chassis; golden/behavioral tests pin compatibility.
- **`JailbreakGuardrail`** (`name="jailbreak"`, stages={INPUT}, priority 11 —
  runs right after `prompt_injection` in the sanitizer band): resolves its
  engine via the chassis (env dir → cached snapshot → heuristic floor).
  Primary engine shape is **embedding similarity** (0din model): embed the
  INPUT (ONNX backbone → mean pooling → L2 norm, per the model card) and
  score = max cosine similarity against the reference attack-corpus matrix
  (pre-embedded vectors loaded next to the model; default threshold ≈0.70,
  calibrated by the benchmark). Over-threshold ⇒ threat record →
  SecurityEventLogger → TRANSFORM-wrap (or BLOCK under `block_on_threat`).
  The corpus is a versioned data asset (seeded from WildJailbreak + curated
  ES/EN attacks); hardening against a new attack family = append vectors,
  no retrain. The model is single-turn — each INPUT is scored standalone.
  The heuristic floor is a curated multilingual pattern set
  (instruction-override, persona-switch, ignore-previous framings) shipped
  as data, not model.
- **Tool-output injection**: `PromptInjectionGuardrail` gains
  `scan_tool_output: bool = False`. When true, `stages` includes
  TOOL_OUTPUT; `check()` branches on `ctx.stage`: at TOOL_OUTPUT the verdict
  space is capped at TRANSFORM (wrap via `_wrap_flagged_input`) + FLAG —
  BLOCK is never returned for tool content regardless of `block_on_threat`
  (one poisoned RAG chunk must not kill the turn). The seam already passes
  `tool_name` in ctx (`tools/abstract.py:188-196`); reports land in
  `ToolResult.metadata["guardrails"]`.
- **`PromptLeakageGuardrail`** (`name="prompt_leakage"`, stages={INPUT,
  OUTPUT}, priority 12 on INPUT / observer band on OUTPUT):
  - INPUT: deterministic extraction-attempt patterns (multilingual:
    "repeat your instructions", "print everything above", role/system
    disclosure asks) → FLAG (TRANSFORM-wrap or BLOCK per policy).
  - OUTPUT: obtains the turn's rendered system prompt from
    `ctx.extras["system_prompt"]` (new: `_run_output_pipeline` populates it
    alongside the existing `ai_message` extra when a leakage guardrail is
    registered); normalizes both texts (casefold, whitespace/punct
    collapse); builds word n-gram shingles (default n=8) of the prompt and
    scans the response for shingle hits; on hit-density or fuzzy-similarity
    (partial-ratio over windows) ≥ threshold ⇒ leak. Verdict: TRANSFORM —
    replace the leaked spans with a redaction marker (or BLOCK per policy);
    FLAG report carries match statistics (counts/offsets), never the prompt
    text. Optional `canary: str` policy value is checked first (exact,
    normalized substring) and counts as CRITICAL.
- Registration: two new lazy factories in `registry.py`; no eager imports.
- Benchmarks: `benchmarks/injection_guardrail_latency/` gains a jailbreak
  corpus (ES/EN attacks + benign) and leakage-attempt corpus; the existing
  FP gate pattern applies before any model becomes the default.

### Edge Cases & Error Handling

- **No model available** (jailbreak): resolver returns the heuristic floor;
  loud log naming `warmup_jailbreak_model()`; guardrail stays functional.
- **Engine failure mid-request**: standard FEAT-396 error contract —
  `fail_open` logs + PASS unless `block_on_threat` selected `fail_closed`.
- **Streaming**: OUTPUT leakage runs on the final `AIMessage` only; chunks
  already streamed may have leaked before detection (v1 limitation, open
  question re: StreamingGuardrail withholding adapter).
- **Non-string outputs** (DataFrames/structured): OUTPUT pipeline already
  skips them (`abstract.py:2782`); leakage applies to text outputs only.
- **Short/empty system prompt**: below a minimum shingle count the OUTPUT
  check no-ops (a 5-word prompt would FP constantly on topic words).
- **Trusted-source bypass**: `ctx.extras["trusted_source"]` honored by all
  three, mirroring `prompt_injection` (agent-to-agent calls skip checks).
- **Double-wrap protection**: TOOL_OUTPUT wrap stamps content idempotently
  (FEAT-396 stamping precedent) so re-runs don't nest markers.
- **Legitimate quoting**: user asks "what can you do?" — answers describing
  capabilities in own words produce low shingle density; only near-verbatim
  reproduction crosses the threshold (threshold calibrated in benchmark).

---

## Capabilities

### New Capabilities
- `jailbreak-guardrail`: INPUT-stage ML jailbreak detection plugin with ONNX
  chassis, heuristic floor, warmup, and policy parity with prompt_injection.
- `prompt-leakage-guardrail`: INPUT extraction-attempt detection + OUTPUT
  deterministic system-prompt leak detection (shingles + fuzzy + canary).
- `guardrail-onnx-chassis`: shared, parametrized ONNX engine
  resolution/warmup machinery factored from the injection guardrail, with
  classifier and embedding-similarity engine shapes behind one
  `score(text) -> [0,1]` protocol.

### Modified Capabilities
- `guardrails-infrastructure` (FEAT-396 spec): registry gains `jailbreak` /
  `prompt_leakage` names; OUTPUT ctx extras gain `system_prompt`.
- `onnx-injection-guardrail-backend` (FEAT-439 spec): engine machinery
  relocated to the chassis (public surface unchanged);
  `PromptInjectionGuardrail` gains `scan_tool_output` + TOOL_OUTPUT stage.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/guardrails/builtin/prompt_injection.py` | modifies | engine chassis extracted; `scan_tool_output` policy + TOOL_OUTPUT stage; golden compat tests |
| `parrot/bots/guardrails/builtin/` (new `jailbreak.py`, `prompt_leakage.py`, shared chassis module) | extends | new plugins |
| `parrot/bots/guardrails/registry.py:146-174` | extends | two lazy factory registrations |
| `parrot/bots/abstract.py:2785-2799` (`_run_output_pipeline`) | modifies | add `system_prompt` to OUTPUT ctx extras (lazily, only when a registered guardrail needs it) |
| `parrot/security/prompt_injection.py` | depends on | pattern/logger machinery reused, unchanged |
| `benchmarks/injection_guardrail_latency/` | extends | jailbreak + leakage corpora, FP gates |
| `packages/ai-parrot/pyproject.toml` | maybe | rapidfuzz placement (core vs `difflib`) — open question; no other new deps |
| `docs/security/` | extends | ops docs per guardrail (mirrors `onnx-injection-guardrail.md`) |
| Bedrock/Google provider-native guardrails | unaffected | still out of scope (FEAT-396 non-goal) |

No breaking changes: nothing activates without explicit registration.

---

## Code Context

### User-Provided Code

(none — requirements given as prose; the three category definitions in the
request map to JAILBREAK / PROMPT_INJECTION / PROMPT_LEAKAGE as stated in
the Problem Statement.)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/guardrails/base.py
class GuardrailStage(str, Enum):  # :15 — INPUT/TOOL_OUTPUT/OUTPUT/OUTPUT_STREAM/TOOL_CALL (:25-29)
class GuardrailAction(str, Enum):  # :32 — PASS/TRANSFORM/FLAG/BLOCK
class GuardrailResult(BaseModel):  # :47 — action, content, report, reason
class GuardrailContext(BaseModel):  # :65 — stage, agent_name, user_id, session_id, method, tool_name, extras (:80-86)
class Guardrail(ABC):  # :97 — name, stages, priority, on_error (:119-122)
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:  # :125

# From packages/ai-parrot/src/parrot/bots/guardrails/registry.py
def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None:  # :41
def _make_lazy_factory(module_path: str, class_name: str) -> Callable[..., Guardrail]:  # :52
def build_guardrails(spec: list[str | dict[str, Any] | Guardrail]) -> list[Guardrail]:  # :95
# registered names: prompt_injection :146, secrets :150, moderation :154,
# groundedness :162, pbac :171; _RESERVED_NAMES = {"pii", "pseudonymize"} :35-38

# From packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
_DEFAULT_ONNX_MODEL_ID = "patronus-studio/wolf-defender-prompt-injection-small"  # :71
_ONNX_MAX_LENGTH = 512  # :103
class _OnnxInjectionEngine:  # :188 — thread-capped ORT session, local-only tokenizer
class _PytectorInjectionEngine:  # :258
def _do_resolve_injection_engine() -> _InjectionScoringEngine | None:  # :565
def _resolve_injection_engine(force_reresolve: bool = False):  # :618 — memoized, double-checked lock
class PromptInjectionGuardrail(Guardrail):  # :648
    name = "prompt_injection"  # :682
    stages: ClassVar[set] = {GuardrailStage.INPUT}  # :683 — INPUT ONLY today
    priority = 10  # :684 sanitizer band
    def _wrap_flagged_input(text: str, threats: list[dict[str, Any]]) -> str:  # :836 (static)
async def warmup_injection_model(force_download: bool = False) -> str:  # :915 — only download site

# From packages/ai-parrot/src/parrot/bots/guardrails/builtin/moderation.py
class ModerationPolicy(BaseModel):  # :33 — categories, threshold, action flag|block
class ModerationBackend(Protocol):  # :50 — async classify(text) -> dict[str, float]
class ModerationGuardrail(Guardrail):  # :99 — INPUT+OUTPUT reference plugin

# From packages/ai-parrot/src/parrot/security/prompt_injection.py
class ThreatLevel(Enum):  # :14
def max_threat_level(...):  # :62 (total-ordering fix, FEAT-714)
class PromptInjectionDetector:  # :102 — regex/keyword engine + framework-pattern stripping
class SecurityEventLogger:  # :297

# From packages/ai-parrot/src/parrot/bots/abstract.py
self._guardrail_pipelines: Dict[GuardrailStage, GuardrailPipeline] = build_pipelines_from_config(...)  # :693
# GroundednessGuardrail added directly at bot wiring  # :753 (precedent for wiring with bot state)
self.tool_manager._tool_output_pipeline = self._guardrail_pipelines[GuardrailStage.TOOL_OUTPUT]  # :769
# INPUT pipeline run  # :2756
async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage:  # :2758
# OUTPUT ctx extras = {"chatbot_id": ..., "ai_message": response}  # :2798 — NO system_prompt today
# non-string outputs skipped  # :2782
def system_prompt(self) -> str:  # :1126 property (template, not rendered)
async def create_system_prompt(  # :3679
```

#### Verified Imports
```python
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)  # used by builtin/prompt_injection.py imports (verified)
from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel, max_threat_level,
)  # verified at builtin/prompt_injection.py imports
from parrot.bots.guardrails.registry import register_guardrail  # registry.py:41
```

#### Key Attributes & Constants
- TOOL_OUTPUT seam builds `GuardrailContext(stage=TOOL_OUTPUT, agent_name=tool_name, tool_name=tool_name)` → `packages/ai-parrot/src/parrot/tools/abstract.py:188-196`; BLOCK there yields `"[content removed by guardrail: <reason>]"`.
- Env vars precedent: `PARROT_INJECTION_ONNX_DIR` / `PARROT_INJECTION_ONNX_MODEL` / `PARROT_INJECTION_ONNX_GRAPH`, `PARROT_INJECTION_ORT_INTRA_OP_THREADS` (prompt_injection.py).
- `rapidfuzz>=3.0` → `packages/ai-parrot/pyproject.toml:282` — **declared only in the `graphindex` extra**; dependency-boundary test referenced at pyproject:354 (`test_dependency_boundary.py`).
- `onnxruntime>=1.16` core dep → `packages/ai-parrot/pyproject.toml:747`.
- Benchmark harness: `benchmarks/injection_guardrail_latency/{compare_models.py, corpus.py, detectors.py, harness.py, metrics.py, export.py, README.md}` (listing verified).

### Does NOT Exist (Anti-Hallucination)
- ~~`JailbreakGuardrail` / `PromptLeakageGuardrail`~~ — no jailbreak or
  leakage guardrail code anywhere under `parrot/bots/guardrails/` or
  `parrot/security/`.
- ~~registry names `"jailbreak"` / `"prompt_leakage"`~~ — not registered,
  not reserved (`_RESERVED_NAMES` holds only `pii`, `pseudonymize`).
- ~~a shared/parametrized ONNX engine chassis module~~ — the machinery lives
  private inside `builtin/prompt_injection.py` only; the chassis is NEW.
- ~~`system_prompt` in OUTPUT `GuardrailContext.extras`~~ — extras carry
  only `chatbot_id` + `ai_message` (`abstract.py:2798`).
- ~~a rendered-system-prompt cache per turn~~ — `system_prompt` property
  (`abstract.py:1126`) returns the *template*; rendering happens in
  `create_system_prompt` (`:3679`) per call; no stored rendered artifact.
- ~~`warmup_jailbreak_model`~~, ~~`PARROT_JAILBREAK_*` env vars~~ — new.
- ~~jailbreak/leakage corpora in `benchmarks/injection_guardrail_latency/`~~.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. The chassis extraction (touching
  `prompt_injection.py`) is a load-bearing first module and must be
  sequential. After it: `JailbreakGuardrail` ∥ `PromptLeakageGuardrail` ∥
  benchmark-corpus work are disjoint files. The `scan_tool_output`
  extension depends on the chassis module (same file).
- **Cross-feature independence**: no in-flight spec touches
  `bots/guardrails/` (FEAT-396/398/406/439 are merged); the
  `_run_output_pipeline` edit in `bots/abstract.py` is small but that file
  is hot — coordinate landing windows.
- **Recommended isolation**: mixed — chassis module sequential first, then
  per-plugin parallel tasks in the same feature worktree.
- **Rationale**: the chassis is the only shared mutable surface; everything
  downstream is additive new files plus one registry touch each.

---

## Open Questions

- [ ] **0din model license**: neither `0dinai/jailbreak-embeddings-base-onnx`
  nor `...-large-onnx-int8` declares ANY license (HF API verified
  2026-10-27). Base model `intfloat/multilingual-e5-base` is MIT, but the
  fine-tune's terms are unstated — contact 0din (Mozilla) or treat as
  unusable until clarified. Fallback: Prompt Guard 2 86M (Llama community
  license, also to verify; no official ONNX — we export ourselves). —
  *Owner: Jesús*
- [ ] **Benign FP behavior of the 0din model**: trained/evaluated only for
  duplicate detection among attacks (55-pair eval, "directional"); whether
  benign ES/EN prompts stay under the 0.70 similarity band vs the attack
  corpus is unknown — the extended benchmark gate decides, and base vs
  large-int8 variant is picked there too. — *Owner: Jesús*
- [ ] **Reference attack corpus**: sourcing (WildJailbreak license for
  derived embeddings? curated internal set?), size budget, where it ships
  (package data vs HF dataset vs env dir), and update cadence. —
  *Owner: Jesús*
- [ ] Fuzzy matcher for leakage: add `rapidfuzz` to core deps (touches
  `test_dependency_boundary.py`) vs stdlib `difflib.SequenceMatcher`
  (slower, zero deps)? — *Owner: Jesús*
- [ ] Which system-prompt artifact does OUTPUT leakage compare against: the
  static template (`system_prompt` property) or the per-turn rendered
  prompt (incl. skills/tenant layers)? Rendered is more correct but needs a
  per-turn cache or re-render at OUTPUT time. — *Owner: Jesús*
- [ ] Streaming leakage: accept v1 limitation (final-message check only —
  leaked chunks already streamed) or invest in a `StreamingGuardrail`
  withholding adapter? — *Owner: Jesús*
- [ ] Confirm `scan_tool_output` default-off (opt-in) for the compat
  invariant, and whether per-tool opt-out is needed (e.g. skip scanning
  trusted internal tools). — *Owner: Jesús*
- [ ] Canary-token support in v1 (`canary` policy key, operator-managed) or
  follow-up? Auto-injection into the prompt is explicitly out of scope
  either way. — *Owner: Jesús*
- [ ] INPUT-side leakage (extraction attempts): heuristics-only in v1, or
  also consult the jailbreak model's score (extraction attempts often
  classify as jailbreak)? — *Owner: Jesús*
- [ ] Priority ordering within the sanitizer band (injection 10 → jailbreak
  11 → leakage 12): confirm, and decide whether a combined "security"
  convenience preset (`guardrails=["security"]`) is worth adding. —
  *Owner: Jesús*
