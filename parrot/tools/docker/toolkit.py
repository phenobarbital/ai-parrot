"""Docker Toolkit for managing containers and compose stacks.

Exposes all Docker operations as agent tools via AbstractToolkit.
Implements spec Section 3 — Module 5 (FEAT-033).
"""

import json
from typing import Any, Dict, List, Optional

from navconfig.logging import logging

from parrot.tools.toolkit import AbstractToolkit

from .compose import ComposeGenerator
from .config import DockerConfig
from .executor import DockerExecutor
from .models import (
    ComposeServiceDef,
    ContainerRunInput,
    DockerBuildInput,
    DockerExecInput,
    DockerOperationResult,
    PortMapping,
    PruneResult,
    VolumeMapping,
)


class DockerToolkit(AbstractToolkit):
    """Toolkit for managing Docker containers and compose stacks.

    Each public async method is exposed as a separate tool with the `docker_` prefix.

    Available Operations:
    - docker_ps: List running containers
    - docker_images: List available images
    - docker_run: Launch a new container
    - docker_stop: Stop a running container
    - docker_rm: Remove a container
    - docker_logs: View container logs
    - docker_inspect: Get detailed container info
    - docker_prune: Clean up unused resources
    - docker_build: Build a Docker image
    - docker_exec: Execute a command in a container
    - docker_compose_generate: Generate a docker-compose.yml
    - docker_compose_up: Deploy a compose stack
    - docker_compose_down: Tear down a compose stack
    - docker_test: Health-check a running container

    Example:
        toolkit = DockerToolkit()
        tools = toolkit.get_tools()

        # Use with agent
        agent = Agent(tools=tools)
    """

    def __init__(self, config: Optional[DockerConfig] = None, **kwargs):
        """Initialize the Docker toolkit.

        Args:
            config: Docker configuration. Uses defaults if not provided.
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.config = config or DockerConfig()
        self.executor = DockerExecutor(self.config)
        self.compose_gen = ComposeGenerator()
        self.logger = logging.getLogger(self.__class__.__name__)

    async def _check_daemon(self, operation: str) -> Optional[DockerOperationResult]:
        """Check Docker daemon availability.

        Args:
            operation: Name of the operation requesting the check.

        Returns:
            DockerOperationResult with error if daemon is not running, None otherwise.
        """
        if not await self.executor.check_daemon():
            return self.executor.make_error_result(
                operation,
                "Docker daemon is not running. Start Docker and try again.",
            )
        return None

    # --- Inspect tools ---

    async def docker_ps(
        self,
        all: bool = False,
        filters: Optional[Dict[str, str]] = None,
    ) -> DockerOperationResult:
        """List Docker containers.

        Args:
            all: Show all containers (default shows only running).
            filters: Filter output (e.g., {"status": "running", "name": "redis"}).

        Returns:
            List of containers with status info.
        """
        err = await self._check_daemon("docker_ps")
        if err:
            return err

        args = self.executor._build_cli_args(
            command="ps", all=all, filters=filters
        )
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_ps", stderr.strip() or "Failed to list containers"
            )

        containers = self.executor.parse_ps_output(stdout)
        return self.executor.make_success_result(
            "docker_ps", output=stdout, containers=containers
        )

    async def docker_images(
        self,
        filters: Optional[Dict[str, str]] = None,
    ) -> DockerOperationResult:
        """List Docker images.

        Args:
            filters: Filter output (e.g., {"reference": "python*"}).

        Returns:
            List of images with size and tag info.
        """
        err = await self._check_daemon("docker_images")
        if err:
            return err

        args = self.executor._build_cli_args(command="images", filters=filters)
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_images", stderr.strip() or "Failed to list images"
            )

        images = self.executor.parse_images_output(stdout)
        return self.executor.make_success_result(
            "docker_images", output=stdout, images=images
        )

    async def docker_inspect(
        self,
        container: str,
    ) -> DockerOperationResult:
        """Get detailed container information.

        Args:
            container: Container name or ID.

        Returns:
            Detailed container configuration and state.
        """
        err = await self._check_daemon("docker_inspect")
        if err:
            return err

        args = self.executor._build_cli_args(
            command="inspect", container=container
        )
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_inspect",
                stderr.strip() or f"Failed to inspect container '{container}'",
            )

        return self.executor.make_success_result(
            "docker_inspect", output=stdout
        )

    async def docker_logs(
        self,
        container: str,
        tail: int = 100,
        since: Optional[str] = None,
    ) -> DockerOperationResult:
        """View container logs.

        Args:
            container: Container name or ID.
            tail: Number of lines from the end (default 100).
            since: Show logs since timestamp (e.g., '2h', '2026-01-01').

        Returns:
            Log output.
        """
        err = await self._check_daemon("docker_logs")
        if err:
            return err

        args = self.executor._build_cli_args(
            command="logs", container=container, tail=tail, since=since
        )
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_logs",
                stderr.strip() or f"Failed to get logs for '{container}'",
            )

        # docker logs outputs to both stdout and stderr
        output = stdout or stderr
        return self.executor.make_success_result(
            "docker_logs", output=output
        )

    # --- Lifecycle tools ---

    async def docker_run(
        self,
        image: str,
        name: Optional[str] = None,
        ports: Optional[List[Dict[str, Any]]] = None,
        volumes: Optional[List[Dict[str, Any]]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        command: Optional[str] = None,
        detach: bool = True,
        restart_policy: Optional[str] = None,
        cpu_limit: Optional[str] = None,
        memory_limit: Optional[str] = None,
    ) -> DockerOperationResult:
        """Launch a new Docker container.

        Args:
            image: Docker image to run.
            name: Optional container name.
            ports: Port mappings as list of dicts with host_port, container_port, protocol.
            volumes: Volume mappings as list of dicts with host_path, container_path, read_only.
            env_vars: Environment variables.
            command: Override default command.
            detach: Run in background (default True).
            restart_policy: Restart policy (no, always, on-failure, unless-stopped).
            cpu_limit: CPU limit (e.g., '2' for 2 CPUs).
            memory_limit: Memory limit (e.g., '4g', '512m').

        Returns:
            Result with container info.
        """
        err = await self._check_daemon("docker_run")
        if err:
            return err

        # Build typed input model
        port_mappings = (
            [PortMapping(**p) for p in ports] if ports else []
        )
        volume_mappings = (
            [VolumeMapping(**v) for v in volumes] if volumes else []
        )

        run_input = ContainerRunInput(
            image=image,
            name=name,
            ports=port_mappings,
            volumes=volume_mappings,
            env_vars=env_vars or {},
            command=command,
            detach=detach,
            restart_policy=restart_policy,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
        )

        args = self.executor.build_run_args(run_input)
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            error_msg = stderr.strip()
            if "port is already allocated" in error_msg:
                error_msg += " — Try a different host port."
            elif "No such image" in error_msg:
                error_msg += " — Check the image name or pull it first."
            return self.executor.make_error_result("docker_run", error_msg)

        return self.executor.make_success_result(
            "docker_run", output=stdout.strip()
        )

    async def docker_stop(
        self,
        container: str,
        timeout: int = 10,
    ) -> DockerOperationResult:
        """Stop a running container.

        Args:
            container: Container name or ID.
            timeout: Seconds to wait before killing.

        Returns:
            Operation result.
        """
        err = await self._check_daemon("docker_stop")
        if err:
            return err

        args = self.executor._build_cli_args(
            command="stop", container=container, timeout=timeout
        )
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_stop",
                stderr.strip() or f"Failed to stop container '{container}'",
            )

        return self.executor.make_success_result(
            "docker_stop", output=stdout.strip()
        )

    async def docker_rm(
        self,
        container: str,
        force: bool = False,
        volumes: bool = False,
    ) -> DockerOperationResult:
        """Remove a Docker container.

        Args:
            container: Container name or ID.
            force: Force removal of running container.
            volumes: Remove associated volumes.

        Returns:
            Operation result.
        """
        err = await self._check_daemon("docker_rm")
        if err:
            return err

        args = self.executor._build_cli_args(
            command="rm", container=container, force=force, volumes=volumes
        )
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_rm",
                stderr.strip() or f"Failed to remove container '{container}'",
            )

        return self.executor.make_success_result(
            "docker_rm", output=stdout.strip()
        )

    # --- Build tool ---

    async def docker_build(
        self,
        tag: str,
        dockerfile_path: str = ".",
        build_args: Optional[Dict[str, str]] = None,
        no_cache: bool = False,
    ) -> DockerOperationResult:
        """Build a Docker image from a Dockerfile.

        Args:
            tag: Image tag (e.g., 'myapp:latest').
            dockerfile_path: Path to directory containing Dockerfile.
            build_args: Build arguments as key-value pairs.
            no_cache: Build without cache.

        Returns:
            Operation result with build output.
        """
        err = await self._check_daemon("docker_build")
        if err:
            return err

        build_input = DockerBuildInput(
            dockerfile_path=dockerfile_path,
            tag=tag,
            build_args=build_args or {},
            no_cache=no_cache,
        )

        args = self.executor.build_build_args(build_input)
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_build",
                stderr.strip() or "Failed to build image",
            )

        return self.executor.make_success_result(
            "docker_build", output=stdout.strip() or stderr.strip()
        )

    # --- Exec tool ---

    async def docker_exec(
        self,
        container: str,
        command: str,
        workdir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        user: Optional[str] = None,
    ) -> DockerOperationResult:
        """Execute a command inside a running container.

        Args:
            container: Container name or ID.
            command: Command to execute.
            workdir: Working directory inside container.
            env_vars: Additional environment variables.
            user: User to run command as.

        Returns:
            Operation result with command output.
        """
        err = await self._check_daemon("docker_exec")
        if err:
            return err

        exec_input = DockerExecInput(
            container=container,
            command=command,
            workdir=workdir,
            env_vars=env_vars or {},
            user=user,
        )

        args = self.executor.build_exec_args(exec_input)
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_exec",
                stderr.strip() or f"Failed to exec in container '{container}'",
            )

        return self.executor.make_success_result(
            "docker_exec", output=stdout.strip()
        )

    # --- Compose tools ---

    async def docker_compose_generate(
        self,
        project_name: str,
        services: Dict[str, Dict[str, Any]],
        output_path: str = "./docker-compose.yml",
    ) -> DockerOperationResult:
        """Generate a docker-compose.yml file from service definitions.

        Args:
            project_name: Project name for the compose stack.
            services: Service definitions as dicts (converted to ComposeServiceDef).
            output_path: Where to write the file.

        Returns:
            Result with path to generated file.
        """
        try:
            svc_models = {
                name: ComposeServiceDef(**svc_def)
                for name, svc_def in services.items()
            }
            path = await self.compose_gen.generate(
                project_name, svc_models, output_path=output_path
            )
            return self.executor.make_success_result(
                "docker_compose_generate",
                output=f"Generated compose file: {path}",
            )
        except Exception as e:
            return self.executor.make_error_result(
                "docker_compose_generate", str(e)
            )

    async def docker_compose_up(
        self,
        compose_file: str = "./docker-compose.yml",
        detach: bool = True,
        build: bool = False,
    ) -> DockerOperationResult:
        """Deploy a docker-compose stack.

        Args:
            compose_file: Path to docker-compose.yml.
            detach: Run in background.
            build: Build images before starting.

        Returns:
            Result with deployed services info.
        """
        err = await self._check_daemon("docker_compose_up")
        if err:
            return err

        args = ["-f", compose_file, "up"]
        if detach:
            args.append("-d")
        if build:
            args.append("--build")

        stdout, stderr, code = await self.executor.run_compose_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_compose_up",
                stderr.strip() or "Failed to deploy compose stack",
            )

        return self.executor.make_success_result(
            "docker_compose_up", output=stdout.strip() or stderr.strip()
        )

    async def docker_compose_down(
        self,
        compose_file: str = "./docker-compose.yml",
        volumes: bool = False,
        remove_orphans: bool = True,
    ) -> DockerOperationResult:
        """Tear down a docker-compose stack.

        Args:
            compose_file: Path to docker-compose.yml.
            volumes: Remove named volumes.
            remove_orphans: Remove containers not defined in compose file.

        Returns:
            Operation result.
        """
        err = await self._check_daemon("docker_compose_down")
        if err:
            return err

        args = ["-f", compose_file, "down"]
        if volumes:
            args.append("-v")
        if remove_orphans:
            args.append("--remove-orphans")

        stdout, stderr, code = await self.executor.run_compose_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_compose_down",
                stderr.strip() or "Failed to tear down compose stack",
            )

        return self.executor.make_success_result(
            "docker_compose_down", output=stdout.strip() or stderr.strip()
        )

    # --- Ops tools ---

    async def docker_prune(
        self,
        containers: bool = True,
        images: bool = False,
        volumes: bool = False,
    ) -> PruneResult:
        """Clean up unused Docker resources.

        Args:
            containers: Prune stopped containers.
            images: Prune dangling images.
            volumes: Prune unused volumes (CAUTION: data loss).

        Returns:
            Summary of removed resources and reclaimed space.
        """
        daemon_err = await self._check_daemon("docker_prune")
        if daemon_err:
            return PruneResult(
                success=False,
                error="Docker daemon is not running. Start Docker and try again.",
            )

        if volumes:
            self.logger.warning(
                "Volume pruning requested — this may cause data loss!"
            )

        containers_removed = 0
        images_removed = 0
        volumes_removed = 0
        space_parts: list[str] = []

        if containers:
            args = self.executor._build_cli_args(command="prune_containers")
            stdout, stderr, code = await self.executor.run_command(args)
            if code == 0:
                containers_removed = self._count_pruned(stdout)
                space = self._extract_space(stdout)
                if space:
                    space_parts.append(space)

        if images:
            args = self.executor._build_cli_args(command="prune_images")
            stdout, stderr, code = await self.executor.run_command(args)
            if code == 0:
                images_removed = self._count_pruned(stdout)
                space = self._extract_space(stdout)
                if space:
                    space_parts.append(space)

        if volumes:
            args = self.executor._build_cli_args(command="prune_volumes")
            stdout, stderr, code = await self.executor.run_command(args)
            if code == 0:
                volumes_removed = self._count_pruned(stdout)
                space = self._extract_space(stdout)
                if space:
                    space_parts.append(space)

        return PruneResult(
            success=True,
            containers_removed=containers_removed,
            images_removed=images_removed,
            volumes_removed=volumes_removed,
            space_reclaimed=", ".join(space_parts) if space_parts else "",
        )

    async def docker_test(
        self,
        container: str,
        port: Optional[int] = None,
        endpoint: Optional[str] = None,
    ) -> DockerOperationResult:
        """Health-check a running container.

        Checks if the container is running and optionally tests
        TCP connectivity to a port or HTTP endpoint.

        Args:
            container: Container name or ID.
            port: Port to check TCP connectivity.
            endpoint: HTTP URL to test (e.g., 'http://localhost:8080/health').

        Returns:
            Health status result.
        """
        err = await self._check_daemon("docker_test")
        if err:
            return err

        # Check container is running
        args = self.executor._build_cli_args(
            command="inspect", container=container
        )
        stdout, stderr, code = await self.executor.run_command(args)

        if code != 0:
            return self.executor.make_error_result(
                "docker_test",
                f"Container '{container}' not found: {stderr.strip()}",
            )

        # Parse state
        try:
            data = json.loads(stdout)
            if isinstance(data, list) and data:
                data = data[0]
            state = data.get("State", {})
            running = state.get("Running", False) if isinstance(state, dict) else False
        except (json.JSONDecodeError, TypeError):
            running = False

        if not running:
            return self.executor.make_error_result(
                "docker_test",
                f"Container '{container}' is not running.",
            )

        health_info = [f"Container '{container}' is running."]

        # TCP port check
        if port is not None:
            tcp_args = ["exec", container, "sh", "-c", f"echo > /dev/tcp/localhost/{port}"]
            _, _, tcp_code = await self.executor.run_command(tcp_args)
            if tcp_code == 0:
                health_info.append(f"Port {port}: reachable.")
            else:
                health_info.append(f"Port {port}: not reachable.")

        # HTTP endpoint check
        if endpoint is not None:
            curl_args = [
                "exec", container, "sh", "-c",
                f"wget -q -O /dev/null --spider {endpoint} 2>/dev/null || "
                f"curl -sf -o /dev/null {endpoint}",
            ]
            _, _, http_code = await self.executor.run_command(curl_args)
            if http_code == 0:
                health_info.append(f"Endpoint {endpoint}: healthy.")
            else:
                health_info.append(f"Endpoint {endpoint}: unhealthy.")

        return self.executor.make_success_result(
            "docker_test", output=" ".join(health_info)
        )

    # --- Private helpers ---

    def _count_pruned(self, output: str) -> int:
        """Count items removed from prune output.

        Args:
            output: Raw stdout from a prune command.

        Returns:
            Number of items removed.
        """
        count = 0
        for line in output.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("Total") and not line.startswith("deleted"):
                count += 1
        return max(count - 1, 0)  # Subtract header line

    def _extract_space(self, output: str) -> str:
        """Extract reclaimed space from prune output.

        Args:
            output: Raw stdout from a prune command.

        Returns:
            Space reclaimed string or empty string.
        """
        for line in output.strip().split("\n"):
            if "reclaimed" in line.lower():
                return line.strip()
        return ""
