"""Shared fixtures for Docker toolkit tests."""

import pytest

from parrot.tools.docker.config import DockerConfig
from parrot.tools.docker.executor import DockerExecutor
from parrot.tools.docker.models import ComposeServiceDef
from parrot.tools.docker.toolkit import DockerToolkit


@pytest.fixture
def docker_config():
    """Create a default DockerConfig for testing."""
    return DockerConfig(use_docker=False, timeout=30)


@pytest.fixture
def docker_config_with_limits():
    """Create a DockerConfig with resource limits."""
    return DockerConfig(
        use_docker=False,
        timeout=30,
        cpu_limit="2",
        memory_limit="4g",
        default_network="test-net",
    )


@pytest.fixture
def docker_executor(docker_config):
    """Create a DockerExecutor with test config."""
    return DockerExecutor(docker_config)


@pytest.fixture
def docker_toolkit(docker_config):
    """Create a DockerToolkit with test config."""
    return DockerToolkit(config=docker_config)


@pytest.fixture
def sample_compose_services():
    """Sample service definitions for compose generation tests."""
    return {
        "redis": ComposeServiceDef(
            image="redis:alpine",
            ports=["6379:6379"],
            healthcheck={
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "10s",
            },
        ),
        "postgres": ComposeServiceDef(
            image="postgres:16-alpine",
            ports=["5432:5432"],
            environment={
                "POSTGRES_DB": "testdb",
                "POSTGRES_USER": "testuser",
                "POSTGRES_PASSWORD": "testpass",
            },
            volumes=["pgdata:/var/lib/postgresql/data"],
        ),
    }


@pytest.fixture
def mock_docker_ps_output():
    """Mock docker ps JSON output (single line)."""
    return '{"ID":"abc123","Names":"redis","Image":"redis:alpine","Status":"Up 2h","Ports":"6379","CreatedAt":"now"}'


@pytest.fixture
def mock_docker_ps_multi_output():
    """Mock docker ps JSON output (multiple lines)."""
    return (
        '{"ID":"abc123","Names":"redis","Image":"redis:alpine","Status":"Up 2h","Ports":"6379","CreatedAt":"now"}\n'
        '{"ID":"def456","Names":"postgres","Image":"postgres:16","Status":"Up 1h","Ports":"5432","CreatedAt":"now"}'
    )


@pytest.fixture
def mock_docker_images_output():
    """Mock docker images JSON output."""
    return '{"ID":"sha256:abc","Repository":"redis","Tag":"alpine","Size":"30MB","CreatedAt":"now"}'
