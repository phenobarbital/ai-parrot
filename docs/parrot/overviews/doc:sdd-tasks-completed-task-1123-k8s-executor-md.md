---
type: Wiki Overview
title: 'TASK-1123: KubernetesExecutor — async client wrapper'
id: doc:sdd-tasks-completed-task-1123-k8s-executor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (never dump full API objects).
relates_to:
- concept: mod:parrot_tools.kubernetes.config
  rel: mentions
- concept: mod:parrot_tools.kubernetes.executor
  rel: mentions
---

# TASK-1123: KubernetesExecutor — async client wrapper

**Feature**: FEAT-214 — Kubernetes Toolkit
**Spec**: `sdd/specs/FEAT-214-kubernetes-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1122
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 2. Wraps `kubernetes_asyncio` into a clean async executor
> that returns bounded `K8sOperationResult` projections. The toolkit (TASK-1124)
> delegates all cluster calls to this executor. Mirrors `PulumiExecutor`.

---

## Scope

- Implement `KubernetesExecutor` as a **standalone class** (not inheriting `BaseExecutor`).
- Lazy-import `kubernetes_asyncio` with a clear error message if missing.
- Support kubeconfig file or in-cluster config loading from `KubernetesConfig`.
- Implement **4 read operations**: `list_pods`, `get_logs`, `describe`, `get_resources`.
- Implement **4 mutating operations**: `apply_manifest`, `scale_deployment`,
  `delete_resource`, `rollout_restart`.
- All operations return `K8sOperationResult` with **bounded** item projections
  (never dump full API objects).
- Implement proper client lifecycle (`close()` method).
- Write unit tests with fully mocked `kubernetes_asyncio` — never hit a real cluster.

**NOT in scope**: AbstractToolkit integration, routing_meta, lazy registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/kubernetes/executor.py` | CREATE | `KubernetesExecutor` class |
| `packages/ai-parrot-tools/src/parrot_tools/kubernetes/__init__.py` | MODIFY | Add `KubernetesExecutor` export |
| `packages/ai-parrot-tools/tests/kubernetes/test_executor.py` | CREATE | Unit tests with mocked k8s client |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. DO NOT invent k8s API calls.

### Verified Imports
```python
# From TASK-1122 (this feature):
from parrot_tools.kubernetes.config import KubernetesConfig, K8sOperationResult

# kubernetes_asyncio — LAZY import (verified pattern: tools/executors/k8s.py:81-89)
# Do NOT import at module level. Use the pattern:
try:
    import kubernetes_asyncio
    from kubernetes_asyncio import client as k8s_client
    from kubernetes_asyncio import config as k8s_config
except ImportError as exc:
    raise ImportError(
        "kubernetes_asyncio is required for KubernetesToolkit. "
        "Install with: uv pip install kubernetes_asyncio"
    ) from exc

# Standard library
import logging
import yaml   # for apply_manifest (pyyaml already in deps)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/pulumi/executor.py:22
# MIRROR THIS PATTERN (but standalone, not inheriting BaseExecutor):
class PulumiExecutor(BaseExecutor):             # line 22
    def __init__(self, config: Optional[PulumiConfig] = None):  # line 40
        super().__init__(config or PulumiConfig())

# packages/ai-parrot-tools/src/parrot_tools/kubernetes/config.py (TASK-1122)
class KubernetesConfig(BaseModel):
    kubeconfig_path: Optional[str] = None
    context: Optional[str] = None
    namespace: str = "default"
    in_cluster: bool = False
    timeout_seconds: int = Field(60, gt=0)

class K8sOperationResult(BaseModel):
    success: bool
    operation: str
    summary: str
    items: list[dict] = Field(default_factory=list)
    error: Optional[str] = None

# kubernetes_asyncio API (from official library — verified via k8s.py:84):
# kubernetes_asyncio.config.load_kube_config(config_file=..., context=...)
# kubernetes_asyncio.config.load_incluster_config()
# kubernetes_asyncio.client.CoreV1Api(api_client)
# kubernetes_asyncio.client.AppsV1Api(api_client)
# kubernetes_asyncio.client.ApiClient()
```

### Does NOT Exist
- ~~`KubernetesExecutor` inheriting `BaseExecutor`~~ — **DO NOT** inherit. `BaseExecutor`
  (`security/base_executor.py:92`) is oriented toward Docker/CLI subprocess execution
  (`use_docker`, `_build_cli_args`, `_build_docker_command`). The k8s executor uses
  `kubernetes_asyncio` client API calls, not subprocess commands.
- ~~`parrot_tools.kubernetes.executor`~~ — does not exist yet; create it.
- ~~`kubernetes_asyncio` imported at module top level~~ — NEVER. Lazy-import inside
  methods or `__init__`, same as `K8sToolExecutor` does at `k8s.py:81-84`.
- ~~`K8sToolExecutor` reuse~~ — that's a Job executor for running OTHER tools in k8s.
  Completely different purpose. Do not touch or import it.

---

## Implementation Notes

### Pattern to Follow
```python
class KubernetesExecutor:
    """Async Kubernetes client wrapper. Mirrors PulumiExecutor pattern."""

    def __init__(self, config: KubernetesConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._api_client = None  # lazy init

    async def _ensure_client(self):
        """Lazy-initialize kubernetes_asyncio client."""
        if self._api_client is not None:
            return
        # Lazy import
        try:
            import kubernetes_asyncio
            from kubernetes_asyncio import client as k8s_client, config as k8s_config
        except ImportError as exc:
            raise ImportError(...) from exc

        if self.config.in_cluster:
            k8s_config.load_incluster_config()
        else:
            await k8s_config.load_kube_config(
                config_file=self.config.kubeconfig_path,
                context=self.config.context,
            )
        self._api_client = k8s_client.ApiClient()

    async def close(self):
        """Close the API client to avoid connection leaks."""
        if self._api_client:
            await self._api_client.close()
            self._api_client = None

    async def list_pods(self, namespace=None, label_selector=None) -> K8sOperationResult:
        ...

    async def get_logs(self, pod, namespace=None, container=None, tail_lines=200) -> K8sOperationResult:
        ...
```

### Key Constraints
- **Lazy import** of `kubernetes_asyncio` inside `_ensure_client()`.
- **Bounded projections**: `list_pods` returns `items` with only `name`, `namespace`,
  `status.phase`, `nodeName` — not the full pod spec.
- **`get_logs` truncation**: respect `tail_lines` parameter; also truncate output
  to a max char limit (~50k) to avoid flooding the LLM context.
- **`apply_manifest`**: parse YAML, use dynamic client or typed API to apply.
  Support multi-document YAML.
- **`scale_deployment`**: patch `spec.replicas` via `AppsV1Api`.
- **`delete_resource`**: use dynamic client or typed API by kind.
- **`rollout_restart`**: patch deployment `spec.template.metadata.annotations`
  with a restart timestamp (same as `kubectl rollout restart`).
- **Error handling**: catch `kubernetes_asyncio.client.exceptions.ApiException`,
  return `K8sOperationResult(success=False, error=str(e))`.
- **Client lifecycle**: `close()` must close the `ApiClient`.

### Open Decisions (from spec §8)
- **Standalone vs BaseExecutor**: use standalone (spec preference: "standalone si
  BaseExecutor asume Docker/CLI").
- **`k8s_get`/`k8s_describe` scope**: start with common kinds (Pod, Deployment,
  Service, ConfigMap, Secret, Job, CronJob, Namespace) via typed API. For
  uncommon kinds, use `CustomObjectsApi` if available, otherwise return an error.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/pulumi/executor.py` — PulumiExecutor pattern
- `packages/ai-parrot/src/parrot/tools/executors/k8s.py:81-89` — lazy import pattern

---

## Acceptance Criteria

- [ ] `KubernetesExecutor` initializes from `KubernetesConfig`
- [ ] Lazy-imports `kubernetes_asyncio` (clear error if missing)
- [ ] 4 read ops: `list_pods`, `get_logs`, `describe`, `get_resources`
- [ ] 4 mutating ops: `apply_manifest`, `scale_deployment`, `delete_resource`, `rollout_restart`
- [ ] All operations return `K8sOperationResult`
- [ ] Items in results are bounded projections (not full API objects)
- [ ] `get_logs` respects `tail_lines` and truncates large output
- [ ] `close()` properly cleans up the API client
- [ ] All tests use mocked `kubernetes_asyncio` — no real cluster calls
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/kubernetes/test_executor.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/kubernetes/test_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot_tools.kubernetes.config import KubernetesConfig, K8sOperationResult
from parrot_tools.kubernetes.executor import KubernetesExecutor


@pytest.fixture
def config():
    return KubernetesConfig(namespace="test-ns")


@pytest.fixture
def executor(config):
    return KubernetesExecutor(config)


class TestKubernetesExecutor:
    @pytest.mark.asyncio
    async def test_list_pods_mocked(self, executor):
        """list_pods returns bounded items from mocked CoreV1Api."""
        # Mock kubernetes_asyncio and its CoreV1Api.list_namespaced_pod
        # Verify items contain only projected fields (name, namespace, phase)

    @pytest.mark.asyncio
    async def test_get_logs_mocked(self, executor):
        """get_logs returns truncated log output."""
        # Mock read_namespaced_pod_log, verify tail_lines respected

    @pytest.mark.asyncio
    async def test_describe_mocked(self, executor):
        """describe returns summary for a given kind+name."""

    @pytest.mark.asyncio
    async def test_scale_deployment_mocked(self, executor):
        """scale_deployment patches replicas via AppsV1Api."""
        # Mock patch_namespaced_deployment_scale, verify replicas value

    @pytest.mark.asyncio
    async def test_apply_manifest_mocked(self, executor):
        """apply_manifest parses YAML and creates/patches resources."""

    @pytest.mark.asyncio
    async def test_delete_resource_mocked(self, executor):
        """delete_resource calls the correct delete API."""

    @pytest.mark.asyncio
    async def test_rollout_restart_mocked(self, executor):
        """rollout_restart patches deployment annotation."""

    @pytest.mark.asyncio
    async def test_error_handling(self, executor):
        """ApiException is caught and returned as error result."""

    @pytest.mark.asyncio
    async def test_close_client(self, executor):
        """close() properly disposes the API client."""

    def test_import_error_message(self):
        """Clear error when kubernetes_asyncio not installed."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-214-kubernetes-toolkit.spec.md` for full context
2. **Check dependencies** — TASK-1122 must be completed (config models must exist)
3. **Verify the Codebase Contract** — read `k8s.py:81-89` for lazy import pattern,
   read `pulumi/executor.py` for executor pattern
4. **Implement** `executor.py` with all 8 operations
5. **Update** `__init__.py` to export `KubernetesExecutor`
6. **Write and run tests** with full mocking
7. **Update status** in index → `"in-progress"` / `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: Implemented standalone KubernetesExecutor (not inheriting BaseExecutor) with lazy
kubernetes_asyncio import. All 8 operations implemented: list_pods, get_logs (with truncation),
describe, get_resources, apply_manifest (multi-doc YAML), scale_deployment, delete_resource,
rollout_restart (annotation patch). Bounded projections for all results. 24 unit tests pass
using sys.modules injection to mock kubernetes_asyncio without installing it.

**Deviations from spec**: none
