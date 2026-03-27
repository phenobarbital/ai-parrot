"""Tests for Docker configuration (TASK-239)."""

from parrot.tools.docker.config import DockerConfig


class TestDockerConfig:
    """Unit tests for DockerConfig."""

    def test_default_values(self):
        config = DockerConfig()
        assert config.docker_cli == "docker"
        assert config.compose_cli == "docker compose"
        assert config.default_network is None
        assert config.cpu_limit is None
        assert config.memory_limit is None

    def test_inherited_defaults(self):
        config = DockerConfig()
        assert config.use_docker is True
        assert config.timeout == 600

    def test_custom_docker_cli(self):
        config = DockerConfig(docker_cli="/usr/local/bin/docker")
        assert config.docker_cli == "/usr/local/bin/docker"

    def test_custom_compose_cli(self):
        config = DockerConfig(compose_cli="docker-compose")
        assert config.compose_cli == "docker-compose"

    def test_custom_network(self):
        config = DockerConfig(default_network="my-network")
        assert config.default_network == "my-network"

    def test_resource_limits(self):
        config = DockerConfig(cpu_limit="2", memory_limit="4g")
        assert config.cpu_limit == "2"
        assert config.memory_limit == "4g"

    def test_custom_timeout(self):
        config = DockerConfig(timeout=30)
        assert config.timeout == 30

    def test_extra_fields_ignored(self):
        config = DockerConfig(unknown_field="value")
        assert not hasattr(config, "unknown_field")

    def test_json_schema(self):
        schema = DockerConfig.model_json_schema()
        assert "properties" in schema
        assert "docker_cli" in schema["properties"]
        assert "compose_cli" in schema["properties"]
        assert "cpu_limit" in schema["properties"]
        assert "memory_limit" in schema["properties"]

    def test_serialization_roundtrip(self):
        config = DockerConfig(
            docker_cli="/opt/docker",
            cpu_limit="1.5",
            memory_limit="2g",
            default_network="bridge",
            timeout=60,
        )
        data = config.model_dump()
        restored = DockerConfig(**data)
        assert restored.docker_cli == "/opt/docker"
        assert restored.cpu_limit == "1.5"
        assert restored.memory_limit == "2g"
        assert restored.default_network == "bridge"
        assert restored.timeout == 60
