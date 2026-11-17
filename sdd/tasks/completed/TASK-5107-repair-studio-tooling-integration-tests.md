# TASK-5107: Diagnose and repair the three red tests in test_tooling_integration.py

**Feature**: FEAT-791 — BotManager fixes — Jira web-channel OAuth2 registration + BotManager test-API drift
**Spec**: `sdd/specs/manager-manager-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:31f12d3a6967`

---

## Context

Implements spec §3 Module 4 (Lane B, part 2). Three tests in
`packages/ai-parrot-server/tests/studio/test_tooling_integration.py` fail on
`dev`. Unlike TASK-5106's 16, these are **not** one uniform API drift — each has
a different cause, and only the first is clearly a removed-symbol problem:

| Test | Line | Observed failure |
|---|---|---|
| `test_yaml_agent_toolkit_persist_roundtrip` | 327 | `AttributeError: 'BotManager' object has no attribute '_build_from_registry'` |
| `test_dataset_manager_datasources_in_memory` | 389 | `assert 0 == 2` — `await manager.replay_datasources(datasources)` returns `[]` |
| `test_user_override_session_isolation` | 472 | `AttributeError: 'NoneType' object has no attribute 'list_tools'` |

Two observations recorded while triaging on `2ac26be889`, to be confirmed, not
assumed:
- Around `test_dataset_manager_datasources_in_memory`, the log shows
  `replay_datasources: skipped 'query1' (TenantError)` and
  `skipped 'sql1' (RuntimeError)` from `parrot/tools/dataset_manager/tool.py:2198`
  — i.e. both datasources are *skipped*, not rejected, which is why the list is empty.
- Around `test_user_override_session_isolation`, the log shows
  `Failed to connect to DocumentDB: ... localhost:27017: [Errno 111] Connection refused`
  followed by `Toolkit override application failed for 'a1': ConnectionError`, and
  `_apply_user_toolkit_overrides` then returns `None`. This one may need a live
  MongoDB rather than a code fix.

This module is a direct importer of `manager.py`, so these three are part of the
19-test false "new red" that the merge/feature-tier gate reports on every feature
touching `BotManager`.

---

## Scope

- Diagnose each of the three failures to its actual root cause before changing anything.
- Repoint `test_yaml_agent_toolkit_persist_roundtrip` at the current BotManager API
  that replaced `_build_from_registry`.
- Fix `test_dataset_manager_datasources_in_memory` so the two datasources register,
  or — if `replay_datasources` legitimately requires a tenant/runtime the unit test
  cannot provide — give the test that context explicitly.
- For `test_user_override_session_isolation`: if it genuinely requires a live
  DocumentDB/MongoDB, mark it with the repository's existing integration/service
  marker or an explicit `pytest.mark.skipif` **naming the service in its reason**;
  otherwise fix it.

**NOT in scope**: restoring `BotManager._build_from_registry`; changing
`parrot/tools/dataset_manager/tool.py`, `parrot/manager/manager.py` or any other
`src/` file to make a test pass; standing up MongoDB in CI; weakening or deleting
any assertion; TASK-5106's file; anything in Lane A (TASK-5105).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` | MODIFY | Repair the three failing tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `2ac26be889` (dev, 2026-11-03).

### Verified Imports
```python
from parrot.manager.manager import BotManager  # verified: packages/ai-parrot-server/tests/studio/test_tooling_integration.py:17
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/tests/studio/test_tooling_integration.py — current test setup, line 318 ff.
mgr = BotManager.__new__(BotManager)          # line 318
mgr.logger = MagicMock()
mgr._resolve_database_bot_class = MagicMock(return_value=_CapturedBot)
mgr._normalize_database_bot_permissions = MagicMock(return_value={})
mgr._apply_prompt_config = MagicMock()
mgr.registry = registry
mgr.registry.register_db_bot_policies = MagicMock(return_value=0)
bot = mgr._build_from_registry("test-agent", app=MagicMock())   # line 327 — REMOVED METHOD

# The sibling test in the same file (line 211 ff.) uses a method that DOES still exist:
await mgr._build_database_bot(fake_bot_model, app=MagicMock())
```

`BotManager._build_database_bot` is the surviving sibling factory and is the
starting point for locating `_build_from_registry`'s replacement — but **verify
it is the right replacement** before using it: the two tests feed different
inputs (a DB bot model vs. a registry entry name).

### Does NOT Exist
- ~~`BotManager._build_from_registry`~~ — removed; zero hits in `packages/*/src`
- ~~`BotManager._build_prompt_builder`~~ — removed (TASK-5106's subject)
- ~~`BotManager.build_from_registry`~~ (public) — do not assume a de-underscored variant
  exists; `grep` before using any name
- ~~`AgentRegistry.build_bot`~~ — not verified to exist; verify before referencing

### To Verify Before Implementing (deliberately unresolved)
The replacement for `_build_from_registry`, the reason `replay_datasources` skips both
datasources, and whether `_apply_user_toolkit_overrides` can work without DocumentDB are
**not** fixed by this contract. Resolve each by reading the current source — that
diagnosis is the substance of this task, which is why it carries no Delegation Contract.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tooling_integration.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._build_database_bot"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Test-only task.** No `src/` file may be modified. If the root cause turns out to be
  a production bug rather than test drift, STOP, record it in the Completion Note, open a
  ledger issue (`wikitoolkit ledger open --kind bug --discovered-from spec:FEAT-791 ...`),
  and close this task `done-with-issues` rather than editing `src/`.
- Never weaken an assertion, never delete a test, never `xfail` to reach green. A skip is
  allowed **only** for a genuine external-service dependency, and its reason string must
  name the service.
- Check how the rest of this repository marks service-dependent tests before inventing a
  marker — reuse the existing convention.
- `test_dataset_manager_datasources_in_memory`'s log line comes from
  `parrot/tools/dataset_manager/tool.py:2198` (`replay_datasources: skipped ...`). Read that
  function to learn what `TenantError`/`RuntimeError` mean there before deciding whether the
  test or its fixture is wrong.

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_tooling_integration.py:211` — the sibling
  `_build_database_bot` call that still works; same `_CapturedBot` harness
- `packages/ai-parrot-server/src/parrot/manager/manager.py` — the surviving factory methods
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:2198` — the skip log site

---

## Implementation Blueprint

### Steps (in order)
1. Reproduce all three failures from the worktree and capture the full tracebacks —
   *why*: two of the three have causes that the `AttributeError` headline hides, and
   the triage above was done on a different checkout.
2. `grep` `packages/*/src` for the factory that replaced `_build_from_registry`
   (start from `_build_database_bot` and the registry call sites) — *why*: the
   contract deliberately does not name it; guessing is the failure mode this
   task exists to avoid.
3. Repoint `test_yaml_agent_toolkit_persist_roundtrip` at that factory, adjusting only
   the `mgr.*` mock attributes the new factory actually reads — *why*: the current
   mock set was built for the removed method's collaborators.
4. Read `replay_datasources` and decide whether the empty list is a missing tenant
   context in the test or a real defect — *why*: `assert 0 == 2` with two *skipped*
   datasources points at the fixture, not the assertion.
5. Decide `test_user_override_session_isolation`'s disposition: fix if the DocumentDB
   dependency is incidental, otherwise skip with a service-naming reason — *why*: making
   a service-dependent test pass by mocking away the thing it tests would be worse than a
   skip.
6. Run the Validation Commands; `0 failed` is the bar, with any skip explained in the
   Completion Note.

### `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` (MODIFY — roundtrip test)
```python
# occurrences: 1 (verified: grep -c '    bot = mgr._build_from_registry("test-agent", app=MagicMock())' packages/ai-parrot-server/tests/studio/test_tooling_integration.py)
# REPLACE — `    bot = mgr._build_from_registry("test-agent", app=MagicMock())` (verified: packages/ai-parrot-server/tests/studio/test_tooling_integration.py:327)
# FILL IN: call the current registry-backed factory found in step 2, with the arguments
# its real signature takes. Adjust the mgr.* MagicMock attributes above (lines 318-325)
# to exactly the collaborators that factory reads — no more, no less.
# Leave assertions at lines 329-337 byte-identical.
# Bounded by: AC-1 and AC-5 (no assertion weakened).
```
**Why**: the assertions below the call are the test's whole value — they check that
`available_tools` is absent and that the `ToolkitSpec` survives hydration with its
params, secret_refs and vault_owner. Only the construction line and its mock scaffolding
may move.

### `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` (MODIFY — datasources test)
```python
# occurrences: 1 (verified: grep -c '    assert len(registered) == 2' packages/ai-parrot-server/tests/studio/test_tooling_integration.py)
# CONTEXT — `    registered = await manager.replay_datasources(datasources)` precedes
# `    assert len(registered) == 2` (verified: packages/ai-parrot-server/tests/studio/test_tooling_integration.py:387-389)
# FILL IN: give the manager/fixture whatever replay_datasources requires so both
# datasources register instead of being skipped (the log names TenantError for 'query1'
# and RuntimeError for 'sql1'). Do NOT change the assertion to match the skip.
# Bounded by: AC-2 and AC-5.
```
**Why**: `replay_datasources` reports the skips rather than raising, so the test's
expectation of 2 is almost certainly right and its setup is what drifted. Confirm that
from the source before changing the fixture.

### `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` (MODIFY — override isolation test)
```python
# occurrences: 1 (verified: grep -c '    assert tool_manager.list_tools() == \["echo"\]' packages/ai-parrot-server/tests/studio/test_tooling_integration.py)
# CONTEXT — `    tool_manager = await handler._apply_user_toolkit_overrides(agent, _Session(), None)`
# precedes the failing assert (verified: packages/ai-parrot-server/tests/studio/test_tooling_integration.py:470-472)
# FILL IN: either (a) remove the incidental DocumentDB dependency so
# _apply_user_toolkit_overrides returns a real manager, or (b) mark the test skipped with a
# reason naming MongoDB/DocumentDB and the port it needs. Choose (b) ONLY after confirming
# the connection is required by what the test asserts, not merely by an unrelated import.
# Bounded by: AC-3 and AC-4 (a skip must name the service).
```
**Why**: the `None` return is downstream of `Toolkit override application failed for 'a1':
ConnectionError`. Mocking the connection away could make the assertion vacuous, so the
decision between (a) and (b) must be made against the real code path.

### FILL IN checklist
- [ ] `test_yaml_agent_toolkit_persist_roundtrip` — replacement factory + mock set; bounded by AC-1
- [ ] `test_dataset_manager_datasources_in_memory` — fixture gives replay_datasources its context; bounded by AC-2
- [ ] `test_user_override_session_isolation` — fixed, or skipped with a service-naming reason; bounded by AC-3/AC-4
- [ ] Completion Note records each root cause and any skip; bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-1: `test_yaml_agent_toolkit_persist_roundtrip` passes against the current BotManager API.
- [ ] AC-2: `test_dataset_manager_datasources_in_memory` passes with `len(registered) == 2` unchanged.
- [ ] AC-3: `test_user_override_session_isolation` passes, or is skipped.
- [ ] AC-4: Any skip carries a reason naming the required external service.
- [ ] AC-5: No assertion was weakened, renamed or deleted; no test was removed or `xfail`ed.
- [ ] AC-6: The Completion Note states the root cause of each of the three failures.
- [ ] AC-7: No file under any `src/` tree was modified.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py -q` → 0 failed.
- [ ] No linting errors: `ruff check` on the changed file.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py::test_yaml_agent_toolkit_persist_roundtrip -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py::test_dataset_manager_datasources_in_memory -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py::test_user_override_session_isolation -q`

---

## Test Specification

No new tests. The three existing tests are the specification. Run with an absolute
`PYTHONPATH` covering both changed packages, since the shared venv is editable-installed
against the main checkout:

```bash
PYTHONPATH=/abs/path/to/worktree/packages/ai-parrot/src:/abs/path/to/worktree/packages/ai-parrot-server/src \
  pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py -q
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug manager-manager-fixes --feature-id FEAT-791`)
2. **Read the spec** at `sdd/specs/manager-manager-fixes.spec.md` (§3 M4)
3. **Check dependencies** — none
4. **Diagnose before editing** — reproduce all three failures and find each root cause;
   this task's contract deliberately leaves the replacement API unnamed
5. **Update status** in `sdd/tasks/index/manager-manager-fixes.json` → `"in-progress"`
6. **Implement** from the Implementation Blueprint; never edit a `src/` file
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only this task's one file
9. **Close** with `parrot sdd task close TASK-5107 manager-manager-fixes verified`
   (or `partial` if a test had to be skipped for a live service)
10. **Fill in the Completion Note** with the three root causes, then commit the SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: ai-parrot-8c (/sdd-fix, agent:sdd-fix)
**Date**: 2026-11-03
**Notes**: All three failures were test-side; no `src/` file was modified, no
assertion weakened, no test skipped or deleted. `test_tooling_integration.py`
is now `4 passed`. AC-6's root causes:

1. **`test_yaml_agent_toolkit_persist_roundtrip`** — genuine API drift.
   `BotManager._build_from_registry` was replaced by
   `AgentRegistry.create_agent_factory(config) -> AgentFactory`
   (`registry.py:903`), which is the code that calls `normalize_tooling(...)`
   and sets `merged_args["tools"] = tooling.tools + tooling.toolkits` /
   `merged_args["agent_mcp_servers"]` (`registry.py:968-974`) — exactly the AC8
   behaviour this test asserts. The factory resolves the agent class through a
   real `importlib.import_module(config.module)` + `getattr(module,
   config.class_name)`, so the old `_resolve_database_bot_class` mock no longer
   has anything to intercept: `_CapturedBot` is now published into
   `sys.modules` under a fake module name and `BotConfig.module`/`class_name`
   point at it. The `mgr` scaffolding and the two `create_reranker` /
   `create_parent_searcher` monkeypatches went away with it; the registry is
   built with `AgentRegistry.__new__` since `create_agent_factory` only touches
   `self._apply_prompt_config`, and only when `config.prompt` is set (it is not).
   Assertions unchanged.

2. **`test_dataset_manager_datasources_in_memory`** — not an assertion problem.
   `replay_datasources` delegates to `add_dataset()`, which *materializes* each
   descriptor by awaiting the backing source's `fetch()` (`tool.py:1032-1058`).
   `query_slug` therefore goes out to QuerySource and raises
   `TenantError: Query not found: 'test-slug'`, and `sql` actually executes
   `SELECT * FROM test` against `sqlite:///:memory:`, which asyncdb's sqlite
   driver cannot open (`DriverError: Unable to Open Database`, surfaced as
   `RuntimeError: SQLQuerySource execution failed`). `replay_datasources`
   swallows both as `replay_datasources: skipped ... (TenantError|RuntimeError)`
   and returns `[]` — hence `assert 0 == 2`. The module's own docstring says
   "offline, fakes only", so `QuerySlugSource.fetch` and `SQLQuerySource.fetch`
   are now stubbed to return an empty frame. The behaviour under test — replay
   registration bookkeeping — runs for real; only the network/driver round-trip
   is faked. `assert len(registered) == 2` is untouched.

3. **`test_user_override_session_isolation`** — two defects, neither needing a
   live service. The test built a `_Service` fake and then never injected it:
   `_apply_user_toolkit_overrides` constructs `ToolkitConfigService()` itself
   (`agent.py:50` import, instantiated inside the method), which reached
   DocumentDB on `localhost:27017`, failed with `ConnectionError`, and returned
   the `tool_manager` argument — `None`. The fake is now patched over
   `parrot.handlers.agent.ToolkitConfigService`, and its methods were updated to
   the API the handler actually calls: `load(user_id, ref) -> list` and
   `revision(user_id, ref)` (the fake still had the stale
   `load(user_id, agent_id, slug) -> override | None` shape). Separately, the
   final assertion passed a `ToolManager` to `get_toolkit_owner()`, which takes
   a *tool* and returns `None` for anything else — it had simply never been
   reached before. It now mirrors the line above it and reads the owner off
   `agent.tool_manager.get_tool("echo")`. **No live MongoDB/DocumentDB is
   required**, so AC-3 is satisfied by a fix and AC-4 does not apply.

**Deviations from spec**: one, and it is a pre-existing red, not a regression.

`packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py::test_register_oauth2_providers_from_descriptors`
fails with `AssertionError: Expected 'mock' to be called once. Called 2 times.`
It is in FEAT-791's validation contract (added for TASK-5105's sake) and it
fails identically on a clean `dev` checkout at the base commit, verified by
running that node id in the main checkout before this branch existed. It
exercises the descriptor-provider path, is unrelated to both lanes of this
feature, and is out of scope here; a ledger issue was opened for it. The rest of
the contract is `60 passed`.
