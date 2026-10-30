# TASK-4917: Expert policy — tier→ModelConfig, mandatory toolkits, allowlist, deny rule

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4914, TASK-4916
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10, goal G7, §8 Q3. Pure functions the registry (TASK-4926) calls when it builds an `ExpertAgent`:
project `tier` to a `ModelConfig`, add the mandatory wiki + bookstore toolkits, compute the tool allowlist that
never contains `spawn_sub_agent`, and produce the per-expert PBAC deny rule (which needs the `resource` field
added by TASK-4916).

---

## Scope

- Implement `DEFAULT_TIER_POLICY`, `model_config_for`, `MANDATORY_TOOLKITS`, `effective_toolkits`,
  `effective_allowlist`, `SPAWN_DENY_PRIORITY`, `expert_policy_rules` in `parrot/experts/policy.py`.
- Write `test_policy.py`.

**NOT in scope**: instantiating toolkits (that is TASK-4926's factory), registering the rule (TASK-4926).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/policy.py` | CREATE | Tier policy, toolkits, allowlist, deny rule |
| `packages/ai-parrot/tests/experts/test_policy.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import ModelConfig       # verified: parrot/models/basic.py (class ModelConfig: provider, model, temperature=0.1, max_tokens=8192)
from parrot.auth.models import PolicyRuleConfig   # verified: parrot/auth/models.py:32 — `resource` added by TASK-4916
from parrot.experts.models import ExpertManifest, ExpertTier, ExpertPolicyError, SPAWN_TOOL_NAME   # TASK-4914
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/basic.py
class ModelConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.1
    max_tokens: int = 8192
# PBAC TOOL_CALL check that the deny rule must match (do not modify):
#   parrot/bots/guardrails/builtin/pbac.py:274-279 — check_access(resource_type=TOOL, resource_name=tool_name, action="tool:execute")
#   parrot/auth/resolver.py:322-327 — same action string
```

### Does NOT Exist
- ~~`parrot.conf.EXPERT_TIER_POLICY`~~ — no conf key exists; overrides come only through the `overrides` argument.
- ~~a deny-list on `SpawnSubAgentTool`~~ — non-delegation is allowlist + PBAC deny; `tools/spawn.py` is not modified (§8 Q3).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/policy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_policy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ModelConfig",
    "sym:packages/ai-parrot/src/parrot/auth/models.py#PolicyRuleConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `SPAWN_DENY_PRIORITY = 100` is deliberately above operator YAML (`>= 20`): the non-delegation invariant must
  survive an operator `tool:*` allow (spec §7 Known Risks). Never lower it.
- `effective_allowlist` must never return an empty list when tools were discovered — `SpawnSubAgentTool`
  treats an empty allowlist as "allow everything" (spec §7, `tools/spawn.py:164`).

---

## Implementation Blueprint

### Steps (in order)
1. Write the constants and `model_config_for` — *why*: the manifest never names a model (Non-Goals).
2. Write `effective_toolkits` / `effective_allowlist` — *why*: AC10.
3. Write `expert_policy_rules` and validate its output through `PolicyRuleConfig(**rule)` in the test — *why*:
   the registry hands it to `parse_bot_permissions`, which builds exactly that.

### `packages/ai-parrot/src/parrot/experts/policy.py` (CREATE)
```python
"""Expert policy: tier→ModelConfig, mandatory toolkits, tool allowlist, non-delegation PBAC rule (FEAT-778 M10)."""
from __future__ import annotations

from typing import Any, Final, Mapping, Sequence

from parrot.experts.models import SPAWN_TOOL_NAME, ExpertManifest, ExpertPolicyError, ExpertTier
from parrot.models.basic import ModelConfig

DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]] = {
    # FILL IN: provider/model/temperature per tier — judgment = strongest reasoning model, templated = cheapest;
    # use provider ids and model names the repo's clients already accept (see parrot/clients/*) — bounded by Non-Goals
    ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-2.5-pro", "temperature": 0.2},
    ExpertTier.BALANCED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.1},
    ExpertTier.TEMPLATED: {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.0},
}
MANDATORY_TOOLKITS: Final[tuple[str, ...]] = ("LLMWikiToolkit", "BookstoreToolkit")
SPAWN_DENY_PRIORITY: Final[int] = 100


def model_config_for(tier: ExpertTier, *, overrides: Mapping[str, Any] | None = None) -> ModelConfig:
    """ModelConfig for a tier; `overrides` keys replace the defaults (provider/model/temperature/max_tokens)."""
    return ModelConfig(**{**DEFAULT_TIER_POLICY[tier], **dict(overrides or {})})


def effective_toolkits(manifest: ExpertManifest) -> list[str]:
    """manifest.toolkits followed by the missing MANDATORY_TOOLKITS, deduped, order kept."""
    # FILL IN: dedupe preserving first occurrence — bounded by AC10
    return list(manifest.toolkits)


def effective_allowlist(manifest: ExpertManifest, discovered: Sequence[str]) -> list[str]:
    """discovered ∩ (tools_allow or all) minus SPAWN_TOOL_NAME; ExpertPolicyError if the spawn tool survives."""
    allowed = [name for name in discovered if not manifest.tools_allow or name in manifest.tools_allow]
    allowed = [name for name in allowed if name != SPAWN_TOOL_NAME]
    if SPAWN_TOOL_NAME in allowed:  # defense in depth over the manifest validator
        raise ExpertPolicyError(f"expert {manifest.name}: {SPAWN_TOOL_NAME} must never be allowed")
    # FILL IN: raise ExpertPolicyError when discovered is non-empty but allowed is empty (empty = allow-all) — §7
    return allowed


def expert_policy_rules(manifest: ExpertManifest) -> list[dict[str, Any]]:
    """The one non-delegation rule every expert registers (§8 Q3); shape accepted by parse_bot_permissions."""
    return [{
        "action": "tool:execute",
        "effect": "deny",
        "resource": f"tool:{SPAWN_TOOL_NAME}",
        "priority": SPAWN_DENY_PRIORITY,
        "description": f"expert {manifest.name}: no delegation (FEAT-778)",
    }]
```
**Why this shape**: the rule dict is exactly what `PolicyRuleConfig(**rule)` accepts once TASK-4916 lands; `action`
`tool:execute` is the string the PBAC TOOL_CALL check evaluates.

### FILL IN checklist
- [ ] `DEFAULT_TIER_POLICY` — confirm the three model ids exist in the clients; adjust if not.
- [ ] `effective_toolkits` — dedupe; AC10.
- [ ] `effective_allowlist` — empty-result guard; spec §7.

---

## Acceptance Criteria

- [ ] AC10 (policy part) — `effective_toolkits()` always contains `LLMWikiToolkit` and `BookstoreToolkit`;
      `effective_allowlist()` never contains `spawn_sub_agent`.
- [ ] `expert_policy_rules()` returns exactly one rule; `PolicyRuleConfig(**rule).to_resource_policy("x")` has
      `resources == ["tool:spawn_sub_agent"]`, `effect == "deny"`, `priority == 100`.
- [ ] `model_config_for` honours `overrides`.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_policy.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_policy.py
def test_effective_toolkits_add_mandatory(): ...            # FILL IN
def test_effective_toolkits_dedupes(): ...                  # FILL IN
def test_effective_allowlist_never_contains_spawn(): ...    # FILL IN
def test_effective_allowlist_rejects_empty_result(): ...    # FILL IN
def test_expert_policy_rules_deny_spawn(): ...              # FILL IN: round-trip through PolicyRuleConfig
def test_model_config_for_overrides(): ...                  # FILL IN
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4917 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: gpt-5.6-sol (codex) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier gate and chunk merge-tier validation green (80 + 5 passed).

**Deviations from spec**: none
