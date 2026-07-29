---
type: Wiki Overview
title: 'TASK-1122: Kubernetes config and result models'
id: doc:sdd-tasks-completed-task-1122-k8s-config-result-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: in-cluster flag, and timeout.
relates_to:
- concept: mod:parrot_tools.kubernetes
  rel: mentions
- concept: mod:parrot_tools.kubernetes.config
  rel: mentions
- concept: mod:parrot_tools.pulumi.config
  rel: mentions
---

# TASK-1122: Kubernetes config and result models

**Feature**: FEAT-214 — Kubernetes Toolkit
**Spec**: `sdd/specs/FEAT-214-kubernetes-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 1. Foundation data models for the entire KubernetesToolkit.
> Every other module (executor, toolkit, registration) imports these.

---

## Scope

- Create the `parrot_tools/kubernetes/` package directory with `__init__.py`.
- Implement `KubernetesConfig(BaseModel)` with kubeconfig path, context, namespace,
  in-cluster flag, and timeout.
- Implement `K8sOperationResult(BaseModel)` with success, operation, summary,
  items (bounded list of dicts), and optional error.
- Write unit tests for both models (defaults, validation, serialization).

**NOT in scope**: executor logic, toolkit methods, lazy registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/kubernetes/__init__.py` | CREATE | Package init; export `KubernetesConfig`, `K8sOperationResult` |
| `packages/ai-parrot-tools/src/parrot_tools/kubernetes/config.py` | CREATE | `KubernetesConfig` and `K8sOperationResult` models |
| `packages/ai-parrot-tools/tests/kubernetes/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot-tools/tests/kubernetes/test_config.py` | CREATE | Unit tests for config + result models |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from pydantic import BaseModel, Field                          # standard Pydantic
# Mirror pattern (PulumiConfig inherits BaseExecutorConfig, but KubernetesConfig
# does NOT need it — see "Does NOT Exist" below):
from parrot_tools.pulumi.config import PulumiOperationResult   # verified: pulumi/config.py:224 (mirror pattern)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/pulumi/config.py:224
# MIRROR THIS PATTERN for K8sOperationResult:
class PulumiOperationResult(BaseModel):
    success: bool = Field(...)                 # line 231
    operation: str = Field(...)                # line 235
    resources: list[PulumiResource] = Field(default_factory=list)  # line 239
    outputs: dict[str, Any] = Field(default_factory=dict)          # line 243
    summary: dict[str, int] = Field(default_factory=dict)          # line 247
    duration_seconds: Optional[float] = Field(default=None)        # line 251
    error: Optional[str] = Field(default=None)                     # line 255
    stack_name: Optional[str] = Field(...)                         # line 259

# packages/ai-parrot-tools/src/parrot_tools/security/base_executor.py:25
class BaseExecutorConfig(BaseModel):
    use_docker: bool = Field(default=True)     # Docker/CLI oriented — NOT suitable for k8s
    docker_image: Optional[str]
    cli_path: Optional[str]
    timeout: int = Field(default=300)
```

### Does NOT Exist
- ~~`KubernetesConfig` inheriting `BaseExecutorConfig`~~ — **DO NOT** inherit from
  `BaseExecutorConfig`. It's oriented toward Docker/CLI execution (has `use_docker`,
  `docker_image`, `cli_path`). `KubernetesConfig` is standalone `BaseModel`.
- ~~`parrot_tools.kubernetes`~~ — the entire package does not exist yet. Create it.
- ~~`K8sResource` model~~ — there is no such model. K8sOperationResult uses
  `items: list[dict]` for bounded projections, not a typed resource model.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror PulumiOperationResult (pulumi/config.py:224) but simpler:
class K8sOperationResult(BaseModel):
    success: bool
    operation: str                            # "list_pods", "apply", "scale", etc.
    summary: str                              # human-readable summary
    items: list[dict] = Field(default_factory=list)   # bounded projection
    error: Optional[str] = None
```

### Key Constraints
- Use Pydantic `Field` with descriptions for all fields (descriptions become LLM tool hints).
- `KubernetesConfig.timeout_seconds` must have `gt=0` validator.
- `K8sOperationResult.items` is a list of dicts (bounded projections), not full K8s API objects.
- Keep models standalone — no imports from security/pulumi packages.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/pulumi/config.py` — PulumiConfig + PulumiOperationResult pattern

---

## Acceptance Criteria

- [ ] `KubernetesConfig` has all fields: `kubeconfig_path`, `context`, `namespace`, `in_cluster`, `timeout_seconds`
- [ ] `K8sOperationResult` has: `success`, `operation`, `summary`, `items`, `error`
- [ ] Default `namespace="default"`, `timeout_seconds=60`, `in_cluster=False`
- [ ] `timeout_seconds` rejects values <= 0
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/kubernetes/test_config.py -v`
- [ ] Imports work: `from parrot_tools.kubernetes.config import KubernetesConfig, K8sOperationResult`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/kubernetes/test_config.py
import pytest
from parrot_tools.kubernetes.config import KubernetesConfig, K8sOperationResult


class TestKubernetesConfig:
    def test_defaults(self):
        cfg = KubernetesConfig()
        assert cfg.namespace == "default"
        assert cfg.timeout_seconds == 60
        assert cfg.in_cluster is False
        assert cfg.kubeconfig_path is None
        assert cfg.context is None

    def test_custom_values(self):
        cfg = KubernetesConfig(
            kubeconfig_path="/home/user/.kube/config",
            context="minikube",
            namespace="production",
            in_cluster=False,
            timeout_seconds=120,
        )
        assert cfg.namespace == "production"
        assert cfg.context == "minikube"

    def test_timeout_must_be_positive(self):
        with pytest.raises(Exception):
            KubernetesConfig(timeout_seconds=0)


class TestK8sOperationResult:
    def test_success_result(self):
        result = K8sOperationResult(
            success=True,
            operation="list_pods",
            summary="Found 3 pods",
            items=[{"name": "pod-1"}, {"name": "pod-2"}, {"name": "pod-3"}],
        )
        assert result.success is True
        assert len(result.items) == 3
        assert result.error is None

    def test_error_result(self):
        result = K8sOperationResult(
            success=False,
            operation="scale_deployment",
            summary="Failed to scale",
            error="Deployment not found",
        )
        assert result.success is False
        assert result.error == "Deployment not found"
        assert result.items == []

    def test_serialization(self):
        result = K8sOperationResult(
            success=True, operation="get", summary="OK", items=[{"a": 1}]
        )
        data = result.model_dump()
        assert isinstance(data, dict)
        assert data["success"] is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-214-kubernetes-toolkit.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm PulumiOperationResult still at pulumi/config.py:224
4. **Create the package** — `packages/ai-parrot-tools/src/parrot_tools/kubernetes/`
5. **Implement** config.py with both models
6. **Implement** `__init__.py` with exports
7. **Write and run tests**
8. **Update status** in `sdd/tasks/index/FEAT-214-kubernetes-toolkit.json` → `"in-progress"`
9. **Verify** all acceptance criteria
10. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: Created `parrot_tools/kubernetes/` package with `config.py` (KubernetesConfig + K8sOperationResult),
`__init__.py` (initial exports), and `tests/kubernetes/` with `test_config.py` (14 passing tests).
All acceptance criteria met: defaults verified, timeout gt=0 validated, items as list[dict], serialization working.

**Deviations from spec**: none
