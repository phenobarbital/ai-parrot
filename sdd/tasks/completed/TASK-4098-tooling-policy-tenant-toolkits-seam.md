# TASK-4098: TenantToolingPolicy.tenant_toolkits seam (B4, parrot core)

**Feature**: FEAT-634 — Agent Studio — UI Backend Gaps
**Spec**: `sdd/specs/agentstudio-ui-backend-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 3 / G3 (B4, seam half) / AC8-AC10. The host (FieldSync) registers one synchronous callback returning the toolkit slugs enabled for a tenant; `check_tool` applies it.

---

## Scope

- Add `model_config = ConfigDict(arbitrary_types_allowed=True)` and optional field `tenant_toolkits: Callable[[str], Collection[str] | None] | None = None` to `TenantToolingPolicy` (stay frozen).
- In `check_tool`, for host entries only (`entry.is_host`), when `subject.tenant` is set and `subject.phase != 'build'` and the callback is set: call it; `None` = unrestricted; a collection not containing `slug` raises `TenantToolingRefused('toolkit_unavailable', item=slug)`; a raising callback is logged and treated as nothing enabled (fail closed).
- Never apply the allow-list to non-host slugs, to `tenant=None`, or to phase `build` (a stored agent whose toolkit was later disabled must still build).
- Verify by grep that policies are not hashed anywhere (frozen model with a callable field); extend `packages/ai-parrot/tests/tools/test_tooling_policy.py` (existing tests pass unmodified, AC10).

**NOT in scope**: Studio routes / `_studio_error` (TASK-4099), FieldSync registration (host work), docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/tooling_policy.py` | MODIFY | `tenant_toolkits` field + `check_tool` branch |
| `packages/ai-parrot/tests/tools/test_tooling_policy.py` | MODIFY | extend with allow-list cases |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `e840b4b44` (2026-10-05). Use these VERBATIM; verify anything else with grep first.

### Verified Imports
```python
from parrot.tools.tooling_policy import TenantToolingPolicy, TenantToolingRefused, ToolingSubject, set_tenant_tooling_policy  # tooling_policy.py:102,34,53,241
from pydantic import BaseModel, field_validator  # tooling_policy.py:9 — add ConfigDict
from collections.abc import Mapping, MutableMapping  # tooling_policy.py:4 — add Callable, Collection
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/tooling_policy.py
class TenantToolingPolicy(BaseModel, frozen=True):   # :102 mcp_servers, mcp_endpoints, mcp_transports, builtin_tools, host_toolkits, apply_to_global
    def check_tool(self, slug: str, *, subject: ToolingSubject) -> None:   # :122
        entry = get_toolkit_resolver().entry(slug)   # :124 ; `if entry.is_host:` branch :127-130 (refuses when not self.host_toolkits)
class ToolingSubject(BaseModel, frozen=True):        # :53  tenant, agent_id, actor, phase: Literal["write","activate","build","attach","execute"]
class TenantToolingRefused(...):                      # :34  TenantToolingRefused("toolkit_unavailable", item=slug)
```

### Does NOT Exist
- ~~`StudioAgentPatch.tools` / `POST /agents/{name}/tools` on a tenant (B3, out of scope)~~
- ~~`config` or `schema_version` in any readable response (deliberately not exposed)~~
- ~~`expected_version` support on the visibility PATCH routes (last-write-wins, B7)~~
- ~~`TenantToolingPolicy.tenant_toolkits`~~ before TASK-4098 lands (added by this feature)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/tooling_policy.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_tooling_policy.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/tooling_policy.py#TenantToolingPolicy",
    "sym:packages/ai-parrot/src/parrot/tools/tooling_policy.py#TenantToolingPolicy.check_tool",
    "sym:packages/ai-parrot/src/parrot/tools/tooling_policy.py#ToolingSubject"
  ]
}
```

---

## Implementation Notes

- Additive only: no existing field, route or error code is renamed or removed. Async-first, Pydantic v2, `self.logger`, Google docstrings, type hints, 120 cols.
- Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.
- Viewers of a tenant-shared agent do NOT read `system_prompt` (Resolved 2026-10-05, Juan).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature or path the blueprint fixes. Re-run each `grep -c` before editing; a count other than the one stated means the anchor moved — stop and report.

### Steps (in order)
1. Add the field and `ConfigDict` — because a callable field needs `arbitrary_types_allowed`.
2. Extend the `is_host` branch of `check_tool` — because built-in slugs and `tenant=None` must be unaffected.
3. Log and fail closed on a raising callback — because a broken host projection must never widen access.

### `packages/ai-parrot/src/parrot/tools/tooling_policy.py` (MODIFY)
```python
# EDIT imports (verified: tooling_policy.py:4,9): add `Callable, Collection` to the collections.abc import and `ConfigDict` to the pydantic import
# occurrences: 1 (verified: grep -c 'class TenantToolingPolicy(BaseModel, frozen=True):' tooling_policy.py)
# AFTER — insert below the class docstring (tooling_policy.py:103) :
    model_config = ConfigDict(arbitrary_types_allowed=True)
    # (field goes after `apply_to_global: bool = False`, verified: :111)
    tenant_toolkits: Callable[[str], Collection[str] | None] | None = None
    # NOTE: if the class already defines model_config (grep first), merge ConfigDict(arbitrary_types_allowed=True) into it instead of redefining

# occurrences: 1 (verified: grep -c '        if entry.is_host:' tooling_policy.py)
# REPLACE the `if entry.is_host:` branch (verified: :127-130) with:
        if entry.is_host:
            if not self.host_toolkits:
                raise TenantToolingRefused("toolkit_unavailable", item=slug)
            # FILL IN: when self.tenant_toolkits and subject.tenant and subject.phase != "build": enabled = callback(subject.tenant) inside try/except Exception -> logger.exception, enabled = (); if enabled is not None and slug not in enabled -> raise TenantToolingRefused("toolkit_unavailable", item=slug) — bounded by AC8, AC9, AC10
            return
```
**Why**: phase `build` is excluded because `studio_runtime.py:261` fails a whole agent build closed on a refusal; the host's call-time check covers use. The reason string is the existing `toolkit_unavailable`, so every downstream mapper emits the specified shape unchanged. Use the module's existing logger (grep for it; add `logging.getLogger(__name__)` only if none exists).

### `packages/ai-parrot/tests/tools/test_tooling_policy.py` (MODIFY)
```python
# AFTER — append at end of file (use the file's existing helpers/fixtures for a host toolkit entry)
class TestTenantToolkits:
    def test_enabled_slug_passes_disabled_host_slug_refused(self): ...
    def test_none_means_unrestricted(self): ...
    def test_build_phase_never_refused(self): ...
    def test_non_host_slugs_ignored(self): ...
    def test_raising_callback_fails_closed(self): ...
    def test_tenant_none_unaffected(self): ...
# FILL IN: replace each `...` with a real TenantToolingPolicy(tenant_toolkits=...) + check_tool assertion — bounded by AC8-AC10
```
**Why**: spec §4 unit list; use the real policy, never a stub.

### FILL IN checklist
- [ ] `check_tool` — allow-list branch; AC8/AC9/AC10
- [ ] `test_tooling_policy.py` — six test bodies

---

## Acceptance Criteria

- [ ] AC8, AC9, AC10 hold at the policy level
- [ ] `grep` confirms no code hashes a `TenantToolingPolicy`
- [ ] Existing `test_tooling_policy.py` tests pass unmodified
- [ ] Validation Commands pass
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_tooling_policy.py -q`

---

## Test Specification

```python
class TestTenantToolkits:
    def test_enabled_slug_passes_disabled_host_slug_refused(self): ...
    def test_raising_callback_fails_closed(self): ...
```
Pure unit tests on a real `TenantToolingPolicy`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agentstudio-ui-backend-gaps --feature-id FEAT-634`), never on `dev`.
2. Read the spec `sdd/specs/agentstudio-ui-backend-gaps.spec.md`; check every `Depends-on` task is `done` in `sdd/tasks/index/agentstudio-ui-backend-gaps.json`.
3. Verify the Codebase Contract before writing code; update it first if stale.
4. Mark `in-progress` in the index (set `started_at`), commit only that file.
5. Implement from the Blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
6. Commit only the files this task lists; close with `scripts/sdd/close_task.sh TASK-4098 agentstudio-ui-backend-gaps verified`; fill the Completion Note; commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*


## Completion Note

Implemented and merged by the orchestrator (chunk 0). Own tests pass (studio: test_agent_definition_readable + test_catalogs; tooling policy: 23 passed per coder). Merge-tier sweep red only on pre-existing environmental failures (Cython parrot.utils.types absent in worktree; studio test_byok stale vs byok.py; test_tools_catalog_shape plugins dotted_path) — none touch this feature. TASK-4097 review fix: test_llm_clients_rows_carry_models now tolerates providers whose list_models raises (commit d37ce5e27).
