# TASK-3923: Core hooks: LocalKBMixin honours _agents_dir; tooling-ref identity helpers

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W0 — Core hooks (M10)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.5c (immutable identity: tooling ref, vault names), §2.7 build step 3 (per-version KB directory), §3 Module 10.
`LocalKBMixin._get_agent_kb_directory` hardcodes `AGENTS_DIR` (`stores/local.py:56`), while the skills mixin already
honours `self._agents_dir`. Studio instances keep their KB under `STUDIO_RUNTIME_DIR/<agent_id>/v<version>`, never
under `AGENTS_DIR`. The identity helpers are pure functions every later identity task uses.

---

## Scope

- `_get_agent_kb_directory`: when `self._agents_dir` is set, return `<_agents_dir>/<safe_name>/kb`; else unchanged
  (`AGENTS_DIR/<safe_name>/kb`). Same priority rule as `SkillRegistryMixin._resolve_agents_dir`.
- `tools/spec.py`: rename the second parameter of `toolkit_vault_name` / `mcp_vault_name` from `agent_name` to
  `agent_ref` (bodies unchanged); add `toolkit_override_vault_name(slug, agent_ref)` and `agent_tooling_ref(bot)`.
- Tests `test_kb_dir_honours_agents_dir`, `test_vault_names_from_ref`, and the core half of `test_tooling_ref_scheme`.

**NOT in scope**: Callers switching to the ref (TASK-3927); `StudioAgentRecord.tooling_ref` (TASK-3922).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/stores/local.py` | MODIFY | honour self._agents_dir in _get_agent_kb_directory |
| `packages/ai-parrot/src/parrot/tools/spec.py` | MODIFY | agent_ref rename; toolkit_override_vault_name; agent_tooling_ref |
| `tests/unit/bots/test_local_kb_dir.py` | CREATE | KB dir hook tests |
| `tests/unit/tools/test_tooling_ref.py` | CREATE | vault-name and tooling-ref helper tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.tools.spec import toolkit_vault_name, mcp_vault_name      # spec.py:59, :64
from parrot.bots.stores.local import LocalKBMixin                     # local.py:13
from parrot.conf import AGENTS_DIR                                     # conf.py:181
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/spec.py
def toolkit_vault_name(slug: str, agent_name: str) -> str:            # line 59  return f"toolkit_{slug}_{agent_name}"
def mcp_vault_name(server: str, agent_name: str) -> str:              # line 64  return f"mcp_agent_{server}_{agent_name}"
# packages/ai-parrot/src/parrot/bots/stores/local.py
    def _get_agent_kb_directory(self) -> Optional[Path]:               # line 42
        kb_dir = Path(AGENTS_DIR) / safe_name / 'kb'                    # line 56 (occurrences: 1)
# packages/ai-parrot/src/parrot/skills/mixin.py
    def _resolve_agents_dir(self) -> Optional[Path]:                   # line 82 — priority: getattr(self, '_agents_dir', None) first (:94)
```
All three existing callers of the vault-name helpers pass the second argument positionally
(`handlers/studio/tooling_store.py:201,221,263`), so the rename breaks no caller.

### Does NOT Exist
- ~~`agent_tooling_ref`~~, ~~`toolkit_override_vault_name`~~ — created here.
- ~~A KB directory override on `LocalKBMixin`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/stores/local.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/spec.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/unit/bots/test_local_kb_dir.py",
      "action": "CREATE"
    },
    {
      "path": "tests/unit/tools/test_tooling_ref.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#toolkit_vault_name",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#mcp_vault_name",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._resolve_agents_dir"
  ]
}
```

---

## Implementation Notes

- Parallelism: no dependency; sole FEAT-621 writer of core bots/stores/local.py and tools/spec.py; TASK-3927 imports agent_tooling_ref/toolkit_override_vault_name from it, TASK-3940 relies on the _agents_dir KB hook
- Cross-feature ordering: none — X16 lists STORAGE W0 in the early, sibling-independent subset (with FEAT-605 W0.1–W0.3/W1.1–W1.5 and TOOLKITS Wave 1).
- Legacy strings must stay byte-identical: `toolkit_vault_name("jira", "sales") == "toolkit_jira_sales"`.
- `agent_tooling_ref(bot)` = `getattr(bot, "_tooling_ref", None) or bot.name` — `:` never occurs in a slug
  (`STUDIO_SLUG_RE`, `_base.py:48`), so a `studio-agent:` ref never equals a legacy name.

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

### Steps (in order)
1. Rename the parameters in `spec.py` and add the two helpers below `mcp_vault_name` — *why*: one module owns every
   vault-name formula (§2.5c table).
2. Patch `_get_agent_kb_directory` — *why*: Studio KB files live in a per-version runtime dir (§2.7 step 3).
3. Write both test files; run the Validation Commands.

### `packages/ai-parrot/src/parrot/tools/spec.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c 'def toolkit_vault_name(slug: str, agent_name: str) -> str:' spec.py ;
#                                grep -c 'def mcp_vault_name(server: str, agent_name: str) -> str:' spec.py)
def toolkit_vault_name(slug: str, agent_ref: str) -> str:
    """Return ``f"toolkit_{slug}_{agent_ref}"`` (agent_ref = tooling ref; a legacy agent's ref is its name)."""
    return f"toolkit_{slug}_{agent_ref}"


def mcp_vault_name(server: str, agent_ref: str) -> str:
    """Return ``f"mcp_agent_{server}_{agent_ref}"`` (never collides with per-user ``mcp_``)."""
    return f"mcp_agent_{server}_{agent_ref}"


def toolkit_override_vault_name(slug: str, agent_ref: str) -> str:
    """Per-user override vault name (spec §2.5c): ``f"toolkit_{slug}_{agent_ref}_user"``."""
    return f"toolkit_{slug}_{agent_ref}_user"


def agent_tooling_ref(bot: Any) -> str:
    """Immutable tooling identity: ``bot._tooling_ref`` for Studio agents, else ``bot.name`` (legacy)."""
    return getattr(bot, "_tooling_ref", None) or bot.name
```
**Why**: bodies of the existing two helpers are unchanged; only the parameter name moves (X17).

### `packages/ai-parrot/src/parrot/bots/stores/local.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "        kb_dir = Path(AGENTS_DIR) / safe_name / 'kb'" local.py)
# REPLACE line 56
        base_dir = getattr(self, "_agents_dir", None)
        kb_dir = (Path(base_dir) if base_dir else Path(AGENTS_DIR)) / safe_name / 'kb'
```

### `tests/unit/tools/test_tooling_ref.py` (CREATE)
```python
"""FEAT-621 M10 — identity helpers (§2.5c)."""
from types import SimpleNamespace  # plain object stand-in for a bot: no request/session plumbing involved

from parrot.tools.spec import agent_tooling_ref, mcp_vault_name, toolkit_override_vault_name, toolkit_vault_name


def test_vault_names_from_ref() -> None:
    ref = "studio-agent:0b0c7c8e-1111-4222-8333-444455556666"
    assert toolkit_vault_name("jira", ref) == f"toolkit_jira_{ref}"
    assert toolkit_vault_name("jira", "sales") == "toolkit_jira_sales"   # legacy unchanged
    # FILL IN: mcp_vault_name and toolkit_override_vault_name, ref and legacy forms.


def test_agent_tooling_ref_legacy_and_studio() -> None:
    # FILL IN: bot without _tooling_ref -> name; with _tooling_ref -> the ref.
    ...
```

### `tests/unit/bots/test_local_kb_dir.py` (CREATE)
```python
"""FEAT-621 M10 — test_kb_dir_honours_agents_dir."""
# FILL IN: instantiate a minimal LocalKBMixin subclass with name="sales"; unset _agents_dir -> AGENTS_DIR/sales/kb;
#   _agents_dir=tmp_path -> tmp_path/sales/kb (mutation: drop the getattr ⇒ RED).
```

### FILL IN checklist
- [ ] remaining assertions in both test files.

---

## Acceptance Criteria

- [ ] `_agents_dir` set → `<dir>/<name>/kb`; unset → `AGENTS_DIR/<name>/kb` unchanged (`test_kb_dir_honours_agents_dir`).
- [ ] Legacy vault names byte-identical; ref forms per §2.5c (`test_vault_names_from_ref`, AC12 partial).
- [ ] `agent_tooling_ref(legacy_bot) == bot.name` (`test_tooling_ref_scheme`, core half).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest tests/unit/bots/test_local_kb_dir.py -q`
- `pytest tests/unit/tools/test_tooling_ref.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_kb_dir_honours_agents_dir` | M10, §2.7 step 3 |
| `test_vault_names_from_ref` | §2.5c, AC12 |
| `test_agent_tooling_ref_legacy_and_studio` | `test_tooling_ref_scheme` (core half) |

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
   `feat(agentstudio-db-storage): TASK-3923 — Core hooks: LocalKBMixin honours _agents_dir; tooling-ref identity helpers`.
8. Close with `scripts/sdd/close_task.sh TASK-3923 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
