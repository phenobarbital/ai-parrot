# TASK-1744: Model ID Extensions for Nova and Multi-Provider

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The existing `bedrock_models.py` translator only maps Claude model IDs. The new `BedrockConverseClient` supports multi-provider models (Nova, Llama, Mistral) and `NovaSonicClient` needs Nova Sonic model IDs. This task extends the translator.

Implements Spec Module 3.

---

## Scope

- Add Nova Sonic model IDs to `PUBLIC_TO_BEDROCK`: `amazon.nova-sonic-v1:0`, `amazon.nova-2-sonic-v1:0`
- Add Nova text model IDs: `amazon.nova-pro-v1:0`, `amazon.nova-lite-v1:0`, `amazon.nova-micro-v1:0`
- Optionally add other common Bedrock models (Llama, Mistral) as needed
- Update `_is_bedrock_id()` to recognize `amazon.` prefix as already-Bedrock-shaped
- Write tests for the new translations

**NOT in scope**: BedrockConverseClient, response models, tool schema.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/bedrock_models.py` | MODIFY | Add model IDs and update `_is_bedrock_id()` |
| `tests/models/test_bedrock_models.py` | CREATE | Unit tests for new translations |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.bedrock_models import translate, PUBLIC_TO_BEDROCK  # verified: parrot/models/bedrock_models.py:87, 37
```

### Existing Signatures to Use
```python
# parrot/models/bedrock_models.py:37
PUBLIC_TO_BEDROCK: dict[str, str] = {
    "claude-sonnet-4-6": "anthropic.claude-sonnet-4-6-20260115-v1:0",
    # ... (Claude models only)
}

# parrot/models/bedrock_models.py:68
def _is_bedrock_id(model_id: str) -> bool:  # checks arn:, anthropic., region prefixes

# parrot/models/bedrock_models.py:87
def translate(public_id: str, region_prefix: str | None = None) -> str:

# parrot/models/bedrock_models.py:26
_REGION_PREFIXES: tuple[str, ...] = ("us.", "eu.", "apac.")
```

### Does NOT Exist
- ~~`PUBLIC_TO_BEDROCK["nova-sonic"]`~~ — not yet; this task adds it
- ~~`_is_bedrock_id()` checking `amazon.`~~ — does not yet check the `amazon.` prefix

---

## Implementation Notes

### Key Constraints
- `_is_bedrock_id()` must recognize `amazon.nova-*` IDs as already Bedrock-shaped (pass-through)
- Nova Sonic model IDs: `amazon.nova-sonic-v1:0` (v1) and `amazon.nova-2-sonic-v1:0` (v2)
- Keep public-to-Bedrock mapping for convenience: `"nova-sonic"` → `"amazon.nova-sonic-v1:0"`, `"nova-2-sonic"` → `"amazon.nova-2-sonic-v1:0"`

---

## Acceptance Criteria

- [ ] `translate("nova-2-sonic")` returns `"amazon.nova-2-sonic-v1:0"`
- [ ] `translate("nova-2-sonic", region_prefix="us")` returns `"us.amazon.nova-2-sonic-v1:0"`
- [ ] `translate("amazon.nova-2-sonic-v1:0")` returns the same ID (pass-through)
- [ ] `_is_bedrock_id("amazon.nova-sonic-v1:0")` returns `True`
- [ ] All tests pass: `pytest tests/models/test_bedrock_models.py -v`

---

## Test Specification

```python
# tests/models/test_bedrock_models.py
import pytest
from parrot.models.bedrock_models import translate, _is_bedrock_id


class TestBedrockModelTranslateNova:
    def test_nova_sonic_v1(self):
        assert translate("nova-sonic") == "amazon.nova-sonic-v1:0"

    def test_nova_2_sonic(self):
        assert translate("nova-2-sonic") == "amazon.nova-2-sonic-v1:0"

    def test_nova_2_sonic_with_region(self):
        assert translate("nova-2-sonic", region_prefix="us") == "us.amazon.nova-2-sonic-v1:0"

    def test_passthrough_amazon_id(self):
        assert translate("amazon.nova-2-sonic-v1:0") == "amazon.nova-2-sonic-v1:0"

    def test_is_bedrock_id_amazon(self):
        assert _is_bedrock_id("amazon.nova-sonic-v1:0") is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Verify** `PUBLIC_TO_BEDROCK` and `translate()` still exist at listed locations
3. **Add** Nova and multi-provider model entries
4. **Update** `_is_bedrock_id()` to check for `amazon.` prefix
5. **Run tests** and verify all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
