# TASK-4827: Engine chassis — shared classifier engine + generic per-category resolver/warmup

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (design-research S8). Creates `builtin/_engine_chassis.py` so the
jailbreak guardrail (TASK-4835) gets ONNX classifier scoring, offline resolution and an
explicit warmup without copying the ~500 lines in `builtin/prompt_injection.py`.

> **Task-time scope decision (deviation from spec §3 M2 wording, recorded here on
> purpose).** The spec says the chassis absorbs injection's snapshot probes, env-dir /
> cache builders, memoized resolver and warmup downloader. Verification at task time
> showed the existing suites patch those **inside `prompt_injection`'s own namespace**:
> `monkeypatch.setattr(pi_module, "_probe_cached_onnx_snapshot", ...)`,
> `pi_module.importlib.util.find_spec`, `pi_module._resolve_injection_engine`, and
> `conftest.py` resets `pi_module._RESOLVED_INJECTION_ENGINE = pi_module._UNSET` /
> `_WARMUP_DONE` (11 test files). Relocating the stateful chain would make those
> patches silently no-op and break the suites. Therefore:
> - **Moves to the chassis** (stateless, no patch targets): the ONNX classifier
>   engine, `softmax`, tokenizer loader, positive-label index resolver, `env_int`, ORT
>   session construction.
> - **Stays in `prompt_injection.py`, untouched**: the whole resolution chain,
>   `_RESOLVED_INJECTION_ENGINE`/`_UNSET`, pytector, probes, `warmup_injection_model`.
> - **New in the chassis**: a generic, `EngineSpec`-driven resolver + warmup used by
>   NEW categories only (jailbreak). Migrating injection onto it is a follow-up that
>   must update the tests in the same change.
> The spec's compatibility goal ("public surface and behavior unchanged, golden tests")
> is exactly what this preserves.

---

## Scope

- Create `_engine_chassis.py` with: `EngineSpec`, `ScoringEngine` protocol, `env_int`,
  `softmax`, `load_tokenizer`, `resolve_positive_index`, `ClassifierOnnxEngine`,
  `resolve_engine(spec, force_reresolve)` (per-category memo + lock), and
  `warmup_model(spec, force_download)` (the only download site for chassis specs).
- In `prompt_injection.py`: make `_OnnxInjectionEngine` a thin subclass of
  `ClassifierOnnxEngine` (same ctor signature, `engine_name="onnx"`, ORT env prefix
  `PARROT_INJECTION`, exposes `_injection_index`); turn `_softmax`, `_load_tokenizer`,
  `_resolve_injection_index`, `_env_int` into thin delegates keeping their names and
  signatures. Nothing else in the file changes.
- Golden parity test: identical scores/index/session options before vs after.

**NOT in scope**: `EmbeddingSimilarityEngine` and `score_async` (TASK-4828); touching
`check()`; migrating `_resolve_injection_engine`/`warmup_injection_model`; any jailbreak
model id (TASK-4832 pins it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/_engine_chassis.py` | CREATE | shared engine machinery |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | MODIFY | `_OnnxInjectionEngine` → subclass; 4 helpers → delegates |
| `packages/ai-parrot/tests/unit/test_guardrails_engine_chassis.py` | CREATE | chassis + parity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# inside prompt_injection.py, after this task:
from ._engine_chassis import ClassifierOnnxEngine, env_int, load_tokenizer, resolve_positive_index, softmax
# existing, unchanged (prompt_injection.py top):
from parrot.security.prompt_injection import PromptInjectionDetector, SecurityEventLogger, ThreatLevel, max_threat_level
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
_ONNX_MAX_LENGTH = 512                                             # :103
def _env_int(name: str, default: int) -> int:                      # :149
class _InjectionScoringEngine(Protocol): engine_name; model_id; score(text)->float   # :172-185
class _OnnxInjectionEngine:                                        # :188-255
    engine_name = "onnx"                                           # :202
    def __init__(self, tokenizer_dir: Path, graph_path: Path, model_id: str) -> None:  # :204
        # lazy `import onnxruntime as ort` :221; _load_tokenizer :228;
        # ORT caps from PARROT_INJECTION_ORT_INTRA_OP_THREADS (2) / _INTER_OP_THREADS (1) :235-238
        # self._session :240; self._input_names :243; self._injection_index :244
    def score(self, text: str) -> float:                           # :246 (truncation max_length=512, softmax[index])
def _softmax(logits: Any) -> Any:                                  # :299
def _load_tokenizer(tokenizer_dir: Path) -> Any:                   # :315 (AutoTokenizer local_files_only, PreTrainedTokenizerFast fallback)
def _resolve_injection_index(tokenizer_dir: Path) -> int:          # :365 ("inject" in id2label, default 1, warnings)
def _probe_cached_onnx_snapshot() -> Path | None:                  # :404 — pattern for the generic probe (huggingface_hub.try_to_load_from_cache)
def _do_resolve_injection_engine()                                 # :565 — precedence pattern to mirror (minus pytector)
def _resolve_injection_engine(force_reresolve: bool = False)       # :618 — double-checked lock pattern to mirror
async def warmup_injection_model(force_download: bool = False) -> str:  # :915 — pattern for warmup_model (to_thread, lock, never raises)

# Tests that constrain this task (must stay green, unmodified):
# tests/unit/test_guardrails_prompt_injection.py:536-541  _OnnxInjectionEngine(tokenizer_dir=, graph_path=, model_id=); engine._injection_index == 1
# tests/unit/test_guardrails_prompt_injection.py:646-662  engine._session.sess_options.intra/inter_op_num_threads from PARROT_INJECTION_ORT_* env
# tests/unit/test_guardrails_prompt_injection.py:169-180  importing parrot.bots.guardrails must not import torch/onnxruntime
# tests/conftest.py:69-73 resets pi_module._RESOLVED_INJECTION_ENGINE/_UNSET/_WARMUP_DONE
```

### Does NOT Exist
- ~~`parrot/bots/guardrails/builtin/_engine_chassis.py`~~ — created here.
- ~~a generic resolver for injection~~ — injection keeps its own chain; do NOT route `_resolve_injection_engine` through the chassis.
- ~~`EmbeddingSimilarityEngine`, `score_async`~~ — TASK-4828.
- ~~`PARROT_JAILBREAK_*` usage here~~ — the chassis is env-prefix-parametrized; no jailbreak constants live in it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/_engine_chassis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_engine_chassis.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_OnnxInjectionEngine",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_softmax",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_load_tokenizer",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_resolve_injection_index",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_env_int",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_resolve_injection_engine",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#warmup_injection_model"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Move-first**: copy `_OnnxInjectionEngine.__init__/score`, `_softmax`,
  `_load_tokenizer`, `_resolve_injection_index`, `_env_int` bodies verbatim into the
  chassis, then parametrize (env prefix, positive label, max_length). Run the existing
  suites before parametrizing further.
- Import discipline (FEAT-439): `onnxruntime`, `transformers`, `huggingface_hub`,
  `numpy` imported **inside functions only**; the existing "import guardrails package
  does not load onnxruntime" test must stay green.
- `resolve_engine` NEVER downloads (offline probes only); `warmup_model` is the only
  download site; both never raise (log loudly and degrade to `None`).
- Per-category memo: `dict[str, ScoringEngine | None]` keyed by `spec.category`, with
  an `_UNSET`-style sentinel per key and one `threading.Lock` — mirror
  `_resolve_injection_engine`'s double-checked lock.
- Expose `_reset_chassis_state()` (module-private) for test fixtures.

---

## Implementation Blueprint

### Steps (in order)
1. Capture golden values FIRST: write the parity test against the *current*
   `_OnnxInjectionEngine` using the existing fake-ORT/tokenizer fixtures pattern from
   `test_guardrails_prompt_injection.py` (sys.modules fakes) — *why*: proves the move is behavior-neutral.
2. Create `_engine_chassis.py` (blocks below) — *why*: shared, stateless engine code.
3. Rewrite the five symbols in `prompt_injection.py` as subclass/delegates — *why*: one implementation, names kept for patch/test compat.
4. Run the three injection suites + the new test; then add resolver/warmup tests.

### `packages/ai-parrot/src/parrot/bots/guardrails/builtin/_engine_chassis.py` (CREATE)
```python
"""Shared ONNX scoring-engine chassis for ML guardrails (FEAT-761).

Stateless engine pieces factored out of ``prompt_injection.py`` plus a
generic, ``EngineSpec``-driven offline resolver and warm-up for guardrail
categories added after FEAT-439 (jailbreak). The prompt-injection
guardrail keeps its own stateful resolution chain (its tests patch it in
place); only its stateless engine/helpers delegate here.

Import discipline (FEAT-439): onnxruntime / transformers / huggingface_hub /
numpy are imported inside functions only — importing this module is free.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_MAX_LENGTH = 512


@dataclass(frozen=True)
class EngineSpec:
    """Static description of one guardrail category's ML engine.

    Attributes:
        category: Memo key and log label (``"jailbreak"``).
        env_prefix: Prefix for ``<P>_ONNX_DIR`` / ``<P>_ONNX_MODEL`` /
            ``<P>_ONNX_GRAPH`` / ``<P>_ORT_INTRA_OP_THREADS`` /
            ``<P>_ORT_INTER_OP_THREADS``.
        default_model_id: HF repo id used when ``<P>_ONNX_MODEL`` is unset.
        known_graph_paths: repo id -> graph path inside the repo.
        kind: ``"classifier"`` (softmax over logits) or ``"embedding"``.
        positive_label_match: Substrings (lower-case) identifying the positive
            class in ``id2label``; first match wins, default index 1.
        max_length: Tokenizer truncation length.
        warmup_allow_patterns: Extra ``snapshot_download`` patterns besides
            the graph (tokenizer/config files).
    """
    category: str
    env_prefix: str
    default_model_id: str
    known_graph_paths: dict[str, str] = field(default_factory=dict)
    kind: Literal["classifier", "embedding"] = "classifier"
    positive_label_match: tuple[str, ...] = ("inject",)
    max_length: int = DEFAULT_MAX_LENGTH
    warmup_allow_patterns: tuple[str, ...] = (
        "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "*.model",
    )


@runtime_checkable
class ScoringEngine(Protocol):
    """Uniform engine contract: a probability in ``[0, 1]`` for *text*."""
    engine_name: str
    model_id: str

    def score(self, text: str) -> float:
        """Synchronous; callers on the event loop must offload it."""
        ...


def env_int(name: str, default: int) -> int:
    """Verbatim move of ``prompt_injection._env_int``."""
    # FILL IN: verbatim body from prompt_injection.py:163-169


def softmax(logits: Any) -> Any:
    """Verbatim move of ``prompt_injection._softmax``."""
    # FILL IN: verbatim body from prompt_injection.py:299-313


def load_tokenizer(tokenizer_dir: Path) -> Any:
    """Verbatim move of ``prompt_injection._load_tokenizer`` (never downloads)."""
    # FILL IN: verbatim body from prompt_injection.py:315-363


def resolve_positive_index(tokenizer_dir: Path, positive_label_match: tuple[str, ...] = ("inject",)) -> int:
    """Index of the first ``id2label`` entry containing any of ``positive_label_match``.

    Generalizes ``prompt_injection._resolve_injection_index`` (same defaults,
    same warnings, same index-1 fallback).
    """
    # FILL IN: body from prompt_injection.py:365-402 with `"inject" in label` → any(m in label for m in positive_label_match)


class ClassifierOnnxEngine:
    """ONNX Runtime sequence-classifier engine (softmax over logits)."""
    engine_name = "onnx"

    def __init__(
        self,
        tokenizer_dir: Path,
        graph_path: Path,
        model_id: str,
        *,
        env_prefix: str = "PARROT_INJECTION",
        positive_label_match: tuple[str, ...] = ("inject",),
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> None:
        """Load tokenizer + thread-capped ORT session (never downloads; raises on failure)."""
        # FILL IN: verbatim from prompt_injection.py:221-244 with env names f"{env_prefix}_ORT_INTRA_OP_THREADS"/
        # f"{env_prefix}_ORT_INTER_OP_THREADS", positive index stored as self._positive_index,
        # self._max_length = max_length — bounded by tests asserting _session.sess_options

    def score(self, text: str) -> float:
        """Probability of the positive class for *text*."""
        # FILL IN: verbatim from prompt_injection.py:248-255 using self._max_length / self._positive_index
```
Second half of the same file (keep under ~80 lines per block when writing):
```python
_UNSET = object()
_RESOLVED: dict[str, Any] = {}
_RESOLVE_LOCK = threading.Lock()
_WARMUP_LOCKS: dict[str, asyncio.Lock] = {}
_WARMUP_DONE: set[str] = set()


def _model_id(spec: EngineSpec) -> str:
    return os.environ.get(f"{spec.env_prefix}_ONNX_MODEL") or spec.default_model_id


def _graph_repo_path(spec: EngineSpec) -> str:
    return (
        os.environ.get(f"{spec.env_prefix}_ONNX_GRAPH")
        or spec.known_graph_paths.get(_model_id(spec), "onnx/model.onnx")
    )


def _build_engine(spec: EngineSpec, tokenizer_dir: Path, graph_path: Path, model_id: str) -> ScoringEngine:
    """Construct the engine for ``spec.kind`` (embedding kind added by TASK-4828)."""
    if spec.kind == "classifier":
        return ClassifierOnnxEngine(
            tokenizer_dir, graph_path, model_id,
            env_prefix=spec.env_prefix, positive_label_match=spec.positive_label_match,
            max_length=spec.max_length,
        )
    raise ValueError(f"engine kind {spec.kind!r} not supported yet")


def _do_resolve(spec: EngineSpec) -> ScoringEngine | None:
    """Offline precedence: ``<P>_ONNX_DIR`` -> cached HF snapshot -> ``None``.

    Mirrors ``prompt_injection._do_resolve_injection_engine`` minus pytector;
    every failure logs (ERROR for a broken env dir, WARNING naming
    ``warmup_model`` when nothing is cached) and falls through. Never raises.
    """
    # FILL IN: env-dir branch (dir + model.onnx, ERROR logs naming the env var), cache branch via
    # huggingface_hub.try_to_load_from_cache(_model_id(spec), _graph_repo_path(spec)) climbing
    # len(Path(graph).parts) parents to the snapshot root — SKIPPED entirely when _model_id(spec) == ""
    # (a category with no pinned default, e.g. a null bake-off winner); INFO "selected engine=onnx
    # model=... category=..." — bounded by "never downloads, never raises"


def resolve_engine(spec: EngineSpec, force_reresolve: bool = False) -> ScoringEngine | None:
    """Memoized per ``spec.category``; thread-safe double-checked lock."""
    # FILL IN: mirror prompt_injection._resolve_injection_engine (:618) over _RESOLVED[spec.category]


async def warmup_model(spec: EngineSpec, force_download: bool = False) -> str:
    """Download (if needed), re-resolve and warm ``spec``'s engine; the ONLY download site.

    Returns ``"onnx"`` or ``"none"``. Never raises; download/inference run in threads.
    """
    # FILL IN: mirror warmup_injection_model (:915-963): per-category asyncio.Lock, skip when env dir valid,
    # snapshot_download(_model_id(spec), allow_patterns=[_graph_repo_path(spec), *spec.warmup_allow_patterns]),
    # resolve_engine(spec, True) in to_thread, benign dummy score — bounded by "never raises"


def _reset_chassis_state() -> None:
    """Test hook: forget every memoized resolution and warm-up."""
    _RESOLVED.clear()
    _WARMUP_DONE.clear()
```
**Why this shape**: classifier engine + helpers are byte-for-byte moves (parity); the
resolver/warmup are new code following the injection precedent exactly, keyed per
category so injection-style singletons never collide across guardrails.

### `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class _OnnxInjectionEngine:' prompt_injection.py)
# REPLACE the whole class body `class _OnnxInjectionEngine:` … `return float(_softmax(logits[0])[self._injection_index])`
# (verified: prompt_injection.py:188-255) with:
class _OnnxInjectionEngine(ClassifierOnnxEngine):
    """ONNX Runtime scoring engine for the prompt-injection classifier.

    FEAT-761: implementation lives in the shared chassis
    (`_engine_chassis.ClassifierOnnxEngine`); this subclass pins the
    injection category's env prefix and positive label, and keeps the
    `_injection_index` attribute existing callers/tests read.
    """

    def __init__(self, tokenizer_dir: Path, graph_path: Path, model_id: str) -> None:
        super().__init__(
            tokenizer_dir, graph_path, model_id,
            env_prefix="PARROT_INJECTION", positive_label_match=("inject",), max_length=_ONNX_MAX_LENGTH,
        )

    @property
    def _injection_index(self) -> int:
        return self._positive_index
```
```python
# Each of these keeps its name + signature + docstring first line; body becomes a delegate:
# def _env_int(name, default)            (verified: :149) -> return env_int(name, default)
# def _softmax(logits)                   (verified: :299) -> return softmax(logits)
# def _load_tokenizer(tokenizer_dir)     (verified: :315) -> return load_tokenizer(tokenizer_dir)
# def _resolve_injection_index(tokenizer_dir) (verified: :365) -> return resolve_positive_index(tokenizer_dir, ("inject",))
# and add near the other relative imports (after `from ..base import (...)`):
from ._engine_chassis import ClassifierOnnxEngine, env_int, load_tokenizer, resolve_positive_index, softmax
```
**Why**: names stay importable/patchable; behavior is the chassis' verbatim copy.

### `packages/ai-parrot/tests/unit/test_guardrails_engine_chassis.py` (CREATE)
```python
"""FEAT-761 TASK-4827 — engine chassis parity + generic resolver/warmup."""
import pytest

from parrot.bots.guardrails.builtin import _engine_chassis as chassis


@pytest.fixture(autouse=True)
def _reset():
    chassis._reset_chassis_state()
    yield
    chassis._reset_chassis_state()

# FILL IN: reuse the sys.modules fake onnxruntime/transformers pattern from
# tests/unit/test_guardrails_prompt_injection.py:24-60 (copy the helper, do not import private test modules).
# Tests: importing chassis does not import onnxruntime; ClassifierOnnxEngine honors <prefix>_ORT_* env;
# resolve_positive_index matches "jailbreak"/"malicious" labels and falls back to 1;
# _OnnxInjectionEngine parity (_injection_index, sess_options, score == pre-refactor golden values);
# resolve_engine: env dir wins, cache probe second (monkeypatch huggingface_hub.try_to_load_from_cache),
# None when nothing, memoized per category (two specs independent), force_reresolve;
# warmup_model never raises on download failure and is a no-op when env dir valid — bounded by AC list
```

### FILL IN checklist
- [ ] chassis helper bodies — verbatim moves
- [ ] `ClassifierOnnxEngine` — verbatim + parametrized env/label/max_length
- [ ] `_do_resolve` / `resolve_engine` / `warmup_model` — injection precedent, per category
- [ ] tests incl. golden parity

---

## Acceptance Criteria

- [ ] `test_guardrails_prompt_injection.py`, `test_guardrails_input_migration.py`,
      `test_guardrails_injection_onnx.py` pass **unmodified**.
- [ ] `_OnnxInjectionEngine` scores bit-identically to pre-refactor on the parity fixture.
- [ ] Importing `parrot.bots.guardrails` (and the chassis) loads neither onnxruntime nor transformers.
- [ ] `resolve_engine` memoizes per category; never downloads; never raises.
- [ ] `warmup_model` is the only `snapshot_download` call site in the chassis.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_engine_chassis.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_input_migration.py -q`
- `pytest packages/ai-parrot/tests/integration/test_guardrails_injection_onnx.py -q`

---

## Test Specification

See CREATE block; parity is the load-bearing test.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm `Depends-on` are `done`; re-verify anchors (`grep -c`).
3. Mark `in-progress`; golden test first, then move, then parametrize.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4827 agent-security-guardrails verified`; fill the Completion Note (repeat the scope decision in "Deviations").

---

## Completion Note

**Completed by**: sdd-worker (Seat: opus · Backend: native · Attempts: 1)
**Date**: 2026-10-27
**Notes**: Delivered and merged; merge-tier validation green. Closed via close_task.sh (no durable review-evidence artifact writable). Deliverable reviewed by worker at merge.

**Deviations from spec**: none
