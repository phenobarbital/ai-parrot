---
type: Wiki Overview
title: 'TASK-1698: Factory Wiring + Server Bootstrap'
id: doc:sdd-tasks-completed-task-1698-factory-wiring-server-bootstrap-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (reuse existing dispatchers or create new ones as needed)
relates_to:
- concept: mod:parrot.flows.dev_loop.code_review
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
---

# TASK-1698: Factory Wiring + Server Bootstrap

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1694, TASK-1695, TASK-1696, TASK-1697
**Assigned-to**: unassigned

---

## Context

> This task implements Module 7 from the spec — threading the code review
> dispatcher through the factory chain (`build_dev_loop_node_factories` →
> `build_dev_loop_flow` → `_on_startup`) and adding the `DEV_LOOP_CODEREVIEW_AGENT`
> config var.

---

## Scope

- Add `DEV_LOOP_CODEREVIEW_AGENT` config var to `conf.py` (default: `"claude-code"`)
- Modify `build_dev_loop_node_factories()` in `factories.py`:
  - Add `codereview_dispatcher: Optional[AbstractCodeReviewDispatcher] = None` param
  - Pass it to `QANode(codereview_dispatcher=codereview_dispatcher)` in `qa_factory`
- Modify `build_dev_loop_flow()` in `flow.py`:
  - Add `codereview_dispatcher: Optional[Any] = None` param
  - Pass it through to `build_dev_loop_node_factories()`
- Modify `_on_startup()` in `server.py`:
  - Read `DEV_LOOP_CODEREVIEW_AGENT` env var
  - Create the corresponding development dispatcher instance for review
    (reuse existing dispatchers or create new ones as needed)
  - Call `CodeReviewDispatcherFactory.create(agent_name, dispatcher=...)` to
    instantiate the reviewer
  - Pass it to `build_dev_loop_flow(codereview_dispatcher=...)`
- Write integration-level tests for the wiring.

**NOT in scope**: ABC/factory definition (Task 1692), concrete reviewers (Tasks 1694–1696), QANode logic (Task 1697).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `DEV_LOOP_CODEREVIEW_AGENT` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` | MODIFY | Add `codereview_dispatcher` param |
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | Thread `codereview_dispatcher` through |
| `examples/dev_loop/server.py` | MODIFY | Wire `DEV_LOOP_CODEREVIEW_AGENT` |
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | MODIFY | Add wiring tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
    ClaudeCodeReviewDispatcher,      # TASK-1694
    CodexCodeReviewDispatcher,       # TASK-1695
    GeminiCodeReviewDispatcher,      # TASK-1696
)
from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,            # dispatcher.py:145
    CodexCodeDispatcher,             # dispatcher.py:859
    GeminiCodeDispatcher,            # dispatcher.py:1281
)
from parrot import conf                                            # conf.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/factories.py:40
def build_dev_loop_node_factories(
    *, dispatcher, jira_toolkit, redis_url,
    development_dispatcher=None, development_profile=None,
    git_toolkit=None, log_toolkits=None, repos=None,
) -> Dict[str, NodeFactory]: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/factories.py:105
def qa_factory(nd, deps, succs):
    return _with_graph(QANode(dispatcher=dispatcher, name=nd.id), deps, succs)

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:159
def build_dev_loop_flow(
    *, dispatcher: ClaudeCodeDispatcher, jira_toolkit, log_toolkits,
    redis_url, name="dev-loop", publish_flow_events=True,
    lifecycle_events=True, development_dispatcher=None,
    development_profile=None, git_toolkit=None, repos=None,
) -> AgentsFlow: ...

# examples/dev_loop/server.py:445
async def _on_startup(app):
    # ... creates dispatchers based on DEV_LOOP_DEVELOPMENT_AGENT
    # ... calls build_dev_loop_flow(dispatcher=..., development_dispatcher=..., ...)

# packages/ai-parrot/src/parrot/conf.py:899
DEV_LOOP_CODEREVIEW_MODEL: str = config.get(
    "DEV_LOOP_CODEREVIEW_MODEL", fallback="claude-sonnet-4-6"
)
```

### Does NOT Exist
- ~~`DEV_LOOP_CODEREVIEW_AGENT`~~ — config var does not exist yet; this task creates it
- ~~`build_dev_loop_node_factories(..., codereview_dispatcher=...)`~~ — param does not exist yet
- ~~`build_dev_loop_flow(..., codereview_dispatcher=...)`~~ — param does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# In server.py _on_startup, mirror the development_agent selection pattern:
codereview_agent = conf.config.get(
    "DEV_LOOP_CODEREVIEW_AGENT", fallback="claude-code"
).strip().lower()

# Map agent name to the underlying dispatcher needed:
# "claude-code" → use the existing `dispatcher` (ClaudeCodeDispatcher)
# "codex" → use the existing `development_dispatcher` if it's Codex, or create a new one
# "gemini" → same logic

codereview_dispatcher = CodeReviewDispatcherFactory.create(
    codereview_agent,
    dispatcher=<appropriate_underlying_dispatcher>,
)
```

### Key Constraints
- The code review dispatcher wraps an underlying development dispatcher. The
  server must ensure the underlying dispatcher exists (e.g., if
  `DEV_LOOP_CODEREVIEW_AGENT=codex` but `DEV_LOOP_DEVELOPMENT_AGENT=claude-code`,
  a new `CodexCodeDispatcher` instance must be created for the reviewer)
- `DEV_LOOP_CODEREVIEW_AGENT` defaults to `"claude-code"` for zero-config migration
- The `codereview_dispatcher` parameter must be optional in all factory/flow
  functions for backward compatibility

### References in Codebase
- `examples/dev_loop/server.py:445-560` — `_on_startup` dispatcher wiring pattern
- `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py:105-106` — current `qa_factory`
- `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:218-227` — `build_dev_loop_node_factories` call

---

## Acceptance Criteria

- [ ] `DEV_LOOP_CODEREVIEW_AGENT` config var exists in `conf.py` with default `"claude-code"`
- [ ] `build_dev_loop_node_factories` accepts and threads `codereview_dispatcher`
- [ ] `build_dev_loop_flow` accepts and threads `codereview_dispatcher`
- [ ] `_on_startup` reads `DEV_LOOP_CODEREVIEW_AGENT` and creates the right reviewer
- [ ] `DEV_LOOP_CODEREVIEW_AGENT=codex` creates `CodexCodeReviewDispatcher`
- [ ] `DEV_LOOP_CODEREVIEW_AGENT=gemini` creates `GeminiCodeReviewDispatcher`
- [ ] Default (`claude-code`) creates `ClaudeCodeReviewDispatcher`
- [ ] Invalid value raises `RuntimeError` at startup
- [ ] All tests pass
- [ ] No linting errors

---

## Test Specification

```python
import pytest
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory


class TestServerWiring:
    def test_factory_creates_claude(self):
        from unittest.mock import MagicMock
        d = CodeReviewDispatcherFactory.create("claude-code", dispatcher=MagicMock())
        assert d.agent_name == "claude-code"

    def test_factory_creates_codex(self):
        from unittest.mock import MagicMock
        d = CodeReviewDispatcherFactory.create("codex", dispatcher=MagicMock())
        assert d.agent_name == "codex"

    def test_factory_creates_gemini(self):
        from unittest.mock import MagicMock
        d = CodeReviewDispatcherFactory.create("gemini", dispatcher=MagicMock())
        assert d.agent_name == "gemini"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1694, 1695, 1696, 1697 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `factories.py`, `flow.py`, and `server.py` to confirm current signatures
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1698-factory-wiring-server-bootstrap.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `DEV_LOOP_CODEREVIEW_AGENT` to `conf.py` (default
`"claude-code"`). Added `codereview_dispatcher: Optional[Any] = None` to
`build_dev_loop_node_factories()`, threaded into `QANode(codereview_dispatcher=...)`
in `qa_factory`. Added the same param to `build_dev_loop_flow()`, threaded
into `build_dev_loop_node_factories(...)`. Wired `examples/dev_loop/server.py`
`_on_startup`: reads `DEV_LOOP_CODEREVIEW_AGENT` via `conf.config.get(...)`
(mirroring the existing `development_agent` read pattern exactly, rather
than the precomputed `conf.DEV_LOOP_CODEREVIEW_AGENT` constant — this matters
for `test_server_grok_agent_startup`, which monkeypatches `conf.config`
directly), reuses the matching development dispatcher instance when the
review agent equals the development agent (avoids spinning up a second
Codex/Gemini CLI dispatcher), otherwise builds a dedicated one, then calls
`CodeReviewDispatcherFactory.create(agent_key, dispatcher=...)` and passes
the result to `build_dev_loop_flow(codereview_dispatcher=...)`. Invalid
`DEV_LOOP_CODEREVIEW_AGENT` values raise `RuntimeError` at startup (mirrors
the existing `DEV_LOOP_DEVELOPMENT_AGENT` validation). Added
`TestServerWiring` (factory creates claude/codex/gemini) and
`TestBuildDevLoopNodeFactoriesWiring` (explicit + default `codereview_dispatcher`
threading through `qa_factory`) to `test_code_review.py`. Full `dev_loop/`
suite re-run: 334 passed, same 4 pre-existing flaky failures (unrelated,
verified via `git stash` in TASK-1697).

**Deviations from spec**: none — the `conf.config.get(...)` vs.
`conf.DEV_LOOP_CODEREVIEW_AGENT` module-constant choice follows the task's
own "Pattern to Follow" snippet and the file's existing
`development_agent` convention, not a deviation from either.
