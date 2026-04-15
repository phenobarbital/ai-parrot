# TASK-620: Fix base_executor Cross-Package Imports (docker, pulumi)

**Feature**: refactor-tools-imports
**Spec**: `sdd/specs/refactor-tools-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `docker` and `pulumi` toolkits import `BaseExecutor` and `BaseExecutorConfig` from
`parrot.tools.security.base_executor`, but the `security` module only exists in
`parrot_tools`, not in `parrot.tools`. This causes `ImportError` when these toolkits are loaded.

Implements Spec Module 2.

---

## Scope

- Fix `docker/config.py:12` — `from parrot.tools.security.base_executor import BaseExecutorConfig` → `from parrot_tools.security.base_executor import BaseExecutorConfig`
- Fix `docker/executor.py:15` — `from parrot.tools.security.base_executor import BaseExecutor` → `from parrot_tools.security.base_executor import BaseExecutor`
- Fix `pulumi/config.py:13` — `from parrot.tools.security.base_executor import BaseExecutorConfig` → `from parrot_tools.security.base_executor import BaseExecutorConfig`
- Fix `pulumi/executor.py:13` — `from parrot.tools.security.base_executor import BaseExecutor` → `from parrot_tools.security.base_executor import BaseExecutor`

**NOT in scope**: scraping/pricestool fixes (TASK-619), docstrings (TASK-621), security `__init__.py` docstrings (TASK-621).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/docker/config.py` | MODIFY | Fix line 12 import |
| `packages/ai-parrot-tools/src/parrot_tools/docker/executor.py` | MODIFY | Fix line 15 import |
| `packages/ai-parrot-tools/src/parrot_tools/pulumi/config.py` | MODIFY | Fix line 13 import |
| `packages/ai-parrot-tools/src/parrot_tools/pulumi/executor.py` | MODIFY | Fix line 13 import |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# The correct import path for base_executor classes:
from parrot_tools.security.base_executor import BaseExecutor        # packages/ai-parrot-tools/src/parrot_tools/security/base_executor.py
from parrot_tools.security.base_executor import BaseExecutorConfig  # packages/ai-parrot-tools/src/parrot_tools/security/base_executor.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/security/base_executor.py
class BaseExecutor:         # Base class for security tool executors
class BaseExecutorConfig:   # Configuration for executors
```

### Does NOT Exist

- ~~`parrot.tools.security`~~ — does NOT exist in ai-parrot core
- ~~`parrot.tools.security.base_executor`~~ — does NOT exist in ai-parrot core
- ~~`parrot.tools.docker`~~ — does NOT exist in ai-parrot core
- ~~`parrot.tools.pulumi`~~ — does NOT exist in ai-parrot core

---

## Implementation Notes

### Pattern to Follow

```python
# BEFORE (broken):
from parrot.tools.security.base_executor import BaseExecutor

# AFTER (fixed):
from parrot_tools.security.base_executor import BaseExecutor
```

### Key Constraints
- Only change the 4 import lines listed in Scope
- Do NOT modify any logic, class definitions, or other imports

---

## Acceptance Criteria

- [ ] `from parrot_tools.docker.config import DockerConfig` works without ImportError
- [ ] `from parrot_tools.docker.executor import DockerExecutor` works without ImportError
- [ ] `from parrot_tools.pulumi.config import PulumiConfig` works without ImportError
- [ ] `from parrot_tools.pulumi.executor import PulumiExecutor` works without ImportError
- [ ] No `from parrot.tools.security.base_executor` remains in docker/ or pulumi/

---

## Test Specification

```python
# Manual verification
import importlib

for mod in ["parrot_tools.docker.config", "parrot_tools.docker.executor",
            "parrot_tools.pulumi.config", "parrot_tools.pulumi.executor"]:
    try:
        importlib.import_module(mod)
        print(f"OK: {mod}")
    except ImportError as e:
        print(f"FAIL: {mod} — {e}")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-620-fix-base-executor-imports.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
