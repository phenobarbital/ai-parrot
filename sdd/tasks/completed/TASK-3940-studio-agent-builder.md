# TASK-3940: StudioAgentBuilder: explicit constructor map, policy binding before configure()

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Runtime + cache + lifecycle + builder (M7, part 2: StudioAgentBuilder)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3923, TASK-3933
**Assigned-to**: unassigned

---

## Context

Spec §2.7 "Instance build" (constructor map table and build steps 1–4), §2.5b (build-time gate + binding with
`bot.bind_tooling_policy(...)` before `configure()`), §2.5c/R4 (`chatbot_id = str(agent_id)`), "Build refusal vs
unavailable tooling" rule, §3 Module 7 skeleton. Not delegation-eligible (§3): precedence between factory overwrites
and kwargs needs care.

---

## Scope

- `manager/studio_builder.py` `StudioAgentBuilder(registry, runtime_dir, tooling_gate)` with
  `async build(snapshot, app, *, part) -> tuple[AbstractBot, Path]`:
  1. gate (`phase="build"`) on the snapshot's normalised tooling incl. `definition.tools`;
  2. `BotConfig(name, class_name, module, origin="factory", tools, toolkits, mcp_servers, system_prompt, model=None,
     config={}, startup_config={})` + constructor kwargs per the §2.7 map; `factory = registry.create_agent_factory`;
     `bot = await factory(**kwargs)` (never registers);
  3. write KB/skills assets to `runtime_dir/<agent_id>/v<version>/<name>/{kb,skills}/`; `bot._agents_dir =
     runtime_dir/<agent_id>/v<version>`;
  4. stamp `_studio_key`, `_studio_version`, `_studio_agent_id`, `_tooling_ref`; `bot.bind_tooling_policy(...)`;
     install `app["studio_confirmation_guard"]` when set; `await bot.configure(app)`.
- On any failure: clean the half-built instance once, remove its directory, raise `StudioToolingRefused` (policy) or
  an `AgentReloadError`-compatible error.

**NOT in scope**: Caching, leases, revalidation (TASK-3942).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/studio_builder.py` | CREATE | StudioAgentBuilder |
| `packages/ai-parrot-server/tests/manager/test_studio_builder.py` | CREATE | constructor-map, memory-key, policy and runtime-dir tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.registry import agent_registry                         # registry/__init__.py:7
from parrot.registry.registry import AgentRegistry, BotConfig      # registry.py:258, :227 (studio/agents.py:31)
from parrot.models.basic import ToolConfig                         # basic.py:33
from parrot.tools.spec import ToolkitSpec, AgentMCPServerSpec      # spec.py
from parrot.manager.manager import AgentReloadError                # manager.py:153
from parrot.bots.prompts.identity import IDENTITY_FILES            # identity.py:27
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
class BotConfig(BaseModel):   # :227 ; origin :235 (Literal["repo","factory"]) ; config :236 ; tools :239 ; toolkits :240 ;
                              # mcp_servers: List[Dict[str, Any]] :241 ; model :242 ; system_prompt :243 ; startup_config :250
    def create_agent_factory(self, config: BotConfig) -> AgentFactory   # AgentRegistry :846 — does not register;
                              # merged_args = {**startup_config, **kwargs} :860; overwrites system_prompt :863-882,
                              # llm/temperature/max_tokens from BotConfig.model, tools/agent_mcp_servers
# packages/ai-parrot/src/parrot/bots/abstract.py — chatbot_id kwarg :348 ; _chatbot_id_explicit :355 ; identity kwargs :427-431 ;
#   model_config canonical :461 ; _resolve_llm_kwarg :505-522 ; memory_key_id :1959 (explicit id :1982)
# packages/ai-parrot/src/parrot/tools/manager.py
    def set_confirmation_guard(self, guard: "ConfirmationGuard") -> None   # :551
```

### Does NOT Exist
- ~~`AbstractBot.bind_tooling_policy`~~, ~~`get_tenant_tooling_policy`~~, ~~`ToolingSubject`~~ — TOOLKITS Wave 1
  (M7 core); not on `dev` @ 32b1a45d4.
- ~~`BotConfig.origin == "studio"`~~ — use `"factory"`.
- ~~Putting values in `BotConfig.config`/`startup_config`~~ — forbidden; every value goes through the §2.7 map.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/studio_builder.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_studio_builder.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.create_agent_factory",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.set_confirmation_guard"
  ]
}
```

---

## Implementation Notes

- Parallelism: sets bot._agents_dir for the KB hook from TASK-3923 (core stores/local.py); runs StudioToolingGate(phase='build') from TASK-3933 (services/_common.py); models from TASK-3922 arrive transitively; creates manager/studio_builder.py
- Cross-feature ordering: X16 — core `interfaces/tools.py`: TOOLKITS M7 core (Wave 1) merges before this builder
  (it provides the build hook `apply_tooling_specs(*, tooling_policy=, tooling_subject=)` and
  `bind_tooling_policy`). `bind_tooling_policy` is valid only before tooling is applied (else `RuntimeError`, X15).
- Constructor rule (spec §4): tests assert on the built instance (`bot._llm_kwargs`, `bot._llm_raw`, prompt builder
  output, `bot.role`, `bot.memory_key_id`, `bot._pending_mcp_specs`), never on JSON.
- A toolkit that is merely unresolvable is skipped and reported `unavailable` (agent still builds); a policy refusal
  fails the whole build closed.
- Default runtime root: `<tempdir>/parrot-studio-<pid>`, never under `AGENTS_DIR`.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### `packages/ai-parrot-server/src/parrot/manager/studio_builder.py` (CREATE)
```python
"""Build a Studio agent instance from one storage snapshot (spec §2.7). Never registers anything."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("Parrot.AgentStudio.Storage")


class StudioAgentBuilder:
    def __init__(self, registry: "AgentRegistry", runtime_dir: Path, tooling_gate: "StudioToolingGate") -> None:
        self._registry, self._root, self._gate = registry, runtime_dir, tooling_gate

    async def build(self, snapshot: "StudioAgentSnapshot", app, *, part: "StudioPartition") -> tuple["AbstractBot", Path]:
        rec = snapshot.record
        # step 1 — FILL IN: self._gate.enforce(part, normalized_tooling_for(rec.definition, snapshot.tooling),
        #   agent_id=rec.agent_id, actor=None, phase="build")
        bot_config, kwargs = self._constructor(snapshot)          # step 2 (≤ 60 lines; split per map row if needed)
        factory = self._registry.create_agent_factory(bot_config)
        bot = await factory(**kwargs)
        # steps 3–4 — FILL IN: asset dir; _agents_dir; stamps; bind_tooling_policy; confirmation guard;
        #   await bot.configure(app); on failure clean once + rmtree + raise — bounded by test_builder_constructor_settings.
        raise NotImplementedError

    def _constructor(self, snapshot) -> tuple["BotConfig", dict]:
        """§2.7 map: chatbot_id=str(agent_id); llm kwarg; model_config from non-None model_params; BotConfig.model=None."""
        raise NotImplementedError
```

### `packages/ai-parrot-server/tests/manager/test_studio_builder.py` (CREATE)
```python
"""FEAT-621 M7 builder (AC10, AC11, AC13, AC4)."""
# FILL IN: test_builder_constructor_settings (llm openai:gpt-4o-mini, temperature 0.3→0.7 via a second snapshot,
#   max_tokens 1000 not 8192, system_prompt, role.md → bot.role, one MCP spec in _pending_mcp_specs; mutation:
#   factory() with no kwargs or BotConfig.model set ⇒ RED); test_memory_key_is_agent_id; test_build_refused_by_policy
#   (no configure() call, no subprocess, directory removed); test_runtime_dir_not_in_agents_dir;
#   test_unresolvable_toolkit_skipped.
```

---

## Acceptance Criteria

- [ ] Built instance carries the §2.7 constructor values (`test_builder_constructor_settings`, AC10).
- [ ] `memory_key_id == str(agent_id)` (AC11).
- [ ] A policy-refused snapshot never reaches `configure()` or starts a process (AC13, build half).
- [ ] KB/skills files live under `STUDIO_RUNTIME_DIR/<agent_id>/v<n>/`, nothing new under `AGENTS_DIR` (AC4).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/manager/test_studio_builder.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_builder_constructor_settings` | AC10 (unit half; cross-runtime half in TASK-3942) |
| `test_memory_key_is_agent_id` | AC11 |
| `test_build_refused_by_policy` | AC13 |
| `test_runtime_dir_not_in_agents_dir` | AC4 |
| `test_unresolvable_toolkit_skipped` | build-refusal rule |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3940 — StudioAgentBuilder: explicit constructor map, policy binding before configure()`.
8. Close with `scripts/sdd/close_task.sh TASK-3940 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: manager/studio_builder.py StudioAgentBuilder(registry, runtime_dir, tooling_gate).build(snapshot, app, *, part): gate(phase=build, actor None) on normalised tooling -> tenant class allowlist (StudioClassAllowlist.from_app) -> BotConfig(origin=factory, model=None, config/startup_config empty) + kwargs per the §2.7 map (chatbot_id=str(agent_id), llm, model_config from non-None model_params, description, created_by, identity kwargs from identity assets, definition.config) -> registry.create_agent_factory (never registers) -> KB/skills written under runtime_dir/<agent_id>/v<version>/ , bot._agents_dir set -> stamps (_studio_key = StudioAgentKey object, _studio_version, _studio_agent_id, _tooling_ref) -> bind_tooling_policy(get_tenant_tooling_policy(app), ToolingSubject(phase=build), owner=record.owner) -> confirmation guard -> configure. Failure: half-built bot cleaned once through cleanup_bot_instance (TASK-3941, executed first for that reason), directory removed; StudioToolingRefused and CancelledError propagate, anything else becomes AgentReloadError. Decisions: _studio_key holds the StudioAgentKey (not the qualified string) - consumers read .qualified; KB is written under the dir name LocalKBMixin derives (agent_id attr else name) so the core hook finds it, skills under <name>/skills; owner= passed to bind_tooling_policy (optional kwarg of the merged core hook). 16 tests pass; 17 mutations RED (4 needed extra assertions, added).

**Deviations from spec**: none
