# TASK-2309: warmup_injection_model() — the only download site

**Feature**: FEAT-439 — ONNX Backend for the Prompt-Injection Guardrail
**Spec**: `sdd/specs/onnx-injection-guardrail-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2307
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Resolution (TASK-2307) is strictly offline — an
uncached graph is treated as absent. Something must therefore be allowed
to fetch the ~700 MB v2 graph, exactly once, at a moment the operator
chooses: an explicit warm-up coroutine invoked at startup by long-lived
hosts. It is the ONLY code path in the feature permitted to download,
and it also absorbs cold-start (session construction + one dummy
inference) so the first real turn pays nothing.

## Scope

- Implement module-level coroutine
  `async def warmup_injection_model(force_download: bool = False) -> str`
  in `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py`:
  1. If `PARROT_INJECTION_ONNX_DIR` is set and valid → no download
     needed; resolve + load + dummy-infer from it.
  2. Else `snapshot_download("protectai/deberta-v3-base-prompt-injection-v2", ...)`
     scoped to the files the engine needs (the `onnx/model.onnx` graph +
     tokenizer/config files — use `allow_patterns` to avoid pulling the
     torch weights too; verify pattern support against the installed
     `huggingface_hub`). Honor `force_download`.
  3. Force re-resolution of the engine singleton (TASK-2307 exposes this)
     so a pre-warm-up "resolved: none/pytector" outcome is upgraded.
  4. Run one dummy inference through the resolved engine.
  5. Return the selected engine name (`"onnx" | "pytector" | "regex"`).
- Blocking work (download, session build, dummy inference) runs via
  `asyncio.to_thread` (or loop executor) — warm-up itself must not block
  the loop.
- Idempotent: a second call with an already-warm engine is a fast no-op
  (unless `force_download=True`).
- Failure is loud but non-fatal: a failed download logs the exception
  and returns whatever engine still resolves (pytector/regex) — hosts
  must start even offline.
- Optional `AbstractBot` wiring: expose an explicit way for bots/hosts
  to invoke it, mirroring the `warmup_embeddings` precedent
  (`abstract.py:1715`). Add an `async def warmup_injection(self)` thin
  delegate on `AbstractBot` ONLY if it can be done without touching the
  `injection_detection` flag semantics; otherwise document module-level
  invocation in the docstring and leave `abstract.py` untouched (spec
  notes there is NO generic warm-up hook — do not invent one).
- Unit tests: idempotence, only-download-site, offline-failure fallback.

**NOT in scope**: automatic warm-up on bot construction (downloading
inside `__init__` is exactly what the spec forbids); server/handler
startup integration (ops docs in TASK-2311 tell operators to call it);
engine internals (TASK-2307).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | `warmup_injection_model()` coroutine |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY (optional) | Thin `warmup_injection()` delegate next to `warmup_embeddings` — only if clean |
| `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` | MODIFY | Warm-up tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verify each anchor with `read`/`grep` before coding —
> TASK-2307 changed this module; re-anchor first.

### Verified Imports

```python
from huggingface_hub import snapshot_download   # importable (transitive today;
#   declared by TASK-2311). Signature: snapshot_download(repo_id, *,
#   allow_patterns=..., local_files_only=..., force_download=..., ...) —
#   verify kwargs against the INSTALLED version (whisperx pins
#   huggingface-hub<1.0, pyproject:391) before use.
import asyncio   # asyncio.to_thread for blocking work
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
async def warmup_embeddings(self) -> None:   # line 1715 — the precedent:
    # embeddings-specific, called from exactly ONE site (abstract.py:~1598);
    # copy its SHAPE (explicit, opt-in coroutine), not its wiring.

# From TASK-2307 (verify final names in the module):
_resolve_injection_engine()        # singleton resolution; offline-only
# + whatever re-resolution hook TASK-2307 exposed (e.g. a reset/force param)
# Engine protocol: .engine_name, .model_id, .score(text) -> float
```

### Key Facts

- Repo: `protectai/deberta-v3-base-prompt-injection-v2`; graph path
  inside repo: `onnx/model.onnx` (~700 MB). v2 has NO
  `model_optimized.onnx`.
- `PARROT_INJECTION_ONNX_DIR` wins over the cache — warm-up with it set
  must not download.
- Construction-time resolution stays offline; ONLY this coroutine
  downloads. There is a test in the matrix (TASK-2310) asserting this.

### Does NOT Exist

- ~~A generic "warm up all models" bot/host hook~~ — nothing to hang
  this on; `warmup_embeddings` is embeddings-specific.
- ~~`AbstractBot.warmup_injection`~~ — does not exist yet; this task MAY
  add it (optional, only if clean).
- ~~Automatic startup invocation~~ — no handler/server code calls
  warm-up; operators do (documented in TASK-2311).
- ~~`hf_hub_download` for multi-file fetch~~ — use `snapshot_download`
  with `allow_patterns`; a single-file `hf_hub_download` of the graph
  would miss tokenizer/config files the engine needs.

---

## Implementation Notes

### Key Constraints
- Never let warm-up failure propagate: log + return the degraded engine
  name.
- Concurrent warm-up calls must not double-download: guard with a lock
  (an `asyncio.Lock` at coroutine level around the to_thread work, or
  reuse the resolution lock discipline — document the choice).
- Google docstring must state loudly: "the only code path permitted to
  download the model."
- If adding the `AbstractBot` delegate: keep it 3-5 lines, no new flags,
  no behaviour change for bots that never call it.

### References in Codebase
- `abstract.py:1715` — `warmup_embeddings` shape
- `prompt_injection.py` module docstring (lines 7-21) — import-boundary
  rules that still apply inside the coroutine (lazy imports)

---

## Acceptance Criteria

- [ ] `warmup_injection_model()` resolves, downloads (when needed and
      permitted), loads, dummy-infers, returns the engine name.
- [ ] It is demonstrably the only download site (construction paths
      never download — regression-tested).
- [ ] Idempotent; `force_download=True` re-fetches.
- [ ] Download/session/dummy-inference run off-loop
      (`asyncio.to_thread`/executor).
- [ ] Offline failure → loud log + graceful fallback engine name; never
      raises to the caller.
- [ ] Concurrent calls download at most once.
- [ ] `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -v` green.

---

## Test Specification

```python
class TestWarmup:
    async def test_warmup_downloads_when_uncached(self, monkeypatch): ...
        # snapshot_download mocked; assert called with v2 repo id + allow_patterns
    async def test_warmup_skips_download_with_env_dir(self, fake_onnx_dir, monkeypatch): ...
    async def test_warmup_idempotent(self, monkeypatch): ...
    async def test_warmup_failure_falls_back_loudly(self, monkeypatch, caplog): ...
    async def test_construction_never_downloads(self, monkeypatch): ...
    async def test_concurrent_warmup_single_download(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2307 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-anchor line numbers post-2307
4. **Update status** in `sdd/tasks/index/onnx-injection-guardrail-backend.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
