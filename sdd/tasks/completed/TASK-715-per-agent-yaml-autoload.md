# TASK-715: Per-Agent YAML Auto-Loading in setup_pbac()

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Extends `setup_pbac()` to recursively load YAML policies from subdirectories
> (specifically `policies/agents/`). Currently it only loads from the top-level
> `policies/` directory. Implements Spec Module 9.

---

## Scope

- Modify `setup_pbac()` in `parrot/auth/pbac.py` to also scan `policies/agents/`
  subdirectory for `.yaml` files.
- Use `PolicyLoader.load_from_directory()` for the subdirectory (same as top-level).
- Merge subdirectory policies with top-level policies before loading into evaluator.
- Create the `policies/agents/` directory with a `.gitkeep` file.
- Write unit test.

**NOT in scope**: AgentRegistry, BotConfig, AbstractBot.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/pbac.py` | MODIFY | Add recursive subdirectory loading |
| `policies/agents/.gitkeep` | CREATE | Empty dir placeholder |
| `tests/auth/test_pbac_agent_yaml.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/auth/pbac.py:85-88
from navigator_auth.abac.pdp import PDP
from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader
from navigator_auth.abac.policies.abstract import PolicyEffect
from navigator_auth.abac.storages.yaml_storage import YAMLStorage
```

### Existing Signatures to Use
```python
# parrot/auth/pbac.py:35-40
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]": ...

# parrot/auth/pbac.py:96-104 — policy_path validation
policy_path = Path(policy_dir)
if not policy_path.exists() or not policy_path.is_dir():
    # ... returns None tuple

# parrot/auth/pbac.py:111-113 — evaluator creation
evaluator = PolicyEvaluator(
    default_effect=default_effect,
    cache_ttl_seconds=cache_ttl,
)

# PolicyLoader.load_from_directory(path) → list of policy objects
```

### Does NOT Exist
- ~~`policies/agents/`~~ — directory does not exist yet, must be created
- ~~`setup_pbac(recursive=True)`~~ — no recursive parameter, must add logic manually

---

## Implementation Notes

### Key Constraints
- Only scan `policies/agents/` if it exists — don't fail if missing.
- Log the count of per-agent policies loaded.
- Per-agent YAML files use the same format as `policies/agents.yaml`.

---

## Acceptance Criteria

- [ ] `setup_pbac()` loads policies from `policies/agents/*.yaml` when dir exists
- [ ] Works correctly when `policies/agents/` does not exist
- [ ] `policies/agents/.gitkeep` created
- [ ] Tests pass: `pytest tests/auth/test_pbac_agent_yaml.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/auth/pbac.py` lines 85-168 to see current loading logic
2. **Implement** subdirectory scanning after top-level load
3. **Create** `policies/agents/.gitkeep`
4. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
