# TASK-4880: LLM-driven catalog→query example (`llm_metrics_agent.py`)

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4879
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3 and closes goal **G2** — the gap that motivated the whole
feature. Today `agent_semantic_example.py` builds an `Agent` at line 314 and **discards
it**: `run_demo` drives the toolkit directly, so no example anywhere shows an LLM actually
calling the `sl_*` tools.

That omission is not cosmetic. The governed tool path fail-closes unless the
`_permission_context` kwarg equals `current_pctx()` (`toolkit.py:110-116`), and that kwarg
arrives **only** through `AbstractBot.ask(permission_context=…)` →
`manager.py:2174` → `toolkit.py:178`. Direct method calls bypass `_pre_execute` entirely.
So the single most failure-prone integration detail of the subsystem is demonstrated
nowhere, and a developer copying the existing example into an LLM-driven agent hits
`context_required` with no worked example to compare against. This task is that example.

---

## Scope

- Create `examples/agents/semantic/llm_metrics_agent.py`: an `Agent` exposing only the
  `sl_*` tools, driven through `agent.ask(question, permission_context=ctx)` wrapped in
  `bind_semantic_context`.
- Give it a `--smoke` path that walks `sl_list_models` → `sl_get_dimensions` →
  `sl_query_metrics` deterministically with **no provider initialized and no network**.
- Create `packages/ai-parrot-semantic/tests/test_example_llm_metrics.py` pinning the
  provider-free smoke path, the real `ask(permission_context=…)` dispatch reaching a tool,
  and that **omitting either binding raises** `SemanticAccessError("context_required")`.

**NOT in scope**: the shared scaffolding (TASK-4879 owns `_common.py`); the MCP-local
surface (TASK-4881); masking or saved queries (TASK-4882); time grains or joins
(TASK-4883); the README or docs (TASK-4884); any change under
`packages/ai-parrot-semantic/src/**`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/llm_metrics_agent.py` | CREATE | The LLM-driven example |
| `packages/ai-parrot-semantic/tests/test_example_llm_metrics.py` | CREATE | Pin test (spec §4) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

```python
from parrot.bots import Agent                                   # verified: parrot/bots/__init__.py:12 (re-export of .agent)
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context  # verified: context.py:18,86
from parrot.semantic.errors import SemanticAccessError          # verified: errors.py:31
from parrot.semantic.models import SemanticQuery                # verified: models.py:102
from parrot.semantic.toolkit import SemanticLayerToolkit        # verified: toolkit.py:38
```

Plus the sibling module committed by TASK-4879, imported by absolute path in the test and
as a normal relative import is **not** available (examples are not a package) —
see "Key Constraints".

### Existing Signatures to Use

```python
# packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:110-116  — THE fail-closed gate
async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
    supplied = kwargs.get("_permission_context")
    bound = current_pctx()
    if supplied is None or bound is None or supplied != bound:
        raise SemanticAccessError("context_required", "A matching trusted semantic context is required")

# packages/ai-parrot-semantic/src/parrot/semantic/context.py:85-88
@asynccontextmanager
async def bind_semantic_context(
    ctx: PermissionContext, *, identity: SemanticRequestIdentity | None = None
) -> AsyncIterator[None]: ...
    # Raises SemanticAccessError if ctx is missing or disagrees with identity

# packages/ai-parrot/src/parrot/bots/base.py:1069-1093
async def ask(self, question: str, ..., permission_context: Optional[Any] = None, ...) -> AIMessage: ...
# the chain that carries it:  base.py:1083 -> base.py:1439-1440 / :2095-2096
#   (sets client._permission_context) -> manager.py:2174 (exec_kwargs["_permission_context"])
#   -> toolkit.py:178 (injects into the _pre_execute hook kwargs)

# packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py — the tools this example drives
tool_prefix = "sl"                                                            # :41
async def list_models(self) -> list[dict]: ...                                # :123
async def get_dimensions(self, model: str, metrics: list[str] | None = None) -> list[dict]: ...  # :147
async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult: ...  # :200

# packages/ai-parrot-semantic/src/parrot/semantic/models.py:102
class SemanticQuery(BaseModel):   # model_config = ConfigDict(extra="forbid")  :105
    model: str; metrics: list[str]; dimensions: list[str]; time_dimensions: list[TimeDimension]
    filters: FilterGroup | None; order_by: list[OrderBy]; limit: int | None; offset: int
    timezone: str | None; saved_query: str | None

# The house style for this directory — examples/agents/finance/hooba_agent.py
#   :3-6  `Usage::` docstring   ·  :22 module-level SYSTEM_PROMPT  ·  :28 build_* factory
#   :44   argparse with --smoke ·  :67-71 Agent(name=, system_prompt=, tools=toolkit.get_tools())
#   :72   await agent.configure()  before the first ask()
#   :78   asyncio.run(main())
```

Helpers committed by TASK-4879 in `examples/agents/semantic/_common.py`:
`MODELS_DIR`, `CONNECTION_ENV`, `CONNECTION_ENV_DIM`, `ExamplePolicyEvaluator`,
`build_guard`, `build_warehouse`, `build_dim_warehouse`, `connection_env`,
`example_identity`, `build_toolkit`.

### Does NOT Exist

- ~~`Agent(semantic_toolkit=…)`~~ — there is no such kwarg. Tools go in `tools=[...]`.
- ~~a way to pass `_permission_context` by calling a toolkit method directly~~ — a direct
  `await toolkit.query_metrics(...)` never runs `_pre_execute` at all. Only
  `ask(permission_context=…)` populates it.
- ~~`bind_semantic_context` as a *sync* context manager~~ — it is
  `@asynccontextmanager` (`context.py:85`); use `async with`.
- ~~`from parrot.semantic import SemanticRequestIdentity`~~ — the package root exports only
  `__version__, SemanticQuery, SemanticQueryResult, SemanticLayerToolkit`.
- ~~an `sl_reload` tool~~ — `exclude_tools = ("reload",)` (`toolkit.py:42`).
- ~~`sl_run_sql` / `sl_save_result_as_dataset` on this toolkit~~ — hidden unless
  `allow_raw_sql=True` / a `dataset_manager_factory` is supplied (`toolkit.py:104-107`).
  This example supplies neither.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/llm_metrics_agent.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_llm_metrics.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/context.py#bind_semantic_context",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#SemanticQuery",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **`examples/` is not a package** — there is no `__init__.py` and none may be added. The
  example imports its sibling with
  `sys.path.insert(0, str(Path(__file__).parent))` + `import _common`, or by loading it with
  `importlib.util.spec_from_file_location`. Pick one and use it consistently; a bare
  `from ._common import …` is an `ImportError` when the file is run as a script.
- **The smoke path must not construct a provider.** `Agent(...)` is only built on the LLM
  path, after `--smoke` has returned. `agent.configure()` is what reaches a provider; never
  call it in the smoke path (spec AC6).
- `--smoke` is the default behaviour when no question is given; the LLM path is opt-in,
  because `ci.yml:535-536` supplies no LLM credentials (S3).
- Direct toolkit method calls still need a **bound** context (`self._context()`), so the
  smoke path runs inside `async with bind_semantic_context(...)` even though it bypasses
  `_pre_execute`.
- `ruff` runs over `examples/` at line-length 120; only `F401,F841,E402` are waived, so the
  `sys.path` manipulation before an import needs no `noqa` (E402 is waived) but everything
  else must be clean.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module docstring in `Usage::` form and the `SYSTEM_PROMPT` — *why*: `hooba_agent.py:3-6,22` is the house style for this directory.
2. Add `build_agent(toolkit)` returning an `Agent` with `tools=toolkit.get_tools()` — *why*: there is no `semantic_toolkit` kwarg; tools are passed as a list.
3. Add `smoke(toolkit, identity)` walking catalog → dimensions → query with direct calls inside a bound context — *why*: it must run with no provider and no network (AC6) while still proving the catalog walk.
4. Add `ask_llm(agent, question, identity)` wrapping `bind_semantic_context` around `ask(permission_context=…)` — *why*: this is the only path that populates `_permission_context`; it is the whole point of the example (G2).
5. Add `main()` with `argparse` (`--smoke` | question) and `asyncio.run(main())` — *why*: matches `hooba_agent.py:44,78`.
6. Write the pin test, including **both** fail-closed cases — *why*: AC4 requires the missing-binding denial to be asserted, and AC7 requires it to fail the test if it silently succeeds.

### `examples/agents/semantic/llm_metrics_agent.py` (CREATE)
```python
"""LLM-driven catalog->query agent over the governed semantic layer (FEAT-769 M3).

This is the example that proves the binding the rest of the subsystem depends on: the
``sl_*`` tools fail closed unless ``ask(permission_context=...)`` supplies a context that
matches the one bound by ``bind_semantic_context``.

Usage::

    python examples/agents/semantic/llm_metrics_agent.py --smoke          # no LLM, no network
    python examples/agents/semantic/llm_metrics_agent.py "revenue by region"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import _common  # noqa: E402  (examples/ is not a package; see the task's Key Constraints)

from parrot.bots import Agent
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.models import SemanticQuery
from parrot.semantic.toolkit import SemanticLayerToolkit

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = """You answer questions about sales metrics using ONLY the sl_* tools.
Always discover the catalog first: call sl_list_models, then sl_get_dimensions for the model
you chose, and only then sl_query_metrics. Never invent a metric, a dimension or a figure.
If a member you need is not granted, say so plainly and stop — do not guess a substitute."""


def build_agent(toolkit: SemanticLayerToolkit) -> Agent:
    """Build an Agent exposing only the semantic layer's tools.

    Args:
        toolkit: A governed toolkit built by :func:`_common.build_toolkit`.

    Returns:
        An unconfigured Agent; the caller awaits ``configure()`` before the first ask.
    """
    return Agent(name="SemanticMetricsAgent", system_prompt=SYSTEM_PROMPT, tools=toolkit.get_tools())


async def smoke(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> dict[str, Any]:
    """Walk catalog -> dimensions -> query deterministically, with no LLM and no network.

    The calls are direct toolkit methods, which bypass ``_pre_execute`` by design
    (only ``ask()`` populates ``_permission_context``); the semantic context is still
    bound, because the tool bodies resolve the current subject from it.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted fixture identity.

    Returns:
        A JSON-safe summary of the three steps.
    """
    async with bind_semantic_context(identity.ctx, identity=identity):
        models = await toolkit.list_models()
        dimensions = await toolkit.get_dimensions("orders", metrics=["revenue"])
        result = await toolkit.query_metrics(
            SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
        )
    # FILL IN: build the summary dict — model names, dimension names, row count
    #          — bounded by: it must be json.dumps-able and contain no raw row data.
    raise NotImplementedError


async def ask_llm(agent: Agent, question: str, identity: SemanticRequestIdentity) -> Any:
    """Drive the sl_* tools through the real governed dispatch path.

    Wraps ``bind_semantic_context(identity.ctx, identity=identity)`` around
    ``agent.ask(question, permission_context=identity.ctx)``. Omitting EITHER binding
    raises ``SemanticAccessError("context_required")`` at ``toolkit.py:110-116``: the
    supplied kwarg and the bound context must both be present and equal.

    Args:
        agent: A configured Agent built by :func:`build_agent`.
        question: The user's natural-language question.
        identity: The trusted fixture identity; its ``ctx`` is both bound and supplied.

    Returns:
        The agent's ``AIMessage``.
    """
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await agent.ask(question, permission_context=identity.ctx)


async def main() -> None:
    """Run the deterministic smoke walk, or answer one question with an LLM."""
    parser = argparse.ArgumentParser(description="LLM-driven semantic metrics agent")
    parser.add_argument("--smoke", action="store_true", help="Run the deterministic walk (no LLM)")
    parser.add_argument("question", nargs="*", help="Question for the agent")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        warehouse = _common.build_warehouse(Path(directory))
        identity = _common.example_identity("analyst-1", "session-1", "eu")
        with _common.connection_env(warehouse):
            toolkit = _common.build_toolkit(warehouse)
            if args.smoke or not args.question:
                summary = await smoke(toolkit, identity)
                print(json.dumps(summary, indent=2))
                return
            # FILL IN: build the agent, await agent.configure(), call ask_llm with
            #          " ".join(args.question), print the answer — bounded by AC6:
            #          configure() must NOT be reachable from the --smoke path.
            raise NotImplementedError


if __name__ == "__main__":
    asyncio.run(main())
```
**Why this shape**: `smoke` and `ask_llm` are separate functions so the pin test can drive
each independently and prove that the smoke path never touches a provider (AC6). `ask_llm`
is three lines on purpose — the lesson is *which* two bindings are required, and the
docstring names the exact source line that enforces it. `main()` defaults to `--smoke` when
no question is given so a developer who runs the file with no arguments and no credentials
gets a working demonstration rather than a provider error.

### `packages/ai-parrot-semantic/tests/test_example_llm_metrics.py` (CREATE)
```python
"""Regression contract: the LLM-driven semantic example (FEAT-769 M3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.context import bind_semantic_context
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.models import SemanticQuery

pytest.importorskip("duckdb")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "llm_metrics_agent.py"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_llm_metrics_example", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture
def governed(example: ModuleType, tmp_path: Path):
    """A governed toolkit and identity with the example connection bound."""
    warehouse = example._common.build_warehouse(tmp_path)
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    with example._common.connection_env(warehouse):
        yield example._common.build_toolkit(warehouse), identity


@pytest.mark.asyncio
async def test_smoke_walks_the_catalog_without_a_provider(example: ModuleType, governed) -> None:
    """Spec AC6: the deterministic path initializes no LLM provider."""
    toolkit, identity = governed
    summary = await example.smoke(toolkit, identity)
    # FILL IN: assert the summary reports the orders model, its dimensions and a row count
    #          — bounded by AC3 (offline, deterministic).


@pytest.mark.asyncio
async def test_ask_dispatch_reaches_a_tool(example: ModuleType, governed, monkeypatch) -> None:
    """Spec AC4: at least one sl_* tool is reached through ask(permission_context=...)."""
    toolkit, identity = governed
    # FILL IN: build the agent, stub its LLM so that `ask` dispatches one sl_* tool call
    #          without a provider, run ask_llm, and assert the tool actually executed
    #          — bounded by AC6: no real provider may be initialized. Record the call by
    #          wrapping the toolkit method, not by asserting on log output.


@pytest.mark.asyncio
async def test_missing_supplied_context_fails_closed(example: ModuleType, governed) -> None:
    """Bound but not supplied -> context_required (toolkit.py:110-116)."""
    toolkit, identity = governed
    tool = next(tool for tool in toolkit.get_tools() if tool.name.endswith("list_models"))
    async with bind_semantic_context(identity.ctx, identity=identity):
        with pytest.raises(SemanticAccessError) as excinfo:
            await tool._execute()          # no _permission_context kwarg
    assert "context_required" in str(excinfo.value)


@pytest.mark.asyncio
async def test_mismatched_context_fails_closed(example: ModuleType, governed) -> None:
    """Supplied but not bound, and supplied-but-different, both fail closed (spec AC4/AC7)."""
    toolkit, identity = governed
    # FILL IN: two cases — (a) supply identity.ctx with NO surrounding bind_semantic_context,
    #          (b) bind identity.ctx but supply a DIFFERENT context built by
    #          _common.example_identity("other-user", "other-session", "us").ctx.
    #          Both must raise SemanticAccessError("context_required")
    #          — bounded by AC7: if either silently succeeds, this test must fail.
```
**Why this shape**: the two fail-closed tests are the ones AC4 names, and they are written
as `pytest.raises` rather than a logged warning because AC7 requires a denial that silently
succeeds to **fail** the test — the `test_example_agent.py:199-215` pattern. The example is
loaded by absolute path with `spec_from_file_location` and `sys.modules` popped in a
`finally`, the precedent at `test_example_agent.py:26-37`. Reaching `example._common` works
because the example inserts its own directory on `sys.path` at import time.

### FILL IN checklist
- [ ] `llm_metrics_agent.py::smoke` — the JSON-safe summary dict; bounded by: no raw rows, `json.dumps`-able.
- [ ] `llm_metrics_agent.py::main` — the LLM branch (build, `configure()`, `ask_llm`, print); bounded by AC6 (unreachable from `--smoke`).
- [ ] `test_example_llm_metrics.py::test_smoke_walks_the_catalog_without_a_provider` — the summary assertions; bounded by AC3.
- [ ] `test_example_llm_metrics.py::test_ask_dispatch_reaches_a_tool` — the provider stub and the executed-tool assertion; bounded by AC4 + AC6.
- [ ] `test_example_llm_metrics.py::test_mismatched_context_fails_closed` — the two mismatch cases; bounded by AC4 + AC7.

---

## Acceptance Criteria

- [ ] The example drives at least one `sl_*` tool through
      `agent.ask(question, permission_context=ctx)` under `bind_semantic_context`
      (spec AC4, goal G2).
- [ ] The pin test asserts that omitting **either** binding raises
      `SemanticAccessError("context_required")`, and fails if a denial silently succeeds
      (spec AC4, AC7).
- [ ] `--smoke` runs offline: no LLM call, no network, no write outside a temporary
      directory, and `CONNECTION_ENV` restored on exit (spec AC3).
- [ ] No LLM provider is initialized in the deterministic path of the example or its test
      (spec AC6).
- [ ] `ruff check examples/agents/semantic packages/ai-parrot-semantic/tests/test_example_llm_metrics.py`
      is clean (spec AC9).
- [ ] No file named `test_*.py` was added under `examples/` (spec AC10).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_llm_metrics.py -q`

---

## Test Specification

See the `test_example_llm_metrics.py` block above — it IS the test specification. Four
tests: provider-free smoke, real `ask` dispatch reaching a tool, missing-supplied-context
denial, mismatched-context denial.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above — especially §1 "Problem Statement", which
   explains why this example exists
3. **Check dependencies** — TASK-4879 must be `"done"`; this example imports `_common`
4. **Verify the Codebase Contract** — re-read `toolkit.py:110-116` and `context.py:85-88`
   before writing the dispatch code; these two are the whole subject of the example
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4880 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
