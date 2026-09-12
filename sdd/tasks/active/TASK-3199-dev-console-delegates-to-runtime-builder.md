# TASK-3199: `examples/dev_loop/server_dev.py` delegates its dev-flow wiring to `build_dev_flow_runtime()`

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3197
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, optional refactor (design research S2, Known Risk
"`build_dev_flow_runtime` drift"). TASK-3197 lifts the dev-flow wiring into the
package; if the example console keeps its own copy the two will drift. This
task makes `_on_startup` call the package builder and layer only the
console-specific extras on top (ideation-seat MCP servers from `mcp_wiring`,
the console's default model plan, the judge-panel reviewer that the console
keeps by default, `DEV_FLOW_USE_REVIEW_PAIR`). A parity test asserts both call
`build_dev_flow` with the same key set.

---

## Scope

- Refactor `examples/dev_loop/server_dev.py::_on_startup` (:883-1098): build the
  base runtime via `build_dev_flow_runtime()`, then rebuild `app["flow"]` /
  `app["runner"]` **only if** console overrides differ (model plan, judge panel,
  research MCP servers), reusing `runtime.dev_loop_flow_kwargs` as the base dict.
- Keep every `app[...]` key the console publishes today (`redis`, `model_plan`,
  `wiki_search`, `jira_toolkit`, `flow`, `runner`, `codereview_agent_key`,
  `review_pair_active`, `development_pool_max`, `require_plan_approval`,
  `flow_tasks`, `dev_loop_runner`).
- Extend `packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py` with a
  parity test: the key set passed to `build_dev_flow` by the console equals the
  key set in `DevFlowRuntime.dev_loop_flow_kwargs` ∪ {console-only keys}.

**NOT in scope**: changing console behaviour (judge panel stays its default QA
gate; the UI's `/api/config` payload is unchanged); `examples/dev_loop/server.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/server_dev.py` | MODIFY | `_on_startup` delegates base wiring to `build_dev_flow_runtime()` |
| `packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py` | MODIFY | Add `test_on_startup_kwargs_parity_with_package_builder` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli.devloop.bootstrap import build_dev_flow_runtime, DevFlowRuntime   # TASK-3197 (verify it landed: grep -n "def build_dev_flow_runtime" packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py)
from parrot.flows.dev_flow.flow import build_dev_flow                              # verified: examples/dev_loop/server_dev.py:63
from parrot.flows.dev_flow.runner import DevFlowRunner                             # verified: server_dev.py:72
from parrot.flows.dev_flow.model_plan import resolve_model_plan                    # verified: server_dev.py:64-70
```

### Existing Signatures to Use
```python
# examples/dev_loop/server_dev.py (example script; imports sibling modules `llm_catalog`, `mcp_wiring`, `server as ops_server` at :40-42)
async def _on_startup(app: web.Application) -> None:                        # line 883 (1 occurrence)
#   app["redis"] = aioredis.from_url(redis_url, decode_responses=True)     # line 890
#   ClaudeCodeDispatcher(...)                                               # line 892-896
#   development backend cascade (ops_server._DEVELOPMENT_AGENT_MAX_CONCURRENT_ENV)   # lines 898-928
#   ops_server._resolve_codereview_dispatcher(...) → codereview_agent_key  # line 939-943
#   use_review_pair = mcp_wiring._config_flag("DEV_FLOW_USE_REVIEW_PAIR", False)   # line 947
#   qa_review_dispatcher = ops_server._build_judge_panel_dispatcher(redis_url=redis_url)   # line 955
#   model_plan = _console_default_model_plan(); app["model_plan"] = model_plan   # lines 989-990
#   research_mcp_servers/tools via mcp_wiring.build_research_mcp(...)       # lines 1011-1013
#   dev_loop_flow_kwargs = {...}                                             # lines 1036-1060
#   app["flow"] = build_dev_flow(**dev_loop_flow_kwargs)                    # line 1061 (1 occurrence)
#   runner = DevFlowRunner(app["flow"], ..., dev_loop_flow_kwargs=dev_loop_flow_kwargs)   # lines 1062-1077
#   app["runner"] = runner ... app["dev_loop_runner"] = runner              # lines 1079-1091

# packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py
#   loads server_dev via importlib.util (line 14) with fixtures `server_dev`, `make_client`; stubs `_StubFlow` (:43), `_GateFlow` (:57)
#   existing tests: test_route_inventory (:491), test_no_bug_brief_builder (:547)

# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py (after TASK-3197)
@dataclass class DevFlowRuntime: runner; flow; dispatcher; dev_loop_flow_kwargs: Dict[str, Any]; jira_toolkit; redis_url; model_plan; graph_memory
async def build_dev_flow_runtime(*, console=None) -> DevFlowRuntime   # preflight(topology="dev_flow") inside; SystemExit(1) on failure
```

### Does NOT Exist
- ~~`build_dev_flow_runtime(overrides=...)`~~ — the builder takes no override kwargs (TASK-3197 signature is fixed); apply overrides by copying `runtime.dev_loop_flow_kwargs` and rebuilding `build_dev_flow(**merged)` in the console.
- ~~a package-level judge-panel builder~~ — `_build_judge_panel_dispatcher` stays in `examples/dev_loop/server.py:580` (spec §8 Q5); the console keeps calling it through `ops_server`.
- ~~`parrot.flows.dev_flow.bootstrap`~~ — does not exist.
- ~~`server_dev.py` importable as `examples.dev_loop.server_dev`~~ — the test loads it via `importlib.util` (test_server_dev.py:14); keep that.

---

## Implementation Notes

### Pattern to Follow
```python
# In _on_startup: base runtime from the package, then console-only overrides
runtime = await build_dev_flow_runtime()
kwargs = dict(runtime.dev_loop_flow_kwargs)
kwargs.update({"model_plan": model_plan, "codereview_dispatcher": qa_review_dispatcher,
               "research_mcp_servers": extra_mcp_servers or None, "research_mcp_tools": extra_mcp_tools or None,
               "name": "dev-flow-console"})
app["flow"] = build_dev_flow(**kwargs)
runner = DevFlowRunner(app["flow"], dispatcher=runtime.dispatcher, ..., dev_loop_flow_kwargs=kwargs)
```

### Key Constraints
- `build_dev_flow_runtime()` runs `preflight(topology="dev_flow")` and raises `SystemExit(1)` when it fails; the console previously did no preflight — catch `SystemExit` and re-raise as `RuntimeError` with the hint so aiohttp startup logs it (do not exit the process silently).
- Preserve the console's judge-panel default and `DEV_FLOW_USE_REVIEW_PAIR` switch exactly (lines 947-955).
- The existing `test_server_dev.py` suite must stay green: the fixtures patch heavy builders; extend the patch list to include `parrot.cli.devloop.bootstrap.build_dev_flow_runtime` returning a stub `DevFlowRuntime`.

### References in Codebase
- `examples/dev_loop/server_dev.py:883-1098` — current wiring
- `packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py:1-130` — fixtures to extend

---

## Implementation Blueprint

### Steps (in order)
1. Read `_on_startup` end-to-end and list which values are console-only — *why*: those are the only things that may differ from the package builder.
2. Replace the base wiring with `build_dev_flow_runtime()` + override merge — *why*: one source of truth (S2).
3. Extend the test fixture patches and add the parity test — *why*: Known Risk "drift" mitigation.
4. Run `pytest packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py -q`.

### `examples/dev_loop/server_dev.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'app\["flow"\] = build_dev_flow(\*\*dev_loop_flow_kwargs)' examples/dev_loop/server_dev.py)
# REPLACE the block from `    dev_loop_flow_kwargs: dict[str, Any] = {` (line 1036) through `    )` closing DevFlowRunner(...) (line 1077) with:
    from parrot.cli.devloop.bootstrap import build_dev_flow_runtime  # noqa: PLC0415

    try:
        runtime = await build_dev_flow_runtime()
    except SystemExit as exc:  # preflight failed — surface it, never exit the console silently
        raise RuntimeError(f"dev-flow preflight failed (exit {exc.code}); see the checks above") from exc
    dev_loop_flow_kwargs: dict[str, Any] = dict(runtime.dev_loop_flow_kwargs)
    dev_loop_flow_kwargs.update(
        {
            # console-only overrides (everything else comes from the package builder)
            "model_plan": model_plan,
            "codereview_dispatcher": qa_review_dispatcher,
            "research_mcp_servers": extra_mcp_servers or None,
            "research_mcp_tools": extra_mcp_tools or None,
            "name": "dev-flow-console",
        }
    )
    app["flow"] = build_dev_flow(**dev_loop_flow_kwargs)
    runner = DevFlowRunner(
        app["flow"],
        dispatcher=runtime.dispatcher,
        jira_toolkit=dev_loop_flow_kwargs["jira_toolkit"],
        git_toolkit=dev_loop_flow_kwargs["git_toolkit"],
        wiki_toolkit=dev_loop_flow_kwargs["wiki_toolkit"],
        redis_url=redis_url,
        codereview_dispatcher=qa_review_dispatcher,
        graph_memory=dev_loop_flow_kwargs["graph_memory"],
        checkpoint_store=None,
        dev_loop_flow_kwargs=dev_loop_flow_kwargs,
    )
    # FILL IN: delete the now-redundant local construction of dispatcher/jira/git/wiki toolkits, graph_memory and wiki_search
    # above (lines 892-896, 1002-1004, 1020-1023) ONLY where the value is no longer referenced by app[...] keys — bounded by
    # "every app[...] key the console publishes today is preserved" (app["wiki_search"], app["jira_toolkit"] must still be set:
    # take them from dev_loop_flow_kwargs)
```
**Why**: the package builder owns the base key set; the five overrides are exactly the values the console computes itself.

### `packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py` (MODIFY — append)
```python
# APPEND at end of file (verified: last test is test_no_bug_brief_builder at line 547)
def test_on_startup_kwargs_parity_with_package_builder(server_dev):
    """The console passes the package builder's key set (plus its console-only overrides) to build_dev_flow."""
    import inspect

    src = inspect.getsource(server_dev._on_startup)
    # FILL IN: drive _on_startup with build_dev_flow_runtime patched to return a stub DevFlowRuntime whose
    # dev_loop_flow_kwargs has a sentinel key set, capture build_dev_flow.call_args.kwargs, and assert
    # set(captured) == set(stub_kwargs) and captured["name"] == "dev-flow-console" — bounded by Known Risk "drift"
    assert "build_dev_flow_runtime" in src
```
**Why**: guards the refactor; the source assertion is the minimum, the captured-kwargs assertion is the real check.

### FILL IN checklist
- [ ] `server_dev.py::_on_startup` — remove redundant local construction while keeping every `app[...]` key; bounded by "console behaviour unchanged"
- [ ] `test_server_dev.py::test_on_startup_kwargs_parity_with_package_builder` — captured kwargs equality; bounded by Known Risk "drift"
- [ ] fixture patch list — add `parrot.cli.devloop.bootstrap.build_dev_flow_runtime`; bounded by AC19

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow -q`
- [ ] No linting errors: `ruff check examples/dev_loop/server_dev.py`
- [ ] `python examples/dev_loop/server_dev.py --help` (or import via the test loader) still works
- [ ] Spec AC19 (console behaviour unchanged) and §7 Known Risk "drift" mitigated

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_server_dev.py — see blueprint block above
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3199-dev-console-delegates-to-runtime-builder.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
