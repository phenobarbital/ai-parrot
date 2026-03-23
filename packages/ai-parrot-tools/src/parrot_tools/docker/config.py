"""Docker executor configuration.

Defines configuration options for running Docker CLI operations including
container management, compose operations, and resource limits.
"""

from typing import Optional

from pydantic import Field

# Import directly from module to avoid security package __init__.py chain
from parrot.tools.security.base_executor import BaseExecutorConfig


class DockerConfig(BaseExecutorConfig):
    """Configuration for Docker executor.

    Extends BaseExecutorConfig with Docker-specific settings for
    CLI paths, networking, and default resource limits.

    Example:
        config = DockerConfig(
            docker_cli="docker",
            compose_cli="docker compose",
            cpu_limit="2",
            memory_limit="4g",
        )
    """

    # Docker CLI
    docker_cli: str = Field(
        default="docker",
        description="Path to docker CLI binary",
    )
    compose_cli: str = Field(
        default="docker compose",
        description="Docker compose command (v2 plugin syntax)",
    )

    # Networking
    default_network: Optional[str] = Field(
        default=None,
        description="Default Docker network to attach containers to",
    )

    # Default resource limits
    cpu_limit: Optional[str] = Field(
        default=None,
        description="Default CPU limit for containers (e.g., '0.5', '2')",
    )
    memory_limit: Optional[str] = Field(
        default=None,
        description="Default memory limit for containers (e.g., '512m', '2g')",
    )

    model_config = {"extra": "ignore"}
