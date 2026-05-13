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
    CloudProvider,
    CloudSploitConfig,
    ComparisonReport,
    ComplianceFramework,
    EcrCollectionPlan,
    EcrCollectionResult,
    EcrRepoPlan,
    EcrSeverity,
    ScanResult,
    SeverityLevel,
)
from .parser import ScanResultParser
from .reports import ReportGenerator


# CloudSploit CLI uses its own short framework codes (the values of
# ``ComplianceFramework`` — ``hipaa``, ``cis1``, ``cis2``, ``pci``). The
# shared security catalog uses the canonical vocabulary from
# ``parrot_tools.security.ComplianceFramework`` (``hipaa``, ``cis``,
# ``pci_dss``, …). Translate at the catalog boundary so weekly summaries and
# other consumers querying the canonical names see CloudSploit's scans.
_CATALOG_FRAMEWORK_MAP: dict[ComplianceFramework, str] = {
    ComplianceFramework.HIPAA: "hipaa",
    ComplianceFramework.CIS1: "cis",
    ComplianceFramework.CIS2: "cis",
    ComplianceFramework.PCI: "pci_dss",
}


# Curated "open ports" plugin lists per provider. Each entry is a real
# CloudSploit plugin name; refer to the upstream plugins/ tree:
#   - AWS:    plugins/aws/ec2/open*
#   - GCP:    plugins/google/compute/open*
#   - Oracle: plugins/oracle/networking/open*
_OPEN_PORTS_PLUGINS: dict[CloudProvider, list[str]] = {
    CloudProvider.AWS: [
        "openSSH", "openRDP", "openMySQL", "openPostgreSQL",
        "openMongo", "openMsSQL", "openOracle", "openRedis",
        "openDNS", "openTelnet", "openSMTP", "openFTP",
        "openCIFS", "openNetBIOS", "openCassandra", "openDocker",
        "openElasticsearch", "openHadoopNameNode", "openKibana",
        "openSalt", "openLDAP", "openLDAPS",
        "openVNCClient", "openVNCServer",
        "openCustomPorts", "openAllPortsProtocols",
    ],
    CloudProvider.GCP: [
        "openSSH", "openRDP", "openMySQL", "openPostgreSQL",
        "openMongoDB", "openMsSQL", "openOracle", "openRedis",
        "openDNS", "openTelnet", "openSMTP", "openFTP",
        "openCIFS", "openCassandra", "openDocker", "openElasticsearch",
        "openHadoop", "openKibana", "openSalt", "openVNC",
        "openCustomPorts", "openAllPorts",
    ],
    CloudProvider.ORACLE: [
        "openSSH", "openRDP", "openMySQL", "openPostgreSQL",
        "openMongoDB", "openMsSQL", "openOracle", "openRedis",
        "openDNS", "openTelnet", "openSMTP", "openFTP",
        "openCIFS", "openCassandra", "openDocker", "openElasticsearch",
        "openHadoop", "openKibana", "openVNC",
        "openCustomPorts", "openAllPorts",
    ],
}


# ---------------------------------------------------------------------------
# Input schemas for the new ECR agent tools (private — not exported)
# ---------------------------------------------------------------------------


class _CollectEcrInput(BaseModel):
    """Input schema for ``collect_ecr_findings``.

    Precedence (highest first): ``repos`` → ``plan`` → configured default.
    Call with no arguments to scan every repository in the configured plan.
    """

    repos: Optional[list[EcrRepoPlan]] = Field(
        default=None,
        description=(
            "Inline list of repositories to scan, e.g. "
            "[{'name': 'navigator-api-tf', 'tags': ['staging']}]. "
            "Each entry MUST use the key 'name' (NOT 'repo') and a 'tags' "
            "list with priority order; first matching tag wins. When set, "
            "takes precedence over 'plan' and the configured default plan. "
            "Do NOT write a YAML file just to pass a one-off scope — use "
            "this parameter instead."
        ),
    )
    region: Optional[str] = Field(
        default=None,
        description=(
            "AWS region for the inline 'repos' scope (e.g. 'us-east-1'). "
            "Required when 'repos' is set unless CloudSploitConfig.aws_region "
            "is configured. Ignored when 'plan' is used."
        ),
    )
    aws_id: Optional[str] = Field(
        default=None,
        description=(
            "Credential identifier resolved by AWSInterface (e.g. 'default'). "
            "Only used with inline 'repos'. Defaults to 'default'."
        ),
    )
    concurrency: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description=(
            "Max concurrent ECR API calls for the inline scope. Defaults to 5. "
            "Ignored when 'plan' is used."
        ),
    )
    plan: Optional[str] = Field(
        default=None,
        description=(
            "Path to a YAML ECR collection plan ON DISK (must already exist). "
            "Falls back to CloudSploitConfig.ecr_plan_file when None. "
            "For ad-hoc one-off scopes, prefer the 'repos' parameter instead."
        ),
    )


class _GenerateEcrReportInput(BaseModel):
    """Input schema for ``generate_ecr_report``.

    The toolkit keeps the last ``collect_ecr_findings`` result internally
    (``self._last_ecr_result``) and the report is rendered from it — do NOT
    re-pass the previous tool's output here. Call ``collect_ecr_findings``
    first if needed, then call ``generate_ecr_report`` with only the
    optional ``output_path``.
    """

    output_path: Optional[str] = Field(
        None,
        description="File path to write the HTML report. Auto-generated when None.",
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
        catalog_framework = _CATALOG_FRAMEWORK_MAP.get(fw, fw.value)
        result.summary.compliance_framework = catalog_framework
        self._last_result = result

        if self.config.results_dir:
            results_dir = Path(self.config.results_dir)
            ts = result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
            path = str(results_dir / f"scan_{ts}.json")
            self.parser.save_result(result, path)
            self.logger.info("Compliance scan result saved to %s", path)

        # Side-effect: persist to catalog when deps are wired (no-op otherwise)
        await self._persist_after_scan(result, framework=catalog_framework)
        return result

    # -- Open-ports / firewall scans (provider-aware helpers) --------------

    async def scan_open_ports(
        self,
        provider: str = "aws",
        extra_plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        config: Optional[str] = None,
    ) -> ScanResult:
        """Scan only the "open ports" plugins for a given cloud provider.

        Runs CloudSploit's curated open-port plugin set for the target
        provider (AWS EC2 Security Groups, GCP Firewall Rules, or OCI
        Security Lists). Temporarily switches ``self.config.cloud_provider``
        for the duration of the scan and restores it afterwards.

        Args:
            provider: One of ``"aws"``, ``"google"``, ``"oracle"``.
            extra_plugins: Additional CloudSploit plugin names to append.
            ignore_ok: If True, exclude passing (OK) results.
            suppress: Regex patterns to suppress specific results.
            config: Per-call CloudSploit JS credentials file (see run_scan).

        Returns:
            ScanResult with findings limited to the open-port plugins.
        """
        try:
            target = CloudProvider(provider.lower())
        except ValueError as e:
            valid = [p.value for p in _OPEN_PORTS_PLUGINS]
            raise ValueError(
                f"Unsupported provider '{provider}'. Valid options: {valid}"
            ) from e

        plugins = _OPEN_PORTS_PLUGINS.get(target)
        if not plugins:
            valid = [p.value for p in _OPEN_PORTS_PLUGINS]
            raise ValueError(
                f"No open-port plugin list registered for provider "
                f"'{provider}'. Supported: {valid}"
            )
        if extra_plugins:
            plugins = [*plugins, *extra_plugins]

        previous_provider = self.config.cloud_provider
        self.config.cloud_provider = target
        try:
            return await self.run_scan(
                plugins=plugins,
                ignore_ok=ignore_ok,
                suppress=suppress,
                config=config,
            )
        finally:
            self.config.cloud_provider = previous_provider

    async def scan_security_groups(
        self,
        extra_plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        config: Optional[str] = None,
    ) -> ScanResult:
        """Scan AWS EC2 Security Groups for open-port misconfigurations.

        Convenience alias for ``scan_open_ports(provider="aws", ...)``.
        """
        return await self.scan_open_ports(
            provider="aws",
            extra_plugins=extra_plugins,
            ignore_ok=ignore_ok,
            suppress=suppress,
            config=config,
        )

    async def scan_firewall_rules(
        self,
        extra_plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        config: Optional[str] = None,
    ) -> ScanResult:
        """Scan GCP Firewall Rules for open-port misconfigurations.

        Convenience alias for ``scan_open_ports(provider="google", ...)``.
        """
        return await self.scan_open_ports(
            provider="google",
            extra_plugins=extra_plugins,
            ignore_ok=ignore_ok,
            suppress=suppress,
            config=config,
        )

    async def scan_security_lists(
        self,
        extra_plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        config: Optional[str] = None,
    ) -> ScanResult:
        """Scan OCI Security Lists for open-port misconfigurations.

        Convenience alias for ``scan_open_ports(provider="oracle", ...)``.
        """
        return await self.scan_open_ports(
            provider="oracle",
            extra_plugins=extra_plugins,
            ignore_ok=ignore_ok,
            suppress=suppress,
            config=config,
        )

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

        ts = self._last_result.summary.scan_timestamp.strftime("%Y%m%d_%H%M%S")
        if not output_path:
            base_dir = self.config.results_dir or "/tmp"
            output_path = str(Path(base_dir) / f"report_{ts}.{fmt}")

        if fmt == "html":
            result_path = await self.report_generator.generate_html(
                self._last_result, output_path=output_path,
            )
        else:
            result_path = await self.report_generator.generate_pdf(
                self._last_result, output_path=output_path,
            )

        await self._mirror_rendered_report(
            local_path=result_path,
            scanner="cloudsploit",
            framework=self._last_result.summary.compliance_framework,
            timestamp=self._last_result.summary.scan_timestamp,
            extension=fmt,
        )

        return result_path

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
        self,
        repos: Optional[list[EcrRepoPlan]] = None,
        region: Optional[str] = None,
        aws_id: Optional[str] = None,
        concurrency: Optional[int] = None,
        plan: Optional[str] = None,
    ) -> EcrCollectionResult:
        """Aggregate ECR vulnerability scan findings across many repos.

        Three ways to specify what to scan, in precedence order:

        1. ``repos`` (inline) — preferred for ad-hoc, single-repo, or one-off
           scopes.  Each entry uses key ``name`` (NOT ``repo``) and a ``tags``
           list, e.g. ``[{"name": "navigator-api-tf", "tags": ["staging"]}]``.
           Do NOT write a YAML file on disk just to pass an ad-hoc scope —
           use this parameter.
        2. ``plan`` (YAML path on disk) — for stable, version-controlled scopes.
        3. ``CloudSploitConfig.ecr_plan_file`` — the configured default plan,
           used when both ``repos`` and ``plan`` are ``None``.

        The result is stored as ``self._last_ecr_result`` and persisted to the
        security-report catalog when persistence dependencies are wired.

        Args:
            repos: Inline repositories to scan.  When set, takes precedence
                over ``plan`` and the configured default plan.
            region: AWS region for the inline scope.  Required when ``repos``
                is set unless ``CloudSploitConfig.aws_region`` is configured.
                Ignored when ``plan`` is used.
            aws_id: Credential identifier for the inline scope.  Defaults to
                ``"default"``.  Ignored when ``plan`` is used.
            concurrency: Max concurrent ECR API calls for the inline scope.
                Defaults to 5.  Ignored when ``plan`` is used.
            plan: Path to a YAML ECR collection plan on disk.  Falls back to
                ``CloudSploitConfig.ecr_plan_file`` when ``None``.

        Returns:
            ``EcrCollectionResult`` with per-repo findings and severity counts.

        Raises:
            ValueError: When no scope can be resolved from any of the inputs,
                or when ``repos`` is set without a usable region.
        """
        if repos:
            effective_region = region or self.config.aws_region
            if not effective_region:
                raise ValueError(
                    "Inline 'repos' scope requires a region. Pass region=<aws-region> "
                    "or set CloudSploitConfig.aws_region."
                )
            plan_kwargs: dict = {
                "region": effective_region,
                "repos": repos,
            }
            if aws_id is not None:
                plan_kwargs["aws_id"] = aws_id
            if concurrency is not None:
                plan_kwargs["concurrency"] = concurrency
            plan_model = EcrCollectionPlan(**plan_kwargs)
            self.logger.debug(
                "Using inline ECR scope: region=%s, %d repo(s)",
                effective_region, len(repos),
            )
        else:
            effective = self._resolve_ecr_plan(plan)
            if not effective:
                raise ValueError(
                    "No ECR collection plan configured. Pass repos=[...] for an "
                    "inline scope, plan=<path.yaml> for a YAML file, or set "
                    "CloudSploitConfig.ecr_plan_file."
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

        Uses the most recent ``collect_ecr_findings`` result stored in
        ``self._last_ecr_result`` (or the optional ``result`` argument when
        called programmatically; LLMs never pass it).  The output path is
        auto-generated from ``CloudSploitConfig.results_dir`` when not given,
        and the filename includes the repo name(s) so it's predictable.

        IMPORTANT for LLM callers: the returned string is the ABSOLUTE PATH
        of the written file.  Quote it back to the user EXACTLY — do not
        rename, paraphrase, or invent a "friendlier" filename.

        Args:
            output_path: File path to write the HTML report.  Parent
                directories are created automatically.  Auto-generated when
                ``None``.
            result: Override the last collected result.  Defaults to
                ``self._last_ecr_result``.  Not exposed to LLM callers.

        Returns:
            Absolute file path of the written report (always a ``str``).

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
        # The tool dispatcher dumps Pydantic args to dicts before invoking the
        # bound method, so a model handed in via ``result`` arrives as a dict.
        # Re-hydrate so the rest of the method can use attribute access.
        if isinstance(target, dict):
            target = EcrCollectionResult.model_validate(target)
        if not output_path:
            ts = target.generated_at.strftime("%Y%m%d_%H%M%S")
            base_dir = self.config.results_dir or "/tmp"
            output_path = str(
                Path(base_dir) / self._ecr_report_filename(target, ts)
            )
        self.logger.info("Generating ECR HTML report at %s", output_path)
        return await self.report_generator.generate_ecr_html(
            target, output_path=output_path,
        )

    @staticmethod
    def _ecr_report_filename(result: EcrCollectionResult, ts: str) -> str:
        """Build a deterministic, repo-aware filename for the HTML report.

        Single-repo result → ``ecr_report_<repo-slug>_<ts>.html`` so callers
        (including LLMs that paraphrase) can predict the path.  Multi-repo
        result → ``ecr_report_<n>repos_<ts>.html``.  Empty result →
        ``ecr_report_<ts>.html``.

        Args:
            result: The ECR collection result being rendered.
            ts: Pre-formatted timestamp slug (``YYYYMMDD_HHMMSS``).

        Returns:
            The filename (basename only, no directory).
        """
        if not result.repos:
            return f"ecr_report_{ts}.html"
        if len(result.repos) == 1:
            slug = result.repos[0].repo.replace("/", "-").replace(":", "-")
            return f"ecr_report_{slug}_{ts}.html"
        return f"ecr_report_{len(result.repos)}repos_{ts}.html"
