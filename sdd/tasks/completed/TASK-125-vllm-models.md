# TASK-125: vLLM Pydantic Models

**Feature**: FEAT-022 vLLM Client Integration
**Spec**: `sdd/specs/vllm-client.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: null

---

## Context

> This task implements Module 1 from the spec: vLLM Pydantic Models.

Create Pydantic models for vLLM-specific configuration, requests, and responses.

---

## Scope

- Create `VLLMConfig` model for client configuration
- Create `VLLMSamplingParams` model for extended sampling parameters
- Create `VLLMLoRARequest` model for LoRA adapter configuration
- Create `VLLMGuidedParams` model for guided decoding parameters
- Create `VLLMBatchRequest` and `VLLMBatchResponse` models for batch API
- Create helper function to convert Pydantic models to `guided_json` schema

**NOT in scope**:
- Client implementation (TASK-126)
- Tests (TASK-128)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/models/vllm.py` | CREATE | vLLM Pydantic models |

---

## Implementation Notes

### VLLMConfig Model

```python
from pydantic import BaseModel, Field
from typing import Optional

class VLLMConfig(BaseModel):
    """Configuration for vLLM client."""
    base_url: str = Field(
        default="http://localhost:8000/v1",
        description="vLLM server base URL"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for authentication"
    )
    timeout: int = Field(
        default=120,
        description="Request timeout in seconds"
    )
```

### VLLMSamplingParams Model

```python
class VLLMSamplingParams(BaseModel):
    """Extended sampling parameters for vLLM."""
    top_k: int = Field(default=-1, description="Top-k sampling (-1 to disable)")
    min_p: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum probability threshold")
    repetition_penalty: float = Field(default=1.0, ge=0.0, description="Repetition penalty")
    length_penalty: float = Field(default=1.0, description="Length penalty for beam search")
```

### VLLMGuidedParams Model

```python
class VLLMGuidedParams(BaseModel):
    """Guided decoding parameters for constrained generation."""
    guided_json: Optional[Dict[str, Any]] = Field(default=None, description="JSON schema for constrained output")
    guided_regex: Optional[str] = Field(default=None, description="Regex pattern to match")
    guided_choice: Optional[List[str]] = Field(default=None, description="List of valid choices")
```

### Helper Function for Pydantic to guided_json

```python
def pydantic_to_guided_json(model: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model class to vLLM guided_json schema.

    Args:
        model: A Pydantic BaseModel class

    Returns:
        JSON schema dict compatible with vLLM's guided_json parameter
    """
    return model.model_json_schema()
```

---

## Acceptance Criteria

- [ ] `VLLMConfig` model created with base_url, api_key, timeout fields
- [ ] `VLLMSamplingParams` model created with top_k, min_p, repetition_penalty, length_penalty
- [ ] `VLLMLoRARequest` model created with adapter name and optional weight
- [ ] `VLLMGuidedParams` model created with guided_json, guided_regex, guided_choice
- [ ] `VLLMBatchRequest` model created for batch API requests
- [ ] `VLLMBatchResponse` model created for batch API responses
- [ ] `pydantic_to_guided_json()` helper function converts Pydantic models to JSON schema
- [ ] All models have proper Field descriptions for documentation
- [ ] Linting passes: `ruff check parrot/models/vllm.py`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Create** `parrot/models/vllm.py` with all models
4. **Run linting** and fix any issues
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-125-vllm-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude session
**Date**: 2026-03-04
**Notes**:
- Created `parrot/models/vllm.py` with all required models
- `VLLMConfig` — client configuration (base_url, api_key, timeout)
- `VLLMSamplingParams` — extended sampling with `to_extra_body()` helper
- `VLLMLoRARequest` — LoRA adapter configuration with `to_extra_body()` helper
- `VLLMGuidedParams` — guided decoding with mutual exclusivity validation
- `VLLMBatchRequest` / `VLLMBatchResponse` — batch API models
- `VLLMServerInfo` — server metadata model
- `pydantic_to_guided_json()` — helper to convert Pydantic models to JSON schema
- All models include Field descriptions for documentation
- Linting passes
