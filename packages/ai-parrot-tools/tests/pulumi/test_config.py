"""Tests for Pulumi configuration and data models."""

import pytest
from pydantic import ValidationError

from parrot.tools.pulumi.config import (
    PulumiApplyInput,
    PulumiConfig,
    PulumiDestroyInput,
    PulumiOperationResult,
    PulumiPlanInput,
    PulumiResource,
    PulumiStatusInput,
)


class TestPulumiConfig:
    """Tests for PulumiConfig model."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = PulumiConfig()
        assert config.docker_image == "pulumi/pulumi:latest"
        assert config.default_stack == "dev"
        assert config.auto_create_stack is True
        assert config.use_docker is True
        assert config.state_backend == "local"
        assert config.non_interactive is True

    def test_custom_values(self):
        """Config accepts custom values."""
        config = PulumiConfig(
            docker_image="pulumi/pulumi:3.100.0",
            default_stack="staging",
            use_docker=False,
            auto_create_stack=False,
            state_backend="file:///tmp/pulumi-state",
        )
        assert config.docker_image == "pulumi/pulumi:3.100.0"
        assert config.default_stack == "staging"
        assert config.use_docker is False
        assert config.auto_create_stack is False
        assert config.state_backend == "file:///tmp/pulumi-state"

    def test_inherits_base_executor_config(self):
        """Config inherits timeout and results_dir from BaseExecutorConfig."""
        config = PulumiConfig(
            timeout=1200,
            results_dir="/tmp/pulumi-results",
            cli_path="/usr/local/bin/pulumi",
        )
        assert config.timeout == 1200
        assert config.results_dir == "/tmp/pulumi-results"
        assert config.cli_path == "/usr/local/bin/pulumi"

    def test_aws_credentials_from_base(self):
        """Config accepts AWS credentials from BaseExecutorConfig."""
        config = PulumiConfig(
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            aws_region="us-west-2",
        )
        assert config.aws_access_key_id == "AKIAIOSFODNN7EXAMPLE"
        assert config.aws_region == "us-west-2"

    def test_pulumi_specific_options(self):
        """Config accepts Pulumi-specific options."""
        config = PulumiConfig(
            pulumi_home="/home/user/.pulumi",
            config_passphrase="secret",
            non_interactive=False,
            skip_preview=True,
        )
        assert config.pulumi_home == "/home/user/.pulumi"
        assert config.config_passphrase == "secret"
        assert config.non_interactive is False
        assert config.skip_preview is True

    def test_extra_fields_ignored(self):
        """Extra fields are ignored due to model_config."""
        config = PulumiConfig(unknown_field="value")
        assert not hasattr(config, "unknown_field")


class TestPulumiInputModels:
    """Tests for Pulumi input models."""

    def test_plan_input_required_fields(self):
        """PulumiPlanInput requires project_path."""
        with pytest.raises(ValidationError):
            PulumiPlanInput()

    def test_plan_input_valid(self):
        """PulumiPlanInput accepts valid input."""
        inp = PulumiPlanInput(project_path="/path/to/project")
        assert inp.project_path == "/path/to/project"
        assert inp.stack_name is None
        assert inp.config is None
        assert inp.refresh is True

    def test_plan_input_with_all_options(self):
        """PulumiPlanInput accepts all optional fields."""
        inp = PulumiPlanInput(
            project_path="/path/to/project",
            stack_name="staging",
            config={"app:port": 8080},
            target=["urn:pulumi:dev::app::docker:Container::redis"],
            refresh=False,
        )
        assert inp.stack_name == "staging"
        assert inp.config == {"app:port": 8080}
        assert inp.target == ["urn:pulumi:dev::app::docker:Container::redis"]
        assert inp.refresh is False

    def test_apply_input_auto_approve_default(self):
        """PulumiApplyInput defaults auto_approve to True."""
        inp = PulumiApplyInput(project_path="/path")
        assert inp.auto_approve is True
        assert inp.refresh is True

    def test_apply_input_required_fields(self):
        """PulumiApplyInput requires project_path."""
        with pytest.raises(ValidationError):
            PulumiApplyInput()

    def test_apply_input_with_all_options(self):
        """PulumiApplyInput accepts all optional fields."""
        inp = PulumiApplyInput(
            project_path="/path/to/project",
            stack_name="prod",
            config={"db:host": "localhost"},
            auto_approve=False,
            target=["urn:pulumi:dev::app::docker:Container::db"],
            refresh=False,
            replace=["urn:pulumi:dev::app::docker:Container::old"],
        )
        assert inp.stack_name == "prod"
        assert inp.auto_approve is False
        assert inp.replace == ["urn:pulumi:dev::app::docker:Container::old"]

    def test_destroy_input_required_fields(self):
        """PulumiDestroyInput requires project_path."""
        with pytest.raises(ValidationError):
            PulumiDestroyInput()

    def test_destroy_input_auto_approve_default(self):
        """PulumiDestroyInput defaults auto_approve to True."""
        inp = PulumiDestroyInput(project_path="/path")
        assert inp.auto_approve is True

    def test_destroy_input_with_all_options(self):
        """PulumiDestroyInput accepts all optional fields."""
        inp = PulumiDestroyInput(
            project_path="/path/to/project",
            stack_name="staging",
            auto_approve=False,
            target=["urn:pulumi:dev::app::docker:Container::redis"],
        )
        assert inp.stack_name == "staging"
        assert inp.auto_approve is False
        assert inp.target == ["urn:pulumi:dev::app::docker:Container::redis"]

    def test_status_input_required_fields(self):
        """PulumiStatusInput requires project_path."""
        with pytest.raises(ValidationError):
            PulumiStatusInput()

    def test_status_input_valid(self):
        """PulumiStatusInput accepts valid input."""
        inp = PulumiStatusInput(project_path="/path/to/project")
        assert inp.project_path == "/path/to/project"
        assert inp.stack_name is None
        assert inp.show_urns is False

    def test_status_input_with_all_options(self):
        """PulumiStatusInput accepts all optional fields."""
        inp = PulumiStatusInput(
            project_path="/path/to/project",
            stack_name="dev",
            show_urns=True,
        )
        assert inp.stack_name == "dev"
        assert inp.show_urns is True


class TestPulumiOutputModels:
    """Tests for Pulumi output models."""

    def test_resource_model(self):
        """PulumiResource captures resource state."""
        resource = PulumiResource(
            urn="urn:pulumi:dev::test::docker:index/container:Container::redis",
            type="docker:index/container:Container",
            name="redis",
            status="create",
        )
        assert resource.urn.startswith("urn:pulumi")
        assert resource.type == "docker:index/container:Container"
        assert resource.name == "redis"
        assert resource.status == "create"
        assert resource.outputs is None
        assert resource.provider is None

    def test_resource_model_with_outputs(self):
        """PulumiResource can include outputs and provider."""
        resource = PulumiResource(
            urn="urn:pulumi:dev::test::docker:index/container:Container::redis",
            type="docker:index/container:Container",
            name="redis",
            status="same",
            outputs={"id": "abc123", "name": "test-redis", "ports": [6379]},
            provider="docker",
        )
        assert resource.outputs == {"id": "abc123", "name": "test-redis", "ports": [6379]}
        assert resource.provider == "docker"

    def test_resource_required_fields(self):
        """PulumiResource requires urn, type, name, status."""
        with pytest.raises(ValidationError):
            PulumiResource(urn="urn:pulumi:dev::test::type::name")

        with pytest.raises(ValidationError):
            PulumiResource(
                urn="urn:pulumi:dev::test::type::name",
                type="docker:Container",
            )

    def test_operation_result_success(self):
        """PulumiOperationResult captures successful operation."""
        result = PulumiOperationResult(
            success=True,
            operation="up",
            resources=[],
            outputs={"url": "http://localhost"},
            summary={"create": 1},
        )
        assert result.success is True
        assert result.operation == "up"
        assert result.outputs == {"url": "http://localhost"}
        assert result.summary == {"create": 1}
        assert result.error is None

    def test_operation_result_failure(self):
        """PulumiOperationResult captures failed operation."""
        result = PulumiOperationResult(
            success=False,
            operation="preview",
            error="Docker daemon not running",
        )
        assert result.success is False
        assert result.error == "Docker daemon not running"
        assert result.resources == []
        assert result.outputs == {}

    def test_operation_result_with_resources(self):
        """PulumiOperationResult can include resource list."""
        resources = [
            PulumiResource(
                urn="urn:pulumi:dev::test::docker:Container::redis",
                type="docker:Container",
                name="redis",
                status="create",
            ),
            PulumiResource(
                urn="urn:pulumi:dev::test::docker:Container::nginx",
                type="docker:Container",
                name="nginx",
                status="update",
            ),
        ]
        result = PulumiOperationResult(
            success=True,
            operation="up",
            resources=resources,
            summary={"create": 1, "update": 1},
            duration_seconds=12.5,
            stack_name="dev",
            project_name="myapp",
        )
        assert len(result.resources) == 2
        assert result.resources[0].name == "redis"
        assert result.duration_seconds == 12.5
        assert result.stack_name == "dev"
        assert result.project_name == "myapp"

    def test_operation_result_required_fields(self):
        """PulumiOperationResult requires success and operation."""
        with pytest.raises(ValidationError):
            PulumiOperationResult(success=True)

        with pytest.raises(ValidationError):
            PulumiOperationResult(operation="up")

    def test_operation_result_defaults(self):
        """PulumiOperationResult has sensible defaults for optional fields."""
        result = PulumiOperationResult(
            success=True,
            operation="stack",
        )
        assert result.resources == []
        assert result.outputs == {}
        assert result.summary == {}
        assert result.duration_seconds is None
        assert result.error is None
        assert result.stack_name is None
        assert result.project_name is None
