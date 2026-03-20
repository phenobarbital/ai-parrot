# Feature Specification: Docker Toolkit

**Feature ID**: FEAT-033
**Date**: 2026-03-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AI agents need direct Docker management capabilities for development, testing, and deployment workflows. Currently, Docker operations require either manual CLI usage or going through the Pulumi abstraction (FEAT-013), which adds unnecessary complexity for straightforward container tasks.

Agents need the ability to:

1. **List running containers/images** — inspect current Docker state
2. **Launch containers** — spin up services on-demand (databases, test environments)
3. **Generate docker-compose files** — dynamically create multi-service configurations
4. **Deploy stacks** — apply docker-compose configurations
5. **View logs** — stream and inspect container logs for debugging
6. **Test services** — health-check running containers
7. **Clean up** — remove containers, images, and prune unused resources
8. **Docker image building from Dockerfile** - create or read Dockerfile files for launching images
9.- **Command Docker execution** - Running commands inside docker images

### Goals
- Implement `DockerToolkit` inheriting from `AbstractToolkit`
- Expose Docker operations as agent tools with the `docker_` prefix
- Support both single-container and docker-compose workflows
- Use async subprocess execution via `asyncio.create_subprocess_exec`
- Generate docker-compose YAML on the fly from Pydantic models
- Provide safe cleanup operations with confirmation semantics

### Non-Goals (explicitly out of scope)
- Docker Swarm orchestration — use Pulumi or dedicated orchestration tools
- Kubernetes integration — separate concern
- Docker registry management (push/pull to private registries) — future enhancement
- Docker network/volume advanced management — keep to basic operations
- Remote Docker daemon connections — local daemon only initially

---

## 2. Architectural Design

### Overview

Follow the **CLI-Based Executor Pattern** established by security toolkits (Checkov, Prowler, Trivy) and the Pulumi toolkit. The toolkit wraps the Docker CLI and docker-compose CLI as an executor with structured input/output parsing.

This approach:
- Uses the battle-tested `BaseExecutor` infrastructure
- Provides consistent async subprocess execution
- Supports Docker execution mode detection (is Docker running?)
- Parses JSON output from `docker inspect`, `docker ps --format json`, etc.

### Component Diagram
```
┌──────────────────────────────────────────────────────────────────┐
│                        DockerToolkit                             │
│  (AbstractToolkit subclass)                                      │
├──────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────┐            │
│  │ docker_ps    │ │ docker_run   │ │ docker_logs   │            │
│  │ docker_images│ │ docker_stop  │ │ docker_inspect│            │
│  │ docker_rm    │ │ docker_prune │ │ docker_compose│            │
│  │              │ │ compose_gen  │ │ compose_up    │            │
│  │              │ │ compose_down │ │ docker_test   │            │
│  └──────┬───────┘ └──────┬───────┘ └───────┬───────┘            │
│         │                │                  │                    │
│         └────────────────┼──────────────────┘                    │
│                          ▼                                       │
│              ┌───────────────────────┐                           │
│              │    DockerExecutor     │                           │
│              │   (BaseExecutor)      │                           │
│              ├───────────────────────┤                           │
│              │ _build_cli_args()     │                           │
│              │ _parse_json_output()  │                           │
│              │ _check_daemon()       │                           │
│              │ run_command()         │                           │
│              └───────────┬───────────┘                           │
│                          │                                       │
│                          ▼                                       │
│              ┌───────────────────────┐                           │
│              │   asyncio.subprocess  │                           │
│              │   docker / compose    │                           │
│              └───────────────────────┘                           │
└──────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Base class for toolkit with auto tool generation |
| `BaseExecutor` | extends | CLI execution pattern from security toolkits |
| `BaseExecutorConfig` | extends | Configuration with timeout, CLI path |
| `ToolRegistry` | uses | Register toolkit for agent discovery |

### Data Models
```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from parrot.tools.security.base_executor import BaseExecutorConfig


class DockerConfig(BaseExecutorConfig):
    """Configuration for Docker executor."""

    docker_cli: str = Field(
        default="docker",
        description="Path to docker CLI binary"
    )
    compose_cli: str = Field(
        default="docker compose",
        description="Docker compose command (v2 plugin)"
    )
    default_network: Optional[str] = Field(
        default=None,
        description="Default Docker network to attach containers"
    )


class ContainerInfo(BaseModel):
    """Information about a Docker container."""

    container_id: str = Field(..., description="Container ID")
    name: str = Field(..., description="Container name")
    image: str = Field(..., description="Image name")
    status: str = Field(..., description="Container status")
    ports: str = Field(default="", description="Port mappings")
    created: str = Field(default="", description="Creation timestamp")


class ImageInfo(BaseModel):
    """Information about a Docker image."""

    image_id: str = Field(..., description="Image ID")
    repository: str = Field(..., description="Repository name")
    tag: str = Field(default="latest", description="Image tag")
    size: str = Field(default="", description="Image size")
    created: str = Field(default="", description="Creation timestamp")


class PortMapping(BaseModel):
    """Port mapping for a container."""

    host_port: int = Field(..., description="Host port")
    container_port: int = Field(..., description="Container port")
    protocol: str = Field(default="tcp", description="Protocol (tcp/udp)")


class VolumeMapping(BaseModel):
    """Volume mapping for a container."""

    host_path: str = Field(..., description="Host path or volume name")
    container_path: str = Field(..., description="Container mount path")
    read_only: bool = Field(default=False, description="Mount as read-only")


class ContainerRunInput(BaseModel):
    """Input for docker_run operation."""

    image: str = Field(..., description="Docker image to run")
    name: Optional[str] = Field(None, description="Container name")
    ports: List[PortMapping] = Field(default_factory=list, description="Port mappings")
    volumes: List[VolumeMapping] = Field(default_factory=list, description="Volume mappings")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    command: Optional[str] = Field(None, description="Override command")
    detach: bool = Field(default=True, description="Run in background")
    restart_policy: Optional[str] = Field(
        default=None, description="Restart policy (no, always, on-failure, unless-stopped)"
    )


class ComposeServiceDef(BaseModel):
    """Definition of a single service in a docker-compose file."""

    image: str = Field(..., description="Docker image")
    ports: List[str] = Field(default_factory=list, description="Port mappings (e.g., '8080:80')")
    volumes: List[str] = Field(default_factory=list, description="Volume mappings")
    environment: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    depends_on: List[str] = Field(default_factory=list, description="Service dependencies")
    restart: str = Field(default="unless-stopped", description="Restart policy")
    command: Optional[str] = Field(None, description="Override command")
    healthcheck: Optional[Dict[str, Any]] = Field(None, description="Health check config")


class ComposeGenerateInput(BaseModel):
    """Input for generating a docker-compose file."""

    project_name: str = Field(..., description="Project name for the compose stack")
    services: Dict[str, ComposeServiceDef] = Field(
        ..., description="Service definitions keyed by service name"
    )
    output_path: str = Field(
        default="./docker-compose.yml",
        description="Path to write the generated file"
    )


class DockerOperationResult(BaseModel):
    """Result of a Docker operation."""

    success: bool
    operation: str
    output: str = ""
    containers: List[ContainerInfo] = []
    images: List[ImageInfo] = []
    error: Optional[str] = None


class PruneResult(BaseModel):
    """Result of a Docker prune operation."""

    success: bool
    containers_removed: int = 0
    images_removed: int = 0
    volumes_removed: int = 0
    space_reclaimed: str = ""
    error: Optional[str] = None
```

### New Public Interfaces
```python
class DockerToolkit(AbstractToolkit):
    """Toolkit for managing Docker containers and compose stacks.

    Each public method is exposed as a separate tool with the `docker_` prefix.

    Available Operations:
    - docker_ps: List running containers
    - docker_images: List available images
    - docker_run: Launch a new container
    - docker_stop: Stop a running container
    - docker_rm: Remove a container
    - docker_logs: View container logs
    - docker_inspect: Get detailed container info
    - docker_prune: Clean up unused resources
    - docker_compose_generate: Generate a docker-compose.yml from service definitions
    - docker_compose_up: Deploy a docker-compose stack
    - docker_compose_down: Tear down a docker-compose stack
    - docker_test: Health-check a running container/service

    Example:
        toolkit = DockerToolkit()
        tools = toolkit.get_tools()

        # Use with agent
        agent = Agent(tools=tools)
    """

    async def docker_ps(
        self,
        all: bool = False,
        filters: Optional[Dict[str, str]] = None
    ) -> DockerOperationResult:
        """List Docker containers.

        Args:
            all: Show all containers (default shows only running)
            filters: Filter output (e.g., {"status": "running", "name": "redis"})

        Returns:
            List of containers with status info
        """
        ...

    async def docker_images(
        self,
        filters: Optional[Dict[str, str]] = None
    ) -> DockerOperationResult:
        """List Docker images.

        Args:
            filters: Filter output (e.g., {"reference": "python*"})

        Returns:
            List of images with size and tag info
        """
        ...

    async def docker_run(
        self,
        image: str,
        name: Optional[str] = None,
        ports: Optional[List[PortMapping]] = None,
        volumes: Optional[List[VolumeMapping]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        command: Optional[str] = None,
        detach: bool = True,
        restart_policy: Optional[str] = None
    ) -> DockerOperationResult:
        """Launch a new Docker container.

        Args:
            image: Docker image to run
            name: Optional container name
            ports: Port mappings (host:container)
            volumes: Volume mappings
            env_vars: Environment variables
            command: Override default command
            detach: Run in background (default True)
            restart_policy: Restart policy

        Returns:
            Result with container info
        """
        ...

    async def docker_stop(
        self,
        container: str,
        timeout: int = 10
    ) -> DockerOperationResult:
        """Stop a running container.

        Args:
            container: Container name or ID
            timeout: Seconds to wait before killing

        Returns:
            Operation result
        """
        ...

    async def docker_rm(
        self,
        container: str,
        force: bool = False,
        volumes: bool = False
    ) -> DockerOperationResult:
        """Remove a Docker container.

        Args:
            container: Container name or ID
            force: Force removal of running container
            volumes: Remove associated volumes

        Returns:
            Operation result
        """
        ...

    async def docker_logs(
        self,
        container: str,
        tail: int = 100,
        since: Optional[str] = None,
        follow: bool = False
    ) -> DockerOperationResult:
        """View container logs.

        Args:
            container: Container name or ID
            tail: Number of lines from the end (default 100)
            since: Show logs since timestamp (e.g., '2h', '2026-01-01')
            follow: Not supported in async context, returns snapshot

        Returns:
            Log output
        """
        ...

    async def docker_inspect(
        self,
        container: str
    ) -> DockerOperationResult:
        """Get detailed container information.

        Args:
            container: Container name or ID

        Returns:
            Detailed container configuration and state
        """
        ...

    async def docker_prune(
        self,
        containers: bool = True,
        images: bool = False,
        volumes: bool = False
    ) -> PruneResult:
        """Clean up unused Docker resources.

        Args:
            containers: Prune stopped containers
            images: Prune dangling images
            volumes: Prune unused volumes (CAUTION: data loss)

        Returns:
            Summary of removed resources and reclaimed space
        """
        ...

    async def docker_compose_generate(
        self,
        project_name: str,
        services: Dict[str, ComposeServiceDef],
        output_path: str = "./docker-compose.yml"
    ) -> DockerOperationResult:
        """Generate a docker-compose.yml file from service definitions.

        Args:
            project_name: Project name
            services: Service definitions
            output_path: Where to write the file

        Returns:
            Result with path to generated file
        """
        ...

    async def docker_compose_up(
        self,
        compose_file: str = "./docker-compose.yml",
        detach: bool = True,
        build: bool = False
    ) -> DockerOperationResult:
        """Deploy a docker-compose stack.

        Args:
            compose_file: Path to docker-compose.yml
            detach: Run in background
            build: Build images before starting

        Returns:
            Result with deployed services info
        """
        ...

    async def docker_compose_down(
        self,
        compose_file: str = "./docker-compose.yml",
        volumes: bool = False,
        remove_orphans: bool = True
    ) -> DockerOperationResult:
        """Tear down a docker-compose stack.

        Args:
            compose_file: Path to docker-compose.yml
            volumes: Remove named volumes
            remove_orphans: Remove containers not defined in compose file

        Returns:
            Operation result
        """
        ...

    async def docker_test(
        self,
        container: str,
        port: Optional[int] = None,
        endpoint: Optional[str] = None
    ) -> DockerOperationResult:
        """Health-check a running container.

        Checks if the container is running and optionally tests
        TCP connectivity to a port or HTTP endpoint.

        Args:
            container: Container name or ID
            port: Port to check TCP connectivity
            endpoint: HTTP URL to test (e.g., 'http://localhost:8080/health')

        Returns:
            Health status result
        """
        ...
```

---

## 3. Module Breakdown

### Module 1: Docker Configuration
- **Path**: `parrot/tools/docker/config.py`
- **Responsibility**: Define `DockerConfig` extending `BaseExecutorConfig` with Docker-specific settings
- **Depends on**: `parrot/tools/security/base_executor.py`

### Module 2: Docker Data Models
- **Path**: `parrot/tools/docker/models.py`
- **Responsibility**: Pydantic models for containers, images, ports, volumes, compose services, and operation results
- **Depends on**: None (standalone Pydantic models)

### Module 3: Docker Executor
- **Path**: `parrot/tools/docker/executor.py`
- **Responsibility**: CLI argument building, async subprocess execution, JSON output parsing, daemon detection
- **Depends on**: Module 1, `BaseExecutor`

### Module 4: Compose Generator
- **Path**: `parrot/tools/docker/compose.py`
- **Responsibility**: Generate docker-compose YAML files from Pydantic `ComposeServiceDef` models
- **Depends on**: Module 2, `pyyaml`

### Module 5: Docker Toolkit
- **Path**: `parrot/tools/docker/toolkit.py`
- **Responsibility**: `AbstractToolkit` subclass exposing all Docker operations as agent tools
- **Depends on**: Modules 2, 3, 4

### Module 6: Package Init
- **Path**: `parrot/tools/docker/__init__.py`
- **Responsibility**: Export `DockerToolkit`, `DockerConfig`, register with toolkit registry
- **Depends on**: Modules 1-5

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_config_defaults` | Module 1 | Validates default configuration values |
| `test_config_custom_cli_path` | Module 1 | Custom docker CLI path |
| `test_container_info_model` | Module 2 | ContainerInfo serialization |
| `test_compose_service_model` | Module 2 | ComposeServiceDef validation |
| `test_port_mapping_model` | Module 2 | PortMapping defaults and validation |
| `test_executor_build_ps_args` | Module 3 | CLI args for `docker ps --format json` |
| `test_executor_build_run_args` | Module 3 | CLI args with ports, volumes, env |
| `test_executor_parse_ps_output` | Module 3 | Parse `docker ps` JSON to ContainerInfo |
| `test_executor_parse_images_output` | Module 3 | Parse `docker images` JSON to ImageInfo |
| `test_executor_daemon_check` | Module 3 | Detect Docker daemon not running |
| `test_compose_generate_single_service` | Module 4 | Generate YAML for one service |
| `test_compose_generate_multi_service` | Module 4 | Generate YAML with dependencies |
| `test_compose_generate_with_healthcheck` | Module 4 | YAML includes healthcheck config |
| `test_toolkit_get_tools` | Module 5 | All 12 tools exposed correctly |
| `test_toolkit_ps_returns_containers` | Module 5 | docker_ps returns structured data |
| `test_toolkit_run_validates_image` | Module 5 | Rejects empty image name |

### Integration Tests
| Test | Description |
|---|---|
| `test_docker_ps_live` | List containers on local Docker daemon |
| `test_docker_run_and_stop` | Run a container, verify running, stop it |
| `test_docker_logs_output` | Retrieve logs from a running container |
| `test_docker_prune_containers` | Prune stopped containers |
| `test_compose_generate_and_up` | Generate compose file, deploy, verify, tear down |
| `test_docker_test_health` | Health-check a running container |

### Test Data / Fixtures
```python
@pytest.fixture
def docker_config():
    """Create a default DockerConfig."""
    return DockerConfig(
        use_docker=False,
        docker_cli="docker",
        timeout=30
    )


@pytest.fixture
def sample_compose_services():
    """Sample service definitions for compose generation."""
    return {
        "redis": ComposeServiceDef(
            image="redis:alpine",
            ports=["6379:6379"],
            restart="unless-stopped",
            healthcheck={
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 3
            }
        ),
        "postgres": ComposeServiceDef(
            image="postgres:16-alpine",
            ports=["5432:5432"],
            environment={
                "POSTGRES_DB": "testdb",
                "POSTGRES_USER": "testuser",
                "POSTGRES_PASSWORD": "testpass"
            },
            volumes=["pgdata:/var/lib/postgresql/data"],
            restart="unless-stopped"
        ),
        "app": ComposeServiceDef(
            image="myapp:latest",
            ports=["8080:8080"],
            depends_on=["redis", "postgres"],
            environment={"DATABASE_URL": "postgresql://testuser:testpass@postgres/testdb"},
            restart="unless-stopped"
        )
    }


@pytest.fixture
def mock_docker_ps_output():
    """Mock docker ps JSON output."""
    return [
        {
            "ID": "abc123",
            "Names": "test-redis",
            "Image": "redis:alpine",
            "Status": "Up 2 hours",
            "Ports": "0.0.0.0:6379->6379/tcp",
            "CreatedAt": "2026-03-09 10:00:00"
        }
    ]
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `DockerToolkit` class exists and inherits from `AbstractToolkit`
- [ ] `docker_ps` lists containers with structured JSON output
- [ ] `docker_images` lists images with size and tag info
- [ ] `docker_run` launches containers with ports, volumes, and env vars
- [ ] `docker_stop` and `docker_rm` manage container lifecycle
- [ ] `docker_logs` returns last N lines of container logs
- [ ] `docker_inspect` returns detailed container configuration
- [ ] `docker_prune` cleans up stopped containers, dangling images, and optionally volumes
- [ ] `docker_compose_generate` creates valid docker-compose.yml from Pydantic models
- [ ] `docker_compose_up` deploys a compose stack
- [ ] `docker_compose_down` tears down a compose stack
- [ ] `docker_test` performs container health checks (running state + optional TCP/HTTP)
- [ ] Docker daemon detection gives clear error when Docker is not running
- [ ] All unit tests pass: `pytest tests/tools/docker/ -v`
- [ ] Integration test runs a container, checks logs, and removes it
- [ ] Error handling returns actionable messages (not stack traces)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `BaseExecutor` pattern from `parrot/tools/security/base_executor.py`
- Follow `PulumiToolkit` style for async CLI-based operations
- Use `docker ps --format '{{json .}}'` for structured output parsing
- Use `docker compose` (v2 plugin syntax, not legacy `docker-compose`)
- Pydantic models for all inputs/outputs
- Comprehensive logging with `self.logger`
- Use `pyyaml` for docker-compose YAML generation

### Known Risks / Gotchas
- **Docker daemon**: Must be running; detect with `docker info` and give clear error
- **Docker socket permissions**: User may need to be in `docker` group; surface permission errors clearly
- **Compose v1 vs v2**: Target `docker compose` (v2 plugin); detect and warn if only v1 available
- **Volume pruning**: Data loss risk; require explicit opt-in and log warnings
- **Long-running containers**: `docker logs --follow` is not suitable for async; use tail-based snapshot
- **Port conflicts**: `docker run` with occupied ports fails; parse error and suggest alternatives

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `docker` (CLI) | `>=20.10` | Docker CLI for all operations |
| `docker compose` (plugin) | `>=2.0` | Compose v2 for stack management |
| `pyyaml` | `>=6.0` | YAML generation for compose files |

### Security Considerations
- Never pass secrets in container names or labels (visible in `docker ps`)
- Environment variables with secrets should use `--env-file` pattern when possible
- Volume mounts should be validated to prevent mounting sensitive host paths (e.g., `/etc/shadow`)
- Prune operations should log what will be removed before executing

---

## 7. Open Questions

- [ ] **Compose file location**: Should generated compose files go in a standard directory (e.g., `./docker/`) or user-specified? — *Owner: architect*: on parrot/conf.py lets create a new environment variable called DOCKER_FILE_LOCATION default to BASE_DIR / docker
- [ ] **Resource limits**: Should `docker_run` support CPU/memory limits to prevent resource exhaustion? — *Owner: platform*: Yes
- [ ] **Docker context**: Should we support remote Docker contexts (e.g., Docker over SSH) in the future? — *Owner: architect*: if feasible.
- [ ] **Image pull**: Should there be a dedicated `docker_pull` tool or let `docker_run` handle pulling automatically? — *Owner: architect*: handle pulling automatically.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-09 | claude-session | Initial draft |
