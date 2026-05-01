# TASK-952: Migrate JiraSpecialist from system_prompt_template to PromptBuilder

**Feature**: FEAT-139 — Jira Analyst System Prompt Hardening
**Spec**: `sdd/specs/jira-analyst-systemprompt-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-950, TASK-951
**Assigned-to**: unassigned

---

## Context

JiraSpecialist currently uses the legacy monolithic `system_prompt_template`
pattern (line 490: `system_prompt_template: str = JIRA_SPECIALIST_PROMPT`).
The base class `AbstractBot` already supports `PromptBuilder` via the
`_prompt_builder` attribute (line 176) with full two-phase lifecycle
(`_configure_prompt_builder` at line 847). When `_prompt_builder` is set,
it takes precedence over `system_prompt_template`.

This task wires up JiraSpecialist to use `PromptBuilder.default()` plus the
two new layers created in TASK-950 and TASK-951, enabling composable prompt
management and the new anti-hallucination protections.

Implements spec Module 3 (JiraSpecialist PromptBuilder Migration).

---

## Scope

- Replace `system_prompt_template: str = JIRA_SPECIALIST_PROMPT` with a
  `_prompt_builder` class attribute on JiraSpecialist
- The builder must compose: `PromptBuilder.default()` + `JIRA_GROUNDING_LAYER` +
  `JIRA_OPERATIONS_LAYER`
- Remove (or keep as dead code with deprecation comment) the `JIRA_SPECIALIST_PROMPT`
  constant — it is no longer the active prompt source
- Verify that `AbstractBot._configure_prompt_builder()` is called during the
  JiraSpecialist lifecycle (it should be, via `configure()` → `_configure_prompt_builder()`)
- Verify that `clone_for_user()` correctly copies the `_prompt_builder`
- Check for any JiraSpecialist subclasses that override `system_prompt_template`
  and update them
- Write integration test verifying the full prompt assembly

**NOT in scope**: Modifying the prompt text content, adding new anti-hallucination
rules (done in TASK-950), JiraToolkit error hardening (TASK-953).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Replace system_prompt_template with _prompt_builder |
| `packages/ai-parrot/tests/test_jiraspecialist_prompt.py` | CREATE | Integration test for prompt assembly |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.builder import PromptBuilder
# verified: packages/ai-parrot/src/parrot/bots/prompts/builder.py:20

from parrot.bots.prompts.domain_layers import JIRA_GROUNDING_LAYER, JIRA_OPERATIONS_LAYER
# NOTE: These will exist AFTER TASK-950 and TASK-951 are completed.
# Verify they exist before implementing this task.

from parrot.bots.prompts.layers import PromptLayer, LayerPriority
# verified: packages/ai-parrot/src/parrot/bots/prompts/layers.py:22,50
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    _prompt_builder: Optional[PromptBuilder] = None  # line 176
    # When _prompt_builder is set, it is used instead of system_prompt_template.
    # Checked at abstract.py:1059:
    #   if self._prompt_builder and not self._prompt_builder.is_configured:
    #       await self._configure_prompt_builder()

    async def _configure_prompt_builder(self) -> None:  # line 847
        # Resolves static variables (name, role, goal, backstory, rationale,
        # dynamic_values) via builder.configure(). Called automatically during
        # the bot's configure() lifecycle.

    @property
    def prompt_builder(self) -> Optional[PromptBuilder]:  # line 838
    @prompt_builder.setter
    def prompt_builder(self, builder: PromptBuilder) -> None:  # line 842

# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):  # line 468
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW  # line 489
    system_prompt_template: str = JIRA_SPECIALIST_PROMPT  # line 490 — REPLACE THIS
    def __init__(self, **kwargs):  # line 492

    async def clone_for_user(self, user_context) -> "JiraSpecialist":  # line 663
        # Creates isolated per-user clone. Must verify _prompt_builder is
        # correctly transferred or rebuilt in the clone.

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:  # line 20
    @classmethod
    def default(cls) -> PromptBuilder:  # line 44
    def add(self, layer: PromptLayer) -> PromptBuilder:  # line 116
    def clone(self) -> PromptBuilder:  # line 172
    def configure(self, context: Dict[str, Any]) -> None:  # line 184
    def build(self, context: Dict[str, Any]) -> str:  # line 204
    @property
    def is_configured(self) -> bool:  # line 233
```

### Does NOT Exist
- ~~`PromptBuilder.jira()`~~ — no Jira-specific factory; compose inline
- ~~`JiraSpecialist._prompt_builder`~~ — currently None; this task sets it
- ~~`JiraSpecialist.setup_prompt_builder()`~~ — no such method; set as class attribute
- ~~`AbstractBot.set_prompt_builder()`~~ — use the property setter or class attribute

---

## Implementation Notes

### Pattern to Follow
```python
# Follow VoiceBot pattern at packages/ai-parrot/src/parrot/bots/voice.py:100
# which sets _prompt_builder as a class attribute:
class VoiceBot(Chatbot):
    _prompt_builder = PromptBuilder.voice()

# For JiraSpecialist:
class JiraSpecialist(Agent):
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW

    # Build the prompt builder inline
    _prompt_builder = (
        PromptBuilder.default()
        .add(JIRA_GROUNDING_LAYER)
        .add(JIRA_OPERATIONS_LAYER)
    )
    # Remove or comment out: system_prompt_template = JIRA_SPECIALIST_PROMPT
```

### Key Constraints
- The `PromptBuilder.add()` method returns `self` for chaining (line 116-126)
- `_prompt_builder` is a class attribute, not instance. The base class checks
  `self._prompt_builder` which resolves to the class attribute if not overridden
  on the instance. This is the same pattern as `VoiceBot`.
- `clone_for_user()` at line 663 creates a new instance via `type(self)(**self._init_kwargs)`.
  Since `_prompt_builder` is a class attribute, the clone automatically gets it.
  However, verify that the builder's `_configured` state is not shared — if it is,
  each clone may need `builder.clone()`. Check `_configure_prompt_builder` to see
  if it mutates the builder in place (it does, via `configure()` at line 896).
  This means the class-level builder gets mutated on first configure. For per-user
  clones, each must get its own builder instance. Solutions:
  1. Override `__init__` to do `self._prompt_builder = type(self)._prompt_builder.clone()`
  2. Or set it in `post_configure()` instead of as a class attribute
- The `JIRA_SPECIALIST_PROMPT` constant can be kept temporarily (marked with a
  deprecation comment) for reference, or removed entirely.
- The identity line "You are **JiraSpecialist**..." is now in the operations layer.
  The IDENTITY_LAYER provides the generic identity via `$name`, `$role`, `$goal`,
  `$backstory`. Make sure JiraSpecialist's `role`, `goal`, and `backstory` attributes
  align with the identity layer expectations.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/voice.py:100` — VoiceBot _prompt_builder pattern
- `packages/ai-parrot/src/parrot/bots/abstract.py:847-896` — _configure_prompt_builder lifecycle
- `packages/ai-parrot/src/parrot/bots/abstract.py:1059` — _prompt_builder precedence check
- `packages/ai-parrot/src/parrot/bots/jira_specialist.py:663-722` — clone_for_user

---

## Acceptance Criteria

- [ ] JiraSpecialist has `_prompt_builder` set (not None)
- [ ] `system_prompt_template` is no longer the active prompt source
- [ ] Built prompt contains JIRA_GROUNDING_LAYER content (anti-hallucination rules)
- [ ] Built prompt contains JIRA_OPERATIONS_LAYER content (standup, cancellation, etc.)
- [ ] Built prompt contains IDENTITY_LAYER content (agent name, role)
- [ ] Built prompt contains SECURITY_LAYER content
- [ ] `clone_for_user()` produces clones with independent prompt builders
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_jiraspecialist_prompt.py -v`
- [ ] No breaking changes to existing JiraSpecialist behavior

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jiraspecialist_prompt.py
import pytest
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import LayerPriority


class TestJiraSpecialistPromptBuilder:
    def test_prompt_builder_is_set(self):
        """JiraSpecialist class has a _prompt_builder attribute."""
        from parrot.bots.jira_specialist import JiraSpecialist
        assert JiraSpecialist._prompt_builder is not None
        assert isinstance(JiraSpecialist._prompt_builder, PromptBuilder)

    def test_prompt_builder_has_grounding_layer(self):
        """Builder includes the jira_grounding layer."""
        from parrot.bots.jira_specialist import JiraSpecialist
        assert "jira_grounding" in JiraSpecialist._prompt_builder.layer_names

    def test_prompt_builder_has_operations_layer(self):
        """Builder includes the jira_operations layer."""
        from parrot.bots.jira_specialist import JiraSpecialist
        assert "jira_operations" in JiraSpecialist._prompt_builder.layer_names

    def test_built_prompt_contains_grounding(self):
        """Built prompt includes anti-hallucination text."""
        from parrot.bots.jira_specialist import JiraSpecialist
        builder = JiraSpecialist._prompt_builder.clone()
        # Provide minimal context for rendering
        builder.configure({
            "name": "JiraSpecialist",
            "role": "Jira specialist agent",
            "goal": "",
            "capabilities": "",
            "backstory": "",
            "pre_instructions_content": "",
            "extra_security_rules": "",
            "has_tools": True,
            "extra_tool_instructions": "",
            "rationale": "",
        })
        prompt = builder.build({})
        assert "jira_grounding_policy" in prompt
        assert "jira_operations" in prompt

    def test_built_prompt_contains_identity(self):
        """Built prompt includes identity layer."""
        from parrot.bots.jira_specialist import JiraSpecialist
        builder = JiraSpecialist._prompt_builder.clone()
        builder.configure({
            "name": "TestBot",
            "role": "test role",
            "goal": "",
            "capabilities": "",
            "backstory": "",
            "pre_instructions_content": "",
            "extra_security_rules": "",
            "has_tools": False,
            "extra_tool_instructions": "",
            "rationale": "",
        })
        prompt = builder.build({})
        assert "TestBot" in prompt
        assert "agent_identity" in prompt
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-analyst-systemprompt-hardening.spec.md`
2. **Check dependencies** — verify TASK-950 and TASK-951 are in `tasks/completed/`
3. **Verify the new layers exist** — `grep` for `JIRA_GROUNDING_LAYER` and
   `JIRA_OPERATIONS_LAYER` in `domain_layers.py`
4. **Read the VoiceBot pattern** — `packages/ai-parrot/src/parrot/bots/voice.py:100`
5. **Read clone_for_user** — `jira_specialist.py:663-722` to understand cloning
6. **Read _configure_prompt_builder** — `abstract.py:847-896` to understand lifecycle
7. **Implement** the migration
8. **Test manually** — instantiate and check `.prompt_builder.layer_names`
9. **Verify** all acceptance criteria
10. **Move this file** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
