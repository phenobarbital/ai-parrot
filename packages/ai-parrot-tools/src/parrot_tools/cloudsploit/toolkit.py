"""CloudSploit Security Scanning Toolkit for AI-Parrot.

Orchestrates CloudSploit executor, parser, report generator, and
comparator into a single AbstractToolkit subclass.  Every public
async method is automatically exposed as an agent tool.
"""
from datetime import datetime
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
    ScanSummary,
    SeverityLevel,
)
from .parser import ScanResultParser
from .reports import ReportGenerator


class CloudSploitToolkit(AbstractToolkit):
    """Cloud Security Posture Management toolkit powered by CloudSploit.

    Runs security scans against AWS infrastructure, parses results,
    generates reports, and tracks security posture over time.
    """

    def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        self.executor = CloudSploitExecutor(self.config)
        self.parser = ScanResultParser()
        self.report_generator = ReportGenerator()
        self.comparator = ScanComparator()
        self._last_result: Optional[ScanResult] = None

    # -- Public async methods (each becomes an agent tool) -----------------

    async def run_scan(
        self,
        plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
    ) -> ScanResult:
        """Run a CloudSploit security scan against cloud infrastructure.

        Args:
            plugins: Specific plugins to run. If None, runs all plugins.
            ignore_ok: If True, exclude passing (OK) results.
            suppress: Regex patterns to suppress specific results.

        Returns:
            ScanResult with typed findings and summary.
        """
        stdout, stderr, code = await self.executor.run_scan(
            plugins=plugins, ignore_ok=ignore_ok, suppress=suppress,
        )
        if code != 0:
            self.logger.warning(
                "CloudSploit exited with code %d: %s", code, stderr[:500],
            )

        result = self.parser.parse(stdout)
        self._last_result = result

        if self.config.results_dir:
            ts = result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
            path = str(Path(self.config.results_dir) / f"scan_{ts}.json")
            self.parser.save_result(result, path)
            self.logger.info("Scan result saved to %s", path)

        return result

    async def run_compliance_scan(
        self,
        framework: str,
        ignore_ok: bool = True,
    ) -> ScanResult:
        """Run a compliance-filtered CloudSploit scan.

        Args:
            framework: Compliance framework - one of: hipaa, cis1, cis2, pci.
            ignore_ok: If True, exclude passing results (default True for compliance).

        Returns:
            ScanResult filtered to the specified compliance framework.
        """
        try:
            fw = ComplianceFramework(framework.lower())
        except ValueError:
            valid = [f.value for f in ComplianceFramework]
            raise ValueError(
                f"Unknown compliance framework '{framework}'. "
                f"Valid options: {valid}"
            )

        stdout, stderr, code = await self.executor.run_compliance_scan(
            framework=fw, ignore_ok=ignore_ok,
        )
        if code != 0:
            self.logger.warning(
                "CloudSploit compliance scan exited with code %d: %s",
                code, stderr[:500],
            )

        result = self.parser.parse(stdout)
        result.summary.compliance_framework = fw.value
        self._last_result = result
        return result

    async def get_summary(self) -> dict:
        """Get a summary of the most recent scan results.

        Returns:
            Dictionary with severity counts and category breakdown.
            Returns an error dict if no scan has been run yet.
        """
        if self._last_result is None:
            return {"error": "No scan has been run yet. Call run_scan() first."}
        return self._last_result.summary.model_dump()

    async def generate_report(
        self,
        format: str = "html",
        output_path: Optional[str] = None,
    ) -> str:
        """Generate a security report from the most recent scan.

        Args:
            format: Report format - 'html' or 'pdf'.
            output_path: File path to save the report. Auto-generated if not set.

        Returns:
            File path of the generated report.
        """
        if self._last_result is None:
            return "Error: No scan has been run yet. Call run_scan() first."

        fmt = format.lower()
        if fmt not in ("html", "pdf"):
            return f"Error: Unsupported format '{format}'. Use 'html' or 'pdf'."

        if not output_path:
            ts = self._last_result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
            base_dir = self.config.results_dir or "/tmp"
            output_path = str(Path(base_dir) / f"report_{ts}.{fmt}")

        if fmt == "html":
            return await self.report_generator.generate_html(
                self._last_result, output_path=output_path,
            )
        return await self.report_generator.generate_pdf(
            self._last_result, output_path=output_path,
        )

    async def compare_scans(
        self,
        baseline_path: str,
        current_path: Optional[str] = None,
    ) -> ComparisonReport:
        """Compare two scan results to track security posture changes.

        Args:
            baseline_path: Path to a previously saved scan result JSON.
            current_path: Path to current scan JSON. Uses last scan if not set.

        Returns:
            ComparisonReport showing new, resolved, and unchanged findings.
        """
        baseline = self.parser.load_result(baseline_path)

        if current_path:
            current = self.parser.load_result(current_path)
        elif self._last_result:
            current = self._last_result
        else:
            raise ValueError(
                "No current scan available. Run a scan first or provide current_path."
            )

        return self.comparator.compare(baseline, current)

    async def list_findings(
        self,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        region: Optional[str] = None,
    ) -> list[dict]:
        """List findings from the most recent scan with optional filters.

        Args:
            severity: Filter by severity level (OK, WARN, FAIL, UNKNOWN).
            category: Filter by service category (e.g., EC2, S3, IAM).
            region: Filter by cloud region.

        Returns:
            List of finding dictionaries matching the filters.
        """
        if self._last_result is None:
            return []

        findings = self._last_result.findings

        if severity:
            try:
                level = SeverityLevel(severity.upper())
            except ValueError:
                valid = [s.value for s in SeverityLevel]
                self.logger.warning(
                    "Unknown severity '%s'. Valid: %s", severity, valid,
                )
                return []
            findings = [f for f in findings if f.status == level]

        if category:
            findings = [f for f in findings if f.category == category]

        if region:
            findings = [f for f in findings if f.region == region]

        return [f.model_dump() for f in findings]
