"""KubernetesExecutor — async Kubernetes client wrapper.

Wraps kubernetes_asyncio to provide kubectl-like operations for AI agents.
Returns bounded K8sOperationResult projections; never dumps raw API objects.

Mirrors PulumiExecutor pattern but is standalone (does not inherit
BaseExecutor because that is oriented toward Docker/CLI subprocess execution).

kubernetes_asyncio is lazy-imported to avoid cost when the toolkit is not
used. See K8sToolExecutor (parrot/tools/executors/k8s.py) for the same pattern.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .config import K8sOperationResult, KubernetesConfig

# Maximum characters to return from pod logs (prevents flooding LLM context)
_MAX_LOG_CHARS = 50_000


def _now_ts() -> str:
    """Return current UTC timestamp as string (for rollout restart annotation)."""
    return datetime.now(tz=timezone.utc).isoformat()


class KubernetesExecutor:
    """Async Kubernetes client wrapper.

    Wraps kubernetes_asyncio (CoreV1Api, AppsV1Api) to implement read and
    mutating operations, returning bounded K8sOperationResult projections.

    kubernetes_asyncio is lazy-imported inside _ensure_client() to avoid
    import-time cost when the package is not installed.

    Example:
        config = KubernetesConfig(namespace="production")
        executor = KubernetesExecutor(config)
        result = await executor.list_pods()
        await executor.close()
    """

    def __init__(self, config: KubernetesConfig) -> None:
        """Initialize the executor with Kubernetes configuration.

        Args:
            config: KubernetesConfig with kubeconfig path, context, namespace,
                    in-cluster flag, and timeout.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._api_client = None  # lazy-initialized by _ensure_client()

    async def _ensure_client(self) -> None:
        """Lazy-initialize the kubernetes_asyncio ApiClient.

        Loads kubeconfig (file or in-cluster) on first call.
        Subsequent calls are no-ops.

        Raises:
            ImportError: If kubernetes_asyncio is not installed.
        """
        if self._api_client is not None:
            return

        try:
            import kubernetes_asyncio  # noqa: F401
            from kubernetes_asyncio import client as k8s_client
            from kubernetes_asyncio import config as k8s_config
        except ImportError as exc:
            raise ImportError(
                "kubernetes_asyncio is required for KubernetesToolkit. "
                "Install with: uv pip install kubernetes_asyncio"
            ) from exc

        if self.config.in_cluster:
            k8s_config.load_incluster_config()
        else:
            await k8s_config.load_kube_config(
                config_file=self.config.kubeconfig_path,
                context=self.config.context,
            )

        self._api_client = k8s_client.ApiClient()

    async def close(self) -> None:
        """Close the API client to release connections.

        Must be called when the executor is no longer needed to avoid
        connection leaks.
        """
        if self._api_client is not None:
            await self._api_client.close()
            self._api_client = None

    # ------------------------------------------------------------------ #
    # READ operations                                                      #
    # ------------------------------------------------------------------ #

    async def list_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
    ) -> K8sOperationResult:
        """List pods in a namespace with optional label filtering.

        Args:
            namespace: Target namespace. Defaults to config.namespace.
            label_selector: Optional label selector (e.g. "app=nginx").

        Returns:
            K8sOperationResult with bounded pod projections.
        """
        ns = namespace or self.config.namespace
        try:
            await self._ensure_client()
            from kubernetes_asyncio import client as k8s_client
            from kubernetes_asyncio.client.exceptions import ApiException

            v1 = k8s_client.CoreV1Api(self._api_client)
            kwargs: dict[str, Any] = {"namespace": ns}
            if label_selector:
                kwargs["label_selector"] = label_selector

            response = await v1.list_namespaced_pod(
                **kwargs, _request_timeout=self.config.timeout_seconds
            )
            items = [
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase if pod.status else None,
                    "node": pod.spec.node_name if pod.spec else None,
                    "ready": _pod_ready(pod),
                    "restarts": _pod_restarts(pod),
                }
                for pod in response.items
            ]
            return K8sOperationResult(
                success=True,
                operation="list_pods",
                summary=f"Found {len(items)} pod(s) in namespace '{ns}'",
                items=items,
            )
        except ApiException as exc:
            self.logger.error("list_pods failed: [%s] %s", exc.status, exc.reason)
            return K8sOperationResult(
                success=False,
                operation="list_pods",
                summary=f"Failed to list pods in namespace '{ns}'",
                error=f"[{exc.status}] {exc.reason}",
            )
        except Exception as exc:
            self.logger.exception("list_pods unexpected error")
            return K8sOperationResult(
                success=False,
                operation="list_pods",
                summary=f"Failed to list pods in namespace '{ns}'",
                error=str(exc),
            )

    async def get_logs(
        self,
        pod: str,
        namespace: Optional[str] = None,
        container: Optional[str] = None,
        tail_lines: int = 200,
    ) -> K8sOperationResult:
        """Get logs from a pod, optionally from a specific container.

        Args:
            pod: Pod name.
            namespace: Target namespace. Defaults to config.namespace.
            container: Container name (required for multi-container pods).
            tail_lines: Number of lines to return from the end of logs.

        Returns:
            K8sOperationResult with log output truncated to _MAX_LOG_CHARS.
        """
        ns = namespace or self.config.namespace
        try:
            await self._ensure_client()
            from kubernetes_asyncio import client as k8s_client
            from kubernetes_asyncio.client.exceptions import ApiException

            v1 = k8s_client.CoreV1Api(self._api_client)
            kwargs: dict[str, Any] = {
                "name": pod,
                "namespace": ns,
                "tail_lines": tail_lines,
                "_request_timeout": self.config.timeout_seconds,
            }
            if container:
                kwargs["container"] = container

            log_text = await v1.read_namespaced_pod_log(**kwargs)

            # Guard: ensure log_text is a string
            if not isinstance(log_text, str):
                log_text = str(log_text or "")

            # Truncate to avoid flooding LLM context
            if len(log_text) > _MAX_LOG_CHARS:
                log_text = log_text[-_MAX_LOG_CHARS:]
                truncated = True
            else:
                truncated = False

            summary = f"Logs for pod '{pod}' in '{ns}'"
            if truncated:
                summary += f" (truncated to last {_MAX_LOG_CHARS} chars)"

            return K8sOperationResult(
                success=True,
                operation="get_logs",
                summary=summary,
                items=[{"pod": pod, "namespace": ns, "log": log_text}],
            )
        except ApiException as exc:
            self.logger.error("get_logs failed for pod '%s': [%s] %s", pod, exc.status, exc.reason)
            return K8sOperationResult(
                success=False,
                operation="get_logs",
                summary=f"Failed to get logs for pod '{pod}'",
                error=f"[{exc.status}] {exc.reason}",
            )
        except Exception as exc:
            self.logger.exception("get_logs unexpected error for pod '%s'", pod)
            return K8sOperationResult(
                success=False,
                operation="get_logs",
                summary=f"Failed to get logs for pod '{pod}'",
                error=str(exc),
            )

    async def describe(
        self,
        kind: str,
        name: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Describe a Kubernetes resource (kubectl describe equivalent).

        Supports common kinds: Pod, Deployment, Service, ConfigMap, Secret,
        StatefulSet, DaemonSet, ReplicaSet.

        Args:
            kind: Resource kind (e.g. "Pod", "Deployment").
            name: Resource name.
            namespace: Target namespace. Defaults to config.namespace.

        Returns:
            K8sOperationResult with a summary dict of the resource.
        """
        ns = namespace or self.config.namespace
        kind_lower = kind.lower()

        try:
            await self._ensure_client()
            from kubernetes_asyncio.client.exceptions import ApiException

            item = await self._get_single_resource(kind_lower, name, ns)
            if item is None:
                return K8sOperationResult(
                    success=False,
                    operation="describe",
                    summary=f"Unsupported kind '{kind}' for describe",
                    error=f"Kind '{kind}' is not supported. "
                          "Supported kinds: Pod, Deployment, Service, ConfigMap, "
                          "Secret, StatefulSet, DaemonSet, ReplicaSet.",
                )
            return K8sOperationResult(
                success=True,
                operation="describe",
                summary=f"Described {kind} '{name}' in '{ns}'",
                items=[item],
            )
        except ApiException as exc:
            self.logger.error("describe failed for %s/%s: [%s] %s", kind, name, exc.status, exc.reason)
            return K8sOperationResult(
                success=False,
                operation="describe",
                summary=f"Failed to describe {kind} '{name}'",
                error=f"[{exc.status}] {exc.reason}",
            )
        except Exception as exc:
            self.logger.exception("describe unexpected error for %s/%s", kind, name)
            return K8sOperationResult(
                success=False,
                operation="describe",
                summary=f"Failed to describe {kind} '{name}'",
                error=str(exc),
            )

    async def get_resources(
        self,
        kind: str,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
    ) -> K8sOperationResult:
        """List Kubernetes resources by kind with optional label filtering.

        Supports common kinds: Pod, Deployment, Service, ConfigMap, Secret,
        StatefulSet, DaemonSet, ReplicaSet.

        Args:
            kind: Resource kind (e.g. "Deployment", "Service").
            namespace: Target namespace. Defaults to config.namespace.
            label_selector: Optional label selector string.

        Returns:
            K8sOperationResult with bounded resource projections.
        """
        ns = namespace or self.config.namespace
        kind_lower = kind.lower()

        try:
            await self._ensure_client()
            from kubernetes_asyncio.client.exceptions import ApiException

            items = await self._list_resources(kind_lower, ns, label_selector)
            if items is None:
                return K8sOperationResult(
                    success=False,
                    operation="get",
                    summary=f"Unsupported kind '{kind}'",
                    error=f"Kind '{kind}' is not supported. "
                          "Supported kinds: Pod, Deployment, Service, ConfigMap, "
                          "Secret, StatefulSet, DaemonSet, ReplicaSet.",
                )
            return K8sOperationResult(
                success=True,
                operation="get",
                summary=f"Found {len(items)} {kind}(s) in '{ns}'",
                items=items,
            )
        except ApiException as exc:
            self.logger.error("get_resources failed for kind %s: [%s] %s", kind, exc.status, exc.reason)
            return K8sOperationResult(
                success=False,
                operation="get",
                summary=f"Failed to get {kind} resources",
                error=f"[{exc.status}] {exc.reason}",
            )
        except Exception as exc:
            self.logger.exception("get_resources unexpected error for kind %s", kind)
            return K8sOperationResult(
                success=False,
                operation="get",
                summary=f"Failed to get {kind} resources",
                error=str(exc),
            )

    # ------------------------------------------------------------------ #
    # MUTATING operations                                                  #
    # ------------------------------------------------------------------ #

    async def apply_manifest(
        self,
        manifest_yaml: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Create Kubernetes resources from a manifest YAML string.

        Parses the YAML manifest and creates each resource. On conflict
        (409 Already Exists), the resource is skipped (not patched).
        Supports multi-document YAML (separated by ---).

        Args:
            manifest_yaml: YAML string of the manifest to apply.
            namespace: Target namespace override. Defaults to config.namespace
                       or the namespace in the manifest.

        Returns:
            K8sOperationResult with a list of created/skipped resources.
        """
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required for apply_manifest. "
                "Install with: pip install pyyaml"
            ) from exc

        ns_override = namespace or self.config.namespace
        applied = []
        errors = []

        try:
            await self._ensure_client()
            from kubernetes_asyncio.client.exceptions import ApiException
            from kubernetes_asyncio.utils import create_from_dict

            docs = list(yaml.safe_load_all(manifest_yaml))
            docs = [d for d in docs if d is not None]  # skip empty docs

            if not docs:
                return K8sOperationResult(
                    success=False,
                    operation="apply",
                    summary="No valid YAML documents found in manifest",
                    error="Empty or invalid manifest YAML",
                )

            for doc in docs:
                # Inject namespace if not set in manifest
                if "metadata" in doc:
                    if "namespace" not in doc["metadata"]:
                        doc["metadata"]["namespace"] = ns_override

                kind = doc.get("kind", "Unknown")
                name = doc.get("metadata", {}).get("name", "unknown")

                try:
                    await create_from_dict(self._api_client, doc, namespace=ns_override)
                    applied.append({"kind": kind, "name": name, "action": "applied"})
                except ApiException as e:
                    if e.status == 409:
                        applied.append({"kind": kind, "name": name, "action": "skipped (already exists)"})
                    else:
                        errors.append({"kind": kind, "name": name, "error": f"[{e.status}] {e.reason}"})
                except Exception as e:
                    err_str = str(e)
                    if "already exists" in err_str:
                        applied.append({"kind": kind, "name": name, "action": "skipped (already exists)"})
                    else:
                        errors.append({"kind": kind, "name": name, "error": err_str})

            success = len(errors) == 0
            summary = f"Applied {len(applied)} resource(s)"
            if errors:
                summary += f"; {len(errors)} error(s)"

            return K8sOperationResult(
                success=success,
                operation="apply",
                summary=summary,
                items=applied + errors,
                error="; ".join(e["error"] for e in errors) if errors else None,
            )
        except Exception as exc:
            self.logger.exception("apply_manifest unexpected error")
            return K8sOperationResult(
                success=False,
                operation="apply",
                summary="Failed to apply manifest",
                error=str(exc),
            )

    async def scale_deployment(
        self,
        name: str,
        replicas: int,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Scale a Deployment to the specified number of replicas.

        Args:
            name: Deployment name.
            replicas: Desired number of replicas (must be >= 0).
            namespace: Target namespace. Defaults to config.namespace.

        Returns:
            K8sOperationResult confirming the scale operation.
        """
        ns = namespace or self.config.namespace
        if replicas < 0:
            return K8sOperationResult(
                success=False,
                operation="scale",
                summary="Invalid replicas value",
                error=f"replicas must be >= 0, got {replicas}",
            )

        try:
            await self._ensure_client()
            from kubernetes_asyncio import client as k8s_client
            from kubernetes_asyncio.client.exceptions import ApiException

            apps_v1 = k8s_client.AppsV1Api(self._api_client)
            scale_body = {"spec": {"replicas": replicas}}
            await apps_v1.patch_namespaced_deployment_scale(
                name=name,
                namespace=ns,
                body=scale_body,
                _request_timeout=self.config.timeout_seconds,
            )
            return K8sOperationResult(
                success=True,
                operation="scale",
                summary=f"Scaled deployment '{name}' to {replicas} replica(s) in '{ns}'",
                items=[{"name": name, "namespace": ns, "replicas": replicas}],
            )
        except ApiException as exc:
            self.logger.error("scale_deployment failed for '%s': [%s] %s", name, exc.status, exc.reason)
            return K8sOperationResult(
                success=False,
                operation="scale",
                summary=f"Failed to scale deployment '{name}'",
                error=f"[{exc.status}] {exc.reason}",
            )
        except Exception as exc:
            self.logger.exception("scale_deployment unexpected error for '%s'", name)
            return K8sOperationResult(
                success=False,
                operation="scale",
                summary=f"Failed to scale deployment '{name}'",
                error=str(exc),
            )

    async def delete_resource(
        self,
        kind: str,
        name: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Delete a Kubernetes resource by kind and name.

        Supports common kinds: Pod, Deployment, Service, ConfigMap, Secret,
        StatefulSet, DaemonSet, ReplicaSet.

        Args:
            kind: Resource kind (e.g. "Pod", "Deployment").
            name: Resource name.
            namespace: Target namespace. Defaults to config.namespace.

        Returns:
            K8sOperationResult confirming deletion.
        """
        ns = namespace or self.config.namespace
        kind_lower = kind.lower()

        try:
            await self._ensure_client()
            from kubernetes_asyncio import client as k8s_client
            from kubernetes_asyncio.client.exceptions import ApiException

            v1 = k8s_client.CoreV1Api(self._api_client)
            apps_v1 = k8s_client.AppsV1Api(self._api_client)
            timeout = self.config.timeout_seconds

            if kind_lower in {"pod", "pods"}:
                await v1.delete_namespaced_pod(name=name, namespace=ns, _request_timeout=timeout)
            elif kind_lower in {"service", "services", "svc"}:
                await v1.delete_namespaced_service(name=name, namespace=ns, _request_timeout=timeout)
            elif kind_lower in {"configmap", "configmaps", "cm"}:
                await v1.delete_namespaced_config_map(name=name, namespace=ns, _request_timeout=timeout)
            elif kind_lower in {"secret", "secrets"}:
                await v1.delete_namespaced_secret(name=name, namespace=ns, _request_timeout=timeout)
            elif kind_lower in {"deployment", "deployments", "deploy"}:
                await apps_v1.delete_namespaced_deployment(name=name, namespace=ns, _request_timeout=timeout)
            elif kind_lower in {"statefulset", "statefulsets", "sts"}:
                await apps_v1.delete_namespaced_stateful_set(name=name, namespace=ns, _request_timeout=timeout)
            elif kind_lower in {"daemonset", "daemonsets", "ds"}:
                await apps_v1.delete_namespaced_daemon_set(name=name, namespace=ns, _request_timeout=timeout)
            elif kind_lower in {"replicaset", "replicasets", "rs"}:
                await apps_v1.delete_namespaced_replica_set(name=name, namespace=ns, _request_timeout=timeout)
            else:
                return K8sOperationResult(
                    success=False,
                    operation="delete",
                    summary=f"Unsupported kind '{kind}' for delete",
                    error=f"Kind '{kind}' is not supported for delete. "
                          "Supported: Pod, Service, ConfigMap, Secret, "
                          "Deployment, StatefulSet, DaemonSet, ReplicaSet.",
                )

            return K8sOperationResult(
                success=True,
                operation="delete",
                summary=f"Deleted {kind} '{name}' in '{ns}'",
                items=[{"kind": kind, "name": name, "namespace": ns, "status": "deleted"}],
            )
        except ApiException as exc:
            self.logger.error("delete_resource failed for %s/%s: [%s] %s", kind, name, exc.status, exc.reason)
            return K8sOperationResult(
                success=False,
                operation="delete",
                summary=f"Failed to delete {kind} '{name}'",
                error=f"[{exc.status}] {exc.reason}",
            )
        except Exception as exc:
            self.logger.exception("delete_resource unexpected error for %s/%s", kind, name)
            return K8sOperationResult(
                success=False,
                operation="delete",
                summary=f"Failed to delete {kind} '{name}'",
                error=str(exc),
            )

    async def rollout_restart(
        self,
        name: str,
        namespace: Optional[str] = None,
    ) -> K8sOperationResult:
        """Restart a Deployment by patching its pod template annotation.

        Equivalent to kubectl rollout restart deployment/<name>.
        Patches spec.template.metadata.annotations with a restart timestamp,
        triggering a rolling update without changing the container spec.

        Args:
            name: Deployment name.
            namespace: Target namespace. Defaults to config.namespace.

        Returns:
            K8sOperationResult confirming the restart was triggered.
        """
        ns = namespace or self.config.namespace
        restart_ts = _now_ts()

        try:
            await self._ensure_client()
            from kubernetes_asyncio import client as k8s_client
            from kubernetes_asyncio.client.exceptions import ApiException

            apps_v1 = k8s_client.AppsV1Api(self._api_client)
            patch_body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": restart_ts,
                            }
                        }
                    }
                }
            }
            await apps_v1.patch_namespaced_deployment(
                name=name,
                namespace=ns,
                body=patch_body,
                _request_timeout=self.config.timeout_seconds,
            )
            return K8sOperationResult(
                success=True,
                operation="rollout_restart",
                summary=f"Rollout restart triggered for deployment '{name}' in '{ns}'",
                items=[{"name": name, "namespace": ns, "restartedAt": restart_ts}],
            )
        except ApiException as exc:
            self.logger.error("rollout_restart failed for '%s': [%s] %s", name, exc.status, exc.reason)
            return K8sOperationResult(
                success=False,
                operation="rollout_restart",
                summary=f"Failed to rollout restart deployment '{name}'",
                error=f"[{exc.status}] {exc.reason}",
            )
        except Exception as exc:
            self.logger.exception("rollout_restart unexpected error for '%s'", name)
            return K8sOperationResult(
                success=False,
                operation="rollout_restart",
                summary=f"Failed to rollout restart deployment '{name}'",
                error=str(exc),
            )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _get_single_resource(
        self, kind_lower: str, name: str, ns: str
    ) -> Optional[dict[str, Any]]:
        """Get a single resource and return a bounded projection dict.

        Args:
            kind_lower: Lowercase kind string.
            name: Resource name.
            ns: Namespace.

        Returns:
            Bounded projection dict, or None if kind is unsupported.
        """
        from kubernetes_asyncio import client as k8s_client

        v1 = k8s_client.CoreV1Api(self._api_client)
        apps_v1 = k8s_client.AppsV1Api(self._api_client)
        timeout = self.config.timeout_seconds

        if kind_lower in {"pod", "pods"}:
            obj = await v1.read_namespaced_pod(name=name, namespace=ns, _request_timeout=timeout)
            return {
                "kind": "Pod",
                "name": obj.metadata.name,
                "namespace": obj.metadata.namespace,
                "phase": obj.status.phase if obj.status else None,
                "node": obj.spec.node_name if obj.spec else None,
                "ready": _pod_ready(obj),
                "labels": obj.metadata.labels or {},
            }
        elif kind_lower in {"deployment", "deployments", "deploy"}:
            obj = await apps_v1.read_namespaced_deployment(name=name, namespace=ns, _request_timeout=timeout)
            return {
                "kind": "Deployment",
                "name": obj.metadata.name,
                "namespace": obj.metadata.namespace,
                "replicas": obj.spec.replicas if obj.spec else None,
                "ready_replicas": obj.status.ready_replicas if obj.status else None,
                "labels": obj.metadata.labels or {},
            }
        elif kind_lower in {"service", "services", "svc"}:
            obj = await v1.read_namespaced_service(name=name, namespace=ns, _request_timeout=timeout)
            return {
                "kind": "Service",
                "name": obj.metadata.name,
                "namespace": obj.metadata.namespace,
                "type": obj.spec.type if obj.spec else None,
                "cluster_ip": obj.spec.cluster_ip if obj.spec else None,
                "ports": [
                    {"port": p.port, "protocol": p.protocol}
                    for p in (obj.spec.ports or [])
                ] if obj.spec else [],
            }
        elif kind_lower in {"configmap", "configmaps", "cm"}:
            obj = await v1.read_namespaced_config_map(name=name, namespace=ns, _request_timeout=timeout)
            return {
                "kind": "ConfigMap",
                "name": obj.metadata.name,
                "namespace": obj.metadata.namespace,
                "data_keys": list(obj.data.keys()) if obj.data else [],
            }
        elif kind_lower in {"secret", "secrets"}:
            obj = await v1.read_namespaced_secret(name=name, namespace=ns, _request_timeout=timeout)
            return {
                "kind": "Secret",
                "name": obj.metadata.name,
                "namespace": obj.metadata.namespace,
                "type": obj.type,
                "data_keys": list(obj.data.keys()) if obj.data else [],
            }
        return None

    async def _list_resources(
        self, kind_lower: str, ns: str, label_selector: Optional[str]
    ) -> Optional[list[dict[str, Any]]]:
        """List resources of a given kind and return bounded projections.

        Args:
            kind_lower: Lowercase kind string.
            ns: Namespace.
            label_selector: Optional label selector string.

        Returns:
            List of bounded projection dicts, or None if kind unsupported.
        """
        from kubernetes_asyncio import client as k8s_client

        v1 = k8s_client.CoreV1Api(self._api_client)
        apps_v1 = k8s_client.AppsV1Api(self._api_client)
        timeout = self.config.timeout_seconds
        kwargs: dict[str, Any] = {"_request_timeout": timeout}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if kind_lower in {"pod", "pods"}:
            response = await v1.list_namespaced_pod(namespace=ns, **kwargs)
            return [
                {
                    "name": obj.metadata.name,
                    "namespace": obj.metadata.namespace,
                    "phase": obj.status.phase if obj.status else None,
                    "node": obj.spec.node_name if obj.spec else None,
                }
                for obj in response.items
            ]
        elif kind_lower in {"deployment", "deployments", "deploy"}:
            response = await apps_v1.list_namespaced_deployment(namespace=ns, **kwargs)
            return [
                {
                    "name": obj.metadata.name,
                    "namespace": obj.metadata.namespace,
                    "replicas": obj.spec.replicas if obj.spec else None,
                    "ready_replicas": obj.status.ready_replicas if obj.status else None,
                }
                for obj in response.items
            ]
        elif kind_lower in {"service", "services", "svc"}:
            response = await v1.list_namespaced_service(namespace=ns, **kwargs)
            return [
                {
                    "name": obj.metadata.name,
                    "namespace": obj.metadata.namespace,
                    "type": obj.spec.type if obj.spec else None,
                    "cluster_ip": obj.spec.cluster_ip if obj.spec else None,
                }
                for obj in response.items
            ]
        elif kind_lower in {"configmap", "configmaps", "cm"}:
            response = await v1.list_namespaced_config_map(namespace=ns, **kwargs)
            return [
                {
                    "name": obj.metadata.name,
                    "namespace": obj.metadata.namespace,
                    "data_keys": list(obj.data.keys()) if obj.data else [],
                }
                for obj in response.items
            ]
        elif kind_lower in {"secret", "secrets"}:
            response = await v1.list_namespaced_secret(namespace=ns, **kwargs)
            return [
                {
                    "name": obj.metadata.name,
                    "namespace": obj.metadata.namespace,
                    "type": obj.type,
                    "data_keys": list(obj.data.keys()) if obj.data else [],
                }
                for obj in response.items
            ]
        elif kind_lower in {"statefulset", "statefulsets", "sts"}:
            response = await apps_v1.list_namespaced_stateful_set(namespace=ns, **kwargs)
            return [
                {
                    "name": obj.metadata.name,
                    "namespace": obj.metadata.namespace,
                    "replicas": obj.spec.replicas if obj.spec else None,
                    "ready_replicas": obj.status.ready_replicas if obj.status else None,
                }
                for obj in response.items
            ]
        elif kind_lower in {"daemonset", "daemonsets", "ds"}:
            response = await apps_v1.list_namespaced_daemon_set(namespace=ns, **kwargs)
            return [
                {
                    "name": obj.metadata.name,
                    "namespace": obj.metadata.namespace,
                    "desired_number_scheduled": obj.status.desired_number_scheduled if obj.status else None,
                    "number_ready": obj.status.number_ready if obj.status else None,
                }
                for obj in response.items
            ]
        return None


# ------------------------------------------------------------------ #
# Helper functions                                                      #
# ------------------------------------------------------------------ #

def _pod_ready(pod) -> bool:
    """Return True if the pod has at least one ready container."""
    if not pod.status or not pod.status.container_statuses:
        return False
    return any(cs.ready for cs in pod.status.container_statuses)


def _pod_restarts(pod) -> int:
    """Return total restart count across all containers in the pod."""
    if not pod.status or not pod.status.container_statuses:
        return 0
    return sum(cs.restart_count or 0 for cs in pod.status.container_statuses)
