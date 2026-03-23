"""Checkov executor for running IaC security scans.

Extends BaseExecutor to provide Checkov-specific CLI argument building
and helper methods for common scan types.
"""

from typing import Optional

from ..base_executor import BaseExecutor
from .config import CheckovConfig


class CheckovExecutor(BaseExecutor):
    """Executes Checkov IaC security scans via Docker or direct CLI.

    Checkov CLI pattern: `checkov -d <dir> | -f <file> [options]`

    Supported frameworks:
    - terraform: Terraform configurations
    - cloudformation: AWS CloudFormation templates
    - kubernetes: Kubernetes manifests and Helm charts
    - dockerfile: Dockerfile security checks
    - arm: Azure Resource Manager templates
    - bicep: Azure Bicep configurations
    - serverless: Serverless Framework configurations
    - github_actions: GitHub Actions workflows
    - And many more...

    Example:
        config = CheckovConfig(frameworks=["terraform"])
        executor = CheckovExecutor(config)
        stdout, stderr, code = await executor.scan_directory("./terraform")
    """

    def __init__(self, config: Optional[CheckovConfig] = None):
        """Initialize the Checkov executor.

        Args:
            config: Checkov configuration. Uses defaults if not provided.
        """
        super().__init__(config or CheckovConfig())
        self.config: CheckovConfig = self.config  # type narrowing

    def _default_cli_name(self) -> str:
        """Return the default Checkov CLI binary name."""
        return "checkov"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Checkov CLI arguments for a scan.

        Args:
            **kwargs: Scan parameters including:
                - scan_type: Type of scan (directory, file)
                - target: Target to scan (directory path or file path)
                - frameworks: Override frameworks to scan
                - run_checks: Override checks to run
                - skip_checks: Override checks to skip

        Returns:
            List of CLI argument strings.
        """
        args = []
        scan_type = kwargs.get("scan_type", "directory")
        target = kwargs.get("target", ".")

        # Target specification
        if scan_type == "file":
            args.extend(["-f", target])
        else:
            args.extend(["-d", target])

        # Framework selection
        frameworks = kwargs.get("frameworks", self.config.frameworks)
        if frameworks:
            for framework in frameworks:
                args.extend(["--framework", framework])

        # Check filters
        run_checks = kwargs.get("run_checks", self.config.run_checks)
        if run_checks:
            args.extend(["--check", ",".join(run_checks)])

        skip_checks = kwargs.get("skip_checks", self.config.skip_checks)
        if skip_checks:
            args.extend(["--skip-check", ",".join(skip_checks)])

        # Output format
        output_format = kwargs.get("output_format", self.config.output_format)
        args.extend(["-o", output_format])

        # Output file
        output_file = kwargs.get("output_file", self.config.output_file)
        if output_file:
            args.extend(["--output-file-path", output_file])

        # Compact mode
        compact = kwargs.get("compact", self.config.compact)
        if compact:
            args.append("--compact")

        # External checks
        external_dir = kwargs.get("external_checks_dir", self.config.external_checks_dir)
        if external_dir:
            args.extend(["--external-checks-dir", external_dir])

        external_git = kwargs.get("external_checks_git", self.config.external_checks_git)
        if external_git:
            args.extend(["--external-checks-git", external_git])

        # Skip paths
        skip_paths = kwargs.get("skip_paths", self.config.skip_paths)
        for skip_path in skip_paths:
            args.extend(["--skip-path", skip_path])

        # Skip frameworks
        skip_frameworks = kwargs.get("skip_frameworks", self.config.skip_frameworks)
        for skip_fw in skip_frameworks:
            args.extend(["--skip-framework", skip_fw])

        # Soft fail
        soft_fail = kwargs.get("soft_fail", self.config.soft_fail)
        if soft_fail:
            args.append("--soft-fail")

        # Download external modules
        download_modules = kwargs.get(
            "download_external_modules", self.config.download_external_modules
        )
        if download_modules:
            args.append("--download-external-modules")
        else:
            args.append("--no-download-external-modules")

        # Baseline
        baseline = kwargs.get("baseline", self.config.baseline)
        if baseline:
            args.extend(["--baseline", baseline])

        # Secrets scanning
        enable_secrets = kwargs.get("enable_secret_scan", self.config.enable_secret_scan)
        if not enable_secrets:
            args.append("--skip-secrets-checks")

        return args

    # Helper methods for common scan types

    async def scan_directory(
        self,
        path: str,
        frameworks: Optional[list[str]] = None,
        run_checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan a directory for IaC misconfigurations.

        Args:
            path: Path to directory to scan.
            frameworks: Override frameworks to scan.
            run_checks: Override checks to run.
            skip_checks: Override checks to skip.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_directory(
                "./infrastructure",
                frameworks=["terraform", "cloudformation"],
            )
        """
        kwargs = {"scan_type": "directory", "target": path}
        if frameworks is not None:
            kwargs["frameworks"] = frameworks
        if run_checks is not None:
            kwargs["run_checks"] = run_checks
        if skip_checks is not None:
            kwargs["skip_checks"] = skip_checks
        return await self.execute(**kwargs)

    async def scan_file(
        self,
        path: str,
        frameworks: Optional[list[str]] = None,
        run_checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan a single file for IaC misconfigurations.

        Args:
            path: Path to file to scan.
            frameworks: Override frameworks to scan.
            run_checks: Override checks to run.
            skip_checks: Override checks to skip.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_file(
                "./main.tf",
                frameworks=["terraform"],
            )
        """
        kwargs = {"scan_type": "file", "target": path}
        if frameworks is not None:
            kwargs["frameworks"] = frameworks
        if run_checks is not None:
            kwargs["run_checks"] = run_checks
        if skip_checks is not None:
            kwargs["skip_checks"] = skip_checks
        return await self.execute(**kwargs)

    async def scan_terraform(
        self,
        path: str,
        run_checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
        download_modules: bool = True,
    ) -> tuple[str, str, int]:
        """Scan Terraform configurations for misconfigurations.

        Args:
            path: Path to Terraform directory.
            run_checks: Override checks to run.
            skip_checks: Override checks to skip.
            download_modules: Download external modules (default True).

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_terraform(
                "./terraform",
                skip_checks=["CKV_AWS_1"],
            )
        """
        kwargs = {
            "scan_type": "directory",
            "target": path,
            "frameworks": ["terraform"],
            "download_external_modules": download_modules,
        }
        if run_checks is not None:
            kwargs["run_checks"] = run_checks
        if skip_checks is not None:
            kwargs["skip_checks"] = skip_checks
        return await self.execute(**kwargs)

    async def scan_cloudformation(
        self,
        path: str,
        run_checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan CloudFormation templates for misconfigurations.

        Args:
            path: Path to CloudFormation directory or template file.
            run_checks: Override checks to run.
            skip_checks: Override checks to skip.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_cloudformation(
                "./cloudformation",
            )
        """
        kwargs = {
            "scan_type": "directory",
            "target": path,
            "frameworks": ["cloudformation"],
        }
        if run_checks is not None:
            kwargs["run_checks"] = run_checks
        if skip_checks is not None:
            kwargs["skip_checks"] = skip_checks
        return await self.execute(**kwargs)

    async def scan_kubernetes(
        self,
        path: str,
        run_checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan Kubernetes manifests for misconfigurations.

        Args:
            path: Path to Kubernetes manifests directory.
            run_checks: Override checks to run.
            skip_checks: Override checks to skip.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_kubernetes(
                "./k8s",
            )
        """
        kwargs = {
            "scan_type": "directory",
            "target": path,
            "frameworks": ["kubernetes"],
        }
        if run_checks is not None:
            kwargs["run_checks"] = run_checks
        if skip_checks is not None:
            kwargs["skip_checks"] = skip_checks
        return await self.execute(**kwargs)

    async def scan_dockerfile(
        self,
        path: str,
        run_checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan Dockerfile for misconfigurations.

        Args:
            path: Path to Dockerfile or directory containing Dockerfiles.
            run_checks: Override checks to run.
            skip_checks: Override checks to skip.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_dockerfile(
                "./Dockerfile",
            )
        """
        # Check if target is a file or directory
        scan_type = "file" if path.endswith("Dockerfile") else "directory"
        kwargs = {
            "scan_type": scan_type,
            "target": path,
            "frameworks": ["dockerfile"],
        }
        if run_checks is not None:
            kwargs["run_checks"] = run_checks
        if skip_checks is not None:
            kwargs["skip_checks"] = skip_checks
        return await self.execute(**kwargs)

    async def scan_secrets(
        self,
        path: str,
        skip_paths: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan for exposed secrets using entropy-based detection.

        Args:
            path: Path to directory to scan for secrets.
            skip_paths: Paths to skip during scanning.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_secrets(
                "./src",
                skip_paths=["node_modules", ".git"],
            )
        """
        kwargs = {
            "scan_type": "directory",
            "target": path,
            "frameworks": ["secrets"],
            "enable_secret_scan": True,
        }
        if skip_paths is not None:
            kwargs["skip_paths"] = skip_paths
        return await self.execute(**kwargs)

    async def scan_github_actions(
        self,
        path: str,
        run_checks: Optional[list[str]] = None,
        skip_checks: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Scan GitHub Actions workflows for misconfigurations.

        Args:
            path: Path to .github/workflows directory.
            run_checks: Override checks to run.
            skip_checks: Override checks to skip.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.scan_github_actions(
                "./.github/workflows",
            )
        """
        kwargs = {
            "scan_type": "directory",
            "target": path,
            "frameworks": ["github_actions"],
        }
        if run_checks is not None:
            kwargs["run_checks"] = run_checks
        if skip_checks is not None:
            kwargs["skip_checks"] = skip_checks
        return await self.execute(**kwargs)

    async def list_checks(
        self,
        framework: Optional[str] = None,
    ) -> tuple[str, str, int]:
        """List available Checkov checks.

        Args:
            framework: Filter checks by framework.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Example:
            stdout, stderr, code = await executor.list_checks(
                framework="terraform",
            )
        """
        args = ["--list"]
        if framework:
            args.extend(["--framework", framework])
        return await self.execute(args=args)
