"""Tests for K8sToolExecutor with a fully mocked kubernetes_asyncio.

We never reach a real cluster — instead, the kubernetes_asyncio client
classes are patched to return canned pod manifests and the log we
expect the worker process to print between the sentinel markers.

The intent is to lock down the executor's orchestration logic
(Job creation, pod polling, log parsing, cleanup) without requiring a
real K8s environment in CI.
"""
from __future__ import annotations

import json
import sys
import types
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def k8s_mocks(monkeypatch):
    """Inject a fake ``kubernetes_asyncio`` module with the API surface
    used by :class:`K8sToolExecutor`.

    Returns a dict of the mocks the test can assert against.
    """
    fake_module = types.ModuleType("kubernetes_asyncio")
    fake_client = types.ModuleType("kubernetes_asyncio.client")
    fake_config = types.ModuleType("kubernetes_asyncio.config")

    # Shared mock state — all tests in this fixture see the same Job/Pod.
    state: Dict[str, Any] = {
        "created_jobs": [],
        "deleted_jobs": [],
        "pod_logs": "",
        "pod_name": "parrot-pod-abc",
        "pod_phase": "Succeeded",
        "api_close_calls": 0,
    }

    class _ApiClient:
        async def close(self):
            state["api_close_calls"] += 1

    class _BatchV1Api:
        def __init__(self, api): ...

        async def create_namespaced_job(self, namespace, body):
            state["created_jobs"].append({"namespace": namespace, "body": body})
            return MagicMock()

        async def delete_namespaced_job(self, name, namespace, body=None):
            state["deleted_jobs"].append({"name": name, "namespace": namespace})
            return MagicMock()

    class _PodMetadata:
        def __init__(self, name):
            self.name = name

    class _PodStatus:
        def __init__(self, phase):
            self.phase = phase

    class _Pod:
        def __init__(self, name, phase):
            self.metadata = _PodMetadata(name)
            self.status = _PodStatus(phase)

    class _PodList:
        def __init__(self, items):
            self.items = items

    class _CoreV1Api:
        def __init__(self, api): ...

        async def list_namespaced_pod(self, namespace, label_selector=None):
            return _PodList([_Pod(state["pod_name"], state["pod_phase"])])

        async def read_namespaced_pod(self, name, namespace):
            return _Pod(name, state["pod_phase"])

        async def read_namespaced_pod_log(self, name, namespace):
            return state["pod_logs"]

    class _V1DeleteOptions:
        def __init__(self, propagation_policy=None):
            self.propagation_policy = propagation_policy

    fake_client.ApiClient = _ApiClient
    fake_client.BatchV1Api = _BatchV1Api
    fake_client.CoreV1Api = _CoreV1Api
    fake_client.V1DeleteOptions = _V1DeleteOptions

    fake_config.load_incluster_config = MagicMock(
        side_effect=Exception("not in cluster")
    )
    fake_config.load_kube_config = AsyncMock(return_value=None)

    fake_module.client = fake_client
    fake_module.config = fake_config

    monkeypatch.setitem(sys.modules, "kubernetes_asyncio", fake_module)
    monkeypatch.setitem(sys.modules, "kubernetes_asyncio.client", fake_client)
    monkeypatch.setitem(sys.modules, "kubernetes_asyncio.config", fake_config)

    yield state


def _wrap_logs(payload: dict) -> str:
    """Return a string that mimics a pod's stdout — markers + JSON."""
    body = json.dumps(payload)
    return (
        f"info: doing stuff\n"
        f"__PARROT_TOOL_RESULT_BEGIN__\n{body}\n__PARROT_TOOL_RESULT_END__\n"
    )


def _envelope():
    from parrot.tools.executors import ToolExecutionEnvelope

    return ToolExecutionEnvelope(
        tool_import_path="tests.tools.executors._fixtures:EchoTool",
        tool_init_kwargs={},
        arguments={"msg": "ping"},
        timeout_seconds=5,
    )


@pytest.mark.asyncio
async def test_k8s_executor_happy_path(k8s_mocks):
    k8s_mocks["pod_logs"] = _wrap_logs(
        {
            "success": True,
            "status": "success",
            "result": "echo:ping",
            "metadata": {"tool": "echo_tool"},
        }
    )
    from parrot.tools.executors.k8s import K8sToolExecutor

    ex = K8sToolExecutor(
        image="parrot-tools:test",
        namespace="parrot-test",
        kubeconfig_path="/tmp/nonexistent",
        log_poll_interval_seconds=0.0,
    )
    result = await ex.execute(_envelope())

    assert result.status == "success"
    assert result.result == "echo:ping"
    # Stamped with executor metadata.
    assert result.metadata.get("executor") == "k8s"
    assert result.metadata.get("namespace") == "parrot-test"
    assert "job_name" in result.metadata
    # Job was created and then cleaned up.
    assert len(k8s_mocks["created_jobs"]) == 1
    assert len(k8s_mocks["deleted_jobs"]) == 1
    await ex.close()
    assert k8s_mocks["api_close_calls"] >= 1


@pytest.mark.asyncio
async def test_k8s_executor_handles_missing_result_markers(k8s_mocks):
    k8s_mocks["pod_logs"] = "no markers here, just chatter\n"
    from parrot.tools.executors.k8s import K8sToolExecutor

    ex = K8sToolExecutor(log_poll_interval_seconds=0.0)
    result = await ex.execute(_envelope())
    assert result.status == "error"
    assert "result block" in (result.error or "")
    await ex.close()


@pytest.mark.asyncio
async def test_k8s_executor_handles_invalid_json(k8s_mocks):
    k8s_mocks["pod_logs"] = (
        "__PARROT_TOOL_RESULT_BEGIN__\nnot-json\n__PARROT_TOOL_RESULT_END__\n"
    )
    from parrot.tools.executors.k8s import K8sToolExecutor

    ex = K8sToolExecutor(log_poll_interval_seconds=0.0)
    result = await ex.execute(_envelope())
    assert result.status == "error"
    assert "invalid JSON" in (result.error or "")
    await ex.close()


@pytest.mark.asyncio
async def test_k8s_executor_builds_well_formed_job_manifest(k8s_mocks):
    k8s_mocks["pod_logs"] = _wrap_logs(
        {
            "success": True,
            "status": "success",
            "result": "ok",
            "metadata": {},
        }
    )
    from parrot.tools.executors.k8s import K8sToolExecutor

    ex = K8sToolExecutor(
        image="custom:img",
        namespace="ns",
        env={"FOO": "bar"},
        labels={"team": "data"},
        ttl_seconds_after_finished=42,
        log_poll_interval_seconds=0.0,
    )
    await ex.execute(_envelope())

    manifest = k8s_mocks["created_jobs"][0]["body"]
    assert manifest["apiVersion"] == "batch/v1"
    assert manifest["kind"] == "Job"
    spec = manifest["spec"]
    assert spec["backoffLimit"] == 0
    assert spec["ttlSecondsAfterFinished"] == 42
    pod = spec["template"]["spec"]
    container = pod["containers"][0]
    assert container["image"] == "custom:img"
    assert container["command"] == ["python", "-m", "parrot.cli.tool_worker"]
    assert container["args"] == ["--envelope", "-"]
    assert {"name": "FOO", "value": "bar"} in container["env"]
    labels = manifest["metadata"]["labels"]
    assert labels.get("team") == "data"
    assert labels.get("parrot-executor") == "true"
    await ex.close()
