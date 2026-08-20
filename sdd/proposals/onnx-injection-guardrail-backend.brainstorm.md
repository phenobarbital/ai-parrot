---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: ONNX Backend for the Prompt-Injection Guardrail

**Date**: 2026-08-20
**Author**: Jesús Lara (brainstorm conducted with Claude Code)
**Status**: exploration
**Recommended Option**: Option A

> Measured background: `sdd/proposals/nlproxy-guardrails.comparison.md` §3b.
> Harness + evidence: `benchmarks/injection_guardrail_latency/`.

---

## Problem Statement

`AbstractBot.__init__` defaults `injection_detection: bool = True`
(`bots/abstract.py:292`) and `strict_mode: bool = True`
(`bots/abstract.py:290`). Every bot that does not explicitly opt out
therefore registers `PromptInjectionGuardrail`, which loads a full
DeBERTa-v3-base classifier under PyTorch through `pytector` and runs it
on the INPUT stage of every turn.

Measured on 2026-08-20 (96-sample corpus, 10 timed passes, one process
per tier, ORT/torch capped to 2 threads):

| Backend | p50 | p95 | p99 | RSS Δ |
|---|---|---|---|---|
| `clf-torch` (today) | **118.99 ms** | **145.83 ms** | 158.18 ms | 1503 MB |
| `clf-onnx` fp32 | **32.96 ms** | 59.85 ms | 65.97 ms | 1911 MB |

Two distinct problems, and it matters that they are distinct:

1. **Cost.** ~119 ms is spent before the LLM call even begins, on every
   turn, for every agent. ONNX fp32 removes ~86 ms of it running the
   *same weights* — verified at `max|Δ| = 0.000` with **zero flipped
   verdicts** across all 96 samples.
2. **Blocking.** `pytector.detect_injection()` is a synchronous call
   made from inside `async def check()`
   (`guardrails/builtin/prompt_injection.py:180`), so it occupies the
   event loop for its full duration. Under concurrency every in-flight
   turn serialises behind it. **This feature does not fix that** —
   moving the guardrail to the EXECUTOR route is a separate, follow-up
   feature. Reducing 119 ms to 33 ms shortens the stall; it does not
   remove it.

Secondary problem surfaced by the same research: `pytector`'s
`predefined_models` alias `"deberta"` pins
`protectai/deberta-v3-base-prompt-injection` (v1, ~58 k downloads/month).
Upstream `-v2` is the maintained model (~482 k downloads/month) and both
publish ONNX graphs under Apache-2.0. Staying on v1 is an unexamined
default, not a decision.

**Who is affected**: every AI-Parrot agent deployment (latency, and
~1.5 GB of resident model per worker process); operators running
air-gapped or network-restricted installs (today the model is resolved
from HF Hub at first construction, inside a user turn).

## Constraints & Requirements

- **No change to the `Guardrail` contract.** `name`, `stages`,
  `priority`, `on_error`, and the `check(content, ctx) -> GuardrailResult`
  signature stay exactly as they are (`guardrails/base.py:119-125`).
- **No threshold change.** `injection_probability_threshold` stays at its
  current default of `0.98`. Retuning is explicitly a different feature.
- **No tiering.** The regex/embedding-similarity tier from the research
  doc §4.3 is out of scope here — one axis of risk per feature.
- **No int8.** Dynamic int8 quantization of DeBERTa-v3 was measured at
  39/96 flipped verdicts and 0 % recall; it is disqualified until static
  quantization is evaluated separately.
- **The graph must never be downloaded on the request path.** A ~700 MB
  fetch inside a user turn is not acceptable.
- **ORT thread pools must be capped.** Uncapped, ORT sizes its intra-op
  pool to every physical core *per session*, which starves the event loop
  (prior art and hard-won lesson: `voice/tts/supertonic_inference.py:462-472`).
- **Degradation must be loud, never silent.** A missing graph falls back
  and logs; it does not quietly reintroduce the slow path.
- **Both paths must run the same model.** After the v2 move, the ONNX
  path and the fallback path must not disagree on verdicts.
- **Acceptance gate**: the numerical-parity check in
  `benchmarks/injection_guardrail_latency/` must be green against the
  **torch-v2** reference (see Open Questions for why the reference moved).

---

## Options Explored

### Option A: ONNX backend inside `PromptInjectionGuardrail`, hybrid resolution

Add a backend-selection step to the existing guardrail's `__init__`. The
engine is chosen once, at construction, from a fixed precedence:

1. **ONNX**, if a graph resolves — env var `PARROT_INJECTION_ONNX_DIR`
   first (air-gapped / CI), else an already-cached HF snapshot of the
   upstream `onnx/model.onnx`.
2. **pytector/torch**, if `pytector` is importable — same weights, slow.
3. **Regex engine** (`PromptInjectionDetector`), always available.

`check()` is untouched in shape: it still strips framework patterns,
scores, logs the security event, and returns TRANSFORM/BLOCK/PASS. Only
the "produce a probability" step is swapped behind a small engine
interface. The process-wide singleton pattern already used for the
pytector detector (`prompt_injection.py:53-79`) is extended to hold the
ORT session, so N bots share one graph.

A warm-up entry point resolves and loads the graph (plus one dummy
inference) so the first real turn never pays cold start, mirroring
`AbstractBot.warmup_embeddings` (`bots/abstract.py:1713`).

✅ **Pros:**
- Smallest possible diff for the measured win; the guardrail's public
  behaviour, config surface, and registration are unchanged.
- Users get the 3.6× without opting in, which is what makes it actually
  get collected.
- The fallback chain means no install can break: worst case it behaves
  exactly like today.
- Reuses the singleton/lock and lazy-import discipline already proven in
  this exact module.

❌ **Cons:**
- Concentrates three engines behind one class; the class grows and its
  tests must now cover a backend matrix.
- The hybrid resolution has several failure modes to enumerate (env var
  set but empty, cache present but corrupt, partial snapshot).
- Does nothing about the blocking-call problem, or about ~1.9 GB of RSS
  per worker process.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `onnxruntime>=1.16` | Runs the exported graph | Already declared in `ai-parrot[security]`; releases the GIL during `Run()` |
| `huggingface_hub` | Resolve/`snapshot_download` the upstream graph | **Present transitively only** — must be declared explicitly if used (see Code Context) |
| `transformers` | `AutoTokenizer` for the ONNX path | Already arrives with `pytector` |
| `pytector==0.2.0` | Fallback engine | Stays; declared in `ai-parrot[security]` |

🔗 **Existing Code to Reuse:**
- `bots/guardrails/builtin/prompt_injection.py:53-79` — process-wide
  singleton + `threading.Lock` double-checked init.
- `bots/guardrails/builtin/prompt_injection.py:137` —
  `importlib.util.find_spec` gating pattern for optional backends.
- `voice/tts/supertonic_inference.py:108,462-475` — `_env_int` helper and
  the ORT `SessionOptions` thread caps.
- `security/prompt_injection.py:123` — `strip_framework_patterns`,
  unchanged and backend-independent.
- `bots/abstract.py:1713` — `warmup_embeddings` as the shape for a
  warm-up hook.
- `benchmarks/injection_guardrail_latency/` — corpus, parity gate,
  `--classifier` flag for re-measuring on v2.

---

### Option B: A separate, opt-in `OnnxPromptInjectionGuardrail`

Register a second named guardrail (`"prompt_injection_onnx"`) alongside
the existing one via `register_guardrail`
(`guardrails/registry.py:604`). Bots opt in explicitly through
`guardrails=[...]`. The existing class is not touched at all.

✅ **Pros:**
- Zero risk to the current path — it is not modified.
- Trivially A/B-comparable in one process; both can be registered.
- Clean rollback: stop naming it.

❌ **Cons:**
- **Nobody turns it on.** The win is default-on or it is not collected;
  `injection_detection=True` means the slow path stays the default
  forever.
- Duplicates `check()`'s framework-stripping, security-event logging, and
  `_wrap_flagged_input` logic, or requires extracting a shared base —
  which is Option A's refactor anyway, plus a second class.
- Two guardrails claiming the same INPUT stage and priority band is a
  configuration footgun.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as Option A.

🔗 **Existing Code to Reuse:**
- `bots/guardrails/registry.py:604-616` — `register_guardrail` +
  `_make_lazy_factory` for a new named entry.

---

### Option C: Build `parrot.security.models` first, guardrail as its first consumer

Stand up the general offline-model registry described in the research doc
§4.1 — a `LocalModelRegistry` with named entries, checksum verification,
`PARROT_MODELS_DIR`, an offline-strict mode, and shared ORT session
construction with the thread caps baked in. The injection guardrail then
becomes its first client.

✅ **Pros:**
- Solves the model-distribution question once, for the NLI groundedness
  tier and the PII engine too, instead of three times.
- Centralises the ORT session discipline so the thread-cap lesson cannot
  be forgotten by the next implementer.
- Checksum verification and a real offline mode are genuinely valuable
  for regulated deployments.

❌ **Cons:**
- Designs the abstraction before there is a second consumer to shape it —
  the classic way to get the abstraction wrong.
- Substantially delays a measured, zero-quality-risk 86 ms/turn win
  behind speculative infrastructure.
- Much larger review surface for a feature whose value is a backend swap.

📊 **Effort:** High

📦 **Libraries / Tools:** as Option A, plus `hashlib` (stdlib) for
checksums.

🔗 **Existing Code to Reuse:**
- `parrot/_imports.py` — `lazy_import`, the cached optional-dependency
  detection helper already used by `tools/compression/budget.py`.
- `voice/tts/supertonic_inference.py:462-475` — the session-construction
  discipline to generalise.

---

### Option D (unconventional): Shared sidecar inference process

Run one classifier process per host rather than one per worker, reached
over a Unix domain socket. Workers send text and receive a probability;
the guardrail becomes a thin client with the regex engine as its offline
floor.

The motivation is a number the benchmark surfaced almost incidentally:
the classifier costs **1503 MB (torch) / 1911 MB (ONNX)** of resident
memory. Under a typical `gunicorn --workers N` deployment that is
multiplied by N — an 8-worker host carries roughly 12–15 GB of duplicated
identical weights. A sidecar makes it one copy, and simultaneously moves
the inference fully off every worker's event loop without any executor
plumbing.

✅ **Pros:**
- Collapses N copies of the model to one; by far the largest resource win
  of any option here.
- True isolation: a model crash, a memory spike, or an ORT thread storm
  cannot touch a worker's event loop.
- The sidecar can batch across workers, which is exactly what makes a
  future NLI tier affordable.
- Model upgrades become a sidecar restart, decoupled from app deploys.

❌ **Cons:**
- Adds a process to deploy, supervise, health-check, and version — a real
  operational burden for a framework that is currently a library.
- Adds IPC latency and a new failure mode (socket unavailable) to a
  guardrail on the hot path.
- Substantially more surface than the problem in front of us; it is an
  infrastructure decision wearing an optimisation's clothes.
- Hard to justify before the executor route (the cheaper fix for the
  blocking half of the problem) has even been tried.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | UDS client/server | Already a core dependency; project rule forbids `requests`/`httpx` |
| `onnxruntime>=1.16` | Inference, in the sidecar only | Workers would no longer need it |

🔗 **Existing Code to Reuse:**
- `parrot/handlers/` — existing aiohttp handler patterns.

---

## Recommendation

**Option A** is recommended.

The decisive argument is that the measured win is *default-on or it does
not exist*. `injection_detection=True` is the constructor default, so the
population that benefits is "every agent" — and Option B's opt-in switch
would be flipped by approximately nobody, leaving a verified 86 ms/turn
on the table indefinitely. That alone eliminates B.

Against Option C: the model-distribution abstraction is worth building,
but not yet. There is currently one consumer. Designing
`parrot.security.models` now means guessing what the NLI tier and the PII
engine will need from it, and guessing badly is expensive to undo. Option
A's hybrid resolution is deliberately small enough to be *absorbed* by a
future registry rather than fought with — env var, then cache, then
fallback, with the ORT session construction already isolated in one place
to lift out later. We trade some duplication-in-waiting for shipping a
zero-quality-risk change now.

Option D is the most interesting and should not be discarded — the
per-worker memory multiplication it targets is a real, measured problem
that none of the other options address. But it is the wrong *next* step:
it is an operational architecture change, and the cheaper fix for the
blocking half of the problem (the EXECUTOR route plus
`BudgetRouter`/`CircuitBreaker`, already scoped as the follow-up feature)
has not been tried yet. Revisit D if per-worker RSS becomes the binding
constraint after the executor work lands.

**What Option A explicitly trades away**: it does not stop the guardrail
from blocking the event loop, and it does not reduce per-worker memory
(ONNX measured *higher* RSS than torch, 1911 MB vs 1503 MB — worth
stating plainly, since "faster" is doing no work for memory here). Both
are accepted, and both are the follow-up features' job.

---

## Feature Description

### User-Facing Behavior

For an operator who changes nothing: the agent behaves identically and
gets faster. Same verdicts on the same inputs, same
`AIMessage.metadata`, same `<potentially_unsafe_input>` wrapping, same
`threats_detected` reporting — with the caveat that the model itself
moves v1 → v2 (see below), which *is* a behaviour change.

Three new levers, all optional:

- `PARROT_INJECTION_ONNX_DIR` — absolute path to a directory holding the
  graph. Wins over everything else. This is the air-gapped and CI answer.
- `PARROT_INJECTION_ORT_INTRA_OP_THREADS` /
  `PARROT_INJECTION_ORT_INTER_OP_THREADS` — ORT thread caps, defaulting
  conservatively, following the `SUPERTONIC_ORT_*` naming already in the
  codebase.
- A warm-up call, invoked at startup by long-lived hosts, that resolves
  and loads the graph up front.

Logs state which engine was selected, once, at construction — so "why is
this slow" is answerable from a log line rather than a profiler.

**Behaviour change to communicate**: the classifier moves from
`protectai/deberta-v3-base-prompt-injection` to
`…-v2`. Verdicts will differ on some inputs. The v1→v2 delta is measured
and documented as part of this feature rather than discovered in
production.

### Internal Behavior

At construction the guardrail resolves its engine once, in strict
precedence — env-var directory, then cached HF snapshot, then pytector,
then the regex engine — and records the choice. Resolution never reaches
the network: an uncached snapshot is treated as absent.

The chosen engine is held in a process-wide singleton behind a lock, so
N bots in one process share one ORT session (extending the existing
pattern at `prompt_injection.py:53-79`). Session construction sets
`intra_op_num_threads` / `inter_op_num_threads` before anything else.

`check()` keeps its exact current flow — trusted-source bypass,
`strict_mode` bypass, framework-pattern stripping, score, threshold
compare, security-event log, BLOCK or TRANSFORM. The only substitution is
which engine produces the probability. The regex engine keeps its
existing distinct path: it returns `(sanitized, threats)` rather than a
probability, and that asymmetry is preserved rather than papered over.

Warm-up is a separate, explicitly-invoked coroutine that performs
resolution, session construction, and one dummy inference. It is the only
place permitted to download.

### Edge Cases & Error Handling

- **`PARROT_INJECTION_ONNX_DIR` set but missing/incomplete** — log an
  error naming the path and the missing file, fall through to the next
  engine. An operator who configured something wrong must be told.
- **Graph not cached and warm-up never ran** — no download; log a warning
  that names the warm-up entry point, fall back to pytector.
- **ORT session construction fails** (bad opset, corrupt file) — log the
  exception, fall back. Never propagate out of `__init__`.
- **`pytector` absent and no graph** — regex engine, as today.
- **Inference raises at request time** — the existing `on_error` contract
  applies unchanged: `fail_closed` when `block_on_threat`, else
  `fail_open` (`prompt_injection.py:129`). Not re-invented here.
- **Concurrent first construction** — the double-checked lock prevents
  two parallel session loads.
- **Tokenizer/graph label mismatch** — resolve the injection class index
  from the model config rather than assuming index 1.
- **Empty or whitespace-only input** — must not reach the model; short-
  circuit to PASS.
- **Input longer than the model's max length** — truncation policy must
  be explicit and identical across backends, or the backends disagree on
  long inputs and the parity gate becomes meaningless.

---

## Capabilities

### New Capabilities
- `injection-onnx-backend`: ONNX Runtime engine for the prompt-injection
  guardrail, with env-var/cache/fallback resolution and capped ORT
  threads.
- `injection-model-warmup`: explicit, startup-time resolution and load of
  the classifier so no user turn pays cold start or a download.

### Modified Capabilities
- `guardrails-infrastructure` (FEAT-396) — `PromptInjectionGuardrail`
  gains backend selection. The `Guardrail` ABC, pipeline, and registry
  are untouched.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `bots/guardrails/builtin/prompt_injection.py` | modifies | Engine selection in `__init__`; singleton extended to the ORT session; `check()` flow preserved |
| `bots/abstract.py` | extends | Optional warm-up wiring; `injection_detection` default and legacy-flag mapping unchanged |
| `packages/ai-parrot/pyproject.toml` | modifies | `huggingface_hub` must be declared explicitly if the cache path is used (currently transitive only) |
| `benchmarks/injection_guardrail_latency/` | depends on | Parity gate becomes an acceptance criterion; re-run against v2 via `--classifier` |
| `bots/guardrails/registry.py` | none | No new registered name — Option A keeps `"prompt_injection"` |
| `tests/unit/test_guardrails_prompt_injection.py` | extends | Backend-matrix coverage |
| Deployment / ops | modifies | New env vars; warm-up recommended for long-lived hosts; graph provisioning for air-gapped installs |

---

## Code Context

### User-Provided Code

No code was pasted by the user during discovery. The measurements the
user supplied as context are recorded in the Problem Statement and are
reproducible via `benchmarks/injection_guardrail_latency/`.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/bots/guardrails/base.py:97-125
class Guardrail(ABC):
    name: str                                    # line 119
    stages: set[GuardrailStage]                  # line 120
    priority: int                                # line 121
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"   # line 122

    @abstractmethod
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:  # line 125
        ...

# From packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
_SHARED_INJECTION_DETECTOR = None                      # line 53
_SHARED_INJECTION_DETECTOR_LOCK = threading.Lock()     # line 54

def _get_shared_injection_detector():                  # line 57
    # double-checked init; constructs at lines 75-78:
    #     _PytectorDetector(model_name_or_url="deberta",
    #                       enable_keyword_blocking=True)
    ...

class PromptInjectionGuardrail(Guardrail):             # line 82
    name = "prompt_injection"                          # line 102
    stages: ClassVar[set] = {GuardrailStage.INPUT}     # line 103
    priority = 10                                      # line 104

    def __init__(                                      # line 106
        self,
        strict_mode: bool = True,
        block_on_threat: bool = False,
        injection_probability_threshold: float = 0.98,
        **kwargs: Any,
    ) -> None:
        self.on_error = "fail_closed" if block_on_threat else "fail_open"   # line 129
        self._pytector_available = importlib.util.find_spec("pytector") is not None  # line 137

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:   # line 149
        # line 180: is_injection, probability = self._pytector_detector.detect_injection(scan_text)
        # line 192: sanitized, threats = self._injection_detector.sanitize(content, strict=True)
        ...

    @staticmethod
    def _wrap_flagged_input(text: str, threats: list[dict[str, Any]]) -> str:  # line 232
        ...

# From packages/ai-parrot/src/parrot/security/prompt_injection.py
class PromptInjectionDetector:                         # line 27
    def add_framework_allowlist(self, pattern: re.Pattern | str) -> None:  # line 113
    def strip_framework_patterns(self, text: str) -> str:                  # line 123
    def sanitize(...)                                                       # line 191

class SecurityEventLogger:                             # line 222
    async def log_injection_attempt(...)               # line 231

# From packages/ai-parrot/src/parrot/bots/abstract.py
    strict_mode: bool = True,            # line 290
    block_on_threat: bool = False,       # line 291
    injection_detection: bool = True,    # line 292  <-- DEFAULT ON
    async def warmup_embeddings(self) -> None:   # line 1713 (warm-up precedent)

# From packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py
def _env_int(name: str, default: int) -> int:          # line 108

    opts = ort.SessionOptions()                                             # line 462
    _intra = _env_int("SUPERTONIC_ORT_INTRA_OP_THREADS", 2)                 # line 469
    opts.intra_op_num_threads = _intra                                      # line 471
    opts.inter_op_num_threads = _env_int("SUPERTONIC_ORT_INTER_OP_THREADS", 1)  # line 472
    ort.InferenceSession(path, sess_options=opts, providers=providers)      # line 475
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel,
)                                    # security/__init__.py:8-13
from parrot.bots.guardrails import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)                                    # bots/guardrails/__init__.py:14-20
from parrot.bots.guardrails.registry import register_guardrail  # registry.py:56
from huggingface_hub import hf_hub_download, snapshot_download  # installed, see caveat below
```

#### Key Attributes & Constants

- `PromptInjectionGuardrail.priority` → `10` (sanitizer band 0-99)
  (`prompt_injection.py:104`)
- `PromptInjectionGuardrail.stages` → `{GuardrailStage.INPUT}`
  (`prompt_injection.py:103`)
- `injection_probability_threshold` default → `0.98`
  (`prompt_injection.py:106` ff.)
- `pytector.PromptInjectionDetector.predefined_models` →
  `{"deberta": "protectai/deberta-v3-base-prompt-injection"}`
  (`.venv/.../pytector/detector.py:18-19`) — **v1**
- `pytector.PromptInjectionDetector.detect_injection(prompt, threshold=None)`
  (`.venv/.../pytector/detector.py:369`)
- Upstream ONNX artifacts, verified live against the HF API on
  2026-08-20, both Apache-2.0:
  - `protectai/deberta-v3-base-prompt-injection` →
    `onnx/model.onnx`, `onnx/model_optimized.onnx`
  - `protectai/deberta-v3-base-prompt-injection-v2` → `onnx/model.onnx`
- Local export sizes for reference (v1, our own export):
  `model.onnx` 704.4 MB, `model_int8.onnx` 232.7 MB

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.security.models`~~ — **does not exist.** No offline model
  registry, no `LocalModelRegistry`, no `PARROT_MODELS_DIR`. Option C
  would create it; Option A deliberately does not.
- ~~`pytector.PromptInjectionDetector(model_name_or_url="protectai/deberta-v3-base-prompt-injection-v2")`~~
  — **this does NOT work.** Verified by reproducing pytector's resolution
  chain (`detector.py:136-150`): a bare HF repo id is not in
  `predefined_models`, `validators.url()` returns `False` for it, and
  `os.path.exists()` returns `False`, so the constructor raises
  `ValueError("Invalid model identifier...")`. A full `https://` URL
  satisfies `validators.url()` but is then handed straight to
  `AutoTokenizer.from_pretrained()`, which does not accept URLs — pytector's
  own source comments admit this is unverified. **The only working way to
  point pytector at v2 is a local snapshot directory**, which
  `os.path.exists()` accepts. This directly constrains the fallback
  design (see Open Questions).
- ~~`huggingface_hub` as a declared dependency of `ai-parrot`~~ — it is
  **importable but transitive only**, arriving via
  `transformers`/`sentence-transformers`. Depending on it directly
  requires adding it to the `security` extra.
- ~~`onnx/model_optimized.onnx` for v2~~ — exists for v1 only; v2 ships
  the plain graph.
- ~~A generic bot-level warm-up hook~~ — `AbstractBot.warmup_embeddings`
  (`abstract.py:1713`) is embeddings-specific and is called from exactly
  one site (`abstract.py:1598`). There is no general "warm up all models"
  entry point to hang this on.
- ~~`[tool.ruff]` configuration in the repo~~ — none exists; lint
  expectations are set by surrounding code, not enforced config.

---

## Parallelism Assessment

- **Internal parallelism**: Low. Nearly all the work lands in one file,
  `bots/guardrails/builtin/prompt_injection.py`. Graph resolution, ORT
  session construction, and the warm-up hook are separable in principle
  but share a small surface and would collide constantly in separate
  worktrees.
- **Cross-feature independence**: Good. No in-flight spec touches this
  file. The follow-up executor/`BudgetRouter` feature will touch
  `GuardrailPipeline` and `parrot.core.budget`, not this module — but it
  must land *after* this one to avoid rebasing the same call site twice.
  `benchmarks/injection_guardrail_latency/` is shared but read-mostly.
- **Recommended isolation**: `per-spec`
- **Rationale**: A single-module change with a strict dependency order
  (resolve → construct session → warm up → swap engine) gains nothing
  from parallel worktrees and would pay merge cost for it. One worktree,
  tasks sequential.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesús Lara*: `type: feature`,
  `base_branch: dev`. Not a hotfix; this is a performance improvement to
  a guardrail that works correctly today.
- [x] Where does the ONNX graph come from at runtime? — *Owner: Jesús Lara*:
  Hybrid — `PARROT_INJECTION_ONNX_DIR` wins, else a cached HF snapshot of
  the upstream graph, else pytector.
- [x] What happens when the graph is unavailable? — *Owner: Jesús Lara*:
  Loud warning plus fallback to pytector. Never fail-closed on an
  optimisation; never silent.
- [x] Is ONNX opt-in or automatic? — *Owner: Jesús Lara*: Auto-preferred
  whenever a graph resolves. Same detect-and-prefer pattern as
  `SemanticSegmenter`; justified because measured parity is exact.
- [x] Do we remove pytector / the torch stack here? — *Owner: Jesús Lara*:
  No. It stays as the fallback and the `security` extra is unchanged.
  Removing it is a later ticket, once ONNX is proven in production.
- [x] Do we export our own graph or consume upstream? — *Owner: Jesús Lara*:
  Consume ProtectAI's upstream `onnx/model.onnx` (Apache-2.0). Same repo
  pytector already uses, nothing to maintain, no divergence risk.
  `benchmarks/.../export.py` remains a verification tool, not a build step.
- [x] v1 or v2 of the classifier? — *Owner: Jesús Lara*: **v2**
  (`protectai/deberta-v3-base-prompt-injection-v2`). Note this converts
  the feature from a pure backend swap into a backend *and model* change;
  the consequences are handled by the two items below.
- [x] What is the parity gate's reference, given v2? — *Owner: Jesús Lara*:
  **torch-v2**, plus a separately measured and documented v1→v2 verdict
  delta. Parity verifies the export; the delta characterises the
  behaviour change. The harness's `--classifier` flag makes both a
  re-run rather than new code.
- [x] How is the v2 behaviour change rolled out? — *Owner: Jesús Lara*:
  Direct switch, no version knob. Rollback is a deploy.
- [x] When is the ~700 MB graph downloaded? — *Owner: Jesús Lara*:
  Only in an explicit warm-up. The request path never downloads; an
  uncached graph is treated as absent.
- [x] Is the 96-sample parity gate a sufficient acceptance bar? — *Owner: Jesús Lara*:
  Yes for parity, which compares the model against itself and so does not
  depend on corpus representativeness. It is **not** sufficient for the
  v1→v2 delta, which is a genuine quality question — hence the separate
  delta measurement above.
- [ ] **How does the pytector fallback actually load v2?** — *Owner: Jesús Lara*:
  The agreed design ("point pytector at v2 explicitly") cannot be
  implemented as stated — pytector rejects a bare repo id and cannot use a
  URL (see "Does NOT Exist"). The workable route is to hand pytector a
  **local snapshot directory**, which its `os.path.exists()` branch
  accepts, and which the hybrid resolution already produces. Needs
  confirmation that this preserves the user's intent (pytector stays the
  fallback, both paths run v2) before the spec commits to it. The
  alternative — loading the fallback via `transformers` directly and
  dropping pytector from the path — was already declined.
- [ ] Are the measured latency figures still valid for v2? — *Owner: Jesús Lara*:
  v2 is the same architecture and size, so the numbers should carry, but
  they were measured on v1. Re-run `--classifier` on v2 and restate the
  headline figures before the spec quotes them.
- [ ] Should `huggingface_hub` be declared in the `security` extra? —
  *Owner: Jesús Lara*: Required if the HF-cache branch of the hybrid
  resolution ships. Currently satisfied only transitively.
- [ ] What are the default ORT thread caps for this guardrail? —
  *Owner: Jesús Lara*: `SUPERTONIC_ORT_*` defaults to intra=2/inter=1 for
  real-time speech. A guardrail on a request path may want intra=1 to
  leave more headroom under concurrency. Needs a measurement, not a guess.
- [ ] Does the truncation policy match across backends? —
  *Owner: Jesús Lara*: The benchmark used `max_length=256` for both. What
  pytector uses internally is unverified; if it differs, the two paths
  disagree on long inputs and the fallback is not equivalent.
