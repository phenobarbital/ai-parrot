---
type: Wiki Overview
title: 'TASK-1123: `CloudSploitToolkit.collect_ecr_findings` + `generate_ecr_report`'
id: doc:sdd-tasks-completed-task-1123-cloudsploit-toolkit-ecr-methods-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 6** of the spec (`sdd/specs/cloudsploit-ecr.spec.md`
  §3).
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot_tools.cloudsploit
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
- concept: mod:parrot_tools.security.persistence
  rel: mentions
---

# TASK-1123: `CloudSploitToolkit.collect_ecr_findings` + `generate_ecr_report`

**Feature**: FEAT-165 — CloudSploit ECR Image-Scan Collector & Interactive Report
**Spec**: `sdd/specs/cloudsploit-ecr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1118, TASK-1120, TASK-1122
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec (`sdd/specs/cloudsploit-ecr.spec.md` §3).

This task lights up the agent-facing surface: two new async methods on
`CloudSploitToolkit` that compose the collector (TASK-1120) and renderer
(TASK-1122) and (when persistence kwargs are present) write to the security
report catalog via the existing `ReportPersistenceMixin`.

The `_resolve_ecr_plan(per_call)` helper mirrors the `_resolve_config`
precedence pattern shipped by FEAT-160 (`toolkit.py:75-101`).

---

## Scope

- Modify `CloudSploitToolkit.__init__` (toolkit.py:34) to instantiate the
  new collaborator: `self.ecr_collector = EcrScanCollector(...)`. Use
  `AWSInterface(aws_id=..., region_name=self.config.aws_region)` — same
  pattern as `ECRToolkit.__init__`.
- Store last result: `self._last_ecr_result: Optional[EcrCollectionResult] = None`.
- Add `def _resolve_ecr_plan(self, per_call: Optional[str]) -> Optional[str]`,
  modelled on `_resolve_config` (toolkit.py:75-101) but reading
  `self.config.ecr_plan_file`.
- Add `async def _persist_after_ecr_scan(self, result: EcrCollectionResult)`,
  a sibling of `_persist_after_scan` (toolkit.py:49-73), calling
  `self._persist_report(scanner="ecr-image-scan", framework=None,
  provider="aws", scope={"region": plan_region, "account_id": ...}, content=...)`.
  Pre-compute `severity_summary` (a `SeverityBreakdown`-compatible dict
  derived from `result.repos[*].counts`) and pass it explicitly to skip
  the parser-registry lookup (per spec §2 Overview, persistence section).
- Add `async def collect_ecr_findings(self, plan: Optional[str] = None)
  -> EcrCollectionResult`:
  - Resolve effective plan path via `_resolve_ecr_plan(plan)`. Raise
    `ValueError("No ECR plan configured...")` when both `plan` and
    `self.config.ecr_plan_file` are None.
  - Load the plan: `EcrCollectionPlan.from_yaml(effective)`.
  - Call `self.ecr_collector.collect(plan_model)`.
  - Store on `self._last_ecr_result` and call
    `_persist_after_ecr_scan(result)` (side-effect; no-op when persistence
    deps are absent).
  - Return the `EcrCollectionResult`.
- Add `async def generate_ecr_report(self, output_path: Optional[str] = None,
  result: Optional[EcrCollectionResult] = None) -> str`:
  - Use `result` argument if given, else `self._last_ecr_result`.
  - Raise `ValueError("No ECR collection available...")` when both are None.
  - Auto-generate `output_path` from `self.config.results_dir` and the
    result's `generated_at` when None (mirrors `generate_report` at
    toolkit.py:215).
  - Delegate to `self.report_generator.generate_ecr_html(...)`.
- Both new methods decorated with `@tool_schema(...)` with explicit Pydantic
  input models for richer agent tool descriptions (follow the pattern in
  `aws/ecr.py:93,155,187,246`).
- Add unit tests covering: per-call vs config-field precedence, no-plan
  ValueError, last-result reuse, persistence call when deps present,
  no-op when deps absent.

**NOT in scope**: changes to `run_scan`, `run_compliance_scan`,
`compare_scans`, `list_findings`, the executor, the parser, or the
comparator. Module 1 (models), 2 (collector), 5 (report method) are
expected to be complete.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py` | MODIFY | Add `__init__` collaborator + 2 helpers + 2 public methods |
| `packages/ai-parrot-tools/tests/cloudsploit/test_toolkit.py` | MODIFY | Add the 6 tests below |
| `packages/ai-parrot-tools/tests/cloudsploit/test_toolkit_persistence.py` | MODIFY | Add 1 test for ECR persistence call |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already at the top of toolkit.py — re-use, do NOT re-import.
from pathlib import Path
from typing import Optional
from ..toolkit import AbstractToolkit
from .comparator import ScanComparator
from .executor import CloudSploitExecutor
from .models import (
    CloudSploitConfig,
    ComparisonReport,
    ComplianceFramework,
    ScanResult,
    SeverityLevel,
)
from .parser import ScanResultParser
from .reports import ReportGenerator
from parrot_tools.security.persistence import (
    ReportPersistenceMixin,
    pop_persistence_kwargs,
)
# Verified at: cloudsploit/toolkit.py:1-24

# New imports for this task
from parrot.interfaces.aws import AWSInterface
# Verified at: parrot/interfaces/aws.py:22

from .ecr_collector import EcrScanCollector
# Created by TASK-1120 — verify before use.

from .models import (
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrSeverity,
)
# Created by TASK-1118 — verify before use.

from ..decorators import tool_schema
# Verified at: parrot_tools/decorators.py:2
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py
class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit):  # line 27

    def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):
        # line 34
        self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        self.executor = CloudSploitExecutor(self.config)
        self.parser = ScanResultParser()
        self.report_generator = ReportGenerator()
        self.comparator = ScanComparator()
        self._last_result: Optional[ScanResult] = None

    async def _persist_after_scan(
        self, result: ScanResult, *, framework: Optional[str],
    ) -> None: ...                                                   # line 49

    def _resolve_config(self, per_call: Optional[str]) -> Optional[str]:
        ...                                                          # line 75

    async def run_scan(...) -> ScanResult: ...                       # line 105
    async def generate_report(
        self, format: str = "html", output_path: Optional[str] = None,
    ) -> str: ...                                                    # line 215

# packages/ai-parrot-tools/src/parrot_tools/security/persistence.py
async def _persist_report(
    self, *, scanner: str, framework: str | None, provider: str,
    scope: dict, content: bytes | Path,
    content_type: str = "application/json",
    report_kind: ReportKind = ReportKind.SCAN,
    produced_by: str | None = None,
    severity_summary: SeverityBreakdown | None = None,
    top_findings: list[EmbeddedFinding] | None = None,
) -> ReportRef | None: ...                                           # line 77

# packages/ai-parrot/src/parrot/interfaces/aws.py
class AWSInterface:
    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        credentials: Optional[dict] = None,
        **kwargs,
    ): ...                                                           # line 35
```

### Does NOT Exist
- ~~`self.ecr_collector.run(...)`~~ — the collector method is `collect(plan)` (TASK-1120).
- ~~`self.report_generator.generate_ecr_pdf(...)`~~ — out of scope (HTML only).
- ~~A separate `EcrToolkit` class inside `cloudsploit/`~~ — methods live on `CloudSploitToolkit`.
- ~~`from parrot.tools.cloudsploit import EcrCollectionPlan`~~ — public re-export lives in `parrot_tools.cloudsploit` (added by TASK-1124, not yet wired when this task runs unless it does both).
- ~~`SeverityBreakdown` import inside this task~~ — pass a plain dict that matches the schema; the mixin handles conversion (per spec §2 Overview).
- ~~Inspector v2 calls anywhere in this method~~ — Inspector is OUT (spec §1 Non-Goals).

---

## Implementation Notes

### Pattern to Follow

```python
class _CollectEcrInput(BaseModel):
    plan: Optional[str] = Field(
        None,
        description=(
            "Path to a YAML ECR collection plan. When None, falls back to "
            "CloudSploitConfig.ecr_plan_file."
        ),
    )


class _GenerateEcrReportInput(BaseModel):
    output_path: Optional[str] = Field(None, description="...")
    result: Optional[EcrCollectionResult] = Field(None, description="...")


# inside CloudSploitToolkit:

def __init__(self, config=None, **kwargs):
    self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
    super().__init__(**kwargs)
    self.config = config or CloudSploitConfig()
    self.executor = CloudSploitExecutor(self.config)
    self.parser = ScanResultParser()
    self.report_generator = ReportGenerator()
    self.comparator = ScanComparator()
    self._last_result: Optional[ScanResult] = None

    # ECR additions
    self._ecr_aws = AWSInterface(region_name=self.config.aws_region)
    self.ecr_collector = EcrScanCollector(aws=self._ecr_aws)
    self._last_ecr_result: Optional[EcrCollectionResult] = None


def _resolve_ecr_plan(self, per_call: Optional[str]) -> Optional[str]:
    """Resolve effective ECR plan path with per-call > field precedence.

    Mirrors `_resolve_config` (toolkit.py:75-101).
    """
    effective = per_call if per_call is not None else self.config.ecr_plan_file
    if (
        per_call is not None
        and self.config.ecr_plan_file is not None
        and per_call != self.config.ecr_plan_file
    ):
        self.logger.debug(
            "Per-call ecr_plan=%s overrides CloudSploitConfig.ecr_plan_file=%s",
            per_call, self.config.ecr_plan_file,
        )
    if effective:
        self.logger.debug("Effective ECR plan: %s", effective)
    return effective


async def _persist_after_ecr_scan(self, result: EcrCollectionResult) -> None:
    """Side-effect: persist to catalog when deps wired (no-op otherwise)."""
    severity_summary = {sev.value: 0 for sev in EcrSeverity}
    for repo in result.repos:
        for sev, n in repo.counts.items():
            severity_summary[sev.value] += n

    await self._persist_report(
        scanner="ecr-image-scan",
        framework=None,
        provider="aws",
        scope={
            "account_id": getattr(self.config, "aws_account_id", None),
            "region": result.region,
        },
        content=result.model_dump_json().encode("utf-8"),
        severity_summary=severity_summary,
        top_findings=[],   # parser registry deferred; pass empty
    )


@tool_schema(_CollectEcrInput)
async def collect_ecr_findings(
    self, plan: Optional[str] = None,
) -> EcrCollectionResult:
    """Aggregate ECR vulnerability scan findings across many repos."""
    effective = self._resolve_ecr_plan(plan)
    if not effective:
        raise ValueError(
            "No ECR collection plan configured. Pass plan=<path.yaml> or "
            "set CloudSploitConfig.ecr_plan_file."
        )
    plan_model = EcrCollectionPlan.from_yaml(effective)
    result = await self.ecr_collector.collect(plan_model)
    self._last_ecr_result = result
    await self._persist_after_ecr_scan(result)
    return result


@tool_schema(_GenerateEcrReportInput)
async def generate_ecr_report(
    self,
    output_path: Optional[str] = None,
    result: Optional[EcrCollectionResult] = None,
) -> str:
    """Render the interactive HTML ECR vulnerability report."""
    target = result or self._last_ecr_result
    if target is None:
        raise ValueError(
            "No ECR collection available. Call collect_ecr_findings() first "
            "or pass result=<EcrCollectionResult>."
        )
    if not output_path:
        ts = target.generated_at.strftime("%Y%m%d_%H%M%S")
        base_dir = self.config.results_dir or "/tmp"
        output_path = str(Path(base_dir) / f"ecr_report_{ts}.html")
    return await self.report_generator.generate_ecr_html(
        target, output_path=output_path,
    )
```

### Key Constraints

- The new `AWSInterface` instance lives on `self._ecr_aws` (not exposed
  via the toolkit's tool surface — leading underscore).
- DO NOT reorder the existing `__init__` body or change persistence
  kwarg handling (`pop_persistence_kwargs(kwargs)` MUST stay BEFORE
  `super().__init__(**kwargs)` — spec §7).
- `@tool_schema` Input models live as private classes (leading underscore)
  inside the toolkit module — do NOT export them.
- `_persist_report` is async — call with `await`.
- `tool_prefix` is not set on `CloudSploitToolkit`; method names become
  tool names verbatim. So both new methods auto-expose as
  `collect_ecr_findings` and `generate_ecr_report` tools.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:34-46`
  — existing `__init__` pattern to extend.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:49-73`
  — `_persist_after_scan` as the model for `_persist_after_ecr_scan`.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:75-101`
  — `_resolve_config` as the model for `_resolve_ecr_plan`.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:215-247`
  — `generate_report` as the model for `generate_ecr_report` (auto-path,
  delegation to report_generator).

---

## Acceptance Criteria

- [ ] `CloudSploitToolkit()` instantiates without arguments and exposes
      `self.ecr_collector` and `self._last_ecr_result = None`.
- [ ] `collect_ecr_findings(plan="/tmp/plan.yaml")` calls the collector
      with the loaded `EcrCollectionPlan` and returns its result.
- [ ] `collect_ecr_findings()` with both `plan=None` and
      `config.ecr_plan_file=None` raises `ValueError`.
- [ ] Precedence: when `plan` and `config.ecr_plan_file` are both set,
      the per-call `plan` wins and a DEBUG log is emitted (mirrors
      `_resolve_config` behaviour).
- [ ] After a successful `collect_ecr_findings()`,
      `self._last_ecr_result` is set.
- [ ] `generate_ecr_report()` (no args) uses `self._last_ecr_result`.
- [ ] `generate_ecr_report()` raises `ValueError` when neither
      `result` nor `_last_ecr_result` is available.
- [ ] When `file_manager` and `report_store` kwargs are present,
      `collect_ecr_findings` invokes the persistence mixin with
      `scanner="ecr-image-scan"`, `provider="aws"`, and a `scope` dict
      containing the region.
- [ ] When persistence kwargs are absent, `collect_ecr_findings` runs
      without raising and makes no persistence call.
- [ ] No regression in existing `run_scan` / `run_compliance_scan` tests.
- [ ] `pytest packages/ai-parrot-tools/tests/cloudsploit/ -v` passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`
      passes.
- [ ] `grep -rn 'inspector2\|inspector_' packages/ai-parrot-tools/src/parrot_tools/cloudsploit/`
      returns zero hits (Inspector v2 is out of scope).

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/cloudsploit/test_toolkit.py (additions)
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.cloudsploit import CloudSploitConfig, CloudSploitToolkit
from parrot_tools.cloudsploit.models import (
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrRepoFindings,
    EcrRepoPlan,
    EcrSeverity,
)


@pytest.fixture
def fake_result():
    return EcrCollectionResult(
        generated_at=datetime.now(tz=timezone.utc),
        region="us-east-2",
        repos=[
            EcrRepoFindings(
                repo="alpha", tag="staging",
                counts={EcrSeverity.CRITICAL: 1},
                findings=[],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_collect_ecr_findings_no_plan_raises():
    tk = CloudSploitToolkit()
    with pytest.raises(ValueError, match="No ECR collection plan"):
        await tk.collect_ecr_findings()


@pytest.mark.asyncio
async def test_collect_ecr_findings_uses_plan_arg(tmp_path, fake_result):
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        "region: us-east-2\n"
        "repos:\n  - {name: alpha, tags: [staging]}\n"
    )
    tk = CloudSploitToolkit()
    with patch.object(
        tk.ecr_collector, "collect", new=AsyncMock(return_value=fake_result),
    ) as collect_mock:
        out = await tk.collect_ecr_findings(plan=str(plan_path))
    collect_mock.assert_awaited_once()
    assert out is fake_result
    assert tk._last_ecr_result is fake_result


@pytest.mark.asyncio
async def test_per_call_overrides_config_field(tmp_path, fake_result, caplog):
    plan_a = tmp_path / "a.yaml"
    plan_a.write_text("region: x\nrepos:\n  - {name: a, tags: [t]}\n")
    plan_b = tmp_path / "b.yaml"
    plan_b.write_text("region: y\nrepos:\n  - {name: b, tags: [t]}\n")

    cfg = CloudSploitConfig(ecr_plan_file=str(plan_a))
    tk = CloudSploitToolkit(config=cfg)
    with patch.object(
        tk.ecr_collector, "collect", new=AsyncMock(return_value=fake_result),
    ), caplog.at_level("DEBUG", logger="CloudSploitToolkit"):
        await tk.collect_ecr_findings(plan=str(plan_b))
    assert "overrides" in caplog.text


@pytest.mark.asyncio
async def test_generate_ecr_report_uses_last_result(fake_result, tmp_path):
    tk = CloudSploitToolkit(config=CloudSploitConfig(results_dir=str(tmp_path)))
    tk._last_ecr_result = fake_result
    with patch.object(
        tk.report_generator, "generate_ecr_html",
        new=AsyncMock(return_value=str(tmp_path / "out.html")),
    ) as render_mock:
        out = await tk.generate_ecr_report()
    render_mock.assert_awaited_once()
    assert out.endswith(".html")


@pytest.mark.asyncio
async def test_generate_ecr_report_no_result_raises():
    tk = CloudSploitToolkit()
    with pytest.raises(ValueError, match="No ECR collection"):
        await tk.generate_ecr_report()


@pytest.mark.asyncio
async def test_persists_when_deps_present(tmp_path, fake_result):
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("region: r\nrepos:\n  - {name: a, tags: [t]}\n")
    fake_store = MagicMock()
    fake_store.save_report = AsyncMock(return_value=None)
    fake_fm = MagicMock()

    tk = CloudSploitToolkit(file_manager=fake_fm, report_store=fake_store)
    with patch.object(
        tk.ecr_collector, "collect", new=AsyncMock(return_value=fake_result),
    ):
        await tk.collect_ecr_findings(plan=str(plan_path))
    fake_store.save_report.assert_awaited()
    args, kwargs = fake_store.save_report.call_args
    ref = args[0] if args else kwargs.get("ref")
    assert ref.scanner == "ecr-image-scan"
    assert ref.provider == "aws"
    assert ref.scope["region"] == "us-east-2"


@pytest.mark.asyncio
async def test_no_op_when_deps_absent(tmp_path, fake_result):
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("region: r\nrepos:\n  - {name: a, tags: [t]}\n")
    tk = CloudSploitToolkit()  # no file_manager / report_store
    with patch.object(
        tk.ecr_collector, "collect", new=AsyncMock(return_value=fake_result),
    ):
        # Should not raise.
        out = await tk.collect_ecr_findings(plan=str(plan_path))
    assert out is fake_result
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/cloudsploit-ecr.spec.md` (§2 Overview, §3 Module 6, §6 Codebase Contract).
2. Verify dependencies: TASK-1118 (models), TASK-1120 (collector), and TASK-1122 (renderer) must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract: `read` `cloudsploit/toolkit.py:1-101` and `security/persistence.py:77-150`.
4. Extend `CloudSploitToolkit` per Implementation Notes. Preserve every existing public method.
5. Write the 7 unit tests listed in Test Specification.
6. Run `pytest packages/ai-parrot-tools/tests/cloudsploit/ -v` (full suite, including regression).
7. Run `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py`.
8. Run `grep -rn 'inspector2\|inspector_' packages/ai-parrot-tools/src/parrot_tools/cloudsploit/` → must be empty.
9. Move this file to `sdd/tasks/completed/`.
10. Update `sdd/tasks/index/cloudsploit-ecr.json` task status to `done`.
11. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Added `collect_ecr_findings` and `generate_ecr_report` public async methods to `CloudSploitToolkit`. Added `_CollectEcrInput` and `_GenerateEcrReportInput` Pydantic models. Updated `test_tool_count` from 6 to 8 (2 new ECR tools). All 7 new ECR tests pass. Pre-existing 5 executor/model failures (aws_region env default) are unrelated to this task.
**Deviations from spec**: none
