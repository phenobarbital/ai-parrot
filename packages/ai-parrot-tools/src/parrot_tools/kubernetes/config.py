"""Kubernetes Toolkit configuration and result models.

Provides Pydantic models for KubernetesConfig and K8sOperationResult,
mirroring the PulumiConfig/PulumiOperationResult pattern.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class KubernetesConfig(BaseModel):
    """Configuration for KubernetesExecutor.

    Supports both in-cluster (service account) and kubeconfig-based authentication.
    Mirrors PulumiConfig pattern but stands alone (no Docker/CLI inheritance).

    Example:
        # Default in-cluster config
        cfg = KubernetesConfig(in_cluster=True)

        # Kubeconfig with specific context
        cfg = KubernetesConfig(
            kubeconfig_path="/home/user/.kube/config",
            context="minikube",
            namespace="production",
        )
    """

    kubeconfig_path: Optional[str] = Field(
        default=None,
        description="Path to kubeconfig file. None uses default (~/.kube/config or KUBECONFIG env).",
    )
    context: Optional[str] = Field(
        default=None,
        description="Kubernetes context to use from kubeconfig. None uses the current context.",
    )
    namespace: str = Field(
        default="default",
        description="Default namespace for operations when not explicitly specified.",
    )
    in_cluster: bool = Field(
        default=False,
        description="If True, use in-cluster service account config (for pods running inside k8s).",
    )
    timeout_seconds: int = Field(
        default=60,
        gt=0,
        description="Timeout in seconds for Kubernetes API operations. Must be positive.",
    )


class K8sOperationResult(BaseModel):
    """Result of a Kubernetes operation.

    Contains the outcome of a kubectl-like operation with bounded projections.
    Items are simplified dicts — never full Kubernetes API objects — to avoid
    flooding the LLM context with raw API responses.

    Example:
        result = K8sOperationResult(
            success=True,
            operation="list_pods",
            summary="Found 3 pods in namespace default",
            items=[{"name": "pod-1", "phase": "Running"}],
        )
    """

    success: bool = Field(
        ...,
        description="Whether the operation completed successfully.",
    )
    operation: str = Field(
        ...,
        description="Operation type: 'list_pods', 'get_logs', 'describe', 'get', "
                    "'apply', 'scale', 'delete', 'rollout_restart'.",
    )
    summary: str = Field(
        ...,
        description="Human-readable summary of the operation result.",
    )
    items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Bounded projection of resources affected/returned. "
                    "Never contains full Kubernetes API objects.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if operation failed. None on success.",
    )
