# TASK-3654: ToolInterface: record ToolkitSpec entries + async apply_tooling_specs()

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3645, TASK-3649
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (2) + (3), §3 Module 5. `_initialize_tools` runs synchronously from
`AbstractBot.__init__`, but vault reads and `DatasetManager.add_*` are async. So specs are only
*recorded* here and applied by the new async `apply_tooling_specs()`, which TASK-3655 calls
from `configure()`. Class resolution MUST go through `TOOL_REGISTRY` + `resolve_class`
(`ToolkitRegistry.get` filters on names containing "Toolkit" and misses `dataset_manager`).

---

## Scope

- `_initialize_tools`: a `ToolkitSpec` item is appended to `self._pending_toolkit_specs`
  (create the list lazily with `getattr(self, "_pending_toolkit_specs", None)`), then `continue`.
- `async def apply_tooling_specs(self) -> list[str]`: idempotent (`_tooling_applied`), sets
  `self._tooling_revision = tooling_revision(toolkits, mcp)`; for each toolkit spec: hydrate,
  resolve class, filter params to the ctor signature (unknown → WARNING), special-case
  `dataset_manager`, register; for each `self._pending_mcp_specs` item: `hydrate_mcp` →
  `MCPServerConfig(**kwargs)` → `await self.add_mcp_server(cfg)` when the bot has it.
- Every failure → WARNING (slug + exception type), continue; never raise.
- Tests with a fake bot object built on `ToolInterface` + a real `ToolManager`.

**NOT in scope**: calling it from `configure()` and popping `agent_mcp_servers` (TASK-3655).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | Record specs in _initialize_tools; add apply_tooling_specs() |
| `packages/ai-parrot/tests/interfaces/test_apply_tooling_specs.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.spec import (AgentMCPServerSpec, ToolkitSpec, hydrate_mcp, hydrate_params,
                               tooling_revision)  # created by TASK-3645
from parrot.tools.discovery import discover_from_registry, resolve_class  # verified: tools/discovery.py:31, :139
from parrot.tools.dataset_manager.tool import DatasetManager  # verified: handlers/studio/toolkits.py:28 imports it this way
from parrot.mcp import MCPServerConfig  # verified: registry/registry.py:32 (lazy alias of mcp/client.py:133 MCPClientConfig)
import inspect
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/tools.py
from typing import List, Union, Dict, Any, Callable  # :8
class ToolInterface:  # :15
    def _initialize_tools(self, tools: List[Union[str, AbstractTool, ToolDefinition]]) -> None:  # :27
        # for tool in tools: try: if isinstance(tool, str): ...  ← anchor `                if isinstance(tool, str):` :40
    def _capture_knowledge_toolkit(self, toolkit: Any) -> None:  # :164 ← insert apply_tooling_specs before it
# packages/ai-parrot/src/parrot/tools/manager.py
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type], **kwargs) -> List[AbstractTool]:  # :1104
# packages/ai-parrot/src/parrot/tools/discovery.py
def discover_from_registry(...) -> Dict[str, str]  # :31 — slug -> dotted path (TOOL_REGISTRY)
def resolve_class(dotted_path: str) -> Type  # :139 — raises ImportError/AttributeError
# Studio precedent for case-insensitive slug resolution: handlers/studio/toolkits.py:154-178 (_resolve_toolkit_class)
# packages/ai-parrot/src/parrot/tools/mcp_mixin.py
    async def add_mcp_server(self, config: 'MCPServerConfig', context=None) -> List[str]: ...  # :57
# packages/ai-parrot/src/parrot/bots/data.py — PandasAgent sets self._dataset_manager = DatasetManager() (:477)
```

### Does NOT Exist
- ~~`ToolkitRegistry.get("dataset_manager")`~~ — returns None; use discover_from_registry + resolve_class.
- ~~`ToolInterface.apply_tooling_specs` / `_pending_toolkit_specs` / `_tooling_revision`~~ — this task adds them.
- ~~vault access inside `_initialize_tools`~~ — forbidden (sync context).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/interfaces/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/interfaces/test_apply_tooling_specs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/tools.py#ToolInterface",
    "sym:packages/ai-parrot/src/parrot/interfaces/tools.py#ToolInterface._initialize_tools",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.register_toolkit",
    "sym:packages/ai-parrot/src/parrot/tools/discovery.py#discover_from_registry",
    "sym:packages/ai-parrot/src/parrot/tools/discovery.py#resolve_class"
  ]
}
```

---

## Implementation Notes

- `dataset_manager` special case: `datasources = params.pop("datasources", [])`; if
  `isinstance(getattr(self, "_dataset_manager", None), DatasetManager)` → reuse it (do NOT
  register a second one); else `dm = DatasetManager(**filtered)`, `self.tool_manager.register_toolkit(dm)`,
  `self._dataset_manager = dm`; then `await dm.replay_datasources(datasources)`.
- Param filtering: keep keys present in `inspect.signature(cls.__init__).parameters`; if the ctor
  has `**kwargs`, still drop unknown keys (AbstractToolkit stores kwargs verbatim) and log them.
- After registering, call `self._capture_knowledge_toolkit(instance)` like the existing branches.
- `_tooling_revision` must be set even when there are no specs (revision of two empty lists).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the spec branch at the top of the loop body — *why*: must run before the `str` branch.
2. Add `_resolve_spec_class` + `apply_tooling_specs` before `_capture_knowledge_toolkit` — *why*: keeps tool helpers together.
3. Tests: registration with params, idempotency, missing vault, dataset_manager reuse/new.

### `packages/ai-parrot/src/parrot/interfaces/tools.py` (MODIFY — record specs)
```python
# occurrences: 1 (verified: grep -c '                if isinstance(tool, str):' interfaces/tools.py)
# BEFORE `                if isinstance(tool, str):` (verified: tools.py:40) insert:
                if isinstance(tool, ToolkitSpec):
                    # FEAT-593: configured toolkits need async secret hydration → applied in configure()
                    if getattr(self, "_pending_toolkit_specs", None) is None:
                        self._pending_toolkit_specs = []
                    self._pending_toolkit_specs.append(tool)
                    continue
```
**Why**: the `str` branch below would otherwise log "Unknown tool" for a spec object.
FILL IN: the following `if isinstance(tool, str):` must become `elif`-safe — verify the loop still
reads correctly after the `continue`.

### `packages/ai-parrot/src/parrot/interfaces/tools.py` (MODIFY — apply)
```python
# occurrences: 1 (verified: grep -c '    def _capture_knowledge_toolkit' interfaces/tools.py)
# BEFORE `    def _capture_knowledge_toolkit` (verified: tools.py:164) insert:

    @staticmethod
    def _resolve_spec_class(slug: str) -> type | None:
        """Resolve a toolkit slug via TOOL_REGISTRY (case-insensitive); None when unknown."""
        registry = discover_from_registry()
        dotted = registry.get(slug) or {k.lower(): v for k, v in registry.items()}.get(slug.lower())
        if dotted is None:
            return None
        try:
            return resolve_class(dotted)
        except (ImportError, AttributeError):
            return None

    async def apply_tooling_specs(self) -> list[str]:
        """Hydrate and register pending toolkit / MCP specs once (FEAT-593). Never raises."""
        toolkits: list[ToolkitSpec] = list(getattr(self, "_pending_toolkit_specs", None) or [])
        mcp_specs: list[AgentMCPServerSpec] = list(getattr(self, "_pending_mcp_specs", None) or [])
        self._tooling_revision = tooling_revision(toolkits, mcp_specs)
        if getattr(self, "_tooling_applied", False):
            return []
        self._tooling_applied = True
        registered: list[str] = []
        for spec in toolkits:
            try:
                cls = self._resolve_spec_class(spec.slug)
                if cls is None:
                    self.logger.warning("Toolkit spec '%s': unknown slug, skipped", spec.slug)
                    continue
                params = await hydrate_params(spec)
                # FILL IN: dataset_manager special case (Implementation Notes) else: filter params to
                #   the ctor signature (log dropped keys, names only), instance = cls(**filtered),
                #   tools = self.tool_manager.register_toolkit(instance), self._capture_knowledge_toolkit(instance),
                #   registered += [t.name for t in tools]
            except Exception as exc:  # noqa: BLE001 — a bad spec must never fail the agent boot
                self.logger.warning("Toolkit spec '%s' skipped: %s", spec.slug, type(exc).__name__)
        for mspec in mcp_specs:
            # FILL IN: hydrate_mcp → MCPServerConfig(**kwargs) → await self.add_mcp_server(cfg) when
            #   hasattr(self, "add_mcp_server"); failures → WARNING (server name + exception type)
            pass
        if registered and hasattr(self, "enable_tools"):
            self.enable_tools = True
        return registered
```
**Why**: `_tooling_revision` is computed before the idempotency guard so it is always current;
TASK-3662 compares it against the session marker. Logging exception *types* only keeps secrets
out of logs (AC2).

### FILL IN checklist
- [ ] dataset_manager branch; bounded by spec §2 Overview (3) + AC8
- [ ] ctor-signature filtering + registration; bounded by spec §7 "Constructor signature drift"
- [ ] MCP spec loop; bounded by AC2 (no secret in logs)
- [ ] Add imports (ToolkitSpec etc.) at module top; beware import cycles — import inside the method if needed

---

## Acceptance Criteria

- [ ] A `ToolkitSpec` passed in `tools=` is not registered in `__init__`, and is registered with its params after `await apply_tooling_specs()`.
- [ ] Second call registers nothing and raises no `ToolNameCollisionError`.
- [ ] A missing vault entry → WARNING, other specs still registered, no exception.
- [ ] `dataset_manager` on a bot with an existing `_dataset_manager` replays into it (no second DM tools).
- [ ] `_tooling_revision` is set after the call.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/interfaces/test_apply_tooling_specs.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/test_apply_tooling_specs.py
import logging
from unittest.mock import AsyncMock

import pytest
from parrot.interfaces.tools import ToolInterface
from parrot.tools import spec as spec_module
from parrot.tools.manager import ToolManager
from parrot.tools.spec import ToolkitSpec
from parrot.tools.toolkit import AbstractToolkit


class _EchoKit(AbstractToolkit):
    def __init__(self, prefix: str = "", token: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.prefix, self.token = prefix, token

    async def echo(self, text: str) -> str:
        """Echo."""
        return self.prefix + text


class _Bot(ToolInterface):
    def __init__(self):
        self.logger = logging.getLogger("t")
        self.tool_manager = ToolManager()


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(_Bot, "_resolve_spec_class", staticmethod(lambda slug: _EchoKit if slug == "echo" else None))
    return _Bot()


@pytest.mark.asyncio
async def test_registers_with_hydrated_secret(bot, monkeypatch):
    monkeypatch.setattr(spec_module, "retrieve_vault_credential", AsyncMock(return_value={"token": "s"}))
    # FILL IN: hydrate_params is imported into interfaces.tools — patch it there if needed
    bot._initialize_tools([ToolkitSpec(slug="echo", params={"prefix": ">", "bogus": 1},
                                       secret_refs={"token": "v"}, vault_owner="1")])
    assert bot.tool_manager.tool_count() == 0
    names = await bot.apply_tooling_specs()
    assert names and bot._tooling_revision


@pytest.mark.asyncio
async def test_idempotent(bot):
    bot._initialize_tools([ToolkitSpec(slug="echo")])
    await bot.apply_tooling_specs()
    assert await bot.apply_tooling_specs() == []


@pytest.mark.asyncio
async def test_missing_vault_skips(bot, monkeypatch):
    monkeypatch.setattr(spec_module, "retrieve_vault_credential", AsyncMock(side_effect=KeyError("x")))
    bot._initialize_tools([ToolkitSpec(slug="echo", secret_refs={"token": "v"}, vault_owner="1")])
    assert await bot.apply_tooling_specs() == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `gpt-5.6-terra` (MCP backend `codex`), delivered via `coder_run_chunk` job `job-5fd7ba134efc`, attempt `f8259906f6cd4e1d8fe9963f9da5cf39`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `5f7f3059693db32127b888980fe65a43bfe699ce` (`feat(tool-configuration-agentstudio): TASK-3654 — engine-committed coder deliverable`)
**Lint autofix SHA**: `5ddd27898` (`style(tool-configuration-agentstudio): TASK-3654 — engine lint autofix`)
**Merge commit**: `5ad3dce90`
**Review**: `coder_record_review` recorded — `feedback_id: coder-review:d42d292cf3131c926c43699b`, `fix_commits: []`.

**Notes**: `coder_wait`/`coder_merge` returned `outcome: "merged"`, attempt `terminal: "completed"`, 1 attempt,
0 retries, 0 failures (272s). Diff verified against the task's file table: `parrot/interfaces/tools.py`
(MODIFY, 100 insertions) and `tests/interfaces/test_apply_tooling_specs.py` (CREATE, 138 insertions) — exactly
the 2 declared files, no unlisted files, nothing under `sdd/` touched. Lint autofix committed by the engine
(`5ddd27898`); the merge-time residual report showed 1 `F841` finding, pre-existing/unrelated style debt per
project policy — not fixed here, deferred to `/sdd-done`.

**Deviations from spec**: none.
