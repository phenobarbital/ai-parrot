---
type: Wiki Overview
title: 'TASK-1120: `EcrScanCollector` — multi-repo / tag-priority loop'
id: doc:sdd-tasks-completed-task-1120-ecr-scan-collector-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of the spec (`sdd/specs/cloudsploit-ecr.spec.md`
  §3).
relates_to:
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot_tools.aws.ecr
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.ecr_collector
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
---

# TASK-1120: `EcrScanCollector` — multi-repo / tag-priority loop

**Feature**: FEAT-165 — CloudSploit ECR Image-Scan Collector & Interactive Report
**Spec**: `sdd/specs/cloudsploit-ecr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1118, TASK-1119
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (`sdd/specs/cloudsploit-ecr.spec.md` §3).

This is the core orchestration logic that was previously the JS script
`collect_ecr_findings.js`. For each repo in the plan, try its tags in
priority order; stop at the first tag whose image has scan findings;
emit a unified `EcrCollectionResult`.

The Python port improves over the JS by using bounded concurrency
(`asyncio.Semaphore`) — the JS is strictly sequential. ECR has a per-account
rate limit on `describe_image_scan_findings`, so concurrency MUST be capped
by the plan, never raw `asyncio.gather`.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_collector.py`.
- Implement `EcrScanCollector` class with:
  - `__init__(self, aws: AWSInterface)`.
  - `async def collect(self, plan: EcrCollectionPlan) -> EcrCollectionResult`.
- Inside `collect`:
  - Create an `asyncio.Semaphore(plan.concurrency)`.
  - Schedule one coroutine per repo. Each coroutine iterates `repo.tags`
    sequentially (first-match-wins) using the semaphore around the actual
    ECR call.
  - Use the `ECRToolkit` wrapper from TASK-1119
    (`aws_ecr_get_image_scan_findings(repo, tag, include_attributes=True)`).
  - When the wrapper returns `scan_status == "NOT_FOUND"` (or 0 findings),
    treat as "try next tag".
  - When ALL tags for a repo fail, record an entry in
    `result.skipped` (`[{"repo": ..., "reason": "..."}]`).
- Build `EcrScanFinding` from the wrapper output:
  - Parse `attributes[]` once per finding into a dict
    `{a["key"]: a["value"] for a in attributes}`.
  - Map: `package_name`, `package_version`, `fixed_in_versions`.
  - CVSS preference: `CVSS4_SCORE` first, then `CVSS3_SCORE`, else `None`.
  - `severity` → `EcrSeverity(raw_str)`; unknown values map to
    `EcrSeverity.UNTRIAGED` with a warning log.
- Build `EcrRepoFindings` with `counts: dict[EcrSeverity, int]` derived
  from the wrapper's `severity_counts`. Missing severities are absent
  (do not insert zeros).
- Build `EcrCollectionResult` with `generated_at = datetime.now(tz=timezone.utc)`,
  `region = plan.region`, `repos = [...]`, `skipped = [...]`.

**NOT in scope**: persistence (lives in TASK-1123), report rendering
(TASK-1122), exposing the collector via `CloudSploitToolkit` (TASK-1123),
exports in `__init__.py` (TASK-1124).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_collector.py` | CREATE | `EcrScanCollector` class |
| `packages/ai-parrot-tools/tests/cloudsploit/test_ecr_collector.py` | CREATE | Unit tests covering first-match-wins, fallback, concurrency, attribute parsing |
| `packages/ai-parrot-tools/tests/cloudsploit/fixtures/ecr_describe_findings_sample.json` | CREATE | Single anonymised ECR response (with `attributes[]`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from parrot.interfaces.aws import AWSInterface
# Verified at: packages/ai-parrot/src/parrot/interfaces/aws.py:22

from parrot_tools.aws.ecr import ECRToolkit
# Verified at: packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:66

from parrot_tools.cloudsploit.models import (
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrRepoFindings,
    EcrRepoPlan,
    EcrScanFinding,
    EcrSeverity,
)
# All created by TASK-1118 — verify before use.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/aws.py
class AWSInterface:
    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        credentials: Optional[dict] = None,
        **kwargs,
    ): ...                                                # line 35

    @asynccontextmanager
    async def client(
        self, service_name: str, **kwargs
    ) -> AsyncIterator[Any]: ...                          # line 106

# packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py
class ECRToolkit(AbstractToolkit):
    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ): ...                                                # line 76

    # After TASK-1119 is complete, the method takes include_attributes:
    async def aws_ecr_get_image_scan_findings(
        self,
        repository_name: str,
        image_tag: str = "latest",
        include_attributes: bool = False,    # ← added by TASK-1119
    ) -> Dict[str, Any]: ...                              # line 188
```

### Does NOT Exist
- ~~`asyncio.gather(*tasks)` unbounded fan-out~~ — MUST use `asyncio.Semaphore`.
- ~~`AWSInterface.session` as a public attr~~ — use the `client()` context manager. The session attribute exists but is implementation detail.
- ~~`ECRToolkit.collect_repos()` or any aggregation method~~ — this task is the first to add aggregation.
- ~~A direct `aioboto3.Session(...)` instantiation~~ — credentials must flow through `AWSInterface` (auth invariant from spec §1 Goals).
- ~~`yield` / async generator for per-repo emit~~ — return a fully-materialised `EcrCollectionResult`. Streaming is not in scope.
- ~~Retry logic on `ThrottlingException`~~ — out of scope. Log and surface; let the caller decide (per spec §7 Known Risks).

---

## Implementation Notes

### Pattern to Follow

```python
class EcrScanCollector:
    """Aggregate ECR vulnerability scan findings across many repos."""

    def __init__(self, aws: AWSInterface) -> None:
        self.aws = aws
        self.logger = logging.getLogger(self.__class__.__name__)

    async def collect(self, plan: EcrCollectionPlan) -> EcrCollectionResult:
        sem = asyncio.Semaphore(plan.concurrency)
        # ECRToolkit wraps describe_image_scan_findings via AWSInterface;
        # reuse it rather than calling boto3 directly.
        ecr = ECRToolkit.__new__(ECRToolkit)
        ecr.aws = self.aws  # bypass constructor — we supply the AWSInterface

        repo_coros = [
            self._collect_one_repo(ecr, repo, sem) for repo in plan.repos
        ]
        results = await asyncio.gather(*repo_coros, return_exceptions=False)

        found, skipped = [], []
        for repo, outcome in zip(plan.repos, results):
            if isinstance(outcome, EcrRepoFindings):
                found.append(outcome)
            else:
                skipped.append({"repo": repo.name, "reason": outcome})

        return EcrCollectionResult(
            generated_at=datetime.now(tz=timezone.utc),
            region=plan.region,
            repos=found,
            skipped=skipped,
        )

    async def _collect_one_repo(
        self, ecr: ECRToolkit, repo: EcrRepoPlan, sem: asyncio.Semaphore,
    ) -> EcrRepoFindings | str:
        """Returns EcrRepoFindings on first match, or a skip-reason string."""
        for tag in repo.tags:
            async with sem:
                self.logger.debug("Probing %s:%s", repo.name, tag)
                payload = await ecr.aws_ecr_get_image_scan_findings(
                    repo.name, tag, include_attributes=True,
                )
            if payload.get("scan_status") == "NOT_FOUND":
                continue
            if not payload.get("findings"):
                continue
            return self._build_repo_findings(repo.name, tag, payload)
        return "no tag returned scan findings"

    def _build_repo_findings(
        self, repo: str, tag: str, payload: dict[str, Any],
    ) -> EcrRepoFindings:
        ...
        # Parse attributes once per finding via dict-from-list-of-pairs.
        # Map CVSS preference: CVSS4_SCORE > CVSS3_SCORE > None.
        # Unknown severity → EcrSeverity.UNTRIAGED with warning log.
        # Return EcrRepoFindings(...).
```

### Key Constraints

- `asyncio.Semaphore(plan.concurrency)` MUST wrap the actual ECR call
  (inside `_collect_one_repo`), not the whole repo coroutine — otherwise
  the per-repo tag fallback inflates concurrency artificially.
- `EcrSeverity(value)` raises `ValueError` for unknown strings — catch
  and remap to `EcrSeverity.UNTRIAGED`, log a warning. Do not crash.
- Bypass `ECRToolkit.__init__` when reusing `self.aws` — the constructor
  builds a fresh `AWSInterface`, but the collector already has one.
  (See pattern above: `ECRToolkit.__new__(ECRToolkit); tk.aws = self.aws`.)
- `counts` dict keys MUST be `EcrSeverity` enum members, not raw strings.
- Wall-time: `datetime.now(tz=timezone.utc)` — never naive `datetime.now()`.
- Logger name: `EcrScanCollector` (set via `self.__class__.__name__`).

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py:188-240` —
  the wrapper this collector calls (after TASK-1119).
- `packages/ai-parrot/src/parrot/interfaces/aws.py:22-122` —
  `AWSInterface` lifecycle.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:38-62`
  — example of a collaborator class that takes config in `__init__` and
  exposes async methods. Same overall shape applies here (minus the
  Docker complexity).

---

## Acceptance Criteria

- [ ] `from parrot_tools.cloudsploit.ecr_collector import EcrScanCollector` works.
- [ ] First-match-wins per repo: if `tags=["staging", "production"]` and
      staging returns findings, production is NEVER queried.
- [ ] Fallback on `ScanNotFoundException`: when the first tag returns
      `scan_status="NOT_FOUND"`, the next tag is tried.
- [ ] All-tags-fail recorded: when every tag returns NOT_FOUND or zero
      findings, the repo appears in `result.skipped` (not in `result.repos`).
- [ ] Bounded concurrency: with `plan.concurrency=2`, the number of
      in-flight `describe_image_scan_findings` calls NEVER exceeds 2.
      (Verify with a counting mock.)
- [ ] Attribute parsing: `package_name`, `package_version`,
      `fixed_in_versions` propagate to `EcrScanFinding`.
- [ ] CVSS preference: when a finding has both `CVSS4_SCORE=9.8` and
      `CVSS3_SCORE=8.0`, `EcrScanFinding.cvss == "9.8"`.
- [ ] Unknown severity: a finding with `severity="WEIRD"` becomes
      `EcrSeverity.UNTRIAGED` and a warning is logged.
- [ ] `generated_at` is timezone-aware UTC.
- [ ] `pytest packages/ai-parrot-tools/tests/cloudsploit/test_ecr_collector.py -v`
      passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_collector.py`
      passes.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/cloudsploit/test_ecr_collector.py
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.cloudsploit.ecr_collector import EcrScanCollector
from parrot_tools.cloudsploit.models import (
    EcrCollectionPlan,
    EcrRepoPlan,
    EcrSeverity,
)


@pytest.fixture
def sample_payload():
    """One ECR finding with attributes."""
    return {
        "repository_name": "alpha",
        "image_tag": "staging",
        "scan_status": "COMPLETE",
        "severity_counts": {"CRITICAL": 1},
        "findings": [
            {
                "name": "CVE-2024-0001",
                "severity": "CRITICAL",
                "description": "...",
                "uri": "https://example/cve",
                "attributes": [
                    {"key": "package_name", "value": "openssl"},
                    {"key": "package_version", "value": "1.1.1"},
                    {"key": "fixed_in_versions", "value": "1.1.1w"},
                    {"key": "CVSS3_SCORE", "value": "8.0"},
                    {"key": "CVSS4_SCORE", "value": "9.8"},
                ],
            },
        ],
        "findings_count": 1,
        "total_vulnerabilities": 1,
    }


@pytest.fixture
def not_found():
    return {"scan_status": "NOT_FOUND", "findings": []}


@pytest.mark.asyncio
async def test_first_match_wins(sample_payload, not_found):
    wrapper = AsyncMock()
    wrapper.side_effect = [not_found, sample_payload]
    collector = EcrScanCollector(aws=MagicMock())

    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        wrapper,
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            concurrency=2,
            repos=[EcrRepoPlan(name="alpha", tags=["dev", "staging", "prod"])],
        )
        result = await collector.collect(plan)

    # Called exactly twice: dev (NOT_FOUND) then staging (hit) — prod never queried.
    assert wrapper.await_count == 2
    assert result.repos[0].tag == "staging"


@pytest.mark.asyncio
async def test_all_tags_fail_goes_to_skipped(not_found):
    wrapper = AsyncMock(return_value=not_found)
    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        wrapper,
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="zeta", tags=["a", "b"])],
        )
        result = await collector.collect(plan)
    assert result.repos == []
    assert result.skipped[0]["repo"] == "zeta"


@pytest.mark.asyncio
async def test_cvss_v4_preferred_over_v3(sample_payload):
    wrapper = AsyncMock(return_value=sample_payload)
    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        wrapper,
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="alpha", tags=["staging"])],
        )
        result = await collector.collect(plan)
    f = result.repos[0].findings[0]
    assert f.cvss == "9.8"
    assert f.package_name == "openssl"
    assert f.fixed_in_versions == "1.1.1w"


@pytest.mark.asyncio
async def test_bounded_concurrency(sample_payload):
    inflight = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_call(*args, **kwargs):
        nonlocal inflight, peak
        async with lock:
            inflight += 1
            peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        async with lock:
            inflight -= 1
        return sample_payload

    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        side_effect=fake_call,
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            concurrency=2,
            repos=[EcrRepoPlan(name=f"r{i}", tags=["staging"]) for i in range(8)],
        )
        await collector.collect(plan)
    assert peak <= 2


@pytest.mark.asyncio
async def test_unknown_severity_maps_to_untriaged(sample_payload, caplog):
    sample_payload["findings"][0]["severity"] = "WEIRD"
    wrapper = AsyncMock(return_value=sample_payload)
    collector = EcrScanCollector(aws=MagicMock())
    with patch(
        "parrot_tools.cloudsploit.ecr_collector.ECRToolkit.aws_ecr_get_image_scan_findings",
        wrapper,
    ):
        plan = EcrCollectionPlan(
            region="us-east-2",
            repos=[EcrRepoPlan(name="alpha", tags=["staging"])],
        )
        result = await collector.collect(plan)
    assert result.repos[0].findings[0].severity == EcrSeverity.UNTRIAGED
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/cloudsploit-ecr.spec.md` (§2 Overview, §3 Module 2, §6 Codebase Contract, §7 Known Risks).
2. Verify dependencies: TASK-1118 (models) and TASK-1119 (wrapper flag) must be in `sdd/tasks/completed/` before you start.
3. Verify the Codebase Contract: `read` `parrot/interfaces/aws.py:22-122` and `aws/ecr.py:188-240` (with TASK-1119's changes applied).
4. Implement the collector following the pattern in Implementation Notes.
5. Add the 5 tests in `tests/cloudsploit/test_ecr_collector.py`.
6. Save one anonymised ECR response (including `attributes[]`) as a JSON fixture in `tests/cloudsploit/fixtures/`.
7. Run `pytest packages/ai-parrot-tools/tests/cloudsploit/test_ecr_collector.py -v`.
8. Run `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/ecr_collector.py`.
9. Move this file to `sdd/tasks/completed/`.
10. Update `sdd/tasks/index/cloudsploit-ecr.json` task status to `done`.
11. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
