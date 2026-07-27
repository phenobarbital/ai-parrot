# TASK-1894: Devloop Package + Embedded Runtime Bootstrap & Preflight

**Feature**: FEAT-374 — `parrot devloop`: Interactive CLI Console for Dev-Loop Flows
**Spec**: `sdd/specs/devloop-cli-console.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / Goal G3. Embedded execution needs the real dev-loop wired
in-process — dispatcher, Jira toolkit, log toolkits, flow, runner — behind a
**preflight** that fails fast with actionable hints when real-mode
prerequisites (Redis, `claude` CLI, Jira creds, worktree base path) are
missing. Mirrors the canonical wiring in `examples/dev_loop/quickstart.py`.

---

## Scope

- Create the `packages/ai-parrot/src/parrot/cli/devloop/` package with a
  **minimal placeholder** `__init__.py` (docstring only — TASK-1897 fills in
  the click surface).
- Implement `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py`:
  - `PreflightCheck(name, passed, hint)` and
    `PreflightResult(ok, checks)` pydantic models (spec §2 Data Models).
  - `async def preflight() -> PreflightResult` — checks:
    1. `redis`: `REDIS_URL` resolvable + PING (async redis client,
       short timeout).
    2. `claude-cli`: `shutil.which("claude")`.
    3. `jira`: `import jira` succeeds AND Jira creds present in conf
       (`JIRA_INSTANCE`/`JIRA_USERNAME`/`JIRA_API_TOKEN` — verify exact
       key names against `examples/dev_loop/quickstart.py` `_build_jira_toolkit`
       and `parrot/conf.py` before hardcoding).
    4. `worktree-base`: `WORKTREE_BASE_PATH` configured.
    Each failed check carries a one-line actionable `hint`.
  - `class DevLoopRuntime` (simple holder: `runner`, `flow`, `dispatcher`,
    `jira_toolkit`, `redis_url`).
  - `async def build_runtime() -> DevLoopRuntime` — construct
    `ClaudeCodeDispatcher`, Jira toolkit, log toolkits,
    `build_dev_loop_flow(...)`, then
    `DevLoopRunner(flow, dispatcher=..., jira_toolkit=..., git_toolkit=...,
    redis_url=..., codereview_dispatcher=...)` — **revision deps included**
    so `run_revision` works (spec G5). Follow
    `examples/dev_loop/quickstart.py:168-221` for kwarg sources
    (`conf.config.get(...)` fallbacks).
  - Also port `_resolve_identity`-style reporter/escalation defaults helper
    (`async def default_identities(jira_toolkit) -> tuple[str, str]`) for
    TASK-1896's wizard seeding.
- All heavy imports (`parrot.conf`, dev_loop modules) at function level, NOT
  module level (spec §7 "navconfig import cost").
- Unit tests: `packages/ai-parrot/tests/cli/devloop/test_bootstrap.py`
  (mock `shutil.which`, redis client, conf) — no real services.

**NOT in scope**: console/renderer (TASK-1895/1896); click commands
(TASK-1897); any change under `parrot/flows/dev_loop/` (spec G7 — forbidden).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` | CREATE | placeholder docstring module |
| `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` | CREATE | preflight + build_runtime + DevLoopRuntime |
| `packages/ai-parrot/tests/cli/devloop/__init__.py` | CREATE | test package |
| `packages/ai-parrot/tests/cli/devloop/test_bootstrap.py` | CREATE | unit tests (all deps mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop import (        # flows/dev_loop/__init__.py:26-27
    DevLoopRunner, build_dev_loop_flow,
)
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher  # dispatcher.py
from parrot import conf                    # navconfig-backed settings
import shutil                              # stdlib — shutil.which("claude")
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:165
class DevLoopRunner:
    def __init__(self, flow: AgentsFlow, *,
                 max_concurrent_runs: Optional[int] = None,
                 dispatcher: Optional[Any] = None,
                 jira_toolkit: Optional[Any] = None,
                 git_toolkit: Optional[Any] = None,
                 redis_url: Optional[str] = None,
                 codereview_dispatcher: Optional[Any] = None) -> None
    # run_revision RAISES a clear error when dispatcher/jira/git/redis
    # kwargs were not provided at __init__ (runner.py:186-192 comment).

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:189
def build_dev_loop_flow(*, dispatcher: ClaudeCodeDispatcher,
    jira_toolkit: Any, log_toolkits: Dict[str, Any], redis_url: str,
    name: str = "dev-loop", publish_flow_events: bool = True,
    lifecycle_events: bool = True, ..., git_toolkit=None,
    repos: Optional[list[RepoSpec]] = None, codereview_dispatcher=None,
    require_deployment_approval: bool = False) -> AgentsFlow

# examples/dev_loop/quickstart.py:168-181 — canonical dispatcher construction:
dispatcher = ClaudeCodeDispatcher(
    max_concurrent=conf.config.get("CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3),
    redis_url=redis_url,
    stream_ttl_seconds=conf.config.get("FLOW_STREAM_TTL_SECONDS", fallback=604800),
)
# quickstart.py:167 — redis_url = conf.config.get("REDIS_URL", fallback="redis://localhost:6379/0")
# quickstart.py:183-190 — build_dev_loop_flow(dispatcher=, jira_toolkit=,
#                          log_toolkits=_build_log_toolkits(), redis_url=, name=)
# quickstart.py:193-204 — identity fallback chain:
#   conf.FLOW_BOT_JIRA_ACCOUNT_ID → JIRA_REPORTER_ACCOUNT_ID / JIRA_ESCALATION_ACCOUNT_ID
```

### Does NOT Exist
- ~~`parrot.cli.devloop`~~ — created by THIS task (placeholder `__init__`).
- ~~`DevLoopRunner.preflight()` / `check_prerequisites()`~~ — no such
  method; preflight is new code in this task.
- ~~A core `build_runtime` helper~~ — wiring exists only in
  `examples/dev_loop/quickstart.py` and `examples/dev_loop/server.py`;
  this task productizes it.
- ~~`conf.REDIS_URL` as a guaranteed attribute~~ — use
  `conf.config.get("REDIS_URL", fallback=...)` like quickstart does.
- Do NOT modify anything under `parrot/flows/dev_loop/` (spec G7).

---

## Implementation Notes

### Pattern to Follow
- Copy the wiring order of `examples/dev_loop/quickstart.py::main`
  (dispatcher → jira toolkit → flow → runner), adding the revision-dep
  kwargs to `DevLoopRunner(...)`.
- Lazy imports inside functions (see `parrot/cli/__init__.py` LazyGroup
  rationale: `parrot devloop --help` must not boot navconfig).

### Key Constraints
- Async throughout; pydantic models for results; `logging.getLogger(__name__)`.
- Preflight NEVER raises on a failed check — it reports; the caller decides.
- Verify exact Jira conf key names by reading `_build_jira_toolkit` in
  `examples/dev_loop/quickstart.py` before implementing check 3.

### References in Codebase
- `examples/dev_loop/quickstart.py` — canonical embedded wiring.
- `examples/dev_loop/server.py` — same wiring, server-hosted variant.
- `examples/dev_loop/README.md` — "Prerequisites (real mode)" list.

---

## Acceptance Criteria

- [ ] `preflight()` reports pass/fail per check with hints; all-mocked tests
  cover each check failing and all passing.
- [ ] `build_runtime()` returns a `DevLoopRuntime` whose `DevLoopRunner` was
  constructed WITH dispatcher/jira_toolkit/git_toolkit/redis_url kwargs
  (assert via mock).
- [ ] No module-level import of `parrot.conf` or `parrot.flows.dev_loop` in
  `bootstrap.py`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/devloop/test_bootstrap.py -v`
- [ ] `ruff check` clean on new files.
- [ ] No files under `parrot/flows/dev_loop/` modified.

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_bootstrap.py
import pytest
from parrot.cli.devloop.bootstrap import preflight, build_runtime

async def test_preflight_reports_missing_claude(monkeypatch):
    """shutil.which -> None => claude-cli check fails with hint."""

async def test_preflight_redis_unreachable(monkeypatch):
    """PING raises => redis check fails, others still evaluated."""

async def test_preflight_all_green(monkeypatch):
    """All mocked OK => PreflightResult.ok is True."""

async def test_build_runtime_wires_revision_deps(monkeypatch):
    """DevLoopRunner receives dispatcher/jira/git/redis kwargs (mocked ctor)."""
```

---

## Agent Instructions

1. **Read the spec** (§2, §3 M2, §6, §7) at `sdd/specs/devloop-cli-console.spec.md`.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before coding (esp. quickstart line refs).
4. **Update status** in `sdd/tasks/index/devloop-cli-console.json` → `"in-progress"`.
5. **Implement** (TDD).
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`; **update index** → `"done"`.
8. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
