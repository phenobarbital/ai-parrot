"""CloudSploit executor for running scans via Docker or direct CLI."""
import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import Optional
from navconfig.logging import logging
from .models import CloudProvider, CloudSploitConfig, ComplianceFramework


# Container path used as the mount target for output files when running
# CloudSploit inside Docker. CloudSploit writes --json / --collection to
# real files (fs.createWriteStream), so /dev/stdout is unreliable.
_DOCKER_OUTPUT_MOUNT = "/cloudsploit/output"


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

    def _build_docker_command(
        self,
        args: list[str],
        volume_mounts: Optional[list[tuple[str, str, Optional[str]]]] = None,
    ) -> list[str]:
        """Build docker run command with env vars and CLI args.

        Args:
            args: CloudSploit CLI arguments to pass to the container.
            volume_mounts: Optional list of ``(host_dir, container_dir, mode)``
                tuples to mount into the container. ``mode`` may be ``None``,
                ``"ro"`` (read-only), or ``"rw"`` (read-write). Mounts are
                emitted in list order.

        Returns:
            Full docker run command as list of strings.
        """
        cmd = ["docker", "run", "--rm"]
        for mount in volume_mounts or []:
            host_dir, container_dir, mode = mount
            spec = f"{host_dir}:{container_dir}"
            if mode:
                spec = f"{spec}:{mode}"
            cmd.extend(["-v", spec])
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
        json_path: str,
        collection_path: Optional[str] = None,
        plugins: Optional[list[str]] = None,
        compliance: Optional[ComplianceFramework] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        config_path: Optional[str] = None,
    ) -> list[str]:
        """Build CloudSploit CLI arguments.

        Args:
            json_path: File path CloudSploit will write JSON results to.
            collection_path: Optional file path for the raw cloud-provider
                response data (``--collection``).
            plugins: Specific plugins to run. If None, runs all.
            compliance: Compliance framework to filter by.
            ignore_ok: If True, exclude OK (passing) results.
            suppress: Regex patterns to suppress results.
            config_path: Optional path to a CloudSploit JS credentials file.
                When set, ``--config=<config_path>`` is emitted as the first
                CLI argument. An empty string is treated as None (no flag).

        Returns:
            List of CLI argument strings.
        """
        args: list[str] = []
        if config_path:
            args.append(f"--config={config_path}")
        args.extend([
            f"--json={json_path}",
            "--console=none",
            f"--cloud={self.config.cloud_provider.value}",
        ])
        if collection_path:
            args.append(f"--collection={collection_path}")
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

    async def execute(
        self,
        args: list[str],
        volume_mounts: Optional[list[tuple[str, str, Optional[str]]]] = None,
    ) -> tuple[str, str, int]:
        """Run CloudSploit and return output.

        Args:
            args: CloudSploit CLI arguments.
            volume_mounts: List of ``(host_dir, container_dir, mode)`` tuples
                for Docker bind-mounts. ``mode`` may be ``None``, ``"ro"``, or
                ``"rw"``. Ignored when ``use_docker`` is False.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Raises:
            asyncio.TimeoutError: If execution exceeds configured timeout.
        """
        if self.config.use_docker:
            cmd = self._build_docker_command(args, volume_mounts=volume_mounts)
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

    async def _run_with_outputs(
        self,
        *,
        plugins: Optional[list[str]] = None,
        compliance: Optional[ComplianceFramework] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        capture_collection: bool = True,
    ) -> tuple[str, str, str, str, int]:
        """Run CloudSploit writing JSON + collection to temp files.

        CloudSploit's ``--json`` and ``--collection`` flags require real
        file paths (``fs.createWriteStream``); writing to ``/dev/stdout``
        is unreliable. We materialise a temp directory, point CloudSploit
        at files inside it, mount it into the container when running via
        Docker, then read the results back.

        Args:
            plugins: Specific plugins to run. If None, runs all plugins.
            compliance: Compliance framework to filter by.
            ignore_ok: If True, exclude OK results.
            suppress: Regex patterns to suppress specific results.
            capture_collection: When True, also request the raw cloud
                provider collection (``--collection``).

        Returns:
            Tuple of ``(results_json, collection_json, stdout, stderr,
            exit_code)``. ``collection_json`` is an empty string when
            ``capture_collection`` is False or the file is missing.
        """
        with tempfile.TemporaryDirectory(prefix="cloudsploit_") as host_tmp:
            host_dir = Path(host_tmp)
            host_results = host_dir / "results.json"
            host_collection = host_dir / "collection.json"

            if self.config.use_docker:
                container_results = f"{_DOCKER_OUTPUT_MOUNT}/results.json"
                container_collection = (
                    f"{_DOCKER_OUTPUT_MOUNT}/collection.json"
                    if capture_collection else None
                )
                volume_mounts: list[tuple[str, str, Optional[str]]] = [
                    (str(host_dir), _DOCKER_OUTPUT_MOUNT, None)
                ]
            else:
                container_results = str(host_results)
                container_collection = (
                    str(host_collection) if capture_collection else None
                )
                volume_mounts = []

            args = self._build_cli_args(
                json_path=container_results,
                collection_path=container_collection,
                plugins=plugins,
                compliance=compliance,
                ignore_ok=ignore_ok,
                suppress=suppress,
            )
            stdout, stderr, exit_code = await self.execute(
                args, volume_mounts=volume_mounts if volume_mounts else None,
            )

            results_json = (
                host_results.read_text() if host_results.exists() else ""
            )
            collection_json = (
                host_collection.read_text()
                if capture_collection and host_collection.exists()
                else ""
            )

            if not results_json:
                self.logger.warning(
                    "CloudSploit produced no JSON results file at %s",
                    host_results,
                )

            return results_json, collection_json, stdout, stderr, exit_code

    async def run_scan(
        self,
        plugins: Optional[list[str]] = None,
        ignore_ok: bool = False,
        suppress: Optional[list[str]] = None,
        capture_collection: bool = True,
    ) -> tuple[str, str, str, str, int]:
        """Run a full or targeted CloudSploit scan.

        Args:
            plugins: Specific plugins to run. If None, runs all plugins.
            ignore_ok: If True, exclude OK (passing) results.
            suppress: Regex patterns to suppress specific results.
            capture_collection: When True, also request the raw cloud
                provider collection (``--collection``).

        Returns:
            Tuple of ``(results_json, collection_json, stdout, stderr,
            exit_code)``.
        """
        return await self._run_with_outputs(
            plugins=plugins,
            ignore_ok=ignore_ok,
            suppress=suppress,
            capture_collection=capture_collection,
        )

    async def run_compliance_scan(
        self,
        framework: ComplianceFramework,
        ignore_ok: bool = True,
        capture_collection: bool = True,
    ) -> tuple[str, str, str, str, int]:
        """Run a compliance-filtered CloudSploit scan.

        Args:
            framework: Compliance framework to filter by.
            ignore_ok: If True, exclude OK results (default True for compliance).
            capture_collection: When True, also request the raw cloud
                provider collection (``--collection``).

        Returns:
            Tuple of ``(results_json, collection_json, stdout, stderr,
            exit_code)``.
        """
        return await self._run_with_outputs(
            compliance=framework,
            ignore_ok=ignore_ok,
            capture_collection=capture_collection,
        )
