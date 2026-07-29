"""Kubernetes-backed remote tool executor.

Submits the envelope as a single-shot ``batch/v1 Job`` running the
``parrot-tools`` image. The image's entrypoint is
``python -m parrot.cli.tool_worker --envelope -`` which reads the
envelope JSON from stdin and prints the resulting ``ToolResult`` JSON
to stdout. The executor tails the pod's logs to read that result, then
deletes the Job so Kubernetes reclaims the pod.

This module's heavy dependency (``kubernetes_asyncio``) is only
imported when an executor instance is constructed, so projects that
never use the K8s executor are not forced to install the client.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .abstract import AbstractToolExecutor, ToolExecutionEnvelope

if TYPE_CHECKING:
    from ..abstract import ToolResult

logger = logging.getLogger(__name__)

# K8s names: lowercase alphanumeric and '-', start/end alphanumeric.
_NAME_SAFE = re.compile(r"[^a-z0-9-]")


def _sanitize_for_label(value: str, max_len: int = 50) -> str:
    """Turn an arbitrary string into a k8s-name-safe slug."""
    slug = _NAME_SAFE.sub("-", value.lower()).strip("-")
    return slug[:max_len] or "tool"


class K8sToolExecutor(AbstractToolExecutor):
    """Runs the envelope inside an ephemeral Kubernetes Job.

    Args:
        image: Container image that ships ``parrot.cli.tool_worker``.
            Defaults to :data:`parrot.conf.K8S_TOOL_IMAGE`.
        namespace: Kubernetes namespace in which to create the Job.
            Defaults to :data:`parrot.conf.K8S_NAMESPACE`.
        kubeconfig_path: Path to a kubeconfig file. When ``None``, the
            executor first tries in-cluster config (so it works from a
            pod with a ServiceAccount), then falls back to
            ``~/.kube/config``.
        ttl_seconds_after_finished: ``ttlSecondsAfterFinished`` for the
            Job. Defaults to 60s so Kubernetes garbage-collects the pod
            shortly after we read its result.
        resources: Optional ``resources.limits`` / ``requests`` block to
            attach to the pod. Defaults to a small slice
            (``500m`` CPU, ``512Mi`` memory) so unattended tools can't
            balloon the cluster.
        env: Extra environment variables to inject into the pod.
        image_pull_secrets: Names of K8s secrets for private registries.
        service_account: ServiceAccount name the pod runs as.
        labels: Extra labels stamped on the Job/Pod (merged with the
            executor's standard ``parrot-executor=true`` label).
        log_poll_interval_seconds: How often to poll the pod's logs
            while waiting for the worker to finish. Defaults to 1s.
    """

    def __init__(
        self,
        image: Optional[str] = None,
        namespace: Optional[str] = None,
        kubeconfig_path: Optional[str] = None,
        ttl_seconds_after_finished: Optional[int] = None,
        resources: Optional[Dict[str, Dict[str, str]]] = None,
        env: Optional[Dict[str, str]] = None,
        image_pull_secrets: Optional[List[str]] = None,
        service_account: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        log_poll_interval_seconds: float = 1.0,
    ) -> None:
        # Lazy-import the kubernetes client so projects without the
        # ``remote-tools`` extra don't pay an import-time cost.
        try:
            import kubernetes_asyncio  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised by users
            raise ImportError(
                "kubernetes_asyncio is required for K8sToolExecutor. "
                "Install with: uv pip install ai-parrot[remote-tools]"
            ) from exc

        from ...conf import (  # local to avoid heavy import cost
            K8S_KUBECONFIG_PATH,
            K8S_NAMESPACE,
            K8S_JOB_TTL_SECONDS,
            K8S_TOOL_IMAGE,
        )

        self.image = image or K8S_TOOL_IMAGE
        self.namespace = namespace or K8S_NAMESPACE
        self.kubeconfig_path = kubeconfig_path or K8S_KUBECONFIG_PATH
        self.ttl_seconds_after_finished = (
            ttl_seconds_after_finished
            if ttl_seconds_after_finished is not None
            else K8S_JOB_TTL_SECONDS
        )
        self.resources = resources or {
            "limits": {"cpu": "500m", "memory": "512Mi"},
            "requests": {"cpu": "100m", "memory": "128Mi"},
        }
        self.env = env or {}
        self.image_pull_secrets = list(image_pull_secrets or [])
        self.service_account = service_account
        self.labels = {"parrot-executor": "true", **(labels or {})}
        self.log_poll_interval_seconds = float(log_poll_interval_seconds)
        self._api_client: Any = None  # kubernetes_asyncio.client.ApiClient
        self.logger = logger.getChild(self.__class__.__name__)

    async def _ensure_client(self):
        if self._api_client is not None:
            return self._api_client

        from kubernetes_asyncio import client, config

        # Try in-cluster first (cheap), fall back to kubeconfig.
        try:
            config.load_incluster_config()
        except Exception:
            await config.load_kube_config(config_file=self.kubeconfig_path)

        self._api_client = client.ApiClient()
        return self._api_client

    def _build_job_manifest(
        self, envelope: ToolExecutionEnvelope, job_name: str
    ) -> Dict[str, Any]:
        """Build a ``batch/v1 Job`` manifest that runs the envelope.

        The envelope is passed via a single ``--envelope`` flag with
        JSON on stdin (so we don't need a ConfigMap or a Secret for
        the payload, and the Job is self-contained).
        """
        envelope_json = envelope.model_dump_json()
        container_env = [
            {"name": k, "value": str(v)} for k, v in self.env.items()
        ]
        labels = {
            **self.labels,
            "parrot-tool": _sanitize_for_label(
                envelope.tool_import_path.split(":")[-1]
            ),
        }

        pod_spec: Dict[str, Any] = {
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "tool-worker",
                    "image": self.image,
                    "imagePullPolicy": "IfNotPresent",
                    # The worker reads the envelope from stdin so the
                    # full payload never appears in `ps`.
                    "command": ["python", "-m", "parrot.cli.tool_worker"],
                    "args": ["--envelope", "-"],
                    "stdin": True,
                    "stdinOnce": True,
                    "tty": False,
                    "env": container_env,
                    "resources": self.resources,
                }
            ],
        }
        if self.service_account:
            pod_spec["serviceAccountName"] = self.service_account
        if self.image_pull_secrets:
            pod_spec["imagePullSecrets"] = [
                {"name": n} for n in self.image_pull_secrets
            ]

        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": self.namespace,
                "labels": labels,
                "annotations": {
                    # Stash the envelope JSON on the Job so the worker
                    # can fetch it via the downward API without a
                    # network round-trip back to the caller.
                    "parrot.ai/envelope": envelope_json,
                },
            },
            "spec": {
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": self.ttl_seconds_after_finished,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": pod_spec,
                },
            },
        }

    async def execute(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        # Local import keeps the heavy SDK out of cold-import paths.
        from kubernetes_asyncio import client
        from kubernetes_asyncio.client import (
            BatchV1Api,
            CoreV1Api,
        )

        from ..abstract import ToolResult

        api = await self._ensure_client()
        batch = BatchV1Api(api)
        core = CoreV1Api(api)

        job_name = f"parrot-tool-{uuid.uuid4().hex[:12]}"
        manifest = self._build_job_manifest(envelope, job_name)

        self.logger.info(
            "Creating K8s Job %s in ns=%s image=%s tool=%s",
            job_name,
            self.namespace,
            self.image,
            envelope.tool_import_path,
        )
        try:
            await batch.create_namespaced_job(self.namespace, manifest)
        except Exception as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Failed to submit K8s Job: {exc}",
                metadata={
                    "executor": "k8s",
                    "namespace": self.namespace,
                    "job_name": job_name,
                },
            )

        try:
            pod_name = await self._wait_for_pod(core, job_name, envelope.timeout_seconds)
            await self._wait_for_pod_terminal(core, pod_name, envelope.timeout_seconds)
            logs = await core.read_namespaced_pod_log(
                name=pod_name, namespace=self.namespace
            )
            return self._parse_logs(logs, envelope, job_name, pod_name)
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=(
                    f"K8s Job {job_name} did not finish within "
                    f"{envelope.timeout_seconds}s"
                ),
                metadata={
                    "executor": "k8s",
                    "namespace": self.namespace,
                    "job_name": job_name,
                },
            )
        finally:
            # Best-effort cleanup. We rely on ttlSecondsAfterFinished
            # for the happy path; this catches stuck Jobs we
            # interrupted ourselves.
            try:
                await batch.delete_namespaced_job(
                    name=job_name,
                    namespace=self.namespace,
                    body=client.V1DeleteOptions(
                        propagation_policy="Background"
                    ),
                )
            except Exception as cleanup_exc:
                self.logger.warning(
                    "Failed to delete K8s Job %s: %s", job_name, cleanup_exc
                )

    async def _wait_for_pod(
        self, core: Any, job_name: str, timeout_seconds: int
    ) -> str:
        """Poll until a pod owned by *job_name* exists; return its name."""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while True:
            pods = await core.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"job-name={job_name}",
            )
            if pods.items:
                return pods.items[0].metadata.name
            if asyncio.get_event_loop().time() > deadline:
                raise asyncio.TimeoutError(
                    f"No pod for Job {job_name} appeared in time."
                )
            await asyncio.sleep(self.log_poll_interval_seconds)

    async def _wait_for_pod_terminal(
        self, core: Any, pod_name: str, timeout_seconds: int
    ) -> None:
        """Block until the pod is Succeeded or Failed."""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while True:
            pod = await core.read_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )
            phase = pod.status.phase if pod.status else None
            if phase in ("Succeeded", "Failed"):
                return
            if asyncio.get_event_loop().time() > deadline:
                raise asyncio.TimeoutError(
                    f"Pod {pod_name} did not reach a terminal phase."
                )
            await asyncio.sleep(self.log_poll_interval_seconds)

    def _parse_logs(
        self,
        logs: str,
        envelope: ToolExecutionEnvelope,
        job_name: str,
        pod_name: str,
    ) -> "ToolResult":
        """Find the worker's marker-delimited result block in pod logs.

        The worker writes the JSON result between
        ``__PARROT_TOOL_RESULT_BEGIN__`` and
        ``__PARROT_TOOL_RESULT_END__`` so unrelated stdout/stderr
        chatter is ignored.
        """
        from .runner import parse_sentinel_output

        return parse_sentinel_output(
            logs,
            metadata={
                "executor": "k8s",
                "namespace": self.namespace,
                "job_name": job_name,
                "pod_name": pod_name,
            },
        )

    async def close(self) -> None:
        if self._api_client is not None:
            try:
                await self._api_client.close()
            except Exception:
                pass
            self._api_client = None
