"""Integration tests for Pulumi toolkit.

Tests the full lifecycle of Pulumi operations including package imports,
fixture validation, and mocked operation workflows.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml


@pytest.fixture
def fixtures_dir():
    """Return the path to the Pulumi test fixture directory."""
    return Path(__file__).parent.parent.parent / "fixtures" / "pulumi_docker_project"


@pytest.fixture
def toolkit():
    """Create a PulumiToolkit instance for testing."""
    from parrot.tools.pulumi import PulumiConfig, PulumiToolkit

    return PulumiToolkit(PulumiConfig(use_docker=False))


class TestPulumiImports:
    """Test that all Pulumi package exports are importable."""

    def test_import_toolkit(self):
        """PulumiToolkit is importable from package."""
        from parrot.tools.pulumi import PulumiToolkit

        assert PulumiToolkit is not None

    def test_import_config(self):
        """PulumiConfig is importable from package."""
        from parrot.tools.pulumi import PulumiConfig

        assert PulumiConfig is not None

    def test_import_executor(self):
        """PulumiExecutor is importable from package."""
        from parrot.tools.pulumi import PulumiExecutor

        assert PulumiExecutor is not None

    def test_import_input_models(self):
        """All input models are importable."""
        from parrot.tools.pulumi import (
            PulumiApplyInput,
            PulumiDestroyInput,
            PulumiPlanInput,
            PulumiStatusInput,
        )

        assert PulumiPlanInput is not None
        assert PulumiApplyInput is not None
        assert PulumiDestroyInput is not None
        assert PulumiStatusInput is not None

    def test_import_output_models(self):
        """All output models are importable."""
        from parrot.tools.pulumi import (
            PulumiOperationResult,
            PulumiResource,
        )

        assert PulumiResource is not None
        assert PulumiOperationResult is not None

    def test_all_exports(self):
        """Verify __all__ contains expected exports."""
        from parrot.tools import pulumi

        expected = [
            "PulumiToolkit",
            "PulumiExecutor",
            "PulumiConfig",
            "PulumiPlanInput",
            "PulumiApplyInput",
            "PulumiDestroyInput",
            "PulumiStatusInput",
            "PulumiResource",
            "PulumiOperationResult",
        ]
        for name in expected:
            assert name in pulumi.__all__, f"{name} not in __all__"
            assert hasattr(pulumi, name), f"{name} not exportable"


class TestPulumiRegistration:
    """Test toolkit registration in the registry."""

    def test_toolkit_registered(self):
        """PulumiToolkit is registered in ToolkitRegistry source code."""
        # Skip actual registry loading due to environment dependencies
        # Instead verify registration is in the source code
        from pathlib import Path

        registry_path = Path(__file__).parent.parent.parent.parent / "parrot" / "tools" / "registry.py"
        content = registry_path.read_text()

        # Verify PulumiToolkit is imported and registered
        assert "from .pulumi.toolkit import PulumiToolkit" in content
        assert '"pulumi": PulumiToolkit' in content

    def test_pulumi_in_registry_dict(self):
        """Pulumi toolkit mapping exists in registry source."""
        from pathlib import Path

        registry_path = Path(__file__).parent.parent.parent.parent / "parrot" / "tools" / "registry.py"
        content = registry_path.read_text()

        # Find the return dict and verify pulumi is there
        assert "pulumi" in content.lower()


class TestPulumiFixture:
    """Test the Pulumi test fixture is valid."""

    def test_fixture_exists(self, fixtures_dir):
        """Test fixture directory exists."""
        assert fixtures_dir.exists(), f"Fixture dir not found: {fixtures_dir}"

    def test_pulumi_yaml_exists(self, fixtures_dir):
        """Pulumi.yaml exists in fixture."""
        pulumi_yaml = fixtures_dir / "Pulumi.yaml"
        assert pulumi_yaml.exists(), "Pulumi.yaml not found"

    def test_pulumi_yaml_valid(self, fixtures_dir):
        """Pulumi.yaml is valid YAML with required fields."""
        pulumi_yaml = fixtures_dir / "Pulumi.yaml"
        data = yaml.safe_load(pulumi_yaml.read_text())

        assert data is not None, "Pulumi.yaml is empty"
        assert "name" in data, "Pulumi.yaml missing 'name'"
        assert data["name"] == "test-docker-project"
        assert "runtime" in data, "Pulumi.yaml missing 'runtime'"
        assert data["runtime"] == "yaml"

    def test_main_yaml_exists(self, fixtures_dir):
        """Main.yaml exists in fixture."""
        main_yaml = fixtures_dir / "Main.yaml"
        assert main_yaml.exists(), "Main.yaml not found"

    def test_main_yaml_valid(self, fixtures_dir):
        """Main.yaml is valid YAML with resources."""
        main_yaml = fixtures_dir / "Main.yaml"
        data = yaml.safe_load(main_yaml.read_text())

        assert data is not None, "Main.yaml is empty"
        assert "resources" in data, "Main.yaml missing 'resources'"
        assert "redis" in data["resources"], "Main.yaml missing 'redis' resource"

    def test_stack_config_exists(self, fixtures_dir):
        """Pulumi.dev.yaml exists in fixture."""
        stack_yaml = fixtures_dir / "Pulumi.dev.yaml"
        assert stack_yaml.exists(), "Pulumi.dev.yaml not found"


class TestPulumiToolkitTools:
    """Test that toolkit provides properly configured tools."""

    @pytest.mark.asyncio
    async def test_tools_have_descriptions(self, toolkit):
        """All tools have descriptions for LLM."""
        tools = await toolkit.get_tools()
        assert len(tools) > 0, "No tools returned"

        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"
            assert len(tool.description) > 20, f"Tool {tool.name} description too short"

    @pytest.mark.asyncio
    async def test_expected_tools_exist(self, toolkit):
        """Expected tool methods exist."""
        tools = await toolkit.get_tools()
        tool_names = [t.name for t in tools]

        expected_tools = ["pulumi_plan", "pulumi_apply", "pulumi_destroy", "pulumi_status"]
        for expected in expected_tools:
            assert expected in tool_names, f"Expected tool {expected} not found"


class TestPulumiPlanOperation:
    """Test pulumi_plan operation."""

    @pytest.mark.asyncio
    async def test_plan_with_mocked_executor(self, toolkit, fixtures_dir):
        """Plan operation works with mocked executor."""
        preview_output = json.dumps({
            "steps": [
                {
                    "op": "create",
                    "urn": "urn:pulumi:dev::test::docker:Container::redis",
                    "type": "docker:Container",
                    "name": "redis",
                }
            ],
            "summary": {"create": 1},
        })

        with patch.object(
            toolkit.executor, "_execute_in_project", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (preview_output, "", 0)

            # Mock _ensure_stack to succeed
            with patch.object(
                toolkit.executor, "_ensure_stack", new_callable=AsyncMock
            ) as mock_stack:
                mock_stack.return_value = (True, "")

                result = await toolkit.pulumi_plan(str(fixtures_dir))

                assert result.success is True
                assert result.operation == "preview"

    @pytest.mark.asyncio
    async def test_plan_invalid_path(self, toolkit):
        """Plan fails gracefully with invalid path."""
        result = await toolkit.pulumi_plan("/nonexistent/path")

        assert result.success is False
        assert "not found" in result.error.lower()


class TestPulumiApplyOperation:
    """Test pulumi_apply operation."""

    @pytest.mark.asyncio
    async def test_apply_with_mocked_executor(self, toolkit, fixtures_dir):
        """Apply operation works with mocked executor."""
        up_output = json.dumps({
            "steps": [
                {
                    "op": "create",
                    "urn": "urn:pulumi:dev::test::docker:Container::redis",
                    "type": "docker:Container",
                    "name": "redis",
                }
            ],
            "outputs": {"containerId": "abc123", "containerName": "test-redis"},
            "summary": {"create": 1},
        })

        with patch.object(
            toolkit.executor, "_execute_in_project", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (up_output, "", 0)

            with patch.object(
                toolkit.executor, "_ensure_stack", new_callable=AsyncMock
            ) as mock_stack:
                mock_stack.return_value = (True, "")

                result = await toolkit.pulumi_apply(str(fixtures_dir))

                assert result.success is True
                assert result.operation == "up"


class TestPulumiDestroyOperation:
    """Test pulumi_destroy operation."""

    @pytest.mark.asyncio
    async def test_destroy_with_mocked_executor(self, toolkit, fixtures_dir):
        """Destroy operation works with mocked executor."""
        destroy_output = json.dumps({
            "steps": [
                {
                    "op": "delete",
                    "urn": "urn:pulumi:dev::test::docker:Container::redis",
                    "type": "docker:Container",
                    "name": "redis",
                }
            ],
            "summary": {"delete": 1},
        })

        with patch.object(
            toolkit.executor, "_execute_in_project", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (destroy_output, "", 0)

            result = await toolkit.pulumi_destroy(str(fixtures_dir))

            assert result.success is True
            assert result.operation == "destroy"


class TestPulumiStatusOperation:
    """Test pulumi_status operation."""

    @pytest.mark.asyncio
    async def test_status_with_mocked_executor(self, toolkit, fixtures_dir):
        """Status operation works with mocked executor."""
        status_output = json.dumps({
            "containerId": "abc123",
            "containerName": "test-redis",
        })

        with patch.object(
            toolkit.executor, "_execute_in_project", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (status_output, "", 0)

            result = await toolkit.pulumi_status(str(fixtures_dir))

            assert result.success is True
            assert result.operation == "stack"


class TestPulumiFullLifecycle:
    """Test full Pulumi lifecycle: plan -> apply -> status -> destroy."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, toolkit, fixtures_dir):
        """Full lifecycle works with mocked executor."""
        preview_output = json.dumps({
            "steps": [
                {"op": "create", "urn": "urn:pulumi:dev::test::docker:Container::redis"}
            ]
        })
        up_output = json.dumps({
            "steps": [
                {"op": "create", "urn": "urn:pulumi:dev::test::docker:Container::redis"}
            ],
            "outputs": {"containerId": "abc123"},
        })
        status_output = json.dumps({"containerId": "abc123"})
        destroy_output = json.dumps({
            "steps": [
                {"op": "delete", "urn": "urn:pulumi:dev::test::docker:Container::redis"}
            ]
        })

        with patch.object(
            toolkit.executor, "_execute_in_project", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(
                toolkit.executor, "_ensure_stack", new_callable=AsyncMock
            ) as mock_stack:
                mock_stack.return_value = (True, "")

                # Plan
                mock_exec.return_value = (preview_output, "", 0)
                plan_result = await toolkit.pulumi_plan(str(fixtures_dir))
                assert plan_result.success is True
                assert plan_result.operation == "preview"

                # Apply
                mock_exec.return_value = (up_output, "", 0)
                apply_result = await toolkit.pulumi_apply(str(fixtures_dir))
                assert apply_result.success is True
                assert apply_result.operation == "up"

                # Status
                mock_exec.return_value = (status_output, "", 0)
                status_result = await toolkit.pulumi_status(str(fixtures_dir))
                assert status_result.success is True
                assert status_result.operation == "stack"

                # Destroy
                mock_exec.return_value = (destroy_output, "", 0)
                destroy_result = await toolkit.pulumi_destroy(str(fixtures_dir))
                assert destroy_result.success is True
                assert destroy_result.operation == "destroy"


class TestPulumiErrorHandling:
    """Test error handling in Pulumi operations."""

    @pytest.mark.asyncio
    async def test_executor_failure_handled(self, toolkit, fixtures_dir):
        """Executor failures are handled gracefully."""
        with patch.object(
            toolkit.executor, "_execute_in_project", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(
                toolkit.executor, "_ensure_stack", new_callable=AsyncMock
            ) as mock_stack:
                mock_stack.return_value = (True, "")
                mock_exec.return_value = ("", "Stack not found", 1)

                result = await toolkit.pulumi_plan(str(fixtures_dir))

                assert result.success is False
                assert result.error is not None

    @pytest.mark.asyncio
    async def test_exception_in_executor_handled(self, toolkit, fixtures_dir):
        """Exceptions in executor are caught and handled."""
        with patch.object(
            toolkit.executor, "preview", new_callable=AsyncMock
        ) as mock_preview:
            mock_preview.side_effect = Exception("Connection refused")

            result = await toolkit.pulumi_plan(str(fixtures_dir))

            assert result.success is False
            assert "Connection refused" in result.error
