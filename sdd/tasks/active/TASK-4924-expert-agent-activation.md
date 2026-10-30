# TASK-4924: `ExpertAgent` and `activate_expert()` attribution scope

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4914, TASK-4918, TASK-4919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, U1, G8, AC3, AC12, AC17, AC18. `ExpertAgent(IdentityMixin, Agent)` is what a bundle becomes at
runtime: identity from `<bundle>/identity/` (FEAT-321 five-file layout; `persona.md` is never read), knowledge
installed as literal layers from the resolved `KnowledgeContext`, a tool allowlist enforced at construction.
`activate_expert()` stacks the two existing observability context managers so every call inside is attributed to
the expert and the seat `<stage>.<expert>`.

Verified behaviour that shapes the design: `IdentityMixin` does **not** override `configure()`; the subclass must
call `await self._configure_identity()` after `await super().configure(app)` (`bots/mixins/identity.py:130-140`).
`Agent`/`BasicAgent` have no generic `allowed_tools` argument, so the allowlist is applied by filtering the
toolkits' tools before they reach `super().__init__(tools=…)`.

---

## Scope

- Create `experts/agent.py` (`ExpertAgent`) and `experts/activation.py` (`activate_expert`).
- Write `test_agent_activation.py` with a fake LLM (no network): identity dir, allowlist filtering, layers
  installed, attribution and restoration, concurrency isolation.

**NOT in scope**: building toolkits or the resolver (the registry does, TASK-4926); tier → model (TASK-4917).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/agent.py` | CREATE | `ExpertAgent` |
| `packages/ai-parrot/src/parrot/experts/activation.py` | CREATE | `activate_expert` |
| `packages/ai-parrot/tests/experts/test_agent_activation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.agent import Agent                          # verified: parrot/bots/agent.py:1576
from parrot.bots.mixins.identity import IdentityMixin         # verified: parrot/bots/mixins/identity.py:40
from parrot.models.basic import ModelConfig                   # verified: parrot/models/basic.py:40
from parrot.tools.toolkit import AbstractToolkit              # verified: parrot/tools/toolkit.py:225
from parrot.observability.context import agent_identity, usage_attribution, current_agent_name, current_seat
#   verified: parrot/observability/context.py:86, :162, :67, :158
from parrot.experts.knowledge.render import install_layers    # TASK-4918
from parrot.experts.knowledge.resolver import KnowledgeResolver   # TASK-4919
from parrot.experts.models import ExpertBundle, KnowledgeContext  # TASK-4914
```

### Existing Signatures to Use
```python
# parrot/bots/mixins/identity.py
class IdentityMixin:                         # line 40
    enable_identity: bool = False            # line 59
    identity_dir: Union[str, Path, None] = None   # line 60 — explicit value wins (line 126-127)
    async def _configure_identity(self) -> None   # line 130 — call after super().configure()
# parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):   # line 40
    def __init__(self, name: str = "Agent", agent_id: str = "agent", use_llm: str = "google", llm: str = None,
                 tools: List[AbstractTool] = None, system_prompt: str = None, human_prompt: str = None,
                 use_tools: bool = True, instructions: Optional[str] = None, dataframes=None, **kwargs)   # line 86
    async def configure(self, app=None) -> None   # line 179
class Agent(BasicAgent)                           # line 1576
# parrot/bots/abstract.py — AbstractBot.__init__ pops kwargs "temperature" / "max_tokens" (lines 1030-1032);
#   self._prompt_builder (line 234) + property prompt_builder (line 1394) / setter (line 1399)
# parrot/tools/toolkit.py
class AbstractToolkit:   # line 225
    def get_tools(self, permission_context=None, ...) -> list   # line 522 (synchronous)
# parrot/observability/context.py
@contextmanager def agent_identity(name: Optional[str]) -> Iterator[None]                       # line 86
@contextmanager def usage_attribution(run_id: Optional[str], seat: Optional[str] = None) -> Iterator[None]   # line 162
current_agent_name: ContextVar[Optional[str]]   # line 67
current_seat: ContextVar[Optional[str]]         # line 158
```

### Does NOT Exist
- ~~`Agent(allowed_tools=…)`~~ — no such constructor argument on `Agent`/`BasicAgent`/`AbstractBot`; filter tools yourself.
- ~~`IdentityMixin.configure()`~~ — the mixin does not override `configure()`.
- ~~`persona.md` loading~~ — never read by code (U1, AC3).
- ~~an async `agent_identity`~~ — both helpers are sync `@contextmanager`s; wrap them inside an `@asynccontextmanager`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/agent.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/activation.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_agent_activation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/identity.py#IdentityMixin",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/identity.py#IdentityMixin._configure_identity",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ModelConfig",
    "sym:packages/ai-parrot/src/parrot/observability/context.py#agent_identity",
    "sym:packages/ai-parrot/src/parrot/observability/context.py#usage_attribution"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- MRO is `ExpertAgent(IdentityMixin, Agent)`; set `self.identity_dir` **before** `super().__init__` (spec M3).
- Model: pass `llm=f"{model_config.provider}:{model_config.model}"`, `temperature=…`, `max_tokens=…` to
  `super().__init__` — the "provider:model" string is the documented `llm` format (CONTEXT.md, ModelSwitchingMixin).
- `configure` order: `super().configure(app)` → `_configure_identity()` → `resolve()` → `install_layers()` on the
  identity-configured builder. If `install_layers` after identity configuration loses the CONFIGURE-phase render,
  move it before `_configure_identity()` and record why in the Completion Note — bounded by
  `test_bundle_to_prompt_roundtrip` (TASK-4934).

---

## Implementation Blueprint

### Steps (in order)
1. `activation.py` — *why*: tiny, isolates AC12.
2. `agent.py` constructor (identity dir, allowlist filter, model) then `configure`.

### `packages/ai-parrot/src/parrot/experts/activation.py` (CREATE)
```python
"""Attribution scope for an expert activation (FEAT-778 M3, G8)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from parrot.observability.context import agent_identity, usage_attribution

if TYPE_CHECKING:
    from parrot.experts.agent import ExpertAgent


@asynccontextmanager
async def activate_expert(expert: "ExpertAgent", *, run_id: str | None, stage: str | None) -> AsyncIterator["ExpertAgent"]:
    """Bind agent_identity(<expert>) and usage_attribution(run_id, '<stage>.<expert>'); restored on exit (AC12)."""
    name = expert.bundle.manifest.name
    seat = f"{stage}.{name}" if stage else name
    with agent_identity(name), usage_attribution(run_id, seat):
        yield expert
```

### `packages/ai-parrot/src/parrot/experts/agent.py` (CREATE)
```python
"""The runtime agent an expert bundle produces (FEAT-778 M3)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from parrot.bots.agent import Agent
from parrot.bots.mixins.identity import IdentityMixin
from parrot.experts.knowledge.render import install_layers
from parrot.experts.knowledge.resolver import KnowledgeResolver
from parrot.experts.models import ExpertBundle, KnowledgeContext
from parrot.models.basic import ModelConfig
from parrot.tools.toolkit import AbstractToolkit


class ExpertAgent(IdentityMixin, Agent):
    """Agent configured from an ExpertBundle: bundle identity, literal knowledge layers, tool allowlist."""

    enable_identity: bool = True

    def __init__(self, bundle: ExpertBundle, *, resolver: KnowledgeResolver, model_config: ModelConfig,
                 toolkits: Sequence[AbstractToolkit], allowed_tools: Sequence[str],
                 workspace: Path | None = None, **kwargs: Any) -> None:
        self.bundle = bundle
        self.knowledge_resolver = resolver
        self.knowledge_context: KnowledgeContext | None = None
        self.workspace = workspace
        self.identity_dir = bundle.identity_dir  # read by IdentityMixin._resolve_identity_dir (identity.py:126)
        allowed = set(allowed_tools)
        tools = [tool for toolkit in toolkits for tool in toolkit.get_tools() if tool.name in allowed]
        super().__init__(
            name=bundle.manifest.name,
            agent_id=bundle.manifest.name,
            llm=f"{model_config.provider}:{model_config.model}",
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            tools=tools,
            **kwargs,
        )
        self.model_config = model_config

    async def configure(self, app: Any = None) -> None:
        """Base configure, identity layers, then the resolved knowledge as literal layers."""
        await super().configure(app)
        await self._configure_identity()
        self.knowledge_context = await self.knowledge_resolver.resolve(
            self.bundle, None, self.workspace, model=self.model_config.model)
        # FILL IN: self._prompt_builder = install_layers(self._prompt_builder, self.knowledge_context) when a
        # builder exists (keep order per Key Constraints) — bounded by AC8, AC17, AC18
```
**Why this shape**: filtering in `__init__` is the only allowlist point an `Agent` has; storing `knowledge_resolver`
as an instance attribute is what `_build_kb_context` (TASK-4923) looks for.

### FILL IN checklist
- [ ] `configure` — install the layers; confirm order against the roundtrip behaviour.

---

## Acceptance Criteria

- [ ] AC3 — identity comes from `<bundle>/identity/`; a `persona.md` sentinel string never appears in the prompt.
- [ ] AC12 — inside `activate_expert`, `current_agent_name.get()` is the expert name and `current_seat.get()` is
      `"<stage>.<expert>"`; both are restored after exit.
- [ ] AC18 — two concurrent `activate_expert` scopes (`asyncio.gather`) keep their own name/seat and their own builders.
- [ ] Tools not in `allowed_tools` are not registered on the agent.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_agent_activation.py -q`
- `pytest packages/ai-parrot/tests/bots/test_identity_mixin.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_agent_activation.py — expert_bundle fixture; fake resolver; llm stubbed
def test_expert_agent_uses_bundle_identity_dir(expert_bundle): ...   # FILL IN
def test_allowlist_filters_tools(expert_bundle): ...                 # FILL IN: toolkit with spawn_sub_agent + 1 tool
async def test_configure_installs_expert_layers(expert_bundle): ...  # FILL IN
async def test_activate_expert_attribution(expert_bundle): ...       # FILL IN
async def test_concurrent_activations_isolated(expert_bundle): ...   # FILL IN
def test_persona_md_never_read(expert_bundle): ...                   # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4924 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
