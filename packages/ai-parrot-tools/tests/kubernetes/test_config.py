"""Unit tests for KubernetesConfig and K8sOperationResult models (TASK-1122)."""

import pytest
from pydantic import ValidationError
from parrot_tools.kubernetes.config import K8sOperationResult, KubernetesConfig


class TestKubernetesConfig:
    """Tests for KubernetesConfig defaults and validation."""

    def test_defaults(self):
        """Default config has namespace='default', timeout=60, in_cluster=False."""
        cfg = KubernetesConfig()
        assert cfg.namespace == "default"
        assert cfg.timeout_seconds == 60
        assert cfg.in_cluster is False
        assert cfg.kubeconfig_path is None
        assert cfg.context is None

    def test_custom_values(self):
        """Custom values are stored correctly."""
        cfg = KubernetesConfig(
            kubeconfig_path="/home/user/.kube/config",
            context="minikube",
            namespace="production",
            in_cluster=False,
            timeout_seconds=120,
        )
        assert cfg.namespace == "production"
        assert cfg.context == "minikube"
        assert cfg.kubeconfig_path == "/home/user/.kube/config"
        assert cfg.timeout_seconds == 120

    def test_in_cluster_flag(self):
        """in_cluster flag is stored as bool."""
        cfg = KubernetesConfig(in_cluster=True)
        assert cfg.in_cluster is True

    def test_timeout_must_be_positive(self):
        """timeout_seconds must be > 0 (gt=0 validator)."""
        with pytest.raises(ValidationError):
            KubernetesConfig(timeout_seconds=0)

    def test_timeout_negative_rejected(self):
        """Negative timeout_seconds is rejected."""
        with pytest.raises(ValidationError):
            KubernetesConfig(timeout_seconds=-10)

    def test_timeout_positive_accepted(self):
        """Positive timeout_seconds is accepted."""
        cfg = KubernetesConfig(timeout_seconds=1)
        assert cfg.timeout_seconds == 1

    def test_serialization(self):
        """KubernetesConfig serializes to dict."""
        cfg = KubernetesConfig(namespace="staging", timeout_seconds=30)
        data = cfg.model_dump()
        assert isinstance(data, dict)
        assert data["namespace"] == "staging"
        assert data["timeout_seconds"] == 30
        assert data["in_cluster"] is False


class TestK8sOperationResult:
    """Tests for K8sOperationResult model."""

    def test_success_result(self):
        """Successful result with items is stored correctly."""
        result = K8sOperationResult(
            success=True,
            operation="list_pods",
            summary="Found 3 pods",
            items=[{"name": "pod-1"}, {"name": "pod-2"}, {"name": "pod-3"}],
        )
        assert result.success is True
        assert len(result.items) == 3
        assert result.error is None
        assert result.operation == "list_pods"
        assert result.summary == "Found 3 pods"

    def test_error_result(self):
        """Failed result with error message."""
        result = K8sOperationResult(
            success=False,
            operation="scale_deployment",
            summary="Failed to scale",
            error="Deployment not found",
        )
        assert result.success is False
        assert result.error == "Deployment not found"
        assert result.items == []

    def test_items_default_empty(self):
        """items defaults to an empty list."""
        result = K8sOperationResult(
            success=True,
            operation="delete",
            summary="Deleted successfully",
        )
        assert result.items == []

    def test_serialization(self):
        """K8sOperationResult serializes to dict (Pydantic v2)."""
        result = K8sOperationResult(
            success=True, operation="get", summary="OK", items=[{"a": 1}]
        )
        data = result.model_dump()
        assert isinstance(data, dict)
        assert data["success"] is True
        assert data["items"] == [{"a": 1}]
        assert data["error"] is None

    def test_bounded_items(self):
        """items holds a list of dicts (bounded projections)."""
        items = [
            {"name": f"pod-{i}", "phase": "Running", "node": "node-1"}
            for i in range(10)
        ]
        result = K8sOperationResult(
            success=True,
            operation="list_pods",
            summary="Found 10 pods",
            items=items,
        )
        assert len(result.items) == 10
        assert all(isinstance(item, dict) for item in result.items)

    def test_operation_field_required(self):
        """operation field is required."""
        with pytest.raises(ValidationError):
            K8sOperationResult(success=True, summary="OK")  # missing operation

    def test_summary_field_required(self):
        """summary field is required."""
        with pytest.raises(ValidationError):
            K8sOperationResult(success=True, operation="get")  # missing summary
