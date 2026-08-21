# TASK-2307: ONNX scoring engine + hybrid engine resolution

**Feature**: FEAT-439 — ONNX Backend for the Prompt-Injection Guardrail
**Spec**: `sdd/specs/onnx-injection-guardrail-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 — the core of FEAT-439. `PromptInjectionGuardrail`
currently produces its injection probability via pytector/torch
(p50 ~121 ms). This task builds the engine layer: an ONNX Runtime
scoring engine (p50 ~35 ms, exact parity) and the once-at-construction
hybrid resolution chain that picks the best locally-available engine,
loudly. Later tasks swap `check()` onto it (TASK-2308) and add warm-up
(TASK-2309).

## Scope

All inside
`packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py`:

- Implement an internal engine protocol (spec §2 Data Models):
  `engine_name: str`, `model_id: str`, `def score(self, text: str) -> float`.
- Implement `_OnnxInjectionEngine`: ORT session + `AutoTokenizer`,
  tokenizing with `truncation=True, max_length=512`; injection-class
  index resolved from the model config (`id2label` or equivalent),
  NEVER hardcoded to 1; softmax over logits to a probability.
- Implement `_PytectorInjectionEngine`: thin adapter over
  `pytector.PromptInjectionDetector.detect_injection()` exposing the
  same `score()` shape; constructed either from a **local v2 snapshot
  directory** (pytector's `os.path.exists()` branch) or from the
  `"deberta"` alias (=v1) as last resort.
- Implement `_resolve_injection_engine()` — process-wide singleton
  behind a double-checked lock (extend the existing pattern, lines
  53-79), precedence:
  1. `PARROT_INJECTION_ONNX_DIR` (valid dir with graph + tokenizer
     files) → ONNX. Invalid/incomplete → **ERROR log naming the path
     and the missing file**, fall through.
  2. Cached HF snapshot of
     `protectai/deberta-v3-base-prompt-injection-v2` containing
     `onnx/model.onnx` → ONNX. **Cache probing must be strictly
     offline** (`local_files_only=True` semantics); uncached = absent,
     with a WARNING naming `warmup_injection_model()` as the fix.
  3. `pytector` importable: local v2 snapshot dir (from step 2's probe,
     even if the ONNX file specifically was missing/corrupt) →
     pytector-on-v2; else `"deberta"` alias with a **WARNING that the
     fallback model is v1, not the intended v2**.
  4. Nothing → return `None`; the guardrail keeps its existing regex
     path (regex is NOT wrapped in the engine protocol).
- ORT `SessionOptions` construction: a module-local `_env_int` helper
  (copy semantics from `supertonic_inference.py:108`); caps
  `intra_op_num_threads` = `PARROT_INJECTION_ORT_INTRA_OP_THREADS`
  (default 2), `inter_op_num_threads` =
  `PARROT_INJECTION_ORT_INTER_OP_THREADS` (default 1) — set BEFORE
  `InferenceSession` construction, always.
- Every resolution outcome logs ONE construction-time line naming the
  selected engine and model. Resolution failures never propagate out of
  `__init__` — any exception (corrupt graph, bad opset, tokenizer load
  failure) logs and falls through.
- Lazy imports only: `onnxruntime`, `transformers`, `huggingface_hub`,
  `pytector` are imported inside functions, never at module import time
  (this module owns the import boundary — module docstring, lines 7-21).
- Unit tests for this layer (resolution matrix, caps, index-from-config,
  singleton) — the broader behaviour matrix lands in TASK-2310.

**NOT in scope**: touching `check()` (TASK-2308); warm-up/download
(TASK-2309 — this task NEVER downloads); pyproject changes (TASK-2311);
the regex engine (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | Engine protocol, ONNX + pytector engines, `_resolve_injection_engine()`, `_env_int`, singleton extension |
| `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` | MODIFY | Resolution-layer unit tests (subset; full matrix in TASK-2310) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verify each anchor with `read`/`grep` before coding; if
> drifted, update this contract first.

### Verified Imports

```python
# Already present in the module:
from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel,
)                                    # verified: security/__init__.py:8-13
# Lazy (function-local) imports this task adds:
import onnxruntime as ort            # security extra: onnxruntime>=1.16 (pyproject:534)
from transformers import AutoTokenizer
from huggingface_hub import snapshot_download   # TRANSITIVE-ONLY dep today;
#   use for offline cache probing here (local_files_only) — TASK-2311
#   declares it. Also available: try_to_load_from_cache / scan_cache_dir —
#   verify the exact probing API against the installed version first.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
_SHARED_INJECTION_DETECTOR = None                      # line 53
_SHARED_INJECTION_DETECTOR_LOCK = threading.Lock()     # line 54
def _get_shared_injection_detector():                  # line 57
    # double-checked lock; constructs at lines 75-78:
    #   _PytectorDetector(model_name_or_url="deberta", enable_keyword_blocking=True)
class PromptInjectionGuardrail(Guardrail):             # line 82
    def __init__(self, strict_mode=True, block_on_threat=False,
                 injection_probability_threshold=0.98, **kwargs) -> None:  # line 106
        self._pytector_available = importlib.util.find_spec("pytector") is not None  # line 137
        self._pytector_detector = _get_shared_injection_detector()  # line 142 (when available)

# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py
def _env_int(name: str, default: int) -> int:          # line 108 — copy semantics
    # blank/unparseable env value → default
opts = ort.SessionOptions()                            # line 462
_intra = _env_int("SUPERTONIC_ORT_INTRA_OP_THREADS", 2)      # line 469
if _intra > 0: opts.intra_op_num_threads = _intra            # lines 470-471
opts.inter_op_num_threads = _env_int("SUPERTONIC_ORT_INTER_OP_THREADS", 1)  # line 472
ort.InferenceSession(path, sess_options=opts, providers=providers)          # line 475

# pytector (installed 0.2.0, .venv/lib/python3.12/site-packages/pytector/detector.py)
predefined_models = {"deberta": "protectai/deberta-v3-base-prompt-injection"}  # lines 18-19 (v1!)
def detect_injection(self, prompt, threshold=None):    # line 369 → (bool, float)
# ctor accepts: alias in predefined_models | https URL (broken downstream) |
#   an EXISTING LOCAL PATH (os.path.exists branch) — the ONLY working v2 input
# pytector does NOT truncate: line 392 tokenizes with no max_length
```

### Key Constants / Facts

- Upstream model: `protectai/deberta-v3-base-prompt-injection-v2`,
  ONNX graph at repo path `onnx/model.onnx` (~700 MB, Apache-2.0).
- v2 does NOT ship `onnx/model_optimized.onnx` (v1 only).
- ONNX tokenization: `truncation=True, max_length=512` (user decision;
  the parity gate at 512 is TASK-2306's deliverable).
- Env vars owned by this task: `PARROT_INJECTION_ONNX_DIR`,
  `PARROT_INJECTION_ORT_INTRA_OP_THREADS` (default 2),
  `PARROT_INJECTION_ORT_INTER_OP_THREADS` (default 1).

### Does NOT Exist

- ~~`parrot.security.models` / `LocalModelRegistry` / `PARROT_MODELS_DIR`~~
  — no offline model registry exists (brainstorm Option C, rejected).
- ~~`pytector.PromptInjectionDetector(model_name_or_url="protectai/deberta-v3-base-prompt-injection-v2")`~~
  — raises `ValueError`: a bare repo id is not an alias, not a URL, not
  a path. Only a local directory works for v2.
- ~~`huggingface_hub` in `[security]` extra~~ — transitive-only until
  TASK-2311; import it lazily and defensively.
- ~~A shared `parrot` helper for `_env_int`~~ — the supertonic one lives
  in `ai-parrot-integrations` (a different distribution); core cannot
  import it. Define a module-local copy.
- ~~`[tool.ruff]` config in the repo~~ — none; match surrounding style.

---

## Implementation Notes

### Pattern to Follow

The existing singleton (lines 53-79) is the exact template: module-level
`None` + `threading.Lock` + double-checked init inside a getter. Extend
to hold a *resolved engine* (or an explicit "resolved: none" sentinel so
failed resolution isn't retried on every construction — but DO allow
`warmup_injection_model()` (TASK-2309) to force re-resolution after a
download).

### Key Constraints

- No network, ever, in this task's code paths. Cache probing offline.
- No module-level heavy imports (there is an existing subprocess test
  asserting torch is not imported at module import time —
  `test_lazy_import_no_torch_at_module_import`; it must keep passing).
- `ort.InferenceSession.Run()` releases the GIL — no special handling
  here; async offloading is the follow-up feature, not this one.
- Softmax carefully: the graph outputs logits; verify output names/shape
  against the real graph rather than assuming (`session.get_outputs()`).
- Type hints + Google docstrings; module `logger` (exists, line 41).

### References in Codebase

- `prompt_injection.py:53-79` — singleton pattern to extend
- `supertonic_inference.py:462-475` — ORT session discipline
- `benchmarks/injection_guardrail_latency/detectors.py:289-298` — the
  reference tokenize-and-run implementation the benchmark used (np
  tensors for ONNX) — mirror its numerics

---

## Acceptance Criteria

- [ ] Resolution precedence implemented exactly as specified, each
      fallback step logging loudly (ERROR for misconfigured env dir,
      WARNING for uncached graph naming the warm-up, WARNING for v1
      fallback naming the model mismatch).
- [ ] Selected engine + model logged once at construction.
- [ ] ORT session always constructed with caps (default intra=2/inter=1;
      env overrides honored; `_env_int` semantics).
- [ ] Injection class index read from model config, never assumed.
- [ ] `__init__` can never raise from resolution; worst case = today's
      behaviour (pytector v1 alias, or regex).
- [ ] No download in any code path of this task.
- [ ] Singleton: two guardrails share one engine; concurrent first
      construction is safe.
- [ ] Module-import purity preserved
      (`test_lazy_import_no_torch_at_module_import` still green).
- [ ] New unit tests pass:
      `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -v`
- [ ] Existing tests in that file still pass unmodified in behaviour.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py (extend)
# Follow the file's existing convention: patch module-level names, never
# load real models. Reset the new engine singleton in a fixture.

class TestEngineResolution:
    def test_env_dir_wins(self, fake_onnx_dir, monkeypatch): ...
    def test_env_dir_invalid_falls_through_with_error_log(self, tmp_path, monkeypatch, caplog): ...
    def test_uncached_snapshot_absent_no_network(self, monkeypatch): ...
        # hf probing mocked; assert no download API is called
    def test_pytector_v2_snapshot_dir_used_when_present(self, monkeypatch): ...
    def test_pytector_v1_alias_warns(self, monkeypatch, caplog): ...
    def test_regex_floor_when_nothing_available(self, monkeypatch): ...
    def test_ort_thread_caps_default_and_env_override(self, fake_onnx_dir, monkeypatch): ...
    def test_session_failure_falls_back_never_raises(self, monkeypatch): ...
    def test_injection_index_from_config_not_hardcoded(self, fake_onnx_dir): ...
    def test_singleton_shared_and_lock_safe(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task (TASK-2306 runs in
   parallel; if its 512 parity result is already in
   `results-v2-512/report.md`, confirm it passed before relying on 512)
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/onnx-injection-guardrail-backend.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Code)
**Date**: 2026-08-21
**Notes**:
- Implemented in
  `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py`:
  `_InjectionScoringEngine` (Protocol), `_OnnxInjectionEngine`,
  `_PytectorInjectionEngine`, `_env_int`, `_softmax`,
  `_resolve_injection_index` (reads `id2label` from `config.json`, never
  assumes index 1), `_probe_cached_onnx_snapshot` /
  `_probe_cached_v2_snapshot_dir` (both offline-only, via
  `huggingface_hub.try_to_load_from_cache` — verified against the
  installed `huggingface_hub==0.36.2` signature), the four
  `_try_build_*`/`_do_resolve_injection_engine` resolution steps, and
  `_resolve_injection_engine()` — the process-wide singleton extending
  the `_get_shared_injection_detector` double-checked-lock pattern, using
  a distinct `_UNSET` sentinel so a legitimate "resolved to regex" (`None`)
  outcome is memoized instead of retried, and a `force_reresolve` param
  for TASK-2309's warm-up hook.
- Precedence implemented exactly per spec: env dir -> cached HF snapshot
  -> pytector (local v2 snapshot dir, else `"deberta"` v1 alias, reusing
  the EXISTING shared singleton for the v1 case so today's memory-sharing
  behavior is preserved byte-for-byte) -> `None` (regex floor). Every
  fallback step logs (ERROR for a misconfigured env dir naming the path
  and missing file; WARNING for an uncached snapshot naming
  `warmup_injection_model()`; WARNING for the v1 fallback naming the
  model mismatch); the selected engine + model is logged once on success.
- ORT session construction mirrors `supertonic_inference.py:462-475`
  exactly: `SessionOptions()` built and thread caps (`PARROT_INJECTION_ORT_INTRA_OP_THREADS`
  default 2, `PARROT_INJECTION_ORT_INTER_OP_THREADS` default 1) applied
  BEFORE `InferenceSession()` construction.
- `onnxruntime`/`transformers`/`huggingface_hub`/`pytector` are all
  imported lazily, function-local only — confirmed via the existing
  `test_lazy_import_no_torch_at_module_import` subprocess test (still
  green) and by construction (no top-level imports added).
- Added `TestEngineResolution` (11 tests) to
  `test_guardrails_prompt_injection.py`, covering: env-dir-wins,
  invalid-env-dir-falls-through-with-ERROR, uncached-snapshot-no-network,
  pytector-v2-snapshot-dir-used, pytector-v1-alias-WARNING, regex floor,
  ORT thread-cap default + env override, session-construction-failure
  never raises, injection-index-from-config (not hardcoded), singleton
  sharing, and `force_reresolve` bypass. Added the `fake_onnx_dir` and
  `fake_ort_and_transformers` fixtures (fake `sys.modules` entries — no
  real graph, no network) and an autouse `reset_engine_singleton` fixture
  (required as soon as any test exercises `_resolve_injection_engine()`,
  since it is a process-wide memoized singleton) — TASK-2310 will
  consolidate/extend these per its own scope.
- Full suite: `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -v`
  — 24 passed (13 pre-existing + 11 new), assertions on pre-existing tests
  unmodified. `ruff check` clean on both touched files.
- Verified in this environment: `parrot` resolves via an editable install
  pointing at the MAIN repo checkout, not this worktree, so running tests
  here requires `PYTHONPATH` prepended with this worktree's
  `packages/*/src` dirs (plus the compiled `parrot.utils.types` /
  `parrot.utils.parsers.toml` `.so` extensions copied in from the main
  repo, since Cython artifacts aren't rebuilt per-worktree) — a
  worktree-testing mechanic, not a code change.

**Deviations from spec**: none.
