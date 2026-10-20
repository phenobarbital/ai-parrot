# TASK-4507: Tenant skill hardening (review follow-ups)

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: done
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

- [x] After `ask()` raises before prompt construction, `current_active_skill()` equals its pre-call value.
- [x] Tenant reset runs even when a reset placed after it would raise.
- [x] A skill description containing `$user_context` renders literally, through both `configure()`+`build()` and `build()` alone.
- [x] Tenant layer conditions honour the instance default tenant outside `ask()`.
- [x] Handler diffs vs `origin/dev` contain only tenant-binding changes.
- [x] Existing FEAT-707 tests pass.

---

## Validation Commands

```bash
pytest packages/ai-parrot/tests/unit/test_skill_tenant_hardening.py packages/ai-parrot/tests/unit/test_ask_tenant_binding.py packages/ai-parrot/tests/unit/test_skill_active_request_local.py packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py -q
pytest packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py -q
```

---

## Completion Note

**Completed by**: agent:sdd-fix (`/sdd-fix issue:8ea16e60de56`), 2026-10-20 · code commit `22eb900e1`

1. `enter_active_skill_scope()` / `exit_active_skill_scope()` in `tenancy.py`; `ask()`/`ask_stream()` open the
   scope before the `try` and restore it in the `finally` (the `/trigger` middleware runs inside `ask()` through the
   INPUT guardrail, so the restore covers every failure path).
2. The tenant reset and the active-skill restore are now the first statements of both `finally` blocks.
3. `$$` escaping was rejected: a CONFIGURE layer is substituted once or twice depending on whether it was added
   before `configure()`, so the escape would be undone. Added `PromptLayer.literal` (verbatim in `render()` and
   `partial_render()`); `render_skills_prompt_layer()` returns literal layers. Their templates contain no
   placeholders, so nothing that used to expand is lost.
4. Bound instead of documented: `tenant_layer_condition()` / `global_layer_condition()` accept a `resolver`
   (default `current_skill_tenant`, so the signature stays backward compatible); the mixin passes `_layer_tenant()`
   (bound tenant, else the instance default `tenant_id`, `None` when `tenant_based=False`).
5. Both handlers restored to the `origin/dev` text plus only the tenant-binding hunks; ruff reports exactly the
   same 8 pre-existing findings as `origin/dev`.

**Validation**: the task's Validation Commands pass (87 + 7). Wider prompt/skill suites: 230 passed, 2 failed in
`tests/test_prompt_caching_claude.py` (`AnthropicClient` has no `_backend_name`); these fail identically on
`origin/dev` and are unrelated.

**Note**: `ensure_worktree` refuses an existing branch, so the worktree was attached by hand to the existing
`feat-FEAT-707-per-tenant-skills` branch (its stale local pointer held only `origin/dev` commits and was repointed to
the origin tip). `layers.py` was not black-clean before this change and was left unformatted to avoid churn.
