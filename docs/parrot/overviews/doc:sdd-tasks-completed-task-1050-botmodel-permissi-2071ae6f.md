---
type: Wiki Overview
title: 'TASK-1050: BotModel.permissions schema documentation'
id: doc:sdd-tasks-completed-task-1050-botmodel-permissions-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 2 of the spec. The `permissions` JSONB column on
relates_to:
- concept: mod:parrot.auth.agent_guard
  rel: mentions
- concept: mod:parrot.auth.models
  rel: mentions
- concept: mod:parrot.handlers.models
  rel: mentions
---

# TASK-1050: BotModel.permissions schema documentation

**Feature**: FEAT-153 — botmanager-pbac-permissions
**Spec**: `sdd/specs/botmanager-pbac-permissions.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1049
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 2 of the spec. The `permissions` JSONB column on
`navigator.ai_bots` (declared at
`packages/ai-parrot/src/parrot/handlers/models/bots.py:272-276`)
already exists with the right type and default; what is missing is the
contract so consumers (admins, UI, downstream code) know what JSON
shape to write.

This is a documentation-only task — no DDL change, no behavioural code.

---

## Scope

- Update the `ui_help` string of the `permissions` field on `BotModel`
  (`bots.py:272-276`) to describe the accepted shapes:
  - `{}` / null / missing → public (all users allowed).
  - `{"permissions": []}` → public.
  - `{"permissions": [<PolicyRuleConfig dict>, ...]}` → deny-by-default
    with explicit allow/deny rules.
  - Bare `[<rule>, ...]` → accepted as forgiving fallback (parser will
    coerce).
- Reference `parse_bot_permissions` (TASK-1049) by full module path
  (`parrot.auth.agent_guard.parse_bot_permissions`) in the docstring
  so a reader can find the canonical validator.
- Add an example rule inline in the docstring, mirroring the example
  in spec §1 Problem Statement.

**NOT in scope**:
- Any DDL / migration change. The column already is JSONB DEFAULT '{}'.
- Any change to `UserBotModel.permissions` (`users_bots.py:104`).
  That field is out of scope for FEAT-153 entirely.
- The parser implementation (TASK-1049 owns it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/models/bots.py` | MODIFY | Update the `ui_help` of `permissions: dict` field at line 272-276. |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/models/bots.py
class BotModel(Model):                          # line 21
    # ... many fields ...
    permissions: dict = Field(                  # line 272
        required=False,
        default_factory=dict,
        ui_help="The bot’s user and group permissions.",  # line 275 — TO REPLACE
    )
```

### Does NOT Exist

- ~~A separate `policies` column on `BotModel`~~ — does not exist;
  the canonical column is `permissions`.
- ~~`UserBotModel.policy_rules`~~ — does not exist and is out of scope.

---

## Implementation Notes

### Suggested replacement `ui_help`

```
"User/group permissions for this bot. JSONB shape:
 {} or null = public (any authenticated user can resolve).
 {\"permissions\": [<rule>, ...]} = deny-by-default; only matching
 allow rules grant access.
 Each rule is a dict matching parrot.auth.models.PolicyRuleConfig
 (action, effect, groups, roles, priority).
 Example:
   {\"permissions\": [
     {\"action\": \"agent:resolve\", \"effect\": \"allow\",
      \"groups\": [\"engineering\"]}
   ]}
 Validated at load time by
 parrot.auth.agent_guard.parse_bot_permissions; malformed input is
 logged WARNING and that bot is skipped."
```

Keep the `ui_help` value as a single string literal (multi-line via
parenthesised concatenation if needed). Don't break field declaration
syntax.

### Patterns to Follow

- Mirror the existing tone and length of other `ui_help` strings in
  `bots.py` (e.g., `model_config`, `vector_store_config`).
- Do NOT change the field's `required=False` or `default_factory=dict`.

---

## Acceptance Criteria

- [ ] `BotModel.permissions.ui_help` describes the accepted JSON
  shapes, the public-when-empty rule, and points to
  `parrot.auth.agent_guard.parse_bot_permissions`.
- [ ] No DDL or default value changes; `BotModel(...)` still
  instantiates with `permissions = {}` by default.
- [ ] `from parrot.handlers.models import BotModel` still works.
- [ ] `ruff check` passes on the touched file.

---

## Test Specification

No new tests required — this is documentation. Verify the existing
`BotModel` tests (if any) still pass.

```bash
pytest packages/ai-parrot/tests/handlers/ -v -k bot 2>/dev/null || true
```

---

## Agent Instructions

When you pick up this task:

1. Read spec §3 Module 2 and §6 Codebase Contract.
2. Verify TASK-1049 has shipped (the docstring references
   `parrot.auth.agent_guard.parse_bot_permissions` — the symbol must
   exist).
3. Edit `bots.py:272-276` to replace the `ui_help` value.
4. Verify the file still imports cleanly.
5. Move this file to `sdd/tasks/completed/`, update the per-spec
   index, fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker (claude-sonnet-4-6) on 2026-05-07.

Updated `ui_help` on `BotModel.permissions` (bots.py:272) to describe the accepted JSON
shapes, the public-when-empty rule, and to reference `parrot.auth.agent_guard.parse_bot_permissions`.
No DDL change; default_factory=dict unchanged. ruff check introduced no new errors (3
pre-existing F401s on unused imports remain from before this task).
