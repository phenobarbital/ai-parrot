---
type: Wiki Overview
title: 'TASK-1045: setup_pbac datasets directory extension'
id: doc:sdd-tasks-completed-task-1045-setup-pbac-datasets-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: loading block (lines 131–149), add an identical block for `policies/datasets/`.
---

# TASK-1045: setup_pbac datasets directory extension

**Feature**: FEAT-151 — PBAC-Driven DatasetManager Policy Enforcement
**Spec**: `sdd/specs/pbac-datasetmanager-policy.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 2 of the FEAT-151 spec: extending `setup_pbac()` in
> `parrot/auth/pbac.py` to also load YAML policies from `policies/datasets/*.yml`
> alongside the existing `policies/agents/*.yml` glob.
>
> The pattern is identical to the existing `policies/agents/` block (lines 131–149
> in `pbac.py`): check if the subdirectory exists, load policies from it with
> `PolicyLoader.load_from_directory`, merge them into the policy list, and
> warn-and-continue on failure.
>
> This task is independent of TASK-1044 (DatasetPolicyGuard) and can run in parallel.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/auth/pbac.py`: after the existing `policies/agents/`
  loading block (lines 131–149), add an identical block for `policies/datasets/`.
- The new block must:
  1. Compute `datasets_subdir = policy_path / "datasets"`.
  2. Check `datasets_subdir.exists() and datasets_subdir.is_dir()`.
  3. Call `PolicyLoader.load_from_directory(datasets_subdir)`.
  4. Merge the loaded policies into the `policies` list.
  5. Log `"PBAC: loaded %d per-dataset policies from '%s'"` on success.
  6. On exception: log a WARNING and continue without per-dataset policies.
- Write unit tests in `packages/ai-parrot/tests/auth/test_setup_pbac_datasets.py`.

**NOT in scope**: creating `DatasetPolicyGuard` (TASK-1044), modifying `DatasetManager` (TASK-1046), creating sample YAML files (TASK-1047).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/pbac.py` | MODIFY | Add `policies/datasets/` loading block after the existing `policies/agents/` block |
| `packages/ai-parrot/tests/auth/test_setup_pbac_datasets.py` | CREATE | Unit tests for the new datasets loading |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
# Already imported in pbac.py — no new imports needed:
from pathlib import Path
import logging

# Already lazy-imported inside setup_pbac:
from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader  # pbac.py:86
from navigator_auth.abac.storages.yaml_storage import YAMLStorage                # pbac.py:88
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/pbac.py:35
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]":
    ...

# The EXACT block to mirror (packages/ai-parrot/src/parrot/auth/pbac.py:131-149):
#
#   # Load per-agent YAML policies from policies/agents/ subdirectory (if present)
#   agents_subdir = policy_path / "agents"
#   if agents_subdir.exists() and agents_subdir.is_dir():
#       try:
#           agent_policies = PolicyLoader.load_from_directory(agents_subdir)
#           if agent_policies:
#               policies = list(policies) + list(agent_policies)
#               logger.info(
#                   "PBAC: loaded %d per-agent policies from '%s'",
#                   len(agent_policies),
#                   str(agents_subdir),
#               )
#       except Exception as exc:  # pylint: disable=broad-except
#           logger.warning(
#               "PBAC: error loading per-agent policies from '%s': %s. "
#               "Continuing without per-agent policies.",
#               str(agents_subdir),
#               exc,
#           )

# The new datasets block goes AFTER the agents block and BEFORE the
# evaluator.load_policies(policies) call at line 152.
```

### Does NOT Exist

- ~~`policies/datasets/`~~ — the directory does NOT exist on disk yet. `setup_pbac` must handle the missing directory gracefully (the `if .exists()` check does this).
- ~~`setup_pbac` returning a `DatasetPolicyGuard`~~ — out of scope for v1. The return signature stays unchanged: `(PDP, PolicyEvaluator, Guardian)`.
- ~~`PolicyLoader.load_datasets`~~ — there is no dataset-specific loader. Use the same `PolicyLoader.load_from_directory` that agents use.

---

## Implementation Notes

### Pattern to Follow

```python
# Insert this block after the agents_subdir block (line 149) and before
# evaluator.load_policies(policies) (line 152):

    # Load per-dataset YAML policies from policies/datasets/ subdirectory (if present)
    datasets_subdir = policy_path / "datasets"
    if datasets_subdir.exists() and datasets_subdir.is_dir():
        try:
            dataset_policies = PolicyLoader.load_from_directory(datasets_subdir)
            if dataset_policies:
                policies = list(policies) + list(dataset_policies)
                logger.info(
                    "PBAC: loaded %d per-dataset policies from '%s'",
                    len(dataset_policies),
                    str(datasets_subdir),
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "PBAC: error loading per-dataset policies from '%s': %s. "
                "Continuing without per-dataset policies.",
                str(datasets_subdir),
                exc,
            )
```

### Key Constraints

- Do NOT change the `setup_pbac` return type or signature.
- The new block MUST go before `evaluator.load_policies(policies)` (line 152) so dataset policies are included in the single `load_policies` call.
- Preserve the existing `agents/` block unchanged.
- Warn-and-continue on any exception (same pattern as agents).
- Log message must distinguish "per-dataset" from "per-agent" for operator clarity.

### References in Codebase

- `packages/ai-parrot/src/parrot/auth/pbac.py:131-149` — agents block to mirror verbatim.
- `packages/ai-parrot/src/parrot/auth/pbac.py:152` — `evaluator.load_policies(policies)` call where all policies converge.

---

## Acceptance Criteria

- [ ] `setup_pbac()` loads `policies/datasets/*.yml` into the same `PolicyEvaluator` as `policies/` and `policies/agents/`.
- [ ] When `policies/datasets/` does not exist, existing behaviour is unchanged (no error, no warning).
- [ ] When `policies/datasets/` contains valid YAML, an INFO log says how many per-dataset policies were loaded.
- [ ] When `policies/datasets/` contains malformed YAML, a WARNING is logged and execution continues. The rest of the policies (top-level + agents) still load.
- [ ] The `setup_pbac` return signature is unchanged: `(PDP, PolicyEvaluator, Guardian)`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/auth/test_setup_pbac_datasets.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/auth/pbac.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_setup_pbac_datasets.py
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


class TestSetupPbacDatasetsExtension:
    def test_loads_datasets_subdir(self, tmp_path):
        """Creates a temp policies/datasets/x.yml; verifies setup_pbac logs N policies loaded."""
        ...

    def test_continues_when_datasets_subdir_missing(self, tmp_path):
        """Existing behaviour preserved when policies/datasets/ does not exist."""
        ...

    def test_warn_on_datasets_yaml_parse_error(self, tmp_path):
        """Malformed YAML in policies/datasets/ logs WARNING but doesn't abort."""
        ...

    def test_agents_and_datasets_both_load(self, tmp_path):
        """Both agents/ and datasets/ subdirs exist; all policies merged."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pbac-datasetmanager-policy.spec.md` for full context
2. **Check dependencies** — this task has no dependencies; start immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `packages/ai-parrot/src/parrot/auth/pbac.py` and confirm lines 131–149 still match the pattern shown above
   - Confirm `PolicyLoader.load_from_directory` is the method used at line 135
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/pbac-datasetmanager-policy.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1045-setup-pbac-datasets-extension.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Code)
**Date**: 2026-05-07
**Notes**: Added datasets subdir loading block in `setup_pbac()` at `parrot/auth/pbac.py`
immediately after the existing agents block, before `evaluator.load_policies(policies)`.
The block mirrors the agents block exactly: exists-check, PolicyLoader.load_from_directory,
merge into policies list, INFO log on success, WARNING-and-continue on any exception.
Written 4 unit tests covering: loads datasets subdir, continues when missing, warns on
parse error, and merges both agents+datasets. All tests pass.

**Deviations from spec**: none
