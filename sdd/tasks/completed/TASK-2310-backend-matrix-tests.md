# TASK-2310: Backend-matrix test suite + integration tests

**Feature**: FEAT-439 — ONNX Backend for the Prompt-Injection Guardrail
**Spec**: `sdd/specs/onnx-injection-guardrail-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2307, TASK-2308, TASK-2309
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / §4 Test Specification. Tasks 2307-2309 each landed
their own focused tests; this task closes the gaps to the spec's FULL
test matrix, adds the integration tests, and sweeps the suite for
duplication/consistency so the matrix in spec §4 maps 1:1 to real,
passing tests. This is the verification gate before packaging/docs
(TASK-2311) and `/sdd-done`.

## Scope

- Audit `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py`
  against spec §4's unit-test table; implement every row not already
  covered by 2307-2309 (identify by behaviour, not test name):
  resolution precedence matrix, thread caps, session-failure fallback,
  index-from-config, pytector v2-dir vs v1-alias, regex floor, singleton
  sharing under concurrency, empty-input short-circuit, `check()` flow
  preservation, warm-up idempotence, only-download-site.
- Consolidate shared fixtures (spec §4): `fake_onnx_dir` (valid dir +
  missing-graph + missing-tokenizer variants), `no_hf_cache`
  (offline probing, asserts zero network), autouse
  `reset_engine_singleton`.
- Add the two integration tests (spec §4):
  - `test_onnx_engine_scores_real_graph` — real local graph, `skipif`
    when unavailable (env-gated; CI without the graph skips cleanly).
  - `test_bot_default_on_uses_onnx_when_cached` — an `AbstractBot`
    subclass with default flags picks up the ONNX engine when resolution
    finds a (mocked/fake) snapshot.
- Ensure the module-import purity test
  (`test_lazy_import_no_torch_at_module_import`) also guards against
  `onnxruntime` at module import time (extend the subprocess assertion).
- Full-file green run + no test relies on network or a real model
  download (except the skip-gated integration test).

**NOT in scope**: fixing implementation bugs beyond trivial test-exposed
ones (real defects → report, coordinate with the owning task);
benchmarks (TASK-2306); docs/packaging (TASK-2311).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` | MODIFY | Complete the unit matrix + fixtures |
| `packages/ai-parrot/tests/integration/test_guardrails_injection_onnx.py` | CREATE | The two integration tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: by this task the implementation (2307-2309) is final —
> anchor against the ACTUAL merged code, not the spec's pre-implementation
> sketches. `read` the module first.

### Verified Imports

```python
from parrot.bots.guardrails.base import (
    GuardrailAction, GuardrailContext, GuardrailStage,
)                                    # existing test file imports, lines 17-22
from parrot.bots.guardrails.builtin.prompt_injection import PromptInjectionGuardrail
# + the engine/resolution/warm-up names delivered by TASK-2307/2309 —
#   read the module for their final spellings before importing.
```

### Existing Test Conventions (MUST follow)

```python
# packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py
# - fixture `guardrail` patches module-level detector getter so no real
#   model ever loads (file docstring, lines 1-13, explains the MagicMock
#   unpacking gotcha: detect_injection needs a concrete (bool, float)
#   return, a bare MagicMock raises ValueError on unpacking)
# - fixture `ctx` builds a GuardrailContext
# - module-import purity via subprocess:
#   test_lazy_import_no_torch_at_module_import (asserts torch absent
#   from sys.modules after importing the guardrail module)
# - registry checks import build_guardrails from
#   parrot.bots.guardrails.registry inside the test
```

### Integration-test anchors

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
#   injection_detection: bool = True     # ctor default (line ~292) — the
#     default-on path that must select the ONNX engine when cached
# packages/ai-parrot/tests/integration/ — existing style references:
#   test_guardrails_output.py, test_pbac_guardrails_e2e.py
```

### Does NOT Exist

- ~~`tests/unit/test_guardrails_prompt_injection.py` at repo root~~ —
  the real path is `packages/ai-parrot/tests/unit/...` (repo-root
  `tests/` holds only `tests/benchmarks/`).
- ~~A CI-provisioned ONNX graph~~ — integration test MUST skip cleanly
  when no graph is present; gate on an env var
  (e.g. `PARROT_INJECTION_ONNX_DIR`) being set and valid.
- ~~pytest-network plugins~~ — "no network" is asserted by mocking
  `huggingface_hub` APIs, not by a network-blocking plugin.

---

## Implementation Notes

### Key Constraints
- Autouse singleton reset is mandatory — TASK-2307's engine singleton
  otherwise leaks across tests and ordering becomes load-bearing.
- Keep existing tests' assertions untouched; extend, don't rewrite.
- Async tests follow the file's existing pytest-asyncio usage (bare
  `async def` tests — check how the file/conftest configures the mode).
- Skip-gated integration test documents in its docstring how to run it
  locally (point `PARROT_INJECTION_ONNX_DIR` at a real export).

### References in Codebase
- Spec §4 tables — the authoritative matrix to close against.
- `benchmarks/injection_guardrail_latency/corpus.py` — sample texts to
  borrow for the real-graph integration test (one attack, one benign).

---

## Acceptance Criteria

- [ ] Every row of spec §4's unit-test table maps to a passing test
      (list the mapping in the Completion Note).
- [ ] Fixtures `fake_onnx_dir`, `no_hf_cache`, `reset_engine_singleton`
      (autouse) exist and are used.
- [ ] Integration file created; real-graph test skips cleanly without a
      local graph and passes with one.
- [ ] Module-import purity extended to onnxruntime.
- [ ] `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -v` — all green.
- [ ] `pytest packages/ai-parrot/tests/integration/test_guardrails_injection_onnx.py -v` — green (or skipped where gated).
- [ ] No test performs network access.

---

## Test Specification

The matrix itself is the deliverable — see spec §4. New integration
scaffold:

```python
# packages/ai-parrot/tests/integration/test_guardrails_injection_onnx.py
import os
import pytest

requires_graph = pytest.mark.skipif(
    not os.environ.get("PARROT_INJECTION_ONNX_DIR"),
    reason="needs a local ONNX graph (set PARROT_INJECTION_ONNX_DIR)",
)

@requires_graph
async def test_onnx_engine_scores_real_graph():
    """Scores a known attack sample above threshold and a benign one below."""

async def test_bot_default_on_uses_onnx_when_cached(monkeypatch):
    """AbstractBot defaults (injection_detection=True) select the ONNX
    engine when resolution finds a snapshot (mocked cache probe)."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2307, 2308, 2309 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read the final module before anchoring
4. **Update status** in `sdd/tasks/index/onnx-injection-guardrail-backend.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — include the spec-§4→test mapping

---

## Completion Note

**Completed by**: sdd-worker (Claude Code)
**Date**: 2026-08-21
**Notes**:

**Spec §4 → test mapping** (all in
`packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` unless noted):

| Spec §4 test | Implementing test(s) |
|---|---|
| `test_env_dir_wins_resolution` | `TestEngineResolution::test_env_dir_wins` |
| `test_env_dir_invalid_falls_through_loudly` | `test_env_dir_invalid_falls_through_with_error_log`, `test_missing_graph_falls_through_loudly` (new — incomplete-dir variant) |
| `test_uncached_snapshot_is_absent_no_network` | `test_uncached_snapshot_absent_no_network`, `test_full_resolution_with_no_hf_cache_touches_no_network` (new — consolidated `no_hf_cache` fixture) |
| `test_cached_snapshot_selects_onnx` | `test_cached_snapshot_selects_onnx` (new — was the one gap in the matrix) |
| `test_ort_thread_caps_applied` | `test_ort_thread_caps_default_and_env_override` |
| `test_session_failure_falls_back` | `test_session_failure_falls_back_never_raises` |
| `test_injection_index_from_config` | `test_injection_index_from_config_not_hardcoded`, `test_missing_tokenizer_config_defaults_index` (new — missing-config variant) |
| `test_pytector_gets_v2_snapshot_dir` | `test_pytector_v2_snapshot_dir_used_when_present` |
| `test_pytector_v1_alias_warns` | `test_pytector_v1_alias_warns` |
| `test_regex_floor` | `test_regex_floor_when_nothing_available` |
| `test_singleton_shared_across_bots` | `test_singleton_shared_and_lock_safe` |
| `test_empty_input_short_circuits` | `TestCheckFlowPreservation::test_empty_input_short_circuits_no_engine_call`, `test_whitespace_input_short_circuits` |
| `test_check_flow_unchanged` | `TestCheckFlowPreservation` (8 tests: ONNX over/under threshold, BLOCK, pattern naming, regex branch, security-event payload shape) |
| `test_warmup_idempotent` | `TestWarmup::test_warmup_idempotent` |
| `test_warmup_is_only_download_site` | `test_construction_never_downloads`, `test_warmup_skips_download_with_env_dir` |
| `test_onnx_engine_scores_real_graph` (integration) | `tests/integration/test_guardrails_injection_onnx.py::TestRealOnnxGraph::test_onnx_engine_scores_real_graph` |
| `test_bot_default_on_uses_onnx_when_cached` (integration) | `TestBotDefaultEngineSelection::test_bot_default_on_uses_onnx_when_cached` |

- Consolidated fixtures added: `fake_onnx_dir_missing_graph`,
  `fake_onnx_dir_missing_tokenizer` (siblings of the existing valid
  `fake_onnx_dir`), and `no_hf_cache` (fake `huggingface_hub` whose
  `try_to_load_from_cache` always reports absent and whose
  `snapshot_download` raises `AssertionError` if ever called — makes the
  "no network on the request path" contract mechanically unviolable
  within a test using it). `reset_engine_singleton` (already autouse from
  TASK-2307/2309) needed no further changes.
- Extended `test_lazy_import_no_torch_at_module_import` to also assert
  `'onnxruntime' not in sys.modules` after importing
  `parrot.bots.guardrails` — the ONNX import boundary is exactly as lazy
  as pytector's.
- Created `packages/ai-parrot/tests/integration/test_guardrails_injection_onnx.py`
  with the two spec-mandated integration tests:
  - `test_onnx_engine_scores_real_graph` — `skipif` gated on
    `PARROT_INJECTION_ONNX_DIR`; verified BOTH ways in this session: skips
    cleanly with the var unset, and (manually, pointed at TASK-2306's
    `models/injection-clf-v2/` export) passes for real — attack sample
    scores >0.9, benign sample scores <0.5.
  - `test_bot_default_on_uses_onnx_when_cached` — constructs a real
    `BasicBot(name="TestBot")` (default `injection_detection=True`) with
    `_probe_cached_onnx_snapshot` mocked to a fake snapshot dir and fake
    `onnxruntime`/`transformers` modules; asserts the bot's INPUT
    `GuardrailPipeline` resolves a `PromptInjectionGuardrail` whose
    `_injection_engine.engine_name == "onnx"`. No network, no real model.
- Full-suite run (unit + integration):
  `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py
  packages/ai-parrot/tests/integration/test_guardrails_injection_onnx.py -v`
  — **43 passed, 1 skipped** (the real-graph test, cleanly, with no env
  var set). No test performs network access (every HF-hub-touching test
  either mocks `huggingface_hub` or mocks the probe functions directly).
  `ruff check` clean on all three touched/created files.

**Deviations from spec**: none.
