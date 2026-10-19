# TASK-4510: Tenant resolution fixes (review follow-ups)

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4497, TASK-4498
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:ab29c5dd9d83`, `issue:10addb2313ee`

---

## Context

Follow-ups from the FEAT-707 delta review, filed as ledger issues
`issue:ab29c5dd9d83` (minor bug) and `issue:10addb2313ee` (low tech debt) and
promoted by `/sdd-fix` after all FEAT-707 tasks closed:

1. `resolve_request_tenant()` (`handlers/scope.py`) catches every exception,
   including a `web.HTTPException` (`HTTPUnauthorized` / `HTTPForbidden`)
   raised by the scope resolver. A denied request then proceeds with the
   global skill view. The inline comment says "fail closed", but the
   behaviour is a fallback to the global view.
2. `SkillRegistryMixin._resolve_tenant` raises `ValueError` for an empty-string
   tenant. A third-party scope resolver returning `""` to mean "no tenant"
   would make `ask()` / `ask_stream()` fail.
3. `AbstractBot._toolless_prompt_builder()` hard-codes `"available_skills:"`
   while `parrot/skills/mixin.py` owns `TENANT_SKILLS_LAYER_PREFIX`.

---

## Scope

- `ai-parrot-server` `handlers/scope.py`: `resolve_request_tenant()` re-raises
  `web.HTTPException`, keeps the global-view fallback for any other resolver
  failure (comment corrected), and normalises an empty tenant to `None`.
- `ai-parrot-server` `handlers/agents/abstract.py`: `ask_agent()` resolves the
  tenant before its `try/except Exception`, so a resolver's 401/403 reaches the
  client instead of being wrapped into a `RuntimeError` (500). `chat.py`
  already resolves the tenant outside its `try`.
- `ai-parrot` `bots/abstract.py`: `_toolless_prompt_builder()` imports
  `TENANT_SKILLS_LAYER_PREFIX` from `parrot.skills.mixin` (lazily — the skills
  package imports `parrot.bots`).
- Tests for all three items.

**NOT in scope**: changing `_resolve_tenant`'s strictness (the empty-string
normalisation happens at the HTTP boundary); the `_TOOL_DEPENDENT_PROMPT_LAYERS`
class attribute (a class-level import would be circular).

---

## Files to Modify

- `packages/ai-parrot-server/src/parrot/handlers/scope.py`
- `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py`
- `packages/ai-parrot/src/parrot/bots/abstract.py`
- `packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py`
- `packages/ai-parrot/tests/unit/bots/test_pandasagent_use_tools.py`

---

## Codebase Contract

### Verified Imports
- `from parrot.skills.mixin import TENANT_SKILLS_LAYER_PREFIX` (`skills/mixin.py:43`)
- `from parrot.handlers.scope import RequestScope, resolve_request_tenant`
- `from parrot.bots.prompts.layers import PromptLayer`

### Existing Signatures
- `async def resolve_request_tenant(app: Any, request: web.Request) -> str | None` (`handlers/scope.py`)
- `def _toolless_prompt_builder(self) -> PromptBuilder` (`bots/abstract.py`)
- `PromptBuilder.add(layer)`, `.remove(name)`, `.get(name)`, `.clone()`, `.layer_names`

### Does NOT Exist
- A tenant-layer prefix constant in `parrot.bots` — the skills package owns it.

---

## Acceptance Criteria

- [x] A resolver raising `web.HTTPForbidden` makes `resolve_request_tenant()` raise it.
- [x] A resolver returning `tenant=""` makes `resolve_request_tenant()` return `None`.
- [x] Any other resolver exception still returns `None` (global view).
- [x] `AgentHandler.ask_agent()` propagates the resolver's `HTTPForbidden` and never calls `agent.ask()`.
- [x] The tool-less builder drops a layer named `f"{TENANT_SKILLS_LAYER_PREFIX}<tenant>"`
      without mutating the shared builder.

---

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src pytest packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py packages/ai-parrot-server/tests/handlers/test_request_scope.py -q
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src pytest packages/ai-parrot/tests/unit/bots/test_pandasagent_use_tools.py packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py -q
```

---

## Completion Note

**Completed by**: agent:sdd-fix (Claude Opus 5.5), 2026-10-19
**Implementing commit**: 7f319ed85
**Resolves**: `issue:ab29c5dd9d83`, `issue:10addb2313ee`

- `resolve_request_tenant()` re-raises `web.HTTPException`; other resolver
  failures still fall back to the global view (comment corrected); `""` → `None`.
- `ask_agent()` resolves the tenant before its catch-all `try`, otherwise the
  re-raised 401/403 would have been wrapped into a `RuntimeError` (500). This
  file was not named in the ledger issue but the bug fix is ineffective
  without it.
- `_toolless_prompt_builder()` uses `TENANT_SKILLS_LAYER_PREFIX` (lazy import).
- Tests: 4 new (`test_request_tenant_binding.py` ×3,
  `test_pandasagent_use_tools.py` ×1). Validation: server suite 110 passed,
  core tenant/toolless suites 32 passed. `ruff`: the 3 findings in
  `handlers/agents/abstract.py` (B904 ×2, ASYNC230) pre-date this task.
- Core tests needed the compiled `parrot.utils.types` / `parrot.utils.parsers.toml`
  extensions copied from the main checkout into the worktree (untracked).
