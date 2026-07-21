---
type: Wiki Overview
title: 'TASK-948: Partition `LLMClient._get_supported_models` into active/deprecated'
id: doc:sdd-tasks-completed-task-948-llm-handler-partition-active-deprecated-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: returns a flat list of model IDs per provider. Once TASK-944 lands the
relates_to:
- concept: mod:parrot.handlers.llm
  rel: mentions
- concept: mod:parrot.models.openai
  rel: mentions
---

# TASK-948: Partition `LLMClient._get_supported_models` into active/deprecated

**Feature**: FEAT-138 — OpenAI Model Deprecation Refresh
**Spec**: `sdd/specs/openai-model-deprecation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-944
**Assigned-to**: unassigned

---

## Context

`parrot/handlers/llm.py` exposes `GET /api/v1/ai/clients/models` which
returns a flat list of model IDs per provider. Once TASK-944 lands the
OpenAI enum no longer contains deprecated IDs, but downstream UIs may
still need to recognise legacy IDs that customers have saved in their
configurations. The spec (Module 6) calls for a partitioned response:
`{"active": [...], "deprecated": [...]}` for OpenAI/Azure, while keeping
the existing flat-list shape for other providers until they undergo
their own deprecation work.

Implements Module 6 of §3.

---

## Scope

- Update `LLMClient._get_supported_models` to return:
  - For `provider in {"openai", "azure"}`: a `dict[str, list[str]]` with
    keys `"active"` (the enum values) and `"deprecated"`
    (`list(DEPRECATIONS.keys())`).
  - For all other providers: keep the existing flat `List[str]` return.
- Update the method signature/return type to
  `Union[List[str], Dict[str, List[str]]]`.
- Update the docstring to describe both shapes.
- Update `_list_models()` (the GET handler) so the response payload
  reflects the new shape without breaking other providers.

**NOT in scope**:
- Adding partitioning for `groq`, `claude`, or `google` — those need
  their own deprecation registries, which are out of scope for this
  feature.
- Changing the URL or auth decorators on the endpoint.
- Adding pagination, filtering, or any other feature.
- Writing tests (TASK-949).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/llm.py` | MODIFY | Update `_get_supported_models` and `_list_models` per spec Module 6. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/handlers/llm.py:21 (existing)
try:
    from parrot.models.openai import OpenAIModel
except ImportError:
    OpenAIModel = None

# UPDATE this guarded import to also bring in DEPRECATIONS:
try:
    from parrot.models.openai import OpenAIModel, DEPRECATIONS
except ImportError:
    OpenAIModel = None
    DEPRECATIONS = None
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/llm.py
@is_authenticated()
@user_session()
class LLMClient(BaseView):
    _logger_name: str = "Parrot.LLMClient"               # line 53

    def post_init(self, *args, **kwargs):                # line 55
        self.logger = logging.getLogger(self._logger_name)

    def _get_supported_models(self, provider: str) -> List[str]:   # line 58
        provider = provider.lower()
        if provider in ['openai', 'azure'] and OpenAIModel:
            return [m.value for m in OpenAIModel]
        elif provider == 'groq' and GroqModel:
            return [m.value for m in GroqModel]
        elif provider in ['anthropic', 'claude'] and ClaudeModel:
            return [m.value for m in ClaudeModel]
        elif provider == 'google' and GoogleModel:
            return [m.value for m in GoogleModel]
        return []

    async def get(self):                                 # line 74
        if 'models' in self.request.path:
            return self._list_models()
        return self.json_response({...})

    def _list_models(self):                              # line 88
        qs = self.query_parameters(self.request)
        client_filter = qs.get('client')
        if client_filter:
            if client_filter not in SUPPORTED_CLIENTS:
                return self.error(...)
            models = self._get_supported_models(client_filter)
            return self.json_response({"client": client_filter, "models": models})
        all_models = {}
        for client in SUPPORTED_CLIENTS:
            models = self._get_supported_models(client)
            if models:
                all_models[client] = models
        return self.json_response(all_models)
```

### Target Signature (after this task)

```python
def _get_supported_models(
    self, provider: str,
) -> Union[List[str], Dict[str, List[str]]]:
    """Return supported model IDs for a given provider.

    For ``openai`` / ``azure``: returns a dict
    ``{"active": [...], "deprecated": [...]}`` so the public endpoint
    can surface deprecated IDs separately.

    For all other providers: returns a flat ``List[str]`` (unchanged).
    """
    provider = provider.lower()
    if provider in ['openai', 'azure'] and OpenAIModel:
        active = [m.value for m in OpenAIModel]
        deprecated = list(DEPRECATIONS.keys()) if DEPRECATIONS else []
        return {"active": active, "deprecated": deprecated}
    elif provider == 'groq' and GroqModel:
        return [m.value for m in GroqModel]
    elif provider in ['anthropic', 'claude'] and ClaudeModel:
        return [m.value for m in ClaudeModel]
    elif provider == 'google' and GoogleModel:
        return [m.value for m in GoogleModel]
    return []
```

### Does NOT Exist

- ~~`parrot.models.openai.ACTIVE_MODELS`~~ — no such module-level constant. Build the list from `OpenAIModel` members.
- ~~`parrot.models.openai.deprecated_ids()`~~ — no such function. Use `list(DEPRECATIONS.keys())`.
- ~~`LLMClient.list_models_handler`~~ — the public method is `get()`; the helper is the underscore-prefixed `_list_models`.

---

## Implementation Notes

### Pattern to Follow

The change to `_list_models` is minimal — it already wraps the return
in `json_response`; just ensure the dict shape is preserved when the
helper returns a dict instead of a list:

```python
def _list_models(self):
    qs = self.query_parameters(self.request)
    client_filter = qs.get('client')
    if client_filter:
        if client_filter not in SUPPORTED_CLIENTS:
            return self.error(f"Client '{client_filter}' not supported.", status=404)
        models = self._get_supported_models(client_filter)
        return self.json_response({"client": client_filter, "models": models})
    all_models = {}
    for client in SUPPORTED_CLIENTS:
        models = self._get_supported_models(client)
        if models:
            all_models[client] = models
    return self.json_response(all_models)
```

The existing `_list_models` body works with both shapes — `json_response`
serialises `dict` and `list` equivalently. Verify by reading the body
after editing; do not refactor it.

### Key Constraints

- Update the type hint at the top of the method: `Union[List[str], Dict[str, List[str]]]`.
- Add `Dict, Union` to the existing `from typing import` if missing.
- Keep the guarded `try/except ImportError` pattern — this module already
  uses it for optional providers.
- Do NOT change the response shape for non-OpenAI providers.

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/llm.py` — full edit target.

---

## Acceptance Criteria

- [ ] `_get_supported_models("openai")` returns
      `{"active": [...], "deprecated": [...]}`.
- [ ] `_get_supported_models("azure")` returns the same shape.
- [ ] `_get_supported_models("groq")` returns a flat `List[str]`.
- [ ] `_get_supported_models("claude")` returns a flat `List[str]`.
- [ ] `_get_supported_models("google")` returns a flat `List[str]`.
- [ ] `_get_supported_models("unknown")` returns `[]` (unchanged).
- [ ] Type hint on the method is `Union[List[str], Dict[str, List[str]]]`.
- [ ] Docstring describes both shapes.
- [ ] `from parrot.models.openai import OpenAIModel, DEPRECATIONS` is the
      new guarded import.
- [ ] Module imports cleanly.
- [ ] No linting errors:
      `ruff check packages/ai-parrot/src/parrot/handlers/llm.py`.

---

## Test Specification

Tests live in TASK-949. Smoke check:

```bash
source .venv/bin/activate
python -c "
from parrot.handlers.llm import LLMClient
inst = LLMClient.__new__(LLMClient)
out = inst._get_supported_models('openai')
assert isinstance(out, dict), out
assert set(out.keys()) == {'active', 'deprecated'}
assert 'gpt-5-mini' in out['active']
assert 'gpt-3.5-turbo-0125' in out['deprecated']
out_groq = inst._get_supported_models('groq')
assert isinstance(out_groq, list)
print('OK')
"
```

(`__new__` skips `BaseView.__init__`; that's fine for testing the pure
helper.)

---

## Agent Instructions

1. Verify TASK-944 in `sdd/tasks/completed/`.
2. Update `.index.json` → `"in-progress"`.
3. Implement; run smoke check.
4. Move file to `sdd/tasks/completed/`, update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
