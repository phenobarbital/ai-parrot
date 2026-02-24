"""CloudSploit executor for running scans via Docker or direct CLI."""
import asyncio
import os
import re
from typing import Optional

from navconfig.logging import logging

from .models import CloudProvider, CloudSploitConfig, ComplianceFramework


class CloudSploitExecutor:
    """Executes CloudSploit scans via Docker or direct CLI.

    Supports two execution modes:
    - Docker mode (default): runs CloudSploit inside a Docker container
    - Direct CLI mode: runs CloudSploit directly via Node.js CLI

    AWS credentials are passed via environment variables only,
    never written to files.
    """

    def __init__(self, config: CloudSploitConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    def _build_env_vars(self) -> dict[str, str]:
        """Build provider-specific environment variables for CloudSploit."""
        env: dict[str, str] = {}

        if self.config.cloud_provider == CloudProvider.AWS:
            if self.config.aws_access_key_id:
                env["AWS_ACCESS_KEY_ID"] = self.config.aws_access_key_id
                env["AWS_SECRET_ACCESS_KEY"] = self.config.aws_secret_access_key or ""
                if self.config.aws_session_token:
                    env["AWS_SESSION_TOKEN"] = self.config.aws_session_token
            if self.config.aws_profile:
                env["AWS_PROFILE"] = self.config.aws_profile

            # Default regions and AWS SDK config
            env["AWS_REGION"] = self.config.aws_region
            env["AWS_DEFAULT_REGION"] = self.config.aws_default_region
            env["AWS_SDK_LOAD_CONFIG"] = self.config.aws_sdk_load_config

        elif self.config.cloud_provider == CloudProvider.GCP:
            if self.config.gcp_project_id:
                env["PROJECT"] = self.config.gcp_project_id
            if self.config.gcp_credentials_path:
                env["GOOGLE_APPLICATION_CREDENTIALS"] = self.config.gcp_credentials_path

        return env

    def _build_docker_command(self, args: list[str]) -> list[str]:
        """Build docker run command with env vars and CLI args.

        Args:
            args: CloudSploit CLI arguments to pass to the container.

        Returns:
            Full docker run command as list of strings.
        """
        cmd = ["docker", "run", "--rm"]
        for key, val in self._build_env_vars().items():
            cmd.extend(["-e", f"{key}={val}"])
        cmd.append(self.config.docker_image)
        cmd.extend(args)
        return cmd

    def _build_direct_command(self, args: list[str]) -> list[str]:
        """Build direct CLI command for non-Docker execution.

        Args:
            args: CloudSploit CLI arguments.

        Returns:
            CLI command as list of strings.
        """
        cli = self.config.cli_path or "cloudsploit"
        return [cli, *args]

    def _build_process_env(self) -> dict[str, str]:
        """Build process environment for direct CLI execution.

        Merges AWS credential env vars with the current system environment.

        Returns:
            Full environment dictionary for subprocess.
        """
        env = os.environ.copy()
        env.update(self._build_env_vars())
        return env

    def _build_cli_args(
        self,
        plugins: Optional[list[str]] = None,
        compliance: Optional[ComplianceFramework] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
    ) -> list[str]:
        """Build CloudSploit CLI arguments.

        Args:
            plugins: Specific plugins to run. If None, runs all.
            compliance: Compliance framework to filter by.
            ignore_ok: If True, exclude OK (passing) results.
            suppress: Regex patterns to suppress results.

        Returns:
            List of CLI argument strings.
        """
        args = [
            "--json", "/dev/stdout", "--console", "none",
            "--cloud", self.config.cloud_provider.value,
        ]
        if compliance:
            args.append(f"--compliance={compliance.value}")
        if plugins:
            for plugin in plugins:
                args.extend(["--plugin", plugin])
        if ignore_ok:
            args.append("--ignore-ok")
        if suppress:
            for s in suppress:
                args.extend(["--suppress", s])
        if self.config.govcloud and self.config.cloud_provider == CloudProvider.AWS:
            args.append("--govcloud")
        return args

    def _mask_command(self, cmd: list[str]) -> str:
        """Mask sensitive credentials in a command for safe logging.

        Args:
            cmd: Command as list of strings.

        Returns:
            Masked command as a single string.
        """
        masked_parts = []
        for part in cmd:
            masked = part
            # Mask AWS_SECRET_ACCESS_KEY
            masked = re.sub(
                r'AWS_SECRET_ACCESS_KEY=[^\s]+',
                'AWS_SECRET_ACCESS_KEY=***',
                masked,
            )
            # Mask AWS_SESSION_TOKEN
            masked = re.sub(
                r'AWS_SESSION_TOKEN=[^\s]+',
                'AWS_SESSION_TOKEN=***',
                masked,
            )
            # Mask AWS_ACCESS_KEY_ID (show first 3 chars)
            masked = re.sub(
                r'AWS_ACCESS_KEY_ID=([A-Za-z0-9]{3})[^\s]*',
                r'AWS_ACCESS_KEY_ID=\1***',
                masked,
            )
            masked_parts.append(masked)
        return " ".join(masked_parts)

    async def execute(self, args: list[str]) -> tuple[str, str, int]:
        """Run CloudSploit and return output.

        Args:
            args: CloudSploit CLI arguments.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Raises:
            asyncio.TimeoutError: If execution exceeds configured timeout.
        """
        if self.config.use_docker:
            cmd = self._build_docker_command(args)
            env = None
        else:
            cmd = self._build_direct_command(args)
            env = self._build_process_env()

        self.logger.debug("Executing: %s", self._mask_command(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=self.config.timeout_seconds
        )
        exit_code = proc.returncode or 0

        if exit_code != 0:
            self.logger.warning(
                "CloudSploit exited with code %d: %s",
                exit_code,
                stderr.decode()[:500],
            )

        return stdout.decode(), stderr.decode(), exit_code

    async def run_scan(
        self,
        plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
    ) -> tuple[str, str, int]:
        """Run a full or targeted CloudSploit scan.

        Args:
            plugins: Specific plugins to run. If None, runs all plugins.
            ignore_ok: If True, exclude OK (passing) results.
            suppress: Regex patterns to suppress specific results.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        args = self._build_cli_args(
            plugins=plugins,
            ignore_ok=ignore_ok,
            suppress=suppress,
        )
        return await self.execute(args)

    async def run_compliance_scan(
        self,
        framework: ComplianceFramework,
        ignore_ok: bool = True,
    ) -> tuple[str, str, int]:
        """Run a compliance-filtered CloudSploit scan.

        Args:
            framework: Compliance framework to filter by.
            ignore_ok: If True, exclude OK results (default True for compliance).

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        args = self._build_cli_args(
            compliance=framework,
            ignore_ok=ignore_ok,
        )
        return await self.execute(args)
