# TASK-786: Store Router YAML Override Loader

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-785
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-111. Agents configure the store router per-agent via YAML; this loader merges hardcoded defaults with user overrides, following the precedent set by `IntentRouterConfig.custom_keywords`.

---

## Scope

- Create `parrot/registry/routing/yaml_loader.py`.
- Implement `load_store_router_config(path_or_dict)`:
  - Accepts either a filesystem path (`str` / `pathlib.Path`) or a pre-parsed `dict`.
  - Produces a `StoreRouterConfig` where scalar fields from the YAML override the model defaults, and `custom_rules` from YAML append to (not replace) any defaults.
  - On missing file: log WARNING and return `StoreRouterConfig()` (defaults).
  - On malformed YAML (`yaml.YAMLError`): log ERROR and return `StoreRouterConfig()` (defaults). Must NOT raise.
  - On Pydantic `ValidationError`: log ERROR and return `StoreRouterConfig()` (defaults). Must NOT raise.
- Write unit tests under `tests/unit/registry/routing/test_yaml_loader.py`.

**NOT in scope**: YAML schema for rules engine execution, actual rule evaluation, bot integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/yaml_loader.py` | CREATE | YAML override loader |
| `packages/ai-parrot/src/parrot/registry/routing/__init__.py` | MODIFY | Re-export `load_store_router_config` |
| `packages/ai-parrot/tests/unit/registry/routing/test_yaml_loader.py` | CREATE | Unit tests including malformed-YAML fallback |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import yaml  # project-wide dependency
import logging
from pathlib import Path
from pydantic import ValidationError
from parrot.registry.routing import StoreRouterConfig, StoreRule  # introduced by TASK-785
from parrot.tools.multistoresearch import StoreType  # verified: packages/ai-parrot/src/parrot/tools/multistoresearch.py:30
```

### Existing Signatures to Use
```python
# parrot/registry/capabilities/models.py:178  — override precedent
class IntentRouterConfig(BaseModel):
    custom_keywords: dict[str, str]  # keys lowercased, values RoutingType string
```

### Does NOT Exist
- ~~`parrot.registry.routing.load_store_router_config`~~ — this task creates it.
- ~~A global YAML schema validator~~ — the loader's job ends with `StoreRouterConfig.model_validate(...)`.

---

## Implementation Notes

### Key Constraints
- Use `yaml.safe_load`, never `yaml.load` (security).
- Pydantic `ValidationError` must be caught and logged — do NOT propagate. Starting up a bot should not fail just because an override is malformed.
- Log levels: WARNING for "file not found"; ERROR for parse / validation failures.
- YAML structure:
  ```yaml
  margin_threshold: 0.20
  fallback_policy: "fan_out"
  custom_rules:
    - pattern: "graph"
      store: "arango"
      weight: 0.9
    - pattern: ".*supplier.*"
      store: "arango"
      regex: true
  ```

### References in Codebase
- `packages/ai-parrot/src/parrot/registry/capabilities/models.py:178` — `custom_keywords` precedent.

---

## Acceptance Criteria

- [ ] `from parrot.registry.routing import load_store_router_config` works.
- [ ] Valid YAML file → correct `StoreRouterConfig` with overridden scalars and appended custom rules.
- [ ] Non-existent path → WARNING log + defaults returned (no raise).
- [ ] Malformed YAML → ERROR log + defaults returned (no raise).
- [ ] Invalid field types in YAML → ERROR log + defaults returned (no raise).
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/registry/routing/test_yaml_loader.py -v`.

---

## Test Specification

```python
import pytest
from pathlib import Path
from parrot.registry.routing import (
    StoreRouterConfig, StoreFallbackPolicy, load_store_router_config,
)
from parrot.tools.multistoresearch import StoreType


def test_loads_valid_yaml(tmp_path):
    p = tmp_path / "router.yaml"
    p.write_text(
        "margin_threshold: 0.25\n"
        "fallback_policy: fan_out\n"
        "custom_rules:\n"
        "  - pattern: graph\n"
        "    store: arango\n"
    )
    cfg = load_store_router_config(p)
    assert cfg.margin_threshold == 0.25
    assert cfg.fallback_policy == StoreFallbackPolicy.FAN_OUT
    assert cfg.custom_rules[0].store == StoreType.ARANGO


def test_missing_file_returns_defaults(caplog):
    cfg = load_store_router_config("/does/not/exist.yaml")
    assert isinstance(cfg, StoreRouterConfig)
    assert cfg.margin_threshold == 0.15


def test_malformed_yaml_returns_defaults(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("::: not: valid: yaml :::")
    cfg = load_store_router_config(p)
    assert cfg.margin_threshold == 0.15   # defaults


def test_invalid_schema_returns_defaults(tmp_path):
    p = tmp_path / "bad_schema.yaml"
    p.write_text("margin_threshold: not_a_float\n")
    cfg = load_store_router_config(p)
    assert cfg.margin_threshold == 0.15


def test_dict_input():
    cfg = load_store_router_config({"top_n": 3})
    assert cfg.top_n == 3
```

---

## Agent Instructions

1. Read the spec (§2 Data Models, §6 Codebase Contract, §7 Patterns to Follow).
2. Verify the Codebase Contract: confirm TASK-785 artifacts exist on this branch.
3. Implement `load_store_router_config` with the tolerance guarantees above.
4. Re-export the function from `parrot/registry/routing/__init__.py`.
5. Run the test suite.
6. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
