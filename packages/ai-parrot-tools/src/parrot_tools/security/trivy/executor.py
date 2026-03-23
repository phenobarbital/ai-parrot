"""Trivy executor for running security scans.

Extends BaseExecutor to provide Trivy-specific CLI argument building
and helper methods for common scan types.
"""

from typing import Optional

from ..base_executor import BaseExecutor
from .config import TrivyConfig


class TrivyExecutor(BaseExecutor):
    """Executes Trivy security scans via Docker or direct CLI.

    Trivy CLI pattern: `trivy <scan_type> [options] <target>`

    Scan types:
    - image: Container image vulnerability scanning
    - fs: Filesystem vulnerability and secret scanning
    - repo: Git repository scanning
    - config: IaC misconfiguration detection
    - k8s: Kubernetes cluster scanning
    - sbom: Software Bill of Materials generation

    Example:
        config = TrivyConfig(severity_filter=["CRITICAL", "HIGH"])
        executor = TrivyExecutor(config)
        stdout, stderr, code = await executor.scan_image("nginx:latest")
    """

    def __init__(self, config: Optional[TrivyConfig] = None):
        """Initialize the Trivy executor.

        Args:
            config: Trivy configuration. Uses defaults if not provided.
        """
        super().__init__(config or TrivyConfig())
        self.config: TrivyConfig = self.config  # type narrowing

    def _default_cli_name(self) -> str:
        """Return the default Trivy CLI binary name."""
        return "trivy"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Trivy CLI arguments for a scan.

        Args:
            **kwargs: Scan parameters including:
                - scan_type: Type of scan (image, fs, repo, config, k8s, sbom)
                - target: Target to scan (image name, path, cluster, etc.)
                - k8s_context: Kubernetes context (for k8s scans)
                - k8s_namespace: Kubernetes namespace (for k8s scans)
                - compliance: Compliance specification
                - sbom_format: SBOM output format (cyclonedx, spdx)

        Returns:
            List of CLI argument strings.
        """
        scan_type = kwargs.get("scan_type", "image")
        target = kwargs.get("target", "")

        # Start with scan type
        args = [scan_type]

        # Add common options
        args.extend(self._build_common_args(**kwargs))

        # Add scan-type specific options
        if scan_type == "k8s":
            args.extend(self._build_k8s_args(**kwargs))
        elif scan_type == "config":
            args.extend(self._build_config_args(**kwargs))
        elif scan_type == "image":
            args.extend(self._build_image_args(**kwargs))

        # Add compliance option if specified
        compliance = kwargs.get("compliance", self.config.compliance)
        if compliance:
            args.extend(["--compliance", compliance])

        # Add target last (except for k8s which uses "cluster" keyword)
        if scan_type == "k8s" and target == "cluster":
            args.append("cluster")
        elif target:
            args.append(target)

        return args

    def _build_common_args(self, **kwargs) -> list[str]:
        """Build common CLI arguments used across scan types."""
        args = []

        # Output format
        sbom_format = kwargs.get("sbom_format")
        if sbom_format:
            # SBOM output uses different format flag
            args.extend(["--format", sbom_format])
        else:
            output_format = kwargs.get("output_format", self.config.output_format)
            args.extend(["--format", output_format])

        # Output file
        output_file = kwargs.get("output_file", self.config.output_file)
        if output_file:
            args.extend(["--output", output_file])

        # Severity filter
        severity = kwargs.get("severity_filter", self.config.severity_filter)
        if severity:
            args.extend(["--severity", ",".join(severity)])

        # Scanners (not for SBOM generation)
        if kwargs.get("scan_type") != "sbom":
            scanners = kwargs.get("scanners", self.config.scanners)
            if scanners:
                args.extend(["--scanners", ",".join(scanners)])

        # Ignore unfixed
        ignore_unfixed = kwargs.get("ignore_unfixed", self.config.ignore_unfixed)
        if ignore_unfixed:
            args.append("--ignore-unfixed")

        # Cache options
        cache_dir = kwargs.get("cache_dir", self.config.cache_dir)
        if cache_dir:
            args.extend(["--cache-dir", cache_dir])

        db_skip = kwargs.get("db_skip_update", self.config.db_skip_update)
        if db_skip:
            args.append("--skip-db-update")

        # Skip directories
        skip_dirs = kwargs.get("skip_dirs", self.config.skip_dirs)
        for skip_dir in skip_dirs:
            args.extend(["--skip-dirs", skip_dir])

        # Skip files
        skip_files = kwargs.get("skip_files", self.config.skip_files)
        for skip_file in skip_files:
            args.extend(["--skip-files", skip_file])

        # Exit code
        exit_code = kwargs.get("exit_code", self.config.exit_code)
        if exit_code != 0:
            args.extend(["--exit-code", str(exit_code)])

        return args

    def _build_k8s_args(self, **kwargs) -> list[str]:
        """Build Kubernetes-specific CLI arguments."""
        args = []

        # Kubernetes context
        context = kwargs.get("k8s_context", self.config.k8s_context)
        if context:
            args.extend(["--context", context])

        # Kubernetes namespace
        namespace = kwargs.get("k8s_namespace", self.config.k8s_namespace)
        if namespace:
            args.extend(["--namespace", namespace])

        # K8s components
        components = kwargs.get("k8s_components", self.config.k8s_components)
        if components:
            args.extend(["--components", ",".join(components)])

        return args

    def _build_config_args(self, **kwargs) -> list[str]:
        """Build IaC config scan-specific CLI arguments."""
        args = []

        # Custom policy directory
        policy = kwargs.get("config_policy", self.config.config_policy)
        if policy:
            args.extend(["--config-policy", policy])

        # Custom data directory
        data = kwargs.get("config_data", self.config.config_data)
        if data:
            args.extend(["--config-data", data])

        return args

    def _build_image_args(self, **kwargs) -> list[str]:
        """Build image scan-specific CLI arguments."""
        args = []

        # Vulnerability types
        vuln_type = kwargs.get("vuln_type", self.config.vuln_type)
        if vuln_type:
            args.extend(["--vuln-type", ",".join(vuln_type)])

        # Image config scanners
        img_scanners = kwargs.get(
            "image_config_scanners", self.config.image_config_scanners
        )
        if img_scanners:
            args.extend(["--image-config-scanners", ",".join(img_scanners)])

        return args

    # Helper methods for common scan types

    async def scan_image(
        self,
        image: str,
        severity: Optional[list[str]] = None,
        ignore_unfixed: Optional[bool] = None,
        scanners: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan a container image for vulnerabilities.

        Args:
            image: Image name with optional tag (e.g., "nginx:latest").
            severity: Override severity filter.
            ignore_unfixed: Override ignore_unfixed setting.
            scanners: Override scanner types.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_image(
                "nginx:latest",
                severity=["CRITICAL"],
            )
        """
        kwargs = {"scan_type": "image", "target": image}
        if severity is not None:
            kwargs["severity_filter"] = severity
        if ignore_unfixed is not None:
            kwargs["ignore_unfixed"] = ignore_unfixed
        if scanners is not None:
            kwargs["scanners"] = scanners
        return await self.execute(**kwargs)

    async def scan_filesystem(
        self,
        path: str,
        severity: Optional[list[str]] = None,
        scanners: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan a filesystem directory for vulnerabilities and secrets.

        Args:
            path: Path to directory or file to scan.
            severity: Override severity filter.
            scanners: Override scanner types.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_filesystem(
                "/app",
                scanners=["vuln", "secret", "misconfig"],
            )
        """
        kwargs = {"scan_type": "fs", "target": path}
        if severity is not None:
            kwargs["severity_filter"] = severity
        if scanners is not None:
            kwargs["scanners"] = scanners
        return await self.execute(**kwargs)

    async def scan_repository(
        self,
        repo_url: str,
        branch: Optional[str] = None,
        severity: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan a Git repository for vulnerabilities.

        Args:
            repo_url: Git repository URL.
            branch: Branch to scan (default: default branch).
            severity: Override severity filter.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_repository(
                "https://github.com/org/repo.git",
                branch="main",
            )
        """
        target = repo_url
        if branch:
            target = f"{repo_url}@{branch}"

        kwargs = {"scan_type": "repo", "target": target}
        if severity is not None:
            kwargs["severity_filter"] = severity
        return await self.execute(**kwargs)

    async def scan_config(
        self,
        path: str,
        compliance: Optional[str] = None,
        policy_dir: Optional[str] = None,
    ) -> tuple[str, str, int]:
        """Scan IaC configuration files for misconfigurations.

        Supports Terraform, CloudFormation, Kubernetes manifests,
        Dockerfile, and more.

        Args:
            path: Path to IaC configuration directory or file.
            compliance: Compliance specification to check against.
            policy_dir: Custom policy directory.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_config(
                "./terraform",
                compliance="aws-cis-1.4.0",
            )
        """
        kwargs = {
            "scan_type": "config",
            "target": path,
            "scanners": ["misconfig"],  # Config scans use misconfig scanner
        }
        if compliance is not None:
            kwargs["compliance"] = compliance
        if policy_dir is not None:
            kwargs["config_policy"] = policy_dir
        return await self.execute(**kwargs)

    async def scan_k8s(
        self,
        context: Optional[str] = None,
        namespace: Optional[str] = None,
        compliance: Optional[str] = None,
        components: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan a Kubernetes cluster for vulnerabilities and misconfigurations.

        Args:
            context: Kubernetes context to use.
            namespace: Namespace to scan (None = all namespaces).
            compliance: Compliance specification (e.g., "k8s-cis-1.23").
            components: K8s components to scan (workload, infra, rbac).

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_k8s(
                context="prod-cluster",
                compliance="k8s-cis-1.23",
            )
        """
        kwargs = {"scan_type": "k8s", "target": "cluster"}
        if context is not None:
            kwargs["k8s_context"] = context
        if namespace is not None:
            kwargs["k8s_namespace"] = namespace
        if compliance is not None:
            kwargs["compliance"] = compliance
        if components is not None:
            kwargs["k8s_components"] = components
        return await self.execute(**kwargs)

    async def generate_sbom(
        self,
        target: str,
        scan_type: str = "image",
        sbom_format: str = "cyclonedx",
        output_file: Optional[str] = None,
    ) -> tuple[str, str, int]:
        """Generate a Software Bill of Materials (SBOM) for a target.

        Args:
            target: Target to generate SBOM for (image name or path).
            scan_type: Type of target (image, fs, repo).
            sbom_format: SBOM format (cyclonedx, spdx, spdx-json).
            output_file: Output file path (defaults to stdout).

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.generate_sbom(
                "myapp:v1",
                sbom_format="cyclonedx",
                output_file="/tmp/sbom.json",
            )
        """
        kwargs = {
            "scan_type": scan_type,
            "target": target,
            "sbom_format": sbom_format,
            "scanners": [],  # SBOM generation doesn't use scanners
        }
    async def list_scanners(self) -> tuple[str, str, int]:
        """List available scanner types.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        args = ["--help"]
        return await self.execute(args=args)
