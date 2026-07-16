---
type: Wiki Overview
title: 'TASK-1124: KubernetesToolkit — AbstractToolkit with routing_meta'
id: doc:sdd-tasks-completed-task-1124-k8s-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: prefixed `k8s_` (4 read + 4 mutating).
relates_to:
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.kubernetes.config
  rel: mentions
- concept: mod:parrot_tools.kubernetes.executor
  rel: mentions
- concept: mod:parrot_tools.kubernetes.toolkit
  rel: mentions
---

# TASK-1124: KubernetesToolkit — AbstractToolkit with routing_meta

**Feature**: FEAT-214 — Kubernetes Toolkit
**Spec**: `sdd/specs/FEAT-214-kubernetes-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1122, TASK-1123
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 3. The `KubernetesToolkit(AbstractToolkit)` exposes 8 async
> methods as agent tools via `get_tools()`. Read operations have no grant
> requirement; mutating operations carry `routing_meta={"requires_grant": True,
> "grant_scope": "k8s:write"}` for FEAT-211 governance integration.

---

## Scope

- Implement `KubernetesToolkit(AbstractToolkit)` with 8 public async methods
  prefixed `k8s_` (4 read + 4 mutating).
- Each method delegates to `KubernetesExecutor` and returns `K8sOperationResult`.
- **Critical**: override `_generate_tools()` to set `routing_meta` on the 4
  mutating tools after generation (since `_create_tool_from_method` does not
  pass `routing_meta` through).
- Implement `close()` / async context manager for executor cleanup.
- Write tests verifying all 8 tools are exposed and mutating tools have correct
  `routing_meta`.

**NOT in scope**: executor internals (TASK-1123), lazy registration (TASK-1125).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/kubernetes/toolkit.py` | CREATE | `KubernetesToolkit(AbstractToolkit)` |
| `packages/ai-parrot-tools/src/parrot_tools/kubernetes/__init__.py` | MODIFY | Add `KubernetesToolkit` export |
| `packages/ai-parrot-tools/tests/kubernetes/test_toolkit.py` | CREATE | Tests for tool exposure + routing_meta |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # verified: tools/toolkit.py:191
from parrot_tools.kubernetes.config import KubernetesConfig, K8sOperationResult  # TASK-1122
from parrot_tools.kubernetes.executor import KubernetesExecutor                  # TASK-1123
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:191
class AbstractToolkit(ABC):
    def __init__(self, **kwargs):            # accepts tool_prefix, return_direct, executor, etc.
    def get_tools(self, ...) -> list:        # line 337 — generates + returns tool list
    def _generate_tools(self) -> None:       # line 390 — generates tools from public async methods
    def _create_tool_from_method(self, name, bound_method) -> ToolkitTool:  # line 482

# ToolkitTool (tools/toolkit.py:32) inherits AbstractTool
# AbstractTool.__init__ (tools/abstract.py:109) accepts routing_meta: Optional[Dict] = None
# So: tool.routing_meta = {...} is writable after creation (it's a plain instance attr set at line 139-140)

# PulumiToolkit mirror pattern (parrot_tools/pulumi/toolkit.py:23):
class PulumiToolkit(AbstractToolkit):
    def __init__(self, config=None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or PulumiConfig()
        self.executor = PulumiExecutor(self.config)
    # Each public async method becomes a tool with pulumi_ prefix
```

### Key Technical Detail — Setting routing_meta on Generated Tools

`_create_tool_from_method()` (line 482-523) does NOT pass `routing_meta` to
`ToolkitTool`. But `tool.routing_meta` is a plain dict set in `AbstractTool.__init__`
(line 139-140). **Override `_generate_tools()`** to call `super()._generate_tools()`
then iterate `self._tool_cache` and set `routing_meta` on mutating tools:

```python
_MUTATING_METHODS = frozenset({
    "k8s_apply_manifest", "k8s_scale_deployment",
    "k8s_delete_resource", "k8s_rollout_restart",
})

def _generate_tools(self) -> None:
    super()._generate_tools()
    for name, tool in self._tool_cache.items():
        if name in self._MUTATING_METHODS:
            tool.routing_meta = {"requires_grant": True, "grant_scope": "k8s:write"}
```

### Does NOT Exist
- ~~`routing_meta` parameter in `_create_tool_from_method`~~ — it does NOT accept
  routing_meta. Set it after tool generation via `_generate_tools()` override.
- ~~grant enforcement in toolkit~~ — FEAT-211 handles gating in `ToolManager`.
  This toolkit only **marks** mutating tools.
- ~~`AbstractToolkit.close()`~~ — no built-in lifecycle method. Add `close()` and
  optionally `__aenter__`/`__aexit__` to the toolkit itself.

---

## Implementation Notes

### Pattern to Follow
```python
class KubernetesToolkit(AbstractToolkit):
    """Kubernetes cluster management toolkit.

    Exposes kubectl-like operations as agent tools. Read operations
    (list_pods, get_logs, describe, get) require no grant. Mutating
    operations (apply_manifest, scale_deployment, delete_resource,
    rollout_restart) carry routing_meta["requires_grant"] = True
    for FEAT-211 governance.
    """

    _MUTATING_METHODS = frozenset({...})

    def __init__(self, config: Optional[KubernetesConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or KubernetesConfig()
        self.executor = KubernetesExecutor(self.config)

    def _generate_tools(self) -> None:
        super()._generate_tools()
        for name, tool in self._tool_cache.items():
            if name in self._MUTATING_METHODS:
                tool.routing_meta = {"requires_grant": True, "grant_scope": "k8s:write"}

    async def close(self):
        await self.executor.close()

    # --- READ operations (no grant) ---
    async def k8s_list_pods(self, namespace=None, label_selector=None) -> K8sOperationResult:
        """List pods in a namespace with optional label filtering."""
        ...

    async def k8s_get_logs(self, pod, namespace=None, container=None, tail_lines=200) -> K8sOperationResult:
        """Get logs from a pod, optionally from a specific container."""
        ...

    # ... etc
```

### Key Constraints
- Method names MUST start with `k8s_` — `AbstractToolkit._generate_tools()` picks up
  all public async methods as tools, and the `k8s_` prefix ensures no collision.
- Docstrings are critical — they become the tool description shown to the LLM.
  Keep them clear and concise (one sentence explaining what the tool does).
- Each method validates inputs before delegating to the executor.
- Default namespace falls back to `self.config.namespace`.
- `self.logger` for all operations.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/pulumi/toolkit.py` — PulumiToolkit (mirror)
- `packages/ai-parrot/src/parrot/tools/toolkit.py:390` — `_generate_tools()`
- `packages/ai-parrot/src/parrot/tools/toolkit.py:482` — `_create_tool_from_method()`
- `packages/ai-parrot/src/parrot/tools/abstract.py:139` — `self.routing_meta` assignment

---

## Acceptance Criteria

- [ ] `KubernetesToolkit(AbstractToolkit)` with 8 public async `k8s_*` methods
- [ ] `get_tools()` returns exactly 8 tools with `k8s_` prefix
- [ ] 4 mutating tools have `routing_meta == {"requires_grant": True, "grant_scope": "k8s:write"}`
- [ ] 4 read tools have `routing_meta == {}` (empty, no grant)
- [ ] All methods delegate to `KubernetesExecutor` and return `K8sOperationResult`
- [ ] `close()` cleans up the executor
- [ ] Clear docstrings on every method (they become LLM tool descriptions)
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/kubernetes/test_toolkit.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/kubernetes/test_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch

from parrot_tools.kubernetes.config import KubernetesConfig
from parrot_tools.kubernetes.toolkit import KubernetesToolkit


@pytest.fixture
def toolkit():
    return KubernetesToolkit(config=KubernetesConfig())


class TestKubernetesToolkit:
    def test_get_tools_count(self, toolkit):
        """get_tools() exposes exactly 8 tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 8

    def test_tool_names(self, toolkit):
        """All tools have k8s_ prefix."""
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        expected = {
            "k8s_list_pods", "k8s_get_logs", "k8s_describe", "k8s_get",
            "k8s_apply_manifest", "k8s_scale_deployment",
            "k8s_delete_resource", "k8s_rollout_restart",
        }
        assert names == expected

    def test_mutating_tools_require_grant(self, toolkit):
        """Mutating tools have routing_meta['requires_grant'] == True."""
        tools = toolkit.get_tools()
        mutating = {"k8s_apply_manifest", "k8s_scale_deployment",
                     "k8s_delete_resource", "k8s_rollout_restart"}
        for tool in tools:
            if tool.name in mutating:
                assert tool.routing_meta.get("requires_grant") is True
                assert tool.routing_meta.get("grant_scope") == "k8s:write"

    def test_read_tools_no_grant(self, toolkit):
        """Read tools do NOT have requires_grant."""
        tools = toolkit.get_tools()
        read_tools = {"k8s_list_pods", "k8s_get_logs", "k8s_describe", "k8s_get"}
        for tool in tools:
            if tool.name in read_tools:
                assert not tool.routing_meta.get("requires_grant")

    @pytest.mark.asyncio
    async def test_close(self, toolkit):
        """close() delegates to executor."""
        toolkit.executor.close = AsyncMock()
        await toolkit.close()
        toolkit.executor.close.assert_awaited_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-214-kubernetes-toolkit.spec.md`
2. **Check dependencies** — TASK-1122 and TASK-1123 must be completed
3. **Verify the Codebase Contract** — especially `_generate_tools()` at toolkit.py:390
   and `routing_meta` at abstract.py:139
4. **Implement** `toolkit.py` with all 8 methods + `_generate_tools()` override
5. **Update** `__init__.py` exports
6. **Write and run tests**
7. **Update index** status

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: Implemented KubernetesToolkit(AbstractToolkit) with 8 public async k8s_* methods.
Overrode _generate_tools() to set routing_meta on 4 mutating tools. Added 'close' to
exclude_tools so it's not exposed as an agent tool. Added input validation (empty strings).
Async context manager (__aenter__/__aexit__) added. 26 tests all pass.

**Deviations from spec**: none
