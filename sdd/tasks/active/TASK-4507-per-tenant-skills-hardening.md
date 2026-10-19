# TASK-4507: Tenant skill hardening (review follow-ups)

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4496, TASK-4497, TASK-4498, TASK-4501
**Assigned-to**: unassigned
**Discovered-from**: `issue:8ea16e60de56`

---

## Context

Follow-ups from the FEAT-707 code review, filed as ledger issue
`issue:8ea16e60de56` and promoted by `/sdd-fix`. Five items:

1. A skill activated by `/trigger` (via the INPUT guardrail → prompt-middleware
   path inside `ask()`) leaves the `parrot_active_skill` ContextVar set when
   `ask()` fails before `create_system_prompt()` consumes it. In long-lived
   tasks (Telegram polling) the skill leaks into the next request.
2. The tenant ContextVar reset is the last statement of the `finally` in
   `ask()`/`ask_stream()`; an earlier failing reset would skip it.
3. `render_skills_prompt_layer()` output goes through
   `Template.safe_substitute` (`PromptLayer.render` / `partial_render`), so a
   skill description containing `$user_context` is expanded. A CONFIGURE layer
   can be substituted once or twice (depending on whether it was added before
   `configure()`), so `$$` escaping is not reliable.
4. Tenant prompt-layer conditions read only `current_skill_tenant()`; outside
   `ask()`/`ask_stream()` they ignore the instance default `tenant_id`, unlike
   `current_skill_view()`.
5. `handlers/agents/abstract.py` and `handlers/chat.py` carry unrelated
   cosmetic (formatter) edits on the feature branch.

---

## Scope

- `parrot/skills/tenancy.py`: add `enter_active_skill_scope() -> Token` and
  `exit_active_skill_scope(token)` (snapshot / restore the active-skill
  ContextVar).
- `parrot/bots/base.py`: in `ask()` and `ask_stream()` open the active-skill
  scope at the start of the `try`; in the `finally`, run the tenant reset and the
  active-skill restore FIRST, before the other resets.
- `parrot/bots/prompts/layers.py`: add a `literal: bool = False` field to
  `PromptLayer`; a literal layer's template is returned verbatim by `render()`
  and `partial_render()` (condition still honoured; `partial_render` propagates
  `literal`).
- `parrot/skills/prompt.py`: `render_skills_prompt_layer()` returns
  `literal=True` layers; `tenant_layer_condition()` / `global_layer_condition()`
  accept an optional `resolver` callable (default `current_skill_tenant`).
- `parrot/skills/mixin.py`: pass a resolver that falls back to the instance
  default tenant (`_layer_tenant()`), consistent with `current_skill_view()`.
- `ai-parrot-server` `handlers/agents/abstract.py` and `handlers/chat.py`:
  restore the pre-feature text and keep only the tenant-binding changes.
- Tests for items 1–4.

**NOT in scope**: changing `create_system_prompt()`'s consume-and-clear logic;
reformatting any other file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | MODIFY | active-skill scope helpers |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | scope + reset ordering in ask/ask_stream |
| `packages/ai-parrot/src/parrot/bots/prompts/layers.py` | MODIFY | `PromptLayer.literal` |
| `packages/ai-parrot/src/parrot/skills/prompt.py` | MODIFY | literal skills layer, condition resolver |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `_layer_tenant()` resolver wiring |
| `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` | MODIFY | drop cosmetic edits |
| `packages/ai-parrot-server/src/parrot/handlers/chat.py` | MODIFY | drop cosmetic edits |
| `packages/ai-parrot/tests/unit/test_skill_tenant_hardening.py` | CREATE | tests for items 1–4 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.tenancy import current_skill_tenant, current_active_skill, set_active_skill  # tenancy.py:81,96,101
from parrot.skills.prompt import render_skills_prompt_layer, tenant_layer_condition, global_layer_condition
from parrot.bots.prompts import PromptLayer, RenderPhase
```

### Existing Signatures
```python
# parrot/skills/tenancy.py
_active_skill: ContextVar[Optional[SkillDefinition]]  # line 78
# parrot/skills/mixin.py
def _enter_skill_tenant(self, tenant, ctx) -> Optional[Token]  # line 182
def _exit_skill_tenant(self, token) -> None                    # line 188
# parrot/bots/prompts/layers.py
@dataclass(frozen=True) class PromptLayer: name, priority, template, phase, condition, required_vars, cacheable
```

### Does NOT Exist
- `PromptLayer.literal` (added by this task)
- `parrot.skills.tenancy.enter_active_skill_scope` (added by this task)

---

## Acceptance Criteria

- [ ] After `ask()` raises before prompt construction, `current_active_skill()` equals its pre-call value.
- [ ] Tenant reset runs even when a reset placed after it would raise.
- [ ] A skill description containing `$user_context` renders literally, through both `configure()`+`build()` and `build()` alone.
- [ ] Tenant layer conditions honour the instance default tenant outside `ask()`.
- [ ] Handler diffs vs `origin/dev` contain only tenant-binding changes.
- [ ] Existing FEAT-707 tests pass.

---

## Validation Commands

```bash
pytest packages/ai-parrot/tests/unit/test_skill_tenant_hardening.py packages/ai-parrot/tests/unit/test_ask_tenant_binding.py packages/ai-parrot/tests/unit/test_skill_active_request_local.py packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py -q
pytest packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py -q
```

---

## Completion Note

_Filled on close._
