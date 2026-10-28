# TASK-4856: Wire metrics toolkit, mixin and routes; document the registry

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4852, TASK-4853, TASK-4855
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10. Three small edits make the feature reachable:
- `TOOL_REGISTRY["metrics"]` (so `parrot mcp-local metrics` works);
- an eager `MetricRoutingMixin` export from `parrot.bots.mixins`;
- the `/api/v1/metrics` routes in `BotManager`.

This task also adds the operator/author doc page.

---

## Scope

- Add the `"metrics"` entry to `TOOL_REGISTRY`.
- Export `MetricRoutingMixin` from `parrot/bots/mixins/__init__.py` (import + `__all__`).
- Import `MetricDefinitionsHandler` in `manager.py` and register three `add_view` routes, with `/schema` before `/{metric_id}`.
- Write `docs/outputs/metric-registry.md`.
- Add a registry test.

**NOT in scope**: editing `.parrot/mcp-toolkits.yaml` (operator config, documented only) and making any behavioural change to the toolkit, mixin or handler.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | `"metrics"` TOOL_REGISTRY entry |
| `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` | MODIFY | export `MetricRoutingMixin` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | import + 3 routes |
| `docs/outputs/metric-registry.md` | CREATE | user/operator doc |
| `packages/ai-parrot-tools/tests/metrics/test_tool_registry_metrics.py` | CREATE | registry test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools import TOOL_REGISTRY                                   # verified: parrot_tools/__init__.py:13
from parrot_tools.metrics.toolkit import MetricsToolkit                  # created by TASK-4852
from .metric_routing import MetricRoutingMixin                           # created by TASK-4853 (parrot/bots/mixins/metric_routing.py)
from ..handlers.metric_definitions import MetricDefinitionsHandler       # created by TASK-4855
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
TOOL_REGISTRY: dict[str, str] = {...}                                    # L13 — not strictly alphabetical
    "metadata": "parrot_tools.metadata.MetadataTool",                    # L64 — "m" block (L61-64); "metrics" is free (grep -c '"metrics"' = 0)
# packages/ai-parrot/src/parrot/bots/mixins/__init__.py
from .intent_router import IntentRouterMixin                             # L15 (eager block L15-17)
__all__ = [ "IntentRouterMixin", ... ]                                   # L19-26; lazy _LAZY_IMPORTS for the heavy a2ui chain L31
# packages/ai-parrot-server/src/parrot/manager/manager.py
from ..handlers.ui_surfaces import UISurfacesHandler                      # L48
        router.add_view("/api/v1/ui/surfaces/{surface_id}/share/{token}", UISurfacesHandler)   # L2427 (last of the ui_surfaces block L2422-2427)
# parrot/cli/__init__.py:116 "mcp-local" → parrot.mcp.local_cli; .parrot/mcp-toolkits.yaml:123 `querysource:` entry = MCP recipe pattern
```

### Does NOT Exist
- ~~`TOOL_REGISTRY["metrics"]`~~ and ~~`/api/v1/metrics` routes~~ — added here.
- ~~A lazy `_LAZY_IMPORTS` requirement for `MetricRoutingMixin`~~ — it imports only `parrot.metrics` and `registry/routing/route_labels`, which are light, so an eager import is correct. If TASK-4853's module turns out to import the a2ui chain, move the export to `_LAZY_IMPORTS` instead and note it.
- ~~`docs/outputs/metric-registry.md`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/mixins/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "docs/outputs/metric-registry.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/metrics/test_tool_registry_metrics.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/__init__.py#TOOL_REGISTRY"
  ]
}
```

---

## Implementation Notes

- Register aiohttp routes from the most specific first: `/api/v1/metrics/schema` before `/api/v1/metrics/{metric_id}`. Otherwise `schema` resolves as a metric id.
- The doc must cover:
  - the `metrics.yaml` format (spec §7, verbatim example) and its locations (agent dir and `tenants/<t>/`);
  - `import_kpi_table` usage and the Flex mapping;
  - the precedence chain (explicit > phrasing router > metric default shape > agent default) and the MRO `class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent)`;
  - the four tools and the `.parrot/mcp-toolkits.yaml` `metrics:` entry with `parrot mcp-local metrics --config .parrot/mcp-toolkits.yaml`;
  - the REST endpoints;
  - the linked-period limitation (spec §7) and the Q8 threshold note (0.85 default; sweep results recorded here by the M3 implementer).

---

## Implementation Blueprint

### Steps (in order)
1. Edit the registry. *Why*: it makes `parrot mcp-local metrics` resolve (G5).
2. Edit the mixins `__init__`. *Why*: it gives `from parrot.bots.mixins import MetricRoutingMixin` (spec §2 public interfaces).
3. Edit `manager.py`. *Why*: it mounts the M9 handler.
4. Write the doc and the test.

### `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "metadata": "parrot_tools.metadata.MetadataTool",' packages/ai-parrot-tools/src/parrot_tools/__init__.py)
# AFTER — insert below `    "metadata": "parrot_tools.metadata.MetadataTool",` (verified: parrot_tools/__init__.py:64)
    "metrics": "parrot_tools.metrics.toolkit.MetricsToolkit",
```
**Why**: it sits beside its alphabetical neighbour in the `m` block. The spec's querysource anchor (now L97, count 1) also works, but this placement keeps the block ordered.

### `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from .intent_router import IntentRouterMixin$' …/bots/mixins/__init__.py)
# AFTER — insert below `from .intent_router import IntentRouterMixin` (verified: bots/mixins/__init__.py:15)
from .metric_routing import MetricRoutingMixin

# occurrences: 1 (verified: grep -c '    "IntentRouterMixin",' …/bots/mixins/__init__.py)
# AFTER — insert below `    "IntentRouterMixin",` inside __all__ (verified: L20)
    "MetricRoutingMixin",
```
**Why**: this is an eager export. Also add one docstring bullet for `MetricRoutingMixin` in the module docstring.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..handlers.ui_surfaces import UISurfacesHandler' …/manager/manager.py)
# AFTER — insert below `from ..handlers.ui_surfaces import UISurfacesHandler` (verified: manager.py:48)
from ..handlers.metric_definitions import MetricDefinitionsHandler

# occurrences: 1 (verified: grep -c 'router.add_view("/api/v1/ui/surfaces/{surface_id}/share/{token}", UISurfacesHandler)' …/manager/manager.py)
# AFTER — insert below `        router.add_view("/api/v1/ui/surfaces/{surface_id}/share/{token}", UISurfacesHandler)` (verified: manager.py:2427)
        # FEAT-756: metric definition registry REST lane — /schema before /{metric_id}.
        router.add_view("/api/v1/metrics", MetricDefinitionsHandler)
        router.add_view("/api/v1/metrics/schema", MetricDefinitionsHandler)
        router.add_view("/api/v1/metrics/{metric_id}", MetricDefinitionsHandler)
```
**Why**: it reuses the ui_surfaces `add_view` idiom (spec §3 M10).

### `docs/outputs/metric-registry.md` (CREATE)
```markdown
# Metric Definition Registry (FEAT-756)

## What it is
<!-- FILL IN: one paragraph — tenant-scoped metric definitions with a declared default shape. -->
## Defining metrics — `metrics.yaml`
<!-- FILL IN: spec §7 example verbatim; agent vs tenant file locations; forced tenant / global_only / public rules. -->
## Importing the Flex kpi-table
<!-- FILL IN: import_kpi_table(...) call + mapping table (spec §7). -->
## Output-mode precedence
<!-- FILL IN: chain + MRO example + FEAT-755 set_output_shape hint. -->
## Tools and MCP
<!-- FILL IN: four tools; `.parrot/mcp-toolkits.yaml` `metrics:` entry; `parrot mcp-local metrics --config .parrot/mcp-toolkits.yaml`. -->
## REST API
<!-- FILL IN: endpoints + status codes (spec §3 M9). -->
## Limitations
<!-- FILL IN: linked-period limitation (spec §7), semantic_metric reserved (FEAT-704), Q8 threshold note. -->
```

### `packages/ai-parrot-tools/tests/metrics/test_tool_registry_metrics.py` (CREATE)
```python
"""TOOL_REGISTRY["metrics"] resolves to MetricsToolkit (FEAT-756, TASK-4856)."""
import importlib

from parrot_tools import TOOL_REGISTRY


def test_tool_registry_has_metrics() -> None:
    path = TOOL_REGISTRY["metrics"]
    module_name, _, cls_name = path.rpartition(".")
    cls = getattr(importlib.import_module(module_name), cls_name)
    assert cls.__name__ == "MetricsToolkit"


def test_mixin_exported() -> None:
    from parrot.bots.mixins import MetricRoutingMixin

    assert MetricRoutingMixin.__name__ == "MetricRoutingMixin"
```

### FILL IN checklist
- [ ] Doc sections (content bounded by spec §7 and AC-12)

---

## Acceptance Criteria

- [ ] `TOOL_REGISTRY["metrics"]` imports `MetricsToolkit`.
- [ ] `from parrot.bots.mixins import MetricRoutingMixin` works.
- [ ] `manager.py` mounts the three routes, with `/schema` before `/{metric_id}`.
- [ ] `docs/outputs/metric-registry.md` documents the YAML format, the import, the precedence, the MCP recipe and the linked-period limitation.
- [ ] `ruff check` is clean on the modified Python files.

---

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/metrics/test_tool_registry_metrics.py -q`
- `pytest packages/ai-parrot/tests/bots/test_metric_routing_mixin.py -q`

---

## Test Specification

See the blueprint test file.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4852, TASK-4853 and TASK-4855 are `done`.
2. Re-run each `grep -c` above. If a count is not 1, stop and re-anchor.
3. Run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-server/src`.
4. Commit only the listed files, then run `scripts/sdd/close_task.sh TASK-4856 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
