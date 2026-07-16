---
type: Wiki Overview
title: 'TASK-1027: Phase 2 Tests'
id: doc:sdd-tasks-completed-task-1027-phase2-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Comprehensive unit tests for all Phase 2 methods. This task ensures full
  coverage
relates_to:
- concept: mod:parrot.interfaces.odoointerface
  rel: mentions
- concept: mod:parrot_tools.odoo
  rel: mentions
- concept: mod:parrot_tools.odoo.models.envelopes
  rel: mentions
- concept: mod:parrot_tools.odoo.toolkit
  rel: mentions
---

# TASK-1027: Phase 2 Tests

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1022, TASK-1023, TASK-1024, TASK-1025, TASK-1026
**Assigned-to**: unassigned

---

## Context

Comprehensive unit tests for all Phase 2 methods. This task ensures full coverage
of call diagnostics, JSON-2 payload generation, addon scanning, fit/gap analysis,
and business pack reporting.

Implements spec §3 Module 15 and §4 Test Specification (Phase 2 rows).

---

## Scope

- Create `packages/ai-parrot/tests/test_odoo_diagnostics.py` (new file)
- Test `diagnose_odoo_call`: safety classification, model validation, transport warnings,
  Odoo 20 deprecation
- Test `generate_json2_payload`: known ORM methods, unknown methods, header construction
- Test `scan_addons_source`: manifest discovery, risky method detection, max_files cap,
  path traversal blocking, SyntaxError handling
- Test `fit_gap_report`: standard/custom classification, live evidence improvement
- Test `business_pack_report`: pack definitions, live check, invalid pack name

**NOT in scope**: Phase 1 tests (TASK-1021).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_odoo_diagnostics.py` | CREATE | All Phase 2 tests |
| `packages/ai-parrot/tests/test_odoo_toolkit.py` | MODIFY | Add Phase 2 integration tests if needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, patch

from parrot_tools.odoo.toolkit import OdooToolkit
from parrot_tools.odoo.models.envelopes import (
    OdooCallDiagnosisResult, Json2PayloadResult, AddonScanResult,
    FitGapResult, BusinessPackResult,
)  # TASK-1013
from parrot.interfaces.odoointerface import OdooConfig, OdooRPCError
```

### Does NOT Exist
- ~~`parrot_tools.odoo.testing`~~ — no test utilities module

---

## Implementation Notes

### Test Coverage Requirements (from spec §4)
All 21 Phase 2 test cases listed in the spec's Unit Tests table must be covered.

### Addon Scanner Tests
Use `tempfile.TemporaryDirectory` to create sample addon structures:
```python
@pytest.fixture
def sample_addon_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        addon = os.path.join(tmpdir, "test_addon")
        os.makedirs(addon)
        # Create __manifest__.py
        with open(os.path.join(addon, "__manifest__.py"), "w") as f:
            f.write("{'name': 'Test', 'version': '1.0'}")
        # Create models/my_model.py with risky patterns
        models_dir = os.path.join(addon, "models")
        os.makedirs(models_dir)
        with open(os.path.join(models_dir, "my_model.py"), "w") as f:
            f.write("""
from odoo import models, fields

class MyModel(models.Model):
    _name = 'test.model'
    name = fields.Char()

    def unlink(self):
        self.sudo().check_something()
        return super().unlink()
""")
        yield tmpdir
```

---

## Acceptance Criteria

- [ ] All 21 Phase 2 test cases pass
- [ ] `pytest packages/ai-parrot/tests/test_odoo_diagnostics.py -v` passes
- [ ] No linting errors in test files

---

## Completion Note

Created `test_odoo_diagnostics.py` with 31 tests covering all Phase 2 methods:

- **diagnose_odoo_call** (5 tests): read_only/destructive/side_effect/unknown
  classification, invalid model name, Odoo 20 deprecation warning, observed-error hints,
  corrected-payload pass-through.
- **generate_json2_payload** (5 tests): endpoint format, positional-arg mapping for
  search_read/create/write, unknown method fallback, URL note inclusion.
- **scan_addons_source** (8 tests): manifest discovery, model class detection, risky
  methods (unlink/sudo), security file detection, max_files cap, syntax error handling,
  empty paths warning, non-existent path graceful warning.
- **fit_gap_report** (5 tests): standard/custom_module/studio/avoid classification,
  summary totals equal len(requirements).
- **business_pack_report** (4 tests): sales pack expected modules+models, hr pack,
  installed/missing live check from profile, invalid pack ValueError.

Includes `sample_addon_dir` fixture with manifest, model with `_name`, risky method
overrides, and `ir.model.access.csv`.

Bug fix: business_pack_report tests removed spurious version dict from execute_kw
side_effect (server_info uses transport.version() not execute_kw).

All 31 tests pass.

*(Agent fills this in when done)*
