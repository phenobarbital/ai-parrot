"""CloudSploit Security Scanning Toolkit for AI-Parrot.

Orchestrates CloudSploit executor, parser, report generator, and
comparator into a single AbstractToolkit subclass.  Every public
async method is automatically exposed as an agent tool.
"""
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from parrot.interfaces.aws import AWSInterface
from parrot_tools.security.persistence import (
    ReportPersistenceMixin,
    pop_persistence_kwargs,
)

from ..decorators import tool_schema
from ..toolkit import AbstractToolkit
from .comparator import ScanComparator
from .ecr_collector import EcrScanCollector
from .executor import CloudSploitExecutor
from .models import (
    CloudSploitConfig,
    ComparisonReport,
    ComplianceFramework,
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrSeverity,
    ScanResult,
    SeverityLevel,
)
from .parser import ScanResultParser
from .reports import ReportGenerator


# ---------------------------------------------------------------------------
# Input schemas for the new ECR agent tools (private — not exported)
# ---------------------------------------------------------------------------


class _CollectEcrInput(BaseModel):
    """Input schema for ``collect_ecr_findings``."""

    plan: Optional[str] = Field(
        None,
        description=(
            "Path to a YAML ECR collection plan. When None, falls back to "
            "``CloudSploitConfig.ecr_plan_file``."
        ),
    )


class _GenerateEcrReportInput(BaseModel):
    """Input schema for ``generate_ecr_report``."""

    output_path: Optional[str] = Field(
        None,
        description="File path to write the HTML report. Auto-generated when None.",
    )
    result: Optional[EcrCollectionResult] = Field(
        None,
        description=(
            "Override the last collected result. Defaults to "
            "``self._last_ecr_result``."
        ),
    )


class CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit):
    """Cloud Security Posture Management toolkit powered by CloudSploit.

    Runs security scans against AWS infrastructure, parses results,
    generates reports, and tracks security posture over time.
    """

    def __init__(self, config: Optional[CloudSploitConfig] = None, **kwargs):
        # Pop persistence kwargs BEFORE super().__init__ to avoid unknown-kwarg errors
        self.file_manager, self.report_store = pop_persistence_kwargs(
            kwargs
        )
        super().__init__(**kwargs)
        self.config = config or CloudSploitConfig()
        self.executor = CloudSploitExecutor(self.config)
        self.parser = ScanResultParser()
        self.report_generator = ReportGenerator()
        self.comparator = ScanComparator()
        self._last_result: Optional[ScanResult] = None

        # ECR image-scan additions (FEAT-165)
        self._ecr_aws = AWSInterface(region_name=self.config.aws_region)
        self.ecr_collector = EcrScanCollector(aws=self._ecr_aws)
        self._last_ecr_result: Optional[EcrCollectionResult] = None

    # -- Private helpers ---------------------------------------------------

    async def _persist_after_scan(
        self, result: ScanResult, *, framework: Optional[str],
    ) -> None:
        """Persist a scan result to the catalog (no-op when deps are absent).

        Args:
            result: Completed scan result from the executor.
            framework: Compliance framework name or None for unrestricted scans.
        """
        if self.config.results_dir:
            ts = result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
            content = Path(self.config.results_dir) / f"scan_{ts}.json"
        else:
            content = result.model_dump_json().encode("utf-8")

        await self._persist_report(
            scanner="cloudsploit",
            framework=framework,
            provider=getattr(self.config.cloud_provider, "value", "aws"),
            scope={
                "account_id": getattr(self.config, "aws_account_id", None),
                "region": getattr(self.config, "aws_region", None),
            },
            content=content,
        )

    def _resolve_config(self, per_call: Optional[str]) -> Optional[str]:
        """Resolve effective config path with per-call arg > field precedence.

        Emits a DEBUG log when the per-call argument overrides the model-level
        ``config_file`` field, and a second DEBUG log with the resolved path
        whenever a config is active (regardless of source).

        Args:
            per_call: Per-call config path supplied by the caller, or None.

        Returns:
            Effective config path, or None if no config is configured.
        """
        effective = per_call if per_call is not None else self.config.config_file
        if (
            per_call is not None
            and self.config.config_file is not None
            and per_call != self.config.config_file
        ):
            self.logger.debug(
                "Per-call config=%s overrides CloudSploitConfig.config_file=%s",
                per_call,
                self.config.config_file,
            )
        if effective:
            self.logger.debug("Effective CloudSploit config: %s", effective)
        return effective

    def _resolve_ecr_plan(self, per_call: Optional[str]) -> Optional[str]:
        """Resolve effective ECR plan path with per-call > field precedence.

        Mirrors ``_resolve_config`` (toolkit.py:75-101) but reads
        ``self.config.ecr_plan_file`` instead of ``config_file``.

        Args:
            per_call: Per-call plan path supplied by the caller, or None.

        Returns:
            Effective plan path, or None if no plan is configured.
        """
        effective = per_call if per_call is not None else self.config.ecr_plan_file
        if (
            per_call is not None
            and self.config.ecr_plan_file is not None
            and per_call != self.config.ecr_plan_file
        ):
            self.logger.debug(
                "Per-call ecr_plan=%s overrides CloudSploitConfig.ecr_plan_file=%s",
                per_call,
                self.config.ecr_plan_file,
            )
        if effective:
            self.logger.debug("Effective ECR plan: %s", effective)
        return effective

    async def _persist_after_ecr_scan(
        self, result: EcrCollectionResult,
    ) -> None:
        """Side-effect: persist the ECR result to the catalog (no-op otherwise).

        Computes a severity summary dict from the per-repo counts and passes
        it to ``_persist_report`` with ``scanner="ecr-image-scan"`` to skip
        the parser-registry lookup (per spec §2 Overview).

        Args:
            result: The ``EcrCollectionResult`` that was just collected.
        """
        severity_summary = {sev.value: 0 for sev in EcrSeverity}
        for repo in result.repos:
            for sev, n in repo.counts.items():
                severity_summary[sev.value] = severity_summary.get(sev.value, 0) + n

        await self._persist_report(
            scanner="ecr-image-scan",
            framework=None,
            provider="aws",
            scope={
                "account_id": getattr(self.config, "aws_account_id", None),
                "region": result.region,
            },
            content=result.model_dump_json().encode("utf-8"),
            severity_summary=severity_summary,  # type: ignore[arg-type]
            top_findings=[],
        )

    # -- Public async methods (each becomes an agent tool) -----------------

    async def run_scan(
        self,
        plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        config: Optional[str] = None,
    ) -> ScanResult:
        """Run a CloudSploit security scan against cloud infrastructure.

        Args:
            plugins: Specific plugins to run. If None, runs all plugins.
            ignore_ok: If True, exclude passing (OK) results.
            suppress: Regex patterns to suppress specific results.
            config: Path to a CloudSploit JS credentials file. When set, takes
                precedence over ``CloudSploitConfig.config_file`` and over
                env-var credentials. The file must exist on disk.

        Returns:
            ScanResult with typed findings and summary.
        """
        effective_config = self._resolve_config(config)
        results_json, collection_json, _stdout, stderr, code = (
            await self.executor.run_scan(
                plugins=plugins,
                ignore_ok=ignore_ok,
                suppress=suppress,
                config=effective_config,
            )
        )
        if code != 0:
            self.logger.warning(
                "CloudSploit exited with code %d: %s", code, stderr[:500],
            )

        result = self.parser.parse(results_json)
        self._last_result = result

        if self.config.results_dir:
            results_dir = Path(self.config.results_dir)
            ts = result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
            path = str(results_dir / f"scan_{ts}.json")
            self.parser.save_result(result, path)
            self.logger.info("Scan result saved to %s", path)
            if collection_json:
                coll_path = results_dir / f"collection_{ts}.json"
                coll_path.write_text(collection_json)
                self.logger.info("Raw collection saved to %s", coll_path)

        # Side-effect: persist to catalog when deps are wired (no-op otherwise)
        await self._persist_after_scan(result, framework=None)
        return result

    async def run_compliance_scan(
        self,
        framework: str,
        ignore_ok: bool = True,
        config: Optional[str] = None,
    ) -> ScanResult:
        """Run a compliance-filtered CloudSploit scan.

        Args:
            framework: Compliance framework - one of: hipaa, cis1, cis2, pci.
            ignore_ok: If True, exclude passing results (default True for compliance).
            config: Path to a CloudSploit JS credentials file. When set, takes
                precedence over ``CloudSploitConfig.config_file`` and over
                env-var credentials. The file must exist on disk.

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

        effective_config = self._resolve_config(config)
        results_json, _collection_json, _stdout, stderr, code = (
            await self.executor.run_compliance_scan(
                framework=fw, ignore_ok=ignore_ok, config=effective_config,
            )
        )
        if code != 0:
            self.logger.warning(
                "CloudSploit compliance scan exited with code %d: %s",
                code, stderr[:500],
            )

        result = self.parser.parse(results_json)
        result.summary.compliance_framework = fw.value
        self._last_result = result

        # Side-effect: persist to catalog when deps are wired (no-op otherwise)
        await self._persist_after_scan(result, framework=fw.value)
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

    # -- ECR agent tools (FEAT-165) ----------------------------------------

    @tool_schema(_CollectEcrInput)
    async def collect_ecr_findings(
        self, plan: Optional[str] = None,
    ) -> EcrCollectionResult:
        """Aggregate ECR vulnerability scan findings across many repos.

        Loads the collection plan from YAML, calls the ECR collector for each
        repository in the plan (with bounded concurrency), stores the result
        as ``self._last_ecr_result``, and persists it to the security-report
        catalog when the persistence dependencies are wired.

        Args:
            plan: Path to a YAML ECR collection plan.  When ``None``, falls
                back to ``CloudSploitConfig.ecr_plan_file``.

        Returns:
            ``EcrCollectionResult`` with per-repo findings and severity counts.

        Raises:
            ValueError: When neither ``plan`` nor
                ``CloudSploitConfig.ecr_plan_file`` is set.
        """
        effective = self._resolve_ecr_plan(plan)
        if not effective:
            raise ValueError(
                "No ECR collection plan configured.  Pass plan=<path.yaml> or "
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
        """Render the interactive HTML ECR vulnerability report.

        Uses the provided ``result`` or falls back to the most recent
        collection stored in ``self._last_ecr_result``.  The output path is
        auto-generated from ``CloudSploitConfig.results_dir`` when not given.

        Args:
            output_path: File path to write the HTML report.  Parent
                directories are created automatically.  Auto-generated when
                ``None``.
            result: Override the last collected result.  Defaults to
                ``self._last_ecr_result``.

        Returns:
            File path of the written report (always a ``str``).

        Raises:
            ValueError: When neither ``result`` nor ``self._last_ecr_result``
                is available.
        """
        target = result or self._last_ecr_result
        if target is None:
            raise ValueError(
                "No ECR collection available.  Call collect_ecr_findings() "
                "first or pass result=<EcrCollectionResult>."
            )
        if not output_path:
            ts = target.generated_at.strftime("%Y%m%d_%H%M%S")
            base_dir = self.config.results_dir or "/tmp"
            output_path = str(Path(base_dir) / f"ecr_report_{ts}.html")
        return await self.report_generator.generate_ecr_html(
            target, output_path=output_path,
        )
