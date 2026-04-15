# TASK-665: Template Auto-Detection Pre-Pass

**Feature**: Multi-Tab Infographic Template + New Component Blocks
**Spec**: `sdd/specs/multi-tab-infographic.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-660
**Assigned-to**: unassigned

---

## Context

This task implements Spec Section 3 (Module 3: Template Auto-Detection). When `get_infographic()` is called with `template=None`, a lightweight LLM pre-pass determines the best template based on the user's question and available templates. This replaces the current behavior where `template=None` means no template instructions are provided.

---

## Scope

- Modify `get_infographic()` in `parrot/bots/abstract.py`:
  - When `template is None`: make a lightweight LLM call asking "which template best fits this question?"
  - Provide the list of available templates (names + descriptions) as context
  - Parse the LLM response to extract a template name
  - Fall back to `"basic"` if the pre-pass fails or returns unknown template
  - Use the detected template for the main generation call
- Keep the pre-pass lightweight: short system prompt, low `max_tokens` (~100)
- Write unit tests (mock the LLM call)

**NOT in scope**: Changing the main ask() call, renderer changes, template definitions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add auto-detection logic in `get_infographic()` |
| `tests/test_infographic_autodetect.py` or extend existing | CREATE/MODIFY | Tests for auto-detection |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.infographic_templates import infographic_registry  # verified: infographic_templates.py:382
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py:2599-2700
async def get_infographic(
    self,
    question: str,
    template: Optional[str] = "basic",   # line 2602 — change default to None
    session_id: Optional[str] = None,
    ...
) -> AIMessage:
    # line 2655-2656: imports
    from ..models.infographic import InfographicResponse
    from ..models.infographic_templates import infographic_registry
    # line 2659-2674: template resolution — THIS IS THE SECTION TO MODIFY
    template_instruction = ""
    if template is not None:
        tpl = infographic_registry.get(template)
        template_instruction = tpl.to_prompt_instruction()
        ...

# packages/ai-parrot/src/parrot/models/infographic_templates.py:369-378
def list_templates_detailed(self) -> List[Dict]:
    """Return name + description for all templates."""
    ...

# AbstractBot.ask() — the method used for LLM calls
# packages/ai-parrot/src/parrot/bots/abstract.py (various lines)
async def ask(self, question, ..., **kwargs) -> AIMessage:
    ...
```

### Does NOT Exist
- ~~`AbstractBot._detect_template`~~ — to be created in this task (or inline in get_infographic)
- ~~`AbstractBot._auto_detect_template`~~ — naming is up to implementer

---

## Implementation Notes

### Pattern to Follow
```python
async def get_infographic(self, question, template=None, ...):
    from ..models.infographic import InfographicResponse
    from ..models.infographic_templates import infographic_registry

    # ── Auto-detect template ──
    if template is None:
        template = await self._detect_infographic_template(question)

    # ── Existing template resolution (unchanged) ──
    template_instruction = ""
    if template is not None:
        tpl = infographic_registry.get(template)
        ...

async def _detect_infographic_template(self, question: str) -> str:
    """Lightweight LLM pre-pass to select the best infographic template."""
    templates = infographic_registry.list_templates_detailed()
    template_list = "\n".join(
        f"- {t['name']}: {t['description']}" for t in templates
    )
    prompt = (
        f"Given the following question/topic, select the SINGLE best infographic template.\n"
        f"Available templates:\n{template_list}\n\n"
        f"Question: {question}\n\n"
        f"Respond with ONLY the template name (e.g., 'basic', 'executive', 'multi_tab'). "
        f"Nothing else."
    )
    try:
        response = await self.ask(
            question=prompt,
            max_tokens=50,
            use_vector_context=False,
            use_conversation_history=False,
        )
        detected = response.content.strip().lower().replace("'", "").replace('"', '')
        # Validate it's a known template
        infographic_registry.get(detected)
        return detected
    except Exception:
        return "basic"
```

### Key Constraints
- The pre-pass must NOT use vector context or conversation history (pure LLM question).
- `max_tokens` should be low (~50) to minimize latency and cost.
- If the LLM returns an unknown template name, fall back to `"basic"`.
- If the pre-pass call itself fails (network error, etc.), fall back to `"basic"`.
- The `get_infographic()` default for `template` should change from `"basic"` to `None` to enable auto-detection by default. This is a minor API change — callers that explicitly pass `template="basic"` are unaffected.

---

## Acceptance Criteria

- [ ] When `template=None`, a pre-pass LLM call determines the template
- [ ] Pre-pass uses available template list with descriptions
- [ ] Valid template name from pre-pass is used for main generation
- [ ] Unknown template name from pre-pass falls back to "basic"
- [ ] Pre-pass failure (exception) falls back to "basic"
- [ ] Pre-pass does not use vector context or conversation history
- [ ] Pre-pass uses low max_tokens
- [ ] `get_infographic(template="executive")` still works as before (explicit template)
- [ ] All tests pass

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestTemplateAutoDetection:
    @pytest.mark.asyncio
    async def test_auto_detect_selects_multi_tab(self):
        """Pre-pass returns 'multi_tab' for methodology question."""
        bot = ...  # setup mock bot
        mock_response = MagicMock()
        mock_response.content = "multi_tab"
        with patch.object(bot, 'ask', new_callable=AsyncMock, return_value=mock_response):
            result = await bot._detect_infographic_template(
                "Create a methodology for AI agent implementation with phases and QA"
            )
            assert result == "multi_tab"

    @pytest.mark.asyncio
    async def test_auto_detect_fallback_on_unknown(self):
        """Falls back to 'basic' when LLM returns unknown template."""
        bot = ...
        mock_response = MagicMock()
        mock_response.content = "nonexistent_template"
        with patch.object(bot, 'ask', new_callable=AsyncMock, return_value=mock_response):
            result = await bot._detect_infographic_template("Some question")
            assert result == "basic"

    @pytest.mark.asyncio
    async def test_auto_detect_fallback_on_error(self):
        """Falls back to 'basic' when pre-pass raises exception."""
        bot = ...
        with patch.object(bot, 'ask', new_callable=AsyncMock, side_effect=Exception("LLM error")):
            result = await bot._detect_infographic_template("Some question")
            assert result == "basic"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/multi-tab-infographic.spec.md`
2. **Check dependencies** — verify TASK-660 is completed (multi_tab template must be registered)
3. **Read** `get_infographic()` in `abstract.py` (lines 2599-2700) before modifying
4. **Verify** `infographic_registry.list_templates_detailed()` exists and works
5. **Implement**, **test**, **move to completed**, **update index**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
