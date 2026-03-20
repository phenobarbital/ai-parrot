# TASK-045: Report Generator

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-032, TASK-044
**Assigned-to**: claude-session

---

## Context

The Report Generator produces multi-format compliance reports from consolidated scan results. It uses Jinja2 templates for HTML reports and supports PDF generation via WeasyPrint.

Reference: Spec Section 8.2 (Report Generator).

---

## Scope

- Implement `parrot/tools/security/reports/generator.py`
- Create `ReportGenerator` class with:
  - `generate_compliance_report()` — Framework-specific report
  - `generate_executive_summary()` — High-level summary
  - `generate_consolidated_report()` — Full multi-scanner report
  - `export_findings_csv()` — CSV export for audit
- Create Jinja2 templates:
  - `templates/soc2_report.html`
  - `templates/hipaa_report.html`
  - `templates/executive_summary.html`
  - `templates/consolidated_report.html`
- Write unit tests

**NOT in scope**:
- PDF generation (optional WeasyPrint, document as enhancement)
- ComplianceReportToolkit (TASK-046)
- Complex charting (basic HTML tables)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/reports/generator.py` | CREATE | ReportGenerator class |
| `parrot/tools/security/reports/templates/base.html` | CREATE | Base HTML template |
| `parrot/tools/security/reports/templates/soc2_report.html` | CREATE | SOC2 report |
| `parrot/tools/security/reports/templates/hipaa_report.html` | CREATE | HIPAA report |
| `parrot/tools/security/reports/templates/executive_summary.html` | CREATE | Executive summary |
| `parrot/tools/security/reports/templates/consolidated_report.html` | CREATE | Full report |
| `parrot/tools/security/reports/__init__.py` | MODIFY | Add generator export |
| `tests/test_report_generator.py` | CREATE | Unit tests |

---

## Implementation Notes

### ReportGenerator Class

```python
# parrot/tools/security/reports/generator.py
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from ..models import ConsolidatedReport, ScanResult, ComplianceFramework
from .compliance_mapper import ComplianceMapper


class ReportGenerator:
    """Multi-format report generator with Jinja2 templates."""

    def __init__(self, output_dir: str = "/tmp/security-reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=True,
        )
        self.compliance_mapper = ComplianceMapper()

    async def generate_compliance_report(
        self,
        consolidated: ConsolidatedReport,
        framework: ComplianceFramework,
        format: str = "html",
        output_path: str | None = None,
        include_evidence: bool = True,
    ) -> str:
        """Generate a compliance report for a specific framework."""
        template = self.env.get_template(f"{framework.value}_report.html")
        coverage = self._calculate_coverage(consolidated, framework)

        html = template.render(
            report=consolidated,
            framework=framework,
            coverage=coverage,
            include_evidence=include_evidence,
            generated_at=datetime.now(),
        )

        output_path = output_path or str(
            self.output_dir / f"{framework.value}_report_{datetime.now():%Y%m%d_%H%M%S}.html"
        )
        Path(output_path).write_text(html)
        return output_path
```

### Base HTML Template Structure

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}Security Report{% endblock %}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1 { color: #333; }
        .summary { background: #f5f5f5; padding: 20px; border-radius: 8px; }
        .critical { color: #d32f2f; }
        .high { color: #f57c00; }
        .medium { color: #fbc02d; }
        .low { color: #388e3c; }
        .pass { color: #4caf50; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background: #333; color: white; }
        tr:nth-child(even) { background: #f9f9f9; }
        .control-section { margin: 30px 0; }
        .finding-card { border: 1px solid #ddd; padding: 15px; margin: 10px 0; }
    </style>
</head>
<body>
    {% block content %}{% endblock %}
    <footer>
        <p>Generated: {{ generated_at.strftime('%Y-%m-%d %H:%M:%S') }}</p>
    </footer>
</body>
</html>
```

### SOC2 Report Template

```html
<!-- templates/soc2_report.html -->
{% extends "base.html" %}
{% block title %}SOC2 Compliance Report{% endblock %}
{% block content %}
<h1>SOC2 Type II Compliance Report</h1>

<div class="summary">
    <h2>Executive Summary</h2>
    <p><strong>Total Findings:</strong> {{ report.total_findings }}</p>
    <p><strong>Coverage:</strong> {{ coverage.coverage_pct | round(1) }}%</p>
    <p><strong>Controls Checked:</strong> {{ coverage.checked_controls }}</p>
    <p><strong>Controls Passed:</strong> {{ coverage.passed_controls }}</p>
</div>

{% for category in ["CC6", "CC7", "CC8"] %}
<div class="control-section">
    <h2>{{ category }}: {{ category_names[category] }}</h2>
    <table>
        <tr>
            <th>Control</th>
            <th>Status</th>
            <th>Findings</th>
        </tr>
        {% for control in controls_by_category[category] %}
        <tr>
            <td>{{ control.id }}: {{ control.name }}</td>
            <td class="{{ control.status }}">{{ control.status | upper }}</td>
            <td>{{ control.finding_count }}</td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endfor %}

{% if include_evidence %}
<h2>Evidence Details</h2>
{% for finding in report.findings %}
<div class="finding-card">
    <h4 class="{{ finding.severity.value | lower }}">{{ finding.title }}</h4>
    <p><strong>Severity:</strong> {{ finding.severity.value }}</p>
    <p><strong>Resource:</strong> {{ finding.resource or "N/A" }}</p>
    <p><strong>Remediation:</strong> {{ finding.remediation or "N/A" }}</p>
</div>
{% endfor %}
{% endif %}

{% endblock %}
```

### Key Constraints

- Use Jinja2 for all templating (no custom HTML generation)
- Templates must be self-contained (inline CSS)
- CSV export must include all finding fields
- Output paths should be auto-generated with timestamps
- Handle empty reports gracefully

---

## Acceptance Criteria

- [ ] `ReportGenerator` generates HTML reports from templates
- [ ] SOC2, HIPAA, executive summary templates created
- [ ] `generate_compliance_report()` produces valid HTML
- [ ] `export_findings_csv()` produces valid CSV
- [ ] Reports include severity breakdown and findings
- [ ] All tests pass: `pytest tests/test_report_generator.py -v`
- [ ] Import works: `from parrot.tools.security.reports import ReportGenerator`

---

## Test Specification

```python
# tests/test_report_generator.py
import pytest
from pathlib import Path
from datetime import datetime
from parrot.tools.security.reports.generator import ReportGenerator
from parrot.tools.security.models import (
    ConsolidatedReport,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    FindingSource,
    SeverityLevel,
    CloudProvider,
    ComplianceFramework,
)


@pytest.fixture
def generator(tmp_path):
    return ReportGenerator(output_dir=str(tmp_path))


@pytest.fixture
def sample_consolidated():
    findings = [
        SecurityFinding(
            id="f1",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.CRITICAL,
            title="Critical IAM Issue",
            check_id="iam_root_mfa",
            remediation="Enable MFA for root account",
        ),
        SecurityFinding(
            id="f2",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="High CVE",
            check_id="CVE-2023-1234",
        ),
        SecurityFinding(
            id="f3",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.PASS,
            title="S3 Encryption Enabled",
            check_id="CKV_AWS_19",
        ),
    ]
    summary = ScanSummary(
        source=FindingSource.PROWLER,
        provider=CloudProvider.AWS,
        total_findings=3,
        critical_count=1,
        high_count=1,
        pass_count=1,
        scan_timestamp=datetime.now(),
    )
    prowler_result = ScanResult(findings=findings[:1], summary=summary)
    trivy_result = ScanResult(findings=findings[1:2], summary=summary)

    return ConsolidatedReport(
        scan_results={"prowler": prowler_result, "trivy": trivy_result},
        total_findings=3,
        findings_by_severity={"CRITICAL": 1, "HIGH": 1, "PASS": 1},
        generated_at=datetime.now(),
    )


class TestReportGeneratorInit:
    def test_creates_output_dir(self, tmp_path):
        """Creates output directory if not exists."""
        output_dir = tmp_path / "reports" / "subdir"
        generator = ReportGenerator(output_dir=str(output_dir))
        assert output_dir.exists()

    def test_loads_templates(self, generator):
        """Jinja2 environment is configured."""
        assert generator.env is not None


class TestGenerateComplianceReport:
    @pytest.mark.asyncio
    async def test_generate_soc2_report(self, generator, sample_consolidated):
        """Generates SOC2 HTML report."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "SOC2" in content
        assert "Critical IAM Issue" in content

    @pytest.mark.asyncio
    async def test_generate_hipaa_report(self, generator, sample_consolidated):
        """Generates HIPAA HTML report."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.HIPAA,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "HIPAA" in content

    @pytest.mark.asyncio
    async def test_custom_output_path(self, generator, sample_consolidated, tmp_path):
        """Respects custom output path."""
        custom_path = str(tmp_path / "custom_report.html")
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            output_path=custom_path,
        )
        assert path == custom_path
        assert Path(path).exists()


class TestGenerateExecutiveSummary:
    @pytest.mark.asyncio
    async def test_generate_executive_summary(self, generator, sample_consolidated):
        """Generates executive summary report."""
        path = await generator.generate_executive_summary(
            sample_consolidated,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "Summary" in content or "Executive" in content


class TestExportFindingsCsv:
    @pytest.mark.asyncio
    async def test_export_csv(self, generator, tmp_path):
        """Exports findings to CSV."""
        findings = [
            SecurityFinding(
                id="f1",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.HIGH,
                title="Test Finding",
                resource="arn:aws:s3:::bucket",
            ),
        ]
        output_path = str(tmp_path / "findings.csv")
        path = await generator.export_findings_csv(findings, output_path)

        assert Path(path).exists()
        content = Path(path).read_text()
        assert "id" in content.lower()
        assert "f1" in content
        assert "HIGH" in content

    @pytest.mark.asyncio
    async def test_export_csv_empty(self, generator, tmp_path):
        """Handles empty findings list."""
        output_path = str(tmp_path / "empty.csv")
        path = await generator.export_findings_csv([], output_path)
        assert Path(path).exists()


class TestReportContent:
    @pytest.mark.asyncio
    async def test_report_includes_severity_breakdown(self, generator, sample_consolidated):
        """Report includes severity statistics."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
        )
        content = Path(path).read_text()
        assert "Critical" in content or "CRITICAL" in content

    @pytest.mark.asyncio
    async def test_report_includes_remediation(self, generator, sample_consolidated):
        """Report includes remediation guidance."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            include_evidence=True,
        )
        content = Path(path).read_text()
        assert "MFA" in content or "remediation" in content.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 8.2
2. **Check dependencies** — TASK-032, TASK-044 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create templates directory first**: `parrot/tools/security/reports/templates/`
5. **Start with base.html**, then add specific templates
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-045-report-generator.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: Implemented ReportGenerator with 4 async methods for generating compliance reports. Created 6 Jinja2 HTML templates (base, soc2, hipaa, pci_dss, executive_summary, consolidated). All 25 tests passing. Added PCI-DSS template beyond original scope.

**Deviations from spec**: Added `pci_dss_report.html` template for PCI-DSS compliance framework support. Added `generate_report_from_scan_result()` convenience method for single scan results.
