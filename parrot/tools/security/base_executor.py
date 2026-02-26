"""Base executor for running CLI-based security scanners.

Provides a reusable abstraction for running security scanners via Docker
or direct process execution. All scanner executors (Prowler, Trivy, Checkov)
inherit from this base class.
"""

import asyncio
import os
import re
from abc import ABC, abstractmethod
from typing import Optional

from navconfig.logging import logging
from pydantic import BaseModel, Field


class BaseExecutorConfig(BaseModel):
    """Base configuration shared by all scanner executors.

    Supports credential configuration for AWS, GCP, and Azure cloud providers.
    Credentials can be provided directly or via profile/file references.
    """

    # Execution mode
    use_docker: bool = Field(
        default=True, description="Run via Docker or direct CLI"
    )
    docker_image: str = Field(default="", description="Docker image to use")
    cli_path: Optional[str] = Field(
        default=None, description="Path to CLI binary for direct execution"
    )
    timeout: int = Field(default=600, description="Execution timeout in seconds")
    results_dir: Optional[str] = Field(
        default=None, description="Directory to store scan results"
    )

    # AWS credentials
    aws_access_key_id: Optional[str] = Field(
        default=None, description="AWS access key ID"
    )
    aws_secret_access_key: Optional[str] = Field(
        default=None, description="AWS secret access key"
    )
    aws_session_token: Optional[str] = Field(
        default=None, description="AWS session token for temporary credentials"
    )
    aws_profile: Optional[str] = Field(
        default=None, description="AWS CLI profile name"
    )
    aws_region: str = Field(default="us-east-1", description="Default AWS region")

    # GCP credentials
    gcp_credentials_file: Optional[str] = Field(
        default=None, description="Path to GCP service account JSON file"
    )
    gcp_project_id: Optional[str] = Field(
        default=None, description="GCP project ID"
    )

    # Azure credentials
    azure_client_id: Optional[str] = Field(
        default=None, description="Azure AD application (client) ID"
    )
    azure_client_secret: Optional[str] = Field(
        default=None, description="Azure AD client secret"
    )
    azure_tenant_id: Optional[str] = Field(
        default=None, description="Azure AD tenant ID"
    )
    azure_subscription_id: Optional[str] = Field(
        default=None, description="Azure subscription ID"
    )

    model_config = {"extra": "ignore"}


class BaseExecutor(ABC):
    """Abstract base executor for Docker or CLI process management.

    Provides common functionality for running security scanners:
    - Environment variable building for cloud credentials
    - Docker and direct CLI command construction
    - Async subprocess execution with timeout
    - Credential masking for safe logging

    Subclasses must implement:
    - _build_cli_args(): Build scanner-specific CLI arguments
    - _default_cli_name(): Return the default CLI binary name
    """

    def __init__(self, config: BaseExecutorConfig):
        """Initialize the executor with configuration.

        Args:
            config: Executor configuration including credentials and timeouts.
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build CLI arguments specific to the scanner.

        Args:
            **kwargs: Scanner-specific parameters.

        Returns:
            List of CLI argument strings.
        """
        ...

    @abstractmethod
    def _default_cli_name(self) -> str:
        """Return the default CLI binary name.

        Returns:
            CLI binary name (e.g., 'prowler', 'trivy', 'checkov').
        """
        ...

    def _build_env_vars(self) -> dict[str, str]:
        """Build environment variables for cloud credentials.

        Builds provider-specific environment variables based on the
        configured credentials. Only includes variables for which
        credentials are actually provided.

        Returns:
            Dictionary of environment variable names to values.
        """
        env: dict[str, str] = {}

        # AWS credentials
        if self.config.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = self.config.aws_access_key_id
        if self.config.aws_secret_access_key:
            env["AWS_SECRET_ACCESS_KEY"] = self.config.aws_secret_access_key
        if self.config.aws_session_token:
            env["AWS_SESSION_TOKEN"] = self.config.aws_session_token
        if self.config.aws_profile:
            env["AWS_PROFILE"] = self.config.aws_profile
        if self.config.aws_region:
            env["AWS_REGION"] = self.config.aws_region
            env["AWS_DEFAULT_REGION"] = self.config.aws_region

        # GCP credentials
        if self.config.gcp_credentials_file:
            env["GOOGLE_APPLICATION_CREDENTIALS"] = self.config.gcp_credentials_file
        if self.config.gcp_project_id:
            env["CLOUDSDK_CORE_PROJECT"] = self.config.gcp_project_id
            env["GCP_PROJECT_ID"] = self.config.gcp_project_id

        # Azure credentials
        if self.config.azure_client_id:
            env["AZURE_CLIENT_ID"] = self.config.azure_client_id
        if self.config.azure_client_secret:
            env["AZURE_CLIENT_SECRET"] = self.config.azure_client_secret
        if self.config.azure_tenant_id:
            env["AZURE_TENANT_ID"] = self.config.azure_tenant_id
        if self.config.azure_subscription_id:
            env["AZURE_SUBSCRIPTION_ID"] = self.config.azure_subscription_id

        return env

    def _build_docker_command(self, args: list[str]) -> list[str]:
        """Build docker run command with env vars and CLI args.

        Constructs a docker run command that:
        - Removes the container after execution (--rm)
        - Passes cloud credentials via environment variables
        - Mounts results directory if configured

        Args:
            args: Scanner CLI arguments to pass to the container.

        Returns:
            Full docker run command as list of strings.
        """
        cmd = ["docker", "run", "--rm"]

        # Add environment variables
        for key, val in self._build_env_vars().items():
            cmd.extend(["-e", f"{key}={val}"])

        # Mount results directory if specified
        if self.config.results_dir:
            cmd.extend(["-v", f"{self.config.results_dir}:/results"])

        # Add the docker image
        cmd.append(self.config.docker_image)

        # Add scanner-specific arguments
        cmd.extend(args)

        return cmd

    def _build_direct_command(self, args: list[str]) -> list[str]:
        """Build direct CLI command for non-Docker execution.

        Args:
            args: Scanner CLI arguments.

        Returns:
            CLI command as list of strings.
        """
        cli = self.config.cli_path or self._default_cli_name()
        return [cli, *args]

    def _build_process_env(self) -> dict[str, str]:
        """Build process environment for direct CLI execution.

        Merges cloud credential env vars with the current system environment.

        Returns:
            Full environment dictionary for subprocess.
        """
        env = os.environ.copy()
        env.update(self._build_env_vars())
        return env

    def _mask_command(self, cmd: list[str]) -> str:
        """Mask sensitive credentials in a command for safe logging.

        Masks:
        - AWS secret access key (fully masked)
        - AWS session token (fully masked)
        - AWS access key ID (shows first 3 chars only)
        - Azure client secret (fully masked)
        - GCP credentials file path (partially masked)

        Args:
            cmd: Command as list of strings.

        Returns:
            Masked command as a single string.
        """
        masked_parts = []
        for part in cmd:
            masked = part

            # AWS credentials
            masked = re.sub(
                r"AWS_SECRET_ACCESS_KEY=[^\s]+",
                "AWS_SECRET_ACCESS_KEY=***",
                masked,
            )
            masked = re.sub(
                r"AWS_SESSION_TOKEN=[^\s]+",
                "AWS_SESSION_TOKEN=***",
                masked,
            )
            masked = re.sub(
                r"AWS_ACCESS_KEY_ID=([A-Za-z0-9]{3})[^\s]*",
                r"AWS_ACCESS_KEY_ID=\1***",
                masked,
            )

            # Azure credentials
            masked = re.sub(
                r"AZURE_CLIENT_SECRET=[^\s]+",
                "AZURE_CLIENT_SECRET=***",
                masked,
            )

            # GCP credentials (mask file path except filename)
            masked = re.sub(
                r"GOOGLE_APPLICATION_CREDENTIALS=.*/([^/]+)",
                r"GOOGLE_APPLICATION_CREDENTIALS=****/\1",
                masked,
            )

            masked_parts.append(masked)

        return " ".join(masked_parts)

    async def execute(
        self, args: Optional[list[str]] = None, **kwargs
    ) -> tuple[str, str, int]:
        """Run the scanner and return output.

        Executes the scanner either via Docker or direct CLI based on
        configuration. Handles timeout and process cleanup.

        Args:
            args: Pre-built CLI arguments. If None, builds from kwargs.
            **kwargs: Arguments passed to _build_cli_args() if args is None.

        Returns:
            Tuple of (stdout, stderr, exit_code).
            On timeout, exit_code is -1 and stderr contains "Timeout" message.
        """
        # Build arguments if not provided
        if args is None:
            args = self._build_cli_args(**kwargs)

        # Build command based on execution mode
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

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout
            )
            exit_code = proc.returncode or 0

            if exit_code != 0:
                self.logger.warning(
                    "Scanner exited with code %d: %s",
                    exit_code,
                    stderr.decode()[:500],
                )

            return stdout.decode(), stderr.decode(), exit_code

        except asyncio.TimeoutError:
            self.logger.error(
                "Execution timed out after %d seconds", self.config.timeout
            )
            # Kill the process to avoid zombie
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass  # Process already terminated

            return "", f"Timeout: execution exceeded {self.config.timeout} seconds", -1
