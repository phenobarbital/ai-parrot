---
type: Wiki Overview
title: 'TASK-1122: `ReportGenerator.generate_ecr_html` — render the template'
id: doc:sdd-tasks-completed-task-1122-ecr-report-generator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5** of the spec (`sdd/specs/cloudsploit-ecr.spec.md`
  §3).
relates_to:
- concept: mod:parrot_tools.cloudsploit
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.reports
  rel: mentions
---

# TASK-1122: `ReportGenerator.generate_ecr_html` — render the template

**Feature**: FEAT-165 — CloudSploit ECR Image-Scan Collector & Interactive Report
**Spec**: `sdd/specs/cloudsploit-ecr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1118, TASK-1121
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec (`sdd/specs/cloudsploit-ecr.spec.md` §3).

Adds the async method that takes an `EcrCollectionResult`, computes the
view-model fields the template needs (sorting, slicing, severity-colour
resolution), and writes / returns the rendered HTML.

This task owns the **business logic** that keeps the Jinja2 template in
TASK-1121 simple — sorting, grouping by package, picking worst-severity
per package, truncating descriptions.

---

## Scope

- Add `async def generate_ecr_html(self, result, output_path=None) -> str`
  to `ReportGenerator` in `cloudsploit/reports.py`.
- Compute the view-model from the `EcrCollectionResult`:
  - **Global totals** across all repos in
    `total_counts: dict[str, int]`.
  - **Sort repos**: `navigator-api-tf` pinned first; other `navigator-*`
    second, sorted by CRITICAL→HIGH→MEDIUM→LOW descending; everything else
    third, alphabetic.
  - **Group findings by package**: key is `(package_name, package_version)`;
    each group carries the list of CVEs sorted by severity (CRITICAL first).
  - **Sort packages** within a repo by worst-severity (CRITICAL → LOW).
  - **Worst severity per package**: minimum SEV_ORDER across its CVEs.
  - **Boolean flags** for template:
    `has_critical/has_high/has_medium/has_low`, `repo_open`, `pkg_open`.
  - **Severity colours**: pre-resolved hex bg / text per CVE.
  - **Description truncation**: cap at 180 chars + `…`.
  - **Scan time format**: e.g.
    `result.repos[i].scan_time.strftime("%Y-%m-%d %H:%M")`, or `"N/A"`
    when None.
- Render `ecr_scan_report.html` via the existing `self.env` Jinja2 env
  (reports.py:28-32). DO NOT create a new env.
- If `output_path` is given, write the file (`mkdir parents`) and return
  the path. Otherwise return the rendered HTML string.
- Add 4 unit tests + 1 integration test (see §Test Specification).

**NOT in scope**: PDF rendering (out of v1), the `xhtml2pdf` path (won't
work with the template), exposing the method via `CloudSploitToolkit`
(TASK-1123).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py` | MODIFY | Add `generate_ecr_html` method and supporting helpers |
| `packages/ai-parrot-tools/tests/cloudsploit/test_ecr_reports.py` | CREATE | Unit + integration tests |
| `packages/ai-parrot-tools/tests/cloudsploit/fixtures/ecr_collection_sample.json` | CREATE | Small `EcrCollectionResult` fixture for the integration test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already at top of reports.py — re-use, do NOT re-import.
import io
from pathlib import Path
from typing import Optional

from navconfig.logging import logging
from jinja2 import Environment, FileSystemLoader
# Verified at: cloudsploit/reports.py:6-11

# New imports for ecr method
from .models import EcrCollectionResult, EcrSeverity
# Verified after TASK-1118 ships.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py
class ReportGenerator:                                  # line 19
    def __init__(self):                                 # line 26
        self.logger = logging.getLogger(self.__class__.__name__)
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(                         # line 29-32
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )

    async def generate_html(
        self, result: ScanResult,
        output_path: Optional[str] = None,
        max_findings: int = DEFAULT_MAX_FINDINGS,
    ) -> str: ...                                       # line 63

    async def generate_comparison_html(...) -> str: ... # line 134
```

### Does NOT Exist
- ~~`from .ecr_collector import EcrScanCollector`~~ — the renderer does
  NOT call the collector. Inputs are pre-built `EcrCollectionResult`.
- ~~`xhtml2pdf` path for ECR~~ — HTML only in v1 (spec §1 Non-Goals).
- ~~A new `ReportGenerator.__init__` or replacement env~~ — reuse `self.env`.
- ~~`from parrot_tools.cloudsploit.templates import ecr_scan_report`~~ —
  templates are loaded by name via `self.env.get_template("ecr_scan_report.html")`,
  not imported.

---

## Implementation Notes

### Pattern to Follow

```python
SEV_ORDER = {
    EcrSeverity.CRITICAL: 1,
    EcrSeverity.HIGH: 2,
    EcrSeverity.MEDIUM: 3,
    EcrSeverity.LOW: 4,
    EcrSeverity.INFORMATIONAL: 5,
    EcrSeverity.UNTRIAGED: 6,
}

SEV_COLOR = {
    EcrSeverity.CRITICAL: ("#dc3545", "white"),
    EcrSeverity.HIGH: ("#fd7e14", "white"),
    EcrSeverity.MEDIUM: ("#ffc107", "#000"),
    EcrSeverity.LOW: ("#6c757d", "white"),
    EcrSeverity.INFORMATIONAL: ("#adb5bd", "white"),
    EcrSeverity.UNTRIAGED: ("#adb5bd", "white"),
}


def _repo_priority(name: str) -> int:
    if name == "navigator-api-tf":
        return 0
    if name.startswith("navigator-"):
        return 1
    return 2


async def generate_ecr_html(
    self,
    result: EcrCollectionResult,
    output_path: Optional[str] = None,
) -> str:
    """Render an interactive HTML vulnerability report.

    Args:
        result: Collected ECR scan findings.
        output_path: File path to write to. When None, returns the HTML string.

    Returns:
        Rendered HTML string when output_path is None, otherwise the
        absolute path of the written file.
    """
    template = self.env.get_template("ecr_scan_report.html")

    # Global totals
    total_counts: dict[str, int] = {}
    for repo in result.repos:
        for sev, n in repo.counts.items():
            total_counts[sev.value] = total_counts.get(sev.value, 0) + n

    # Sort repos: navigator-api-tf first, navigator-* by severity, others alpha
    def _repo_sort_key(repo) -> tuple:
        return (
            _repo_priority(repo.repo),
            -repo.counts.get(EcrSeverity.CRITICAL, 0),
            -repo.counts.get(EcrSeverity.HIGH, 0),
            -repo.counts.get(EcrSeverity.MEDIUM, 0),
            -repo.counts.get(EcrSeverity.LOW, 0),
            repo.repo,
        )
    repos_sorted_models = sorted(result.repos, key=_repo_sort_key)

    # Build view-model dicts
    repos_sorted = [self._build_repo_view(r) for r in repos_sorted_models]

    html = template.render(
        generated_at=result.generated_at.isoformat(),
        region=result.region,
        total_counts=total_counts,
        repo_count=len(result.repos),
        repos_sorted=repos_sorted,
    )
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(html, encoding="utf-8")
        self.logger.info("ECR HTML report saved to %s", output_path)
        return output_path
    return html


def _build_repo_view(self, repo) -> dict:
    """Build per-repo view-model: groups CVEs by package, sorts, etc."""
    # 1. Group findings by (package_name, package_version)
    # 2. For each group, compute worst severity and sort CVEs by severity
    # 3. Sort groups by worst severity
    # 4. Pre-truncate descriptions to 180 chars
    # 5. Pre-resolve severity colours
    # Return dict with keys consumed by the template.
    ...
```

### Key Constraints

- `repo.counts` keys are `EcrSeverity` enum members (per TASK-1118). To
  access by string key inside Jinja, expose strings in the view-model.
- Description truncation must be on the FINDING-level, not the group.
- Use `repo.scan_time and repo.scan_time.strftime(...)` to handle None.
- Do NOT modify the existing `generate_html`, `generate_pdf`,
  `generate_comparison_html`, or `generate_comparison_pdf` methods.
- Async signature even though there is no `await` inside — match the
  toolkit's async convention.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py:63-98`
  — existing `generate_html` pattern (Jinja render + optional write).
- `sdd/state/FEAT-165/source.md` (script 2) — the sorting & grouping
  algorithm to port to Python.

---

## Acceptance Criteria

- [ ] `await report_generator.generate_ecr_html(result)` returns a
      non-empty HTML string when `output_path=None`.
- [ ] Same call with `output_path="/tmp/out.html"` writes the file
      (creates parent dirs) and returns the path.
- [ ] Repo ordering: with `[other-repo, navigator-front-tf, navigator-api-tf]`
      in input, the rendered HTML shows `navigator-api-tf` first.
- [ ] Repo secondary ordering: two `navigator-*` repos with different
      CRITICAL counts are ordered with the higher-CRITICAL repo first.
- [ ] Findings with the same `(package_name, package_version)` are grouped
      into a single package block in the output.
- [ ] CVE description truncation: a 1000-char description renders as
      180 chars + `…` in the table.
- [ ] Special chars in CVE description are HTML-escaped (a `<script>` tag
      in the description appears as `&lt;script&gt;`).
- [ ] Smoke: rendered output contains the substrings
      `"navigator-api-tf"`, `"CRITICAL"`, and at least one CVE name from
      the fixture.
- [ ] `pytest packages/ai-parrot-tools/tests/cloudsploit/test_ecr_reports.py -v`
      passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py`
      passes.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/cloudsploit/test_ecr_reports.py
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot_tools.cloudsploit.models import (
    EcrCollectionResult,
    EcrRepoFindings,
    EcrScanFinding,
    EcrSeverity,
)
from parrot_tools.cloudsploit.reports import ReportGenerator


@pytest.fixture
def sample_result():
    f = EcrScanFinding(
        name="CVE-2024-0001",
        severity=EcrSeverity.CRITICAL,
        description="boom " * 100,
        uri="https://example/cve",
        package_name="openssl",
        package_version="1.1.1",
        fixed_in_versions="1.1.1w",
        cvss="9.8",
    )
    return EcrCollectionResult(
        generated_at=datetime.now(tz=timezone.utc),
        region="us-east-2",
        repos=[
            EcrRepoFindings(
                repo="navigator-front-tf",
                tag="staging",
                counts={EcrSeverity.CRITICAL: 1},
                findings=[f],
            ),
            EcrRepoFindings(
                repo="navigator-api-tf",
                tag="staging",
                counts={EcrSeverity.HIGH: 1},
                findings=[
                    f.model_copy(update={
                        "name": "CVE-2024-0002",
                        "severity": EcrSeverity.HIGH,
                    }),
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_returns_html_string_when_no_path(sample_result):
    rg = ReportGenerator()
    out = await rg.generate_ecr_html(sample_result)
    assert isinstance(out, str)
    assert "<html" in out.lower()


@pytest.mark.asyncio
async def test_writes_file_when_path_given(sample_result, tmp_path):
    rg = ReportGenerator()
    out = await rg.generate_ecr_html(
        sample_result, output_path=str(tmp_path / "deep" / "report.html"),
    )
    assert Path(out).is_file()
    assert "navigator-api-tf" in Path(out).read_text()


@pytest.mark.asyncio
async def test_navigator_api_pinned_first(sample_result):
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(sample_result)
    api_pos = html.find("navigator-api-tf")
    front_pos = html.find("navigator-front-tf")
    assert api_pos != -1 and front_pos != -1
    assert api_pos < front_pos


@pytest.mark.asyncio
async def test_description_truncated_to_180(sample_result):
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(sample_result)
    # `"boom " * 100` → 500 chars; renderer truncates to 180 + ellipsis.
    assert "boom boom" in html  # part of the truncated description
    # The full original 500-char description should NOT appear:
    assert ("boom " * 100) not in html


@pytest.mark.asyncio
async def test_html_escapes_script_in_description(sample_result):
    sample_result.repos[0].findings[0].description = "<script>alert(1)</script>"
    rg = ReportGenerator()
    html = await rg.generate_ecr_html(sample_result)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/cloudsploit-ecr.spec.md` (§2 Overview, §3 Module 5).
2. Verify dependencies: TASK-1118 (models) and TASK-1121 (template) must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract: `read` `cloudsploit/reports.py:1-100` to confirm the env shape.
4. Implement `generate_ecr_html` + helpers following Implementation Notes.
5. Write the 5 unit tests above.
6. Save one minimal `EcrCollectionResult` fixture as JSON for cross-task reuse.
7. Run `pytest packages/ai-parrot-tools/tests/cloudsploit/test_ecr_reports.py -v`.
8. Run `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py`.
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
