"""Tests for Docker Compose Generator (TASK-236)."""

import pytest
import yaml
from pathlib import Path

from parrot.tools.docker.compose import ComposeGenerator
from parrot.tools.docker.models import ComposeServiceDef


class TestComposeGenerator:
    """Unit tests for ComposeGenerator."""

    def test_to_dict_single_service(self):
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(image="redis:alpine", ports=["6379:6379"])
        }
        result = gen.to_dict("test", services)
        assert "services" in result
        assert "redis" in result["services"]
        assert result["services"]["redis"]["image"] == "redis:alpine"
        assert result["services"]["redis"]["ports"] == ["6379:6379"]
        assert result["version"] == "3.8"

    def test_to_dict_with_depends_on(self):
        gen = ComposeGenerator()
        services = {
            "db": ComposeServiceDef(image="postgres:16"),
            "app": ComposeServiceDef(image="myapp:latest", depends_on=["db"]),
        }
        result = gen.to_dict("test", services)
        assert result["services"]["app"]["depends_on"] == ["db"]
        assert "depends_on" not in result["services"]["db"]

    def test_to_dict_with_healthcheck(self):
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(
                image="redis:alpine",
                healthcheck={
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "10s",
                },
            )
        }
        result = gen.to_dict("test", services)
        assert "healthcheck" in result["services"]["redis"]
        assert result["services"]["redis"]["healthcheck"]["interval"] == "10s"

    def test_to_dict_with_environment(self):
        gen = ComposeGenerator()
        services = {
            "db": ComposeServiceDef(
                image="postgres:16",
                environment={"POSTGRES_DB": "test", "POSTGRES_USER": "admin"},
            )
        }
        result = gen.to_dict("test", services)
        assert result["services"]["db"]["environment"]["POSTGRES_DB"] == "test"

    def test_to_dict_with_command(self):
        gen = ComposeGenerator()
        services = {
            "app": ComposeServiceDef(
                image="myapp:latest", command="python main.py"
            )
        }
        result = gen.to_dict("test", services)
        assert result["services"]["app"]["command"] == "python main.py"

    def test_to_dict_restart_default(self):
        gen = ComposeGenerator()
        services = {"app": ComposeServiceDef(image="myapp:latest")}
        result = gen.to_dict("test", services)
        assert result["services"]["app"]["restart"] == "unless-stopped"

    def test_to_dict_no_empty_fields(self):
        """Empty lists/dicts should be omitted from output."""
        gen = ComposeGenerator()
        services = {"app": ComposeServiceDef(image="myapp:latest")}
        result = gen.to_dict("test", services)
        svc = result["services"]["app"]
        assert "ports" not in svc
        assert "volumes" not in svc
        assert "environment" not in svc
        assert "depends_on" not in svc
        assert "command" not in svc
        assert "healthcheck" not in svc

    def test_named_volumes_extracted(self):
        gen = ComposeGenerator()
        services = {
            "db": ComposeServiceDef(
                image="postgres:16",
                volumes=["pgdata:/var/lib/postgresql/data"],
            )
        }
        result = gen.to_dict("test", services)
        assert "volumes" in result
        assert "pgdata" in result["volumes"]

    def test_host_path_volumes_not_extracted(self):
        gen = ComposeGenerator()
        services = {
            "app": ComposeServiceDef(
                image="myapp:latest",
                volumes=["./data:/app/data", "/host/path:/container/path"],
            )
        }
        result = gen.to_dict("test", services)
        assert "volumes" not in result

    def test_mixed_volumes(self):
        gen = ComposeGenerator()
        services = {
            "db": ComposeServiceDef(
                image="postgres:16",
                volumes=[
                    "pgdata:/var/lib/postgresql/data",
                    "./init:/docker-entrypoint-initdb.d",
                ],
            )
        }
        result = gen.to_dict("test", services)
        assert "volumes" in result
        assert "pgdata" in result["volumes"]

    @pytest.mark.asyncio
    async def test_generate_writes_file(self, tmp_path):
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(image="redis:alpine")
        }
        output = str(tmp_path / "docker-compose.yml")
        path = await gen.generate("test", services, output_path=output)
        assert Path(path).exists()
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "services" in data
        assert data["services"]["redis"]["image"] == "redis:alpine"

    @pytest.mark.asyncio
    async def test_generate_creates_parent_dirs(self, tmp_path):
        gen = ComposeGenerator()
        services = {"app": ComposeServiceDef(image="myapp:latest")}
        output = str(tmp_path / "subdir" / "nested" / "docker-compose.yml")
        path = await gen.generate("test", services, output_path=output)
        assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_generate_valid_yaml(self, tmp_path):
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(
                image="redis:alpine",
                ports=["6379:6379"],
                healthcheck={
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "10s",
                },
            ),
            "app": ComposeServiceDef(
                image="myapp:latest",
                depends_on=["redis"],
                environment={"REDIS_URL": "redis://redis:6379"},
                volumes=["appdata:/app/data"],
            ),
        }
        output = str(tmp_path / "docker-compose.yml")
        path = await gen.generate("test", services, output_path=output)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["version"] == "3.8"
        assert len(data["services"]) == 2
        assert "volumes" in data
        assert "appdata" in data["volumes"]

    def test_multi_service_compose(self):
        """Full multi-service compose from spec fixtures."""
        gen = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(
                image="redis:alpine",
                ports=["6379:6379"],
                restart="unless-stopped",
                healthcheck={
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "10s",
                    "timeout": "5s",
                    "retries": 3,
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
                restart="unless-stopped",
            ),
            "app": ComposeServiceDef(
                image="myapp:latest",
                ports=["8080:8080"],
                depends_on=["redis", "postgres"],
                environment={
                    "DATABASE_URL": "postgresql://testuser:testpass@postgres/testdb"
                },
                restart="unless-stopped",
            ),
        }
        result = gen.to_dict("myproject", services)
        assert len(result["services"]) == 3
        assert result["services"]["app"]["depends_on"] == ["redis", "postgres"]
        assert "pgdata" in result["volumes"]
