---
id: F001
slug: toolkit-base-class
query: "AbstractToolkit definition and patterns"
type: read
---

## Finding: AbstractToolkit is the correct base class

**File:** `packages/ai-parrot/src/parrot/tools/toolkit.py` (lines 207-602)

### Key facts:
- `AbstractToolkit(ABC)` is the base for all toolkits
- Auto-discovers public async methods and wraps them as `ToolkitTool` instances
- Supports `tool_prefix` for namespacing (e.g., `"gig"` → `gig_submit_bid`)
- Lifecycle hooks: `_pre_execute()`, `_post_execute()`, `_prepare_kwargs()`
- `confirming_tools: frozenset[str]` for HITL-gated mutations
- `exclude_tools: tuple[str, ...]` to hide internal methods
- Registration via `ToolManager.register_toolkit(toolkit)`

### Correction to SPEC:
- SPEC says inherit from `WorkingMemoryToolkit` — WRONG
- `WorkingMemoryToolkit` is itself a toolkit (for DataFrames), not a base for other toolkits
- GigSmartToolkit should inherit `AbstractToolkit` and optionally compose with WorkingMemory
