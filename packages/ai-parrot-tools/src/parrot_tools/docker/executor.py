"""Docker executor for running Docker CLI commands.

Extends BaseExecutor to provide Docker-specific CLI argument building,
output parsing, and daemon/compose detection. Supports container lifecycle,
image building, and command execution operations.
"""

import asyncio
import json
import shlex
from typing import Optional

from navconfig.logging import logging

from parrot.tools.security.base_executor import BaseExecutor

from .config import DockerConfig
from .models import (
    ContainerInfo,
    ContainerRunInput,
    DockerBuildInput,
    DockerExecInput,
    DockerOperationResult,
    ImageInfo,
)


class DockerExecutor(BaseExecutor):
    """Async executor for Docker CLI commands.

    Wraps the Docker CLI and docker compose CLI for structured
    container management operations. Parses JSON output into
    Pydantic models.

    Example:
        config = DockerConfig(docker_cli="docker")
        executor = DockerExecutor(config)

        if await executor.check_daemon():
            result = await executor.run_command(["ps", "--format", "json"])
    """

    def __init__(self, config: Optional[DockerConfig] = None):
        """Initialize the Docker executor.

        Args:
            config: Docker configuration. Uses defaults if not provided.
        """
        super().__init__(config or DockerConfig())
        self.config: DockerConfig = self.config  # type narrowing
        self.logger = logging.getLogger(self.__class__.__name__)

    def _default_cli_name(self) -> str:
        """Return the default Docker CLI binary name."""
        return self.config.docker_cli

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Docker CLI arguments for an operation.

        Args:
            **kwargs: Operation parameters including:
                - command: Docker subcommand (ps, images, run, etc.)
                - Additional command-specific parameters.

        Returns:
            List of CLI argument strings.
        """
        command = kwargs.get("command", "ps")
        args: list[str] = []

        if command == "ps":
            args.extend(["ps", "--format", "{{json .}}"])
            if kwargs.get("all", False):
                args.append("-a")
            filters = kwargs.get("filters")
            if filters and isinstance(filters, dict):
                for key, val in filters.items():
                    args.extend(["--filter", f"{key}={val}"])

        elif command == "images":
            args.extend(["images", "--format", "{{json .}}"])
            filters = kwargs.get("filters")
            if filters and isinstance(filters, dict):
                for key, val in filters.items():
                    args.extend(["--filter", f"{key}={val}"])

        elif command == "start":
            args.extend(["start", kwargs["container"]])

        elif command == "restart":
            args.append("restart")
            timeout = kwargs.get("timeout")
            if timeout is not None:
                args.extend(["-t", str(timeout)])
            args.append(kwargs["container"])

        elif command == "stop":
            args.append("stop")
            timeout = kwargs.get("timeout")
            if timeout is not None:
                args.extend(["-t", str(timeout)])
            args.append(kwargs["container"])

        elif command == "rm":
            args.append("rm")
            if kwargs.get("force", False):
                args.append("-f")
            if kwargs.get("volumes", False):
                args.append("-v")
            args.append(kwargs["container"])

        elif command == "logs":
            args.append("logs")
            tail = kwargs.get("tail", 100)
            args.extend(["--tail", str(tail)])
            since = kwargs.get("since")
            if since:
                args.extend(["--since", since])
            args.append(kwargs["container"])

        elif command == "inspect":
            args.extend(["inspect", "--format", "{{json .}}", kwargs["container"]])

        elif command == "prune_containers":
            args.extend(["container", "prune", "-f"])

        elif command == "prune_images":
            args.extend(["image", "prune", "-f"])

        elif command == "prune_volumes":
            args.extend(["volume", "prune", "-f"])

        elif command == "info":
            args.extend(["info", "--format", "json"])

        return args

    # --- Daemon and Compose detection ---

    async def check_daemon(self) -> bool:
        """Check if Docker daemon is running.

        Returns:
            True if Docker daemon is accessible, False otherwise.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self.config.docker_cli, "info", "--format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except (OSError, asyncio.TimeoutError, Exception):
            return False

    async def check_compose(self) -> bool:
        """Check if docker compose v2 is available.

        Returns:
            True if docker compose is available, False otherwise.
        """
        try:
            parts = self.config.compose_cli.split()
            proc = await asyncio.create_subprocess_exec(
                *parts, "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except (OSError, asyncio.TimeoutError, Exception):
            return False

    # --- Command execution ---

    async def run_command(
        self,
        args: list[str],
        timeout: Optional[int] = None,
    ) -> tuple[str, str, int]:
        """Execute a Docker CLI command asynchronously.

        Args:
            args: CLI arguments (without the docker binary).
            timeout: Timeout in seconds. Defaults to config.timeout.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        cmd = [self.config.docker_cli, *args]
        effective_timeout = timeout or self.config.timeout

        self.logger.debug("Executing: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
            exit_code = proc.returncode or 0

            if exit_code != 0:
                self.logger.warning(
                    "Docker exited with code %d: %s",
                    exit_code,
                    stderr.decode()[:500],
                )

            return stdout.decode(), stderr.decode(), exit_code

        except asyncio.TimeoutError:
            self.logger.error(
                "Docker command timed out after %d seconds", effective_timeout
            )
            try:
                proc.kill()
                await proc.wait()
            except (ProcessLookupError, UnboundLocalError):
                pass
            return "", f"Timeout: execution exceeded {effective_timeout} seconds", -1

        except OSError as e:
            return "", f"Failed to execute docker: {e}", -1

    async def run_compose_command(
        self,
        args: list[str],
        timeout: Optional[int] = None,
    ) -> tuple[str, str, int]:
        """Execute a docker compose command asynchronously.

        Args:
            args: Compose subcommand arguments (without 'docker compose').
            timeout: Timeout in seconds. Defaults to config.timeout.

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        parts = self.config.compose_cli.split()
        cmd = [*parts, *args]
        effective_timeout = timeout or self.config.timeout

        self.logger.debug("Executing: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
            exit_code = proc.returncode or 0

            return stdout.decode(), stderr.decode(), exit_code

        except asyncio.TimeoutError:
            self.logger.error(
                "Docker compose timed out after %d seconds", effective_timeout
            )
            try:
                proc.kill()
                await proc.wait()
            except (ProcessLookupError, UnboundLocalError):
                pass
            return "", f"Timeout: execution exceeded {effective_timeout} seconds", -1

        except OSError as e:
            return "", f"Failed to execute docker compose: {e}", -1

    # --- Output parsing ---

    def parse_ps_output(self, raw: str) -> list[ContainerInfo]:
        """Parse docker ps JSON output into ContainerInfo list.

        Handles both single-line JSON (one per line) and JSON array format.

        Args:
            raw: Raw stdout from `docker ps --format json`.

        Returns:
            List of ContainerInfo objects.
        """
        containers: list[ContainerInfo] = []
        if not raw.strip():
            return containers

        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, list):
                    for item in data:
                        containers.append(self._parse_container(item))
                elif isinstance(data, dict):
                    containers.append(self._parse_container(data))
            except (json.JSONDecodeError, Exception) as e:
                self.logger.debug("Skipping unparseable line: %s", e)
                continue

        return containers

    def _parse_container(self, data: dict) -> ContainerInfo:
        """Parse a single container JSON object.

        Args:
            data: JSON dict from docker ps output.

        Returns:
            ContainerInfo object.
        """
        return ContainerInfo(
            container_id=data.get("ID", data.get("Id", "")),
            name=data.get("Names", data.get("Name", "")),
            image=data.get("Image", ""),
            status=data.get("Status", data.get("State", "")),
            ports=data.get("Ports", ""),
            created=data.get("CreatedAt", data.get("Created", "")),
        )

    def parse_images_output(self, raw: str) -> list[ImageInfo]:
        """Parse docker images JSON output into ImageInfo list.

        Args:
            raw: Raw stdout from `docker images --format json`.

        Returns:
            List of ImageInfo objects.
        """
        images: list[ImageInfo] = []
        if not raw.strip():
            return images

        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, list):
                    for item in data:
                        images.append(self._parse_image(item))
                elif isinstance(data, dict):
                    images.append(self._parse_image(data))
            except (json.JSONDecodeError, Exception) as e:
                self.logger.debug("Skipping unparseable line: %s", e)
                continue

        return images

    def _parse_image(self, data: dict) -> ImageInfo:
        """Parse a single image JSON object.

        Args:
            data: JSON dict from docker images output.

        Returns:
            ImageInfo object.
        """
        return ImageInfo(
            image_id=data.get("ID", data.get("Id", "")),
            repository=data.get("Repository", ""),
            tag=data.get("Tag", "latest"),
            size=data.get("Size", data.get("VirtualSize", "")),
            created=data.get("CreatedAt", data.get("Created", "")),
        )

    # --- CLI argument builders ---

    def build_run_args(self, inp: ContainerRunInput) -> list[str]:
        """Build docker run CLI arguments from ContainerRunInput.

        Args:
            inp: Container run input parameters.

        Returns:
            List of CLI argument strings for `docker run`.
        """
        args: list[str] = ["run"]

        if inp.detach:
            args.append("-d")

        if inp.name:
            args.extend(["--name", inp.name])

        # Port mappings
        for pm in inp.ports:
            port_str = f"{pm.host_port}:{pm.container_port}/{pm.protocol}"
            args.extend(["-p", port_str])

        # Volume mappings
        for vm in inp.volumes:
            vol_str = f"{vm.host_path}:{vm.container_path}"
            if vm.read_only:
                vol_str += ":ro"
            args.extend(["-v", vol_str])

        # Environment variables
        for key, val in inp.env_vars.items():
            args.extend(["-e", f"{key}={val}"])

        # Restart policy
        if inp.restart_policy:
            args.extend(["--restart", inp.restart_policy])

        # Resource limits (from input, fall back to config defaults)
        cpu = inp.cpu_limit or self.config.cpu_limit
        if cpu:
            args.extend(["--cpus", cpu])

        memory = inp.memory_limit or self.config.memory_limit
        if memory:
            args.extend(["--memory", memory])

        # Network
        if self.config.default_network:
            args.extend(["--network", self.config.default_network])

        # Image (must come after all flags)
        args.append(inp.image)

        # Command override (must come after image)
        if inp.command:
            args.extend(shlex.split(inp.command))

        return args

    def build_exec_args(self, inp: DockerExecInput) -> list[str]:
        """Build docker exec CLI arguments from DockerExecInput.

        Args:
            inp: Docker exec input parameters.

        Returns:
            List of CLI argument strings for `docker exec`.
        """
        args: list[str] = ["exec"]

        if inp.workdir:
            args.extend(["-w", inp.workdir])

        if inp.user:
            args.extend(["-u", inp.user])

        for key, val in inp.env_vars.items():
            args.extend(["-e", f"{key}={val}"])

        args.append(inp.container)
        args.extend(shlex.split(inp.command))

        return args

    def build_build_args(self, inp: DockerBuildInput) -> list[str]:
        """Build docker build CLI arguments from DockerBuildInput.

        Args:
            inp: Docker build input parameters.

        Returns:
            List of CLI argument strings for `docker build`.
        """
        args: list[str] = ["build"]

        args.extend(["-t", inp.tag])

        if inp.no_cache:
            args.append("--no-cache")

        for key, val in inp.build_args.items():
            args.extend(["--build-arg", f"{key}={val}"])

        args.append(inp.dockerfile_path)

        return args

    # --- Result helpers ---

    def make_error_result(
        self,
        operation: str,
        error: str,
    ) -> DockerOperationResult:
        """Create a failed DockerOperationResult.

        Args:
            operation: Name of the operation that failed.
            error: Human-readable error message.

        Returns:
            DockerOperationResult with success=False.
        """
        return DockerOperationResult(
            success=False,
            operation=operation,
            error=error,
        )

    def make_success_result(
        self,
        operation: str,
        output: str = "",
        containers: Optional[list[ContainerInfo]] = None,
        images: Optional[list[ImageInfo]] = None,
    ) -> DockerOperationResult:
        """Create a successful DockerOperationResult.

        Args:
            operation: Name of the operation.
            output: Raw output string.
            containers: Optional list of containers.
            images: Optional list of images.

        Returns:
            DockerOperationResult with success=True.
        """
        return DockerOperationResult(
            success=True,
            operation=operation,
            output=output,
            containers=containers or [],
            images=images or [],
        )
