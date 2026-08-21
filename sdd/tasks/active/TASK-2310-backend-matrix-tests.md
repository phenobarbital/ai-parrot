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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
