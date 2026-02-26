"""Prowler executor for running cloud security scans.

Extends BaseExecutor to provide Prowler-specific CLI argument building
and scan execution methods.
"""

from typing import Optional

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

        # Output modes
        output_modes = kwargs.get("output_modes", self.config.output_modes)
        if output_modes:
            args.extend(["-M", ",".join(output_modes)])

        # Output directory
        output_dir = kwargs.get("output_directory", self.config.output_directory)
        if output_dir:
            args.extend(["-o", output_dir])

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

        # Region filtering
        regions = kwargs.get("filter_regions", self.config.filter_regions)
        if regions:
            for region in regions:
                args.extend(["-f", region])

        # AWS profile
        profile = kwargs.get("aws_profile", self.config.aws_profile)
        if profile:
            args.extend(["-p", profile])

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

        # Services to scan
        services = kwargs.get("services", self.config.services)
        if services:
            for service in services:
                args.extend(["-s", service])

        # Specific checks
        checks = kwargs.get("checks", self.config.checks)
        if checks:
            for check in checks:
                args.extend(["-c", check])

        # Excluded checks
        excluded_checks = kwargs.get("excluded_checks", self.config.excluded_checks)
        if excluded_checks:
            for check in excluded_checks:
                args.extend(["-e", check])

        # Excluded services
        excluded_services = kwargs.get(
            "excluded_services", self.config.excluded_services
        )
        if excluded_services:
            args.extend(["--excluded-services", ",".join(excluded_services)])

        # Severity filter
        severity = kwargs.get("severity", self.config.severity)
        if severity:
            args.extend(["--severity", ",".join(severity)])

        # Compliance framework
        compliance = kwargs.get(
            "compliance_framework", self.config.compliance_framework
        )
        if compliance:
            args.extend(["--compliance", compliance])

        # Mutelist file
        mutelist = kwargs.get("mutelist_file", self.config.mutelist_file)
        if mutelist:
            args.extend(["--mutelist", mutelist])

        # Scan unused services
        scan_unused = kwargs.get("scan_unused_services", self.config.scan_unused_services)
        if scan_unused:
            args.append("--scan-unused-services")

        return args

    async def run_scan(
        self,
        provider: Optional[str] = None,
        services: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
        compliance_framework: Optional[str] = None,
        severity: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Run a Prowler security scan.

        Args:
            provider: Override the configured provider.
            services: Override services to scan.
            checks: Override specific checks to run.
            compliance_framework: Override compliance framework.
            severity: Override severity filter.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        kwargs = {}
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

        return await self.execute(**kwargs)

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
