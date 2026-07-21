---
type: Wiki Overview
title: 'TASK-1125: Lazy registration + exports + integration tests'
id: doc:sdd-tasks-completed-task-1125-k8s-lazy-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (all covered by TASK-1122–1124).
relates_to:
- concept: mod:parrot_tools.docker.toolkit
  rel: mentions
- concept: mod:parrot_tools.kubernetes
  rel: mentions
- concept: mod:parrot_tools.kubernetes.toolkit
  rel: mentions
- concept: mod:parrot_tools.pulumi.toolkit
  rel: mentions
---

# TASK-1125: Lazy registration + exports + integration tests

**Feature**: FEAT-214 — Kubernetes Toolkit
**Spec**: `sdd/specs/FEAT-214-kubernetes-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1124
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 4. Register `KubernetesToolkit` in the `parrot_tools` lazy
> registry and finalize `__init__.py` exports. Write integration tests to
> verify end-to-end lazy loading and tool exposure.

---

## Scope

- Add `"kubernetes": "parrot_tools.kubernetes.toolkit.KubernetesToolkit"` to
  `TOOL_REGISTRY` in `parrot_tools/__init__.py`.
- Finalize `parrot_tools/kubernetes/__init__.py` with all public exports.
- Write integration tests verifying lazy registry resolution and tool count.

**NOT in scope**: executor internals, toolkit method logic, routing_meta logic
(all covered by TASK-1122–1124).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Add `"kubernetes"` to `TOOL_REGISTRY` |
| `packages/ai-parrot-tools/src/parrot_tools/kubernetes/__init__.py` | MODIFY | Finalize exports |
| `packages/ai-parrot-tools/tests/kubernetes/test_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:12
TOOL_REGISTRY: dict[str, str] = {
    # ...
    "pulumi": "parrot_tools.pulumi.toolkit.PulumiToolkit",   # line 61 — MIRROR THIS
    # ...
}
```

### Existing Signatures to Use
```python
# Lazy registry pattern (parrot_tools/__init__.py):
# Each entry maps a short name to a dotted import path.
# The ToolManager resolves these lazily at runtime via importlib.
# Add alongside line 61 (near "pulumi"):
"kubernetes": "parrot_tools.kubernetes.toolkit.KubernetesToolkit"
```

### Does NOT Exist
- ~~`TOOL_REGISTRY` auto-registration~~ — entries are manually added to the dict.
  The script `scripts/generate_tool_registry.py` can regenerate, but manual
  additions are preserved (per docstring at line 8).
- ~~runtime import of kubernetes in `__init__.py`~~ — the registry is strings only;
  no actual import happens at package load time.

---

## Implementation Notes

### Registry Entry Placement

Add the entry in the "Toolkits (Batch 2)" section alongside `pulumi` and `docker`:

```python
    "docker": "parrot_tools.docker.toolkit.DockerToolkit",
    "pulumi": "parrot_tools.pulumi.toolkit.PulumiToolkit",
    "kubernetes": "parrot_tools.kubernetes.toolkit.KubernetesToolkit",  # FEAT-214
```

### Package `__init__.py` Exports

```python
# packages/ai-parrot-tools/src/parrot_tools/kubernetes/__init__.py
from .config import KubernetesConfig, K8sOperationResult
from .executor import KubernetesExecutor
from .toolkit import KubernetesToolkit

__all__ = [
    "KubernetesConfig",
    "K8sOperationResult",
    "KubernetesExecutor",
    "KubernetesToolkit",
]
```

### Key Constraints
- The registry entry MUST be a string — no actual import at load time.
- Placement: in the "Batch 2 — toolkit-based tools" section, near pulumi.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py:61` — pulumi registry entry

---

## Acceptance Criteria

- [ ] `TOOL_REGISTRY["kubernetes"]` resolves to `"parrot_tools.kubernetes.toolkit.KubernetesToolkit"`
- [ ] `from parrot_tools.kubernetes import KubernetesToolkit, KubernetesConfig, K8sOperationResult, KubernetesExecutor` works
- [ ] Lazy import: `import parrot_tools` does NOT import `kubernetes_asyncio`
- [ ] Integration test: resolve registry entry → instantiate toolkit → get 8 tools
- [ ] No modifications to existing tools or toolkits
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/kubernetes/ -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/kubernetes/test_integration.py
import pytest
import importlib


class TestLazyRegistration:
    def test_registry_has_kubernetes(self):
        """TOOL_REGISTRY contains the kubernetes entry."""
        from parrot_tools import TOOL_REGISTRY
        assert "kubernetes" in TOOL_REGISTRY
        assert TOOL_REGISTRY["kubernetes"] == "parrot_tools.kubernetes.toolkit.KubernetesToolkit"

    def test_lazy_resolve(self):
        """Registry entry resolves to KubernetesToolkit class."""
        from parrot_tools import TOOL_REGISTRY
        module_path, class_name = TOOL_REGISTRY["kubernetes"].rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        assert cls.__name__ == "KubernetesToolkit"

    def test_toolkit_instantiates(self):
        """KubernetesToolkit can be instantiated from lazy import."""
        from parrot_tools.kubernetes import KubernetesToolkit, KubernetesConfig
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        assert toolkit is not None

    def test_toolkit_exposes_eight_tools(self):
        """Full integration: instantiate → get_tools() → 8 tools."""
        from parrot_tools.kubernetes import KubernetesToolkit, KubernetesConfig
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        tools = toolkit.get_tools()
        assert len(tools) == 8

    def test_read_tools_no_grant_meta(self):
        """Read tools do not carry requires_grant."""
        from parrot_tools.kubernetes import KubernetesToolkit, KubernetesConfig
        toolkit = KubernetesToolkit(config=KubernetesConfig())
        tools = toolkit.get_tools()
        read_names = {"k8s_list_pods", "k8s_get_logs", "k8s_describe", "k8s_get"}
        for tool in tools:
            if tool.name in read_names:
                assert not tool.routing_meta.get("requires_grant")

    def test_import_does_not_load_kubernetes_asyncio(self):
        """Importing parrot_tools should NOT trigger kubernetes_asyncio import."""
        import sys
        # Fresh import check — kubernetes_asyncio should not be in sys.modules
        # just from importing the registry
        modules_before = set(sys.modules.keys())
        importlib.reload(importlib.import_module("parrot_tools"))
        new_modules = set(sys.modules.keys()) - modules_before
        assert "kubernetes_asyncio" not in new_modules
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-1124 must be completed (toolkit must exist)
2. **Verify** `parrot_tools/__init__.py` still has `TOOL_REGISTRY` at line 12 and
   `"pulumi"` at line 61
3. **Add** the `"kubernetes"` entry to the registry
4. **Finalize** `kubernetes/__init__.py` with all exports
5. **Write and run** integration tests
6. **Run full test suite**: `pytest packages/ai-parrot-tools/tests/kubernetes/ -v`
7. **Update index** status

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: Added "kubernetes" entry to TOOL_REGISTRY in parrot_tools/__init__.py (alongside pulumi/docker).
Finalized kubernetes/__init__.py with all 4 exports. 16 integration tests verify lazy registry
resolution, package imports, lazy loading (no kubernetes_asyncio import at load time), and
full end-to-end tool exposure. 80 total tests pass across all kubernetes test files.

**Deviations from spec**: none

**Deviations from spec**: none | describe if any
