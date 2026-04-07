# TASK-621: Fix Docstring and Example Import References

**Feature**: refactor-tools-imports
**Spec**: `sdd/specs/refactor-tools-imports.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Multiple `__init__.py` files and documentation files in `parrot_tools` contain
docstring examples and usage snippets that reference old `parrot.tools.<toolkit>`
paths. While these don't cause runtime errors (they're in docstrings, not executed
code), they mislead developers and will fail if copy-pasted.

Implements Spec Module 3.

---

## Scope

Fix all docstring/example import references in these files:

- `security/__init__.py:8,25-27` — docstring examples referencing `parrot.tools.security`
- `security/checkov/__init__.py:8` — docstring example referencing `parrot.tools.security.checkov`
- `security/trivy/__init__.py:7` — docstring example referencing `parrot.tools.security.trivy`
- `security/prowler/__init__.py:7` — docstring example referencing `parrot.tools.security.prowler`
- `security/reports/__init__.py:7` — docstring example referencing `parrot.tools.security.reports`
- `docker/__init__.py:16,22` — docstring examples referencing `parrot.tools.docker`
- `pulumi/__init__.py:10,16` — docstring examples referencing `parrot.tools.pulumi`
- `ibkr/__init__.py:8` — docstring example referencing `parrot.tools.ibkr`
- `system_health/tool.py:14` — docstring example referencing `parrot.tools.system_health`
- `chart.py:12` — docstring example referencing `parrot.tools.chart`
- `codeinterpreter/__init__.py:14` — docstring example referencing `parrot.tools.code_interpreter`

All references should change `parrot.tools.<module>` → `parrot_tools.<module>`.

**NOT in scope**: runtime imports (TASK-619, TASK-620), markdown docs (workday/MULTI_WSDL_EXAMPLE.md, ibisworld/README.md — these are documentation files, not code).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/security/__init__.py` | MODIFY | Fix docstring lines 8, 25-27 |
| `packages/ai-parrot-tools/src/parrot_tools/security/checkov/__init__.py` | MODIFY | Fix docstring line 8 |
| `packages/ai-parrot-tools/src/parrot_tools/security/trivy/__init__.py` | MODIFY | Fix docstring line 7 |
| `packages/ai-parrot-tools/src/parrot_tools/security/prowler/__init__.py` | MODIFY | Fix docstring line 7 |
| `packages/ai-parrot-tools/src/parrot_tools/security/reports/__init__.py` | MODIFY | Fix docstring line 7 |
| `packages/ai-parrot-tools/src/parrot_tools/docker/__init__.py` | MODIFY | Fix docstring lines 16, 22 |
| `packages/ai-parrot-tools/src/parrot_tools/pulumi/__init__.py` | MODIFY | Fix docstring lines 10, 16 |
| `packages/ai-parrot-tools/src/parrot_tools/ibkr/__init__.py` | MODIFY | Fix docstring line 8 |
| `packages/ai-parrot-tools/src/parrot_tools/system_health/tool.py` | MODIFY | Fix docstring line 14 |
| `packages/ai-parrot-tools/src/parrot_tools/chart.py` | MODIFY | Fix docstring line 12 |
| `packages/ai-parrot-tools/src/parrot_tools/codeinterpreter/__init__.py` | MODIFY | Fix docstring line 14 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All docstring examples should use parrot_tools.* paths:
from parrot_tools.security import (...)                # NOT parrot.tools.security
from parrot_tools.security.models import SecurityFinding, ScanResult
from parrot_tools.security.prowler import ProwlerExecutor, ProwlerConfig
from parrot_tools.security.reports import ComplianceMapper, ReportGenerator
from parrot_tools.security.checkov import CheckovConfig, CheckovExecutor
from parrot_tools.security.trivy import TrivyConfig, TrivyExecutor, TrivyParser
from parrot_tools.docker import DockerToolkit
from parrot_tools.pulumi import PulumiToolkit, PulumiConfig
from parrot_tools.ibkr import IBKRToolkit, IBKRConfig, RiskConfig
from parrot_tools.system_health import SystemHealthTool
from parrot_tools.chart import ChartTool
from parrot_tools.codeinterpreter import CodeInterpreterTool
```

### Does NOT Exist

- ~~`parrot.tools.security`~~ — does NOT exist in core
- ~~`parrot.tools.docker`~~ — does NOT exist in core
- ~~`parrot.tools.pulumi`~~ — does NOT exist in core
- ~~`parrot.tools.ibkr`~~ — does NOT exist in core
- ~~`parrot.tools.system_health`~~ — does NOT exist in core
- ~~`parrot.tools.chart`~~ — does NOT exist in core
- ~~`parrot.tools.code_interpreter`~~ — does NOT exist in core

---

## Implementation Notes

### Pattern to Follow

These are all in docstrings (triple-quoted strings) or comments. Simply replace the import path:

```python
# BEFORE (in docstring):
    >>> from parrot.tools.docker import DockerToolkit

# AFTER (in docstring):
    >>> from parrot_tools.docker import DockerToolkit
```

### Key Constraints
- Only change text inside docstrings and comments
- Do NOT change any runtime import statements (those are handled by TASK-619 and TASK-620)
- Preserve docstring formatting and indentation

---

## Acceptance Criteria

- [ ] `grep -rn "from parrot\.tools\.security" packages/ai-parrot-tools/src/parrot_tools/` returns zero results
- [ ] `grep -rn "from parrot\.tools\.docker" packages/ai-parrot-tools/src/parrot_tools/` returns zero results
- [ ] `grep -rn "from parrot\.tools\.pulumi" packages/ai-parrot-tools/src/parrot_tools/` returns zero results (except executor/config runtime imports if not yet fixed)
- [ ] `grep -rn "from parrot\.tools\.ibkr" packages/ai-parrot-tools/src/parrot_tools/` returns zero results
- [ ] All modified files have valid Python syntax

---

## Test Specification

```bash
# Verification: no stale docstring references remain
grep -rn "from parrot\.tools\.\(security\|docker\|pulumi\|ibkr\|system_health\|chart\|code_interpreter\)" \
  packages/ai-parrot-tools/src/parrot_tools/ --include="*.py" | grep -v __pycache__
# Expected: zero results (or only runtime imports handled by other tasks)
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
7. **Move this file** to `tasks/completed/TASK-621-fix-docstring-import-references.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
