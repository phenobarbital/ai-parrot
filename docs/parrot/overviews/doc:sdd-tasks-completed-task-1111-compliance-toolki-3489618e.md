---
type: Wiki Overview
title: 'TASK-1111: ComplianceReportToolkit mixin integration'
id: doc:sdd-tasks-completed-task-1111-compliance-toolkit-mixin-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires `ReportPersistenceMixin` into `ComplianceReportToolkit` so each
relates_to:
- concept: mod:parrot_tools.security
  rel: mentions
- concept: mod:parrot_tools.security.persistence
  rel: mentions
---

# TASK-1111: ComplianceReportToolkit mixin integration

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1109
**Assigned-to**: unassigned

---

## Context

Wires `ReportPersistenceMixin` into `ComplianceReportToolkit` so each
multi-scanner compliance run (Prowler + Trivy + Checkov) auto-persists
its `ConsolidatedReport` into the catalog as a side effect.

Implements Spec §3 Module 6 part B. Mirrors TASK-1110's pattern;
read that task for the canonical mixin-integration approach.

---

## Scope

- Modify the existing `ComplianceReportToolkit` module under
  `packages/ai-parrot-tools/src/parrot_tools/security/` (confirm the
  exact filename at task start via
  `ls packages/ai-parrot-tools/src/parrot_tools/security/`).
- Change the class base to `(ReportPersistenceMixin, AbstractToolkit)`.
- Update `__init__` to pop `file_manager` / `report_store` BEFORE
  `super().__init__(**kwargs)` using `pop_persistence_kwargs`.
- After each public scan method produces a `ConsolidatedReport`, call
  `await self._persist_report(...)` with:
  - `scanner="aggregator"` (the orchestrator emits a consolidated report
    that aggregates Prowler/Trivy/Checkov — pick `aggregator` to keep the
    parser dispatch consistent; or pick the dominant child scanner if
    the toolkit emits per-child refs separately — VERIFY at task start
    by reading the existing toolkit).
  - `framework=<framework string>` (e.g., "HIPAA", "PCI", "SOC2").
  - `provider=<provider string>` (likely "aws" for v1; see Spec §8
    unresolved "Multi-provider scope" — but the user has resolved that
    to **full multi-provider from day 1**, so derive `provider` from
    the toolkit's config rather than hard-coding).
  - `scope={"account_id": ..., "region": ...}` from the toolkit's config.
  - `content=result.model_dump_json().encode("utf-8")` (the
    `ConsolidatedReport` is the canonical artifact for this toolkit).
- Unit test verifying:
  - `_persist_report` is called exactly once per scan with the expected
    `scanner` / `framework` / `provider` values.
  - No-op when persistence kwargs aren't injected.

**NOT in scope**: CloudSploitToolkit (TASK-1110); ContainerSecurityToolkit
(TASK-1112); changes to the underlying Prowler/Trivy/Checkov sub-toolkits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/security/<compliance-module>.py` | MODIFY | Add mixin + pop_persistence_kwargs + _persist_report after each scan |
| `packages/ai-parrot-tools/tests/security/test_compliance_persistence.py` | CREATE | New unit tests for the persistence path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# new imports inside the compliance toolkit module
from parrot_tools.security.persistence import (
    ReportPersistenceMixin, pop_persistence_kwargs,
)
```

### Existing Signatures to Use

```python
# F012 / F013 — ComplianceReportToolkit returns ConsolidatedReport (Pydantic).
# Verify exact method names + signatures at task start; the toolkit orchestrates
# Prowler + Trivy + Checkov via sub-toolkits. Likely public methods include
# `run_compliance` or `run_hipaa_compliance` / `run_pci_compliance` etc.
# The mixin call is the same shape regardless of public method name.
```

### Does NOT Exist

- ~~A `dict`-returning scan method on ComplianceReportToolkit~~ — it
  returns `ConsolidatedReport` (Pydantic). Serialize via
  `result.model_dump_json().encode("utf-8")`.
- ~~A `results_dir` attribute on ComplianceReportToolkit~~ — verify;
  the toolkit may carry one for sub-reports but the consolidated
  artifact is in-memory until persisted.

---

## Implementation Notes

### Pattern to Follow

See TASK-1110's *Pattern to Follow* — the structure is identical:

1. `class XToolkit(ReportPersistenceMixin, AbstractToolkit):`
2. `self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)`
   BEFORE `super().__init__(**kwargs)`.
3. After each scan method's body completes successfully, call
   `await self._persist_report(scanner=..., framework=..., provider=...,
   scope=..., content=result.model_dump_json().encode("utf-8"))`.

### Key Constraints

- Return shape unchanged.
- No new behavior on no-op path.
- Pop kwargs FIRST.
- Use `scanner="aggregator"` for the consolidated artifact (matches the
  `AggregatorParser` from TASK-1108) — UNLESS the toolkit also emits
  individual `prowler`/`trivy`/`checkov` refs. If it does, each per-child
  artifact gets its own `_persist_report` call with the matching scanner
  name.

### References in Codebase

- TASK-1110 — canonical mixin integration pattern.
- Findings F012, F013 — current toolkit layout.

---

## Acceptance Criteria

- [ ] ComplianceReportToolkit inherits `ReportPersistenceMixin` first, then `AbstractToolkit`.
- [ ] Constructing with `file_manager=fm, report_store=store` does NOT raise.
- [ ] Each public scan method invokes `_persist_report` exactly once per consolidated artifact, with appropriate `scanner` and `framework` values.
- [ ] Toolkit's existing return shape (`ConsolidatedReport`) is unchanged.
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/security/test_compliance_persistence.py -v`.
- [ ] No regressions in existing compliance tests.

---

## Test Specification

Adapt the test shape from TASK-1110:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Verify exact import path at task start
from parrot_tools.security.compliance_report import ComplianceReportToolkit


class TestCompliancePersistence:
    async def test_persists_after_scan(self):
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ComplianceReportToolkit(
            # ... config args; verify at task start ...
            file_manager=fm, report_store=store,
        )
        # Stub sub-toolkits to return synthetic consolidated report.
        with patch.object(toolkit, "_persist_report", AsyncMock()) as p:
            await toolkit.run_compliance("HIPAA")   # or the real method name
            p.assert_called_once()
            assert p.call_args.kwargs["framework"] == "HIPAA"

    async def test_noop_when_persistence_kwargs_missing(self):
        toolkit = ComplianceReportToolkit(...)
        assert toolkit.file_manager is None
        assert toolkit.report_store is None
```

---

## Agent Instructions

1. Read the spec section §3 Module 6 part B and TASK-1110 for the
   canonical pattern.
2. Inspect the compliance toolkit source — confirm exact module name,
   method names, constructor signature, and the `ConsolidatedReport`
   shape.
3. Apply the diff using TASK-1110's pattern as the template.
4. Run unit tests + existing compliance tests.
5. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Module name confirmed: `compliance_report_toolkit.py`.
Public scan method instrumented: `compliance_full_scan` (the only method that
produces a `ConsolidatedReport`; the `compliance_soc2_report` / `compliance_hipaa_report`
etc. are report generators that return file paths, not scan artifacts).
Used `scanner="aggregator"`, `provider=provider` from method arg.
6 unit tests, all pass.

**Deviations from spec**: none
