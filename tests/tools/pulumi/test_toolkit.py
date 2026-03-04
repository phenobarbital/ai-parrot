"""Tests for Pulumi toolkit."""

from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.pulumi.config import PulumiConfig, PulumiOperationResult, PulumiResource
from parrot.tools.pulumi.toolkit import PulumiToolkit


@pytest.fixture
def toolkit():
    """Create toolkit with direct CLI mode (no Docker)."""
    return PulumiToolkit(PulumiConfig(use_docker=False))


@pytest.fixture
def mock_project(tmp_path):
    """Create a minimal Pulumi project."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    (project_dir / "Pulumi.yaml").write_text("name: test\nruntime: yaml\n")
    return project_dir


@pytest.fixture
def mock_project_yml(tmp_path):
    """Create a minimal Pulumi project with Pulumi.yml."""
    project_dir = tmp_path / "test-project-yml"
    project_dir.mkdir()
    (project_dir / "Pulumi.yml").write_text("name: test\nruntime: yaml\n")
    return project_dir


class TestPulumiToolkitInit:
    """Tests for toolkit initialization."""

    def test_toolkit_initializes(self, toolkit):
        """Toolkit initializes with default config."""
        assert toolkit.config is not None
        assert toolkit.executor is not None

    def test_toolkit_with_custom_config(self):
        """Toolkit accepts custom config."""
        config = PulumiConfig(default_stack="staging", use_docker=True)
        toolkit = PulumiToolkit(config)
        assert toolkit.config.default_stack == "staging"
        assert toolkit.config.use_docker is True

    @pytest.mark.asyncio
    async def test_get_tools_returns_expected_tools(self, toolkit):
        """get_tools() returns expected tools."""
        tools = await toolkit.get_tools()
        tool_names = [t.name for t in tools]

        assert "pulumi_plan" in tool_names
        assert "pulumi_apply" in tool_names
        assert "pulumi_destroy" in tool_names
        assert "pulumi_status" in tool_names
        assert "pulumi_list_stacks" in tool_names

    @pytest.mark.asyncio
    async def test_get_tools_count(self, toolkit):
        """get_tools() returns at least 4 tools."""
        tools = await toolkit.get_tools()
        assert len(tools) >= 4


class TestPulumiToolkitValidation:
    """Tests for project path validation."""

    def test_validate_project_path_success(self, toolkit, mock_project):
        """Validation passes for valid project."""
        valid, error = toolkit._validate_project_path(str(mock_project))
        assert valid is True
        assert error == ""

    def test_validate_project_path_yml(self, toolkit, mock_project_yml):
        """Validation passes for project with Pulumi.yml."""
        valid, error = toolkit._validate_project_path(str(mock_project_yml))
        assert valid is True
        assert error == ""

    def test_validate_project_path_not_found(self, toolkit, tmp_path):
        """Validation fails for nonexistent path."""
        valid, error = toolkit._validate_project_path(str(tmp_path / "nonexistent"))
        assert valid is False
        assert "not found" in error.lower()

    def test_validate_project_path_not_directory(self, toolkit, tmp_path):
        """Validation fails for file instead of directory."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("test")
        valid, error = toolkit._validate_project_path(str(file_path))
        assert valid is False
        assert "not a directory" in error.lower()

    def test_validate_project_path_no_pulumi_yaml(self, toolkit, tmp_path):
        """Validation fails for directory without Pulumi.yaml."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        valid, error = toolkit._validate_project_path(str(empty_dir))
        assert valid is False
        assert "Pulumi.yaml" in error


class TestPulumiToolkitPlan:
    """Tests for pulumi_plan operation."""

    @pytest.mark.asyncio
    async def test_plan_validates_project_path(self, toolkit, tmp_path):
        """Plan fails gracefully for missing project."""
        result = await toolkit.pulumi_plan(str(tmp_path / "nonexistent"))
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_plan_checks_pulumi_yaml(self, toolkit, tmp_path):
        """Plan fails if Pulumi.yaml is missing."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = await toolkit.pulumi_plan(str(empty_dir))
        assert result.success is False
        assert "Pulumi.yaml" in result.error

    @pytest.mark.asyncio
    async def test_plan_success(self, toolkit, mock_project):
        """Plan succeeds with valid project."""
        mock_result = PulumiOperationResult(
            success=True,
            operation="preview",
            resources=[
                PulumiResource(
                    urn="urn:pulumi:dev::test::docker:Container::redis",
                    type="docker:Container",
                    name="redis",
                    status="create",
                )
            ],
            summary={"create": 1},
        )

        with patch.object(toolkit.executor, "preview", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            result = await toolkit.pulumi_plan(str(mock_project))

            assert result.success is True
            assert result.operation == "preview"
            assert len(result.resources) == 1
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_plan_with_options(self, toolkit, mock_project):
        """Plan passes options to executor."""
        mock_result = PulumiOperationResult(success=True, operation="preview")

        with patch.object(toolkit.executor, "preview", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            await toolkit.pulumi_plan(
                str(mock_project),
                stack_name="staging",
                refresh=False,
                target=["urn:pulumi:dev::app::docker:Container::redis"],
            )

            mock.assert_called_once_with(
                project_path=str(mock_project),
                stack="staging",
                config_values=None,
                target=["urn:pulumi:dev::app::docker:Container::redis"],
                refresh=False,
            )

    @pytest.mark.asyncio
    async def test_plan_handles_executor_exception(self, toolkit, mock_project):
        """Plan handles executor exceptions gracefully."""
        with patch.object(toolkit.executor, "preview", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Connection failed")
            result = await toolkit.pulumi_plan(str(mock_project))

            assert result.success is False
            assert "Connection failed" in result.error


class TestPulumiToolkitApply:
    """Tests for pulumi_apply operation."""

    @pytest.mark.asyncio
    async def test_apply_validates_project_path(self, toolkit, tmp_path):
        """Apply fails gracefully for missing project."""
        result = await toolkit.pulumi_apply(str(tmp_path / "nonexistent"))
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_apply_success(self, toolkit, mock_project):
        """Apply succeeds with valid project."""
        mock_result = PulumiOperationResult(
            success=True,
            operation="up",
            resources=[
                PulumiResource(
                    urn="urn:pulumi:dev::test::docker:Container::redis",
                    type="docker:Container",
                    name="redis",
                    status="create",
                )
            ],
            outputs={"url": "http://localhost:6379"},
            summary={"create": 1},
        )

        with patch.object(toolkit.executor, "up", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            result = await toolkit.pulumi_apply(str(mock_project))

            assert result.success is True
            assert result.operation == "up"
            assert result.outputs.get("url") == "http://localhost:6379"
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_with_options(self, toolkit, mock_project):
        """Apply passes options to executor."""
        mock_result = PulumiOperationResult(success=True, operation="up")

        with patch.object(toolkit.executor, "up", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            await toolkit.pulumi_apply(
                str(mock_project),
                stack_name="prod",
                auto_approve=False,
                replace=["urn:pulumi:dev::app::docker:Container::old"],
            )

            mock.assert_called_once_with(
                project_path=str(mock_project),
                stack="prod",
                config_values=None,
                auto_approve=False,
                target=None,
                refresh=True,
                replace=["urn:pulumi:dev::app::docker:Container::old"],
            )

    @pytest.mark.asyncio
    async def test_apply_handles_executor_exception(self, toolkit, mock_project):
        """Apply handles executor exceptions gracefully."""
        with patch.object(toolkit.executor, "up", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Docker daemon not running")
            result = await toolkit.pulumi_apply(str(mock_project))

            assert result.success is False
            assert "Docker daemon not running" in result.error


class TestPulumiToolkitDestroy:
    """Tests for pulumi_destroy operation."""

    @pytest.mark.asyncio
    async def test_destroy_validates_project_path(self, toolkit, tmp_path):
        """Destroy fails gracefully for missing project."""
        result = await toolkit.pulumi_destroy(str(tmp_path / "nonexistent"))
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_destroy_success(self, toolkit, mock_project):
        """Destroy succeeds with valid project."""
        mock_result = PulumiOperationResult(
            success=True,
            operation="destroy",
            resources=[
                PulumiResource(
                    urn="urn:pulumi:dev::test::docker:Container::redis",
                    type="docker:Container",
                    name="redis",
                    status="delete",
                )
            ],
            summary={"delete": 1},
        )

        with patch.object(toolkit.executor, "destroy", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            result = await toolkit.pulumi_destroy(str(mock_project))

            assert result.success is True
            assert result.operation == "destroy"
            assert result.summary.get("delete") == 1
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_destroy_with_target(self, toolkit, mock_project):
        """Destroy passes target option to executor."""
        mock_result = PulumiOperationResult(success=True, operation="destroy")

        with patch.object(toolkit.executor, "destroy", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            await toolkit.pulumi_destroy(
                str(mock_project),
                stack_name="staging",
                target=["urn:pulumi:dev::app::docker:Container::redis"],
            )

            mock.assert_called_once_with(
                project_path=str(mock_project),
                stack="staging",
                auto_approve=True,
                target=["urn:pulumi:dev::app::docker:Container::redis"],
            )

    @pytest.mark.asyncio
    async def test_destroy_handles_executor_exception(self, toolkit, mock_project):
        """Destroy handles executor exceptions gracefully."""
        with patch.object(toolkit.executor, "destroy", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Resource in use")
            result = await toolkit.pulumi_destroy(str(mock_project))

            assert result.success is False
            assert "Resource in use" in result.error


class TestPulumiToolkitStatus:
    """Tests for pulumi_status operation."""

    @pytest.mark.asyncio
    async def test_status_validates_project_path(self, toolkit, tmp_path):
        """Status fails gracefully for missing project."""
        result = await toolkit.pulumi_status(str(tmp_path / "nonexistent"))
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_status_success(self, toolkit, mock_project):
        """Status succeeds with valid project."""
        mock_result = PulumiOperationResult(
            success=True,
            operation="stack",
            outputs={"url": "http://localhost:6379", "port": 6379},
        )

        with patch.object(toolkit.executor, "stack_output", new_callable=AsyncMock) as mock:
            mock.return_value = mock_result
            result = await toolkit.pulumi_status(str(mock_project))

            assert result.success is True
            assert result.operation == "stack"
            assert result.outputs.get("url") == "http://localhost:6379"
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_status_handles_executor_exception(self, toolkit, mock_project):
        """Status handles executor exceptions gracefully."""
        with patch.object(toolkit.executor, "stack_output", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Stack not found")
            result = await toolkit.pulumi_status(str(mock_project))

            assert result.success is False
            assert "Stack not found" in result.error


class TestPulumiToolkitListStacks:
    """Tests for pulumi_list_stacks operation."""

    @pytest.mark.asyncio
    async def test_list_stacks_validates_project_path(self, toolkit, tmp_path):
        """List stacks fails gracefully for missing project."""
        stacks, error = await toolkit.pulumi_list_stacks(str(tmp_path / "nonexistent"))
        assert stacks == []
        assert "not found" in error.lower()

    @pytest.mark.asyncio
    async def test_list_stacks_success(self, toolkit, mock_project):
        """List stacks succeeds with valid project."""
        with patch.object(toolkit.executor, "list_stacks", new_callable=AsyncMock) as mock:
            mock.return_value = (["dev", "staging", "prod"], "")
            stacks, error = await toolkit.pulumi_list_stacks(str(mock_project))

            assert error == ""
            assert "dev" in stacks
            assert "staging" in stacks
            assert "prod" in stacks
            mock.assert_called_once_with(str(mock_project))

    @pytest.mark.asyncio
    async def test_list_stacks_handles_executor_exception(self, toolkit, mock_project):
        """List stacks handles executor exceptions gracefully."""
        with patch.object(toolkit.executor, "list_stacks", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Not a Pulumi project")
            stacks, error = await toolkit.pulumi_list_stacks(str(mock_project))

            assert stacks == []
            assert "Not a Pulumi project" in error
