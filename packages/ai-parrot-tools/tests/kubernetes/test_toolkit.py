"""Unit tests for KubernetesToolkit — tool exposure and routing_meta (TASK-1124)."""

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_k8s_modules():
    """Inject mock kubernetes_asyncio into sys.modules (no real cluster)."""
    k8s = types.ModuleType("kubernetes_asyncio")
    k8s_client = types.ModuleType("kubernetes_asyncio.client")
    k8s_client.CoreV1Api = MagicMock()
    k8s_client.AppsV1Api = MagicMock()
    k8s_client.ApiClient = MagicMock()
    k8s_config_mod = types.ModuleType("kubernetes_asyncio.config")
    k8s_config_mod.load_kube_config = AsyncMock()
    k8s_config_mod.load_incluster_config = MagicMock()
    k8s_utils = types.ModuleType("kubernetes_asyncio.utils")
    k8s_utils.create_from_dict = AsyncMock()
    k8s.client = k8s_client
    k8s.config = k8s_config_mod
    k8s.utils = k8s_utils

    # Add client.exceptions submodule
    k8s_client_exceptions = types.ModuleType("kubernetes_asyncio.client.exceptions")

    class _FakeApiException(Exception):
        def __init__(self, status=0, reason=""):
            self.status = status
            self.reason = reason
            super().__init__(f"[{status}] {reason}")

    k8s_client_exceptions.ApiException = _FakeApiException
    k8s_client.exceptions = k8s_client_exceptions

    return {
        "kubernetes_asyncio": k8s,
        "kubernetes_asyncio.client": k8s_client,
        "kubernetes_asyncio.client.exceptions": k8s_client_exceptions,
        "kubernetes_asyncio.config": k8s_config_mod,
        "kubernetes_asyncio.utils": k8s_utils,
    }


@pytest.fixture(autouse=True)
def mock_k8s_modules():
    """Inject mock kubernetes_asyncio for all tests in this module."""
    mocks = _make_k8s_modules()
    for name, mod in mocks.items():
        sys.modules[name] = mod
    yield mocks
    for name in mocks:
        sys.modules.pop(name, None)


@pytest.fixture
def toolkit():
    """Default KubernetesToolkit for tests."""
    from parrot_tools.kubernetes.config import KubernetesConfig
    from parrot_tools.kubernetes.toolkit import KubernetesToolkit
    return KubernetesToolkit(config=KubernetesConfig())


class TestKubernetesToolkitToolExposure:
    """Tests for get_tools() count and naming."""

    def test_get_tools_count(self, toolkit):
        """get_tools() exposes exactly 8 tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 8

    def test_tool_names(self, toolkit):
        """All tools have the expected k8s_ names."""
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        expected = {
            "k8s_list_pods",
            "k8s_get_logs",
            "k8s_describe",
            "k8s_get",
            "k8s_apply_manifest",
            "k8s_scale_deployment",
            "k8s_delete_resource",
            "k8s_rollout_restart",
        }
        assert names == expected

    def test_all_tools_have_descriptions(self, toolkit):
        """All tools have non-empty docstring descriptions."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool '{tool.name}' has no description"
            assert len(tool.description.strip()) > 10, (
                f"Tool '{tool.name}' has a too-short description: {tool.description!r}"
            )

    def test_close_not_exposed_as_tool(self, toolkit):
        """close() is excluded from tool generation."""
        names = {t.name for t in toolkit.get_tools()}
        assert "close" not in names


class TestKubernetesToolkitRoutingMeta:
    """Tests for routing_meta on mutating vs read tools."""

    def test_mutating_tools_require_grant(self, toolkit):
        """Mutating tools have routing_meta['requires_grant'] == True."""
        tools = toolkit.get_tools()
        mutating = {
            "k8s_apply_manifest",
            "k8s_scale_deployment",
            "k8s_delete_resource",
            "k8s_rollout_restart",
        }
        for tool in tools:
            if tool.name in mutating:
                assert tool.routing_meta.get("requires_grant") is True, (
                    f"{tool.name} missing requires_grant"
                )
                assert tool.routing_meta.get("grant_scope") == "k8s:write", (
                    f"{tool.name} missing grant_scope"
                )

    def test_read_tools_no_grant(self, toolkit):
        """Read tools do NOT have requires_grant."""
        tools = toolkit.get_tools()
        read_tools = {"k8s_list_pods", "k8s_get_logs", "k8s_describe", "k8s_get"}
        for tool in tools:
            if tool.name in read_tools:
                assert not tool.routing_meta.get("requires_grant"), (
                    f"{tool.name} should NOT have requires_grant"
                )

    def test_routing_meta_grant_scope_on_all_mutating(self, toolkit):
        """All 4 mutating tools have grant_scope='k8s:write'."""
        tools = toolkit.get_tools()
        mutating = {
            "k8s_apply_manifest",
            "k8s_scale_deployment",
            "k8s_delete_resource",
            "k8s_rollout_restart",
        }
        mutating_tools = [t for t in tools if t.name in mutating]
        assert len(mutating_tools) == 4, "Expected exactly 4 mutating tools"
        for tool in mutating_tools:
            assert tool.routing_meta["grant_scope"] == "k8s:write"

    def test_read_tools_routing_meta_empty(self, toolkit):
        """Read tools have empty routing_meta (no grant fields)."""
        tools = toolkit.get_tools()
        read_tools = {"k8s_list_pods", "k8s_get_logs", "k8s_describe", "k8s_get"}
        for tool in tools:
            if tool.name in read_tools:
                assert "requires_grant" not in tool.routing_meta or \
                       not tool.routing_meta.get("requires_grant"), \
                    f"{tool.name} routing_meta should not have requires_grant=True"


class TestKubernetesToolkitDelegation:
    """Tests that toolkit methods delegate to executor correctly."""

    @pytest.mark.asyncio
    async def test_k8s_list_pods_delegates(self, toolkit):
        """k8s_list_pods delegates to _k8s_executor.list_pods."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="list_pods", summary="Found 0 pods"
        )
        toolkit._k8s_executor.list_pods = AsyncMock(return_value=expected)
        result = await toolkit.k8s_list_pods(namespace="test")
        toolkit._k8s_executor.list_pods.assert_awaited_once_with(
            namespace="test", label_selector=None
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_k8s_get_logs_delegates(self, toolkit):
        """k8s_get_logs delegates to _k8s_executor.get_logs."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="get_logs", summary="OK",
            items=[{"log": "log line"}]
        )
        toolkit._k8s_executor.get_logs = AsyncMock(return_value=expected)
        result = await toolkit.k8s_get_logs(pod="my-pod", tail_lines=50)
        toolkit._k8s_executor.get_logs.assert_awaited_once_with(
            pod="my-pod", namespace=None, container=None, tail_lines=50
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_k8s_describe_delegates(self, toolkit):
        """k8s_describe delegates to _k8s_executor.describe."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="describe", summary="Described"
        )
        toolkit._k8s_executor.describe = AsyncMock(return_value=expected)
        result = await toolkit.k8s_describe(kind="Deployment", name="my-deploy")
        toolkit._k8s_executor.describe.assert_awaited_once_with(
            kind="Deployment", name="my-deploy", namespace=None
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_k8s_get_delegates(self, toolkit):
        """k8s_get delegates to _k8s_executor.get_resources."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="get", summary="Found 2 items"
        )
        toolkit._k8s_executor.get_resources = AsyncMock(return_value=expected)
        result = await toolkit.k8s_get(kind="Service", label_selector="app=nginx")
        toolkit._k8s_executor.get_resources.assert_awaited_once_with(
            kind="Service", namespace=None, label_selector="app=nginx"
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_k8s_apply_manifest_delegates(self, toolkit):
        """k8s_apply_manifest delegates to _k8s_executor.apply_manifest."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="apply", summary="Applied 1 resource"
        )
        toolkit._k8s_executor.apply_manifest = AsyncMock(return_value=expected)
        yaml_str = "kind: ConfigMap\nmetadata:\n  name: test\n"
        result = await toolkit.k8s_apply_manifest(manifest_yaml=yaml_str)
        toolkit._k8s_executor.apply_manifest.assert_awaited_once_with(
            manifest_yaml=yaml_str, namespace=None
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_k8s_scale_deployment_delegates(self, toolkit):
        """k8s_scale_deployment delegates to _k8s_executor.scale_deployment."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="scale", summary="Scaled to 3"
        )
        toolkit._k8s_executor.scale_deployment = AsyncMock(return_value=expected)
        result = await toolkit.k8s_scale_deployment(name="my-deploy", replicas=3)
        toolkit._k8s_executor.scale_deployment.assert_awaited_once_with(
            name="my-deploy", replicas=3, namespace=None
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_k8s_delete_resource_delegates(self, toolkit):
        """k8s_delete_resource delegates to _k8s_executor.delete_resource."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="delete", summary="Deleted"
        )
        toolkit._k8s_executor.delete_resource = AsyncMock(return_value=expected)
        result = await toolkit.k8s_delete_resource(kind="Pod", name="old-pod")
        toolkit._k8s_executor.delete_resource.assert_awaited_once_with(
            kind="Pod", name="old-pod", namespace=None
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_k8s_rollout_restart_delegates(self, toolkit):
        """k8s_rollout_restart delegates to _k8s_executor.rollout_restart."""
        from parrot_tools.kubernetes.config import K8sOperationResult
        expected = K8sOperationResult(
            success=True, operation="rollout_restart", summary="Restarted"
        )
        toolkit._k8s_executor.rollout_restart = AsyncMock(return_value=expected)
        result = await toolkit.k8s_rollout_restart(name="my-deploy")
        toolkit._k8s_executor.rollout_restart.assert_awaited_once_with(
            name="my-deploy", namespace=None
        )
        assert result.success is True


class TestKubernetesToolkitInputValidation:
    """Tests for input validation in toolkit methods."""

    @pytest.mark.asyncio
    async def test_describe_empty_kind_returns_error(self, toolkit):
        """k8s_describe with empty kind returns error result."""
        result = await toolkit.k8s_describe(kind="", name="my-resource")
        assert result.success is False
        assert "empty" in result.error

    @pytest.mark.asyncio
    async def test_describe_empty_name_returns_error(self, toolkit):
        """k8s_describe with empty name returns error result."""
        result = await toolkit.k8s_describe(kind="Pod", name="")
        assert result.success is False
        assert "empty" in result.error

    @pytest.mark.asyncio
    async def test_apply_empty_manifest_returns_error(self, toolkit):
        """k8s_apply_manifest with empty yaml returns error result."""
        result = await toolkit.k8s_apply_manifest(manifest_yaml="")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_scale_empty_name_returns_error(self, toolkit):
        """k8s_scale_deployment with empty name returns error result."""
        result = await toolkit.k8s_scale_deployment(name="", replicas=3)
        assert result.success is False
        assert "empty" in result.error

    @pytest.mark.asyncio
    async def test_delete_empty_kind_returns_error(self, toolkit):
        """k8s_delete_resource with empty kind returns error result."""
        result = await toolkit.k8s_delete_resource(kind="", name="foo")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_rollout_restart_empty_name_returns_error(self, toolkit):
        """k8s_rollout_restart with empty name returns error result."""
        result = await toolkit.k8s_rollout_restart(name="")
        assert result.success is False


class TestKubernetesToolkitLifecycle:
    """Tests for toolkit lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_delegates_to_executor(self, toolkit):
        """close() delegates to _k8s_executor.close."""
        toolkit._k8s_executor.close = AsyncMock()
        await toolkit.close()
        toolkit._k8s_executor.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager_closes_executor(self):
        """KubernetesToolkit async context manager calls close() on exit."""
        from parrot_tools.kubernetes.config import KubernetesConfig
        from parrot_tools.kubernetes.toolkit import KubernetesToolkit

        tk = KubernetesToolkit(config=KubernetesConfig())
        tk._k8s_executor.close = AsyncMock()
        async with tk:
            pass
        tk._k8s_executor.close.assert_awaited_once()

    def test_instantiation_creates_executor(self, toolkit):
        """KubernetesToolkit instantiation creates a KubernetesExecutor."""
        from parrot_tools.kubernetes.executor import KubernetesExecutor
        assert isinstance(toolkit._k8s_executor, KubernetesExecutor)

    def test_default_config_used_when_none(self):
        """KubernetesToolkit uses default KubernetesConfig when config=None."""
        from parrot_tools.kubernetes.config import KubernetesConfig
        from parrot_tools.kubernetes.toolkit import KubernetesToolkit

        tk = KubernetesToolkit()
        assert isinstance(tk.config, KubernetesConfig)
        assert tk.config.namespace == "default"
