# TASK-535: PBAC Setup & Initialization

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-534
**Assigned-to**: unassigned

---

## Context

> Creates the `setup_pbac()` function that initializes the full PBAC stack during app
> startup. This is the foundation all other ai-parrot integration tasks depend on.
>
> Implements Spec Module 2.

---

## Scope

- Create `parrot/auth/pbac.py` with `setup_pbac()` async function
- `setup_pbac()` must:
  1. Create `YAMLStorage(directory=policy_dir)` to load YAML policy files
  2. Create `PolicyEvaluator(default_effect=PolicyEffect.DENY, cache_ttl_seconds=30)`
  3. Load policies via `PolicyLoader.load_from_directory(policy_dir)`
  4. Create `PDP(storage=yaml_storage)`, attach evaluator
  5. Call `PDP.setup(app)` to register Guardian as `app['security']`, middleware, and
     `/api/v1/abac/check` endpoint
  6. Return `(pdp, evaluator, guardian)` tuple for downstream use
- Handle edge cases: missing policy dir, empty dir, malformed YAML
- Make policy directory path configurable (from app config or parameter)
- Log startup info: number of policies loaded, policy dir, cache TTL

**NOT in scope**:
- PBACPermissionResolver (TASK-536)
- App.py integration (TASK-541)
- Handler modifications (TASK-537+)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/pbac.py` | CREATE | `setup_pbac()` function |
| `parrot/auth/__init__.py` | MODIFY | Export `setup_pbac` |
| `tests/auth/test_pbac_setup.py` | CREATE | Tests for setup function |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/auth/pbac.py
import logging
from pathlib import Path
from typing import Optional
from aiohttp import web

from navigator_auth.abac.pdp import PDP
from navigator_auth.abac.guardian import Guardian
from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader
from navigator_auth.abac.policies.abstract import PolicyEffect
from navigator_auth.abac.storages.yaml_storage import YAMLStorage


async def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: PolicyEffect = PolicyEffect.DENY,
) -> tuple[PDP, PolicyEvaluator, Guardian]:
    """Initialize PBAC engine and register with the aiohttp app."""
    logger = logging.getLogger("parrot.auth.pbac")
    policy_path = Path(policy_dir)

    if not policy_path.exists() or not policy_path.is_dir():
        logger.warning(
            "PBAC policy directory %s not found. PBAC disabled.", policy_dir
        )
        return None, None, None

    # Load policies
    yaml_storage = YAMLStorage(directory=str(policy_path))
    evaluator = PolicyEvaluator(
        default_effect=default_effect,
        cache_ttl_seconds=cache_ttl,
    )
    policies = PolicyLoader.load_from_directory(policy_path)
    evaluator.load_policies(policies)

    logger.info(
        "PBAC initialized: %d policies loaded from %s (cache TTL: %ds)",
        len(policies), policy_dir, cache_ttl,
    )

    # Create PDP and register
    pdp = PDP(storage=yaml_storage)
    pdp._evaluator = evaluator
    pdp.setup(app)

    guardian = app.get('security')
    return pdp, evaluator, guardian
```

### Key Constraints
- Must be async (PDP.setup may involve async operations)
- Graceful degradation: no policies = no PBAC (not an error)
- Logger, not print statements
- Path must be configurable, not hardcoded

### References in Codebase
- `navigator_auth/abac/pdp.py` — PDP class and `setup()` method
- `navigator_auth/abac/policies/evaluator.py` — PolicyEvaluator, PolicyLoader
- `navigator_auth/abac/storages/yaml_storage.py` — YAMLStorage
- `app.py` — Main application setup pattern

---

## Acceptance Criteria

- [ ] `setup_pbac()` loads YAML policies and initializes PDP + PolicyEvaluator + Guardian
- [ ] `PDP.setup(app)` registers Guardian as `app['security']`
- [ ] `PDP.setup(app)` registers `/api/v1/abac/check` endpoint
- [ ] Missing policy directory → logs warning, returns None tuple, app continues
- [ ] Empty policy directory → logs info, PBAC active with zero policies (deny-by-default)
- [ ] `PolicyEvaluator` uses `cache_ttl_seconds=30` for short TTL
- [ ] Tests pass: `pytest tests/auth/test_pbac_setup.py -v`
- [ ] Import works: `from parrot.auth.pbac import setup_pbac`

---

## Test Specification

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from parrot.auth.pbac import setup_pbac


@pytest.fixture
def sample_policies_dir(tmp_path):
    import yaml
    policy = {
        "version": "1.0",
        "defaults": {"effect": "deny"},
        "policies": [{
            "name": "test_policy",
            "effect": "allow",
            "resources": ["tool:*"],
            "actions": ["tool:execute"],
            "subjects": {"groups": ["*"]},
            "priority": 10,
        }],
    }
    (tmp_path / "test.yaml").write_text(yaml.dump(policy))
    return tmp_path


class TestSetupPbac:
    async def test_setup_with_policies(self, sample_policies_dir):
        """setup_pbac loads policies and returns PDP, evaluator, guardian."""
        app = web.Application()
        pdp, evaluator, guardian = await setup_pbac(
            app, policy_dir=str(sample_policies_dir)
        )
        assert pdp is not None
        assert evaluator is not None
        assert 'security' in app

    async def test_setup_missing_dir(self, tmp_path):
        """Missing policy dir returns None tuple."""
        app = web.Application()
        pdp, evaluator, guardian = await setup_pbac(
            app, policy_dir=str(tmp_path / "nonexistent")
        )
        assert pdp is None

    async def test_setup_empty_dir(self, tmp_path):
        """Empty policy dir initializes with zero policies."""
        app = web.Application()
        pdp, evaluator, guardian = await setup_pbac(
            app, policy_dir=str(tmp_path)
        )
        assert pdp is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-535-pbac-setup.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Created parrot/auth/pbac.py with setup_pbac() async function.
Updated parrot/auth/__init__.py to export setup_pbac.
Created tests/auth/test_pbac_setup.py with unit tests.

**Deviations from spec**: none
