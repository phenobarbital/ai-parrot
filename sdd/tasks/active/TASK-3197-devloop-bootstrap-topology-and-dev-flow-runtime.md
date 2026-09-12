# TASK-3197: `bootstrap.py` — topology-aware preflight, `build_dev_flow_runtime()` and `load_headless_brief()`

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (design research S2/S3). The dev-flow topology (FEAT-412) is
wired only inside `examples/dev_loop/server_dev.py::_on_startup`, which imports
sibling example modules and is therefore not importable from the package. The
headless child (TASK-3198) needs a library-level builder. Today's `preflight()`
also treats Jira as a hard check and only verifies that a Redis URL *exists*,
which would refuse feature runs (Jira is optional in the dev-flow) and let a
dead Redis pass. This task adds the topology parameter, the real Redis PING,
`DevFlowRuntime` + `build_dev_flow_runtime()` with the decided defaults, and
the kind-routing brief loader.

---

## Scope

- `preflight(*, console=None, topology: Literal["dev_loop","dev_flow"] = "dev_loop")`:
  for `dev_flow` the `jira` check is advisory (`passed=True` + hint when
  unconfigured); both topologies PING Redis (`redis.asyncio.from_url(...).ping()`
  with a 3 s timeout) and fail the `redis` check when it does not answer.
- `DevFlowRuntime` dataclass (runner, flow, dispatcher, `dev_loop_flow_kwargs`,
  jira_toolkit, redis_url, model_plan, graph_memory).
- `build_dev_flow_runtime(*, console=None) -> DevFlowRuntime` with the decided
  defaults (spec §3 M2): `codereview_dispatcher=None` (model-plan review pair),
  `model_plan=resolve_model_plan(None)`, `development_dispatcher_builder=
  functools.partial(build_dispatcher, redis_url=…, max_concurrent=…, stream_ttl_seconds=…)`,
  `development_pool_max=resolve_pool_max(conf.config.get)`, graph memory + wiki
  search, git/wiki toolkits from two new private helpers, `research_mcp_servers/tools=None`,
  `name="dev-flow-headless"`; `DevFlowRunner(flow, ..., dev_loop_flow_kwargs=kwargs)`.
- `_build_git_toolkit()` / `_build_wiki_toolkit()` mirroring `_build_jira_toolkit`
  (return `None` + warning when unavailable).
- `load_headless_brief(path)`: YAML/JSON → `kind` in `{"new_feature","enhancement"}` ⇒
  `parse_dev_brief`; otherwise `parse_brief`; unknown/absent kind ⇒ `ValueError`.
- Tests in `packages/ai-parrot/tests/cli/devloop/test_bootstrap_dev_flow.py`.

**NOT in scope**: the headless CLI mode (TASK-3198); the example console
refactor (TASK-3199); any change to `build_runtime()` behaviour; re-homing the
judge-panel helper (spec §8 Q5 resolved: review pair).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` | MODIFY | preflight topology + Redis PING; `DevFlowRuntime`; `build_dev_flow_runtime`; helpers; `load_headless_brief` |
| `packages/ai-parrot/tests/cli/devloop/test_bootstrap_dev_flow.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# already at the top of bootstrap.py (verified: bootstrap.py:11-21)
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from rich.console import Console
# deferred (inside function bodies, `# noqa: PLC0415`), all verified:
from parrot import conf                                                  # bootstrap.py:262
from parrot.flows.dev_flow.flow import build_dev_flow                    # verified: dev_flow/flow.py:86
from parrot.flows.dev_flow.runner import DevFlowRunner                   # verified: dev_flow/runner.py:41
from parrot.flows.dev_flow.model_plan import resolve_model_plan           # verified: dev_flow/model_plan.py:334
from parrot.flows.dev_flow.models import parse_dev_brief                 # verified: dev_flow/models.py:131
from parrot.flows.dev_loop.models import parse_brief                     # verified: dev_loop/models/base.py:1123 (re-exported by models/__init__)
from parrot.flows.dev_loop.agent_builder import build_dispatcher, resolve_pool_max  # verified: bootstrap.py:268 (build_dispatcher), examples/dev_loop/server.py:159 (resolve_pool_max)
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory        # verified: bootstrap.py:269
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch          # verified: bootstrap.py:271
from parrot.flows.dev_loop.models import DevAgentSpec                    # verified: bootstrap.py:270
import redis.asyncio as aioredis                                         # verified: examples/dev_loop/server_dev.py:59 (core dep via dev_loop streaming)
from parrot_tools.gittoolkit import GitToolkit                           # verified: examples/dev_loop/server.py:170 (import site)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
class PreflightCheck(BaseModel): name: str; passed: bool; hint: str = ""        # line 55
class PreflightResult(BaseModel): ok: bool; checks: List[PreflightCheck]        # line 63
@dataclass class DevLoopRuntime: runner; flow; dispatcher; jira_toolkit=None; redis_url=""; reporter=""; escalation_assignee=""; graph_memory=None   # line 71
async def preflight(*, console: Optional[Console] = None) -> PreflightResult:  # line 84
#   redis check = URL presence only                                            # lines 92-105
#   jira check appended: checks.append(PreflightCheck(name="jira", passed=jira_ok, hint=jira_hint))   # line 202
#   result = PreflightResult(ok=all(c.passed for c in checks), checks=checks)   # line 223
def _render_preflight(console: Console, result: PreflightResult) -> None       # line 231
async def build_runtime(*, console: Optional[Console] = None) -> DevLoopRuntime  # line 249 — reference wiring: build_dispatcher(DevAgentSpec(agent=backend_id), redis_url=..., max_concurrent=conf.config.get("CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3), stream_ttl_seconds=conf.config.get("FLOW_STREAM_TTL_SECONDS", fallback=604800))  # lines 279-291
def _build_jira_toolkit() -> Any                                                # line 414 — pattern for the new helpers
def _build_log_toolkits() -> Dict[str, Any]                                     # line 430 — last function in the file (file is 447 lines)

# packages/ai-parrot/src/parrot/flows/dev_flow/flow.py
def build_dev_flow(*, dispatcher, redis_url, jira_toolkit=None, git_toolkit=None, wiki_toolkit=None, codereview_dispatcher=None,
                   development_dispatcher_builder=None, development_pool_max: int = 4, graph_memory=None, wiki_search=None,
                   skip_qa=False, require_plan_approval=False, ideation_max_rounds=None, model_plan=None, research_coordinator=None,
                   research_mcp_servers=None, research_mcp_tools=None, name="dev-flow", publish_flow_events=True, lifecycle_events=True,
                   checkpoint=False, checkpoint_required=False, checkpoint_store=None, flow_id=None) -> AgentsFlow   # line 86

# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner)   # line 41 — inherits __init__(flow, *, dispatcher, jira_toolkit, git_toolkit, wiki_toolkit, redis_url,
#     codereview_dispatcher, graph_memory, checkpoint_store, dev_loop_flow_kwargs)  (dev_loop/runner.py:417)

# Reference wiring to mirror (example only — NOT importable): examples/dev_loop/server_dev.py:1036-1077
#   dev_loop_flow_kwargs keys: dispatcher, redis_url, jira_toolkit, git_toolkit, wiki_toolkit, codereview_dispatcher,
#   development_dispatcher_builder, development_pool_max, graph_memory, wiki_search, skip_qa, require_plan_approval,
#   model_plan, research_mcp_servers, research_mcp_tools, name
```

### Does NOT Exist
- ~~`bootstrap.build_dev_flow_runtime()`~~, ~~`bootstrap.DevFlowRuntime`~~, ~~`bootstrap.load_headless_brief()`~~, ~~`bootstrap._build_git_toolkit()` / `_build_wiki_toolkit()`~~ — created by THIS task.
- ~~`preflight(topology=...)`~~ — no such parameter today (line 84).
- ~~`examples.dev_loop.server._build_judge_panel_dispatcher` importable from the package~~ — example-only (server.py:580); do NOT import anything from `examples/`.
- ~~`parrot.flows.dev_flow.bootstrap`~~ — does not exist; the builder lives in `parrot/cli/devloop/bootstrap.py` (spec §8 Q6).
- ~~`DevLoopConsole._load_brief` handling `new_feature`/`enhancement`~~ — it calls `parse_brief` only (console.py:687); do not reuse it.
- ~~`conf.REDIS_URL` guaranteed reachable~~ — preflight must PING.

---

## Implementation Notes

### Pattern to Follow
```python
# bootstrap.py:414 — the helper shape for _build_git_toolkit / _build_wiki_toolkit
def _build_jira_toolkit() -> Any:
    try:
        from parrot import conf  # noqa: PLC0415
        from parrot_tools.jiratoolkit import JiraToolkit  # noqa: PLC0415
        return JiraToolkit(...)
    except Exception:
        logger.warning("JiraToolkit not available; Jira features disabled.", exc_info=True)
        return None
```

### Key Constraints
- `preflight()` with no `topology` argument must stay byte-identical in outcome for the existing tests (`tests/cli/devloop/test_bootstrap.py`), except the Redis PING — those tests patch `conf.REDIS_URL`; patch `aioredis.from_url` in them or in the new tests as needed and keep the old suite green (AC19).
- The Redis PING is wrapped in `asyncio.wait_for(client.ping(), timeout=3.0)` and the client is closed in `finally`.
- `build_dev_flow_runtime` never imports from `examples/`; mirror `server_dev.py:1036-1077` key set exactly (TASK-3199 adds a parity test).
- Heavy imports stay inside function bodies (`# noqa: PLC0415`) so `parrot devloop --help` stays fast.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py:249-376` — `build_runtime` (dev-loop wiring to mirror)
- `examples/dev_loop/server_dev.py:883-1098` — dev-flow wiring to port
- `packages/ai-parrot/tests/cli/devloop/test_bootstrap.py` — test patterns (`patch.object(bootstrap_mod, ...)`)

---

## Implementation Blueprint

### Steps (in order)
1. Add the `topology` parameter and the Redis PING to `preflight` — *why*: S3 verified that Jira is a hard check and Redis is only URL-checked.
2. Add `DevFlowRuntime` right after `DevLoopRuntime` — *why*: same shape, one import site for both topologies.
3. Add `_build_git_toolkit` / `_build_wiki_toolkit` next to `_build_jira_toolkit` — *why*: the example helpers are not importable.
4. Add `build_dev_flow_runtime` after `build_runtime` — *why*: the headless child (TASK-3198) calls it for `DevRequestBrief` runs.
5. Add `load_headless_brief` at the end of the module — *why*: the CLI loader only knows `parse_brief`.
6. Write tests; run `pytest packages/ai-parrot/tests/cli/devloop -q` — *why*: AC22 + AC19.

### `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` (MODIFY — preflight)
```python
# occurrences: 1 (verified: grep -c '^async def preflight(\*, console: Optional\[Console\] = None) -> PreflightResult:' packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py)
# REPLACE the signature line `async def preflight(*, console: Optional[Console] = None) -> PreflightResult:` (verified: bootstrap.py:84) with:
Topology = Literal["dev_loop", "dev_flow"]   # add `Literal` to the typing import on line 17


async def preflight(*, console: Optional[Console] = None, topology: Topology = "dev_loop") -> PreflightResult:
    """Run preflight checks and render results.

    Never raises — returns a PreflightResult with ``ok=False`` on failure.
    FEAT-555 (S3): ``topology="dev_flow"`` makes the ``jira`` check advisory;
    both topologies PING Redis (3 s) instead of only checking the URL.
    """
```
```python
# occurrences: 1 (verified: grep -c '    checks.append(PreflightCheck(name="jira", passed=jira_ok, hint=jira_hint))' packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py)
# REPLACE line `    checks.append(PreflightCheck(name="jira", passed=jira_ok, hint=jira_hint))` (verified: bootstrap.py:202) with:
    if topology == "dev_flow" and not jira_ok:
        jira_hint = f"(advisory for dev-flow) {jira_hint}"
        jira_ok = True
    checks.append(PreflightCheck(name="jira", passed=jira_ok, hint=jira_hint))
```
In the Redis block (bootstrap.py:92-105) replace `checks.append(PreflightCheck(name="redis", passed=True))` with a call to a new helper `await _redis_ping(redis_url)` returning `(passed, hint)`:
```python
async def _redis_ping(redis_url: str) -> Tuple[bool, str]:
    """PING ``redis_url`` with a 3 s timeout; (True, "") on PONG, (False, hint) otherwise. Never raises."""
    import asyncio  # noqa: PLC0415
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415
        client = aioredis.from_url(redis_url, decode_responses=True)
        try:
            await asyncio.wait_for(client.ping(), timeout=3.0)
            return True, ""
        finally:
            # FILL IN: close the client (aclose()/close() depending on redis version) — bounded by "never raises"
            pass
    except Exception as exc:  # noqa: BLE001
        return False, f"Redis at {redis_url} did not answer PING: {exc}"
```
**Why**: AC22 — a dead Redis must fail fast in the child, before the handshake.

### `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` (MODIFY — runtime builder)
```python
# occurrences: 1 (verified: grep -c '^def _build_log_toolkits() -> Dict\[str, Any\]:' packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py)
# BEFORE — insert above `def _build_log_toolkits() -> Dict[str, Any]:` (verified: bootstrap.py:430)
@dataclass
class DevFlowRuntime:
    """Wired dev-flow runtime (FEAT-412 topology) — mirror of DevLoopRuntime."""

    runner: Any  # DevFlowRunner
    flow: Any  # AgentsFlow
    dispatcher: Any
    dev_loop_flow_kwargs: Dict[str, Any] = field(default_factory=dict)
    jira_toolkit: Any = None
    redis_url: str = ""
    model_plan: Any = None
    graph_memory: Any = None


def _build_git_toolkit() -> Any:
    """Build the GitToolkit; ``None`` (with a warning) when unavailable."""
    try:
        from parrot_tools.gittoolkit import GitToolkit  # noqa: PLC0415
        # FILL IN: constructor kwargs — mirror examples/dev_loop/server.py:642 _build_git_toolkit (read it), bounded by "None when unconfigured"
        return GitToolkit()
    except Exception:
        logger.warning("GitToolkit not available; git features disabled.", exc_info=True)
        return None


def _build_wiki_toolkit() -> Any:
    """Build the wiki toolkit; ``None`` when wikitoolkit is not installed."""
    # FILL IN: mirror examples/dev_loop/server.py:726 _build_wiki_toolkit (read it); return None on ImportError
    return None


async def build_dev_flow_runtime(*, console: Optional[Console] = None) -> DevFlowRuntime:
    """Preflight (dev_flow), then wire build_dev_flow + DevFlowRunner with the FEAT-555 decided defaults.

    Raises:
        SystemExit: If preflight fails (same contract as build_runtime).
    """
    import functools  # noqa: PLC0415

    result = await preflight(console=console or Console(), topology="dev_flow")
    if not result.ok:
        raise SystemExit(1)
    from parrot import conf  # noqa: PLC0415
    from parrot.flows.dev_flow.flow import build_dev_flow  # noqa: PLC0415
    from parrot.flows.dev_flow.model_plan import resolve_model_plan  # noqa: PLC0415
    from parrot.flows.dev_flow.runner import DevFlowRunner  # noqa: PLC0415
    from parrot.flows.dev_loop.agent_builder import build_dispatcher, resolve_pool_max  # noqa: PLC0415
    from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory  # noqa: PLC0415
    from parrot.flows.dev_loop.models import DevAgentSpec  # noqa: PLC0415
    from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch  # noqa: PLC0415

    redis_url = conf.config.get("REDIS_URL", fallback="redis://localhost:6379/0")
    backend_id = str(conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code") or "claude-code").strip().lower()
    max_concurrent = conf.config.get("CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3)
    stream_ttl = conf.config.get("FLOW_STREAM_TTL_SECONDS", fallback=604800)
    dispatcher, _profile = build_dispatcher(
        DevAgentSpec(agent=backend_id), redis_url=redis_url, max_concurrent=max_concurrent, stream_ttl_seconds=stream_ttl
    )
    builder = functools.partial(build_dispatcher, redis_url=redis_url, max_concurrent=max_concurrent, stream_ttl_seconds=stream_ttl)
    jira_toolkit = _build_jira_toolkit()
    graph_memory = await DevLoopGraphMemory.from_config()
    model_plan = resolve_model_plan(None)
    dev_loop_flow_kwargs: Dict[str, Any] = {
        "dispatcher": dispatcher, "redis_url": redis_url, "jira_toolkit": jira_toolkit,
        "git_toolkit": _build_git_toolkit(), "wiki_toolkit": _build_wiki_toolkit(),
        "codereview_dispatcher": None,  # decided: model-plan review pair (spec §8 Q5)
        "development_dispatcher_builder": builder, "development_pool_max": resolve_pool_max(conf.config.get),
        "graph_memory": graph_memory, "wiki_search": DevLoopWikiSearch.from_project(),
        "skip_qa": bool(getattr(conf, "DEV_LOOP_SKIP_QA", False)),
        "require_plan_approval": bool(getattr(conf, "DEV_LOOP_REQUIRE_PLAN_APPROVAL", False)),
        "model_plan": model_plan, "research_mcp_servers": None, "research_mcp_tools": None, "name": "dev-flow-headless",
    }
    flow = build_dev_flow(**dev_loop_flow_kwargs)
    runner = DevFlowRunner(
        flow, dispatcher=dispatcher, jira_toolkit=jira_toolkit, git_toolkit=dev_loop_flow_kwargs["git_toolkit"],
        wiki_toolkit=dev_loop_flow_kwargs["wiki_toolkit"], redis_url=redis_url, codereview_dispatcher=None,
        graph_memory=graph_memory, checkpoint_store=None, dev_loop_flow_kwargs=dev_loop_flow_kwargs,
    )
    return DevFlowRuntime(runner=runner, flow=flow, dispatcher=dispatcher, dev_loop_flow_kwargs=dev_loop_flow_kwargs,
                          jira_toolkit=jira_toolkit, redis_url=redis_url, model_plan=model_plan, graph_memory=graph_memory)
```
**Why this shape**: the key set mirrors `server_dev.py:1036-1060` minus the console-only MCP extras; `codereview_dispatcher=None` is the resolved Q5 decision; `dev_loop_flow_kwargs` is captured for `DevFlowRunner`'s recovery path (S2).

### `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` (MODIFY — brief loader, append at end of file)
```python
# APPEND after the last line of the module (verified: bootstrap.py ends at line 447 with `    return toolkits`)
def load_headless_brief(path: str) -> Any:
    """Load a YAML/JSON brief, routing on ``kind`` (FEAT-555 S1).

    ``new_feature``/``enhancement`` ⇒ :func:`parse_dev_brief` (DevRequestBrief); ``feature``/``bug`` or absent ⇒
    :func:`parse_brief` (FeatureBrief / WorkBrief).

    Raises:
        FileNotFoundError: ``path`` is not a file.
        ValueError: Unknown ``kind``.
    """
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    from parrot.flows.dev_flow.models import parse_dev_brief  # noqa: PLC0415
    from parrot.flows.dev_loop.models import parse_brief  # noqa: PLC0415

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    text = p.read_text(encoding="utf-8")
    # FILL IN: YAML vs JSON by suffix (.yaml/.yml ⇒ yaml.safe_load, else json.loads) — bounded by "same formats DevLoopConsole._read_brief_data accepts"
    data = json.loads(text)
    kind = data.get("kind")
    if kind in ("new_feature", "enhancement"):
        return parse_dev_brief(data)
    if kind in ("feature", "bug", None):
        return parse_brief(data)
    raise ValueError(f"unknown brief kind {kind!r}; expected bug, feature, enhancement or new_feature")
```
**Why**: spec M2 skeleton; `enhancement` is accepted headless by decision (Q4).

### `packages/ai-parrot/tests/cli/devloop/test_bootstrap_dev_flow.py` (CREATE)
```python
"""FEAT-555 TASK-3197 — topology-aware preflight, build_dev_flow_runtime, load_headless_brief."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import parrot.cli.devloop.bootstrap as bootstrap_mod
from parrot.cli.devloop.bootstrap import DevFlowRuntime, load_headless_brief, preflight  # verified after this task


@pytest.mark.asyncio
async def test_preflight_dev_flow_jira_advisory(monkeypatch):
    # FILL IN: patch conf so JIRA_* are empty and REDIS_URL set; patch bootstrap_mod._redis_ping → (True, "");
    # assert preflight(topology="dev_flow").ok is True and the jira check hint starts with "(advisory" — bounded by AC22
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_preflight_dev_loop_jira_hard():
    # FILL IN: same setup, topology="dev_loop" ⇒ ok False, jira check passed False — bounded by AC19 (old behaviour kept)
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_preflight_redis_ping_failure_fails_both():
    # FILL IN: patch bootstrap_mod._redis_ping → (False, "no PONG"); both topologies ok False — bounded by AC22
    pytest.skip("FILL IN")


@pytest.mark.asyncio
async def test_build_dev_flow_runtime_wiring():
    ok = bootstrap_mod.PreflightResult(ok=True, checks=[])
    with patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok)), \
         patch("parrot.flows.dev_flow.flow.build_dev_flow") as build, \
         patch("parrot.flows.dev_flow.runner.DevFlowRunner") as runner_cls, \
         patch("parrot.flows.dev_loop.agent_builder.build_dispatcher", return_value=(MagicMock(), MagicMock())), \
         patch("parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config", AsyncMock(return_value=None)):
        rt = await bootstrap_mod.build_dev_flow_runtime()
    assert isinstance(rt, DevFlowRuntime)
    kwargs = build.call_args.kwargs
    assert kwargs["codereview_dispatcher"] is None and kwargs["name"] == "dev-flow-headless"
    assert runner_cls.call_args.kwargs["dev_loop_flow_kwargs"] is rt.dev_loop_flow_kwargs


def test_load_headless_brief_routes_on_kind(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"kind": "new_feature", "title": "t", "description": "d"}))
    assert type(load_headless_brief(str(f))).__name__ == "DevRequestBrief"
    f.write_text(json.dumps({"kind": "nope"}))
    with pytest.raises(ValueError):
        load_headless_brief(str(f))
    # FILL IN: enhancement ⇒ DevRequestBrief; feature ⇒ FeatureBrief (needs an existing document_path); bug ⇒ WorkBrief — bounded by spec M2
```
**Why this shape**: rows `test_build_dev_flow_runtime_wiring`, `test_load_headless_brief_routes_on_kind`, `test_preflight_topology_dev_flow_jira_advisory` from spec §4.

### FILL IN checklist
- [ ] `bootstrap.py::_redis_ping` — client close call; bounded by "never raises"
- [ ] `bootstrap.py::_build_git_toolkit` / `_build_wiki_toolkit` — constructor kwargs mirrored from `examples/dev_loop/server.py:642/726`; bounded by "None when unconfigured"
- [ ] `bootstrap.py::load_headless_brief` — YAML/JSON detection; bounded by `DevLoopConsole._read_brief_data` formats
- [ ] tests — three preflight tests + loader kinds; bounded by AC22/AC19

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/devloop -q` (old `test_bootstrap.py` included)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/devloop`
- [ ] Imports work: `from parrot.cli.devloop.bootstrap import build_dev_flow_runtime, load_headless_brief, DevFlowRuntime`
- [ ] Spec AC5 (no `examples/` import), AC22 (preflight topology + PING), AC19

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_bootstrap_dev_flow.py — see blueprint block above
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
7. **Move this file** to `sdd/tasks/completed/TASK-3197-devloop-bootstrap-topology-and-dev-flow-runtime.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
