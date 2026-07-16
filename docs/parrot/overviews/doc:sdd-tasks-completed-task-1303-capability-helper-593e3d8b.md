---
type: Wiki Overview
title: 'TASK-1303: Capability helper + configurable whitelist + constructor kwarg'
id: doc:sdd-tasks-completed-task-1303-capability-helper-and-configurable-whitelist-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The spec introduces a model-capability gate (`_supports_combined_tools_and_schema`)
  that decides, per call, whether `tools=` and `response_schema=` can be combined
  in a single `GenerateContentConfig`. This task lays the foundation: the helper itself,
  the configurable whitelist me'
relates_to:
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1303: Capability helper + configurable whitelist + constructor kwarg

**Feature**: FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output
**Spec**: `sdd/specs/google-genai-combined-tools-and-schema.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The spec introduces a model-capability gate (`_supports_combined_tools_and_schema`) that decides, per call, whether `tools=` and `response_schema=` can be combined in a single `GenerateContentConfig`. This task lays the foundation: the helper itself, the configurable whitelist mechanism (class attribute + constructor kwarg + per-instance store), and a focused unit test for the helper. The two refactors that USE the helper (`ask()` and `ask_stream()`) are TASK-1304 and TASK-1305 — they depend on this task being complete.

Implements spec §3 Module 2, sub-tasks 1-3 (class attribute, constructor kwarg, capability helper).

---

## Scope

- Add the class attribute `_default_combined_call_prefixes: tuple[str, ...] = ("gemini-3.1-pro", "gemini-3.5-flash", "gemini-3.1-flash-lite")` to `GoogleGenAIClient`, located near `_lightweight_model` (around line 108).
- Extend `GoogleGenAIClient.__init__` to accept `combined_call_prefixes: Optional[tuple[str, ...]] = None`. Resolve to `self._combined_call_prefixes` using the same explicit-kwarg-then-default pattern that `_reformat_model` already uses at `client.py:149-152`.
- Add a new `@staticmethod` `_supports_combined_tools_and_schema(model, prefixes) -> bool` immediately after `_requires_thinking` (around line 190), following the established `@staticmethod + _as_model_str + .startswith()` shape.
- Add a focused unit test for the helper covering whitelisted, non-whitelisted, edge (empty / None), and enum-member inputs.

**NOT in scope**:
- The gate refactor in `ask()` (TASK-1304).
- The gate refactor in `ask_stream()` (TASK-1305).
- The stale comment update at `client.py:109-115` (rolled into TASK-1304 — that task touches the gate immediately below the comment).
- The `gemini-3.1-flash-lite` debug log (rolled into TASK-1304 and TASK-1305 — emitted at gate-trigger time).
- Adding the new enum entry (TASK-1302).
- The combined-mode regression tests (TASK-1307).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Add class attribute, constructor kwarg + resolution, capability helper static method. Three small additions; no removals. |
| `packages/ai-parrot/tests/test_google_client.py` | MODIFY | Append one new test class or two test functions for the helper. Do NOT alter existing tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Optional
# These already exist at the top of client.py — do not re-import.
from parrot.models.google import GoogleModel   # already imported at client.py top
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/google/client.py  (verified at HEAD, 3980 lines, 2026-05-27)

class GoogleGenAIClient(AbstractClient):
    client_type: str = 'google'                                       # line 103
    client_name: str = 'google'                                       # line 104
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value       # line 105
    _fallback_model: str = 'gemini-3.1-flash-lite-preview'            # line 106
    _model_garden: bool = False                                       # line 107
    _lightweight_model: str = "gemini-3.1-flash-lite-preview"         # line 108
    # ↑ INSERT _default_combined_call_prefixes HERE, after _lightweight_model

    _default_reformat_model: str = GoogleModel.GEMINI_3_FLASH_PREVIEW.value  # line 115

    def __init__(
        self,
        vertexai: bool = False,
        model_garden: bool = False,
        reformat_model: Optional[Union[str, GoogleModel]] = None,
        **kwargs,
    ):                                                                 # line 121
        # ... existing body ...
        self._reformat_model: str = self._as_model_str(reformat_model) \
            or self._default_reformat_model                            # line 151-152
        # ↑ INSERT resolution for self._combined_call_prefixes IMMEDIATELY AFTER this line

    @staticmethod
    def _is_gemini3_model(model: str) -> bool:                         # line 157

    @staticmethod
    def _is_preview_model(model: str) -> bool:                         # line 169

    @staticmethod
    def _requires_thinking(model: str) -> bool:                        # line 177
    # ↑ INSERT _supports_combined_tools_and_schema STATIC METHOD AFTER THIS (around line 190)

    @staticmethod
    def _as_model_str(model) -> str:                                   # line 193
```

### Pattern reference — how `_reformat_model` is wired (mirror this exactly)

```python
# In the class body (line 115):
_default_reformat_model: str = GoogleModel.GEMINI_3_FLASH_PREVIEW.value

# In __init__ signature (line 125):
reformat_model: Optional[Union[str, GoogleModel]] = None,

# In __init__ body (lines 149-152):
# Resolve reformat_model: explicit kwarg > class default. Accepts
# both ``GoogleModel`` enum members and raw strings.
self._reformat_model: str = self._as_model_str(reformat_model) \
    or self._default_reformat_model
```

### Does NOT Exist

- ~~`GoogleGenAIClient._combined_call_enabled`~~ — the attribute is a TUPLE of prefixes, not a boolean.
- ~~`GoogleGenAIClient.supports_combined_tools_and_schema`~~ (public name) — keep the underscore prefix, consistent with `_is_gemini3_model` et al.
- ~~`types.FunctionCallingConfigMode.COMBINED`~~ — does not exist in the Google GenAI SDK.
- ~~`StructuredOutputConfig.use_combined_call`~~ — capability is gated on the MODEL, not on the output config.
- ~~`self._combined_call_prefixes` as a `list`~~ — keep it a `tuple` for immutability and to match the pattern used elsewhere for static config.
- ~~`_supports_combined_tools_and_schema` as an instance method~~ — the spec mandates `@staticmethod` to mirror `_is_gemini3_model` (`client.py:156-204`); makes it cheaply testable without instantiating the client.

---

## Implementation Notes

### Implementation sketch (do NOT copy-paste verbatim — read the surrounding code first)

```python
# Insert near client.py:108
_default_combined_call_prefixes: tuple[str, ...] = (
    "gemini-3.1-pro",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
)

# Insert into __init__ signature (next to reformat_model)
combined_call_prefixes: Optional[tuple[str, ...]] = None,

# Insert into __init__ body, immediately after the _reformat_model resolution (~line 152)
# Resolve combined_call_prefixes: explicit kwarg > class default.
# Coerce explicitly to tuple so callers can pass any sequence (list, tuple, generator).
self._combined_call_prefixes: tuple[str, ...] = (
    tuple(combined_call_prefixes)
    if combined_call_prefixes is not None
    else self._default_combined_call_prefixes
)

# Insert after _requires_thinking (~line 190)
@staticmethod
def _supports_combined_tools_and_schema(
    model: str | "GoogleModel" | None,
    prefixes: tuple[str, ...],
) -> bool:
    """Whether `model` may receive tools + response_schema in a single call.

    Returns True when the normalised model identifier starts with any
    prefix in `prefixes`. Pattern matches `_is_gemini3_model` and
    `_requires_thinking` for consistency.

    Args:
        model: Model identifier — accepts plain string, GoogleModel enum,
            or None (returns False for falsy inputs).
        prefixes: Tuple of model-name prefixes to match against.

    Returns:
        True iff `model` starts with any prefix in `prefixes`.
    """
    model = GoogleGenAIClient._as_model_str(model)
    if not model or not prefixes:
        return False
    return any(model.startswith(p) for p in prefixes)
```

### Key Constraints

- The helper MUST be a `@staticmethod`, not an instance method. Two reasons: (a) consistency with `_is_gemini3_model` / `_requires_thinking`, (b) testability — unit tests can call it without building a full client.
- Both parameters are explicit — `prefixes` is NOT read off `self`. This keeps the helper pure and trivially testable. Callers in `ask()` / `ask_stream()` will pass `self._combined_call_prefixes`.
- The empty-tuple case (`prefixes == ()`) MUST return False — this is how a user disables combined mode entirely (spec acceptance criterion `test_combined_call_prefixes_kwarg_override_empty`).
- Do NOT inline `_combined_call_prefixes` resolution into class body — pattern is constructor-kwarg-override (see `_reformat_model` precedent).

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/google/client.py:156-204` — `_is_gemini3_model` / `_is_preview_model` / `_requires_thinking` / `_as_model_str` — the shape to follow.
- `packages/ai-parrot/src/parrot/clients/google/client.py:149-152` — `_reformat_model` resolution — the explicit-kwarg-then-default pattern.
- `packages/ai-parrot/tests/test_google_client.py:8-101` — existing test scaffold to mirror for the new helper test.

---

## Acceptance Criteria

- [ ] `GoogleGenAIClient._default_combined_call_prefixes` exists and equals `("gemini-3.1-pro", "gemini-3.5-flash", "gemini-3.1-flash-lite")`.
- [ ] `GoogleGenAIClient.__init__` accepts `combined_call_prefixes` as an optional kwarg.
- [ ] `GoogleGenAIClient(combined_call_prefixes=("foo",))._combined_call_prefixes == ("foo",)`.
- [ ] `GoogleGenAIClient()._combined_call_prefixes == GoogleGenAIClient._default_combined_call_prefixes`.
- [ ] `GoogleGenAIClient._supports_combined_tools_and_schema(...)` is a `@staticmethod` (use `inspect.isfunction(GoogleGenAIClient.__dict__['_supports_combined_tools_and_schema'].__func__)` or `isinstance(GoogleGenAIClient.__dict__['_supports_combined_tools_and_schema'], staticmethod)` to assert).
- [ ] Helper returns True for `"gemini-3.1-pro-preview"`, `"gemini-3.5-flash"`, `"gemini-3.1-flash-lite-preview"` against the default whitelist.
- [ ] Helper returns False for `"gemini-2.5-pro"`, `"gemini-2.0-flash"`, `"gemini-2.5-flash"`, `""`, `None`.
- [ ] Helper accepts a `GoogleModel` enum member (normalised via `_as_model_str`) and works correctly.
- [ ] Empty-tuple prefixes → helper returns False for ALL models (acceptance for the `combined_call_prefixes=()` kill switch).
- [ ] No regression in existing tests: `pytest packages/ai-parrot/tests/test_google_client.py -v` passes all 10 pre-existing tests.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_google_client.py — append at the bottom

import inspect
import pytest

from parrot.clients.google.client import GoogleGenAIClient
from parrot.models.google import GoogleModel


class TestSupportsCombinedToolsAndSchema:
    """Unit tests for the FEAT-193 capability helper."""

    DEFAULT_PREFIXES = GoogleGenAIClient._default_combined_call_prefixes

    def test_is_staticmethod(self):
        """Helper is a @staticmethod (matches the _is_gemini3_model pattern)."""
        descriptor = GoogleGenAIClient.__dict__["_supports_combined_tools_and_schema"]
        assert isinstance(descriptor, staticmethod)

    @pytest.mark.parametrize("model", [
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite-preview",
        # also matches longer suffixes the API may publish later
        "gemini-3.5-flash-001",
    ])
    def test_whitelisted_returns_true(self, model):
        assert GoogleGenAIClient._supports_combined_tools_and_schema(
            model, self.DEFAULT_PREFIXES
        ) is True

    @pytest.mark.parametrize("model", [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-3-flash-preview",  # NOT in the prefix list — 3-flash without the .5
    ])
    def test_unwhitelisted_returns_false(self, model):
        assert GoogleGenAIClient._supports_combined_tools_and_schema(
            model, self.DEFAULT_PREFIXES
        ) is False

    @pytest.mark.parametrize("model", ["", None])
    def test_falsy_input_returns_false(self, model):
        assert GoogleGenAIClient._supports_combined_tools_and_schema(
            model, self.DEFAULT_PREFIXES
        ) is False

    def test_accepts_googlemodel_enum(self):
        """Helper normalises GoogleModel enum members via _as_model_str."""
        assert GoogleGenAIClient._supports_combined_tools_and_schema(
            GoogleModel.GEMINI_3_PRO_PREVIEW, self.DEFAULT_PREFIXES
        ) is True

    def test_empty_prefixes_disables_combined_mode(self):
        """Passing an empty prefix tuple is the documented kill switch."""
        assert GoogleGenAIClient._supports_combined_tools_and_schema(
            "gemini-3.5-flash", ()
        ) is False


class TestCombinedCallPrefixesResolution:
    """Constructor-kwarg resolution for the configurable whitelist."""

    def test_default_when_kwarg_omitted(self):
        client = GoogleGenAIClient()
        assert client._combined_call_prefixes == GoogleGenAIClient._default_combined_call_prefixes

    def test_explicit_kwarg_overrides_default(self):
        client = GoogleGenAIClient(combined_call_prefixes=("foo", "bar"))
        assert client._combined_call_prefixes == ("foo", "bar")

    def test_kwarg_coerced_to_tuple(self):
        """List / generator inputs are coerced to tuple."""
        client = GoogleGenAIClient(combined_call_prefixes=["foo", "bar"])
        assert client._combined_call_prefixes == ("foo", "bar")
        assert isinstance(client._combined_call_prefixes, tuple)
```

---

## Agent Instructions

1. **Read the spec** — especially §2 (Architectural Design) and §6 (Codebase Contract).
2. **Verify the Codebase Contract** in this task:
   - `sed -n '100,200p' packages/ai-parrot/src/parrot/clients/google/client.py` — confirm the line numbers around `_lightweight_model` (108) and `__init__` (121-153) still match.
   - `grep -n "def _is_gemini3_model\|def _requires_thinking\|def _as_model_str" packages/ai-parrot/src/parrot/clients/google/client.py` — confirm these helpers still exist.
3. **Implement**: three small additions to `client.py`, no removals.
4. **Run the tests**:
   ```bash
   cd packages/ai-parrot
   pytest tests/test_google_client.py::TestSupportsCombinedToolsAndSchema -v
   pytest tests/test_google_client.py::TestCombinedCallPrefixesResolution -v
   pytest tests/test_google_client.py -v   # full file — make sure pre-existing tests pass
   ```
5. **Verify scope**: `git diff packages/ai-parrot/src/parrot/clients/google/client.py | head -80` — expect at most ~30 lines of additions, zero removals.
6. Move this file to `sdd/tasks/completed/` and update the per-spec index status to `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-27
**Notes**: Added `_default_combined_call_prefixes` class attribute, `combined_call_prefixes` constructor kwarg, and `_supports_combined_tools_and_schema` static method to GoogleGenAIClient. Also fixed pre-existing test infrastructure issue: added `InvokeResult` stub to `packages/ai-parrot/tests/conftest.py` to allow tests to run. 13 new helper tests pass. Tests must be run with PYTHONPATH pointing to worktree source (not via editable install) due to how git worktrees work with shared source directories.

**Deviations from spec**: Also modified `packages/ai-parrot/tests/conftest.py` (not listed in task scope) to fix a pre-existing stub ordering issue that prevented tests from running at all. The fix adds `InvokeResult` to the `parrot.models.responses` stub.
