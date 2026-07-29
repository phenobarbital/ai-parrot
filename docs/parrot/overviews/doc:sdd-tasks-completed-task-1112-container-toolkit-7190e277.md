---
type: Wiki Overview
title: 'TASK-1112: ContainerSecurityToolkit mixin integration + Trivy temp-file lifecycle'
id: doc:sdd-tasks-completed-task-1112-container-toolkit-mixin-trivy-tempfile-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires `ReportPersistenceMixin` into `ContainerSecurityToolkit` AND
relates_to:
- concept: mod:parrot_tools.security
  rel: mentions
- concept: mod:parrot_tools.security.persistence
  rel: mentions
---

# TASK-1112: ContainerSecurityToolkit mixin integration + Trivy temp-file lifecycle

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1109
**Assigned-to**: unassigned

---

## Context

Wires `ReportPersistenceMixin` into `ContainerSecurityToolkit` AND
resolves the Trivy stdout-only quirk by capturing stdout into a temp
file inside the toolkit, handing the `Path` to the mixin, and deleting
the file after persist (resolved U3 in the proposal phase).

Implements Spec §3 Module 6 part C. Mirrors TASK-1110's mixin pattern;
the Trivy-specific temp-file machinery is what makes this task distinct.

---

## Scope

- Modify the `ContainerSecurityToolkit` module under
  `packages/ai-parrot-tools/src/parrot_tools/security/` (confirm exact
  filename at task start). All public methods are prefixed `trivy_*`
  per finding F012 (`trivy_scan_filesystem`, `trivy_scan_image`, etc.).
- Change the class base to `(ReportPersistenceMixin, AbstractToolkit)`.
- Update `__init__` to pop `file_manager` / `report_store` via
  `pop_persistence_kwargs(kwargs)` BEFORE `super().__init__(**kwargs)`.
- For each public `trivy_*` scan method:
  1. Run the scan as today, capturing Trivy stdout (the existing scan
     pipeline already does this — verify at task start).
  2. **Write the captured JSON to a temp file** inside the toolkit
     (use `tempfile.NamedTemporaryFile(suffix=".json", delete=False)`
     or equivalent; record the `Path`).
  3. Call `await self._persist_report(scanner="trivy", framework=None,
     provider=<derived from method>, scope=<derived from method args>,
     content=tmp_path, content_type="application/json")` inside a
     `try: ... finally: tmp_path.unlink(missing_ok=True)` block.
  4. Return the same shape the method returns today (likely `ScanResult`
     or `dict` — confirm at task start; if `dict`, leave the return
     untouched; if Pydantic, also unchanged).
- Unit test verifying:
  - When `file_manager` + `report_store` are wired, calling a scan
    method creates AND deletes a temp file (assert via mocking
    `tempfile.NamedTemporaryFile`).
  - `_persist_report` receives the path as `content: Path`.
  - On no-op path (deps missing), no temp file is created (or it's
    cleaned up — either is acceptable; the integration test for
    *normal flow* must observe stdout-to-tmp behavior).
  - On persist failure, the temp file is still deleted (finally clause).

**NOT in scope**: CloudSploitToolkit (TASK-1110); ComplianceReportToolkit
(TASK-1111); refactoring Trivy stdout capture itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/security/<container-module>.py` | MODIFY | Add mixin + pop_persistence_kwargs + per-method temp-file persist |
| `packages/ai-parrot-tools/tests/security/test_container_persistence.py` | CREATE | Unit tests including temp-file lifecycle |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# new imports inside the container toolkit module
import tempfile
from pathlib import Path
from parrot_tools.security.persistence import (
    ReportPersistenceMixin, pop_persistence_kwargs,
)
```

### Existing Signatures to Use

```python
# F012, F013, F023 — ContainerSecurityToolkit current state:
# - All public methods prefixed trivy_* (e.g. trivy_scan_filesystem,
#   trivy_scan_image). Verify exact list at task start.
# - NO `results_dir` / `report_output_dir` attribute. Trivy output is
#   captured from STDOUT during executor.run(...).
# - Return shape: likely ScanResult (Pydantic) or dict — verify.
class ContainerSecurityToolkit(AbstractToolkit):
    async def trivy_scan_filesystem(self, ...): ...
    async def trivy_scan_image(self, ...): ...
    # ...
```

### Does NOT Exist

- ~~`ContainerSecurityToolkit.scan_filesystem`~~ (without prefix) — real
  name is `trivy_scan_filesystem`.
- ~~`ContainerSecurityToolkit.results_dir`~~ — does not exist; this task's
  temp-file approach exists precisely because there's no on-disk artifact
  by default.
- ~~A streaming `AsyncIterator[bytes]` Trivy capture API~~ — out of scope
  per resolved U3 ("temp-file approach", not streaming).

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot-tools/src/parrot_tools/security/<container>.py — diff sketch
import tempfile
from pathlib import Path
from parrot_tools.security.persistence import (
    ReportPersistenceMixin, pop_persistence_kwargs,
)


class ContainerSecurityToolkit(ReportPersistenceMixin, AbstractToolkit):
    def __init__(self, config, **kwargs):
        self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
        super().__init__(**kwargs)
        self.config = config
        # ... rest unchanged ...

    async def trivy_scan_filesystem(self, path: str, *, framework: str | None = None) -> ScanResult:
        # ... existing scan pipeline produces `stdout_bytes: bytes` ...
        result: ScanResult = self._parse(stdout_bytes)   # existing behaviour

        # Temp-file lifecycle for persistence (resolved U3)
        await self._persist_trivy(stdout_bytes, framework=framework, scope={"target_path": path})
        return result

    async def trivy_scan_image(self, image: str, *, framework: str | None = None) -> ScanResult:
        # ... existing scan pipeline ...
        result: ScanResult = self._parse(stdout_bytes)
        await self._persist_trivy(stdout_bytes, framework=framework, scope={"target_image": image})
        return result

    async def _persist_trivy(
        self, stdout_bytes: bytes, *, framework: str | None, scope: dict,
    ) -> None:
        if self.file_manager is None or self.report_store is None:
            return   # short-circuit: no temp file needed
        tmp = Path(tempfile.NamedTemporaryFile(
            mode="wb", suffix=".json", delete=False,
        ).name)
        try:
            tmp.write_bytes(stdout_bytes)
            await self._persist_report(
                scanner="trivy",
                framework=framework,
                provider="n/a",                    # Trivy targets containers/IaC; provider not always applicable
                scope=scope,
                content=tmp,
                content_type="application/json",
            )
        finally:
            tmp.unlink(missing_ok=True)
```

### Key Constraints

- **`try/finally` deletes the temp file** even on persist failure
  (Spec §7 R3 mitigation).
- **No temp file when deps missing.** The short-circuit at the top of
  `_persist_trivy` avoids tmp churn during normal use without persistence.
- **Return shape unchanged.** Callers continue to receive the existing
  `ScanResult` / dict.
- **No streaming.** Single `write_bytes` is sufficient — Trivy filesystem
  scans top out at a few MB.

### References in Codebase

- Spec §3 Module 6 part C.
- Findings F012, F013, F023 — current state of ContainerSecurityToolkit.
- TASK-1110 — canonical mixin-integration pattern.

---

## Acceptance Criteria

- [ ] `ContainerSecurityToolkit` inherits `ReportPersistenceMixin` first, then `AbstractToolkit`.
- [ ] Constructing with `file_manager=fm, report_store=store` does NOT raise.
- [ ] Each public `trivy_*` scan method that emits a persistable artifact
      writes stdout to a temp file, hands it to `_persist_report`, and
      deletes it afterward.
- [ ] On simulated persist failure (mock `_persist_report` to raise),
      the temp file is still deleted (verified via `os.path.exists`).
- [ ] No-op path: when persistence kwargs are absent, no temp file is created.
- [ ] Existing return shapes preserved.
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/security/test_container_persistence.py -v`.
- [ ] No regressions in existing Trivy tests.

---

## Test Specification

```python
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Verify exact import path at task start
from parrot_tools.security.container import ContainerSecurityToolkit


class TestContainerPersistence:
    async def test_trivy_writes_and_deletes_temp_file(self, tmp_path):
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(
            config=...,   # fill in at task start
            file_manager=fm, report_store=store,
        )
        # Stub the actual Trivy executor to return synthetic bytes
        toolkit._executor = AsyncMock()
        toolkit._executor.run = AsyncMock(return_value=b'{"Results": []}')
        captured_paths = []
        async def _persist(**kwargs):
            captured_paths.append(kwargs["content"])
            assert isinstance(kwargs["content"], Path)
            assert kwargs["content"].exists()
        with patch.object(toolkit, "_persist_report", new=_persist):
            await toolkit.trivy_scan_filesystem("/some/path")
        # After return, the temp file must be deleted:
        for p in captured_paths:
            assert not p.exists(), f"Temp file {p} leaked"

    async def test_temp_file_deleted_on_persist_failure(self):
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ContainerSecurityToolkit(config=..., file_manager=fm, report_store=store)
        toolkit._executor = AsyncMock()
        toolkit._executor.run = AsyncMock(return_value=b'{"Results": []}')
        seen_paths = []
        async def _boom(**kwargs):
            seen_paths.append(kwargs["content"])
            raise RuntimeError("persist failed")
        with patch.object(toolkit, "_persist_report", new=_boom):
            with pytest.raises(RuntimeError):
                await toolkit.trivy_scan_filesystem("/some/path")
        for p in seen_paths:
            assert not p.exists(), "Temp file leaked on persist failure"

    async def test_noop_no_tempfile(self, tmp_path):
        toolkit = ContainerSecurityToolkit(config=...)   # no persistence kwargs
        assert toolkit.file_manager is None
        # No-op path: confirm scan still succeeds and produces nothing in /tmp
        # (hard to assert globally — assert that _persist_trivy short-circuits
        #  by mocking tempfile.NamedTemporaryFile and asserting it was not called)
        with patch("tempfile.NamedTemporaryFile") as ntf:
            toolkit._executor = AsyncMock()
            toolkit._executor.run = AsyncMock(return_value=b'{"Results": []}')
            await toolkit.trivy_scan_filesystem("/some/path")
            ntf.assert_not_called()
```

---

## Agent Instructions

1. Read the spec section §3 Module 6 part C and findings F012, F013, F023.
2. Inspect the actual `ContainerSecurityToolkit` source — confirm exact
   filename, public method list (every `trivy_*`), and stdout-capture
   point in the existing executor.
3. Apply the temp-file lifecycle per the pattern above.
4. Run unit tests + existing Trivy tests for regressions.
5. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Module path: `container_security_toolkit.py`. Public methods instrumented:
`trivy_scan_image`, `trivy_scan_filesystem`, `trivy_scan_repo`, `trivy_scan_k8s`,
`trivy_scan_iac`. Added `_persist_trivy` helper with try/finally temp-file lifecycle.
Short-circuit when deps missing (no temp file created). 10 unit tests, all pass.

**Deviations from spec**: None. Note: stdout from TrivyExecutor is `str` — encoded
to bytes via `.encode("utf-8")` before writing to temp file.
