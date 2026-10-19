# TASK-4500: Telegram tenant binding

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4494
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 and design-research S3. One Telegram bot = one customer:
the tenant is a static field of the bot's YAML entry (`TelegramAgentConfig.tenant`),
passed explicitly as `tenant=` on every `agent.ask()`. It is also copied into
`UserContext.metadata["tenant"]` and into the permission context's
`UserSession.tenant_id` (replacing the literal `"default"`). The shared agent's
instance default is never mutated per user (AC-T3). The `/skill` command must
use the request-local `set_active_skill()` instead of writing
`agent._active_skill` (S5), and skill listing/resolution must use the tenant view.

---

## Scope

- `TelegramAgentConfig.tenant: Optional[str] = None` + `from_dict` parsing.
- `_build_permission_context(..., tenant_id=None)` → `UserSession(tenant_id=tenant_id or "default")`; its caller passes `self.config.tenant`.
- `_build_user_context`: `metadata["tenant"] = self.config.tenant` when set.
- `_invoke_agent`: both `agent.ask(...)` calls gain `tenant=self.config.tenant`.
- `_list_agent_skills` and `_resolve_skill_definition`: use `agent.current_skill_view(self.config.tenant)` when the agent has it (duck-typed), else today's `_skill_file_registry`.
- `/skill` handler: `set_active_skill(skill_def)` instead of `self.agent._active_skill = skill_def`, and the following `self.agent.ask(...)` gains `tenant=self.config.tenant`.
- Write `packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py`.

**NOT in scope**: deriving the tenant from the Navigator login (Non-Goal), core changes, other wrappers (MS Teams, Slack).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `tenant` field + `from_dict` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | six edit sites |
| `packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.models import TelegramAgentConfig   # verified: telegram/models.py:42
from parrot.skills.tenancy import set_active_skill                    # TASK-4494
from parrot.auth.permission import PermissionContext, UserSession     # verified: auth/permission.py:134 / :47 (lazily imported in wrapper.py:1293-1296)
from parrot.auth.context import UserContext                           # verified: wrapper.py:59 imports `from ...auth.context import UserContext`
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:                                            # line 42
    name: str; chatbot_id: str; bot_token: Optional[str] = None; allowed_chat_ids: Optional[List[int]] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None                      # line 74
    kind: str = "telegram"; commands: Dict[str, str] = field(default_factory=dict); ...
    @classmethod from_dict(...):  return cls(..., system_prompt_override=data.get("system_prompt_override"), ...)  # line 270

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
self.config = config                                                  # line 134 (TelegramAgentConfig)
    @staticmethod
    def _build_permission_context(session: TelegramUserSession, chat_id: Optional[int] = None,
                                  bot_id: Optional[str] = None) -> Any:          # 1265-1270
        user_session = UserSession(user_id=str(session.telegram_id), tenant_id="default", roles=frozenset())  # 1301-1305
    def _build_user_context(self, session: TelegramUserSession) -> UserContext:    # 1331; metadata dict built 1338-1348
    async def _invoke_agent(self, session, question, *, memory, output_mode=OutputMode.TELEGRAM, message=None, attachments=None)  # 1450
        permission_context = self._build_permission_context(session, chat_id=chat_id, bot_id=self._bot_id)   # 1489 (only caller)
        agent.ask(enriched, user_id=..., session_id=..., memory=memory, output_mode=output_mode,
                  permission_context=permission_context, attachments=attachments)   # 1514-1521 (singleton) and 1540-1547 (per-user)
    def _list_agent_skills(self) -> list[dict]:                                     # 1938; file_registry = getattr(self.agent, "_skill_file_registry", None) at 1954
    async def _resolve_skill_definition(self, name: str):                          # 1993; file_registry = getattr(self.agent, "_skill_file_registry", None) at 1999
                    self.agent._active_skill = skill_def                            # 2083
                    response = await self.agent.ask(question, output_mode=OutputMode.TELEGRAM,)   # 2084-2087
```

### Does NOT Exist
- ~~`TelegramAgentConfig.tenant`~~ — added here.
- ~~`TelegramUserSession.tenant` / `.programs`~~ — not available; tenant is static per bot.
- ~~Assigning `agent.tenant_id` / `agent._tenant_id` from the wrapper or `post_login`~~ — forbidden (AC-T3).
- The wrapper is NOT importable in a bare worktree without aiogram + the Cython `.so` (see `tests/telegram/test_deeplink_resume.py` docstring) — tests must exercise `TelegramAgentConfig` directly and the wrapper methods through `pytest.importorskip("aiogram")` or by calling the unbound methods on a `MagicMock` self where possible.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._build_permission_context",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._build_user_context",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._invoke_agent",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._list_agent_skills"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The flag on the agent stays the single switch: if the agent is not `tenant_based`, `tenant=` is ignored by core (TASK-4499) — no wrapper logic needed.
- Validate the configured tenant once at config load? NO — keep the dataclass dumb; core validates on use (AC-R2). Document that an invalid YAML tenant makes every ask fail fast.
- Keep `_build_permission_context` a `@staticmethod`; add the new keyword at the end with default `None`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the field + `from_dict` line — *why*: YAML `tenant:` per bot (AC-T1).
2. Thread `tenant_id` into `_build_permission_context` and its single caller — *why*: AC-T2.
3. Add `metadata["tenant"]` in `_build_user_context` — *why*: AC-T2 (channel-agnostic carrier for `post_login`).
4. Add `tenant=self.config.tenant` to both `agent.ask` calls — *why*: AC-T1.
5. Make listing/resolution view-based — *why*: AC-C3.
6. Replace the `_active_skill` write in `/skill` — *why*: S5, AC-A3.
7. Tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    system_prompt_override: Optional[str] = None' .../telegram/models.py)
# AFTER — insert below `    system_prompt_override: Optional[str] = None` (models.py:74)
    # FEAT-707: static per-bot tenant (one bot = one customer) for per-tenant skills.
    tenant: Optional[str] = None
# occurrences: 1 (verified: grep -c '            system_prompt_override=data.get("system_prompt_override"),' .../telegram/models.py)
# AFTER — insert below that line (models.py:270)
            tenant=data.get("tenant"),
# FILL IN: add `tenant:` to the class docstring Attributes — bounded by Google docstrings
```

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (MODIFY)
```python
# (1) signature at wrapper.py:1266-1270 — add the trailing keyword:
        tenant_id: Optional[str] = None,
#     occurrences: 1 (verified: grep -c '            tenant_id="default",' .../telegram/wrapper.py) — REPLACE wrapper.py:1303 with:
            tenant_id=tenant_id or "default",
#     caller wrapper.py:1489 → self._build_permission_context(session, chat_id=chat_id, bot_id=self._bot_id, tenant_id=self.config.tenant)

# (2) _build_user_context (wrapper.py:1331) — after the jira_cloud_id block (≈1347-1348):
        if self.config.tenant:
            metadata["tenant"] = self.config.tenant

# (3) both agent.ask(...) calls — anchors (distinct indentation, 1 occurrence each):
#     `                            permission_context=permission_context,` (wrapper.py:1520) and
#     `                permission_context=permission_context,` (wrapper.py:1546) — add on the next line:
#                            tenant=self.config.tenant,
#                tenant=self.config.tenant,

# (4) _list_agent_skills (wrapper.py:1954) and _resolve_skill_definition (wrapper.py:1999) — replace the registry lookup:
        view_fn = getattr(self.agent, "current_skill_view", None)
        file_registry = view_fn(self.config.tenant) if callable(view_fn) else None
        if file_registry is None:
            file_registry = getattr(self.agent, "_skill_file_registry", None)
# FILL IN: keep the rest of each method unchanged; a ValueError from current_skill_view (invalid tenant)
#          must be caught and logged, falling back to an empty listing / None — bounded by AC-C3, AC-R2

# (5) occurrences: 1 (verified: grep -c '                    self.agent._active_skill = skill_def' .../telegram/wrapper.py)
#     REPLACE wrapper.py:2083-2087 with:
                    set_active_skill(skill_def)
                    response = await self.agent.ask(
                        question,
                        output_mode=OutputMode.TELEGRAM,
                        tenant=self.config.tenant,
                    )
#     import near the other parrot imports at the top of wrapper.py:
from parrot.skills.tenancy import set_active_skill
```
**Why**: `set_active_skill` is a ContextVar set in the handler's task; `ask()` runs in the same task, so `create_system_prompt` (TASK-4501) sees it, and concurrent users cannot see each other's skill.

### `packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py` (CREATE)
```python
"""FEAT-707 — Telegram tenant binding (TASK-4500)."""
import pytest

from parrot.integrations.telegram.models import TelegramAgentConfig

# FILL IN tests:
#  test_telegram_config_tenant_from_yaml / _default_none                       (no aiogram needed)
#  test_permission_context_tenant (default "default" when unset)               (importorskip aiogram)
#  test_user_context_metadata_tenant
#  test_invoke_passes_tenant (both singleton and per-user branches; fake agent records kwargs)
#  test_skill_command_uses_contextvar (agent.__dict__ never gets `_active_skill`; tenant passed)
#  test_list_skills_uses_view / falls back to _skill_file_registry when agent lacks current_skill_view
#  test_wrapper_never_sets_agent_tenant (AC-T3)
# — bounded by AC-T1, AC-T2, AC-T3, AC-C3, AC-A3
```

### FILL IN checklist
- [ ] docstring for `tenant`
- [ ] ValueError handling in listing/resolution
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-T1, AC-T2, AC-T3 satisfied and tested.
- [ ] `/skill` uses `set_active_skill`; listing/resolution use the tenant view when available.
- [ ] Bots without `tenant:` behave as today (`tenant=None`, `tenant_id="default"`).
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §3 Module 10, §9 S3/S5.
3. **Check dependencies**: TASK-4494 `done`.
4. **Verify the Codebase Contract** — wrapper line numbers drift; re-grep every anchor.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4500 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (seat gpt-5.6-terra, codex, 1 attempt, 233s)
**Date**: 2026-10-19
**Notes**: Merged via coder_merge; merge-tier validation green (107 passed). Closed with close_task.sh.
