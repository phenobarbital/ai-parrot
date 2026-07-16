---
type: Wiki Overview
title: 'TASK-1110: CloudSploitToolkit mixin integration (with FEAT-160 config threading)'
id: doc:sdd-tasks-completed-task-1110-cloudsploit-toolkit-mixin-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires `ReportPersistenceMixin` into `CloudSploitToolkit` so every
relates_to:
- concept: mod:parrot_tools.cloudsploit
  rel: mentions
- concept: mod:parrot_tools.security.persistence
  rel: mentions
---

# TASK-1110: CloudSploitToolkit mixin integration (with FEAT-160 config threading)

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1109
**Assigned-to**: unassigned

---

## Context

Wires `ReportPersistenceMixin` into `CloudSploitToolkit` so every
`run_scan` / `run_compliance_scan` call auto-persists its `ScanResult`
into the catalog as a side effect. Returns shape is preserved
(`ScanResult` is still returned to callers). Threads FEAT-160's
`CloudSploitConfig.config_file` + per-call `config` arg through unchanged.

Implements Spec §3 Module 6 part A.

---

## Scope

- Modify `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`:
  - Change `class CloudSploitToolkit(AbstractToolkit):` to
    `class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit):`.
  - Update `__init__(self, config: Optional[CloudSploitConfig] = None, **kwargs)`:
    - Call `self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)`
      BEFORE `super().__init__(**kwargs)`.
  - After each scan method body completes successfully (i.e. `result: ScanResult`
    is built), call `await self._persist_report(...)`:
    - `run_scan`: `scanner="cloudsploit"`, `framework=None`,
      `provider=self.config.cloud_provider.value` (or string equivalent — verify
      in the executor at task start),
      `scope={"account_id": <from config>, "region": <from config>}`,
      `content=<results_dir Path if set, else result.model_dump_json().encode()>`.
    - `run_compliance_scan`: same as above with `framework=framework`.
  - Persistence is a side effect. If `_persist_report` returns `None`
    (no deps wired), continue as today; the method's return value is
    unchanged (`ScanResult`).
- Unit test in `tests/cloudsploit/test_toolkit_persistence.py`:
  - Construct toolkit with `file_manager=Mock(), report_store=AsyncMock()`;
    confirm `_persist_report` is called exactly once after a stubbed
    `run_compliance_scan` call.
  - Construct toolkit WITHOUT persistence kwargs; confirm behavior is
    unchanged (no `_persist_report` activity).

**NOT in scope**: ComplianceReportToolkit (TASK-1111); ContainerSecurityToolkit
(TASK-1112); store implementation; LLM-facing toolkit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py` | MODIFY | Add mixin + pop_persistence_kwargs + _persist_report after each scan |
| `packages/ai-parrot-tools/tests/cloudsploit/test_toolkit_persistence.py` | CREATE | New unit tests for the persistence path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# new imports inside parrot/cloudsploit/toolkit.py
from parrot_tools.security.persistence import (
    ReportPersistenceMixin, pop_persistence_kwargs,
)
# existing imports preserved (verify at task start):
#   AbstractToolkit, CloudSploitConfig, CloudSploitExecutor, ScanResultParser,
#   ReportGenerator, ScanComparator, ScanResult, ComplianceFramework
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py — current state (F011, line numbers ±)
class CloudSploitToolkit(AbstractToolkit):                              # line 23
    def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):  # line 23-37
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        self.executor = CloudSploitExecutor(self.config)
        self.parser = ScanResultParser()
        self.report_generator = ReportGenerator()
        self.comparator = ScanComparator()
        self._last_result: Optional[ScanResult] = None

    async def run_scan(
        self, plugins=None, ignore_ok=False, suppress=None, config=None,
    ) -> ScanResult:                                                    # line 71-119
        # When self.config.results_dir is set, writes JSON to
        # {results_dir}/scan_{YYYYMMDD_HHMMSS}.json after parsing.
        ...

    async def run_compliance_scan(
        self, framework: str, ignore_ok: bool = True, config=None,
    ) -> ScanResult:                                                    # line 121-163
        ...

# FEAT-160 (merged 2026-05-12) added:
#   CloudSploitConfig.config_file: Optional[str]
#   per-call `config` arg on run_scan / run_compliance_scan
# DO NOT alter these — pass them through unchanged.

# CloudSploitConfig: verify exact field names for the scope dict at task start.
#   Likely: cloud_provider (enum), aws_account_id, aws_region, results_dir, config_file.
```

### Does NOT Exist

- ~~`CloudSploitToolkit.run_cloudsploit_scan`~~ — finding F011 confirms
  the real method names are `run_scan` and `run_compliance_scan`.
- ~~An `output_format` kwarg on the scan methods~~ — format conversion
  lives in a separate `generate_report(format=...)` method.
- ~~`CloudSploitToolkit.results_dir`~~ at the class level — it's on
  `self.config.results_dir`.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py — diff sketch
from parrot_tools.security.persistence import (
    ReportPersistenceMixin, pop_persistence_kwargs,
)


class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit):
    def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):
        # MUST run BEFORE super().__init__ to keep AbstractToolkit's contract intact
        self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        # ... rest unchanged ...

    async def run_compliance_scan(
        self, framework: str, ignore_ok: bool = True, config=None,
    ) -> ScanResult:
        # ... existing body produces `result: ScanResult` ...

        # Persistence (side effect — no-op when deps missing)
        await self._persist_after_scan(result, framework=framework)
        return result

    async def run_scan(
        self, plugins=None, ignore_ok=False, suppress=None, config=None,
    ) -> ScanResult:
        # ... existing body produces `result: ScanResult` ...
        await self._persist_after_scan(result, framework=None)
        return result

    async def _persist_after_scan(
        self, result: ScanResult, *, framework: str | None,
    ) -> None:
        # Prefer the on-disk JSON if results_dir was set; else serialize bytes.
        if self.config.results_dir:
            ts = result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
            content: bytes | Path = Path(self.config.results_dir) / f"scan_{ts}.json"
        else:
            content = result.model_dump_json().encode("utf-8")

        await self._persist_report(
            scanner="cloudsploit",
            framework=framework,
            provider=getattr(self.config.cloud_provider, "value", "aws"),
            scope={
                "account_id": getattr(self.config, "aws_account_id", None),
                "region":     getattr(self.config, "aws_region", None),
            },
            content=content,
        )
```

### Key Constraints

- **Return shape unchanged.** Callers still receive `ScanResult`. The
  persisted `ReportRef` is NOT returned from the scan methods — that
  would break back-compat.
- **No new behavior on no-op path.** When persistence kwargs are not
  injected, the toolkit behaves exactly as it does today.
- **FEAT-160 surface untouched.** `CloudSploitConfig.config_file` and
  the per-call `config` arg pass through unchanged.
- **Pop kwargs FIRST.** If you call `super().__init__(**kwargs)` with
  `file_manager=...` still in kwargs, AbstractToolkit will raise.

### References in Codebase

- Spec §3 Module 6 part A.
- Finding F011 — current CloudSploitToolkit signatures.
- Finding F019 — FEAT-160 merged today, threading the new config field.

---

## Acceptance Criteria

- [ ] `CloudSploitToolkit` inherits `ReportPersistenceMixin` first, then `AbstractToolkit`.
- [ ] Constructing the toolkit with `file_manager=fm, report_store=store` does NOT raise.
- [ ] Calling `run_compliance_scan("HIPAA")` with persistence wired invokes `_persist_report` exactly once with `scanner="cloudsploit", framework="HIPAA"`.
- [ ] Calling `run_scan(...)` invokes `_persist_report` exactly once with `framework=None`.
- [ ] Calling the scan methods without persistence kwargs produces no `_persist_report` calls (behaves as today).
- [ ] FEAT-160's `CloudSploitConfig.config_file` and per-call `config` arg still pass through unchanged.
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/cloudsploit/test_toolkit_persistence.py -v`.
- [ ] No regressions in existing CloudSploit tests.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/cloudsploit/test_toolkit_persistence.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from parrot_tools.cloudsploit import CloudSploitToolkit, CloudSploitConfig


@pytest.fixture
def stubbed_scan_result():
    # Build a minimal valid ScanResult; verify the shape at task start.
    ...


class TestCloudSploitPersistence:
    async def test_persists_after_compliance_scan(self, stubbed_scan_result, monkeypatch):
        fm = MagicMock()
        store = AsyncMock()
        toolkit = CloudSploitToolkit(
            config=CloudSploitConfig(results_dir=None),
            file_manager=fm, report_store=store,
        )
        # Stub the heavy executor path; route to the stubbed result.
        toolkit.executor = AsyncMock()
        toolkit.executor.run_compliance = AsyncMock(return_value=stubbed_scan_result)
        toolkit.parser = MagicMock()
        toolkit.parser.parse_result = MagicMock(return_value=stubbed_scan_result)

        with patch.object(toolkit, "_persist_report", AsyncMock()) as p:
            await toolkit.run_compliance_scan("HIPAA")
            p.assert_called_once()
            kwargs = p.call_args.kwargs
            assert kwargs["scanner"] == "cloudsploit"
            assert kwargs["framework"] == "HIPAA"

    async def test_noop_when_persistence_kwargs_missing(self, stubbed_scan_result):
        toolkit = CloudSploitToolkit(config=CloudSploitConfig(results_dir=None))
        assert toolkit.file_manager is None
        assert toolkit.report_store is None
        # Calling _persist_report directly should be a no-op:
        result = await toolkit._persist_report(
            scanner="cloudsploit", framework="HIPAA", provider="aws",
            scope={}, content=b"{}",
        )
        assert result is None

    async def test_kwargs_pop_keeps_super_init_clean(self):
        # If pop fails, AbstractToolkit.__init__ would raise on unknown kwargs.
        toolkit = CloudSploitToolkit(
            file_manager=MagicMock(),
            report_store=AsyncMock(),
        )
        assert toolkit is not None
```

---

## Agent Instructions

1. Read the spec section §3 Module 6 part A and §6 Codebase Contract.
2. Inspect the actual `CloudSploitToolkit` source — confirm exact line
   numbers (F011 may have drifted; FEAT-160 commit `bfb825e7` touched
   the file recently).
3. Verify `CloudSploitConfig` field names (`aws_account_id`, `aws_region`,
   `cloud_provider`, `results_dir`, `config_file`).
4. Apply the diff per the pattern above.
5. Run unit tests + existing CloudSploit tests for regressions.
6. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Changed CloudSploitToolkit to inherit from ReportPersistenceMixin first,
then AbstractToolkit. Added pop_persistence_kwargs in __init__ before super().__init__.
Added _persist_after_scan helper. Added persist calls after run_scan and
run_compliance_scan. Created 6 unit tests in test_toolkit_persistence.py, all pass.
5 pre-existing failures in executor/model tests unrelated to this task.

**Deviations from spec**: `aws_account_id` field does NOT exist on CloudSploitConfig
(verified — only aws_region and cloud_provider are present). scope dict uses
getattr fallback: `{"account_id": None, "region": <aws_region>}`.
