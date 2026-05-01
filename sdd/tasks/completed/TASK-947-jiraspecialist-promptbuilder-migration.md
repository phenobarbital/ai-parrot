# TASK-947: Migrate JiraSpecialist to PromptBuilder

**Feature**: FEAT-138 — jira_analyst_systemprompt_hardening
**Spec**: `sdd/specs/jira_analyst_systemprompt_hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-946
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of FEAT-138. With the two new layers registered
(TASK-946), `JiraSpecialist` switches from the legacy monolithic
`system_prompt_template = JIRA_SPECIALIST_PROMPT` to a layered prompt
built via `PromptBuilder.default()` plus the two Jira layers.

This task **deletes the `JIRA_SPECIALIST_PROMPT` literal entirely** in
the same change-set (Q3 resolved as "delete immediately"). The
`Jirachi(JiraSpecialist)` concrete subclass must continue working
without code changes.

---

## Scope

- In `JiraSpecialist`:
  - Delete the class attribute `system_prompt_template`
    (`jira_specialist.py:490`).
  - In `__init__`, install the layered builder before
    `super().__init__()`. Use the `prompt_builder=` kwarg path on
    `AbstractBot` (already exists).
  - Build via:
    ```python
    builder = PromptBuilder.default()
    builder.add(get_domain_layer("jira_workflow"))
    builder.add(get_domain_layer("jira_grounding"))
    ```
  - Preserve `injection_probability_threshold = 0.995` and
    `_init_kwargs` snapshot for `clone_for_user`.
- Delete the entire `JIRA_SPECIALIST_PROMPT` string literal
  (`jira_specialist.py:152-461`). No deprecation shim, no re-export.
- Verify `Jirachi` (the public concrete subclass) instantiates and
  exposes both Jira layers via `prompt_builder.layer_names`.

**NOT in scope**: re-implementing the workflow text (TASK-944),
defining the grounding layer (TASK-945), changing `JiraToolkit`
(TASK-948).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Drop `system_prompt_template`, drop literal, install builder |
| `packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py` | CREATE | Tests for builder wiring + Jirachi inheritance |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/prompts/__init__.py:14, 28, 36-37
from parrot.bots.prompts import (
    PromptBuilder,
    get_domain_layer,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py:468
class JiraSpecialist(Agent):
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW              # line 489 — keep
    system_prompt_template: str = JIRA_SPECIALIST_PROMPT    # line 490 — DELETE
    def __init__(self, **kwargs):                           # line 492
        kwargs.setdefault("injection_probability_threshold", 0.995)  # line 497 — keep
        self._init_kwargs: Dict[str, Any] = dict(kwargs)             # line 503 — keep
        super().__init__(**kwargs)                                    # line 504

# packages/ai-parrot/src/parrot/bots/abstract.py:118, 175-176, 838-845
from .prompts.builder import PromptBuilder
class AbstractBot(...):
    _prompt_builder: Optional[PromptBuilder] = None   # line 176
    @property
    def prompt_builder(self) -> Optional[PromptBuilder]
    @prompt_builder.setter
    def prompt_builder(self, builder: PromptBuilder)

# packages/ai-parrot/src/parrot/bots/abstract.py:235-243
# AbstractBot.__init__ accepts prompt_builder= kwarg (or prompt_preset=)
# When set, it bypasses the legacy system_prompt_template path.

# packages/ai-parrot/src/parrot/bots/prompts/builder.py:45, 116, 239
class PromptBuilder:
    @classmethod
    def default(cls) -> PromptBuilder    # line 45 — IDENTITY/SECURITY/KNOWLEDGE/USER_SESSION/TOOLS/OUTPUT/BEHAVIOR
    def add(self, layer: PromptLayer) -> PromptBuilder   # line 116
    @property
    def layer_names(self) -> List[str]   # line 239
```

```python
# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:183
def get_domain_layer(name: str) -> PromptLayer
```

### Does NOT Exist

- ~~`PromptBuilder.jira()`~~ — no factory; assemble via `default() + add()`.
- ~~`AbstractBot.set_prompt_builder()`~~ — use the `prompt_builder=` kwarg
  or the property setter.
- ~~`JiraSpecialist.use_layers()`~~ — invented method; do not add it.
- ~~Re-exporting `JIRA_SPECIALIST_PROMPT` for backwards compat~~ —
  Q3 resolution: delete outright, no shim.
- ~~`from parrot.bots.jira_specialist import JIRA_SPECIALIST_PROMPT`~~ —
  symbol removed; any external import (none in repo) will hard-fail.

---

## Implementation Notes

### Pattern to Follow

```python
class JiraSpecialist(Agent):
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW

    def __init__(self, **kwargs):
        kwargs.setdefault("injection_probability_threshold", 0.995)
        kwargs.setdefault("prompt_builder", self._build_jira_prompt_builder())
        self._init_kwargs: Dict[str, Any] = dict(kwargs)
        super().__init__(**kwargs)
        self._standup_config = DailyStandupConfig()
        self._redis: Optional[redis.Redis] = None
        self._developers: List[Developer] = []
        self._wrapper = None
        self.jira_toolkit: Optional[JiraToolkit] = None

    @staticmethod
    def _build_jira_prompt_builder() -> PromptBuilder:
        from parrot.bots.prompts import PromptBuilder, get_domain_layer
        builder = PromptBuilder.default()
        builder.add(get_domain_layer("jira_workflow"))
        builder.add(get_domain_layer("jira_grounding"))
        return builder
```

### Key Constraints

- Use `kwargs.setdefault("prompt_builder", ...)` so subclasses
  (`Jirachi`) can override by passing their own builder.
- Build the layered builder via a `@staticmethod` so subclasses can
  call it without instance state.
- Do NOT remove `set_wrapper`, `load_developers`, `agent_tools`,
  `post_configure`, or any other method on `JiraSpecialist`.
- After deletion, `JIRA_SPECIALIST_PROMPT` must not appear anywhere in
  `jira_specialist.py` (verify with `grep`).

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/abstract.py:243` — where the
  `system_prompt_template` kwarg is read; confirm it tolerates absence.
- `packages/ai-parrot/src/parrot/bots/abstract.py:847` —
  `_configure_prompt_builder` runs at `configure()` time to resolve
  CONFIGURE-phase vars; nothing to add for this task.
- Existing `Jirachi` subclass (search `class Jirachi`) — must remain
  untouched; verify it instantiates after the migration.

---

## Acceptance Criteria

- [ ] `JiraSpecialist().prompt_builder` is a `PromptBuilder` instance
      whose `layer_names` contains both `jira_workflow` and
      `jira_grounding`.
- [ ] `JiraSpecialist` no longer defines a `system_prompt_template`
      class attribute (verify with `inspect`).
- [ ] `JIRA_SPECIALIST_PROMPT` is fully removed from
      `jira_specialist.py`. `grep -n JIRA_SPECIALIST_PROMPT
      packages/ai-parrot/src/parrot/bots/jira_specialist.py` returns
      nothing.
- [ ] `class Jirachi(JiraSpecialist): pass` (or the actual Jirachi
      subclass) instantiates and inherits both layers.
- [ ] `injection_probability_threshold` default is still `0.995`.
- [ ] All existing tests in
      `packages/ai-parrot/tests/test_jira_*.py` still pass without
      modification.
- [ ] `pytest packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py -v`
      passes.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py
import inspect
import pytest

from parrot.bots.jira_specialist import JiraSpecialist
from parrot.bots.prompts import PromptBuilder


@pytest.fixture
def specialist():
    return JiraSpecialist(name="TestJira", chatbot_id="test-jira")


def test_specialist_has_prompt_builder(specialist):
    assert isinstance(specialist.prompt_builder, PromptBuilder)


def test_specialist_layers_include_jira_layers(specialist):
    names = specialist.prompt_builder.layer_names
    assert "jira_workflow" in names
    assert "jira_grounding" in names


def test_specialist_no_system_prompt_template_class_attr():
    assert "system_prompt_template" not in JiraSpecialist.__dict__


def test_jira_specialist_prompt_constant_removed():
    import parrot.bots.jira_specialist as mod
    assert not hasattr(mod, "JIRA_SPECIALIST_PROMPT")


def test_injection_threshold_preserved(specialist):
    assert specialist.injection_probability_threshold == pytest.approx(0.995)


def test_subclass_inherits_layers():
    class _Sub(JiraSpecialist):
        pass
    sub = _Sub(name="SubJira", chatbot_id="sub-jira")
    assert "jira_workflow" in sub.prompt_builder.layer_names
    assert "jira_grounding" in sub.prompt_builder.layer_names
```

---

## Agent Instructions

1. Verify TASK-946 is completed and the registry resolves both layers.
2. Update index → `"in-progress"`.
3. Implement the migration in a single logical commit.
4. Run the new test, the existing `test_jira_*.py` suite, and any
   `Jirachi` instantiation smoke test.
5. Run `grep` to confirm `JIRA_SPECIALIST_PROMPT` is fully gone.
6. Move file to `completed/`; update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
