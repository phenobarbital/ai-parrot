---
type: Wiki Overview
title: 'TASK-1024: Addon Source Scanner (Phase 2)'
id: doc:sdd-tasks-completed-task-1024-scan-addons-source-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents need to inspect local custom addon code without importing it. This
  tool scans
relates_to:
- concept: mod:parrot_tools.odoo
  rel: mentions
---

# TASK-1024: Addon Source Scanner (Phase 2)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1013
**Assigned-to**: unassigned

---

## Context

Agents need to inspect local custom addon code without importing it. This tool scans
addon directories using AST parsing to find manifests, model classes, risky method
overrides, and security files.

Implements spec §3 Module 12: Addon Source Scanner.

---

## Scope

- Add `scan_addons_source` method to `OdooToolkit` (synchronous — filesystem only)
- Implement `__manifest__.py` / `__openerp__.py` discovery
- Parse Python files with `ast.parse` — never import or exec
- Detect model class definitions (classes inheriting `models.Model`, `models.TransientModel`)
- Flag risky method overrides: `create`, `write`, `unlink` overrides and `sudo()` calls
- Scan for `ir.model.access.csv` security files
- Scan for XML view files in `views/` directories
- Restrict paths to configured addon roots (prevent path traversal)
- Cap at `max_files` and `max_file_bytes`
- Decorate with `@tool_schema(ScanAddonsSourceInput)`
- Return `AddonScanResult` envelope

**NOT in scope**: Actually importing addon code, `fit_gap_report`, `business_pack_report`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `scan_addons_source` and private scanner helpers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import ScanAddonsSourceInput  # TASK-1013
from .models.envelopes import AddonScanResult     # TASK-1013

# Stdlib:
import ast
import os
from pathlib import Path
```

### Does NOT Exist
- ~~`OdooToolkit.scan_addons_source()`~~ — must be created
- ~~`parrot_tools.odoo.scanner`~~ — no such module

---

## Implementation Notes

### Path Traversal Prevention
```python
def _restrict_addons_paths(self, paths: list[str] | None) -> list[Path]:
    """Validate paths are under configured addon roots."""
    # Use self.config or an env var ODOO_ADDONS_PATHS for allowed roots
    # Resolve all paths and reject if not under an allowed root
    allowed_roots = [Path(p).resolve() for p in os.environ.get("ODOO_ADDONS_PATHS", "").split(":") if p]
    if not allowed_roots:
        return [Path(p).resolve() for p in (paths or [])]
    validated = []
    for p in (paths or []):
        resolved = Path(p).resolve()
        if any(str(resolved).startswith(str(root)) for root in allowed_roots):
            validated.append(resolved)
    return validated
```

### Manifest Discovery
- Walk directories looking for `__manifest__.py` or `__openerp__.py`
- Use `ast.literal_eval` on the file content to safely parse the dict

### Model Class Detection
```python
# In each .py file, look for classes that call models.Model in bases:
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        for base in node.bases:
            # Check for models.Model, models.TransientModel, models.AbstractModel
```

### Risky Method Detection
- Look for method definitions named `create`, `write`, `unlink` inside model classes
- Look for `Name(id='sudo')` calls in the AST

### Key Constraints
- **NEVER** `import` or `exec` addon code — AST parsing only
- Catch `SyntaxError` per file and report as warning, don't abort scan
- `max_files` capped at 1000
- `max_file_bytes` caps individual file reads to prevent memory issues
- Recognise both `__manifest__.py` (Odoo 10+) and `__openerp__.py` (legacy)

---

## Acceptance Criteria

- [ ] Discovers `__manifest__.py` in temp directory with sample addon
- [ ] Detects model class definitions inheriting from `models.Model`
- [ ] Flags `sudo()` calls and `unlink` method overrides
- [ ] Stops scanning after `max_files` cap
- [ ] Rejects paths outside allowed roots (path traversal prevention)
- [ ] Handles `SyntaxError` in individual files gracefully

---

## Test Specification

```python
import tempfile, os

def test_scan_finds_manifests(odoo_toolkit):
    with tempfile.TemporaryDirectory() as tmpdir:
        addon_dir = os.path.join(tmpdir, "my_addon")
        os.makedirs(addon_dir)
        with open(os.path.join(addon_dir, "__manifest__.py"), "w") as f:
            f.write("{'name': 'My Addon', 'version': '1.0'}")
        result = tk.scan_addons_source(addons_paths=[tmpdir])
        assert result.addons_found >= 1

def test_scan_detects_risky_methods(odoo_toolkit):
    # Create temp addon with sudo() call in a model
    ...

def test_scan_path_traversal_blocked(odoo_toolkit, monkeypatch):
    monkeypatch.setenv("ODOO_ADDONS_PATHS", "/safe/addons")
    result = tk.scan_addons_source(addons_paths=["/etc/passwd"])
    assert result.addons_found == 0
```

---

## Completion Note

*(Agent fills this in when done)*
