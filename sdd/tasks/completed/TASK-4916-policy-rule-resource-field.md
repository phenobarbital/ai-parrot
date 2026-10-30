# TASK-4916: `PolicyRuleConfig.resource` — per-resource PBAC rules

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 and §8 Q3. Every expert must carry a PBAC deny rule on `tool:spawn_sub_agent`. Today
`PolicyRuleConfig.to_resource_policy()` hard-codes `resources=[f"agent:{agent_name}"]`
(`parrot/auth/models.py:153`), so a per-tool rule cannot be expressed. This task adds an **optional** `resource`
field. With `resource=None` the produced dict must be byte-identical to today (AC21) — this is shared auth
machinery used by every bot.

---

## Scope

- Add `resource: Optional[str] = Field(default=None, …)` to `PolicyRuleConfig`.
- In `to_resource_policy()`, use `[self.resource]` when set, else the existing `[f"agent:{agent_name}"]`; when
  set, embed the resource in the policy `name` so two rules for one agent never collide.
- Update the class docstring (field list + a note that `resource` targets a non-agent resource).
- Write `test_policy_rule_resource.py` with a pinned pre-change fixture.

**NOT in scope**: the expert deny rule itself (TASK-4917), registering it (TASK-4926), any change to the evaluator,
`agent_guard.py` or `registry.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/models.py` | MODIFY | Optional `resource` field + fallback |
| `packages/ai-parrot/tests/auth/test_policy_rule_resource.py` | CREATE | Pinned-output tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.models import PolicyRuleConfig          # verified: parrot/auth/models.py:32
from parrot.auth.agent_guard import parse_bot_permissions  # verified: parrot/auth/agent_guard.py:73 (test only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/models.py
class PolicyRuleConfig(BaseModel):                                   # line 32
    action: str; effect: Literal["allow", "deny"] = "allow"
    groups: Optional[list[str]] = None; roles: Optional[list[str]] = None
    priority: int = 10; description: Optional[str]
    conditions: Optional[dict[str, Any]] = Field(default=None, description="Reserved for future extensibility (time, IP, attributes, etc.)")  # lines 85-88
    def to_resource_policy(self, agent_name: str) -> dict:          # line 108
        policy = {"name": f"code_rule_{agent_name}_{self.action}", "effect": self.effect,
                  "resources": [f"agent:{agent_name}"],             # line 153
                  "actions": [self.action], "subjects": subjects, "priority": self.priority}
# packages/ai-parrot/src/parrot/auth/agent_guard.py:73
def parse_bot_permissions(value: dict | list | None) -> list[PolicyRuleConfig]   # builds PolicyRuleConfig(**rule_data)
```

### Does NOT Exist
- ~~`PolicyRuleConfig.resource`~~ / ~~`PolicyRuleConfig.resources`~~ — no such field today; this task adds `resource` (singular).
- ~~`PolicyRuleConfig.resource_type`~~ — do not add; the resource id carries its own `tool:` / `agent:` prefix.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_policy_rule_resource.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/models.py#PolicyRuleConfig",
    "sym:packages/ai-parrot/src/parrot/auth/models.py#PolicyRuleConfig.to_resource_policy",
    "sym:packages/ai-parrot/src/parrot/auth/agent_guard.py#parse_bot_permissions"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Additive only. Field order: append `resource` after `conditions` so existing positional/serialised shapes keep
  their order.
- The pinned fixture: build the expected dict for `PolicyRuleConfig(action="agent:chat", groups=["finance"])` by
  hand from the docstring example at `models.py:131-139` — never by calling the modified method.

---

## Implementation Blueprint

### Steps (in order)
1. Add the field — *why*: `parse_bot_permissions` builds `PolicyRuleConfig(**rule_data)`, so a `resource` key in
   a rule dict must validate.
2. Change the two lines in `to_resource_policy` — *why*: this is the only place the resource id is produced.
3. Write the pinned test first, then run `tests/auth/test_policy_rules_integration.py` unchanged (AC21).

### `packages/ai-parrot/src/parrot/auth/models.py` (MODIFY) — field
```python
# occurrences: 1 (verified: grep -c '        description="Reserved for future extensibility (time, IP, attributes, etc.)",' packages/ai-parrot/src/parrot/auth/models.py)
# AFTER — insert below the closing `    )` of the `conditions` Field that follows
#         `        description="Reserved for future extensibility (time, IP, attributes, etc.)",` (verified: models.py:87-88)
    resource: Optional[str] = Field(
        default=None,
        description="Explicit resource id (e.g. 'tool:spawn_sub_agent'); None keeps 'agent:<name>'",
    )
```

### `packages/ai-parrot/src/parrot/auth/models.py` (MODIFY) — policy dict
```python
# occurrences: 1 (verified: grep -c '            "resources": [f"agent:{agent_name}"],' packages/ai-parrot/src/parrot/auth/models.py)
# REPLACE the two lines (verified: models.py:151 and :153)
#     "name": f"code_rule_{agent_name}_{self.action}",
#     "resources": [f"agent:{agent_name}"],
# WITH
            "name": (
                f"code_rule_{agent_name}_{self.action}"
                if self.resource is None
                else f"code_rule_{agent_name}_{self.action}_{self.resource}"
            ),
            "resources": [self.resource] if self.resource is not None else [f"agent:{agent_name}"],
```
**Why**: with `resource=None` both expressions evaluate to the old strings, so every existing rule is unchanged.

### FILL IN checklist
- [ ] Docstring: add `resource` to the Attributes list and one sentence on the `None` fallback.

---

## Acceptance Criteria

- [ ] AC21 — `to_resource_policy()` without `resource` equals the pinned pre-change dict; with
      `resource="tool:spawn_sub_agent"` it yields `resources=["tool:spawn_sub_agent"]`.
- [ ] `parse_bot_permissions([{"action": "tool:execute", "effect": "deny", "resource": "tool:spawn_sub_agent"}])` validates.
- [ ] `tests/auth/test_policy_rules_integration.py` passes unchanged.
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/models.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_policy_rule_resource.py -q`
- `pytest tests/auth/test_policy_rules_integration.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_policy_rule_resource.py
from parrot.auth.models import PolicyRuleConfig

PINNED = {"name": "code_rule_finance_bot_agent:chat", "effect": "allow", "resources": ["agent:finance_bot"],
          "actions": ["agent:chat"], "subjects": {"groups": ["finance"]}, "priority": 10}


def test_policy_rule_without_resource_is_unchanged(): ...   # FILL IN: == PINNED
def test_policy_rule_resource_override(): ...               # FILL IN
def test_policy_rule_resource_names_do_not_collide(): ...   # FILL IN: two rules, same action, different names
def test_parse_bot_permissions_accepts_resource(): ...      # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4916 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (resumed run; coder deliverable merged by engine in a prior run)
**Date**: 2026-10-30
**Notes**: Delivery merged on the feature branch; closed on resume after the combined task tests passed (23 passed: tests/experts, tests/auth/test_policy_rule_resource.py, ai-parrot-tools tests/security/cve). Closed via close_task.sh (no engine evidence refs available on resume).

**Deviations from spec**: none
