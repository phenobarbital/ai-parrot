# TASK-4881: MCP-local allow + deny example (`mcp_local_agent.py`)

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4879
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4 and closes goal **G3**. `docs/tools/semantic-layer.md:172-175`
instructs the reader to "exercise both an explicit allow and an explicit deny policy
against the real server factory" and warns that "parsing or listing configuration alone is
not evidence that the configured PBAC guard binds the static identity around tool
execution" — yet no runnable example performs either decision. The only code that does is
`test_mcp_local.py`, which a reader of `examples/` never sees.

This example makes the documented instruction executable: it builds the documented
toolkit configuration, starts the toolkit through the real
`create_toolkit_mcp_server` factory twice — once with an allowing policy and once with a
denying one — and asserts the deny actually raises.

---

## Scope

- Create `examples/agents/semantic/mcp_local_agent.py` with `write_toolkit_config`,
  `build_guard` (the example's own PBAC factory), `run_decision` and `smoke`.
- Build the toolkit through `create_toolkit_mcp_server`, the supported MCP-local path —
  never by instantiating `LocalSemanticLayerToolkit` directly.
- Execute one **allow** (returns a result) and one **deny** (raises `SemanticAccessError`).
- Create `packages/ai-parrot-semantic/tests/test_example_mcp_local.py` pinning both
  decisions, with the deny asserted via `pytest.raises`.

**NOT in scope**: the shared scaffolding (TASK-4879); the LLM path (TASK-4880); masking or
saved queries (TASK-4882); grains or joins (TASK-4883); **editing
`docs/tools/semantic-layer.md`** (TASK-4884 owns it, and its fences are an API — see
Key Constraints); any change under `packages/ai-parrot-semantic/src/**`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/mcp_local_agent.py` | CREATE | MCP-local allow + deny example |
| `packages/ai-parrot-semantic/tests/test_example_mcp_local.py` | CREATE | Pin test (spec §4) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

```python
from parrot.auth import DataPlanePolicyGuard, RlsRegistry       # lazily re-exported; verify by import
from parrot.mcp.toolkit_server import create_toolkit_mcp_server # verified: toolkit_server.py:137
from parrot.semantic.errors import SemanticAccessError, SemanticPolicyError  # verified: errors.py:31,27
from parrot.semantic.models import SemanticQuery                # verified: models.py:102
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py:137
def create_toolkit_mcp_server(
    name: str,
    root: Path = Path.cwd(),
    **overrides: Any,
) -> StdioMCPServer: ...
# the server owns the toolkit; reach it as  server._owned_toolkit  and then
#   toolkit.get_tool("sl_compile_query")  ->  await tool._execute(query=<SemanticQuery>)
# verified usage: packages/ai-parrot-semantic/tests/test_mcp_local.py:108-124,126-150

# packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:60
class LocalSemanticLayerToolkit(SemanticLayerToolkit):
    def __init__(self, *, static_subject, agent_id: str, guard_factory: str,
                 guard_factory_kwargs: dict | None = None, **kwargs) -> None: ...   # :65-72
    @staticmethod
    def _require_evaluator_modules() -> None: ...   # :118-126
    # raises SemanticPolicyError("pbac_unavailable") without
    #   navigator_auth.abac.policies.evaluator / .environment

# The guard-factory contract, verified at packages/ai-parrot-semantic/tests/_guard_factory.py:32
def build_guard(*, rls_registry: RlsRegistry, policy_dir: str) -> DataPlanePolicyGuard: ...
# KEYWORD-ONLY. `rls_registry` is supplied by the bootstrap; `policy_dir` comes from
# guard_factory_kwargs in the YAML.
```

The documented configuration this example must reproduce — `docs/tools/semantic-layer.md:122-135`,
read verbatim at `e00c8de82` (do **not** edit the doc; this example writes its own copy
to a temporary directory):

```yaml
toolkits:
  semantic-layer:
    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit
    kwargs:
      models_dir: /path/to/models
      dialect: duckdb
      agent_id: local-semantic
      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}
      guard_factory: myapp.semantic_auth.build_guard
      guard_factory_kwargs: {policy_dir: /path/to/policies}
    env: {}
```

The allow/deny pattern to follow — `packages/ai-parrot-semantic/tests/test_mcp_local.py:126-150`:

```python
allow_server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=allow_config)
allow_tool = allow_server._owned_toolkit.get_tool("sl_compile_query")
assert "SELECT" in (await allow_tool._execute(query=_QUERY))["sql"]

deny_server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=deny_config)
deny_tool = deny_server._owned_toolkit.get_tool("sl_compile_query")
with pytest.raises(SemanticAccessError, match="PBAC denied"):
    await deny_tool._execute(query=_QUERY)
```

The factory-module registration trick — `test_mcp_local.py:51-55` — needed because
`examples/` is not an importable package:

```python
monkeypatch.setitem(sys.modules, "semantic_mcp_local_guard_factory", _guard_factory)
# the YAML then names "semantic_mcp_local_guard_factory.build_guard"
```

### Does NOT Exist

- ~~`LocalSemanticLayerToolkit(...)` as the example's entry point~~ — spec §3 M4 and S5
  require the **real server factory**. Instantiating the toolkit directly proves nothing
  about the MCP-local path.
- ~~a `.parrot/mcp-toolkits.yaml` committed in the repo~~ — operator configuration is
  intentionally local and ignored. The example writes its config to a temp directory.
- ~~`build_guard(rls_registry, policy_dir)`~~ positionally — the factory contract is
  **keyword-only** (`_guard_factory.py:32`).
- ~~`server.toolkit`~~ — the attribute is `server._owned_toolkit`
  (`test_mcp_local.py:115,131`).
- ~~stubbing `navigator_auth.abac.policies.*`~~ — spec §7 forbids "fixing" the Navigator
  DEBUG output this way. Both modules import in the workspace venv; the pin test guards
  with `importorskip` instead.
- ~~an `sl_query_metrics` call in this example~~ — not required; `sl_compile_query` is the
  tool the documented check uses and it needs no warehouse connection.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/mcp_local_agent.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_mcp_local.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py#LocalSemanticLayerToolkit",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#SemanticQuery"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Do not touch `docs/tools/semantic-layer.md`.** `test_mcp_local.py:32-50,78-107` parses
  its fences as an API: exactly one yaml block with top-level key `toolkits`, exactly one
  starting `# orders.yml`, exactly one starting `# orders.policy.yaml`, and every json
  block must parse with `mcpServers` equal to exactly one entry. TASK-4884 owns the doc and
  must add no yaml or json fence; this task adds none at all.
- **Importing `navigator_auth` emits Navigator DEBUG output and reads `settings/`.** That
  is expected noise in this example. Do not silence it by stubbing the evaluator modules
  (spec §7).
- The example registers **itself** in `sys.modules` under a stable factory-module name so
  the YAML's dotted `guard_factory` resolves — `examples/` is not an importable package.
  Restore `sys.modules` on the way out, as `test_mcp_local.py` does via `monkeypatch`.
- Everything is written under a `tempfile.TemporaryDirectory`; nothing under the working
  directory (spec AC3).
- No LLM provider anywhere (spec AC6) — this example builds no `Agent` at all.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module docstring in `Usage::` form and the example's own `build_guard` factory — *why*: the YAML names a dotted path, so the factory must live at an importable name before the config is written.
2. Register the module in `sys.modules` under a stable name — *why*: `examples/` is not a package; this is the `test_mcp_local.py:51-55` precedent.
3. Add `write_toolkit_config(directory, *, models, policy_dir, factory)` reproducing the documented YAML with host paths substituted — *why*: the example must demonstrate the *documented* configuration, not an invented one.
4. Add `run_decision(config, *, allow)` going through `create_toolkit_mcp_server` — *why*: S5 and spec AC5 require the real server factory; direct toolkit construction is not evidence.
5. Add `smoke()` running both decisions and **raising** if the deny succeeds — *why*: AC7; a denial that is merely logged is the exact regression class `issue:f0da823294fb` found.
6. Write the pin test asserting both decisions — *why*: spec AC5.

### `examples/agents/semantic/mcp_local_agent.py` (CREATE)
```python
"""MCP-local semantic layer: one real allow and one real deny (FEAT-769 M4).

The documentation tells operators to "exercise both an explicit allow and an explicit deny
policy against the real server factory". This example does exactly that, through
``create_toolkit_mcp_server`` — the supported MCP-local path.

Usage::

    python examples/agents/semantic/mcp_local_agent.py --smoke     # both decisions, no LLM
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import _common  # noqa: E402  (examples/ is not a package)

from parrot.auth import DataPlanePolicyGuard, RlsRegistry
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.models import SemanticQuery

LOGGER = logging.getLogger(__name__)

#: The name this module registers itself under so the YAML's dotted guard_factory resolves.
FACTORY_MODULE = "semantic_example_mcp_guard_factory"

_QUERY = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])


class ExampleDecisionEvaluator:
    """PBAC evaluator returning one explicit, operator-configured decision."""

    def __init__(self, allow: bool) -> None:
        """Store the explicit decision read from the policy directory."""
        self._allow = allow

    def check_access(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        """Return the configured decision for a single protected resource."""
        del args, kwargs
        return SimpleNamespace(allowed=self._allow)

    def filter_resources(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        """Return every resource only when the decision explicitly permits them."""
        resources = args[2] if len(args) > 2 else kwargs["resource_names"]
        return SimpleNamespace(allowed=list(resources) if self._allow else [])


def build_guard(*, rls_registry: RlsRegistry, policy_dir: str) -> DataPlanePolicyGuard:
    """Load the explicit decision from ``policy_dir`` and fail closed when it is missing.

    This is the host-supplied factory the documented YAML names. Its signature is fixed by
    the bootstrap: keyword-only, ``rls_registry`` injected, ``policy_dir`` from
    ``guard_factory_kwargs``.

    Args:
        rls_registry: Registry supplied by the local bootstrap.
        policy_dir: Directory holding ``decisions.json``.

    Returns:
        A real DataPlanePolicyGuard — never a bypassed one.

    Raises:
        ValueError: When the decision file is absent or malformed.
    """
    # FILL IN: read policy_dir/decisions.json, require a boolean "allow", and raise
    #          ValueError on any OSError/KeyError/JSONDecodeError — bounded by:
    #          missing configuration must fail CLOSED, never default to allow.
    raise NotImplementedError


def write_toolkit_config(directory: Path, *, models: Path, policy_dir: Path, factory: str) -> Path:
    """Write the documented ``.parrot/mcp-toolkits.yaml`` equivalent for a local run.

    Reproduces the block in ``docs/tools/semantic-layer.md`` with only the host-owned
    paths and the factory name substituted.

    Args:
        directory: Directory the config file is written to.
        models: Model directory the toolkit loads.
        policy_dir: Directory holding the explicit decision.
        factory: Dotted path of the guard factory, e.g. ``f"{FACTORY_MODULE}.build_guard"``.

    Returns:
        The path of the written config file.
    """
    # FILL IN: write the documented YAML with models/policy_dir/factory substituted —
    #          bounded by: it must stay field-for-field identical to the documented block
    #          quoted in this task's Codebase Contract (class, dialect, agent_id,
    #          static_subject, guard_factory, guard_factory_kwargs, env).
    raise NotImplementedError


async def run_decision(config: Path, *, allow: bool) -> Any:
    """Execute one governed call through the owned MCP toolkit.

    Args:
        config: Path of a config written by :func:`write_toolkit_config`.
        allow: Only used for logging which decision is being exercised.

    Returns:
        The tool result when the policy allows the call.

    Raises:
        SemanticAccessError: When the policy denies it.
    """
    LOGGER.info("running the %s decision through create_toolkit_mcp_server", "allow" if allow else "deny")
    server = create_toolkit_mcp_server("semantic-layer", root=config.parent, config_path=config)
    tool = server._owned_toolkit.get_tool("sl_compile_query")
    if tool is None:
        raise RuntimeError("sl_compile_query is not exposed by the owned toolkit")
    return await tool._execute(query=_QUERY)


async def smoke() -> dict[str, Any]:
    """Run both the allow and the deny decision against the real server factory.

    Returns:
        A JSON-safe summary of both outcomes.

    Raises:
        RuntimeError: If the deny decision does **not** raise — a silently-succeeding
            denial is a failure, not a pass.
    """
    sys.modules[FACTORY_MODULE] = sys.modules[__name__]
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # FILL IN: write an allow policy dir and a deny policy dir (each a
            #          decisions.json holding {"allow": true|false}), write a config for
            #          each with write_toolkit_config(..., factory=f"{FACTORY_MODULE}.build_guard"),
            #          run both decisions, and RAISE RuntimeError("deny unexpectedly succeeded")
            #          if the deny returns instead of raising SemanticAccessError
            #          — bounded by AC5 and AC7.
            raise NotImplementedError
    finally:
        sys.modules.pop(FACTORY_MODULE, None)


async def main() -> None:
    """Run both decisions and print a summary."""
    parser = argparse.ArgumentParser(description="MCP-local semantic layer: allow and deny")
    parser.add_argument("--smoke", action="store_true", help="Run both decisions (default)")
    parser.parse_args()
    print(json.dumps(await smoke(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```
**Why this shape**: `run_decision` is deliberately thin and goes through
`create_toolkit_mcp_server`, because S5 and spec AC5 say that parsing or listing
configuration is **not** evidence — only a tool actually executing under the configured
guard is. `smoke()` raises on a non-denial rather than logging it, which is the
`test_example_agent.py:199-215` pattern AC7 requires. The module registers itself as the
factory module so the documented dotted `guard_factory` resolves without `examples/`
becoming a package, mirroring `test_mcp_local.py:51-55`.

### `packages/ai-parrot-semantic/tests/test_example_mcp_local.py` (CREATE)
```python
"""Regression contract: the MCP-local allow/deny example (FEAT-769 M4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.errors import SemanticAccessError

pytest.importorskip("duckdb")
pytest.importorskip("navigator_auth.abac.policies.evaluator")
pytest.importorskip("navigator_auth.abac.policies.environment")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "mcp_local_agent.py"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the skip checks."""
    spec = importlib.util.spec_from_file_location("semantic_mcp_local_example", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.mark.asyncio
async def test_smoke_runs_both_decisions(example: ModuleType) -> None:
    """Spec AC5: a real allow returns a result AND a real deny raises."""
    summary = await example.smoke()
    # FILL IN: assert the summary records an allowed result (its compiled SQL contains
    #          "SELECT") and a denied outcome — bounded by AC5.


@pytest.mark.asyncio
async def test_deny_raises_through_the_real_factory(example: ModuleType, tmp_path: Path) -> None:
    """The deny decision raises SemanticAccessError from an actual tool execution."""
    sys.modules[example.FACTORY_MODULE] = example
    try:
        # FILL IN: write a deny policy dir and config, then assert
        #          `with pytest.raises(SemanticAccessError)` around
        #          `await example.run_decision(config, allow=False)`
        #          — bounded by AC5 and AC7 (not a logged warning).
        pass
    finally:
        sys.modules.pop(example.FACTORY_MODULE, None)


@pytest.mark.asyncio
async def test_a_silently_succeeding_deny_fails_the_example(example: ModuleType, monkeypatch) -> None:
    """Spec AC7: if the deny stops raising, smoke() must fail rather than pass."""
    # FILL IN: monkeypatch run_decision so the deny branch returns a result instead of
    #          raising, then assert `pytest.raises(RuntimeError)` around smoke()
    #          — bounded by the test_example_agent.py:199-215 pattern.


def test_missing_policy_configuration_fails_closed(example: ModuleType, tmp_path: Path) -> None:
    """build_guard refuses to default to allow when decisions.json is absent."""
    from parrot.auth import RlsRegistry

    with pytest.raises(ValueError):
        example.build_guard(rls_registry=RlsRegistry(), policy_dir=str(tmp_path / "missing"))
```
**Why this shape**: the third test is the one that makes AC7 real — it breaks the denial on
purpose and requires the example to notice. `importorskip` on the two
`navigator_auth.abac.policies` modules is spec §3 M4's stated guard: both import in the
workspace venv, but `LocalSemanticLayerToolkit._require_evaluator_modules`
(`bootstrap.py:118-126`) raises `pbac_unavailable` without them, and a skipped test is
better than a confusing failure on a thinner install.

### FILL IN checklist
- [ ] `mcp_local_agent.py::build_guard` — read `decisions.json`, require a boolean, fail closed; bounded by: missing config never defaults to allow.
- [ ] `mcp_local_agent.py::write_toolkit_config` — the documented YAML with substitutions; bounded by the contract's verbatim block.
- [ ] `mcp_local_agent.py::smoke` — both policy dirs, both configs, both decisions, `RuntimeError` on a non-denial; bounded by AC5 + AC7.
- [ ] `test_example_mcp_local.py::test_smoke_runs_both_decisions` — the summary assertions; bounded by AC5.
- [ ] `test_example_mcp_local.py::test_deny_raises_through_the_real_factory` — the deny config and `pytest.raises`; bounded by AC5.
- [ ] `test_example_mcp_local.py::test_a_silently_succeeding_deny_fails_the_example` — the broken-denial monkeypatch; bounded by AC7.

---

## Acceptance Criteria

- [ ] The example executes one allow **and** one deny through `create_toolkit_mcp_server`,
      and the pin test asserts `SemanticAccessError` on the deny (spec AC5).
- [ ] `smoke()` raises if the deny silently succeeds, and a test proves it (spec AC7).
- [ ] `build_guard` fails closed when its decision file is missing.
- [ ] Nothing is written outside a temporary directory (spec AC3).
- [ ] No LLM provider is initialized (spec AC6) — this example builds no `Agent`.
- [ ] `docs/tools/semantic-layer.md` is **not** modified by this task, and
      `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py` still passes (spec AC8).
- [ ] `ruff check examples/agents/semantic packages/ai-parrot-semantic/tests/test_example_mcp_local.py`
      is clean (spec AC9).
- [ ] No file named `test_*.py` was added under `examples/` (spec AC10).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_mcp_local.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py -q`

---

## Test Specification

See the `test_example_mcp_local.py` block above — it IS the test specification. Four
tests: both decisions run, the deny raises through the real factory, a broken denial fails
the example, and a missing policy file fails closed. `test_mcp_local.py` is re-run as the
AC8 regression check.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above — especially §7's note that the documentation
   fences are an API
3. **Check dependencies** — TASK-4879 must be `"done"`
4. **Verify the Codebase Contract** — re-read `test_mcp_local.py:108-150` for the exact
   factory usage and `_guard_factory.py:32` for the keyword-only factory signature
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4881 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
