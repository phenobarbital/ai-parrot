---
type: Wiki Overview
title: 'TASK-1021: Phase 1 Tests'
id: doc:sdd-tasks-completed-task-1021-phase1-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Comprehensive unit tests for all Phase 1 methods. Each prior task may have
  added
relates_to:
- concept: mod:parrot.interfaces.odoointerface
  rel: mentions
- concept: mod:parrot_tools.odoo
  rel: mentions
- concept: mod:parrot_tools.odoo.models.entities
  rel: mentions
- concept: mod:parrot_tools.odoo.models.envelopes
  rel: mentions
- concept: mod:parrot_tools.odoo.smart_fields
  rel: mentions
- concept: mod:parrot_tools.odoo.toolkit
  rel: mentions
- concept: mod:parrot_tools.odoo.transport.base
  rel: mentions
---

# TASK-1021: Phase 1 Tests

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1014, TASK-1015, TASK-1016, TASK-1017, TASK-1018, TASK-1019, TASK-1020
**Assigned-to**: unassigned

---

## Context

Comprehensive unit tests for all Phase 1 methods. Each prior task may have added
minimal smoke tests; this task ensures full coverage with proper mocking, edge cases,
and integration between smart fields and toolkit methods.

Implements spec §3 Module 9 and §4 Test Specification (Phase 1 rows).

---

## Scope

- Create `packages/ai-parrot/tests/test_odoo_smart_fields.py` (if not already
  created by TASK-1014) — comprehensive smart-field tests
- Extend `packages/ai-parrot/tests/test_odoo_toolkit.py` with tests for:
  - Smart field integration (`search_records` + `get_record` auto mode)
  - `aggregate_records` (both `read_group` and `formatted_read_group` paths)
  - `build_domain` (AND, OR, invalid operator, empty)
  - `get_odoo_profile` and `schema_catalog`
  - `inspect_model_relationships`, `diagnose_access`, `health_check`
  - `search_employee` and `search_holidays` (success + module-not-installed)
- Add shared fixtures: `mock_transport`, `mock_fields_metadata`, `odoo_toolkit`

**NOT in scope**: Phase 2 method tests (TASK-1027).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_odoo_smart_fields.py` | CREATE or MODIFY | Smart field unit tests |
| `packages/ai-parrot/tests/test_odoo_toolkit.py` | MODIFY | Add tests for all Phase 1 methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from parrot_tools.odoo.toolkit import OdooToolkit
from parrot_tools.odoo.smart_fields import select_smart_fields  # TASK-1014
from parrot_tools.odoo.transport.base import AbstractOdooTransport  # transport/base.py:11
from parrot_tools.odoo.models.envelopes import (
    AggregateResult, DomainBuildResult, OdooProfileResult,
    SchemaCatalogResult, ModelRelationshipsResult,
    AccessDiagnosisResult, HealthCheckResult,
)  # TASK-1013
from parrot_tools.odoo.models.entities import HrEmployee, HrLeave  # TASK-1013
from parrot.interfaces.odoointerface import OdooConfig, OdooRPCError
```

### Does NOT Exist
- ~~`parrot_tools.odoo.testing`~~ — no test utilities module; use standard `unittest.mock`

---

## Implementation Notes

### Fixture Pattern
```python
@pytest.fixture
def odoo_config():
    return OdooConfig(url="https://test.odoo.com", database="test", username="admin", password="admin")

@pytest.fixture
def mock_transport():
    transport = AsyncMock(spec=AbstractOdooTransport)
    transport.uid = 2
    transport.name = "json2"
    transport.config = odoo_config()
    return transport

@pytest.fixture
def odoo_toolkit(mock_transport, odoo_config):
    tk = OdooToolkit(transport=mock_transport)
    tk._transport = mock_transport
    return tk
```

### Test Coverage Requirements (from spec §4)
All 22 Phase 1 test cases listed in the spec's Unit Tests table must be covered.

---

## Acceptance Criteria

- [ ] All 22 Phase 1 test cases pass
- [ ] `pytest packages/ai-parrot/tests/test_odoo_smart_fields.py -v` passes
- [ ] `pytest packages/ai-parrot/tests/test_odoo_toolkit.py -v` passes
- [ ] No linting errors in test files

---

## Completion Note

Created `test_odoo_smart_fields.py` (18 tests) covering all `_smart_field_score` and
`select_smart_fields` behaviors: binary/html exclusion, id/display_name pinning, score
ordering, always_include, max_fields cap, and constant assertions.

Extended `test_odoo_toolkit.py` with 18 Phase 1 tests covering: smart-field auto
selection (search_records, get_record), fields_get caching, aggregate_records (Odoo
16-18 read_group + Odoo 19 formatted_read_group), build_domain (AND/OR/invalid/empty),
get_odoo_profile (with/without modules), schema_catalog (with/without query),
inspect_model_relationships, diagnose_access (allowed/denied), health_check,
search_employee, and search_holidays (date range + employee filter).

Bug fixes applied:
- Removed "code" from HIGH_VALUE_PATTERNS (too generic; caused ref_code to score equal
  to "name" field — test_score_name_field_high).
- Updated test_get_record_uses_read to pass explicit fields (smart selection is now
  default for fields=None — separate test covers that path).
- Fixed aggregate_records mock: server_info() calls transport.version() not execute_kw.

All 67 tests pass (18 smart_fields + 49 toolkit).
