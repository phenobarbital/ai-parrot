# TASK-5082: Escape render_knowledge attributes, post-configure spawn guard, visible tenant on ExpertRegistry.get

**Feature**: FEAT-785 — Experts agent tech debt
**Spec**: `sdd/specs/experts-agent-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:230ac877bdf5`

---

## Context

Three minor findings from the FEAT-778 (domain experts) code review, filed as
ledger `issue:230ac877bdf5` and promoted here by `/sdd-fix`. Implements spec
modules M1, M2 and M3 (§2):

1. `render_knowledge()` writes `layer`, `source` and `revision` into XML
   attributes unescaped; ADR/workspace sources can carry arbitrary names.
2. Nothing guards or tests the tool list of a **configured** `ExpertAgent`.
   `Agent.configure()` adds tools after construction (probe 2026-11-01:
   before configure `['lookup_fact', 'to_json']`, after
   `['lookup_fact', 'read_omitted_content', 'to_json']`), so a base-Agent
   injection of `spawn_sub_agent` would go unnoticed.
3. `ExpertRegistry.get(name, tenant=...)` ignores `tenant` silently.

---

## Scope

- Escape `layer`, `source` and `revision` in `render_knowledge` with `html.escape(str(v), quote=True)`.
- At the end of `ExpertAgent.configure()`, unregister `SPAWN_TOOL_NAME` from `self.tool_manager` when present, with a warning log.
- In `ExpertRegistry.get`, log a warning when `tenant is not None`; return value and `KeyError` behaviour unchanged; update the docstring.
- Add the four tests from spec §4.

**NOT in scope**: tenant-specific expert views; re-applying the full allowlist
after configure (framework tools `to_json`/`read_omitted_content` must
survive); escaping section content; any change to `parrot/tools/manager.py`
or the base `Agent`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/knowledge/render.py` | MODIFY | Escape section attributes (M1) |
| `packages/ai-parrot/src/parrot/experts/agent.py` | MODIFY | Post-configure spawn guard (M2) |
| `packages/ai-parrot/src/parrot/experts/registry.py` | MODIFY | Warn on ignored tenant (M3) |
| `packages/ai-parrot/tests/experts/test_render.py` | MODIFY | Escape test |
| `packages/ai-parrot/tests/experts/test_agent_activation.py` | MODIFY | Final tool list tests |
| `packages/ai-parrot/tests/experts/test_registry.py` | MODIFY | Tenant warning test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import html  # stdlib
from parrot.experts.models import SPAWN_TOOL_NAME  # verified: experts/models.py:12 == "spawn_sub_agent"
from parrot.experts.models import ExpertBundle, KnowledgeContext  # existing import, experts/agent.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/experts/knowledge/render.py:25
def render_knowledge(ctx: KnowledgeContext) -> str: ...
#   line 42: f'<section layer="{item.layer}" source="{item.source}" revision="{item.revision}">\n'

# packages/ai-parrot/src/parrot/experts/agent.py:17
class ExpertAgent(IdentityMixin, Agent):
    async def configure(self, app: Any = None) -> None:  # line 62
    #   line 70 (inside `if self._prompt_builder is not None:`):
    #   self._prompt_builder = install_layers(self._prompt_builder, self.knowledge_context)
    #   self.logger / self.tool_manager are provided by the base Agent
    #   (tests already call agent.tool_manager.list_tools())

# packages/ai-parrot/src/parrot/experts/registry.py
class ExpertRegistry:
    self.logger = logging.getLogger(__name__)  # __init__, line 51
    def get(self, name: str, *, tenant: str | None = None) -> ExpertAgent:  # line 61, body `return self._experts[name]` line 66

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def add_tool(self, tool, name: Optional[str] = None) -> None:  # line 828
    def get_tool(self, tool_name: str) -> Optional[Any]:  # line 1393
    def list_tools(self) -> List[str]:  # line 1413
    def unregister_tool(self, tool_name: str) -> bool:  # line 1435

# packages/ai-parrot/src/parrot/experts/models.py:137
class KnowledgeLayer(BaseModel):
    layer: LayerName; source: str; mode: KnowledgeMode; revision: str; content: str | None = None
```

Test helpers already present:
- `tests/experts/test_agent_activation.py`: `_Toolkit` (tools `lookup_fact`, `spawn_sub_agent`), `_FakeResolver`, `_make(expert_bundle, allowed=None)`; fixture `expert_bundle` from `tests/experts/conftest.py`.
- `tests/experts/test_registry.py`: autouse `stub_llm`, `_registry(root, store, **kwargs)`, `InMemoryWikiStore`; `test_registry_registers_tagged_instance` (line 89) shows the load pattern (`await registry.load() == 1`, expert name `"sample-expert"`).
- `tests/experts/test_render.py`: `_ctx(...)` builds a `KnowledgeContext` with `KnowledgeLayer`s.

### Does NOT Exist
- ~~`ExpertRegistry.get_for_tenant` / any tenant-view builder~~ — not implemented (phase one).
- ~~`parrot.experts.utils.escape_attr`~~ or any escaping helper in `parrot.experts` — use stdlib `html.escape`.
- ~~`ToolManager.has_tool`~~ — use `get_tool(name) is not None`.
- ~~`ExpertAgent.allowed_tools` attribute~~ — the allowlist is a local in `__init__`, not stored.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/render.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/experts/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/experts/registry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/experts/test_render.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/experts/test_agent_activation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/experts/test_registry.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/experts/knowledge/render.py#render_knowledge",
    "sym:packages/ai-parrot/src/parrot/experts/agent.py#ExpertAgent",
    "sym:packages/ai-parrot/src/parrot/experts/agent.py#ExpertAgent.configure",
    "sym:packages/ai-parrot/src/parrot/experts/registry.py#ExpertRegistry.get",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.unregister_tool",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.get_tool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Output of `render_knowledge` for plain values must stay byte-identical (existing determinism tests).
- Spawn removal is unconditional: `ExpertManifest` rejects `spawn_sub_agent` in `toolkits`/`tools_allow` (models.py:122) and `effective_allowlist` strips it (policy.py:32).
- `tenant` stays a warning, never an exception — existing callers must keep working.
- Logging via `self.logger`, lazy `%s` formatting.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `render.py` — *why*: escaping must happen where the attribute string is built.
2. Edit `agent.py` — *why*: the guard must run after every base-Agent tool registration, i.e. last in `configure()`.
3. Edit `registry.py` — *why*: makes the phase-one limitation visible at the call site.
4. Add the tests, run Validation Commands, `ruff check` the six files.

### `packages/ai-parrot/src/parrot/experts/knowledge/render.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'import dataclasses' render.py)
# BEFORE `import dataclasses` (line 5) add:
import html

# occurrences: 1 (verified: grep -c 'section layer=' render.py) — line 42
# REPLACE the two-line f-string inside sections.append(...) with:
        layer = html.escape(str(item.layer), quote=True)
        source = html.escape(item.source, quote=True)
        revision = html.escape(item.revision, quote=True)
        sections.append(f'<section layer="{layer}" source="{source}" revision="{revision}">\n{content}\n</section>')
```
**Why**: `quote=True` escapes `"` and `'` as well as `&<>`, which is what an
attribute value needs. Keep the `\n{content}\n</section>` shape so plain output
is unchanged. Wrap to 120 columns if needed.

### `packages/ai-parrot/src/parrot/experts/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.experts.models import ExpertBundle, KnowledgeContext' agent.py) — line 12
from parrot.experts.models import SPAWN_TOOL_NAME, ExpertBundle, KnowledgeContext

# occurrences: 1 (verified: grep -c 'self._prompt_builder = install_layers' agent.py) — line 70
# AFTER the `if self._prompt_builder is not None:` block (dedented to method-body level, 8 spaces):
        if self.tool_manager.get_tool(SPAWN_TOOL_NAME) is not None:
            self.tool_manager.unregister_tool(SPAWN_TOOL_NAME)
            self.logger.warning("Removed %s from expert %s: domain experts never spawn sub-agents", SPAWN_TOOL_NAME, self.name)
```
Also extend the `configure` docstring with one sentence: the final tool list
never contains `spawn_sub_agent`.
**Why**: the guard goes last so it also catches tools registered by
`super().configure()` and `_configure_identity()`. It removes only the spawn
tool, never the framework tools.

### `packages/ai-parrot/src/parrot/experts/registry.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return self._experts\[name\]' registry.py) — line 66
# BEFORE `return self._experts[name]`:
        if tenant is not None:
            self.logger.warning(
                "ExpertRegistry.get(%r, tenant=%r): tenant-specific expert views are not built in phase one; "
                "returning the global instance",
                name,
                tenant,
            )
```
Update the docstring: add `Args:` (name, tenant — "accepted for forward
compatibility; ignored with a warning in phase one"), `Returns:`, `Raises: KeyError`.
**Why**: callers passing a tenant now get a signal without behaviour change.

### Tests (MODIFY — append)
```python
# test_render.py
def test_render_escapes_section_attributes() -> None:
    # FILL IN: KnowledgeContext with one INLINE non-rules layer, source='a"b<c>&d', revision='r"1';
    # assert 'source="a&quot;b&lt;c&gt;&amp;d"' and 'revision="r&quot;1"' in render_knowledge(ctx) — AC1

# test_agent_activation.py
@pytest.mark.asyncio
async def test_configured_expert_excludes_spawn_tool(expert_bundle: Path) -> None:
    # FILL IN: _make(...), await configure(); spawn_sub_agent absent, lookup_fact present — AC2

@pytest.mark.asyncio
async def test_configure_removes_injected_spawn_tool(expert_bundle: Path) -> None:
    # FILL IN: agent = _make(...); agent.tool_manager.add_tool(the `spawn_sub_agent` tool from _Toolkit().get_tools());
    # assert present; await configure(); assert absent and 'read_omitted_content' still listed — AC2

# test_registry.py
@pytest.mark.asyncio
async def test_get_with_tenant_warns_and_returns_global(expert_bundle: Path, caplog: pytest.LogCaptureFixture) -> None:
    # FILL IN: load as in test_registry_registers_tagged_instance; with caplog.at_level(logging.WARNING, logger="parrot.experts.registry"):
    # registry.get("sample-expert", tenant="acme") is registry.get("sample-expert"); "acme" in caplog.text — AC3
```

### FILL IN checklist
- [ ] `test_render.py::test_render_escapes_section_attributes` — AC1
- [ ] `test_agent_activation.py` two tests — AC2 (if `read_omitted_content` is not registered in this environment, assert instead that every pre-configure non-spawn tool survives, and say so in the Completion Note)
- [ ] `test_registry.py::test_get_with_tenant_warns_and_returns_global` — AC3 (add `import logging` if needed)

---

## Acceptance Criteria

- [ ] AC1: `render_knowledge` escapes `layer`, `source`, `revision`; plain output unchanged (existing `test_render.py` tests pass).
- [ ] AC2: a configured `ExpertAgent` never lists `spawn_sub_agent`; framework tools survive.
- [ ] AC3: `ExpertRegistry.get(..., tenant=<not None>)` warns and returns the global instance.
- [ ] AC4: Validation Commands pass; `ruff check` clean on the six files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_render.py -q`
- `pytest packages/ai-parrot/tests/experts/test_agent_activation.py -q`
- `pytest packages/ai-parrot/tests/experts/test_registry.py -q`

---

## Test Specification

See the Tests blueprint block above and spec §4.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug experts-agent-tech-debt --feature-id FEAT-785`), with `PYTHONPATH=packages/ai-parrot/src`.
2. Verify the Codebase Contract, mark the task in-progress in `sdd/tasks/index/experts-agent-tech-debt.json`.
3. Implement from the blueprint, run the Validation Commands, commit only the six files.
4. Close with `scripts/sdd/close_task.sh TASK-5082 experts-agent-tech-debt verified` and fill in the Completion Note.

---

## Completion Note

**Completed by**: agent:sdd-fix (Claude Opus 5.5, /sdd-fix issue:230ac877bdf5)
**Date**: 2026-11-01
**Notes**: Implemented M1–M3 in commit 78821a35b3. `render_knowledge` escapes layer/source/revision
with `html.escape(..., quote=True)`; plain output unchanged (existing render tests pass).
`ExpertAgent.configure()` unregisters `spawn_sub_agent` last, with a warning; framework tools
(`to_json`, `read_omitted_content`) survive. `ExpertRegistry.get(..., tenant=...)` warns and returns
the global instance. Four new tests; `test_render.py`, `test_agent_activation.py`, `test_registry.py`:
23 passed (worktree PYTHONPATH). Mutation check: with the guard disabled,
`test_configure_removes_injected_spawn_tool` fails. `ruff check` clean on the six files.
Resolves `issue:230ac877bdf5`.

**Deviations from spec**: none
