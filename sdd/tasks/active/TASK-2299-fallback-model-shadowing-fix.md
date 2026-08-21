# TASK-2299: Fix _fallback_model constructor shadowing in AbstractClient

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / Goal G5. `AbstractClient.__init__` unconditionally assigns
`self._fallback_model = kwargs.get('fallback_model', None)` (base.py:350),
which SHADOWS any class-level `_fallback_model` a subclass declares — the
class attribute is silently reset to `None` on every instance.
`BedrockMantleClient` works around it with
`kwargs.setdefault("fallback_model", self._fallback_model)` (mantle.py:104).
Fix the root cause so class attributes survive, and delete the workaround.
This is a deliberate `__init__` semantics change for ALL clients — verify no
client relied on the implicit reset.

---

## Scope

- Modify `AbstractClient.__init__` (base.py:350): assign `self._fallback_model`
  ONLY when `fallback_model` is explicitly present in kwargs; otherwise leave
  the class attribute visible (`if 'fallback_model' in kwargs:
  self._fallback_model = kwargs['fallback_model']` — attribute reads fall
  through to the class).
- Delete the workaround in `BedrockMantleClient.__init__` (mantle.py:104).
- Grep every client `__init__` for `fallback_model` and for reads of
  `self._fallback_model` to confirm none depends on instance-level `None`
  masking a class attribute (known class-level declarations: gpt.py:95
  `"gpt-5-nano"`, moonshot.py:132 `MOONSHOT_V1_128K`, mantle.py:82
  `"google.gemma-4-26b-a4b"`).
- Add regression test: subclass with class-level `_fallback_model` constructed
  WITHOUT the kwarg keeps its class value; constructed WITH `fallback_model=X`
  gets X; constructed with `fallback_model=None` explicitly gets `None`.
- Run the fallback suites + full test run.

**NOT in scope**: any other base.py change; the OpenAIBaseClient hierarchy
(TASK-2296–2298); subclass base-class swaps (TASK-2300).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | conditional `_fallback_model` assignment in `__init__` (:350) |
| `packages/ai-parrot/src/parrot/clients/nova/mantle.py` | MODIFY | delete `kwargs.setdefault("fallback_model", …)` (:104) |
| `tests/clients/test_fallback_model_shadowing.py` | CREATE | regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient              # clients/base.py:250
from parrot.clients.nova.mantle import BedrockMantleClient  # clients/nova/mantle.py:29
```

### Existing Signatures to Use
```python
# clients/base.py (verified @ dev ab84ffff0):
#   :350  self._fallback_model: Optional[str] = kwargs.get('fallback_model', None)   ← THE BUG
#   :906  @property default_model -> str  (getattr(self, '_default_model', None))
#   :926  def _should_use_fallback(self, model: str, error: Exception) -> bool   ← reads self._fallback_model

# clients/nova/mantle.py:84-128 __init__ (verified):
#   :81  _default_model: str = "openai.gpt-oss-120b"
#   :82  _fallback_model: str = "google.gemma-4-26b-a4b"
#   :104 kwargs.setdefault("fallback_model", self._fallback_model)   ← DELETE
#   test coverage: packages/ai-parrot/tests/clients/test_bedrock_mantle.py
#     (includes an explicit "_fallback_model shadowing guard" test — UPDATE it to
#      assert the class attribute survives WITHOUT the setdefault)

# Class-level _fallback_model declarations repo-wide (clients/):
#   gpt.py:95 ("gpt-5-nano"), moonshot.py:132, nova/mantle.py:82
# Existing fallback tests: tests/clients/test_base_fallback.py,
#   tests/clients/test_client_fallback.py, tests/clients/test_openai_fallback.py
```

### Does NOT Exist
- ~~a `fallback_model` @property with setter on AbstractClient~~ — plain instance/class attribute access only.
- ~~class-level `_fallback_model` on NvidiaClient/OpenRouterClient/LocalLLMClient/vLLMClient~~ — none declared; after the fix these resolve to `AbstractClient`'s `None`-by-absence (instance attr no longer created unconditionally — `_should_use_fallback` must still work when the attribute exists only on the class, or not at all; keep a class-level `_fallback_model: Optional[str] = None` declaration on `AbstractClient` so `getattr` never fails).

---

## Implementation Notes

### Pattern to Follow
```python
# base.py __init__ — replace :350 with:
if 'fallback_model' in kwargs:
    self._fallback_model = kwargs.pop('fallback_model')
# and ensure the class declares: _fallback_model: Optional[str] = None
# (check whether kwargs['fallback_model'] was previously consumed or passed on —
#  preserve current kwargs-consumption behavior exactly)
```

### Key Constraints
- Verify whether `kwargs.get` vs `kwargs.pop` matters at :350 today (does
  `fallback_model` leak into later kwargs consumers?) — preserve whichever
  consumption behavior is current.
- This touches EVERY client's construction path (Anthropic, Google, Bedrock
  included) — full `pytest` run mandatory.

### References in Codebase
- `packages/ai-parrot/tests/clients/test_bedrock_mantle.py` — shadowing-guard test to update.
- `sdd/specs/openai-compatible-clients.spec.md` §7 Known Risks (G5 entry).

---

## Acceptance Criteria

- [ ] Subclass class-level `_fallback_model` survives `__init__` without explicit kwarg
- [ ] Explicit `fallback_model=X` kwarg still wins; explicit `None` still yields `None`
- [ ] mantle.py workaround removed; `test_bedrock_mantle.py` updated and green
- [ ] `pytest tests/clients/test_base_fallback.py tests/clients/test_client_fallback.py tests/clients/test_openai_fallback.py tests/clients/test_fallback_model_shadowing.py packages/ai-parrot/tests/clients/test_bedrock_mantle.py -v` green
- [ ] Full `pytest` run green (constructor change affects all clients)
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# tests/clients/test_fallback_model_shadowing.py
from parrot.clients.base import AbstractClient


class _WithFallback(AbstractClient):
    _fallback_model = "class-level-fallback"
    # minimal abstract-method stubs...


def test_class_attr_survives_without_kwarg():
    c = _WithFallback()
    assert c._fallback_model == "class-level-fallback"


def test_explicit_kwarg_wins():
    c = _WithFallback(fallback_model="override")
    assert c._fallback_model == "override"


def test_explicit_none_wins():
    c = _WithFallback(fallback_model=None)
    assert c._fallback_model is None


def test_mantle_no_longer_needs_workaround():
    from parrot.clients.nova.mantle import BedrockMantleClient
    c = BedrockMantleClient(api_key="k")
    assert c._fallback_model == "google.gemma-4-26b-a4b"
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none (file-disjoint from TASK-2296)
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2299-fallback-model-shadowing-fix.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
