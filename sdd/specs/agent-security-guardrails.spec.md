---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [guardrails, security, jailbreak, prompt-injection, prompt-leakage, onnx]
---

# Feature Specification: Agent Security Guardrails — Jailbreak, Tool-Output Injection, Prompt Leakage

**Feature ID**: FEAT-761
**Date**: 2026-10-27
**Author**: Jesús Lara (spec drafted with Claude Code)
**Status**: approved
**Target version**: 1.3.0

> Source brainstorm: `sdd/proposals/agent-security-guardrails.brainstorm.md`
> (Recommended Option A, accepted). Extends the FEAT-396 guardrails
> infrastructure and the FEAT-439 ONNX engine pattern.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's guardrails infrastructure (FEAT-396) enforces exactly one
security category with a real engine: **prompt injection on user INPUT**,
via `PromptInjectionGuardrail` backed by the Wolf Defender ONNX classifier
(FEAT-439). Agents deployed in higher-assurance environments need the next
three categories as additional, independent security layers:

- **JAILBREAK** — attempts to override the agent's system instructions or
  bypass its operational boundaries (role-play exploits, DAN-style prompts,
  instruction-override framing). Nothing classifies these distinctly today.
- **PROMPT_INJECTION beyond INPUT** — unintended instructions embedded in
  retrieved documents, tool outputs, or RAG chunks. The TOOL_OUTPUT seam
  exists but only `SecretsGuardrail` runs there — and retrieved vector
  content bypasses the pipeline entirely (`_build_vector_context` →
  `<documents>` block, `bots/abstract.py:1493`).
- **PROMPT_LEAKAGE** — attempts to extract the system prompt or internal
  configuration (INPUT), and actual reproduction of the system prompt in a
  response (OUTPUT). Nothing detects either today.

### Goals

- Each category is a pluggable `Guardrail` registered by name, configured
  via `guardrails=[...]`, with the `prompt_injection` policy shape
  (`strict_mode`, `block_on_threat`, threshold) and verdict semantics:
  default TRANSFORM/FLAG, BLOCK opt-in via `block_on_threat` (which also
  selects `on_error="fail_closed"`).
- No network on the request path: ML engines are local ONNX artifacts with
  the FEAT-439 resolution chain (env dir → cached HF snapshot → fallback →
  heuristic floor) and explicit `warmup_*` download functions.
- **Mandatory jailbreak model bake-off** (hard, reproducible gate): no
  default model is pinned until a candidate passes latency + ES/EN accuracy
  + the Spanish-benign FP gate — the process that selected Wolf Defender.
- Hybrid engines: ML for jailbreak; deterministic matching (shingles +
  fuzzy + canary) against the real rendered system prompt for OUTPUT
  leakage.
- Zero behavior change by default; TOOL_OUTPUT/retrieval injection scanning
  is opt-in (`scan_tool_output=False`).
- Telemetry and security events never carry content — including closing the
  existing `SecurityEventLogger` content-leak path for leakage events.
- Lazy imports throughout (FEAT-439 discipline); registry factories stay
  lazy.

### Non-Goals (explicitly out of scope)

- Concrete moderation backends, provider-native guardrail wrappers
  (Bedrock/Google) — unchanged FEAT-396 non-goals.
- Automatic canary injection into prompts (operator embeds the canary).
- Streaming leakage withholding (`StreamingGuardrail` buffering adapter) —
  v1 checks the final message only; follow-up.
- DLP output classification (`patronus-studio/orca-sonar-document-classifier`)
  — explicit follow-up feature per the brainstorm.
- Multi-turn jailbreak scoring — all engines score single inputs.
- LLM-as-judge guardrails — rejected in brainstorm (Option C: network on
  the request path).

---

## 2. Architectural Design

### Overview

Three new security layers built on FEAT-396, plus the core extensions they
need:

1. **Pipeline core extensions**: `GuardrailResult.report` is surfaced for
   EVERY action (today `pipeline.py:193-197` drops a TRANSFORM's report —
   but TOOL_OUTPUT wrapping needs TRANSFORM + FLAG report); `priority`
   accepts a per-stage mapping (`int | dict[GuardrailStage, int]`) because
   leakage is a sanitizer on INPUT but an observer on OUTPUT, and scalar
   priority already collides (secrets and prompt_injection are both 10).
2. **Engine chassis**: the ~500 lines of engine machinery private to
   `builtin/prompt_injection.py` are factored into a shared module driven
   by an `EngineSpec` descriptor (env prefix, model id, known graph paths,
   engine kind, positive-label matcher), with two backends behind one
   `score(text) -> float` protocol: **classifier** (softmax over logits —
   the existing shape, moved) and **embedding similarity** (embed → mean
   pool → L2 norm → max cosine vs a reference-corpus matrix). `score()` is
   offloaded via `asyncio.to_thread` from async `check()` (today it blocks
   the event loop, `prompt_injection.py:779`); ORT thread caps are kept.
   `prompt_injection.py` keeps its full public surface and behavior
   (golden tests).
3. **`JailbreakGuardrail`** (`name="jailbreak"`, INPUT, priority 11): scores
   via its chassis-resolved engine (`PARROT_JAILBREAK_*` env vars,
   `warmup_jailbreak_model()`); default model = bake-off winner; heuristic
   multilingual pattern floor when no model resolves. Policy:
   `strict_mode`, `block_on_threat`, `jailbreak_probability_threshold`.
4. **Tool-output + retrieval injection**: `PromptInjectionGuardrail` gains
   `scan_tool_output: bool = False` (global, no per-tool opt-out in v1).
   When true it adds TOOL_OUTPUT to its stages; at that stage the verdict
   space is capped at TRANSFORM (`_wrap_flagged_input` markers) + report —
   never BLOCK for tool content. Retrieved vector chunks get the same
   protection: `_build_vector_context` routes each chunk through the
   TOOL_OUTPUT pipeline (`tool_name="vector_retrieval"`) before assembly
   into `<documents>`.
5. **`PromptLeakageGuardrail`** (`name="prompt_leakage"`, INPUT + OUTPUT;
   priority INPUT 12 / OUTPUT 220 observer band): INPUT side runs
   deterministic multilingual extraction-attempt patterns; OUTPUT side runs
   deterministic leak detection against the **turn's rendered system
   prompt**: normalized word n-gram shingles (default n=8, minimum shingle
   count floor) + rapidfuzz windowed partial-ratio for lightly edited
   copies + optional `canary` policy key (exact normalized substring ⇒
   CRITICAL). Verdict: TRANSFORM (redact leaked spans) or BLOCK per
   policy; reports carry match statistics only, never prompt text.
6. **Rendered-prompt capture**: the bot captures the exact system prompt
   produced by `create_system_prompt()` at each invoke/ask/ask_stream seam
   into a per-turn attribute, and `_run_output_pipeline` passes it as
   `ctx.extras["system_prompt"]` alongside the existing `ai_message` —
   never re-rendered at OUTPUT time (re-rendering would compare against a
   different artifact than the LLM saw).
7. **Config sugar**: registry preset `"security"` expands to
   `prompt_injection + jailbreak + prompt_leakage` with defaults.
8. **Content-free security events**: `SecurityEventLogger` gains a
   content-free logging path (category, severity, score, counts, bounded
   metadata — no `matched_text`/`original_input`/`sanitized_input`);
   leakage and jailbreak events MUST use it.

Resolved user decisions folded in (see §8): rapidfuzz becomes a core
dependency (deliberate `test_dependency_boundary.py` update); rendered
per-turn prompt (not the template) is the leakage reference; canary ships
in v1; INPUT leakage is heuristics-only in v1; streaming v1 limitation
accepted and marked in reports (`stream_checked: "final_only"`);
`scan_tool_output` defaults off; priorities 10/11/12 confirmed; the
`security` preset ships in v1.

### Component Diagram

```
                      guardrails=["security"] | legacy flags
                                    │ registry (lazy factories)
            ┌───────────────────────┼─────────────────────────────┐
 user input ▼                       ▼                             ▼
 ── INPUT ──► [prompt_injection(10) → jailbreak(11) → prompt_leakage(12, heuristics)]
                                    │ engines via chassis
                 ┌──────────────────┴──────────────────┐
                 │ _engine_chassis.EngineSpec           │
                 │  ├ ClassifierOnnxEngine (softmax)    │  score() in to_thread
                 │  └ EmbeddingSimilarityEngine (corpus)│
                 └──────────────────────────────────────┘
 tool result ──── TOOL_OUTPUT ──► [secrets(10) → prompt_injection(scan_tool_output)]
 RAG chunk ──────(same pipeline, tool_name="vector_retrieval")──► <documents>
 final answer ─── OUTPUT ──► [secrets → prompt_leakage(220): shingles+fuzzy+canary
                              vs ctx.extras["system_prompt"] (captured per turn)]
                 BLOCK → canned AIMessage · reports → metadata["guardrails"]
                 telemetry + SecurityEventLogger: content-free payloads only
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `bots/guardrails/base.py:121` (`priority: int`) | modifies | per-stage priority `int \| dict[GuardrailStage, int]`; scalar stays valid |
| `bots/guardrails/pipeline.py:190-197` | modifies | surface `result.report` for TRANSFORM (and PASS) too; stage-aware priority sort |
| `bots/guardrails/builtin/prompt_injection.py` | modifies | engine machinery delegated to chassis; `scan_tool_output` + TOOL_OUTPUT stage branch; async score offload; public surface unchanged |
| `bots/guardrails/registry.py:171-174` | extends | lazy factories `jailbreak`, `prompt_leakage`; `security` preset |
| `bots/abstract.py:2798` (`_run_output_pipeline` extras) | modifies | adds `"system_prompt"` from the per-turn captured artifact |
| `bots/abstract.py:3679` (`create_system_prompt`) call seams | modifies | capture rendered prompt per turn (no re-render at OUTPUT) |
| `bots/abstract.py:1493` (`vector_context` → `<documents>`) | modifies | chunk scan through TOOL_OUTPUT pipeline when `scan_tool_output` |
| `security/prompt_injection.py:306` (`log_injection_attempt`) | extends | sibling content-free event method; existing method untouched |
| `tools/abstract.py:188-196` (TOOL_OUTPUT seam) | uses | unchanged — pipeline fix (S1) makes TRANSFORM reports flow to `ToolResult.metadata["guardrails"]` |
| `benchmarks/injection_guardrail_latency/` | extends | jailbreak + leakage corpora, embedding detector, threshold sweep, manifest, FP gate |
| `packages/ai-parrot/pyproject.toml:282` (rapidfuzz) | modifies | rapidfuzz joins core deps; boundary test updated deliberately |

No breaking changes: nothing activates without explicit registration;
default-config behavior is bit-identical (golden/compat tests).

### Data Models

```python
# parrot/bots/guardrails/builtin/_engine_chassis.py — design signatures
@dataclass(frozen=True)
class EngineSpec:
    category: str                      # "injection" | "jailbreak"
    env_prefix: str                    # "PARROT_INJECTION" | "PARROT_JAILBREAK"
    default_model_id: str
    known_graph_paths: dict[str, str]
    kind: Literal["classifier", "embedding"]
    positive_label_match: str = "inject"   # id2label matcher (classifier)
    reference_corpus: Path | None = None   # embedding kind only

class ScoringEngine(Protocol):
    engine_name: str
    model_id: str
    def score(self, text: str) -> float: ...   # sync; callers offload

# parrot/bots/guardrails/builtin/prompt_leakage.py
class LeakagePolicy(BaseModel):
    ngram_size: int = 8
    min_prompt_shingles: int = 12          # below → OUTPUT check no-ops
    shingle_hit_threshold: float = 0.12    # hit density ⇒ leak
    fuzzy_threshold: int = 85              # rapidfuzz partial_ratio 0-100
    canary: str | None = None              # exact normalized match ⇒ CRITICAL
    block_on_threat: bool = False
    strict_mode: bool = True
```

### New Public Interfaces

```python
from parrot.bots.guardrails.builtin.jailbreak import (
    JailbreakGuardrail, warmup_jailbreak_model,
)
from parrot.bots.guardrails.builtin.prompt_leakage import PromptLeakageGuardrail

# registry names: "jailbreak", "prompt_leakage", preset "security"
Agent(guardrails=["security"])
Agent(guardrails=[{"name": "prompt_injection", "scan_tool_output": True},
                  {"name": "jailbreak", "block_on_threat": True},
                  {"name": "prompt_leakage", "canary": "K-7f3a"}])
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: pipeline-core-extensions | yes | signatures fixed below; scalar-compat rule stated; tests enumerated | — |
| M2: engine-chassis | yes | move-only refactor + `EngineSpec`/backends contract fixed; golden tests pin behavior | — |
| M3: jailbreak-bakeoff | no | — | corpus curation, threshold selection and license verdicts are judgment calls |
| M4: jailbreak-guardrail | yes | mirrors PromptInjectionGuardrail shape 1:1; env prefix + policy fixed | — |
| M5: tool-output-retrieval-injection | yes | stage-branch semantics and seam fixed | — |
| M6: prompt-leakage-guardrail | yes | matcher algorithm, policy model and content-free event contract fixed | — |
| M7: bot-wiring-and-preset | yes | capture point, extras key, preset expansion fixed | — |

### Module 1: pipeline-core-extensions
- **Path**: `parrot/bots/guardrails/base.py`, `parrot/bots/guardrails/pipeline.py`
- **Responsibility**: (a) reports orthogonal to actions — the pipeline
  collects `result.report` under the guardrail's name for TRANSFORM (and
  PASS) exactly as it already does for FLAG/BLOCK; (b) per-stage priority:
  `priority: int | dict[GuardrailStage, int]` with a resolver used by the
  pipeline sort; scalar means "same in every stage" (full back-compat).
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # modifies parrot/bots/guardrails/base.py:121
  class Guardrail(ABC):  # verified: base.py:97
      priority: int | dict[GuardrailStage, int]
      def priority_for(self, stage: GuardrailStage) -> int:
          """Resolve effective priority for ``stage`` (scalar passes through)."""

  # modifies parrot/bots/guardrails/pipeline.py:193
  # TRANSFORM branch also does: flag_reports[guardrail.name] = result.report (when set)
  # sort key becomes guardrail.priority_for(ctx.stage)
  ```

### Module 2: engine-chassis
- **Path**: `parrot/bots/guardrails/builtin/_engine_chassis.py` (new),
  `parrot/bots/guardrails/builtin/prompt_injection.py` (delegates)
- **Responsibility**: relocate `_OnnxInjectionEngine` (→
  `ClassifierOnnxEngine`), `_softmax`, `_load_tokenizer`,
  `_resolve_injection_index`, the snapshot probes, env-dir/cache builders,
  memoized resolver and warmup downloader into the chassis, parametrized by
  `EngineSpec`; add `EmbeddingSimilarityEngine` (tokenize → ONNX backbone →
  mean pool → L2 norm → max cosine vs a pre-embedded corpus matrix loaded
  from `reference_corpus`); per-category memoization (one resolved engine
  per `EngineSpec.category`); `async def score_async()` helper wrapping
  `score()` in `asyncio.to_thread`; `check()` call sites use it.
  `prompt_injection.py` keeps `warmup_injection_model`, env var names,
  back-compat attributes and log lines bit-identically (golden tests).
- **Depends on**: nothing new (parallel with M1).
- **Interface Skeleton**:
  ```python
  # parrot/bots/guardrails/builtin/_engine_chassis.py (new)
  class ClassifierOnnxEngine:   # body moved from prompt_injection.py:188
      def __init__(self, tokenizer_dir: Path, graph_path: Path, model_id: str,
                   positive_label_match: str = "inject") -> None: ...
      def score(self, text: str) -> float: ...

  class EmbeddingSimilarityEngine:
      """ONNX embedding backbone + reference-corpus max-cosine scoring."""
      def __init__(self, tokenizer_dir: Path, graph_path: Path, model_id: str,
                   corpus_matrix: "np.ndarray") -> None: ...
      def score(self, text: str) -> float: ...

  def resolve_engine(spec: EngineSpec, force_reresolve: bool = False) -> ScoringEngine | None:
      """Memoized per-category resolution: env dir -> cached snapshot -> None."""
  async def score_async(engine: ScoringEngine, text: str) -> float:
      """Run ``engine.score`` in a worker thread (never on the event loop)."""
  async def warmup_model(spec: EngineSpec, force_download: bool = False) -> str:
      """The only download site for ``spec``'s artifacts."""
  ```

### Module 3: jailbreak-bakeoff
- **Path**: `benchmarks/injection_guardrail_latency/` (`corpus.py`,
  `detectors.py`, `compare_models.py`, new `manifest.py` or JSON outputs),
  results committed under `benchmarks/injection_guardrail_latency/results-jailbreak/`
- **Responsibility**: reproducible hard gate (design-research S9/S10):
  per-category ES/EN corpora (jailbreak attacks, benign incl. the Spanish
  set, leakage-attempt prompts), an embedding-similarity detector wrapper,
  threshold-selection sweep, p50/p95 latency, startup time + resident
  memory, Spanish-benign FP minimum (gate: 0 FP on the benign-ES bucket at
  the selected threshold), a **Spanish ATTACK recall bucket** (the
  shortlist's EN-only fine-tunes risk ES misses, not FPs), and a
  **candidate manifest** (model id, HF revision, sha256, license, verdict).
  **Default-eligible shortlist and pre-registered decision rule are fixed
  in §8 (resolved)**: vllm-sr mmbert32k (apache-2.0) · madhurjindal Large
  (MIT, own export) · gravitee Prompt Guard 2 86M **fp32 only** (llama4,
  conditional attribution; int8 excluded — its own eval shows F1
  0.98→0.89) · enguard potion (MIT); 0din and NC-licensed models excluded;
  winner = highest combined ES+EN F1 s.t. 0 ES-benign FPs and p50 ≤ 30 ms
  CPU @ 512 tokens, ties → permissive license, then size. 0din embeddings
  may still be *measured* (local eval) to inform any future licensing
  conversation, flagged non-eligible in the manifest. Output: pinned
  winner + threshold for M4.
- **Depends on**: M2's detector shapes (benchmark wrapper mirrors them);
  can start concurrently using the model card contracts.

### Module 4: jailbreak-guardrail
- **Path**: `parrot/bots/guardrails/builtin/jailbreak.py` (new),
  `parrot/bots/guardrails/registry.py` (register)
- **Responsibility**: INPUT guardrail mirroring `PromptInjectionGuardrail`'s
  flow (trusted-source bypass → strict_mode gate → engine score via
  `score_async` → threshold → SecurityEventLogger (content-free) →
  TRANSFORM-wrap / BLOCK per `block_on_threat`); `EngineSpec(category=
  "jailbreak", env_prefix="PARROT_JAILBREAK", kind=<bake-off winner>)`;
  heuristic multilingual pattern floor (instruction-override,
  persona-switch, ignore-previous framings — data-driven, ES/EN) when no
  engine resolves; `warmup_jailbreak_model()`.
- **Depends on**: M2 (chassis); M3 (default model + threshold pin — the
  constant, not the code).
- **Interface Skeleton**:
  ```python
  # parrot/bots/guardrails/builtin/jailbreak.py (new)
  class JailbreakGuardrail(Guardrail):  # Guardrail verified: base.py:97
      name = "jailbreak"
      stages: ClassVar[set] = {GuardrailStage.INPUT}
      priority = 11
      def __init__(self, strict_mode: bool = True, block_on_threat: bool = False,
                   jailbreak_probability_threshold: float = <bake-off>, **kwargs: Any) -> None: ...
      async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...

  async def warmup_jailbreak_model(force_download: bool = False) -> str: ...
  ```

### Module 5: tool-output-retrieval-injection
- **Path**: `parrot/bots/guardrails/builtin/prompt_injection.py`,
  `parrot/bots/abstract.py` (retrieval seam)
- **Responsibility**: `scan_tool_output: bool = False` policy on
  `PromptInjectionGuardrail`; when True, `stages` includes
  `GuardrailStage.TOOL_OUTPUT` and `check()` branches on `ctx.stage`: at
  TOOL_OUTPUT the verdict is capped at TRANSFORM (wrap via
  `_wrap_flagged_input`) + report — BLOCK is never returned for tool
  content regardless of `block_on_threat`; idempotent wrap stamping (no
  nested markers on re-run). Retrieval seam: when the bot's TOOL_OUTPUT
  pipeline has an injection scanner registered, `_build_vector_context`
  passes each retrieved chunk through it (`tool_name="vector_retrieval"`)
  before `<documents>` assembly.
- **Depends on**: M1 (TRANSFORM report surfacing), M2 (same-file ordering).
- **Interface Skeleton**:
  ```python
  # modifies parrot/bots/guardrails/builtin/prompt_injection.py:683
  class PromptInjectionGuardrail(Guardrail):
      def __init__(self, ..., scan_tool_output: bool = False, **kwargs: Any) -> None:
          """scan_tool_output=True adds TOOL_OUTPUT to ``stages`` (TRANSFORM+report only)."""
  # modifies parrot/bots/abstract.py near :1493 — chunk scan before <documents> assembly
  ```

### Module 6: prompt-leakage-guardrail
- **Path**: `parrot/bots/guardrails/builtin/prompt_leakage.py` (new),
  `parrot/security/prompt_injection.py` (content-free events),
  `packages/ai-parrot/pyproject.toml` + boundary test (rapidfuzz)
- **Responsibility**: INPUT: deterministic multilingual extraction-attempt
  patterns (ES/EN; "repeat your instructions", "print everything above",
  system-disclosure asks) → TRANSFORM-wrap / BLOCK per policy. OUTPUT:
  normalize both texts (casefold, whitespace/punctuation collapse); build
  word shingles (`ngram_size`) of `ctx.extras["system_prompt"]`; no-op
  below `min_prompt_shingles`; hit-density ≥ `shingle_hit_threshold` or
  windowed `rapidfuzz.fuzz.partial_ratio` ≥ `fuzzy_threshold` ⇒ leak;
  `canary` checked first (CRITICAL). TRANSFORM replaces leaked spans with
  `[redacted: system-prompt disclosure]`; report carries counts/offsets +
  `stream_checked: "final_only"` for `ask_stream`-originated turns — never
  prompt text. `SecurityEventLogger.log_security_category_event(...)`
  (new, content-free) used for all events. rapidfuzz moves to core deps;
  `test_dependency_boundary.py` updated in the same task.
- **Depends on**: M1 (per-stage priority), M7 for live OUTPUT data (tests
  inject extras directly, so code-parallel with M7).
- **Interface Skeleton**:
  ```python
  # parrot/bots/guardrails/builtin/prompt_leakage.py (new)
  class PromptLeakageGuardrail(Guardrail):  # Guardrail verified: base.py:97
      name = "prompt_leakage"
      stages: ClassVar[set] = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}
      priority = {GuardrailStage.INPUT: 12, GuardrailStage.OUTPUT: 220}
      def __init__(self, **policy: Any) -> None:
          """Accepts LeakagePolicy fields as kwargs (registry dict config)."""
      async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...

  # modifies parrot/security/prompt_injection.py:306 (sibling method, existing one untouched)
  class SecurityEventLogger:
      async def log_security_category_event(
          self, *, category: str, severity: "ThreatLevel", score: float | None,
          user_id: str | None, session_id: str | None, chatbot_id: str | None,
          counts: dict[str, int] | None = None,
      ) -> None:
          """Content-free security event: never carries input/output/prompt text."""
  ```

### Module 7: bot-wiring-and-preset
- **Path**: `parrot/bots/abstract.py`, `parrot/bots/guardrails/registry.py`,
  `docs/security/agent-security-guardrails.md` (new)
- **Responsibility**: capture the rendered system prompt at the
  invoke/ask/ask_stream seams (the value `create_system_prompt()` returned
  for THIS turn) into a per-turn holder; `_run_output_pipeline` adds
  `extras["system_prompt"]` only when an OUTPUT guardrail declares it needs
  it (attribute flag, mirroring `has_guardrails` zero-overhead discipline);
  registry preset `"security"` expanding to the three names with defaults;
  ops documentation (warmup, env vars, thresholds, streaming limitation).
- **Depends on**: M4, M6 (names it wires/documents).
- **Interface Skeleton**:
  ```python
  # modifies parrot/bots/abstract.py:2798
  extras={"chatbot_id": ..., "ai_message": response,
          "system_prompt": self._last_rendered_system_prompt}  # set at seam, never re-rendered
  # modifies parrot/bots/guardrails/registry.py:171-174 — after pbac registration:
  # register preset: build_guardrails(["security"]) -> [prompt_injection, jailbreak, prompt_leakage]
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_pipeline_transform_report_surfaced` | M1 | TRANSFORM result's `report` lands in `flag_reports` (tool seam + output seam) |
| `test_per_stage_priority_resolution` | M1 | scalar back-compat; dict resolves per stage; deterministic sort |
| `test_chassis_classifier_parity` | M2 | relocated classifier engine scores bit-identical to pre-refactor (golden corpus) |
| `test_chassis_embedding_engine` | M2 | mean-pool + L2 + max-cosine vs small fixture corpus; threshold behavior |
| `test_chassis_resolution_per_category` | M2 | injection and jailbreak resolve independently; memoized; env-dir precedence |
| `test_score_async_offload` | M2 | `score_async` runs off the event loop (thread id assertion) |
| `test_injection_guardrail_compat` | M2 | existing suite green, no behavior drift (golden) |
| `test_jailbreak_guardrail_policy` | M4 | threshold gate, TRANSFORM-wrap default, BLOCK + fail_closed under block_on_threat, trusted-source bypass |
| `test_jailbreak_heuristic_floor` | M4 | ES/EN pattern floor fires with no engine |
| `test_scan_tool_output_stage_cap` | M5 | TOOL_OUTPUT never BLOCKs; wrap + report; idempotent stamping |
| `test_vector_context_scanning` | M5 | poisoned chunk wrapped before `<documents>` assembly; off by default |
| `test_leakage_shingles_and_fuzzy` | M6 | verbatim leak, lightly-edited leak, benign paraphrase (no FP), short-prompt no-op |
| `test_leakage_canary_critical` | M6 | canary hit ⇒ CRITICAL, precedes shingles |
| `test_leakage_input_heuristics` | M6 | ES/EN extraction-attempt patterns |
| `test_leakage_report_content_free` | M6 | report/log payloads contain no prompt/response text |
| `test_security_event_content_free` | M6 | `log_security_category_event` never receives/logs content |
| `test_rendered_prompt_capture` | M7 | OUTPUT extras carry the same string the seam rendered; no re-render |
| `test_security_preset_expansion` | M7 | `["security"]` → the three guardrails with defaults |

### Integration Tests

| Test | Description |
|---|---|
| `test_ask_end_to_end_security_preset` | bot with `guardrails=["security"]`: jailbreak input blocked/wrapped per policy; leak in output redacted; reports in `metadata["guardrails"]` |
| `test_default_config_regression` | no guardrails kwarg ⇒ bit-identical behavior (existing suite subset) |
| `test_tool_output_injection_e2e` | tool returning injected content gets wrapped; turn completes |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/test_guardrails_pipeline.py
- packages/ai-parrot/tests/unit/test_guardrails_core_models.py
- packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py
- packages/ai-parrot/tests/unit/test_guardrails_input_migration.py
- packages/ai-parrot/tests/unit/test_guardrails_registry_config.py
- packages/ai-parrot/tests/unit/test_guardrails_secrets.py
- packages/ai-parrot/tests/integration/test_guardrails_output.py
- packages/ai-parrot/tests/integration/test_guardrails_injection_onnx.py
- packages/ai-parrot/tests/unit/test_guardrails_stage_priority_reports.py
- packages/ai-parrot/tests/unit/test_guardrails_security_preset.py
- packages/ai-parrot/tests/unit/test_guardrails_engine_chassis.py
- packages/ai-parrot/tests/unit/test_guardrails_engine_chassis_embedding.py
- packages/ai-parrot/tests/unit/test_security_category_events.py
- packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py
- packages/ai-parrot/tests/unit/test_guardrails_scan_tool_output.py
- packages/ai-parrot/tests/unit/test_guardrails_retrieval_scan.py
- packages/ai-parrot/tests/unit/test_guardrails_jailbreak.py
- packages/ai-parrot/tests/unit/test_guardrails_prompt_leakage.py
- packages/ai-parrot/tests/unit/test_guardrails_rendered_prompt.py
- packages/ai-parrot/tests/integration/test_security_guardrails_e2e.py
- tests/benchmarks/test_jailbreak_bakeoff_harness.py
- tests/benchmarks/test_jailbreak_bakeoff_manifest.py
- tests/benchmarks/test_injection_guardrail_metrics.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def golden_injection_cases(): ...   # pre-refactor scores/verdicts, pins M2 parity
@pytest.fixture
def jailbreak_corpus_es_en(): ...   # attacks + benign (incl. Spanish benign bucket)
@pytest.fixture
def rendered_prompt_fixture(): ...  # ~2KB prompt + leaking/benign responses
@pytest.fixture
def tiny_embedding_corpus(): ...    # 8-vector reference matrix for the embedding engine
```

### Performance

| Benchmark | Gate |
|---|---|
| Leakage OUTPUT deterministic pass (2 KB prompt, 4 KB response) | p99 < 5 ms CPU |
| Event-loop blocking during `check()` with ML engine (concurrent requests) | no `score()` on the loop thread; p99 added INPUT latency < 30 ms per enabled ML guardrail at 512 tokens |
| Empty/unregistered pipelines | zero overhead (existing FEAT-396 gate preserved) |

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit + integration tests pass; the pre-existing guardrails suite
      passes unchanged (compat invariant: default config bit-identical).
- [ ] **Bake-off gate**: committed results under
      `benchmarks/injection_guardrail_latency/results-jailbreak/` with
      per-candidate manifest (model id, revision, sha256, license,
      verdict), threshold sweep, p50/p95 latency, startup/memory, and
      **0 Spanish-benign false positives** at the selected threshold for
      the pinned default — no default model constant lands before this.
- [ ] A candidate without a verified license (0din today) is never pinned
      as default; shipped artifacts (corpus, vectors) carry provenance.
- [ ] `jailbreak` and `prompt_leakage` resolve via the registry by name and
      via the `security` preset; policy kwargs accepted through dict config.
- [ ] Verdict semantics: TRANSFORM/FLAG default; `block_on_threat=True` ⇒
      BLOCK (canned response, category-only reason) + `on_error=fail_closed`.
- [ ] TOOL_OUTPUT and vector-retrieval scanning: opt-in, TRANSFORM+report
      only (never BLOCK), idempotent wrapping; off by default.
- [ ] Leakage OUTPUT compares against the per-turn rendered system prompt
      passed via `ctx.extras["system_prompt"]`; no re-render at OUTPUT;
      canary ⇒ CRITICAL; `stream_checked: "final_only"` marked on
      streaming turns.
- [ ] TRANSFORM results' reports surface in `metadata["guardrails"]` /
      `ToolResult.metadata["guardrails"]` (pipeline S1 fix).
- [ ] Per-stage priority works with scalar back-compat; existing ordering
      unchanged for existing guardrails.
- [ ] No content in telemetry or security events for the new categories:
      reports and `log_security_category_event` carry categories, scores,
      counts, offsets only — audited by tests.
- [ ] `score()` never runs on the event loop in `check()` paths (M2
      offload); ORT thread caps preserved; perf gates (§4) met.
- [ ] rapidfuzz declared as a core dependency with
      `test_dependency_boundary.py` updated in the same change (deliberate).
- [ ] `warmup_jailbreak_model()` is the only jailbreak download site; env
      vars `PARROT_JAILBREAK_ONNX_DIR/_MODEL/_GRAPH` honored; heuristic
      floor functional with no model.
- [ ] Ops docs in `docs/security/` (mirrors `onnx-injection-guardrail.md`).
- [ ] Zero new runtime deps besides rapidfuzz; no breaking public-API changes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified on `dev` @ `4e3ba6289` (2026-10-27). Paths relative to repo root;
> `parrot/` paths are under `packages/ai-parrot/src/`.

### Verified Imports

```python
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)  # verified: used by builtin/prompt_injection.py imports
from parrot.bots.guardrails.registry import register_guardrail, build_guardrails
    # verified: registry.py:41 / :95
from parrot.security.prompt_injection import (
    PromptInjectionDetector,   # security/prompt_injection.py:102
    SecurityEventLogger,       # :297
    ThreatLevel,               # :14
    max_threat_level,          # :62
)
```

### Existing Class Signatures

```python
# parrot/bots/guardrails/base.py
class GuardrailStage(str, Enum):  # :15 — INPUT/TOOL_OUTPUT/OUTPUT/OUTPUT_STREAM/TOOL_CALL (:25-29)
class GuardrailAction(str, Enum):  # :32 — PASS/TRANSFORM/FLAG/BLOCK
class GuardrailResult(BaseModel):  # :47 — action, content, report, reason
class GuardrailContext(BaseModel):  # :65 — stage, agent_name, user_id, session_id, method, tool_name, extras (:80-86)
class Guardrail(ABC):  # :97 — name, stages, priority: int (:121), on_error (:122)
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:  # :125

# parrot/bots/guardrails/pipeline.py
class PipelineOutcome(BaseModel)  # :~67 — content, blocked, reason, flag_reports (:80)
# report collection: BLOCK :190-191, FLAG :197 — TRANSFORM (:193-196) drops report (S1 target)

# parrot/bots/guardrails/registry.py
def register_guardrail(name, factory)  # :41
def _make_lazy_factory(module_path, class_name)  # :52
def build_guardrails(spec)  # :95
# registered: prompt_injection :146, secrets :150, moderation :154, groundedness :162, pbac :171
# _RESERVED_NAMES = {"pii", "pseudonymize"}  # :35-38

# parrot/bots/guardrails/builtin/prompt_injection.py
_DEFAULT_ONNX_MODEL_ID = "patronus-studio/wolf-defender-prompt-injection-small"  # :71
_ONNX_MAX_LENGTH = 512  # :103
class _OnnxInjectionEngine:  # :188 — thread-capped ORT, local-only tokenizer, id2label index
class _PytectorInjectionEngine:  # :258
def _do_resolve_injection_engine()  # :565 — env dir → cached snapshot → pytector → None
def _resolve_injection_engine(force_reresolve=False)  # :618 — memoized, double-checked lock
class PromptInjectionGuardrail(Guardrail):  # :648
    name = "prompt_injection"  # :682
    stages: ClassVar[set] = {GuardrailStage.INPUT}  # :683
    priority = 10  # :684
    # sync scoring call: probability = self._injection_engine.score(scan_text)  # :779 (S3 target)
    def _wrap_flagged_input(text, threats)  # :836 (static)
async def warmup_injection_model(force_download=False) -> str  # :915 (to_thread usage :943-958)

# parrot/bots/guardrails/builtin/secrets.py
class SecretsGuardrail(Guardrail): priority = 10  # :49 (collides with prompt_injection — S7)

# parrot/bots/guardrails/builtin/moderation.py
class ModerationPolicy(BaseModel)  # :33 · ModerationBackend(Protocol) :50 · ModerationGuardrail :99 (priority 50 :108)

# parrot/security/prompt_injection.py
class SecurityEventLogger:  # :297
    async def log_injection_attempt(self, user_id, session_id, chatbot_id, threats,
                                    original_input, sanitized_input, metadata=None)  # :306
    # logs matched_text (:333) and passes original/sanitized input (:343-344) — content-leaking (S2)
# threat dicts carry 'matched_text'  # :238/:249/:260

# parrot/bots/abstract.py
self._guardrail_pipelines = build_pipelines_from_config(...)  # :693
# GroundednessGuardrail wired with bot state  # :753 (wiring precedent)
self.tool_manager._tool_output_pipeline = ...[TOOL_OUTPUT]  # :769
# INPUT pipeline run :2756 · _run_output_pipeline :2758 · non-string skip :2782
# OUTPUT extras = {"chatbot_id":…, "ai_message": response}  # :2798 — NO system_prompt today
def system_prompt(self) -> str  # :1126 (property — the TEMPLATE, not rendered)
# vector_context folded into system prompt: if vector_context: ... f"<documents>…"  # :1492-1493
async def create_system_prompt(  # :3679 — per-call rendering (memory/retrieval/skills layers)

# parrot/tools/abstract.py — TOOL_OUTPUT seam
# GuardrailContext(stage=TOOL_OUTPUT, agent_name=tool_name, tool_name=tool_name)  # :188-196
# BLOCK ⇒ "[content removed by guardrail: <reason>]"

# packages/ai-parrot/pyproject.toml
"rapidfuzz>=3.0"  # :282 — graphindex extra ONLY; boundary note :354
"onnxruntime>=1.16"  # :747 — core dep

# benchmarks/injection_guardrail_latency/
# corpus.py: build_eval_set :250, build_eval_languages :269, assert_seed_disjoint :325
# compare_models.py: TorchModel :82, OnnxModel :92
# detectors.py, export.py, harness.py, metrics.py exist (dir listing verified)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `JailbreakGuardrail` | INPUT pipeline | registry lazy factory | `registry.py:146-174` pattern |
| chassis engines | `PromptInjectionGuardrail.check()` | `score_async` | `prompt_injection.py:779` |
| `PromptLeakageGuardrail` OUTPUT | `_run_output_pipeline` extras | `ctx.extras["system_prompt"]` (new key) | `bots/abstract.py:2798` |
| retrieval scan | `_build_vector_context` → `<documents>` | TOOL_OUTPUT pipeline run per chunk | `bots/abstract.py:1492-1493` |
| content-free events | `SecurityEventLogger` | new sibling method | `security/prompt_injection.py:306` |
| TOOL_OUTPUT wrap reports | `ToolResult.metadata["guardrails"]` | existing seam + S1 pipeline fix | `tools/abstract.py:188-196` |

### Does NOT Exist (Anti-Hallucination)

- ~~`JailbreakGuardrail` / `PromptLeakageGuardrail`~~ — new in this feature.
- ~~registry names `"jailbreak"` / `"prompt_leakage"` / preset `"security"`~~ —
  not registered, not reserved.
- ~~`parrot/bots/guardrails/builtin/_engine_chassis.py`~~ — the engine
  machinery lives private inside `builtin/prompt_injection.py` only.
- ~~`system_prompt` in OUTPUT `GuardrailContext.extras`~~ — extras carry only
  `chatbot_id` + `ai_message` (`abstract.py:2798`).
- ~~a per-turn rendered-system-prompt attribute/cache~~ — `system_prompt`
  (`:1126`) is the template; rendering happens per call in
  `create_system_prompt` (`:3679`) and is not retained.
- ~~per-stage priority / `priority_for()`~~ — `priority` is a scalar int
  (`base.py:121`); pipeline sorts on it directly.
- ~~report surfacing for TRANSFORM results~~ — dropped today
  (`pipeline.py:193-196`).
- ~~a content-free `SecurityEventLogger` method~~ — only
  `log_injection_attempt` (`:306`), which logs matched text.
- ~~`warmup_jailbreak_model` / `PARROT_JAILBREAK_*` env vars~~ — new.
- ~~jailbreak/leakage corpora or an embedding detector in
  `benchmarks/injection_guardrail_latency/`~~ — new.
- ~~pipeline scanning of `vector_context` retrieval chunks~~ — retrieval
  bypasses all guardrails today.

### Edit Sites (Blueprint Anchors)

Verified against: `4e3ba6289`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/base.py` | MODIFY | `    priority: int` | `base.py:121` | 1 |
| `packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py` | MODIFY | `            elif result.action == GuardrailAction.TRANSFORM:` | `pipeline.py:193` | 1 |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/_engine_chassis.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | `    stages: ClassVar[set] = {GuardrailStage.INPUT}` | `prompt_injection.py:683` | 1 |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | `            probability = self._injection_engine.score(scan_text)` | `prompt_injection.py:779` | 1 |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/jailbreak.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_leakage.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/guardrails/registry.py` | MODIFY | `    _make_lazy_factory("parrot.bots.guardrails.builtin.pbac", "PBACToolCallGuardrail"),` | `registry.py:173` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `            extras={"chatbot_id": str(self.chatbot_id), "ai_message": response},` | `abstract.py:2798` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `            knowledge_parts.append(f"<documents>\n{vector_context}\n</documents>")` | `abstract.py:1493` | 1 |
| `packages/ai-parrot/src/parrot/security/prompt_injection.py` | MODIFY | `    async def log_injection_attempt(` | `security/prompt_injection.py:306` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `    "rapidfuzz>=3.0",` | `pyproject.toml:282` | 1 |
| `packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py` | MODIFY | `(unverified — check before use)` — rapidfuzz boundary assertion | — | — |
| `benchmarks/injection_guardrail_latency/corpus.py` | MODIFY | `def build_eval_set() -> tuple[list[str], list[int], list[str]]:` | `corpus.py:250` | 1 |
| `benchmarks/injection_guardrail_latency/compare_models.py` | MODIFY | `class OnnxModel:` | `compare_models.py:92` | 1 |
| `benchmarks/injection_guardrail_latency/detectors.py` | MODIFY | `(unverified — check before use)` | — | — |
| `docs/security/agent-security-guardrails.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic policies (`LeakagePolicy` mirrors `ModerationPolicy`,
  `moderation.py:33`); Google docstrings; strict hints; `self.logger`.
- FEAT-439 import discipline: onnxruntime/transformers/huggingface_hub/
  rapidfuzz imported lazily inside engine/guardrail code, never at module
  import time; registry factories stay lazy.
- Chassis refactor is **move-first**: relocate verbatim, then parametrize;
  golden tests captured BEFORE touching `prompt_injection.py`
  (the FEAT-396 migration discipline).
- `warmup_*` functions are the only download sites (FEAT-439 TASK-2309
  precedent); everything else is offline-only probes.
- Zero-overhead discipline: `extras["system_prompt"]` populated only when a
  registered OUTPUT guardrail opts in (mirror `has_guardrails`).
- Heuristic floors and extraction patterns ship as data (module-level
  tuples/JSON), not hardcoded conditionals, so ops can audit them.

### Known Risks / Gotchas

- **`prompt_injection.py` refactor risk**: hottest guardrail; mitigated by
  golden parity tests + bit-identical public surface + existing suite in
  the Validation Contract (8 files).
- **Spanish false positives**: the reason Wolf Defender won; the bake-off's
  Spanish-benign bucket is a hard 0-FP gate, not advisory.
- **Leakage FP on legitimate capability questions**: benign "what can you
  do?" answers share topic words with the prompt — the shingle size (8)
  and `min_prompt_shingles` floor exist precisely for this; thresholds
  calibrated in the benchmark with a benign-paraphrase bucket.
- **Streaming**: leaked chunks are already emitted before the OUTPUT check
  (v1 accepted limitation; `stream_checked: "final_only"` marks it;
  withholding adapter is a follow-up).
- **Content leaks via logging**: existing `log_injection_attempt` logs
  matched text — new categories MUST use the content-free sibling (S2);
  tests assert log payloads.
- **Double-wrap**: TOOL_OUTPUT re-runs must not nest untrusted markers —
  idempotency stamping (FEAT-396 `_already_scrubbed` precedent).
- **`_llm_kwargs` mutation hazard** (`bots/abstract.py`): rebind, never
  mutate, when touching seam code (known repo gotcha).
- **Shared checkout**: `bots/abstract.py` is hot across in-flight features —
  coordinate landing windows; worktree discipline applies.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rapidfuzz` | `>=3.0` (already pinned) | leakage fuzzy matching — **moves from the `graphindex` extra to core deps**, with `test_dependency_boundary.py` updated deliberately |
| — | — | no other new runtime deps (onnxruntime, numpy, transformers already present) |

---

## 8. Open Questions

- [x] Fuzzy matcher: rapidfuzz vs difflib — *Resolved in spec Q&A*:
  rapidfuzz moves to core deps; boundary test updated deliberately.
- [x] System-prompt artifact for OUTPUT leakage — *Resolved in spec Q&A*:
  per-turn rendered prompt, captured at the seam and cached; never
  re-rendered at OUTPUT (design-research S5 refinement adopted).
- [x] Canary token in v1 — *Resolved in spec Q&A*: yes, `canary` policy
  key, operator-managed; auto-injection out of scope.
- [x] INPUT-side leakage approach — *Resolved in spec Q&A*:
  heuristics-only in v1; no coupling to the jailbreak model's score.
- [x] Streaming leakage — *Resolved in spec Q&A*: v1 final-message-only
  accepted; reports marked `stream_checked: "final_only"`; withholding
  adapter is a follow-up.
- [x] `scan_tool_output` default/granularity — *Resolved in spec Q&A*:
  off by default, global (no per-tool opt-out in v1).
- [x] Priority ordering + preset — *Resolved in spec Q&A*: injection 10 →
  jailbreak 11 → leakage 12 (INPUT) / 220 (OUTPUT); `security` preset
  ships in v1.
- [x] **Bake-off eligibility + decision rule** — *Resolved 2026-10-27
  (licenses verified via HF cards/API; empirical winner is M3's committed
  output, now mechanical)*: default-eligible shortlist =
  `vllm-sr/mmbert32k-jailbreak-detector-merged` (apache-2.0; EN-only
  fine-tune on toxic-chat + Salad-Data — ES-attack *miss* risk, so the
  bake-off adds a Spanish ATTACK recall bucket, not just Spanish benign),
  `madhurjindal/Jailbreak-Detector-Large` (MIT; EN fine-tune; own ONNX
  export via `export.py`), `gravitee-io/Llama-Prompt-Guard-2-86M-onnx`
  **fp32 graph only** (llama4 community license — conditional: "Built with
  Llama" attribution + AUP noted in ops docs if it wins; its own eval shows
  the int8 quant collapses F1 0.98→0.89 / recall 0.80, so `model.quant.onnx`
  is excluded on quality), `enguard/medium-guard-128m-xx` (MIT, latency
  dark horse). **Excluded from default**: 0din embeddings (NO license
  declared — may re-enter only if 0din/Mozilla clarifies),
  `sheltron-ai/prompt-guard-68m` (CC-BY-NC), any protectai model (ES-FP
  baseline only). **Pre-registered decision rule**: winner = highest
  combined ES+EN F1 subject to (a) 0 Spanish-benign FPs at the selected
  threshold and (b) p50 ≤ 30 ms CPU @ 512 tokens; ties → more permissive
  license (apache/MIT over llama4), then smaller artifact. M3 commits the
  numbers + manifest; §5 gate unchanged.
- [x] **Reference attack corpus** — *Resolved 2026-10-27*: moot for v1 —
  no embedding candidate is license-eligible, so **no corpus artifact
  ships in v1** (the chassis's `EmbeddingSimilarityEngine` stays: the
  benchmark wrapper uses it and a future embedding adoption needs it).
  Policy recorded for that future: corpus = operator-downloaded artifact
  resolved at warmup via the env-dir chain, never package data; evaluation
  seeds stay curated in-repo ES/EN (the `corpus.py` +
  `assert_seed_disjoint` pattern); WildJailbreak is ODC-BY + gated-auto
  (AI2 terms) — local evaluation use with attribution is fine, derived
  vectors are NOT redistributed by this repo.
- [x] Heuristic pattern data location — *Resolved 2026-10-27*: per
  guardrail — each builtin owns its pattern data as module-level
  structures next to its code (one-owner discipline, mirroring the
  FEAT-439 import-boundary rule). No shared pattern file.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted
> brainstorm. Model: `gpt-5.6-luna` (codex-cli 0.164.0) · Status: completed
> · Transcript: `sdd/state/FEAT-761/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make reports orthogonal to actions (api) | CONFIRM | Verified `pipeline.py:190-197`: TRANSFORM reports dropped; TOOL_OUTPUT wrap needs TRANSFORM+report | §3 M1, §5 |
| S2 | Close content-leaking telemetry path (risk) | CONFIRM | Verified `security/prompt_injection.py:333,343-344` logs matched/original text — fatal for leakage events | §3 M6, §5, §7 |
| S3 | Remove sync inference from async checks (architecture) | CONFIRM | Verified `prompt_injection.py:779` sync `score()` in async `check()` | §3 M2, §4 perf |
| S4 | Explicit RAG-content scanning seam (architecture) | CONFIRM | Verified `abstract.py:1492-1493`: retrieval bypasses all pipelines | §3 M5, §7 |
| S5 | Capture exact rendered prompt per turn (architecture) | CONFIRM | Matches user decision; refinement: capture at seam, never re-render | §2, §3 M7 |
| S6 | Make streaming limits explicit (risk) | CONFIRM | v1 limitation documented + `stream_checked` marker | §7, §8 |
| S7 | Stage-specific ordering (api) | CONFIRM | Verified secrets/prompt_injection both priority 10; leakage needs INPUT/OUTPUT bands | §3 M1 |
| S8 | Explicit engine backends, not bare score protocol (architecture) | CONFIRM | `EngineSpec` descriptor + two backends, per-category caches | §3 M2 |
| S9 | Bake-off as hard reproducible gate (testing) | CONFIRM | corpora, threshold sweep, latency/memory, manifest, fail-closed | §3 M3, §5 |
| S10 | Provenance before shipping artifacts (risk) | CONFIRM | manifest with license/revision/hash; unlicensed never default | §5, §8 |
| S11 | Avoid rapidfuzz as core dep (alternative) | REJECT | User decision: rapidfuzz→core via the suggestion's own sanctioned "deliberate update" path; injectable-matcher indirection adds surface for no need | — |

Summary: **10** confirmed · **1** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for the spec; the `sdd-coder` engine
  gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M4 → M2 (imports chassis `resolve_engine`/`score_async`) and M4 → M3
    (default model + threshold constants come from the committed bake-off).
  - M5 → M1 (TRANSFORM report surfacing) and M5 → M2 (both edit
    `prompt_injection.py`).
  - M6 → M1 (per-stage priority).
  - M7 → M4, M6 (wires and documents their names).
  - M1 ∥ M2 ∥ M3 have no edges between them — expected to run concurrently.
- **Shared files**: `builtin/prompt_injection.py` (M2, M5 — serialize);
  `registry.py` (M4, M6, M7 — serialize); `bots/abstract.py` (M5, M7 —
  serialize).
- **Exclusive resources**: none (no native rebuilds, no migrations; the
  pyproject + boundary-test edit is contained in M6).
- **Cross-feature dependencies**: none — no in-flight spec touches
  `bots/guardrails/` (FEAT-396/398/406/439/714 are merged).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesús Lara / Claude Code | Initial draft from `agent-security-guardrails.brainstorm.md` (Option A) + design-research fold-in (10 CONFIRM / 1 REJECT) |
