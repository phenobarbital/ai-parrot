# TASK-4828: Chassis — embedding-similarity engine + `score_async` offload in injection `check()`

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4827
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, second half (design-research S3 + S8).

1. **S3 — event-loop blocking (verified)**: `PromptInjectionGuardrail.check()` calls
   `self._injection_engine.score(scan_text)` synchronously (`prompt_injection.py:779`);
   only warm-up uses `asyncio.to_thread`. With a second ML guardrail (jailbreak) per
   INPUT, two synchronous ONNX inferences would run on the loop thread every turn.
   Add `score_async()` to the chassis and use it at that call site.
2. **Embedding engine shape**: the bake-off (TASK-4831/4832) measures embedding
   candidates, and a future licensed embedding model must plug in. Add
   `EmbeddingSimilarityEngine` (ONNX backbone → mean pooling → L2 norm → max cosine
   vs a pre-embedded corpus matrix) and wire `kind="embedding"` into `_build_engine`.
   v1 ships no corpus (spec §8 resolved), so resolution of an embedding spec requires
   `<PREFIX>_CORPUS` (a `.npy` matrix path) and returns `None` without it.

---

## Scope

- Add `score_async(engine, text)` to `_engine_chassis.py`.
- Add `EmbeddingSimilarityEngine` + `load_corpus_matrix(path)`; extend `_build_engine`
  for `kind="embedding"` (requires `<PREFIX>_CORPUS`, else resolution yields `None` with a WARNING).
- Replace the synchronous call at `prompt_injection.py:779` with `await score_async(...)`.
- Tests.

**NOT in scope**: any corpus artifact; jailbreak guardrail; `scan_tool_output`
(TASK-4833 — same file, runs after this task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/_engine_chassis.py` | MODIFY | embedding engine, corpus loader, `score_async` |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | offload scoring in `check()` |
| `packages/ai-parrot/tests/unit/test_guardrails_engine_chassis_embedding.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.builtin._engine_chassis import (
    EngineSpec, ScoringEngine, load_tokenizer, resolve_engine, _build_engine, _reset_chassis_state,
)  # created by TASK-4827
```

### Existing Signatures to Use
```python
# _engine_chassis.py (TASK-4827)
def _build_engine(spec, tokenizer_dir, graph_path, model_id) -> ScoringEngine  # raises ValueError for non-classifier kinds today
class ClassifierOnnxEngine: ...  # session construction pattern to copy (ORT caps via env_int)

# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:   # :743
    probability = self._injection_engine.score(scan_text)                         # :779 — target
# tests patch engines with MagicMock/fake objects exposing .score — to_thread works with them

# Reference implementation of the embedding math (benchmark, verified):
# benchmarks/injection_guardrail_latency/detectors.py:110-153 EmbedCosineDetector + _l2_normalise
# 0din model card contract: inputs input_ids/attention_mask/token_type_ids(zeros); output[0] = token embeddings
#   [batch, seq, dim]; mean-pool with attention mask; L2-normalize; cosine = dot.
```

### Does NOT Exist
- ~~`EmbeddingSimilarityEngine`, `load_corpus_matrix`, `score_async`~~ — created here.
- ~~a bundled reference corpus~~ — none ships in v1; never add package data here.
- ~~`asyncio.to_thread` in `check()` today~~ — only in `warmup_injection_model`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/_engine_chassis.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_engine_chassis_embedding.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#PromptInjectionGuardrail.check"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `score_async` — *why*: S3; one helper every ML guardrail awaits.
2. Swap `prompt_injection.py:779` to `await score_async(...)` and run the injection suites — *why*: proves the offload is transparent to mocks.
3. Add `load_corpus_matrix` + `EmbeddingSimilarityEngine`, extend `_build_engine` — *why*: second engine shape behind the same protocol.
4. Tests.

### `_engine_chassis.py` (MODIFY)
```python
# AFTER — insert below the ScoringEngine protocol (created by TASK-4827; re-locate with grep -n 'class ScoringEngine')
async def score_async(engine: ScoringEngine, text: str) -> float:
    """Run ``engine.score(text)`` in a worker thread — never on the event loop.

    ORT sessions are thread-capped at construction, so concurrent offloads
    cannot oversubscribe the CPU beyond the configured intra/inter-op caps.
    """
    return await asyncio.to_thread(engine.score, text)


def load_corpus_matrix(path: Path) -> Any:
    """Load a pre-embedded ``(N, d)`` float32 ``.npy`` corpus and L2-normalize rows.

    Raises:
        ValueError: The file is not a 2-D matrix or has zero rows.
    """
    # FILL IN: numpy.load(path, allow_pickle=False) (lazy numpy import), validate ndim==2 and N>0,
    # astype float32, row-normalize with a 1e-9 zero-norm guard — bounded by "never allow_pickle"


class EmbeddingSimilarityEngine:
    """ONNX embedding backbone; score = max cosine vs a reference corpus, clamped to [0, 1]."""
    engine_name = "onnx-embedding"

    def __init__(self, tokenizer_dir: Path, graph_path: Path, model_id: str, corpus_matrix: Any, *,
                 env_prefix: str, max_length: int = DEFAULT_MAX_LENGTH) -> None:
        """Load tokenizer + thread-capped session (same caps as ClassifierOnnxEngine)."""
        # FILL IN: tokenizer via load_tokenizer; ORT session exactly like ClassifierOnnxEngine;
        # store corpus (already normalized) and input names — bounded by "never downloads"

    def score(self, text: str) -> float:
        """Mean-pool token embeddings with the attention mask, L2-normalize, max cosine vs corpus."""
        # FILL IN: feed only the session's declared inputs; add token_type_ids zeros if the graph declares it
        # and the tokenizer did not emit it; output[0] = [1, seq, d]; clamp negatives to 0.0
```
```python
# REPLACE the `raise ValueError(f"engine kind {spec.kind!r} not supported yet")` line in _build_engine with:
    corpus_env = os.environ.get(f"{spec.env_prefix}_CORPUS")
    if spec.kind == "embedding":
        if not corpus_env:
            raise FileNotFoundError(f"{spec.env_prefix}_CORPUS is not set (embedding engines need a reference corpus)")
        return EmbeddingSimilarityEngine(
            tokenizer_dir, graph_path, model_id, load_corpus_matrix(Path(corpus_env)),
            env_prefix=spec.env_prefix, max_length=spec.max_length,
        )
    raise ValueError(f"unknown engine kind {spec.kind!r}")
```
**Why**: `_do_resolve` already catches construction errors and falls through to `None`, so a missing corpus degrades loudly to the heuristic floor.

### `prompt_injection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            probability = self._injection_engine.score(scan_text)' prompt_injection.py)
# REPLACE (verified: prompt_injection.py:779) with:
            probability = await score_async(self._injection_engine, scan_text)
# and extend the chassis import added by TASK-4827 with `score_async`.
```

### `packages/ai-parrot/tests/unit/test_guardrails_engine_chassis_embedding.py` (CREATE)
```python
"""FEAT-761 TASK-4828 — embedding engine, corpus loader, score_async offload."""
import threading

import numpy as np
import pytest

from parrot.bots.guardrails.builtin import _engine_chassis as chassis

# FILL IN: tests — score_async runs engine.score on a non-main thread (record threading.get_ident());
# load_corpus_matrix normalizes rows, rejects 1-D/empty and pickled files;
# EmbeddingSimilarityEngine.score with a fake ORT session returning fixed token embeddings
# (mean pooling + mask + cosine computed by hand) and clamp to 0;
# embedding spec without <PREFIX>_CORPUS resolves to None (no raise) with a WARNING/ERROR log;
# PromptInjectionGuardrail.check still returns the same verdicts with a fake engine (offload transparent)
```

### FILL IN checklist
- [ ] `load_corpus_matrix` — safe load + normalize
- [ ] `EmbeddingSimilarityEngine.__init__/score` — model-card contract
- [ ] tests

---

## Acceptance Criteria

- [ ] `PromptInjectionGuardrail.check()` never calls `score()` on the event-loop thread.
- [ ] Injection suites pass unmodified.
- [ ] Embedding spec without corpus → `resolve_engine` returns `None`, logs, never raises.
- [ ] `numpy.load` always with `allow_pickle=False`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_engine_chassis_embedding.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_input_migration.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm TASK-4827 is `done`; re-verify anchors.
3. Mark `in-progress`; implement; complete every `# FILL IN:`.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4828 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Seat: gpt-5.6-terra · Backend: codex · Attempts: 1)
**Date**: 2026-10-27
**Notes**: Delivered and merged; merge-tier validation green. Closed via close_task.sh (no durable review-evidence artifact writable). A hook-written sdd/ledger/events.jsonl, if present in the attempt commit, was stripped before merge.

**Deviations from spec**: none
