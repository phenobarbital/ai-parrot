"""Unit tests for KubernetesExecutor with fully mocked kubernetes_asyncio.

All tests use AsyncMock/MagicMock — no real cluster is touched.
kubernetes_asyncio is mocked via sys.modules injection since it is not installed.
"""

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_k8s_modules():
    """Return a dict of mock kubernetes_asyncio modules to inject into sys.modules.

    CoreV1Api, AppsV1Api, ApiClient are MagicMock instances (callables) so that
    calling them returns another MagicMock without causing 'Cannot spec a Mock object'.
    """
    # Top-level
    k8s = types.ModuleType("kubernetes_asyncio")

    # kubernetes_asyncio.client
    k8s_client = types.ModuleType("kubernetes_asyncio.client")
    # These must be MagicMock() instances (not the class itself) so that
    # CoreV1Api(api_client) → MagicMock() without spec errors.
    k8s_client.CoreV1Api = MagicMock()
    k8s_client.AppsV1Api = MagicMock()
    k8s_client.ApiClient = MagicMock()

    # kubernetes_asyncio.config
    k8s_config_mod = types.ModuleType("kubernetes_asyncio.config")
    k8s_config_mod.load_kube_config = AsyncMock()
    k8s_config_mod.load_incluster_config = MagicMock()

    # kubernetes_asyncio.utils
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
    """Inject mock kubernetes_asyncio modules into sys.modules for all tests."""
    mocks = _make_k8s_modules()
    for name, mod in mocks.items():
        sys.modules[name] = mod
    yield mocks
    for name in mocks:
        sys.modules.pop(name, None)


def _make_pod(name: str, namespace: str = "test-ns", phase: str = "Running",
              node: str = "node-1", ready: bool = True, restarts: int = 0):
    """Create a mock pod object."""
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.labels = {"app": name}
    pod.status.phase = phase
    pod.spec.node_name = node
    cs = MagicMock()
    cs.ready = ready
    cs.restart_count = restarts
    pod.status.container_statuses = [cs]
    return pod


@pytest.fixture
def k8s_client_mod():
    """Return the mock kubernetes_asyncio.client module."""
    return sys.modules["kubernetes_asyncio.client"]


@pytest.fixture
def config():
    """Default KubernetesConfig for tests."""
    from parrot_tools.kubernetes.config import KubernetesConfig
    return KubernetesConfig(namespace="test-ns")


@pytest.fixture
def executor(config):
    """KubernetesExecutor with a pre-set mock API client."""
    from parrot_tools.kubernetes.executor import KubernetesExecutor
    exc = KubernetesExecutor(config)
    exc._api_client = MagicMock()  # pre-init to skip _ensure_client network calls
    return exc


class TestKubernetesExecutorListPods:
    """Tests for list_pods operation."""

    @pytest.mark.asyncio
    async def test_list_pods_mocked(self, executor, k8s_client_mod):
        """list_pods returns bounded items from mocked CoreV1Api."""
        fake_pods = [
            _make_pod("pod-1"),
            _make_pod("pod-2", phase="Pending"),
        ]
        mock_response = MagicMock()
        mock_response.items = fake_pods

        mock_v1 = AsyncMock()
        mock_v1.list_namespaced_pod.return_value = mock_response
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        result = await executor.list_pods(namespace="test-ns")

        assert result.success is True
        assert result.operation == "list_pods"
        assert len(result.items) == 2
        assert result.error is None
        # Verify bounded projection
        item = result.items[0]
        assert "name" in item
        assert "phase" in item
        assert "node" in item

    @pytest.mark.asyncio
    async def test_list_pods_with_label_selector(self, executor, k8s_client_mod):
        """list_pods passes label_selector to the API."""
        mock_response = MagicMock()
        mock_response.items = [_make_pod("pod-1")]

        mock_v1 = AsyncMock()
        mock_v1.list_namespaced_pod.return_value = mock_response
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        result = await executor.list_pods(namespace="test-ns", label_selector="app=nginx")
        mock_v1.list_namespaced_pod.assert_called_once_with(
            namespace="test-ns", label_selector="app=nginx"
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_list_pods_api_error(self, executor, k8s_client_mod):
        """API errors are caught and returned as error result."""
        mock_v1 = AsyncMock()
        mock_v1.list_namespaced_pod.side_effect = Exception("Connection refused")
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        result = await executor.list_pods()

        assert result.success is False
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_list_pods_empty(self, executor, k8s_client_mod):
        """list_pods with no pods returns empty items."""
        mock_response = MagicMock()
        mock_response.items = []

        mock_v1 = AsyncMock()
        mock_v1.list_namespaced_pod.return_value = mock_response
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        result = await executor.list_pods()

        assert result.success is True
        assert result.items == []
        assert "0" in result.summary


class TestKubernetesExecutorGetLogs:
    """Tests for get_logs operation."""

    @pytest.mark.asyncio
    async def test_get_logs_mocked(self, executor, k8s_client_mod):
        """get_logs returns log output from mocked CoreV1Api."""
        log_text = "2026-01-01 startup\n2026-01-01 ready"

        mock_v1 = AsyncMock()
        mock_v1.read_namespaced_pod_log.return_value = log_text
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        result = await executor.get_logs(pod="my-pod", namespace="test-ns")

        assert result.success is True
        assert result.operation == "get_logs"
        assert len(result.items) == 1
        assert result.items[0]["log"] == log_text

    @pytest.mark.asyncio
    async def test_get_logs_tail_lines_respected(self, executor, k8s_client_mod):
        """get_logs passes tail_lines to the API."""
        mock_v1 = AsyncMock()
        mock_v1.read_namespaced_pod_log.return_value = "line1\nline2"
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        await executor.get_logs(pod="my-pod", tail_lines=50)
        mock_v1.read_namespaced_pod_log.assert_called_once_with(
            name="my-pod", namespace="test-ns", tail_lines=50
        )

    @pytest.mark.asyncio
    async def test_get_logs_truncation(self, executor, k8s_client_mod):
        """Very large logs are truncated to _MAX_LOG_CHARS."""
        from parrot_tools.kubernetes.executor import _MAX_LOG_CHARS
        huge_log = "x" * (_MAX_LOG_CHARS + 10_000)

        mock_v1 = AsyncMock()
        mock_v1.read_namespaced_pod_log.return_value = huge_log
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        result = await executor.get_logs(pod="my-pod")

        assert result.success is True
        assert len(result.items[0]["log"]) == _MAX_LOG_CHARS
        assert "truncated" in result.summary

    @pytest.mark.asyncio
    async def test_get_logs_with_container(self, executor, k8s_client_mod):
        """get_logs passes container kwarg when specified."""
        mock_v1 = AsyncMock()
        mock_v1.read_namespaced_pod_log.return_value = "log line"
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        await executor.get_logs(pod="my-pod", container="sidecar")
        mock_v1.read_namespaced_pod_log.assert_called_once_with(
            name="my-pod", namespace="test-ns", tail_lines=200, container="sidecar"
        )


class TestKubernetesExecutorDescribe:
    """Tests for describe operation."""

    @pytest.mark.asyncio
    async def test_describe_pod_mocked(self, executor, k8s_client_mod):
        """describe returns summary for a pod."""
        mock_pod = _make_pod("my-pod")

        mock_v1 = AsyncMock()
        mock_v1.read_namespaced_pod.return_value = mock_pod
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        mock_apps = AsyncMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.describe(kind="Pod", name="my-pod", namespace="test-ns")

        assert result.success is True
        assert len(result.items) == 1
        assert result.items[0]["kind"] == "Pod"
        assert result.items[0]["name"] == "my-pod"

    @pytest.mark.asyncio
    async def test_describe_unsupported_kind(self, executor, k8s_client_mod):
        """describe returns error for unsupported kind."""
        mock_v1 = AsyncMock()
        k8s_client_mod.CoreV1Api.return_value = mock_v1
        mock_apps = AsyncMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.describe(kind="UnknownKind", name="foo")
        assert result.success is False
        assert "not supported" in result.error


class TestKubernetesExecutorScaleDeployment:
    """Tests for scale_deployment operation."""

    @pytest.mark.asyncio
    async def test_scale_deployment_mocked(self, executor, k8s_client_mod):
        """scale_deployment calls patch_namespaced_deployment_scale with correct replicas."""
        mock_apps = AsyncMock()
        mock_apps.patch_namespaced_deployment_scale.return_value = MagicMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.scale_deployment(
            name="my-deploy", replicas=5, namespace="test-ns"
        )

        assert result.success is True
        assert "5" in result.summary
        assert result.items[0]["replicas"] == 5
        mock_apps.patch_namespaced_deployment_scale.assert_called_once_with(
            name="my-deploy",
            namespace="test-ns",
            body={"spec": {"replicas": 5}},
        )

    @pytest.mark.asyncio
    async def test_scale_deployment_zero_replicas(self, executor, k8s_client_mod):
        """scale_deployment accepts 0 replicas (scale down)."""
        mock_apps = AsyncMock()
        mock_apps.patch_namespaced_deployment_scale.return_value = MagicMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.scale_deployment(
            name="my-deploy", replicas=0, namespace="test-ns"
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_scale_deployment_negative_replicas(self, executor, k8s_client_mod):
        """scale_deployment rejects negative replicas without calling API."""
        result = await executor.scale_deployment(name="my-deploy", replicas=-1)
        assert result.success is False
        assert ">= 0" in result.error


class TestKubernetesExecutorApplyManifest:
    """Tests for apply_manifest operation."""

    @pytest.mark.asyncio
    async def test_apply_manifest_mocked(self, executor, mock_k8s_modules):
        """apply_manifest parses YAML and calls create_from_dict."""
        manifest = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
data:
  key: value
"""
        # Mock create_from_dict in the injected utils module
        mock_k8s_modules["kubernetes_asyncio.utils"].create_from_dict = AsyncMock(return_value=MagicMock())

        result = await executor.apply_manifest(manifest_yaml=manifest)

        assert result.success is True
        assert len(result.items) > 0

    @pytest.mark.asyncio
    async def test_apply_manifest_empty_yaml(self, executor, mock_k8s_modules):
        """apply_manifest returns error for empty YAML."""
        result = await executor.apply_manifest(manifest_yaml="")
        assert result.success is False


class TestKubernetesExecutorDeleteResource:
    """Tests for delete_resource operation."""

    @pytest.mark.asyncio
    async def test_delete_pod_mocked(self, executor, k8s_client_mod):
        """delete_resource deletes a pod via CoreV1Api."""
        mock_v1 = AsyncMock()
        mock_v1.delete_namespaced_pod.return_value = MagicMock()
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        mock_apps = AsyncMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.delete_resource(
            kind="Pod", name="old-pod", namespace="test-ns"
        )

        assert result.success is True
        assert result.items[0]["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_deployment_mocked(self, executor, k8s_client_mod):
        """delete_resource deletes a deployment via AppsV1Api."""
        mock_v1 = AsyncMock()
        k8s_client_mod.CoreV1Api.return_value = mock_v1

        mock_apps = AsyncMock()
        mock_apps.delete_namespaced_deployment.return_value = MagicMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.delete_resource(
            kind="Deployment", name="my-deploy", namespace="test-ns"
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_delete_unsupported_kind(self, executor, k8s_client_mod):
        """delete_resource returns error for unsupported kind."""
        mock_v1 = AsyncMock()
        k8s_client_mod.CoreV1Api.return_value = mock_v1
        mock_apps = AsyncMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.delete_resource(kind="UnknownKind", name="foo")

        assert result.success is False
        assert "not supported" in result.error


class TestKubernetesExecutorRolloutRestart:
    """Tests for rollout_restart operation."""

    @pytest.mark.asyncio
    async def test_rollout_restart_mocked(self, executor, k8s_client_mod):
        """rollout_restart patches deployment annotation."""
        mock_apps = AsyncMock()
        mock_apps.patch_namespaced_deployment.return_value = MagicMock()
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.rollout_restart(
            name="my-deploy", namespace="test-ns"
        )

        assert result.success is True
        assert "rollout_restart" in result.operation
        assert "restartedAt" in result.items[0]

        # Verify the patch was called with annotation
        call_kwargs = mock_apps.patch_namespaced_deployment.call_args.kwargs
        body = call_kwargs["body"]
        annotations = body["spec"]["template"]["metadata"]["annotations"]
        assert "kubectl.kubernetes.io/restartedAt" in annotations

    @pytest.mark.asyncio
    async def test_rollout_restart_api_error(self, executor, k8s_client_mod):
        """rollout_restart API errors returned as error result."""
        mock_apps = AsyncMock()
        mock_apps.patch_namespaced_deployment.side_effect = Exception("Forbidden")
        k8s_client_mod.AppsV1Api.return_value = mock_apps

        result = await executor.rollout_restart(name="my-deploy")

        assert result.success is False
        assert "Forbidden" in result.error


class TestKubernetesExecutorLifecycle:
    """Tests for executor lifecycle (close, client init)."""

    @pytest.mark.asyncio
    async def test_close_client(self):
        """close() properly disposes the API client."""
        from parrot_tools.kubernetes.executor import KubernetesExecutor
        from parrot_tools.kubernetes.config import KubernetesConfig

        exc = KubernetesExecutor(KubernetesConfig())
        mock_client = AsyncMock()
        exc._api_client = mock_client

        await exc.close()

        mock_client.close.assert_awaited_once()
        assert exc._api_client is None

    @pytest.mark.asyncio
    async def test_close_no_client(self):
        """close() is safe to call when no client has been initialized."""
        from parrot_tools.kubernetes.executor import KubernetesExecutor
        from parrot_tools.kubernetes.config import KubernetesConfig

        exc = KubernetesExecutor(KubernetesConfig())
        # Should not raise
        await exc.close()

    def test_import_error_message(self):
        """KubernetesExecutor initializes with _api_client as None (lazy)."""
        from parrot_tools.kubernetes.executor import KubernetesExecutor
        from parrot_tools.kubernetes.config import KubernetesConfig

        exc = KubernetesExecutor(KubernetesConfig())
        assert exc._api_client is None  # not yet initialized

    @pytest.mark.asyncio
    async def test_ensure_client_idempotent(self):
        """_ensure_client() is a no-op when client is already initialized."""
        from parrot_tools.kubernetes.executor import KubernetesExecutor
        from parrot_tools.kubernetes.config import KubernetesConfig

        exc = KubernetesExecutor(KubernetesConfig())
        mock_client = MagicMock()
        exc._api_client = mock_client  # pre-set

        # _ensure_client should return immediately (client already set)
        await exc._ensure_client()
        assert exc._api_client is mock_client  # unchanged
