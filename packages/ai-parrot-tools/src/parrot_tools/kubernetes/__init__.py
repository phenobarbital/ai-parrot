"""Kubernetes Toolkit for AI-Parrot agents.

Provides kubectl-like cluster management operations as agent tools.
Read operations (list_pods, get_logs, describe, get) require no grant.
Mutating operations (apply_manifest, scale_deployment, delete_resource,
rollout_restart) carry routing_meta["requires_grant"] = True for FEAT-211
governance integration.
"""

from .config import K8sOperationResult, KubernetesConfig
from .executor import KubernetesExecutor

__all__ = [
    "KubernetesConfig",
    "K8sOperationResult",
    "KubernetesExecutor",
]
