"""Docker Toolkit — manage containers and compose stacks.

Provides agent tools for Docker operations:
- docker_ps: List containers
- docker_images: List images
- docker_run: Launch containers
- docker_stop / docker_rm: Container lifecycle
- docker_logs / docker_inspect: Container inspection
- docker_build: Build images from Dockerfiles
- docker_exec: Run commands inside containers
- docker_prune: Clean up unused resources
- docker_compose_generate / docker_compose_up / docker_compose_down: Compose workflows
- docker_test: Health-check containers

Example:
    from parrot.tools.docker import DockerToolkit

    toolkit = DockerToolkit()
    agent = Agent(tools=toolkit.get_tools())

Or with custom configuration:
    from parrot.tools.docker import DockerToolkit, DockerConfig

    config = DockerConfig(
        docker_cli="docker",
        cpu_limit="2",
        memory_limit="4g",
    )
    toolkit = DockerToolkit(config)
"""

from .compose import ComposeGenerator
from .config import DockerConfig
from .executor import DockerExecutor
from .models import (
    ComposeGenerateInput,
    ComposeServiceDef,
    ContainerInfo,
    ContainerRunInput,
    DockerBuildInput,
    DockerExecInput,
    DockerOperationResult,
    ImageInfo,
    PortMapping,
    PruneResult,
    VolumeMapping,
)
from .toolkit import DockerToolkit

__all__ = [
    # Main classes
    "DockerToolkit",
    "DockerExecutor",
    "DockerConfig",
    "ComposeGenerator",
    # Input models
    "ContainerRunInput",
    "DockerBuildInput",
    "DockerExecInput",
    "ComposeServiceDef",
    "ComposeGenerateInput",
    "PortMapping",
    "VolumeMapping",
    # Output models
    "ContainerInfo",
    "ImageInfo",
    "DockerOperationResult",
    "PruneResult",
]

# Note: DockerToolkit is registered in parrot/tools/registry.py
# via the _get_supported_toolkits() function for lazy loading.
