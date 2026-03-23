"""Prowler executor for running cloud security scans.

Extends BaseExecutor to provide Prowler-specific CLI argument building
and scan execution methods.
"""

from typing import Optional
import tempfile
from pathlib import Path

from ..base_executor import BaseExecutor
from .config import ProwlerConfig


class ProwlerExecutor(BaseExecutor):
    """Executes Prowler security scans via Docker or direct CLI.

    Prowler CLI pattern: `prowler <provider> [options]`

    Supports:
    - AWS, Azure, GCP, Kubernetes providers
    - Multiple output formats
    - Region/service filtering
    - Compliance framework filtering
    - Check exclusions
    """

    def __init__(self, config: Optional[ProwlerConfig] = None):
        """Initialize the Prowler executor.

        Args:
            config: Prowler configuration. Uses defaults if not provided.
        """
        super().__init__(config or ProwlerConfig())
        self.config: ProwlerConfig = self.config  # type narrowing
        self.expected_exit_codes = [0, 3]

    def _default_cli_name(self) -> str:
        """Return the default Prowler CLI binary name."""
        return "prowler"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Prowler CLI arguments from configuration.

        Args:
            **kwargs: Override config values for this invocation.
                - provider: Override the provider
                - services: Override services list
                - checks: Override checks list
                - compliance_framework: Override compliance framework

        Returns:
            List of CLI argument strings.
        """
        # Start with provider (can be overridden)
        provider = kwargs.get("provider", self.config.provider)
        args = [provider]

        # Output modes (updated for Prowler v4+)
        output_modes = kwargs.get("output_modes", self.config.output_modes)
        if output_modes:
            args.extend(["--output-formats", ",".join(output_modes)])

        # Output directory
        output_dir = kwargs.get("output_directory", self.config.output_directory)
        if output_dir:
            args.extend(["--output-directory", output_dir])

        # Provider-specific options
        if provider == "aws":
            args.extend(self._build_aws_args(**kwargs))
        elif provider == "azure":
            args.extend(self._build_azure_args(**kwargs))
        elif provider == "gcp":
            args.extend(self._build_gcp_args(**kwargs))
        elif provider == "kubernetes":
            args.extend(self._build_kubernetes_args(**kwargs))

        # Common filtering options
        args.extend(self._build_filter_args(**kwargs))

        return args

    def _build_aws_args(self, **kwargs) -> list[str]:
        """Build AWS-specific CLI arguments."""
        args = []

        # Region filtering (updated for Prowler v4+)
        regions = kwargs.get("filter_regions", self.config.filter_regions)
        if regions:
            args.extend(["-f", ",".join(regions)])

        # AWS profile
        profile = kwargs.get("aws_profile", self.config.aws_profile)
        if profile:
            args.extend(["--profile", profile])

        return args

    def _build_azure_args(self, **kwargs) -> list[str]:
        """Build Azure-specific CLI arguments."""
        args = []

        # Auth method
        auth_method = kwargs.get("azure_auth_method", self.config.azure_auth_method)
        if auth_method:
            args.append(f"--{auth_method}")

        # Subscription IDs
        subs = kwargs.get("subscription_ids", self.config.subscription_ids)
        if subs:
            args.extend(["--subscription-ids", ",".join(subs)])

        return args

    def _build_gcp_args(self, **kwargs) -> list[str]:
        """Build GCP-specific CLI arguments."""
        args = []

        # Project IDs
        projects = kwargs.get("gcp_project_ids", self.config.gcp_project_ids)
        if projects:
            args.extend(["--project-ids", ",".join(projects)])

        return args

    def _build_kubernetes_args(self, **kwargs) -> list[str]:
        """Build Kubernetes-specific CLI arguments."""
        args = []

        # Context
        context = kwargs.get("kubernetes_context", self.config.kubernetes_context)
        if context:
            args.extend(["--context", context])

        # Namespace
        namespace = kwargs.get("kubernetes_namespace", self.config.kubernetes_namespace)
        if namespace:
            args.extend(["--namespace", namespace])

        return args

    def _build_filter_args(self, **kwargs) -> list[str]:
        """Build common filtering arguments."""
        args = []
        provider = kwargs.get("provider", self.config.provider)

        # Services to scan (updated for Prowler v4+)
        services = kwargs.get("services", self.config.services)
        if services:
            args.extend(["--service", ",".join(services)])

        # Specific checks (updated for Prowler v4+)
        checks = kwargs.get("checks", self.config.checks)
        if checks:
            args.extend(["--check", ",".join(checks)])

        # Excluded checks (updated for Prowler v4+)
        excluded_checks = kwargs.get("excluded_checks", self.config.excluded_checks)
        if excluded_checks:
            args.extend(["--excluded-check", ",".join(excluded_checks)])

        # Excluded services (updated for Prowler v4+)
        excluded_services = kwargs.get(
            "excluded_services", self.config.excluded_services
        )
        if excluded_services:
            args.extend(["--excluded-service", ",".join(excluded_services)])

        # Severity filter
        severity = kwargs.get("severity", self.config.severity)
        if severity:
            args.extend(["--severity", ",".join(severity)])

        # Compliance framework (Prowler v4+ requires provider suffix like soc2_aws)
        compliance = kwargs.get(
            "compliance_framework", self.config.compliance_framework
        )
        if compliance:
            # Add provider suffix if not already present
            if not compliance.endswith(f"_{provider}"):
                compliance = f"{compliance}_{provider}"
            args.extend(["--compliance", compliance])

        # Mutelist file (updated for Prowler v4+)
        mutelist = kwargs.get("mutelist_file", self.config.mutelist_file)
        if mutelist:
            args.extend(["--mutelist-file", mutelist])

        # Scan unused services
        scan_unused = kwargs.get("scan_unused_services", self.config.scan_unused_services)
        if scan_unused:
            args.append("--scan-unused-services")

        return args

    def _build_scan_kwargs(
        self,
        provider: Optional[str] = None,
        services: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
        compliance_framework: Optional[str] = None,
        severity: Optional[list[str]] = None,
        filter_regions: Optional[list[str]] = None,
    ) -> dict:
        """Build kwargs dict from scan parameters."""
        kwargs: dict = {}
        if provider:
            kwargs["provider"] = provider
        if services:
            kwargs["services"] = services
        if checks:
            kwargs["checks"] = checks
        if compliance_framework:
            kwargs["compliance_framework"] = compliance_framework
        if severity:
            kwargs["severity"] = severity
        if filter_regions:
            kwargs["filter_regions"] = filter_regions
        return kwargs

    async def run_scan(
        self,
        provider: Optional[str] = None,
        services: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
        compliance_framework: Optional[str] = None,
        severity: Optional[list[str]] = None,
        filter_regions: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Run a Prowler security scan.

        Args:
            provider: Override the configured provider.
            services: Override services to scan.
            checks: Override specific checks to run.
            compliance_framework: Override compliance framework.
            severity: Override severity filter.
            filter_regions: AWS regions to scan (AWS provider only).

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        kwargs = self._build_scan_kwargs(
            provider, services, checks,
            compliance_framework, severity, filter_regions,
        )
        return await self._execute_with_json_capture(self.execute, **kwargs)

    async def run_scan_streaming(
        self,
        progress_callback=None,
        provider: Optional[str] = None,
        services: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
        compliance_framework: Optional[str] = None,
        severity: Optional[list[str]] = None,
        filter_regions: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Run a Prowler scan with real-time stderr streaming.

        Same as run_scan but streams stderr lines to progress_callback.

        Args:
            progress_callback: Called with each stderr line as it arrives.
            provider: Override the configured provider.
            services: Override services to scan.
            checks: Override specific checks to run.
            compliance_framework: Override compliance framework.
            severity: Override severity filter.
            filter_regions: AWS regions to scan (AWS provider only).

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        kwargs = self._build_scan_kwargs(
            provider, services, checks,
            compliance_framework, severity, filter_regions,
        )
        return await self._execute_with_json_capture(
            self.execute_streaming, progress_callback=progress_callback, **kwargs
        )

    async def _execute_with_json_capture(self, execute_func, *args, **kwargs) -> tuple[str, str, int]:
        """Run execution and capture JSON-OCSF output."""
        # Only capture if json-ocsf is requested
        output_modes = kwargs.get("output_modes", self.config.output_modes)
        if "json-ocsf" not in output_modes:
            return await execute_func(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Backup original config
            orig_results_dir = self.config.results_dir
            orig_output_dir = self.config.output_directory
            
            try:
                if self.config.use_docker:
                    # Docker: mount temp_dir to /results, tell prowler to write to /results
                    self.config.results_dir = str(temp_path)
                    kwargs["output_directory"] = "/results"
                else:
                    # Local: tell prowler to write to temp_dir
                    kwargs["output_directory"] = str(temp_path)

                # Run the scan
                stdout, stderr, exit_code = await execute_func(*args, **kwargs)

                # Find the generated JSON-OCSF file
                json_files = list(temp_path.glob("*.ocsf.json"))
                if json_files:
                    # Return the JSON content as stdout, as the parser expects
                    json_content = json_files[0].read_text(encoding="utf-8")
                    return json_content, stderr, exit_code
                else:
                    self.logger.warning("No JSON-OCSF file found in Prowler output")
                    return stdout, stderr, exit_code
            finally:
                # Restore config
                self.config.results_dir = orig_results_dir
                self.config.output_directory = orig_output_dir

    async def list_checks(
        self, provider: Optional[str] = None, service: Optional[str] = None
    ) -> tuple[str, str, int]:
        """List available Prowler checks.

        Args:
            provider: Provider to list checks for (default: configured provider).
            service: Filter checks by service.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        provider = provider or self.config.provider
        args = [provider, "--list-checks"]
        if service:
            args.extend(["-s", service])
        return await self.execute(args=args)

    async def list_services(
        self, provider: Optional[str] = None
    ) -> tuple[str, str, int]:
        """List available services for a provider.

        Args:
            provider: Provider to list services for (default: configured provider).

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        provider = provider or self.config.provider
        args = [provider, "--list-services"]
        return await self.execute(args=args)

    async def list_compliance_frameworks(
        self, provider: Optional[str] = None
    ) -> tuple[str, str, int]:
        """List available compliance frameworks.

        Args:
            provider: Provider to list frameworks for (default: configured provider).

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        provider = provider or self.config.provider
        args = [provider, "--list-compliance"]
        return await self.execute(args=args)
