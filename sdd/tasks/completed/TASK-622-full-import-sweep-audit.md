# TASK-622: Full Automated Sweep — Catch Remaining Stale Imports

**Feature**: refactor-tools-imports
**Spec**: `sdd/specs/refactor-tools-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-619, TASK-620, TASK-621
**Assigned-to**: unassigned

---

## Context

Tasks 619-621 fix the known broken imports identified during the initial audit.
However, with 244 Python files and 100+ tools in `parrot_tools`, the initial audit
may have missed edge cases. This task performs a comprehensive automated sweep to
catch ANY remaining stale `from parrot.tools.<X>` imports where `<X>` is a module
that only exists in `parrot_tools`.

Implements Spec Module 5.

---

## Scope

1. Run a comprehensive grep across ALL `.py` files in `packages/ai-parrot-tools/src/parrot_tools/`
2. For every `from parrot.tools.<module>` import found, verify whether `<module>` actually exists in `packages/ai-parrot/src/parrot/tools/`
3. If it does NOT exist there, fix the import to use `parrot_tools.<module>` or relative imports
4. Also check for any `import parrot.tools.<module>` (bare imports, not just `from` imports)
5. Check markdown documentation files (`.md`) in parrot_tools for stale references

**Modules that DO exist in parrot.tools (do NOT change these):**
- `abstract`, `toolkit`, `decorators`, `manager`, `registry`, `discovery`
- `agent`, `json_tool`, `mcp_mixin`, `filemanager`, `pythonrepl`, `pythonpandas`
- `openapitoolkit`, `multistoresearch`, `vectorstoresearch`, `pageindex_toolkit`
- `excel_intelligence`, `database/`, `dataset_manager/`, `working_memory/`

**Everything else is parrot_tools-only and must NOT be imported via `parrot.tools.*`.**

**NOT in scope**: creating the test suite (TASK-623).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| Any `.py` file in `parrot_tools/` with stale imports | MODIFY | Fix import paths |
| Any `.md` file in `parrot_tools/` with stale references | MODIFY | Fix documentation paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Cross-package imports that ARE correct (these modules exist in parrot.tools core):
from parrot.tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool
from parrot.tools.decorators import tool_schema, tool, requires_permission
from parrot.tools.manager import ToolManager                 # packages/ai-parrot/src/parrot/tools/manager.py:192
from parrot.tools.registry import ToolkitRegistry            # packages/ai-parrot/src/parrot/tools/registry.py
from parrot.tools.dataset_manager import DatasetManager      # packages/ai-parrot/src/parrot/tools/dataset_manager/
from parrot.tools.pythonpandas import PythonPandasTool        # packages/ai-parrot/src/parrot/tools/pythonpandas.py
```

### Does NOT Exist

- ~~`parrot.tools.security`~~ — entire subtree only in parrot_tools
- ~~`parrot.tools.scraping`~~ — entire subtree only in parrot_tools
- ~~`parrot.tools.docker`~~ — entire subtree only in parrot_tools
- ~~`parrot.tools.pulumi`~~ — entire subtree only in parrot_tools
- ~~`parrot.tools.querytoolkit`~~ — only in parrot_tools
- ~~`parrot.tools.databasequery`~~ — only in parrot_tools
- ~~`parrot.tools.ibkr`~~ — only in parrot_tools
- ~~`parrot.tools.quant`~~ — only in parrot_tools
- ~~`parrot.tools.o365`~~ — only in parrot_tools
- ~~`parrot.tools.navigator`~~ — only in parrot_tools
- ~~`parrot.tools.massive`~~ — only in parrot_tools
- ~~`parrot.tools.flowtask`~~ — only in parrot_tools
- ~~`parrot.tools.company_info`~~ — only in parrot_tools
- ~~`parrot.tools.google`~~ — only in parrot_tools
- ~~`parrot.tools.retail`~~ — only in parrot_tools
- ~~`parrot.tools.workday`~~ — only in parrot_tools
- ~~`parrot.tools.sassie`~~ — only in parrot_tools
- ~~`parrot.tools.troc`~~ — only in parrot_tools
- ~~`parrot.tools.messaging`~~ — only in parrot_tools
- ~~`parrot.tools.epson`~~ — only in parrot_tools
- ~~`parrot.tools.shell_tool`~~ — only in parrot_tools
- ~~`parrot.tools.sitesearch`~~ — only in parrot_tools
- ~~`parrot.tools.cloudsploit`~~ — only in parrot_tools
- ~~`parrot.tools.codeinterpreter`~~ — only in parrot_tools
- ~~`parrot.tools.system_health`~~ — only in parrot_tools
- ~~`parrot.tools.calculator`~~ — only in parrot_tools
- ~~`parrot.tools.ibisworld`~~ — only in parrot_tools
- ~~`parrot.tools.chart`~~ — only in parrot_tools
- ~~`parrot.tools.file`~~ — only in parrot_tools
- ~~`parrot.tools.pricestool`~~ — only in parrot_tools

---

## Implementation Notes

### Audit Script

```bash
# Step 1: Find all from parrot.tools.* imports in parrot_tools
grep -rn "from parrot\.tools\." packages/ai-parrot-tools/src/parrot_tools/ \
  --include="*.py" | grep -v __pycache__

# Step 2: For each unique module, check if it exists in core
ls packages/ai-parrot/src/parrot/tools/

# Step 3: Any import referencing a module NOT in that list is broken
```

### Key Constraints
- Preserve correct imports (base classes from `parrot.tools`)
- Use relative imports for within-subpackage references
- Use `parrot_tools.*` absolute imports for cross-subpackage references within ai-parrot-tools
- Check `.md` files too (grep for `parrot.tools.` in documentation)

---

## Acceptance Criteria

- [ ] `grep -rn "from parrot\.tools\." packages/ai-parrot-tools/src/ --include="*.py"` returns ONLY imports of modules that actually exist in `packages/ai-parrot/src/parrot/tools/`
- [ ] Every remaining `from parrot.tools.*` import can be verified by the corresponding file existing at `packages/ai-parrot/src/parrot/tools/<module>.py` or `<module>/`
- [ ] Zero false positives — correct cross-package imports are preserved

---

## Test Specification

```bash
# Final validation: list all remaining parrot.tools imports and verify each one
grep -rn "from parrot\.tools\." packages/ai-parrot-tools/src/parrot_tools/ \
  --include="*.py" | grep -v __pycache__ | \
  awk -F'from parrot.tools.' '{print $2}' | awk -F' ' '{print $1}' | \
  sort -u | while read mod; do
    base=$(echo "$mod" | cut -d. -f1)
    if [ -e "packages/ai-parrot/src/parrot/tools/${base}.py" ] || \
       [ -d "packages/ai-parrot/src/parrot/tools/${base}" ]; then
      echo "OK: parrot.tools.${mod}"
    else
      echo "BROKEN: parrot.tools.${mod}"
    fi
  done
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
7. **Move this file** to `tasks/completed/TASK-622-full-import-sweep-audit.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
