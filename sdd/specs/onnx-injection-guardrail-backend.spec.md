---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ONNX Backend for the Prompt-Injection Guardrail

**Feature ID**: FEAT-439
**Date**: 2026-08-21
**Author**: Jesús Lara (spec drafted with Claude Code)
**Status**: approved
**Target version**: 0.27.0

> Brainstorm: `sdd/proposals/onnx-injection-guardrail-backend.brainstorm.md` (Option A)
> Measured background: `sdd/proposals/nlproxy-guardrails.comparison.md` §3b
> Evidence: `benchmarks/injection_guardrail_latency/results/` (v1) and `results-v2/` (v2 + v1→v2 delta)

---

## 1. Motivation & Business Requirements

### Problem Statement

`AbstractBot.__init__` defaults `injection_detection: bool = True`
(`bots/abstract.py:292`) and `strict_mode: bool = True`
(`bots/abstract.py:290`). Every bot that does not explicitly opt out
therefore registers `PromptInjectionGuardrail`, which loads a full
DeBERTa-v3-base classifier under PyTorch through `pytector` and runs it
on the INPUT stage of every turn.

Measured on the v2 classifier (2026-08-21, 96-sample corpus, 10 timed
passes, one process per tier, ORT/torch capped to 2 threads —
`benchmarks/injection_guardrail_latency/results-v2/report.md`):

| Backend | p50 | p95 | p99 | RSS Δ |
|---|---|---|---|---|
| `clf-torch` (today's engine) | **120.71 ms** | 147.28 ms | 155.37 ms | 1641 MB |
| `clf-onnx` fp32 | **35.16 ms** | 63.71 ms | 68.35 ms | 1823 MB |

Two distinct problems, and it matters that they are distinct:

1. **Cost.** ~121 ms is spent before the LLM call even begins, on every
   turn, for every agent. ONNX fp32 removes ~86 ms of it running the
   *same weights* — verified at `max|Δ| = 0.000` with **zero flipped
   verdicts** across all 96 samples (parity holds identically on v1 and
   v2 exports).
2. **Blocking.** `pytector.detect_injection()` is a synchronous call made
   from inside `async def check()` (`guardrails/builtin/
   prompt_injection.py:180`), so it occupies the event loop for its full
   duration. **This feature does not fix that** — moving the guardrail to
   an executor route is a separate follow-up feature. Reducing ~121 ms to
   ~35 ms shortens the stall; it does not remove it.

Secondary problem: `pytector`'s `predefined_models` alias `"deberta"`
pins `protectai/deberta-v3-base-prompt-injection` (v1). Upstream `-v2` is
the maintained model, and both publish ONNX graphs under Apache-2.0.
Staying on v1 is an unexamined default, not a decision. This feature
moves the primary path to **v2** (a deliberate, measured behaviour
change — see §7 Known Risks).

**Who is affected**: every AI-Parrot agent deployment (latency, and
~1.6–1.8 GB of resident model per worker process); operators running
air-gapped or network-restricted installs (today the model is resolved
from HF Hub at first construction).

### Goals

- Swap the probability-producing engine of `PromptInjectionGuardrail` to
  ONNX Runtime whenever a graph is locally resolvable, with **no change
  to the `Guardrail` contract** (`name`, `stages`, `priority`,
  `on_error`, `check(content, ctx) -> GuardrailResult` all unchanged —
  `guardrails/base.py:119-125`).
- Default-on: users get the ~3.4× speedup without opting in. Engine
  resolution follows a strict precedence: env-var directory → cached HF
  snapshot → pytector → regex.
- Move the classifier to `protectai/deberta-v3-base-prompt-injection-v2`
  on both ML paths whenever a local v2 snapshot exists.
- **Never download on the request path.** The ~700 MB graph is fetched
  only inside an explicit warm-up entry point; an uncached snapshot is
  treated as absent at construction time.
- Cap ORT thread pools (default intra=2 / inter=1, env-overridable) so
  the session can never starve the event loop.
- Degrade loudly, never silently: every fallback step logs what was
  tried, what failed, and which engine was selected.
- Keep `injection_probability_threshold` at its current default `0.98` —
  retuning is explicitly a different feature.
- File the follow-up feature for the measured v2 Spanish
  false-positive regression before this feature is closed (resolved
  decision: ship v2 *with* a mandatory follow-up ticket).

### Non-Goals (explicitly out of scope)

- **Fixing the event-loop blocking.** The executor route +
  `BudgetRouter`/`CircuitBreaker` is the scoped follow-up feature.
- **Reducing per-worker memory.** ONNX measured *higher* RSS than torch
  (1823 MB vs 1641 MB). The sidecar architecture that would fix the
  N-workers × 1.7 GB multiplication was rejected for now — see
  brainstorm Option D.
- **Threshold retuning.** `0.98` stays.
- **Tiering** (regex/embedding-similarity pre-filter) — one axis of risk
  per feature.
- **int8 quantization.** Dynamic int8 was measured at 39/96 flipped
  verdicts and 0% recall; disqualified until static quantization is
  evaluated separately.
- **A separate opt-in guardrail** was rejected in brainstorm (nobody
  would turn it on) — see `proposals/onnx-injection-guardrail-backend.brainstorm.md` Option B.
- **A general offline-model registry** (`parrot.security.models`) was
  rejected as premature — see brainstorm Option C. This feature's
  resolution logic is deliberately small enough to be absorbed by a
  future registry.
- **Removing pytector / the torch stack.** It stays as the fallback; the
  `security` extra keeps `pytector==0.2.0`. Removal is a later ticket.

---

## 2. Architectural Design

### Overview

Add a backend-selection step to `PromptInjectionGuardrail.__init__`. The
engine is chosen once, at construction, from a fixed precedence:

1. **ONNX** — if a graph resolves locally:
   - `PARROT_INJECTION_ONNX_DIR` (env var, absolute path to a directory
     holding the graph + tokenizer files) wins over everything. This is
     the air-gapped / CI answer.
   - else an **already-cached** HF snapshot of
     `protectai/deberta-v3-base-prompt-injection-v2` (`onnx/model.onnx`).
     Resolution never reaches the network: `local_files_only` semantics;
     an uncached snapshot is treated as absent.
2. **pytector/torch** — if `pytector` is importable:
   - pointed at the **local v2 snapshot directory** when one exists
     (pytector's `os.path.exists()` branch accepts it — the only working
     way to give pytector v2);
   - else today's exact behaviour: the `"deberta"` alias (**v1**), plus a
     loud warning that the fallback model differs from the intended v2
     (resolved decision: worst case = today, never worse).
3. **Regex engine** (`PromptInjectionDetector`) — always available.

`check()` is untouched in shape: trusted-source bypass, `strict_mode`
bypass, framework-pattern stripping, score, threshold compare,
security-event logging, BLOCK/TRANSFORM/PASS — only the "produce a
probability" step is swapped behind a small engine interface. The regex
engine keeps its existing distinct path (it returns `(sanitized,
threats)` rather than a probability); that asymmetry is preserved.

The process-wide singleton pattern already used for the pytector
detector (`prompt_injection.py:53-79`) is extended to hold the resolved
engine (ORT session + tokenizer, or pytector detector), so N bots share
one model. ORT `SessionOptions` thread caps are set **before** session
construction: default `intra_op_num_threads=2`,
`inter_op_num_threads=1`, overridable via
`PARROT_INJECTION_ORT_INTRA_OP_THREADS` /
`PARROT_INJECTION_ORT_INTER_OP_THREADS` (same `_env_int` pattern as
`SUPERTONIC_ORT_*`, `voice/tts/supertonic_inference.py:108,462-475`).

The ONNX path tokenizes with `truncation=True, max_length=512` (resolved
decision — model maximum; scans more of long inputs than the benchmarked
256). Because the published latency/parity figures were measured at 256,
**the parity gate and latency run MUST be re-run at 512 before merge**
(acceptance criterion). The pytector fallback does not truncate at all
(`pytector/detector.py:392`); this divergence on long inputs is
documented as a known limitation rather than papered over.

A warm-up entry point (explicit coroutine, mirroring the shape of
`AbstractBot.warmup_embeddings`, `bots/abstract.py:1713`) performs
resolution, optional download (`snapshot_download` — the ONLY place
allowed to download), session construction, and one dummy inference, so
the first real turn never pays cold start.

Engine selection is logged once, at construction, naming the engine and
the model — so "why is this slow" and "which model is running" are
answerable from a log line rather than a profiler.

### Component Diagram

```
PromptInjectionGuardrail.__init__
        │
        ▼
_resolve_injection_engine()  ──singleton+lock──▶  (process-wide, shared by N bots)
        │
        ├─ 1. PARROT_INJECTION_ONNX_DIR set? ──valid──▶ OnnxInjectionEngine
        │        │ invalid → ERROR log, fall through      (ORT session, capped threads,
        │        ▼                                         tokenizer, max_length=512)
        ├─ 2. cached HF snapshot of v2? ──yes──────────▶ OnnxInjectionEngine
        │        │ no (never downloads here)
        │        ▼
        ├─ 3. pytector importable?
        │        ├─ local v2 snapshot dir exists ──────▶ PytectorEngine(v2 snapshot)
        │        └─ else WARNING (v1≠v2) ──────────────▶ PytectorEngine("deberta"=v1)
        │        │ not importable
        │        ▼
        └─ 4. ────────────────────────────────────────▶ RegexEngine
                                                          (PromptInjectionDetector,
                                                           existing sanitize() path)

check(content, ctx)  ──strip framework patterns──▶ engine.score(text) ──▶ threshold/BLOCK/TRANSFORM
                                                    (unchanged flow)

warmup_injection_model()  ──▶ snapshot_download(v2)  [ONLY download site]
                          ──▶ _resolve_injection_engine() + dummy inference
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `bots/guardrails/builtin/prompt_injection.py` | modifies | Engine selection in `__init__`; singleton extended to hold the resolved engine; `check()` flow preserved |
| `bots/abstract.py` | extends | Optional warm-up wiring; `injection_detection` default and legacy-flag mapping unchanged |
| `packages/ai-parrot/pyproject.toml` | modifies | Declare `huggingface_hub` explicitly in the `security` extra (currently transitive-only) |
| `benchmarks/injection_guardrail_latency/` | depends on | Parity gate is an acceptance criterion; re-run at `max_length=512` against torch-v2 |
| `bots/guardrails/registry.py` | none | No new registered name — the guardrail stays `"prompt_injection"` |
| `security/prompt_injection.py` | uses | `strip_framework_patterns` unchanged, backend-independent |
| `tests/unit/test_guardrails_prompt_injection.py` | extends | Backend-matrix coverage |
| Deployment / ops | modifies | New env vars; warm-up recommended for long-lived hosts; graph provisioning for air-gapped installs |

### Data Models

No new Pydantic models. The engine abstraction is internal:

```python
# Internal engine protocol (module-private; NOT part of the Guardrail contract)
class _InjectionScoringEngine(Protocol):
    """Produces an injection probability for pre-stripped scan text."""
    engine_name: str          # "onnx" | "pytector"
    model_id: str             # resolved model repo id or local path
    def score(self, text: str) -> float: ...
```

The regex engine is NOT behind this protocol — it keeps its existing
`(sanitized, threats)` path in `check()` exactly as today
(`prompt_injection.py:191-192`).

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py

async def warmup_injection_model(force_download: bool = False) -> str:
    """Resolve, (down)load, and warm the injection classifier.

    The ONLY code path permitted to download the model. Returns the name
    of the engine that ended up selected ("onnx", "pytector", "regex").
    Safe to call multiple times; subsequent calls are no-ops.
    """
```

Environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `PARROT_INJECTION_ONNX_DIR` | unset | Absolute path to a directory holding the ONNX graph + tokenizer files. Wins over everything. |
| `PARROT_INJECTION_ORT_INTRA_OP_THREADS` | `2` | ORT intra-op thread cap for the guardrail session. |
| `PARROT_INJECTION_ORT_INTER_OP_THREADS` | `1` | ORT inter-op thread cap. |

---

## 3. Module Breakdown

### Module 1: Engine resolution & ONNX scoring engine
- **Path**: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py`
- **Responsibility**: `_resolve_injection_engine()` implementing the
  precedence chain (env dir → cached snapshot → pytector-v2-dir →
  pytector-v1-alias → regex), each step with its loud-failure logging;
  the ONNX engine (ORT session with capped threads, tokenizer,
  `truncation=True, max_length=512`, injection-class index resolved from
  the model config — never assumed to be 1); extension of the existing
  singleton/lock to hold the resolved engine.
- **Depends on**: existing module code; `onnxruntime`, `transformers`
  (`AutoTokenizer`), `huggingface_hub` (cache probing only — no network).

### Module 2: `check()` engine swap + empty-input short-circuit
- **Path**: same file
- **Responsibility**: substitute the "produce a probability" step in
  `check()` with the resolved engine; preserve the regex path verbatim;
  short-circuit empty/whitespace-only input to PASS before any model is
  reached; keep threshold compare, security-event logging,
  `_wrap_flagged_input`, BLOCK/TRANSFORM logic byte-for-byte.
- **Depends on**: Module 1.

### Module 3: Warm-up entry point + `AbstractBot` wiring
- **Path**: same file (coroutine) + `packages/ai-parrot/src/parrot/bots/abstract.py` (optional wiring)
- **Responsibility**: `warmup_injection_model()` — resolution,
  `snapshot_download` of the v2 repo (the only download site), session
  construction, one dummy inference. Optional invocation hook for
  long-lived hosts, following the `warmup_embeddings` precedent
  (`abstract.py:1713`) — note there is NO generic warm-up hook to attach
  to (see §6 Does NOT Exist), so wiring is explicit.
- **Depends on**: Module 1.

### Module 4: Packaging + benchmark re-run + docs
- **Path**: `packages/ai-parrot/pyproject.toml`,
  `benchmarks/injection_guardrail_latency/`, `docs/`
- **Responsibility**: declare `huggingface_hub` in the `security` extra;
  re-run the harness at `max_length=512` on v2 (parity gate + restated
  latency figures); ops documentation for the env vars, warm-up, and
  air-gapped graph provisioning; file the follow-up feature ticket for
  the v2 Spanish FP regression.
- **Depends on**: Modules 1–3.

### Module 5: Backend-matrix tests
- **Path**: `tests/unit/test_guardrails_prompt_injection.py` (extend)
- **Responsibility**: resolution-precedence matrix (env dir wins; bad
  env dir falls through with an ERROR log; uncached snapshot treated as
  absent without touching the network; pytector-v2-dir vs v1-alias
  selection; regex floor), thread-cap application, empty-input
  short-circuit, singleton sharing, `check()` behaviour parity across
  engines with a mocked scorer, warm-up idempotence.
- **Depends on**: Modules 1–3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_env_dir_wins_resolution` | 1 | `PARROT_INJECTION_ONNX_DIR` valid → ONNX engine selected, log names engine+model |
| `test_env_dir_invalid_falls_through_loudly` | 1 | Env var set to missing/incomplete dir → ERROR log naming path + missing file, next step tried |
| `test_uncached_snapshot_is_absent_no_network` | 1 | No cache → resolution proceeds to pytector without any network call (HF hub mocked to assert no download) |
| `test_cached_snapshot_selects_onnx` | 1 | Snapshot present in cache → ONNX engine |
| `test_ort_thread_caps_applied` | 1 | SessionOptions receives intra=2/inter=1 by default; env overrides respected (`_env_int` semantics) |
| `test_session_failure_falls_back` | 1 | Corrupt graph → exception logged, pytector fallback, `__init__` never raises |
| `test_injection_index_from_config` | 1 | Class index resolved from model config, not assumed 1 |
| `test_pytector_gets_v2_snapshot_dir` | 1 | Local v2 snapshot + no ONNX usable → pytector constructed with the snapshot directory |
| `test_pytector_v1_alias_warns` | 1 | Nothing local → pytector `"deberta"` alias + WARNING that model is v1, not v2 |
| `test_regex_floor` | 1 | No graph, no pytector → regex engine, as today |
| `test_singleton_shared_across_bots` | 1 | Two guardrail instances share one engine; double-checked lock under concurrent construction |
| `test_empty_input_short_circuits` | 2 | Empty/whitespace input → PASS without reaching any engine |
| `test_check_flow_unchanged` | 2 | With a mocked engine: bypass paths, stripping, threshold, security-event log, BLOCK/TRANSFORM identical to current behaviour |
| `test_warmup_idempotent` | 3 | Second `warmup_injection_model()` call is a no-op |
| `test_warmup_is_only_download_site` | 3 | Construction never downloads; warm-up (mocked `snapshot_download`) does |

### Integration Tests

| Test | Description |
|---|---|
| `test_onnx_engine_scores_real_graph` | With a real local graph (skipped when unavailable): score a known corpus sample, verdict matches torch reference |
| `test_bot_default_on_uses_onnx_when_cached` | An `AbstractBot` with defaults picks up the ONNX engine when a snapshot is cached |

### Test Data / Fixtures

```python
@pytest.fixture
def fake_onnx_dir(tmp_path):
    """Directory that looks like a valid PARROT_INJECTION_ONNX_DIR
    (graph + tokenizer files present) vs variants with files missing."""

@pytest.fixture
def no_hf_cache(monkeypatch):
    """Force huggingface_hub cache probing to report nothing cached and
    assert no network access is attempted."""

@pytest.fixture(autouse=True)
def reset_engine_singleton():
    """Reset the module-level engine singleton between tests."""
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest tests/unit/test_guardrails_prompt_injection.py -v`)
- [ ] **Parity gate green at the shipping configuration**: the
      `benchmarks/injection_guardrail_latency/` harness re-run on
      `protectai/deberta-v3-base-prompt-injection-v2` with
      `max_length=512` shows `clf-onnx` vs `clf-torch` parity
      (0 flipped verdicts) and restated latency figures committed to
      `results-v2/` (the existing figures were measured at 256 and do
      not certify the 512 configuration).
- [ ] The v1→v2 verdict delta is measured and documented
      (`results-v2/delta-v1-to-v2.md` — DONE, commit 637276005; keep it
      referenced from the ops docs).
- [x] **Follow-up feature filed** for the v2 Spanish benign
      false-positive regression (18.8% → 43.8%; threshold retune and/or
      corpus expansion) and referenced from this spec before `/sdd-done`.
      Filed at `sdd/proposals/injection-v2-spanish-fp-mitigation.proposal.md`
      (light proposal — no FEAT id yet; reserved when it is spec'd).
- [ ] No change to the `Guardrail` contract: `name`, `stages`,
      `priority`, `on_error`, `check()` signature identical
      (`guardrails/base.py:119-125`); the guardrail keeps the registered
      name `"prompt_injection"`.
- [ ] `injection_probability_threshold` default remains `0.98`.
- [ ] Construction never performs a network download under any
      resolution outcome (verified by test with HF hub mocked).
- [ ] `warmup_injection_model()` is the only download site; it resolves,
      loads, and runs one dummy inference; idempotent.
- [ ] ORT session is always constructed with thread caps applied
      (default intra=2/inter=1; `PARROT_INJECTION_ORT_*` overrides work).
- [ ] Every fallback step logs loudly: invalid env dir → ERROR naming
      path and missing file; uncached graph → WARNING naming the warm-up
      entry point; pytector-v1 fallback → WARNING naming the model
      mismatch; selected engine logged once at construction.
- [ ] Empty/whitespace input short-circuits to PASS without invoking any
      model.
- [ ] `huggingface_hub` declared explicitly in the `security` extra of
      `packages/ai-parrot/pyproject.toml`.
- [ ] Existing behaviour preserved when nothing is cached and
      `pytector` is installed: identical to today (v1 alias), plus the
      new warning.
- [ ] Ops documentation covers the three env vars, warm-up for
      long-lived hosts, and air-gapped graph provisioning
      (`PARROT_INJECTION_ONNX_DIR`).
- [ ] No breaking changes to the existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references below re-verified on 2026-08-21 against `dev`.

### Verified Imports

```python
from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel,
)                                    # verified: security/__init__.py:8-13
from parrot.bots.guardrails import (
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)                                    # verified: bots/guardrails/__init__.py:14-20
from parrot.bots.guardrails.registry import register_guardrail  # registry.py:56
from huggingface_hub import hf_hub_download, snapshot_download
# ^ importable but TRANSITIVE-ONLY today (via transformers /
#   sentence-transformers). Module 4 declares it in the `security` extra.
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/guardrails/base.py:97-125
class Guardrail(ABC):
    name: str                                    # line 119
    stages: set[GuardrailStage]                  # line 120
    priority: int                                # line 121
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"   # line 122
    @abstractmethod
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:  # line 125
        ...

# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
_SHARED_INJECTION_DETECTOR = None                      # line 53
_SHARED_INJECTION_DETECTOR_LOCK = threading.Lock()     # line 54
def _get_shared_injection_detector():                  # line 57
    # double-checked init; constructs at lines 75-78:
    #   _PytectorDetector(model_name_or_url="deberta", enable_keyword_blocking=True)

class PromptInjectionGuardrail(Guardrail):             # line 82
    name = "prompt_injection"                          # line 102
    stages: ClassVar[set] = {GuardrailStage.INPUT}     # line 103
    priority = 10                                      # line 104
    def __init__(self, strict_mode: bool = True, block_on_threat: bool = False,
                 injection_probability_threshold: float = 0.98, **kwargs: Any) -> None:  # line 106
        self.on_error = "fail_closed" if block_on_threat else "fail_open"   # line 129
        self._framework_sanitizer = PromptInjectionDetector(logger=self.logger)  # line 134
        self._pytector_available = importlib.util.find_spec("pytector") is not None  # line 137
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:   # line 149
        # line 177: scan_text = self._framework_sanitizer.strip_framework_patterns(content)
        # line 180: is_injection, probability = self._pytector_detector.detect_injection(scan_text)
        # line 192: sanitized, threats = self._injection_detector.sanitize(content, strict=True)
    @staticmethod
    def _wrap_flagged_input(text: str, threats: list[dict[str, Any]]) -> str:  # line 232

# packages/ai-parrot/src/parrot/security/prompt_injection.py
class PromptInjectionDetector:                         # line 27
    def add_framework_allowlist(self, pattern: re.Pattern | str) -> None:  # line 113
    def strip_framework_patterns(self, text: str) -> str:                  # line 123
    def sanitize(...)                                                       # line 191
class SecurityEventLogger:                             # line 222
    async def log_injection_attempt(...)               # line 231

# packages/ai-parrot/src/parrot/bots/abstract.py
    strict_mode: bool = True,            # line 290
    block_on_threat: bool = False,       # line 291
    injection_detection: bool = True,    # line 292  <-- DEFAULT ON
    injection_probability_threshold: float = 0.98,    # line 293
    async def warmup_embeddings(self) -> None:   # line 1715 (warm-up precedent)

# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py
def _env_int(name: str, default: int) -> int:          # line 108
    # ORT session-construction discipline to mirror:
    opts = ort.SessionOptions()                                              # line 462
    _intra = _env_int("SUPERTONIC_ORT_INTRA_OP_THREADS", 2)                  # line 469
    if _intra > 0: opts.intra_op_num_threads = _intra                        # lines 470-471
    opts.inter_op_num_threads = _env_int("SUPERTONIC_ORT_INTER_OP_THREADS", 1)  # line 472
    ort.InferenceSession(path, sess_options=opts, providers=providers)       # line 475
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_resolve_injection_engine()` | singleton + lock pattern | extends `_get_shared_injection_detector()` | `prompt_injection.py:53-79` |
| ONNX engine | `check()` probability step | replaces `detect_injection()` call | `prompt_injection.py:180` |
| Engine (any) | framework stripping | `strip_framework_patterns(content)` unchanged | `prompt_injection.py:177`, `security/prompt_injection.py:123` |
| Thread caps | ORT `SessionOptions` | `_env_int`-style helper before construction | `supertonic_inference.py:462-475` |
| `warmup_injection_model()` | warm-up precedent (shape only) | new module-level coroutine | `abstract.py:1715` |
| Parity gate | benchmark harness | `--classifier` / `--max-length` re-run | `benchmarks/injection_guardrail_latency/harness.py` |

### Key Attributes & Constants

- `PromptInjectionGuardrail.priority` → `10` (sanitizer band 0-99) (`prompt_injection.py:104`)
- `injection_probability_threshold` default → `0.98` (`prompt_injection.py:110`)
- `pytector.PromptInjectionDetector.predefined_models` →
  `{"deberta": "protectai/deberta-v3-base-prompt-injection"}` (**v1**)
  (`.venv/.../pytector/detector.py:18-19`)
- `pytector.PromptInjectionDetector.detect_injection(prompt, threshold=None)`
  (`.venv/.../pytector/detector.py:369`)
- **pytector does NOT truncate**: `detector.py:392` calls
  `self.tokenizer(prompt, return_tensors="pt")` with no `truncation` /
  `max_length` — verified 2026-08-21. The fallback therefore diverges
  from the ONNX engine on long inputs by construction.
- Benchmark defaults: `MAX_LENGTH = 256` (`benchmarks/.../detectors.py:47`),
  `intra_op_threads=2, inter_op_threads=1` (`detectors.py:212-213`) —
  the configuration behind all published figures.
- `security` extra today: `pytector==0.2.0`, `onnxruntime>=1.16`
  (`packages/ai-parrot/pyproject.toml:512-534`); `optimum[onnxruntime]`
  is deliberately NOT in `security` (line ~627-635).
- Upstream ONNX artifacts (verified against HF API 2026-08-20, Apache-2.0):
  `protectai/deberta-v3-base-prompt-injection-v2` → `onnx/model.onnx`
  (~700 MB). v1 additionally ships `onnx/model_optimized.onnx`; v2 does not.
- Measured v2 figures (`results-v2/report.md`): torch p50 120.71 ms /
  onnx p50 35.16 ms; parity max|Δ|=0.000, 0 flips; RSS 1641 / 1823 MB.
- Measured v1→v2 delta (`results-v2/delta-v1-to-v2.md`): 21 flips
  (21.9%), 14 better / 7 worse; recall 0.70→0.92; Spanish benign FPs
  18.8%→43.8%; `clean_framework` 12/12 → 11/12.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.security.models`~~ — **does not exist.** No offline model
  registry, no `LocalModelRegistry`, no `PARROT_MODELS_DIR` (brainstorm
  Option C, rejected).
- ~~`pytector.PromptInjectionDetector(model_name_or_url="protectai/deberta-v3-base-prompt-injection-v2")`~~
  — **does NOT work.** A bare HF repo id is not in `predefined_models`,
  fails `validators.url()`, fails `os.path.exists()` → constructor raises
  `ValueError`. A `https://` URL passes `validators.url()` but is handed
  to `AutoTokenizer.from_pretrained()`, which does not accept URLs. **The
  only working v2 input to pytector is a local snapshot directory.**
- ~~`huggingface_hub` as a declared dependency of `ai-parrot`~~ —
  importable but transitive-only today; Module 4 fixes this.
- ~~`onnx/model_optimized.onnx` for v2~~ — exists for v1 only.
- ~~A generic bot-level warm-up hook~~ — `warmup_embeddings`
  (`abstract.py:1715`) is embeddings-specific, called from exactly one
  site. There is no "warm up all models" entry point to hang this on.
- ~~`[tool.ruff]` configuration in the repo~~ — none exists; lint
  expectations are set by surrounding code.
- ~~A `--max-length` flag in the benchmark harness~~ —
  `MAX_LENGTH` is a module constant (`detectors.py:47`)
  (unverified whether the harness CLI exposes it — check before use; if
  not, the 512 re-run edits the constant or adds the flag).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Singleton + double-checked lock** for the shared engine — extend the
  exact pattern at `prompt_injection.py:53-79`; never two parallel
  session loads.
- **Lazy optional-import discipline** — `importlib.util.find_spec`
  gating (`prompt_injection.py:137`); neither this module nor
  `parrot.bots.guardrails` may import `onnxruntime`/`torch`/`pytector`
  at module import time. This module owns the import boundary.
- **ORT session construction** — mirror
  `supertonic_inference.py:462-475`: build `SessionOptions`, set both
  thread caps from `_env_int`-style helpers, THEN construct the session.
- **`_env_int` helper** — copy the semantics of
  `supertonic_inference.py:108` (blank/unparseable → default).
- **Never propagate from `__init__`** — every resolution failure logs
  and falls through; the guardrail must always construct.
- **`check()` byte-for-byte** — bypasses, stripping, threshold compare,
  event logging, `max()` severity quirk (`prompt_injection.py:210-215`,
  preserved intentionally), BLOCK report shape, `_wrap_flagged_input`.
- **Injection class index from model config** — read `id2label` (or
  equivalent) from the model/config files; never hardcode index 1.
- **Async-first** — `warmup_injection_model()` is a coroutine; the
  download and dummy inference run via `asyncio.to_thread`/executor so
  warm-up itself never blocks the loop.
- Google-style docstrings + strict type hints; `self.logger`/module
  `logger`, no prints.

### Known Risks / Gotchas

- **v2 is a behaviour change, measured**: 21.9% of verdicts flip vs v1.
  Better: attacks (direct 15/20→20/20, paraphrase 10/20→16/20, recall
  0.70→0.92). Worse: **Spanish benign false positives 18.8%→43.8%**
  (plain business Spanish scored at 1.0000) and `clean_framework`
  12/12→11/12. Spanish bucket is n=16 — effect large, sample small.
  Mitigations: default is TRANSFORM (wrap), not BLOCK; the mandatory
  follow-up feature (threshold retune / corpus expansion) is an
  acceptance criterion; rollback is a deploy.
- **The published latency/parity figures certify `max_length=256`**, not
  the shipping 512. The 512 re-run is a hard gate; if 512 materially
  degrades latency, escalate before merge rather than silently shipping
  slower numbers.
- **Truncation divergence on the fallback**: pytector never truncates;
  the ONNX engine truncates at 512. Inputs beyond 512 tokens may score
  differently across engines. Documented limitation; do not paper over
  by patching pytector.
- **Hybrid-resolution failure modes to enumerate in tests**: env var set
  but empty/missing/partial dir; cache present but corrupt; partial
  snapshot (graph without tokenizer files); ORT rejects the graph (bad
  opset). Every one falls through loudly.
- **ORT uncapped = event-loop starvation**: ORT sizes its intra-op pool
  to all physical cores per session. Caps are set before construction,
  always (hard-won lesson: `supertonic_inference.py:462-472`).
- **Inference failure at request time** is NOT new handling: the
  existing `on_error` contract applies (`fail_closed` when
  `block_on_threat`, else `fail_open` — `prompt_injection.py:129`).
- **This feature does not fix blocking or memory**: `check()` still
  blocks the loop for ~35 ms p50 (executor route = follow-up feature),
  and ONNX RSS is *higher* than torch (1823 vs 1641 MB).
- **HF cache probing must be offline**: use `local_files_only=True` /
  `try_to_load_from_cache`-style APIs; a "probe" that silently
  downloads violates the no-download-on-request-path constraint.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `onnxruntime` | `>=1.16` | Runs the graph; releases the GIL during `Run()`. Already in `security` extra. |
| `huggingface_hub` | (align with `transformers` pin) | Cache probing + `snapshot_download` in warm-up. **Must be added to the `security` extra** (transitive-only today; note line ~391: whisperx pins `huggingface-hub<1.0`). |
| `transformers` | existing pin | `AutoTokenizer` for the ONNX path. Already arrives with `pytector`. |
| `pytector` | `==0.2.0` | Fallback engine. Unchanged. |

---

## 8. Open Questions

> Decision trail — resolved items are carried from the brainstorm, the
> post-brainstorm measurement commit (637276005), spec-time code
> research, and the user's spec-time answers (2026-08-21).

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Where does the ONNX graph come from at runtime? — *Resolved in
  brainstorm*: Hybrid — `PARROT_INJECTION_ONNX_DIR` wins, else a cached
  HF snapshot of the upstream graph, else pytector.
- [x] What happens when the graph is unavailable? — *Resolved in
  brainstorm*: Loud warning plus fallback to pytector. Never fail-closed
  on an optimisation; never silent.
- [x] Is ONNX opt-in or automatic? — *Resolved in brainstorm*:
  Auto-preferred whenever a graph resolves; justified because measured
  parity is exact.
- [x] Do we remove pytector / the torch stack here? — *Resolved in
  brainstorm*: No. It stays as the fallback; the `security` extra keeps
  it. Removal is a later ticket.
- [x] Do we export our own graph or consume upstream? — *Resolved in
  brainstorm*: Consume ProtectAI's upstream `onnx/model.onnx`
  (Apache-2.0). `benchmarks/.../export.py` remains a verification tool.
- [x] v1 or v2 of the classifier? — *Resolved in brainstorm*: **v2**.
  *Re-confirmed at spec time with the measured delta in hand*: v2 stands
  **with a mandatory follow-up ticket** for the Spanish FP regression
  (see acceptance criteria).
- [x] What is the parity gate's reference, given v2? — *Resolved in
  brainstorm*: torch-v2, plus a separately measured v1→v2 verdict delta.
  *Delta delivered* in `results-v2/delta-v1-to-v2.md` (commit 637276005).
- [x] How is the v2 behaviour change rolled out? — *Resolved in
  brainstorm*: Direct switch, no version knob. Rollback is a deploy.
- [x] When is the ~700 MB graph downloaded? — *Resolved in brainstorm*:
  Only in the explicit warm-up. The request path never downloads.
- [x] Is the 96-sample parity gate a sufficient acceptance bar? —
  *Resolved in brainstorm*: Yes for parity; not for the v1→v2 delta,
  which was measured separately (done).
- [x] How does the pytector fallback actually load v2? — *Resolved at
  spec time (user, 2026-08-21)*: pytector is pointed at a **local v2
  snapshot directory** when one exists; when nothing local exists it
  falls back to today's exact behaviour (`"deberta"` alias = v1) with a
  **loud warning** naming the model mismatch. Worst case = today.
- [x] Are the measured latency figures still valid for v2? — *Resolved
  by measurement (commit 637276005)*: yes — torch p50 120.71 ms vs onnx
  p50 35.16 ms, exact parity (0 flips). Figures restated in §1.
- [x] Should `huggingface_hub` be declared in the `security` extra? —
  *Resolved at spec time*: yes — the HF-cache branch ships, so the
  transitive-only dependency becomes explicit (Module 4).
- [x] What are the default ORT thread caps for this guardrail? —
  *Resolved at spec time (user, 2026-08-21)*: **intra=2 / inter=1**,
  matching the exact configuration the benchmark figures were measured
  under and the `SUPERTONIC_ORT_*` precedent; env-overridable.
- [x] Does the truncation policy match across backends? — *Resolved by
  code research (2026-08-21)*: **No.** pytector does not truncate at all
  (`pytector/detector.py:392`); the benchmark used 256. *User decision*:
  the ONNX engine ships `truncation=True, max_length=512`; the parity
  gate and latency figures MUST be re-run at 512 before merge; the
  fallback divergence on long inputs is a documented limitation.
- [ ] Does the benchmark harness CLI expose `MAX_LENGTH`, or does the
  512 re-run require a small harness change? — *Owner: implementer*
  (check `harness.py` at task time; either way the re-run is required).
- [ ] Exact `huggingface_hub` version bound compatible with the whisperx
  `huggingface-hub<1.0` pin (`pyproject.toml:391`) — *Owner: implementer*
  (resolve during Module 4; must not break the audio pipeline extra).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree, tasks sequential.
- **Rationale**: nearly all work lands in one file
  (`bots/guardrails/builtin/prompt_injection.py`) with a strict
  dependency order (resolve → construct session → warm up → swap
  engine). Parallel worktrees gain nothing and pay merge cost.
- **Cross-feature dependencies**: none in-flight touch this file. The
  follow-up executor/`BudgetRouter` feature must land AFTER this one to
  avoid rebasing the same call site twice.
  `benchmarks/injection_guardrail_latency/` is shared but read-mostly.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-21 | Jesús Lara + Claude Code | Initial draft from brainstorm (Option A) + v2 measurements + spec-time decisions |
