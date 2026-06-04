"""KubernetesToolkit — AbstractToolkit exposing kubectl-like agent tools.

Mirrors PulumiToolkit pattern: inherits AbstractToolkit, builds a
KubernetesExecutor from a KubernetesConfig, and exposes each async public
method as a tool via get_tools().

Read operations (k8s_list_pods, k8s_get_logs, k8s_describe, k8s_get) carry
no grant requirement.

Mutating operations (k8s_apply_manifest, k8s_scale_deployment,
k8s_delete_resource, k8s_rollout_restart) carry
routing_meta={"requires_grant": True, "grant_scope": "k8s:write"}
for FEAT-211 governance integration.

Note on routing_meta: FEAT-211 (GrantGuard in ToolManager) will gate
mutating tools when wired. Without FEAT-211, mutating tools behave like
any other tool — no gating occurs. This toolkit only MARKS the metadata.
"""

from typing import Optional

from ..toolkit import AbstractToolkit

from .config import K8sOperationResult, KubernetesConfig
from .executor import KubernetesExecutor

# Mutating method names (exact match) — these get requires_grant metadata.
_MUTATING_METHODS = frozenset({
    "k8s_apply_manifest",
    "k8s_scale_deployment",
    "k8s_delete_resource",
    "k8s_rollout_restart",
})


class KubernetesToolkit(AbstractToolkit):
    """Kubernetes cluster management toolkit.

    Exposes kubectl-like operations as agent tools. Each public async method
    with prefix k8s_ is automatically discovered by AbstractToolkit.get_tools()
    and returned as a separate tool.

    Read operations (no grant required):
        - k8s_list_pods: List pods in a namespace
        - k8s_get_logs: Get logs from a pod
        - k8s_describe: Describe a Kubernetes resource
        - k8s_get: List resources by kind

    Mutating operations (requires_grant=True via routing_meta — FEAT-211):
        - k8s_apply_manifest: Apply a YAML manifest
        - k8s_scale_deployment: Scale a deployment's replicas
        - k8s_delete_resource: Delete a Kubernetes resource
        - k8s_rollout_restart: Restart a deployment (rolling)

    Example:
        toolkit = KubernetesToolkit(config=KubernetesConfig(namespace="prod"))
        tools = toolkit.get_tools()
        agent = Agent(tools=tools)
    """

    # Exclude 'close' from tool generation — it's a lifecycle method, not an agent tool.
    exclude_tools: tuple[str, ...] = ("close",)

    def __init__(
        self, config: Optional[KubernetesConfig] = None, **kwargs
    ) -> None:
        """Initialize the Kubernetes toolkit.

        Args:
            config: KubernetesConfig with connection settings. Uses defaults
                    if not provided (kubeconfig from default location).
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.config = config or KubernetesConfig()
        self._k8s_executor = KubernetesExecutor(self.config)

    def _generate_tools(self) -> None:
        """Generate tools and set routing_meta on mutating tools.

        Calls the base class to discover all public async methods as tools,
        then iterates the generated tool cache to mark the 4 mutating tools
        with requires_grant=True (for FEAT-211 governance).

        Read tools get no grant metadata (empty routing_meta dict).
        """
        super()._generate_tools()
        for name, tool in self._tool_cache.items():
            if name in _MUTATING_METHODS:
                tool.routing_meta = {
                    "requires_grant": True,
                    "grant_scope": "k8s:write",
                }

    async def close(self) -> None:
        """Close the underlying Kubernetes API client.

        Call this when the toolkit is no longer needed to release connections.
        This method is excluded from tool generation (see exclude_tools).
        """
        await self._k8s_executor.close()

    async def __aenter__(self) -> "KubernetesToolkit":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """Async context manager exit — closes the executor."""
        await self.close()

    # ------------------------------------------------------------------ #
    # READ operations (no grant required)                                  #
    # ------------------------------------------------------------------ #

    async def k8s_list_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
    ) -> K8sOperationResult:
        """List pods in a namespace with optional label selector filtering.

        Args:
            namespace: Target namespace. Defaults to the configured namespace.
            label_selector: Label selector string (e.g. "app=nginx,env=prod").

        Returns:
            K8sOperationResult with a list of pods (name, phase, node, ready).
        """
        self.logger.info(
            "k8s_list_pods: namespace=%s label_selector=%s",
            namespace or self.config.namespace,
            label_selector,
        )
        return await self._k8s_executor.list_pods(
            namespace=namespace,
            label_selector=label_selector,
        )

    async def k8s_get_logs(
        self,
        pod: str,
        namespace: Optional[str] = None,
        container: Optional[str] = None,
        tail_lines: int = 200,
    ) -> K8sOperationResult:
        """Get logs from a pod, optionally from a specific container.

        Logs are truncated to prevent flooding the LLM context window.

        Args:
            pod: Pod name.
            namespace: Target namespace. Defaults to the configured namespace.
            container: Container name (required for multi-container pods).
            tail_lines: Number of log lines to return from the end. Default 200.

        Returns:
            K8sOperationResult with the log text (truncated if too large).
        """
        self.logger.info(
            "k8s_get_logs: pod=%s namespace=%s container=%s tail_lines=%d",
            pod,
            namespace or self.config.namespace,
            container,
            tail_lines,
        )
        return await self._k8s_executor.get_logs(
            pod=pod,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
        )

    async def k8s_describe(
        self,
        kind: str,
        name: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Describe a Kubernetes resource (kubectl describe equivalent).

        Supported kinds: Pod, Deployment, Service, ConfigMap, Secret,
        StatefulSet, DaemonSet, ReplicaSet.

        Args:
            kind: Resource kind (e.g. "Pod", "Deployment", "Service").
            name: Resource name.
            namespace: Target namespace. Defaults to the configured namespace.

        Returns:
            K8sOperationResult with a summary dict of the resource.
        """
        self.logger.info(
            "k8s_describe: kind=%s name=%s namespace=%s",
            kind,
            name,
            namespace or self.config.namespace,
        )
        if not kind or not kind.strip():
            return K8sOperationResult(
                success=False,
                operation="describe",
                summary="Invalid input",
                error="kind must not be empty",
            )
        if not name or not name.strip():
            return K8sOperationResult(
                success=False,
                operation="describe",
                summary="Invalid input",
                error="name must not be empty",
            )
        return await self._k8s_executor.describe(kind=kind, name=name, namespace=namespace)

    async def k8s_get(
        self,
        kind: str,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
    ) -> K8sOperationResult:
        """List Kubernetes resources by kind with optional label filtering.

        Supported kinds: Pod, Deployment, Service, ConfigMap, Secret,
        StatefulSet, DaemonSet.

        Args:
            kind: Resource kind (e.g. "Deployment", "Service", "Pod").
            namespace: Target namespace. Defaults to the configured namespace.
            label_selector: Label selector string (e.g. "app=nginx").

        Returns:
            K8sOperationResult with a list of bounded resource projections.
        """
        self.logger.info(
            "k8s_get: kind=%s namespace=%s label_selector=%s",
            kind,
            namespace or self.config.namespace,
            label_selector,
        )
        if not kind or not kind.strip():
            return K8sOperationResult(
                success=False,
                operation="get",
                summary="Invalid input",
                error="kind must not be empty",
            )
        return await self._k8s_executor.get_resources(
            kind=kind,
            namespace=namespace,
            label_selector=label_selector,
        )

    # ------------------------------------------------------------------ #
    # MUTATING operations (requires_grant via routing_meta — FEAT-211)    #
    # ------------------------------------------------------------------ #

    async def k8s_apply_manifest(
        self,
        manifest_yaml: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Apply a Kubernetes manifest YAML string to the cluster.

        Equivalent to kubectl apply -f. Supports multi-document YAML.
        Mutating operation — requires grant approval (FEAT-211).

        Args:
            manifest_yaml: YAML string of the manifest to apply. May contain
                multiple documents separated by ---.
            namespace: Target namespace override. Defaults to the namespace
                       in the manifest or the configured namespace.

        Returns:
            K8sOperationResult with a list of applied/updated resources.
        """
        self.logger.info(
            "k8s_apply_manifest: namespace=%s manifest_length=%d",
            namespace or self.config.namespace,
            len(manifest_yaml),
        )
        if not manifest_yaml or not manifest_yaml.strip():
            return K8sOperationResult(
                success=False,
                operation="apply",
                summary="Invalid input",
                error="manifest_yaml must not be empty",
            )
        return await self._k8s_executor.apply_manifest(
            manifest_yaml=manifest_yaml,
            namespace=namespace,
        )

    async def k8s_scale_deployment(
        self,
        name: str,
        replicas: int,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Scale a Deployment to the specified number of replicas.

        Equivalent to kubectl scale deployment <name> --replicas=<n>.
        Mutating operation — requires grant approval (FEAT-211).

        Args:
            name: Deployment name.
            replicas: Desired number of replicas (must be >= 0).
            namespace: Target namespace. Defaults to the configured namespace.

        Returns:
            K8sOperationResult confirming the scale operation.
        """
        self.logger.info(
            "k8s_scale_deployment: name=%s replicas=%d namespace=%s",
            name,
            replicas,
            namespace or self.config.namespace,
        )
        if not name or not name.strip():
            return K8sOperationResult(
                success=False,
                operation="scale",
                summary="Invalid input",
                error="name must not be empty",
            )
        return await self._k8s_executor.scale_deployment(
            name=name,
            replicas=replicas,
            namespace=namespace,
        )

    async def k8s_delete_resource(
        self,
        kind: str,
        name: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Delete a Kubernetes resource by kind and name.

        Equivalent to kubectl delete <kind> <name>.
        Mutating operation — requires grant approval (FEAT-211).

        Supported kinds: Pod, Deployment, Service, ConfigMap, Secret,
        StatefulSet, DaemonSet.

        WARNING: This operation is destructive and cannot be undone.

        Args:
            kind: Resource kind (e.g. "Pod", "Deployment").
            name: Resource name.
            namespace: Target namespace. Defaults to the configured namespace.

        Returns:
            K8sOperationResult confirming deletion.
        """
        self.logger.info(
            "k8s_delete_resource: kind=%s name=%s namespace=%s",
            kind,
            name,
            namespace or self.config.namespace,
        )
        if not kind or not kind.strip():
            return K8sOperationResult(
                success=False,
                operation="delete",
                summary="Invalid input",
                error="kind must not be empty",
            )
        if not name or not name.strip():
            return K8sOperationResult(
                success=False,
                operation="delete",
                summary="Invalid input",
                error="name must not be empty",
            )
        return await self._k8s_executor.delete_resource(
            kind=kind,
            name=name,
            namespace=namespace,
        )

    async def k8s_rollout_restart(
        self,
        name: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Restart a Deployment by patching its pod template annotation.

        Equivalent to kubectl rollout restart deployment/<name>.
        Triggers a rolling update without changing the container spec.
        Mutating operation — requires grant approval (FEAT-211).

        Args:
            name: Deployment name.
            namespace: Target namespace. Defaults to the configured namespace.

        Returns:
            K8sOperationResult confirming the restart was triggered.
        """
        self.logger.info(
            "k8s_rollout_restart: name=%s namespace=%s",
            name,
            namespace or self.config.namespace,
        )
        if not name or not name.strip():
            return K8sOperationResult(
                success=False,
                operation="rollout_restart",
                summary="Invalid input",
                error="name must not be empty",
            )
        return await self._k8s_executor.rollout_restart(name=name, namespace=namespace)
