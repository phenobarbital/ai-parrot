"""Integration tests for lazy registry and end-to-end toolkit instantiation (TASK-1125).

Tests lazy registration in TOOL_REGISTRY, import resolution, and full
tool exposure without a real Kubernetes cluster.
"""

import importlib
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock


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
    return {
        "kubernetes_asyncio": k8s,
        "kubernetes_asyncio.client": k8s_client,
        "kubernetes_asyncio.config": k8s_config_mod,
        "kubernetes_asyncio.utils": k8s_utils,
    }


@pytest.fixture(autouse=True)
def mock_k8s_modules():
    """Inject mock kubernetes_asyncio for all integration tests."""
    mocks = _make_k8s_modules()
    for name, mod in mocks.items():
        sys.modules[name] = mod
    yield mocks
    for name in mocks:
        sys.modules.pop(name, None)


class TestLazyRegistration:
    """Tests for TOOL_REGISTRY lazy entry and resolution."""

    def test_registry_has_kubernetes(self):
        """TOOL_REGISTRY contains the 'kubernetes' entry."""
        from parrot_tools import TOOL_REGISTRY
        assert "kubernetes" in TOOL_REGISTRY
        assert TOOL_REGISTRY["kubernetes"] == "parrot_tools.kubernetes.toolkit.KubernetesToolkit"

    def test_lazy_resolve(self):
        """Registry entry resolves to KubernetesToolkit class via importlib."""
        from parrot_tools import TOOL_REGISTRY
        module_path, class_name = TOOL_REGISTRY["kubernetes"].rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        assert cls.__name__ == "KubernetesToolkit"

    def test_toolkit_instantiates_from_registry(self):
        """KubernetesToolkit can be instantiated from the registry path."""
        from parrot_tools import TOOL_REGISTRY
        module_path, class_name = TOOL_REGISTRY["kubernetes"].rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        toolkit = cls()
        assert toolkit is not None

    def test_registry_entry_is_string(self):
        """Registry entry is a string (not an actual import — lazy by design)."""
        from parrot_tools import TOOL_REGISTRY
        assert isinstance(TOOL_REGISTRY["kubernetes"], str)

    def test_existing_entries_unchanged(self):
        """Existing registry entries (pulumi, docker) are unmodified."""
        from parrot_tools import TOOL_REGISTRY
        assert TOOL_REGISTRY.get("pulumi") == "parrot_tools.pulumi.toolkit.PulumiToolkit"
        assert TOOL_REGISTRY.get("docker") == "parrot_tools.docker.toolkit.DockerToolkit"


class TestPackageImports:
    """Tests for parrot_tools.kubernetes package imports."""

    def test_import_kubernetes_toolkit(self):
        """from parrot_tools.kubernetes import KubernetesToolkit works."""
        from parrot_tools.kubernetes import KubernetesToolkit
        assert KubernetesToolkit.__name__ == "KubernetesToolkit"

    def test_import_kubernetes_config(self):
        """from parrot_tools.kubernetes import KubernetesConfig works."""
        from parrot_tools.kubernetes import KubernetesConfig
        assert KubernetesConfig.__name__ == "KubernetesConfig"

    def test_import_k8s_operation_result(self):
        """from parrot_tools.kubernetes import K8sOperationResult works."""
        from parrot_tools.kubernetes import K8sOperationResult
        assert K8sOperationResult.__name__ == "K8sOperationResult"

    def test_import_kubernetes_executor(self):
        """from parrot_tools.kubernetes import KubernetesExecutor works."""
        from parrot_tools.kubernetes import KubernetesExecutor
        assert KubernetesExecutor.__name__ == "KubernetesExecutor"

    def test_all_exports_in_dunder_all(self):
        """All expected symbols are in __all__ of kubernetes package."""
        import parrot_tools.kubernetes as pkg
        assert "KubernetesToolkit" in pkg.__all__
        assert "KubernetesConfig" in pkg.__all__
        assert "K8sOperationResult" in pkg.__all__
        assert "KubernetesExecutor" in pkg.__all__

    def test_import_does_not_load_kubernetes_asyncio_at_parrot_tools_level(self):
        """Importing parrot_tools should NOT trigger kubernetes_asyncio import.

        The registry is strings only — no actual import at package load time.
        """
        # Remove kubernetes_asyncio from sys.modules temporarily to test lazy behavior
        k8s_mods = {k: sys.modules.pop(k) for k in list(sys.modules.keys())
                    if k.startswith("kubernetes_asyncio")}
        try:
            # Reload parrot_tools (registry only, no k8s import)
            if "parrot_tools" in sys.modules:
                importlib.reload(sys.modules["parrot_tools"])
            # kubernetes_asyncio should NOT be loaded just from the registry
            assert "kubernetes_asyncio" not in sys.modules
        finally:
            # Restore mocks
            sys.modules.update(k8s_mods)


class TestEndToEnd:
    """End-to-end tests: instantiate toolkit and verify tool exposure."""

    def test_toolkit_instantiates(self):
        """KubernetesToolkit can be instantiated."""
        from parrot_tools.kubernetes import KubernetesConfig, KubernetesToolkit
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        assert toolkit is not None

    def test_toolkit_exposes_eight_tools(self):
        """Full end-to-end: instantiate toolkit → get_tools() → 8 tools."""
        from parrot_tools.kubernetes import KubernetesConfig, KubernetesToolkit
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        tools = toolkit.get_tools()
        assert len(tools) == 8

    def test_read_tools_no_grant_meta(self):
        """Read tools do not carry requires_grant."""
        from parrot_tools.kubernetes import KubernetesConfig, KubernetesToolkit
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        tools = toolkit.get_tools()
        read_names = {"k8s_list_pods", "k8s_get_logs", "k8s_describe", "k8s_get"}
        for tool in tools:
            if tool.name in read_names:
                assert not tool.routing_meta.get("requires_grant"), (
                    f"{tool.name} should NOT have requires_grant"
                )

    def test_mutating_tools_have_grant_meta(self):
        """Mutating tools carry requires_grant=True and grant_scope='k8s:write'."""
        from parrot_tools.kubernetes import KubernetesConfig, KubernetesToolkit
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        tools = toolkit.get_tools()
        mutating_names = {
            "k8s_apply_manifest",
            "k8s_scale_deployment",
            "k8s_delete_resource",
            "k8s_rollout_restart",
        }
        for tool in tools:
            if tool.name in mutating_names:
                assert tool.routing_meta.get("requires_grant") is True
                assert tool.routing_meta.get("grant_scope") == "k8s:write"

    def test_all_tool_names_have_k8s_prefix(self):
        """All 8 tools have the k8s_ prefix."""
        from parrot_tools.kubernetes import KubernetesConfig, KubernetesToolkit
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.name.startswith("k8s_"), (
                f"Tool '{tool.name}' should start with 'k8s_'"
            )
