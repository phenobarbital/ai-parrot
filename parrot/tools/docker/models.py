"""Docker data models for container, image, and compose operations.

Defines all Pydantic models used by the Docker Toolkit (FEAT-033).
These models provide structured input/output for Docker CLI operations.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    ports: List[PortMapping] = Field(
        default_factory=list, description="Port mappings"
    )
    volumes: List[VolumeMapping] = Field(
        default_factory=list, description="Volume mappings"
    )
    env_vars: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    command: Optional[str] = Field(None, description="Override command")
    detach: bool = Field(default=True, description="Run in background")
    restart_policy: Optional[str] = Field(
        default=None,
        description="Restart policy (no, always, on-failure, unless-stopped)",
    )
    cpu_limit: Optional[str] = Field(
        None, description="CPU limit (e.g., '2' for 2 CPUs, '0.5' for half)"
    )
    memory_limit: Optional[str] = Field(
        None, description="Memory limit (e.g., '4g', '512m')"
    )


class ComposeServiceDef(BaseModel):
    """Definition of a single service in a docker-compose file."""

    image: str = Field(..., description="Docker image")
    ports: List[str] = Field(
        default_factory=list, description="Port mappings (e.g., '8080:80')"
    )
    volumes: List[str] = Field(
        default_factory=list, description="Volume mappings"
    )
    environment: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    depends_on: List[str] = Field(
        default_factory=list, description="Service dependencies"
    )
    restart: str = Field(default="unless-stopped", description="Restart policy")
    command: Optional[str] = Field(None, description="Override command")
    healthcheck: Optional[Dict[str, Any]] = Field(
        None, description="Health check config"
    )


class ComposeGenerateInput(BaseModel):
    """Input for generating a docker-compose file."""

    project_name: str = Field(
        ..., description="Project name for the compose stack"
    )
    services: Dict[str, ComposeServiceDef] = Field(
        ..., description="Service definitions keyed by service name"
    )
    output_path: str = Field(
        default="./docker-compose.yml",
        description="Path to write the generated file",
    )


class DockerOperationResult(BaseModel):
    """Result of a Docker operation."""

    success: bool = Field(..., description="Whether the operation succeeded")
    operation: str = Field(..., description="Name of the operation performed")
    output: str = Field(default="", description="Raw output from the operation")
    containers: List[ContainerInfo] = Field(
        default_factory=list, description="Container info list"
    )
    images: List[ImageInfo] = Field(
        default_factory=list, description="Image info list"
    )
    error: Optional[str] = Field(None, description="Error message if failed")


class PruneResult(BaseModel):
    """Result of a Docker prune operation."""

    success: bool = Field(..., description="Whether the prune succeeded")
    containers_removed: int = Field(
        default=0, description="Number of containers removed"
    )
    images_removed: int = Field(
        default=0, description="Number of images removed"
    )
    volumes_removed: int = Field(
        default=0, description="Number of volumes removed"
    )
    space_reclaimed: str = Field(
        default="", description="Amount of disk space reclaimed"
    )
    error: Optional[str] = Field(None, description="Error message if failed")


class DockerBuildInput(BaseModel):
    """Input for docker_build operation."""

    dockerfile_path: str = Field(
        default=".", description="Path to directory containing Dockerfile"
    )
    tag: str = Field(..., description="Image tag (e.g., 'myapp:latest')")
    build_args: Dict[str, str] = Field(
        default_factory=dict, description="Build arguments"
    )
    no_cache: bool = Field(default=False, description="Build without cache")


class DockerExecInput(BaseModel):
    """Input for docker_exec operation."""

    container: str = Field(..., description="Container name or ID")
    command: str = Field(..., description="Command to execute")
    workdir: Optional[str] = Field(
        None, description="Working directory inside container"
    )
    env_vars: Dict[str, str] = Field(
        default_factory=dict, description="Additional environment variables"
    )
    user: Optional[str] = Field(None, description="User to run command as")
