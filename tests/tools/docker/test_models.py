"""Tests for Docker data models (TASK-234)."""

import pytest

from parrot.tools.docker.models import (
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

ALL_MODELS = [
    ContainerInfo,
    ImageInfo,
    PortMapping,
    VolumeMapping,
    ContainerRunInput,
    ComposeServiceDef,
    ComposeGenerateInput,
    DockerOperationResult,
    PruneResult,
    DockerBuildInput,
    DockerExecInput,
]


class TestDockerModels:
    """Unit tests for all Docker data models."""

    def test_container_info(self):
        info = ContainerInfo(
            container_id="abc123", name="redis", image="redis:alpine", status="Up"
        )
        assert info.container_id == "abc123"
        assert info.name == "redis"
        assert info.ports == ""
        assert info.created == ""

    def test_image_info(self):
        img = ImageInfo(image_id="sha256:abc", repository="python")
        assert img.tag == "latest"
        assert img.size == ""

    def test_port_mapping_defaults(self):
        pm = PortMapping(host_port=8080, container_port=80)
        assert pm.protocol == "tcp"

    def test_volume_mapping_defaults(self):
        vm = VolumeMapping(host_path="/data", container_path="/app/data")
        assert vm.read_only is False

    def test_container_run_input_defaults(self):
        run = ContainerRunInput(image="python:3.12")
        assert run.detach is True
        assert run.ports == []
        assert run.volumes == []
        assert run.env_vars == {}
        assert run.command is None
        assert run.restart_policy is None
        assert run.cpu_limit is None
        assert run.memory_limit is None

    def test_container_run_with_limits(self):
        run = ContainerRunInput(
            image="python:3.12", cpu_limit="2", memory_limit="4g"
        )
        assert run.cpu_limit == "2"
        assert run.memory_limit == "4g"

    def test_compose_service_def(self):
        svc = ComposeServiceDef(image="nginx:latest", ports=["80:80"])
        assert svc.restart == "unless-stopped"
        assert svc.depends_on == []
        assert svc.environment == {}
        assert svc.healthcheck is None

    def test_compose_generate_input(self):
        svc = ComposeServiceDef(image="redis:alpine")
        inp = ComposeGenerateInput(
            project_name="test", services={"redis": svc}
        )
        assert inp.output_path == "./docker-compose.yml"

    def test_docker_operation_result_success(self):
        result = DockerOperationResult(
            success=True, operation="docker_ps", output="ok"
        )
        assert result.success is True
        assert result.containers == []
        assert result.images == []
        assert result.error is None

    def test_docker_operation_result_failure(self):
        result = DockerOperationResult(
            success=False, operation="docker_run", error="daemon not running"
        )
        assert result.success is False
        assert result.error == "daemon not running"

    def test_prune_result_defaults(self):
        pr = PruneResult(success=True)
        assert pr.containers_removed == 0
        assert pr.images_removed == 0
        assert pr.volumes_removed == 0
        assert pr.space_reclaimed == ""
        assert pr.error is None

    def test_docker_build_input(self):
        build = DockerBuildInput(tag="myapp:v1")
        assert build.dockerfile_path == "."
        assert build.no_cache is False
        assert build.build_args == {}

    def test_docker_exec_input(self):
        ex = DockerExecInput(container="redis", command="redis-cli ping")
        assert ex.user is None
        assert ex.workdir is None
        assert ex.env_vars == {}

    @pytest.mark.parametrize("model_cls", ALL_MODELS)
    def test_json_schema_generation(self, model_cls):
        """Verify model_json_schema() works for all models."""
        schema = model_cls.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
