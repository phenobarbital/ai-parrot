# TASK-127: vLLM Factory Registration and Exports

**Feature**: FEAT-022 vLLM Client Integration
**Spec**: `sdd/specs/vllm-client.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-126
**Assigned-to**: null

---

## Context

> This task implements Modules 3 and 4 from the spec: Factory Registration and Client Exports.

Register `vLLMClient` in the client factory and export it from the clients package.

---

## Scope

- Register `vllm` client type in `parrot/clients/factory.py`
- Export `vLLMClient` from `parrot/clients/__init__.py`
- Export vLLM models from `parrot/models/__init__.py`

**NOT in scope**:
- Client implementation (TASK-126)
- Tests (TASK-128)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/factory.py` | MODIFY | Register vllm client type |
| `parrot/clients/__init__.py` | MODIFY | Export vLLMClient |
| `parrot/models/__init__.py` | MODIFY | Export vLLM models |

---

## Implementation Notes

### Factory Registration

Find the client factory registration pattern and add:

```python
# In parrot/clients/factory.py
from .vllm import vLLMClient

# Add to client registry/mapping
CLIENT_REGISTRY = {
    # ... existing clients
    "vllm": vLLMClient,
}
```

Or if using a decorator pattern:
```python
@register_client("vllm")
class vLLMClient(LocalLLMClient):
    ...
```

### Package Exports

```python
# In parrot/clients/__init__.py
# Add to lazy imports or direct exports
from .vllm import vLLMClient

__all__ = [
    # ... existing exports
    "vLLMClient",
]
```

```python
# In parrot/models/__init__.py
from .vllm import (
    VLLMConfig,
    VLLMSamplingParams,
    VLLMLoRARequest,
    VLLMGuidedParams,
    VLLMBatchRequest,
    VLLMBatchResponse,
    pydantic_to_guided_json,
)
```

---

## Acceptance Criteria

- [ ] `vLLMClient` registered in client factory with type `"vllm"`
- [ ] `vLLMClient` exported from `parrot/clients/__init__.py`
- [ ] vLLM models exported from `parrot/models/__init__.py`
- [ ] Factory creates `vLLMClient` when `client_type="vllm"` is requested
- [ ] Linting passes on all modified files

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-126 is in `tasks/completed/`
3. **Find the factory pattern** — look at how other clients are registered
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Modify** factory and export files
6. **Run linting** and fix any issues
7. **Verify** factory creates vLLMClient correctly
8. **Move this file** to `sdd/tasks/completed/TASK-127-vllm-registration.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude session
**Date**: 2026-03-04
**Notes**:
- Updated `parrot/clients/factory.py`:
  - Added import for `vLLMClient`
  - Changed `SUPPORTED_CLIENTS["vllm"]` from `LocalLLMClient` to `vLLMClient`
- Updated `parrot/clients/__init__.py`:
  - Added export for `vLLMClient`
- Updated `parrot/models/__init__.py`:
  - Added exports for all vLLM models (VLLMConfig, VLLMSamplingParams, etc.)
  - Added export for `pydantic_to_guided_json` helper
- Verified factory creates correct client class
- Linting passes on all modified files
