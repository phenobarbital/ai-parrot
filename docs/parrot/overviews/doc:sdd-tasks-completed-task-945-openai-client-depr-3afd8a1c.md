---
type: Wiki Overview
title: 'TASK-945: Add `_normalize_model` chokepoint that emits one-shot DeprecationWarning'
id: doc:sdd-tasks-completed-task-945-openai-client-deprecation-warning-chokepoint-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Once TASK-944 lands, `parrot.models.openai` exposes `is_deprecated`,
relates_to:
- concept: mod:parrot.clients.gpt
  rel: mentions
- concept: mod:parrot.models.openai
  rel: mentions
---

# TASK-945: Add `_normalize_model` chokepoint that emits one-shot DeprecationWarning

**Feature**: FEAT-138 — OpenAI Model Deprecation Refresh
**Spec**: `sdd/specs/openai-model-deprecation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-944
**Assigned-to**: unassigned

---

## Context

Once TASK-944 lands, `parrot.models.openai` exposes `is_deprecated`,
`get_shutoff_date`, and `resolve_alias`. This task wires them into
`OpenAIClient` so any caller passing a deprecated model ID receives a
one-shot Python `DeprecationWarning` (not a logger message — that
distinction was decided as part of the /sdd-spec interview, item 2:
interpretation (b) "Python `DeprecationWarning` once per process").

Implements §2 "Architectural Design — Component Diagram" and Module 2 of §3.

---

## Scope

- Add a module-level `_warned: set[str] = set()` cache to
  `packages/ai-parrot/src/parrot/clients/gpt.py`.
- Add an instance method `OpenAIClient._normalize_model(model)` that:
  1. Coerces `Union[str, OpenAIModel]` to `str`.
  2. If `is_deprecated(s)` and `s not in _warned`, emits
     `warnings.warn(...)` with category `DeprecationWarning` and
     `stacklevel=3`, then adds `s` to `_warned`.
  3. Returns the coerced string unchanged.
- Call `_normalize_model` from every public entry point that takes a
  `model` parameter:
  - `__init__` (only if `model` was supplied via `**kwargs`)
  - `ask` (line 598)
  - `responses` (line 1111)
  - the method at line 1410 (legacy `model: str = "gpt-4-turbo"` — replace
    default in TASK-946, but already wire `_normalize_model` here)
  - lines 1543, 1594, 1651, 1694, 1741, 1806

**NOT in scope**:
- Changing the default values of any `model=` parameter (TASK-946).
- Refreshing `RESPONSES_ONLY_MODELS` / `STRUCTURED_OUTPUT_COMPATIBLE_MODELS`
  (TASK-946).
- Touching `handlers/`, `loaders/`, or any file other than
  `parrot/clients/gpt.py` (TASK-947 / TASK-948).
- Writing tests (TASK-949).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Add module import, `_warned` cache, `_normalize_model` method, and call sites at every public entry point. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already present at packages/ai-parrot/src/parrot/clients/gpt.py:38
from ..models.openai import OpenAIModel

# UPDATE this import to also bring in the new helpers from TASK-944:
from ..models.openai import (
    OpenAIModel,
    is_deprecated,
    get_shutoff_date,
    resolve_alias,
)

# NEW import — add at top of file with other stdlib imports:
import warnings
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(AbstractClient):
    client_type: str = 'openai'                   # line 93
    model: str = OpenAIModel.GPT4_TURBO.value     # line 94 — TASK-946 will change
    client_name: str = 'openai'                   # line 95
    _default_model: str = 'gpt-4o-mini'           # line 96 — TASK-946 will change
    _fallback_model: str = 'gpt-4.1-nano'         # line 97
    _lightweight_model: str = "gpt-4.1"           # line 98

    def __init__(                                 # line 100
        self,
        api_key: str = None,
        base_url: str = "https://api.openai.com/v1",
        **kwargs,
    ): ...

    @staticmethod
    def _is_responses_only(model_str: str) -> bool: ...      # line 248
    @staticmethod
    def _resolve_deep_research_model(model_str: str) -> str: ...  # line 256

    # Methods that accept Union[str, OpenAIModel] model parameter:
    async def ask(self, ..., model=OpenAIModel.GPT4_1, ...): ...     # line 598
    async def responses(self, ..., model=OpenAIModel.GPT4_TURBO, ...): ...  # line 1111
    # method at line 1410 takes `model: str = "gpt-4-turbo"`
    async def <method>(self, ..., model=OpenAIModel.GPT4_TURBO, ...): ...  # lines 1543, 1594, 1651, 1694, 1741
    async def <method>(self, ..., model=OpenAIModel.GPT_4_1_MINI, ...): ...  # line 1806
```

### Call-site Map (verify these line numbers — code may have shifted)

Run before editing:

```bash
grep -n "model: Union\[\|model=OpenAIModel\.\|model: str = \"gpt-" \
  packages/ai-parrot/src/parrot/clients/gpt.py
```

Every method in the result list must have `model = self._normalize_model(model)`
inserted as the FIRST line after parameter validation but BEFORE any use
of `model` (especially before being passed to `_is_responses_only` or
`_resolve_deep_research_model`).

### Does NOT Exist

- ~~`parrot.clients.gpt._normalize_model`~~ — module-level function does NOT exist; the new helper is an INSTANCE method on `OpenAIClient`.
- ~~`parrot.clients.gpt._warned_models`~~ — pick the exact name `_warned` per spec §3 Module 2.
- ~~`logging.deprecation`~~ — use `warnings.warn`, not the logging module. (Spec decision: Python `DeprecationWarning`, not a log line.)
- ~~`OpenAIClient.warn_deprecated`~~ — public method does not exist; the helper is private.
- ~~`asyncio.Lock` around `_warned`~~ — not needed; `set.add` is atomic under the GIL and a duplicate warning is benign.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/clients/gpt.py

import warnings
# ... other imports ...
from ..models.openai import (
    OpenAIModel,
    is_deprecated,
    get_shutoff_date,
    resolve_alias,
)

# Module-level deduplication cache (spec §3 Module 2).
_warned: set[str] = set()


class OpenAIClient(AbstractClient):
    # ... existing class body ...

    def _normalize_model(self, model: Union[str, OpenAIModel]) -> str:
        """Coerce model to str and emit a one-shot DeprecationWarning if deprecated.

        The warning is emitted exactly once per (model, process) using a
        module-level cache. `stacklevel=3` so the warning points at user
        code (e.g. the caller of `ask()`), not at this helper.
        """
        s = model.value if isinstance(model, OpenAIModel) else model
        if is_deprecated(s) and s not in _warned:
            shutoff = get_shutoff_date(s)
            target = resolve_alias(s)
            warnings.warn(
                f"OpenAI model '{s}' is deprecated; shutoff {shutoff}. "
                f"Migrate to '{target}'.",
                DeprecationWarning,
                stacklevel=3,
            )
            _warned.add(s)
        return s
```

### Key Constraints

- Place `_normalize_model` near the top of the class (after `__init__`,
  before `_is_capacity_error`) so it is easy to find.
- Call sites pattern: insert `model = self._normalize_model(model)` as
  the first statement after `async def <name>(...):\n    """docstring"""`.
- For `__init__`, the `model` may arrive via `**kwargs` (`super().__init__`
  consumes it). Apply normalization BEFORE the `super().__init__` call:
  ```python
  if "model" in kwargs:
      kwargs["model"] = self._normalize_model(kwargs["model"])
  ```
- Do NOT auto-substitute `s` with `resolve_alias(s)` — the spec is
  explicit (Module 2 step 3) that `_normalize_model` returns the input
  unchanged. Auto-substitution is a follow-up.
- `stacklevel=3` is the spec's chosen value (Implementation Notes
  "Known Risks / Gotchas"). Honor it.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/gpt.py:248–264` — pattern for adding a small helper method on `OpenAIClient` (`_is_responses_only`, `_resolve_deep_research_model`).
- Spec §7 "Patterns to Follow" — confirms `warnings.warn(..., DeprecationWarning, stacklevel=3)` is the agreed pattern.

---

## Acceptance Criteria

- [ ] `_warned: set[str] = set()` exists at module scope in `parrot/clients/gpt.py`.
- [ ] `OpenAIClient._normalize_model` exists with the signature
      `(self, model: Union[str, OpenAIModel]) -> str`.
- [ ] First call to `_normalize_model("gpt-4-turbo")` emits a
      `DeprecationWarning`. Second call to the same string emits NONE.
- [ ] Call to `_normalize_model("gpt-5-mini")` emits no warning.
- [ ] Every method that takes a `model` parameter calls
      `self._normalize_model(model)` before using it. Cross-check with:
      `grep -n "self._normalize_model" packages/ai-parrot/src/parrot/clients/gpt.py`
      should show ≥ 8 hits (1 in `__init__`, 1 each in
      `ask`, `responses`, lines 1410/1543/1594/1651/1694/1741/1806).
- [ ] `import warnings` and the expanded import from
      `..models.openai` are present at the top of the file.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/gpt.py`.
- [ ] Module imports cleanly: `python -c "from parrot.clients.gpt import OpenAIClient"`.

---

## Test Specification

Tests live in TASK-949, but smoke-check before marking done:

```bash
source .venv/bin/activate
python -c "
import warnings
from parrot.clients.gpt import OpenAIClient
c = OpenAIClient(api_key='dummy')
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    s = c._normalize_model('gpt-4-turbo')
    assert s == 'gpt-4-turbo'
    assert len(w) == 1
    assert issubclass(w[0].category, DeprecationWarning)
    s2 = c._normalize_model('gpt-4-turbo')   # second call: silent
    assert len(w) == 1
print('OK')
"
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/openai-model-deprecation.spec.md`.
2. Verify TASK-944 is in `sdd/tasks/completed/` before starting.
3. Verify the codebase contract by re-running the `grep` command in the
   call-site map; line numbers may have shifted.
4. Update `sdd/tasks/.index.json` → `"in-progress"`.
5. Implement; run the smoke check.
6. Move this file to `sdd/tasks/completed/`, update the index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
