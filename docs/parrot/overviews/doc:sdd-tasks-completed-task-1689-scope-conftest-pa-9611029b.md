---
type: Wiki Overview
title: 'TASK-1689: Scope the `_install_parrot_stubs()` sys.modules leak to an opt-in
  fixture'
id: doc:sdd-tasks-completed-task-1689-scope-conftest-parrot-bots-stub-leak-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 376-434) builds fake, minimal stand-ins for `parrot.bots.abstract.AbstractBot`
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.jira_specialist
  rel: mentions
- concept: mod:parrot.bots.search
  rel: mentions
---

# TASK-1689: Scope the `_install_parrot_stubs()` sys.modules leak to an opt-in fixture

**Feature**: FEAT-268 — jiraspecialist-prompt-builder-stub-leak
**Spec**: `sdd/specs/jiraspecialist-prompt-builder-stub-leak.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`packages/ai-parrot/tests/conftest.py::_install_parrot_stubs()` (lines
376-434) builds fake, minimal stand-ins for `parrot.bots.abstract.AbstractBot`
and `parrot.bots.agent.Agent`/`BasicAgent`, for the benefit of lightweight
AgentCrew-style tests that don't want the real heavy dependency chain. It
registers them via `sys.modules.setdefault("parrot.bots.abstract", ...)` /
`sys.modules.setdefault("parrot.bots.agent", ...)`, called **unconditionally
at conftest import time** (line 627), which happens before any test module in
`packages/ai-parrot/tests/` is imported.

Because neither key is normally already present in `sys.modules` at that
point, the fake modules win the `setdefault` race and stay cached in
`sys.modules` for the **entire pytest process** — not just for the tests that
wanted them. Any test file that later does
`from parrot.bots.jira_specialist import JiraSpecialist` and really
constructs `JiraSpecialist(**kwargs)` silently inherits from the **fake**
`_BasicAgent`/`_AbstractBot` instead of the real classes, which is the direct
cause of TASK-1690's `AttributeError` bug (see the spec's §1 for the full
diagnosis chain).

This task fixes the leak at its source, independent of TASK-1690's defensive
one-line fix in `jira_specialist.py` (they can land in either order).

---

## Scope

- Convert `_install_parrot_stubs()` from an unconditional module-level
  function call into an **opt-in pytest fixture** that uses
  `monkeypatch.setitem(sys.modules, key, fake_module)` instead of
  `sys.modules.setdefault(...)`, so the mutation is automatically undone at
  fixture teardown instead of persisting for the rest of the process.
- Before changing anything, enumerate every existing test that currently
  relies on the fake stubs (whether by explicitly importing
  `parrot.bots.agent.BasicAgent`/`Agent` in a context where the fake is
  expected, or implicitly benefiting from the leak). Use:
  ```bash
  grep -rl "_BasicAgent\|BasicAgent\|parrot\.bots\.agent\|parrot\.bots\.abstract" packages/ai-parrot/tests/
  ```
  and manually inspect each hit to determine whether it depends on the fake
  or the real module.
- Update every test identified above to explicitly request the new fixture
  (e.g. add a `fake_parrot_bots` fixture parameter) instead of relying on the
  implicit global leak.
- Preserve the exact behavior/bodies of `_ToolManager`, `_AbstractBot`,
  `_BasicAgent` — only change *how* and *when* they get registered into
  `sys.modules`, not what they do.

**NOT in scope**:
- Any change to `jira_specialist.py` (that's TASK-1690).
- Fixing `_install_navconfig_stub()` or `_install_navigator_stubs()` — leave
  those two installers untouched even though they use a similar pattern;
  only `_install_parrot_stubs()` is implicated in this bug.
- Fixing unrelated collection errors seen in the broader
  `pytest packages/ai-parrot/tests/ -k jira` run.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/conftest.py` | MODIFY | Convert `_install_parrot_stubs()` + its module-level call (line 627) into an opt-in `monkeypatch`-scoped fixture |
| Any test file identified as depending on the fake stubs (from the `grep` above) | MODIFY | Request the new fixture explicitly instead of relying on the implicit leak |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/tests/conftest.py — already imported at top of file
import sys                                    # line 6
import types                                  # line 9
import pytest                                 # line 12
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/conftest.py:376-434
def _install_parrot_stubs() -> None:
    class _ToolManager:                        # line 380
        def __init__(self, *_, **__): ...
        def add_tool(self, tool, tool_name=None) -> None: ...
        def register_tools(self, tools) -> None: ...
        def get_tool(self, name=None) -> Any: ...
        def list_tools(self) -> List[str]: ...
        def tool_count(self) -> int: ...
        def get_tool_schemas(self, provider_format=None) -> List[Dict[str, Any]]: ...
        def all_tools(self) -> List[Any]: ...

    class _AbstractBot:                        # line 411
        def __init__(self, name: str = "Agent", **_):  # line 412
            self.name = name
            self.tool_manager = _ToolManager()
            self.use_llm = None
            self.llm = None
            self._llm = None

    bots_abstract_module = types.ModuleType("parrot.bots.abstract")  # line 419
    bots_abstract_module.AbstractBot = _AbstractBot                 # line 420
    bots_abstract_module.OutputMode = type("OutputMode", (), {})    # line 421
    sys.modules.setdefault("parrot.bots.abstract", bots_abstract_module)  # line 422 — REPLACE

    class _BasicAgent(_AbstractBot):           # line 424
        async def configure(self): ...          # line 425
        def agent_tools(self): ...              # line 428

    bots_agent_module = types.ModuleType("parrot.bots.agent")  # line 431
    bots_agent_module.BasicAgent = _BasicAgent  # line 432
    bots_agent_module.Agent = _BasicAgent       # line 433
    sys.modules.setdefault("parrot.bots.agent", bots_agent_module)  # line 434 — REPLACE

# module-level invocation, unconditional (line 625-627):
_install_navconfig_stub()    # line 625 — leave untouched
_install_navigator_stubs()   # line 626 — leave untouched
_install_parrot_stubs()      # line 627 — REMOVE this unconditional call
```

### Does NOT Exist

- ~~An `autouse=True` fixture responsible for this leak~~ — confirmed via
  `grep -n autouse packages/ai-parrot/tests/conftest.py` (no matches); the
  leak is a plain unconditional function call at module scope, not a fixture.
- ~~`monkeypatch` already imported/used in `_install_parrot_stubs()`~~ — it is
  not; `_install_parrot_stubs()` currently takes no arguments and is not a
  fixture. Converting it to a fixture means adding a `monkeypatch` parameter.

---

## Implementation Notes

### Pattern to Follow

```python
import sys
import types
import pytest


@pytest.fixture
def fake_parrot_bots(monkeypatch):
    """Opt-in fake AbstractBot/Agent stand-ins for lightweight AgentCrew tests.

    Scoped via monkeypatch.setitem so sys.modules is restored automatically
    at teardown, instead of the old sys.modules.setdefault() approach which
    leaked into unrelated tests needing the REAL parrot.bots.abstract /
    parrot.bots.agent (see FEAT-268 for the bug this caused in JiraSpecialist).
    """
    class _ToolManager:
        ...  # keep body identical to today's _install_parrot_stubs()

    class _AbstractBot:
        ...  # keep body identical

    bots_abstract_module = types.ModuleType("parrot.bots.abstract")
    bots_abstract_module.AbstractBot = _AbstractBot
    bots_abstract_module.OutputMode = type("OutputMode", (), {})
    monkeypatch.setitem(sys.modules, "parrot.bots.abstract", bots_abstract_module)

    class _BasicAgent(_AbstractBot):
        ...  # keep body identical

    bots_agent_module = types.ModuleType("parrot.bots.agent")
    bots_agent_module.BasicAgent = _BasicAgent
    bots_agent_module.Agent = _BasicAgent
    monkeypatch.setitem(sys.modules, "parrot.bots.agent", bots_agent_module)

    yield  # or return the fake classes/module if tests need to reference them directly
```

Then any test that currently relies on the fake stubs adds `fake_parrot_bots`
as a fixture parameter (pytest resolves and applies it automatically before
the test body runs, and `monkeypatch` tears it down after).

### Key Constraints

- Use `monkeypatch.setitem`, not manual `sys.modules[key] = ...` assignment —
  `monkeypatch` guarantees teardown even if the test fails/errors.
- Start with function-scoped fixture (default). Only consider widening scope
  if there's a measured performance concern (see spec §8 Open Questions).
- Do not change the fake classes' *behavior* — only their registration
  mechanism.

### References in Codebase

- `packages/ai-parrot/tests/conftest.py:39-115` (`_install_navconfig_stub`)
  and `:115-376` (`_install_navigator_stubs`) — similar stub-installer
  pattern, intentionally left untouched by this task (see Non-Goals).

---

## Acceptance Criteria

- [ ] `_install_parrot_stubs()` no longer runs unconditionally at conftest
      import time; it (or its replacement) only takes effect when a test
      explicitly requests it.
- [ ] Every test identified via the `grep` sweep as depending on the fake
      stubs has been updated to request the new fixture and still passes.
- [ ] `pytest packages/ai-parrot/tests/ -v` (full suite) shows no new
      failures compared to the pre-change baseline, aside from the four
      `_prompt_builder`-related files which are expected to start passing
      once TASK-1690 also lands (verify both tasks together per spec §5).
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/conftest.py`

---

## Test Specification

```python
# No new dedicated test file — this task's correctness is verified by:
# 1. The four previously-failing jira test files (test_jira_assignment.py,
#    test_jiratoolkit_defaults.py, test_jira_ticket_created.py,
#    test_jiraspecialist_prompt_builder.py) passing once combined with
#    TASK-1690.
# 2. Every test file identified as a fake-stub consumer still passing after
#    being updated to request the new fixture explicitly.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jiraspecialist-prompt-builder-stub-leak.spec.md` for full context.
2. **Check dependencies** — none; can run independently of TASK-1690.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the exact line numbers above still match `packages/ai-parrot/tests/conftest.py` (it may have shifted since spec time).
   - Run the `grep -rl` sweep from the Scope section and inspect every hit before touching anything.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met — run the FULL
   `packages/ai-parrot/tests/` suite, not just the jira-related files, to
   catch any test that implicitly depended on the old leak.
7. **Move this file** to `sdd/tasks/completed/TASK-1689-scope-conftest-parrot-bots-stub-leak.md`.
8. **Update the per-spec index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-07-01
**Notes**:

- Converted `_install_parrot_stubs()` into the opt-in `fake_parrot_bots(monkeypatch)`
  fixture per the codebase contract, using `monkeypatch.setitem(sys.modules, ...)`
  instead of `sys.modules.setdefault(...)`. Removed the unconditional
  `_install_parrot_stubs()` call at former line 627; left `_install_navconfig_stub()`
  and `_install_navigator_stubs()` untouched, as scoped.
- Ran the mandated `grep -rl` sweep across `packages/ai-parrot/tests/` (27 hits)
  and manually inspected every hit. Conclusion: **no test file currently needs
  to be updated to request the new fixture.** Every hit fell into one of these
  buckets:
  - Files that already force-load the REAL `parrot.bots.abstract`/`.agent`
    themselves (pop/reload/override sys.modules directly), e.g.
    `test_basic_agent_new.py`, `test_agent_module.py`,
    `test_resolve_output_mode_noop.py`, `bots/prompts/conftest.py` +
    `test_abstractbot_integration.py` + `test_comparison.py`,
    `test_vector_context_integration.py`, `test_rag_conversation_integration.py`,
    `registry/test_vector_store_propagation.py`, `test_odoo_agent.py`.
  - Files with their own fully independent stub machinery, unaffected either
    way: `test_jira_specialist_grounding.py`, `test_bot_cleanup_lifecycle.py`
    (the latter doesn't even touch `parrot.bots.agent`/`.abstract` — only
    matched the grep on the substring "BasicAgent").
  - Files that only reference the strings "BasicAgent"/`parrot.bots.agent` in
    docstrings, YAML fixtures, or unrelated patch targets (`parrot.bots.search.
    BasicAgent`), not the conftest leak: `test_agent_crew_examples.py`,
    `factory/test_contracts.py`, `registry/test_register_db_bot_policies.py`,
    `fixtures/agents/marketing.yaml`, `test_web_search_agent.py`,
    `test_intent_router_output_mode_integration.py`.
  - `test_agent_definitions.py`, `test_agent_registry_instances.py`,
    `test_orchestrator_conference.py`: verified by temporarily disabling the
    stub call and re-running — all pass identically with the REAL modules
    (test_orchestrator_conference.py is ~10x slower with the real chain, 22s
    vs 2s, but still 21/21 passing; no correctness dependency on the fake).
  - `test_notification.py`: already has a pre-existing, unrelated collection
    error (one of the 23 baseline errors) — out of scope.
- **Bonus finding**: two test files were silent VICTIMS of the exact same leak
  (not flagged in the task's 4-file list) and now pass reliably instead of
  failing: `tests/bots/test_bot_warmup_registry.py` (was 6/6 failing on
  `AbstractBot.warmup_embeddings` AttributeError against the fake — now 6/6
  passing) and `tests/bots/database/test_database_agent.py` (was 9/15 failing
  on `issubclass(DatabaseAgent, BasicAgent)` against the fake — now 15/15
  passing when checked with the fixed conftest.py).
- Full verification results (including two still-failing files that are
  pre-existing/unrelated bugs, discovered while verifying this task) are
  recorded in TASK-1691's Completion Note.

**Deviations from spec**: none. No test file required modification to opt in
to the new fixture (grep sweep found zero genuine consumers of the fake for
correctness).
